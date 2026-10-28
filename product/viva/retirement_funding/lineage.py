"""Lossless source field occurrences and exact financial dependencies."""
from dataclasses import fields, is_dataclass
from viva.investment.contracts import Field, EvidenceError, ResourceLimit, encode, digest

class Pool:
    def __init__(self):
        self.anchors = []
        self.fields = []
        self.owners = []
        self.dependencies = []
        self.identities=[];self.paths=[];self.strings=[]
        self._anchors = {}; self._fields = {}; self._dependencies = {}

    def add(self, value, owner, path=''):
        found = []
        if type(value) is Field:
            anchor = (value.document, value.page, value.anchor)
            if anchor not in self._anchors:
                self._anchors[anchor] = len(self.anchors)
                self.anchors.append(list(anchor))
            key = digest(value)
            if key not in self._fields:
                self._fields[key] = len(self.fields)
                record=[self._anchors[anchor], self.string(value.value)]
                if value.raw!=value.value or value.grade!='unverified' or value.status!='accepted':record.append(self.string(value.raw))
                if value.grade!='unverified' or value.status!='accepted':record.extend([value.grade,value.status])
                self.fields.append(record)
            if owner not in self.identities:self.identities.append(owner)
            if path not in self.paths:self.paths.append(path)
            association = [self._fields[key], self.identities.index(owner), self.paths.index(path)]
            if association not in self.owners:
                self.owners.append(association)
            found.append(self.owners.index(association))
        elif is_dataclass(value):
            for member in fields(value):
                if type(value).__name__ in ('PayrollDependency','PayrollCorroboration') and member.name=='source':continue
                found.extend(self.add(getattr(value, member.name), owner, path + '/' + member.name))
        elif type(value) in (tuple, list):
            for index, item in enumerate(value):
                found.extend(self.add(item, owner, path + '/' + str(index)))
        if len({(a[0], a[1]) for a in self.anchors if a[1] is not None}) > 512:
            raise ResourceLimit('retirement source anchor bound')
        return found

    def string(self,value):
        if value not in self.strings:self.strings.append(value)
        return self.strings.index(value)

    def dependency(self, identifier, body_digest, kind, detail):
        record = {'id': identifier, 'digest': body_digest, 'kind': kind, 'detail': encode(detail)}
        key = digest(record)
        if key not in self._dependencies:
            self._dependencies[key] = len(self.dependencies); self.dependencies.append(record)
        return self._dependencies[key]

    def to_dict(self):
        columns={};dependencies=[]
        for record in self.dependencies:
            shape=tuple(sorted(record['detail']))
            name=record['kind']
            if name in columns and columns[name]!=list(shape):
                raise EvidenceError('incompatible retirement dependency detail shape')
            columns[name]=list(shape)
            dependencies.append([record['id'],record['digest'],name,[record['detail'][key] for key in shape]])
        grouped=[]
        for field,owner,path in self.owners:
            if grouped and grouped[-1][0]==owner:grouped[-1][1].append([field,path])
            else:grouped.append([owner,[[field,path]]])
        owner_shapes=[];occurrences=[]
        for owner,rows in grouped:
            shape=[path for field,path in rows]
            if shape not in owner_shapes:owner_shapes.append(shape)
            occurrences.append([owner,owner_shapes.index(shape),[field for field,path in rows]])
        kinds=sorted(columns)
        for record in dependencies:record[2]=kinds.index(record[2])
        # String atoms preserve full identifiers/digests while avoiding repeated
        # employer identities, canonical accounts and document-bearing net keys.
        atoms=[*self.strings,*(a[0] for a in self.anchors),*self.identities];extra=[]
        def atom(value):
            if value not in atoms:atoms.append(value);extra.append(value)
            return atoms.index(value)
        def compact(value,key=''):
            if type(value) is str:
                return {'j':[atom(part) for part in value.split('|')]} if key=='net_movement_key' else atom(value)
            if type(value) is int:return {'i':value}
            if type(value) is list:return [compact(item) for item in value]
            if type(value) is dict:return {'d':{key:compact(item,key) for key,item in value.items()}}
            return value
        dependencies=[[atom(identifier),atom(body_digest),kind,[compact(value,key) for key,value in zip(columns[kinds[kind]],values)]] for identifier,body_digest,kind,values in dependencies]
        return {'schema': 'retirement-source-occurrences-v2',
                'dependency_atom_layout':'strings + anchor documents + source identities + dependency_strings; integer indexes string atoms; {i:n} is literal integer; {j:[atom,...]} is exact pipe-joined text',
                'dependency_strings':extra,
                'anchor_columns': ['document', 'page', 'anchor'], 'anchors': self.anchors,
                'field_columns': ['anchor', 'normalized_value', 'raw', 'grade', 'status'], 'field_defaults':{'raw':'normalized_value','grade':'unverified','status':'accepted'}, 'fields': self.fields,
                'strings':self.strings,'source_identities':self.identities,'contract_paths':self.paths,
                'occurrence_layout':'ordered [source_identity_index,path_shape_index,[field,...]]; zip exact path shape and flatten preserves occurrence ids','path_shapes':owner_shapes, 'occurrences':occurrences,
                'dependency_columns':['id','digest','kind','detail_values'], 'dependency_kinds':kinds,'dependency_detail_columns':columns, 'dependencies':dependencies}


def decode_pool(table):
    """Restore every full field occurrence; no implied ownership or page is added."""
    if type(table) is not dict or table.get('schema')!='retirement-source-occurrences-v2' or len(table.get('fields',[]))>10000 or len(table.get('occurrences',[]))>10000:
        raise EvidenceError('closed retirement source pool required')
    expected={'schema','anchor_columns','anchors','field_columns','field_defaults','fields','strings','source_identities','contract_paths','occurrence_layout','path_shapes','occurrences','dependency_columns','dependency_kinds','dependency_detail_columns','dependencies','dependency_strings','dependency_atom_layout'}
    if type(table) is not dict or set(table)!=expected:raise EvidenceError('unknown retirement pool keys')
    if table['anchor_columns']!=['document','page','anchor'] or table['field_columns']!=['anchor','normalized_value','raw','grade','status'] or table['dependency_columns']!=['id','digest','kind','detail_values']:raise EvidenceError('retirement pool columns changed')
    if table['occurrence_layout']!='ordered [source_identity_index,path_shape_index,[field,...]]; zip exact path shape and flatten preserves occurrence ids' or table['dependency_atom_layout']!='strings + anchor documents + source identities + dependency_strings; integer indexes string atoms; {i:n} is literal integer; {j:[atom,...]} is exact pipe-joined text':raise EvidenceError('retirement pool encoding changed')
    for name in ('anchors','fields','strings','source_identities','contract_paths','path_shapes','occurrences','dependency_kinds','dependencies','dependency_strings'):
        if type(table[name]) is not list or len(table[name])>10000:raise EvidenceError('retirement pool table bound')
    strings=table['strings'];anchors=table['anchors'];identities=table['source_identities'];paths=table['contract_paths']
    from viva.investment.contracts import text
    for value in [*strings,*identities,*paths,*table['dependency_strings']]:text(value,8192,True)
    if len({(a[0],a[1]) for a in anchors if type(a) is list and len(a)==3 and a[1] is not None})>512:raise ResourceLimit('retirement source anchor bound')
    for anchor in anchors:
        if type(anchor) is not list or len(anchor)!=3:raise EvidenceError('invalid retirement source anchor')
        Field('',anchor[0],anchor[1],status='accepted' if anchor[1] is not None else 'unavailable',anchor=anchor[2])
    allowed={'retirement_plan_membership':{'occurrence','plan'},'payroll_population':{'reading_digest','reading_id'},'plan_cash':{'plan','row'},'payroll_witness':{'decomposition_event_id','decomposition_digest','net_deposit_event_id','net_deposit_digest','net_movement_key','occurrence_id','ordinal','payroll_identity','currency','corroborating_sources'},'rollover_witness':{'observation_id','local_id','ordinal','role','counterpart_account','transaction_id','transaction_digest','source_row_event_id'},'ledger_event':{'event_type','body','source'},'complete_posting_closure':{'schema','frontier','cash_event_id','cash_digest','movement_keys','effect_cash_ids','complete','postings','income','dependencies'}}
    kinds=table['dependency_kinds'];columns=table['dependency_detail_columns']
    if type(columns) is not dict or set(columns)!=set(kinds) or kinds!=sorted(set(kinds)) or any(kind not in allowed for kind in kinds):raise EvidenceError('unknown retirement dependency kind')
    for kind,keys in columns.items():
        if type(keys) is not list or any(type(key) is not str for key in keys) or keys!=sorted(set(keys)) or (allowed[kind] is not None and set(keys)!=allowed[kind]):raise EvidenceError('retirement dependency contract differs')
    def select(sequence,index):
        if type(index) is not int or not 0<=index<len(sequence):raise EvidenceError('invalid retirement pool index')
        return sequence[index]
    full=[]
    if table['field_defaults']!={'raw':'normalized_value','grade':'unverified','status':'accepted'}:
        raise EvidenceError('retirement source defaults changed')
    for record in table['fields']:
        if type(record) is not list or len(record) not in (2,3,5):raise EvidenceError('invalid retirement source field')
        location=select(anchors,record[0]);value=select(strings,record[1]);raw=select(strings,record[2]) if len(record)>2 else value
        grade,status=record[3:] if len(record)==5 else ('unverified','accepted')
        if type(location) is not list or len(location)!=3:raise EvidenceError('invalid retirement source location')
        full.append(Field(value,location[0],location[1],grade,status,location[2],raw))
    occurrences=[]
    for group in table['occurrences']:
        if type(group) is not list or len(group)!=3:raise EvidenceError('invalid retirement source group')
        owner=select(identities,group[0]);shape=select(table['path_shapes'],group[1]);members=group[2]
        if type(members) is not list or len(shape)!=len(members):raise EvidenceError('source occurrence shape differs')
        for field,path in zip(members,shape):
            occurrences.append({'field':select(full,field),'source_identity':owner,'contract_path':select(paths,path)})
    atoms=[*strings,*(a[0] for a in anchors),*identities,*table['dependency_strings']]
    def restore(value):
        if type(value) is int:return select(atoms,value)
        if type(value) is list:return [restore(item) for item in value]
        if type(value) is dict:
            if set(value)=={'i'}:
                if type(value['i']) is not int:raise EvidenceError('invalid dependency integer')
                return value['i']
            if set(value)=={'j'}:
                if type(value['j']) is not list:raise EvidenceError('invalid joined source text')
                return '|'.join(select(atoms,index) for index in value['j'])
            if set(value)=={'d'} and type(value['d']) is dict:return {key:restore(item) for key,item in value['d'].items()}
            raise EvidenceError('invalid dependency value tag')
        if type(value) is float:
            from math import isfinite
            if not isfinite(value):raise EvidenceError('nonfinite dependency literal')
            return value
        if value is not None and type(value) is not bool:raise EvidenceError('invalid dependency literal')
        return value
    dependencies=[]
    for record in table['dependencies']:
        if type(record) is not list or len(record)!=4:raise EvidenceError('invalid retirement dependency record')
        kind=select(table['dependency_kinds'],record[2]);columns=table['dependency_detail_columns'][kind]
        if len(columns)!=len(record[3]):raise EvidenceError('retirement dependency columns differ')
        dependencies.append({'id':select(atoms,record[0]),'digest':select(atoms,record[1]),'kind':kind,'detail':dict(zip(columns,(restore(value) for value in record[3])))})
    return occurrences,dependencies


def public_provenance(data,figures):
    """Validate the complete public lineage and resolve only each figure's uses."""
    from viva.investment.contracts import digest
    expected=digest({key:value for key,value in data.items() if key!='source_lineage_digest'})
    if data.get('source_lineage_digest')!=expected:
        raise EvidenceError('retirement source pool digest differs')
    occurrences,dependencies=decode_pool(data['lineage'])
    output={}
    for figure in figures:
        if figure.get('source_lineage_digest')!=expected:
            raise EvidenceError('retirement figure source digest differs')
        proof=data['figure_sources'].get(figure.get('authority_record_id'))
        if type(proof) is not dict or set(proof)!={'source_occurrence_ranges','association_id'} or proof['association_id']!=figure.get('association_id',''):
            raise EvidenceError('retirement figure relationship proof differs')
        selected=[]
        for identity in expand_ranges(proof['source_occurrence_ranges']):
            if type(identity) is not int or not 0<=identity<len(occurrences):raise EvidenceError('retirement figure field occurrence unavailable')
            field=occurrences[identity]['field']
            if field.page is not None and (field.document,field.page) not in selected:selected.append((field.document,field.page))
        if not selected or set(figure.get('record_ids',[]))!={document for document,page in selected}:raise EvidenceError('retirement figure source records differ')
        output[figure['id']]=[{'document_id':document,'page':page} for document,page in selected]
    return output


def index_ranges(indices):
    """Closed inclusive ranges preserve the exact ordered distinct uses."""
    out=[]
    for index in sorted(set(indices)):
        if type(index) is not int or index<0:raise EvidenceError('invalid source occurrence')
        if out and index==out[-1][1]+1:out[-1][1]=index
        else:out.append([index,index])
    return out

def expand_ranges(ranges):
    if type(ranges) is not list or len(ranges)>10000:raise EvidenceError('invalid occurrence ranges')
    out=[]
    for pair in ranges:
        if type(pair) is not list or len(pair)!=2 or any(type(v) is not int for v in pair) or not 0<=pair[0]<=pair[1]<10000 or (out and pair[0]<=out[-1]+1):raise EvidenceError('noncanonical occurrence ranges')
        out.extend(range(pair[0],pair[1]+1))
    return out
