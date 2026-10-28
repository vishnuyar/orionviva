"""Lossless readable source tables with explicit locally scoped aliases.

The closed tables retain full source identities. A source field's owner path
is a local accepted-contract path, never a fabricated physical source anchor.
"""
from .contracts import EvidenceError,digest,Field
from dataclasses import fields as dataclass_fields,is_dataclass
import json


def pool(result):
 fields=result['source_fields'];field_order=sorted(fields,key=lambda key:(fields[key]['document'],fields[key]['page'] or 0,fields[key]['anchor'],tuple(tuple(owner) for owner in sorted(fields[key]['owners'])),key));identities={key:i for i,key in enumerate(field_order)}
 anchors={key:'a'+str(i) for i,key in enumerate(sorted(result['anchors']))}
 result['anchors']={anchors[key]:value for key,value in result['anchors'].items()}
 unavailable={digest({name:record[name] for name in ('document','page','anchor')}):{name:record[name] for name in ('document','page','anchor')} for record in fields.values() if record['page'] is None}
 locations={key:'u'+str(i) for i,key in enumerate(sorted(unavailable))}
 anchors.update(locations)
 unavailable_locations={locations[key]:value for key,value in unavailable.items()}
 observations=sorted({identity for figure in result['figures'] for identity in figure['observation_ids']})
 rows=sorted({identity for figure in result['figures'] for identity in figure['row_ids']}|{operand['row'] for figure in result['figures'] for operand in figure['operands']})
 observation_alias={value:'o'+str(i) for i,value in enumerate(observations)}
 row_alias={value:'r'+str(i) for i,value in enumerate(rows)}
 result['source_identities']={'schema':'investment-source-identities-v1','observations':{alias:identity for identity,alias in observation_alias.items()},'rows':{alias:identity for identity,alias in row_alias.items()}}
 texts=[];indexes={}
 def text(value):
  if value not in indexes:indexes[value]=len(texts);texts.append(value)
  return indexes[value]
 anchor_owners={alias:[] for alias in (*result['anchors'],*unavailable_locations)}
 for record in fields.values():
  anchor_alias=anchors[digest({name:record[name] for name in ('document','page','anchor')})]
  anchor_owners[anchor_alias]=sorted(set(anchor_owners[anchor_alias])|{observation_alias[owner] for owner,path in record['owners']})
 records=[]
 for identity in field_order:
  record=fields[identity]
  anchor_alias=anchors[digest({name:record[name] for name in ('document','page','anchor')})]
  owners=[]
  for owner,path in record['owners']:
   owner_index=anchor_owners[anchor_alias].index(observation_alias[owner]);path_index=text(path)
   owners.append(path_index if owner_index==0 else [owner_index,path_index])
  cells=[anchor_alias,text(record['value']),owners]
  if record['raw']!=record['value'] or record['grade']!='unverified' or record['status']!='accepted':cells.append(text(record['raw']))
  if record['grade']!='unverified' or record['status']!='accepted':cells.extend([record['grade'],record['status']])
  records.append(cells)
 result['source_fields']={'schema':'investment-source-fields-v2','columns':['anchor_id','value_string','owners','raw_string','grade','status'],'defaults':{'raw_string':'value_string','grade':'unverified','status':'accepted'},'owner_encoding':'path_string_index or [anchor_owner_index,path_string_index]; omitted owner index is zero','anchor_owners':anchor_owners,'unavailable_locations':unavailable_locations,'strings':texts,'records':records}
 # Equal membership groups retain every reference once, including scope fields
 # shared by all totals; no range, aggregate or omitted-field inference occurs.
 membership={}
 for i,figure in enumerate(result['figures']):
  for use in figure['source_field_uses']:membership.setdefault(tuple(use),[]).append(i)
 groups={}
 for (key,owner,path),members in sorted(membership.items()):
  owner_index=fields[key]['owners'].index([owner,path]);identity=identities[key]
  groups.setdefault(tuple(members),[]).append(identity if owner_index==0 else [identity,owner_index])
 result['source_field_groups']={'g'+str(i):values for i,values in enumerate(groups.values())}
 group_members={members:'g'+str(i) for i,members in enumerate(groups)}
 for i,figure in enumerate(result['figures']):
  del figure['source_field_ids'];del figure['source_field_uses']
  figure['source_field_groups']=[alias for members,alias in group_members.items() if i in members]
  figure['anchor_ids']=[anchors[key] for key in figure['anchor_ids']]
  figure['observation_ids']=[observation_alias[key] for key in figure['observation_ids']]
  figure['row_ids']=[row_alias[key] for key in figure['row_ids']]
  for operand in figure['operands']:
   operand['row']=row_alias[operand['row']]
   operand['anchor_ids']=[anchors[key] for key in operand['anchor_ids']]
 used_dependencies={key for figure in result['figures'] for key in figure['funding_dependency_ids']}
 result['funding_dependencies']={key:value for key,value in result['funding_dependencies'].items() if key in used_dependencies}
 dependency_ids={identity:'d'+str(i) for i,identity in enumerate(sorted(result['funding_dependencies']))}
 dependency_records={}
 for identity,proof in sorted(result['funding_dependencies'].items()):
  dependency_records[dependency_ids[identity]]={'observation_id':observation_alias[proof['observation_id']],'row_id':row_alias[proof['row_id']],'scalars':[[text(path),{'integer':value} if type(value) is int else text(value)] for path,value in sorted(proof['scalars'].items())]}
 # Reuse the same explicit text pool for source fields and dependency paths/IDs.
 shapes={};columns={};compact_dependencies={}
 for key,record in dependency_records.items():
  shape=tuple(pair[0] for pair in record['scalars'])
  if shape not in shapes:shapes[shape]='c'+str(len(shapes));columns[shapes[shape]]=list(shape)
  compact_dependencies[key]=[record['observation_id'],record['row_id'],shapes[shape],[pair[1] for pair in record['scalars']]]
 result['funding_dependencies']={'schema':'investment-funding-dependencies-v1','strings':'source_fields.strings','record_columns':['observation_id','row_id','scalar_columns','scalar_values'],'scalar_columns':columns,'records':compact_dependencies}
 # Group exact field rows under their common physical/non-page location once.
 # Flattening these groups in their written order restores every original ID.
 grouped=[]
 for row in result['source_fields']['records']:
  owner=row[2][0] if len(row[2])==1 else {'multiple':row[2]}
  record=[row[1],owner,*row[3:]]
  if grouped and grouped[-1][0]==row[0]:grouped[-1][1].append(record)
  else:grouped.append([row[0],[record]])
 owner_shapes={};owner_columns={};shaped=[]
 for location,rows in grouped:
  pattern=json.dumps([row[1] for row in rows],separators=(',',':'))
  if pattern not in owner_shapes:owner_shapes[pattern]='p'+str(len(owner_shapes));owner_columns[owner_shapes[pattern]]=[row[1] for row in rows]
  shaped.append([location,owner_shapes[pattern],[[row[0],*row[2:]] for row in rows]])
 result['source_fields']['records']=shaped
 result['source_fields']['owner_shapes']=owner_columns
 result['anchor_defaults']={'page':1,'anchor':''}
 result['anchors']={key:{name:value for name,value in location.items() if name not in result['anchor_defaults'] or value!=result['anchor_defaults'][name]} for key,location in result['anchors'].items()}
 result['source_fields']['record_layout']='ordered [location,owner_shape,rows] groups; flatten preserves field IDs; owners are supplied exactly once per shape'
 result['source_fields']['path_prefixes']=factor_prefixes(texts)
 document_anchors={}
 for key,location in result['anchors'].items():document_anchors.setdefault(location['document'],key)
 for i,value in enumerate(texts):
  if type(value) is str and value in document_anchors:texts[i]={'document_at':document_anchors[value]}
 for location in result['source_fields']['unavailable_locations'].values():
  if location['document'] in document_anchors:location['document_at']=document_anchors[location.pop('document')]
 for figure in result['figures']:figure['funding_dependency_ids']=[dependency_ids[key] for key in figure['funding_dependency_ids']]
 return result


def dependency_scalars(value,path=''):
 """All non-Field witness values; Fields retain their explicit owner paths."""
 if type(value) is Field or value is None:return {}
 if is_dataclass(value):return {key:item for member in dataclass_fields(value) for key,item in dependency_scalars(getattr(value,member.name),path+'/'+member.name).items()}
 if type(value) in (tuple,list):return {key:item for i,item in enumerate(value) for key,item in dependency_scalars(item,path+'/'+str(i)).items()}
 if type(value) not in (str,int):raise EvidenceError('unsupported funding dependency scalar')
 return {path:value}


def expand_dependencies(result):
 table=result['funding_dependencies'];texts=result['source_fields']['strings'];identities=result['source_identities']
 if type(table) is not dict or set(table)!={'schema','strings','records','record_columns','scalar_columns'} or table['schema']!='investment-funding-dependencies-v1' or table['strings']!='source_fields.strings' or type(table['records']) is not dict:raise EvidenceError('invalid funding dependency table')
 def string(index):
  if type(index) is not int or not 0<=index<len(texts):raise EvidenceError('invalid dependency string reference')
  return source_string(result['source_fields'],index,result['anchors'])
 output={}
 if table['record_columns']!=['observation_id','row_id','scalar_columns','scalar_values'] or type(table['scalar_columns']) is not dict:raise EvidenceError('invalid funding dependency columns')
 for key,row in table['records'].items():
  if type(row) is not list or len(row)!=4 or row[2] not in table['scalar_columns'] or type(row[3]) is not list:raise EvidenceError('invalid funding dependency row')
  columns=table['scalar_columns'][row[2]]
  if type(columns) is not list or len(columns)!=len(row[3]):raise EvidenceError('invalid funding dependency scalar shape')
  record={'observation_id':row[0],'row_id':row[1],'scalars':[[path,value] for path,value in zip(columns,row[3])]}
  if type(key) is not str or not key.startswith('d') or type(record) is not dict or set(record)!={'observation_id','row_id','scalars'} or record['observation_id'] not in identities['observations'] or record['row_id'] not in identities['rows'] or type(record['scalars']) is not list:raise EvidenceError('invalid funding dependency record')
  scalars={}
  for pair in record['scalars']:
   if type(pair) is not list or len(pair)!=2:raise EvidenceError('invalid funding dependency scalar')
   path=string(pair[0]);value=pair[1]
   if path in scalars or not path.startswith('/'):raise EvidenceError('invalid funding dependency path')
   if type(value) is dict:
    if set(value)!={'integer'} or type(value['integer']) is not int:raise EvidenceError('invalid funding dependency integer')
    value=value['integer']
   else:value=string(value)
   scalars[path]=value
  output[key]={'observation_id':identities['observations'][record['observation_id']],'row_id':identities['rows'][record['row_id']],'scalars':scalars}
 return output


def expand_fields(result):
 table=result['source_fields']
 if type(table) is not dict or set(table)!={'schema','columns','defaults','owner_encoding','anchor_owners','unavailable_locations','strings','records','record_layout','path_prefixes','owner_shapes'} or table['schema']!='investment-source-fields-v2' or table['columns']!=['anchor_id','value_string','owners','raw_string','grade','status'] or table['defaults']!={'raw_string':'value_string','grade':'unverified','status':'accepted'} or table['owner_encoding']!='path_string_index or [anchor_owner_index,path_string_index]; omitted owner index is zero':raise EvidenceError('invalid source field table')
 texts=table['strings'];groups=table['records']
 if table['record_layout']!='ordered [location,owner_shape,rows] groups; flatten preserves field IDs; owners are supplied exactly once per shape' or type(texts) is not list or type(groups) is not list:raise EvidenceError('invalid source field strings')
 records=[]
 for group in groups:
  if type(group) is not list or len(group)!=3 or type(group[0]) is not str or group[1] not in table['owner_shapes'] or type(group[2]) is not list or not group[2]:raise EvidenceError('invalid source field location group')
  owners_for_group=table['owner_shapes'][group[1]]
  if type(owners_for_group) is not list or len(owners_for_group)!=len(group[2]):raise EvidenceError('invalid source owner shape')
  for row,owner in zip(group[2],owners_for_group):
   if type(row) is not list or len(row) not in (1,2,4):raise EvidenceError('invalid grouped source field')
   if type(owner) is dict:
    if set(owner)!={'multiple'} or type(owner['multiple']) is not list or len(owner['multiple'])<2:raise EvidenceError('invalid source field owners')
    owners=owner['multiple']
   else:owners=[owner]
   records.append([group[0],row[0],owners,*row[1:]])
 def string(index):
  if type(index) is not int or not 0<=index<len(texts):raise EvidenceError('invalid source string reference')
  return source_string(table,index,result['anchors'])
 locations=table['unavailable_locations']
 if type(locations) is not dict:raise EvidenceError('invalid unavailable source locations')
 expanded_locations={}
 for key,value in locations.items():
  if type(key) is not str or not key.startswith('u') or type(value) is not dict or set(value) not in ({'document','page','anchor'},{'document_at','page','anchor'}) or value['page'] is not None:raise EvidenceError('invalid unavailable source locations')
  value=dict(value)
  if 'document_at' in value:
   anchor_id=value.pop('document_at')
   if anchor_id not in result['anchors']:raise EvidenceError('unavailable document reference missing')
   value['document']=result['anchors'][anchor_id]['document']
  expanded_locations[key]=value
 locations={**expand_anchors(result),**expanded_locations}
 out={}
 for identity,row in enumerate(records):
  if type(row) is not list or len(row) not in (3,4,6) or row[0] not in locations:raise EvidenceError('invalid source field reference')
  anchor=locations[row[0]];owners=[]
  for item in row[2]:
   owner_index,path=(0,item) if type(item) is int else item
   if type(owner_index) is not int or not 0<=owner_index<len(table['anchor_owners'][row[0]]):raise EvidenceError('invalid source field owner')
   owner=table['anchor_owners'][row[0]][owner_index]
   if owner not in result['source_identities']['observations']:raise EvidenceError('invalid source field owner')
   owners.append([result['source_identities']['observations'][owner],string(path)])
  out[identity]={'value':string(row[1]),'raw':string(row[3] if len(row)>3 else row[1]),**anchor,'grade':row[4] if len(row)==6 else 'unverified','status':row[5] if len(row)==6 else 'accepted','owners':owners}
 return out


def figure_field_uses(result,figure):
 groups=result['source_field_groups'];uses=[];expanded=expand_fields(result)
 for key in figure['source_field_groups']:
  if key not in groups:raise EvidenceError('invalid source field group')
  for reference in groups[key]:
   identity,owner_index=(reference,0) if type(reference) is int else reference
   if type(identity) is not int or identity not in expanded or type(owner_index) is not int or not 0<=owner_index<len(expanded[identity]['owners']):raise EvidenceError('invalid source field occurrence')
   uses.append((identity,owner_index))
 if len(set(uses))!=len(uses):raise EvidenceError('duplicate source field occurrence')
 return uses


def figure_field_ids(result,figure):
 return sorted({identity for identity,owner in figure_field_uses(result,figure)})


def lineage_digest(data):
 return digest({key:data[key] for key in ('view','account','currency','revision','coverage','dispositions','anchor_defaults','anchors','source_fields','source_field_groups','source_identities','funding_dependencies','figure_source_columns','figure_sources')})


def validate_result(result):
 """Reconstruct every used field and check all locally scoped references."""
 from .contracts import Field
 expanded=expand_fields(result)
 dependencies=expand_dependencies(result)
 for record in expanded.values():
  Field(**{key:value for key,value in record.items() if key!='owners'})
  if not record['owners']:raise EvidenceError('source field owner missing')
 observations=result['source_identities']['observations'];rows=result['source_identities']['rows']
 for figure in result['figures']:
  identities=figure_field_ids(result,figure)
  for dependency_id in figure['funding_dependency_ids']:
   if dependency_id not in dependencies or dependencies[dependency_id]['row_id'] not in {rows[key] for key in figure['row_ids']} or dependencies[dependency_id]['observation_id'] not in {observations[key] for key in figure['observation_ids']}:raise EvidenceError('funding dependency outside figure')
  if not identities:raise EvidenceError('source figure fields missing')
  if any(key not in observations for key in figure['observation_ids']) or any(key not in rows for key in figure['row_ids']):raise EvidenceError('source figure identity missing')
  if any(key not in result['anchors'] for key in figure['anchor_ids']):raise EvidenceError('source figure page missing')
  selected={expand_anchors(result)[key]['document'] for key in figure['anchor_ids']}
  if any(expanded[key]['document'] not in selected for key in identities):raise EvidenceError('source field document outside figure')
  for operand in figure['operands']:
   if operand['row'] not in rows or any(key not in figure['anchor_ids'] for key in operand['anchor_ids']):raise EvidenceError('source operand identity missing')
 return expanded


def factor_prefixes(strings):
 """Readable shared slash/colon prefixes; no shortening of source identities."""
 available=set(range(len(strings)));prefixes=[]
 while True:
  candidates={}
  for i in available:
   value=strings[i]
   for j,char in enumerate(value):
    if char in '/:' and j>=8:candidates.setdefault(value[:j+1],[]).append(i)
  scored=[(sum(len(prefix)-5 for i in members)-len(prefix)-3,prefix,members) for prefix,members in candidates.items() if len(members)>=3]
  if not scored:break
  saving,prefix,members=max(scored,key=lambda item:(item[0],item[1]))
  if saving<=0:break
  index=len(prefixes);prefixes.append(prefix)
  for i in members:strings[i]=[index,strings[i][len(prefix):]];available.remove(i)
 return prefixes


def source_string(table,index,anchors):
 texts=table['strings'];prefixes=table['path_prefixes']
 if type(index) is not int or not 0<=index<len(texts) or type(prefixes) is not list or any(type(prefix) is not str or not prefix for prefix in prefixes):raise EvidenceError('invalid pooled source string')
 value=texts[index]
 if type(value) is str:return value
 if type(value) is dict:
  if set(value)!={'document_at'} or value['document_at'] not in anchors:raise EvidenceError('invalid pooled document reference')
  return anchors[value['document_at']]['document']
 if type(value) is not list or len(value)!=2 or type(value[0]) is not int or not 0<=value[0]<len(prefixes) or type(value[1]) is not str:raise EvidenceError('invalid source prefix reference')
 return prefixes[value[0]]+value[1]


def expand_figure_sources(data):
 columns=['anchor_ids','source_field_groups','observation_ids','row_ids','funding_roles','funding_dependency_ids','operands']
 if data.get('figure_source_columns')!=columns or type(data.get('figure_sources')) is not dict:raise EvidenceError('invalid figure source columns')
 result={}
 for key,values in data['figure_sources'].items():
  if type(key) is not str or type(values) is not list or len(values)!=len(columns):raise EvidenceError('invalid figure source row')
  result[key]={'authority_record_id':key,**dict(zip(columns,values))}
 return result


def expand_public_provenance(wire):
 """Decode the closed investment-only public reference without source loss."""
 if wire.get('provenance')!=[{'source_anchor_pool':'data.anchors'}]:raise EvidenceError('invalid investment public provenance reference')
 anchors=expand_anchors(wire.get('data',{}))
 if type(anchors) is not dict:raise EvidenceError('investment source anchors missing')
 output=[]
 for key,value in sorted(anchors.items()):
  if type(key) is not str or type(value) is not dict or set(value)!={'document','page','anchor'}:raise EvidenceError('invalid investment source anchor')
  Field('',value['document'],value['page'],anchor=value['anchor'])
  output.append({'doc_id':value['document'],'page':value['page']})
 return output


def expand_anchors(data):
 defaults=data.get('anchor_defaults')
 if defaults!={'page':1,'anchor':''} or type(data.get('anchors')) is not dict:raise EvidenceError('invalid source anchor defaults')
 output={}
 for key,value in data['anchors'].items():
  if type(key) is not str or type(value) is not dict or 'document' not in value or not set(value)<= {'document','page','anchor'}:raise EvidenceError('invalid compact source anchor')
  value={**defaults,**value}
  Field('',value['document'],value['page'],anchor=value['anchor'])
  output[key]=value
 return output
