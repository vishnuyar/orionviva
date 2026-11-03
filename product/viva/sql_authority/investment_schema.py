"""Closed native investment rows and indexes, including immutable cash history."""
from datetime import date
from decimal import InvalidOperation
import hashlib
import json

TABLES = {
    'investment_facts': ('doc_id','currency','as_of','body','context_id','source_kind','created_revision'),
    'investment_components': ('doc_id','account_id','snapshot_state','activity_state','source_state','reason','snapshot_id','group_id','basis_id','revision'),
    'investment_snapshots': ('snapshot_id','doc_id','account_id','currency','as_of','cash','total','position_count','signature','created_revision'),
    'investment_positions': ('snapshot_id','ordinal','security_id','instrument','units','market_value','cost_basis','page','source_state'),
    'investment_cash_inputs': ('doc_id','period_start','period_end','printed_opening','closing','explicit_empty'),
    'investment_rows': ('doc_id','ordinal','date','kind','amount','description','instrument','realized_gain','page','source_event_id','row_signature','source_state'),
    'investment_bases': ('basis_id','doc_id','opening','opening_kind','period_start','start_kind','seed_group','predecessor_snapshot','prior_basis','created_revision','known_operation','source_header_digest'),
    'investment_groups': ('group_id','account_id','currency','period_start','period_end','opening','closing','signature','origin_doc','created_revision'),
    'investment_witnesses': ('doc_id','group_id','basis_id'),
    'investment_effects': ('effect_id','group_id','occurrence_rank','row_signature','date','kind','amount','instrument','realized_gain','owner_doc','owner_ordinal'),
    'investment_legs': ('effect_id','leg','account_id','amount','currency','grade','doc_id','page'),
    'investment_decisions': ('ordinal','group_id','action','basis_id','previous_ordinal','revision','boundary'),
    'investment_active': ('group_id','active','decision_ordinal','basis_id','revision'),
    'investment_adjustments': ('decision_ordinal','effect_id','leg','account_id','amount','currency','grade','doc_id','page','date'),
    'investment_dependencies': ('doc_id','signal_kind','signal','currency','account_id','active'),
    'investment_fields': ('doc_id','scope','ordinal','name','raw','page','value','status','grade','reason'),
}
KEYS = {name: columns[:1] for name, columns in TABLES.items()}
KEYS.update(investment_positions=('snapshot_id','ordinal'), investment_rows=('doc_id','ordinal'),
            investment_witnesses=('doc_id','group_id','basis_id'), investment_legs=('effect_id','leg'),
            investment_adjustments=('decision_ordinal','effect_id','leg'),
            investment_dependencies=('doc_id','signal_kind','signal'),
            investment_fields=('doc_id','scope','ordinal','name'))
MUTABLE = frozenset({'investment_components','investment_active','investment_dependencies'})
_NULLS = {
    'investment_components': {'account_id','snapshot_id','group_id','basis_id'},
    'investment_positions': {'cost_basis','page'},
    'investment_cash_inputs': {'period_start','printed_opening'},
    'investment_rows': {'realized_gain','page','source_event_id'},
    'investment_bases': {'period_start','seed_group','predecessor_snapshot','prior_basis'},
    'investment_groups': {'period_start'}, 'investment_effects': {'realized_gain'},
    'investment_legs': {'page'}, 'investment_decisions': {'previous_ordinal'},
    'investment_active': {'basis_id'}, 'investment_adjustments': {'page'},
    'investment_dependencies': {'account_id'}, 'investment_fields': {'raw','page','value'},
}
_INTS = {'ordinal','leg','occurrence_rank','owner_ordinal','position_count','created_revision',
         'known_operation','revision','decision_ordinal','previous_ordinal','active','page'}
_DIGESTS = {'doc_id','context_id','snapshot_id','security_id','group_id','basis_id','seed_group',
            'predecessor_snapshot','prior_basis','source_header_digest','effect_id','owner_doc','origin_doc'}
_NUMBERS = {'cash','total','units','market_value','cost_basis','printed_opening','closing','opening','amount','realized_gain'}
_JSON = {'body','signature','row_signature','boundary'}
_DATES = {'as_of','date','period_start','period_end'}
_KINDS = {'contribution','withdrawal','dividend','interest','fee','buy','sell'}
_STATES = {'accepted','held','unavailable','conflicted'}
_REASONS = {'invalid_investment_observation','snapshot_arithmetic','population_identity_requires_review','source_value_conflict','invalid_activity','source_activity_conflict','empty_activity_unproved','opening_source_unavailable','seed_unavailable','carry_unavailable','activity_arithmetic','period_conflict','basis_unavailable','missing_source','invalid_page','unreadable_source','unsupported_field','source_disagrees','','identity_requires_review','source_unavailable','source_conflict','snapshot_conflict',
            'snapshot_requires_review','cash_requires_review','cash_conflict','opening_requires_review',
            'activity_requires_review','resource_limit','economic_duplicate','funding_unavailable'}

# Deferred references close the genuine group/basis cycle at the actual commit.
_REFS = {
    'investment_facts': {'doc_id':'interpretations(doc_id)','context_id':'read_contexts(context_id)'},
    'investment_components': {'doc_id':'investment_facts(doc_id)','account_id':'accounts(account_id)',
        'snapshot_id':'investment_snapshots(snapshot_id)','group_id':'investment_groups(group_id)','basis_id':'investment_bases(basis_id)'},
    'investment_snapshots': {'doc_id':'investment_facts(doc_id)','account_id':'accounts(account_id)'},
    'investment_positions': {'snapshot_id':'investment_snapshots(snapshot_id)'},
    'investment_cash_inputs': {'doc_id':'investment_facts(doc_id)'},
    'investment_rows': {'doc_id':'investment_facts(doc_id)'},
    'investment_bases': {'doc_id':'investment_facts(doc_id)','seed_group':'investment_groups(group_id)',
        'predecessor_snapshot':'investment_snapshots(snapshot_id)','prior_basis':'investment_bases(basis_id)'},
    'investment_groups': {'account_id':'accounts(account_id)','origin_doc':'investment_facts(doc_id)'},
    'investment_witnesses': {'doc_id':'investment_facts(doc_id)','group_id':'investment_groups(group_id)','basis_id':'investment_bases(basis_id)'},
    'investment_effects': {'group_id':'investment_groups(group_id)','owner_doc':'investment_facts(doc_id)'},
    'investment_legs': {'effect_id':'investment_effects(effect_id)','doc_id':'investment_facts(doc_id)'},
    'investment_decisions': {'group_id':'investment_groups(group_id)','basis_id':'investment_bases(basis_id)',
        'previous_ordinal':'investment_decisions(ordinal)'},
    'investment_active': {'group_id':'investment_groups(group_id)','decision_ordinal':'investment_decisions(ordinal)','basis_id':'investment_bases(basis_id)'},
    'investment_adjustments': {'decision_ordinal':'investment_decisions(ordinal)','effect_id':'investment_effects(effect_id)','doc_id':'investment_facts(doc_id)'},
    'investment_dependencies': {'doc_id':'investment_facts(doc_id)','account_id':'accounts(account_id)'},
    'investment_fields': {'doc_id':'investment_facts(doc_id)'},
}

def _ddl():
    statements = []
    for table, columns in TABLES.items():
        definitions = []
        for column in columns:
            kind = 'INTEGER' if column in _INTS else 'TEXT'
            null = '' if column in _NULLS.get(table, ()) else ' NOT NULL'
            reference = _REFS.get(table, {}).get(column)
            foreign = ' REFERENCES ' + reference + ' DEFERRABLE INITIALLY DEFERRED' if reference else ''
            definitions.append(column + ' ' + kind + null + foreign)
        definitions.append('PRIMARY KEY(' + ','.join(KEYS[table]) + ')')
        if table == 'investment_snapshots':
            definitions.append('UNIQUE(doc_id)')
        if table == 'investment_effects':
            definitions.append('FOREIGN KEY(owner_doc,owner_ordinal) REFERENCES investment_rows(doc_id,ordinal) DEFERRABLE INITIALLY DEFERRED')
        statements.append('CREATE TABLE ' + table + '(' + ','.join(definitions) + ');')
    statements.extend([
        'CREATE INDEX investment_facts_date ON investment_facts(currency,as_of,doc_id);',
        'CREATE INDEX investment_position_security ON investment_positions(snapshot_id,security_id,ordinal);',
        'CREATE INDEX investment_cash_end ON investment_cash_inputs(period_end,doc_id);',
        'CREATE INDEX investment_active_state ON investment_active(active,group_id);',
        'CREATE INDEX investment_dependency_account ON investment_dependencies(account_id,active,doc_id);',
        'CREATE INDEX investment_snapshot_account ON investment_snapshots(account_id,as_of,created_revision,doc_id);',
        'CREATE INDEX investment_component_account ON investment_components(account_id,doc_id);',
        'CREATE INDEX investment_group_bucket ON investment_groups(account_id,period_end,group_id);',
        'CREATE INDEX investment_witness_group ON investment_witnesses(group_id,doc_id,basis_id);',
        'CREATE INDEX investment_basis_doc ON investment_bases(doc_id,created_revision,known_operation,basis_id);',
        'CREATE INDEX investment_basis_seed ON investment_bases(seed_group,doc_id);',
        'CREATE INDEX investment_basis_predecessor ON investment_bases(predecessor_snapshot,doc_id);',
        'CREATE INDEX investment_effect_group ON investment_effects(group_id,row_signature,occurrence_rank);',
        'CREATE INDEX investment_decision_group ON investment_decisions(group_id,ordinal);',
        'CREATE INDEX investment_adjustment_doc ON investment_adjustments(doc_id,date,decision_ordinal,effect_id,leg);',
        'CREATE INDEX investment_dependency_signal ON investment_dependencies(signal_kind,signal,active,doc_id);',
    ])
    return '\n'.join(statements) + '\n'

DDL = _ddl()


def _canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)


def _tag(value, validator):
    return (type(value) is list and len(value) == 2 and type(value[0]) is str
            and value[0] in {'accepted','unavailable','conflicted'}
            and (validator(value[1]) if value[0] == 'accepted' else value[1] is None))


def _date(value):
    try:
        return type(value) is str and date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False


def valid_row_signature(body):
    from .investment_numbers import valid_key
    names = {'date','kind','amount','instrument','signedgain','funding_role','reported_role_source',
             'funding_reference','counterpart_reference','printed_row_reference','namespace'}
    return (type(body) is dict and set(body) == names and _date(body['date'])
            and body['kind'] in _KINDS and valid_key(body['amount']) and body['amount'][0] == 0
            and body['amount'][1] != '0' and body['funding_role'] == 'unknown'
            and _tag(body['signedgain'], valid_key)
            and all(_tag(body[k],lambda x: type(x) is str and bool(x)) for k in names - {'date','kind','amount','funding_role','signedgain'}))


def valid_row(table, row):
    from .investment_numbers import scalar, valid_key
    if type(row) is not dict or set(row) != set(TABLES[table]):
        return False
    parsed = {}
    try:
        for name, value in row.items():
            if value is None:
                if name not in _NULLS.get(table, ()):
                    return False
                continue
            if name in _INTS:
                low = 0 if name in {'ordinal','leg','occurrence_rank','owner_ordinal','position_count','known_operation','active'} else 1
                if table == 'investment_decisions' and name == 'ordinal':
                    low = 1
                if table == 'investment_fields' and name == 'ordinal':
                    low = -1 if row['scope'] == 'header' else 0
                high = 1 if name == 'active' else 200 if name == 'page' else 2**63-1
                if type(value) is not int or not low <= value <= high:
                    return False
                continue
            if type(value) is not str or len(value.encode()) > (8*1024*1024 if name in _JSON else 16384):
                return False
            if any(ord(c) < 32 or ord(c) == 127 for c in value):
                return False
            if name in _DIGESTS and (len(value) != 64 or any(c not in '0123456789abcdef' for c in value)):
                return False
            if name in _DATES and not _date(value):
                return False
            if name == 'currency' and (len(value) != 3 or not value.isascii() or not value.isupper() or not value.isalpha()):
                return False
            if name in _NUMBERS:
                scalar(value)
            if name in _JSON:
                parsed[name] = json.loads(value)
                if _canonical(parsed[name]) != value:
                    return False
        if 'source_kind' in row and row['source_kind'] not in {'typed','curated'}:
            return False
        if 'kind' in row and row['kind'] not in _KINDS:
            return False
        if 'source_state' in row and row['source_state'] not in _STATES:
            return False
        if table == 'investment_components':
            if any(row[k] not in _STATES for k in ('snapshot_state','activity_state','source_state')) or row['reason'] not in _REASONS:
                return False
        if table == 'investment_fields':
            from ..investment.extraction import HEADERS, POSITION, ROW
            names = {'header': HEADERS,'position': POSITION,'activity': ROW}
            if row['scope'] not in names or row['name'] not in names[row['scope']]:
                return False
            if row['scope'] == 'header' and row['ordinal'] != -1:
                return False
            if row['reason'] not in {'','missing_source','invalid_page','unreadable_source','unsupported_field','source_disagrees'} or row['status'] not in _STATES or row['grade'] not in {'unverified','corroborated','verified','conflicted'}:
                return False
        if table == 'investment_fields' and ((row['status'] in {'unavailable','conflicted'}) != (row['value'] is None)):
            return False
        if table in {'investment_legs','investment_adjustments'} and row['grade'] not in {'verified','unverified','corroborated','conflicted'}:
            return False
        if table == 'investment_cash_inputs' and row['explicit_empty'] not in {'true','false','unavailable'}:
            return False
        if table == 'investment_bases':
            if row['opening_kind'] not in {'printed','carried'} or row['start_kind'] not in {'printed','derived','unavailable'}:
                return False
            body = ['sql-investment-basis-v1',row['doc_id'],key_for(row['opening']),row['opening_kind'],row['period_start'],row['start_kind'],row['seed_group'],row['predecessor_snapshot'],row['prior_basis'],row['created_revision'],row['known_operation'],row['source_header_digest']]
            if row['basis_id'] != hashlib.sha256(_canonical(body).encode()).hexdigest():
                return False
        if table == 'investment_snapshots':
            body=parsed['signature']
            names={'version','logical_account','currency','as_of','cash','total','positions'}
            if type(body) is not dict or set(body)!=names or type(body['version']) is not int or body['version']!=1 or body['logical_account']!=row['account_id'] or body['currency']!=row['currency'] or body['as_of']!=row['as_of'] or body['cash']!=key_for(row['cash']) or body['total']!=key_for(row['total']) or type(body['positions']) is not list:
                return False
            if any(type(p) is not list or len(p)!=2 or type(p[0]) is not str or not p[0] or not valid_key(p[1]) for p in body['positions']) or body['positions']!=sorted(body['positions'],key=_canonical):
                return False
            if row['snapshot_id']!=hashlib.sha256(_canonical(['sql-investment-snapshot-v1',row['doc_id']]).encode()).hexdigest():
                return False
        if table == 'investment_effects':
            expected=['sql-investment-effect-v1',row['group_id'],row['row_signature'],row['occurrence_rank']]
            if row['effect_id']!=hashlib.sha256(_canonical(expected).encode()).hexdigest():
                return False
        if table == 'investment_decisions':
            if row['action'] not in {'activate','deactivate','rebind'}:
                return False
            boundary = parsed['boundary']
            if type(boundary) is not dict or set(boundary) != {'version','causes'} or type(boundary['version']) is not int or boundary['version'] != 1 or type(boundary['causes']) is not list or not boundary['causes']:
                return False
            serialized = []
            for cause in boundary['causes']:
                if type(cause) is not dict or set(cause) != {'table','key','source_doc_id'} or cause['table'] not in {'interpretations','accounts','account_keys','holder_index','reference_claims','reference_views','identity_decisions'}:
                    return False
                from .schema import KEYS as all_keys
                if type(cause['key']) is not list or len(cause['key']) != len(all_keys[cause['table']]) or any(type(v) not in {str,int} for v in cause['key']):
                    return False
                if type(cause['source_doc_id']) is not str or len(cause['source_doc_id']) != 64 or any(c not in '0123456789abcdef' for c in cause['source_doc_id']):
                    return False
                serialized.append(_canonical(cause))
            if serialized != sorted(set(serialized)):
                return False
        if table == 'investment_active' and (row['active'] == 0) != (row['basis_id'] is None):
            return False
        if table == 'investment_dependencies' and row['signal_kind'] not in {'preferred','holder','reference','number'}:
            return False
        if table in {'investment_rows','investment_effects'} and not valid_row_signature(parsed['row_signature']):
            return False
        if table == 'investment_groups':
            body = parsed['signature']
            names = {'version','logical_account','currency','start','end','opening','closing','disposition','explicit_empty','rows'}
            if type(body) is not dict or set(body) != names or type(body['version']) is not int or body['version'] != 1:
                return False
            if (body['logical_account'] != row['account_id'] or body['currency'] != row['currency'] or body['end'] != row['period_end']
                    or body['opening'] != key_for(row['opening']) or body['closing'] != key_for(row['closing'])
                    or not _tag(body['start'], _date) or not _tag(body['explicit_empty'], lambda x: x is True)
                    or body['disposition'] not in {'accepted_complete_nonempty','accepted_complete_empty'}
                    or type(body['rows']) is not list or not all(valid_row_signature(v) for v in body['rows'])
                    or body['rows'] != sorted(body['rows'], key=_canonical)):
                return False
            if row['group_id'] != hashlib.sha256(_canonical(['sql-investment-cash-group-v1',row['signature']]).encode()).hexdigest():
                return False
        if table == 'investment_facts':
            from .investment import decode
            facts = decode(parsed['body'])
            if (facts.doc_id,facts.currency,facts.as_of) != (row['doc_id'],row['currency'],row['as_of']):
                return False
    except (ValueError,TypeError,KeyError,InvalidOperation,OverflowError,RecursionError):
        return False
    return True


def key_for(value):
    from .investment_numbers import key, scalar
    return key(scalar(value))
