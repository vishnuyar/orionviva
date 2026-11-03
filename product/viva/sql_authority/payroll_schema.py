"""Closed payroll facts, explanation witnesses and retained activation history."""
from datetime import date
from decimal import Decimal, InvalidOperation
import json
import hashlib

TABLES = {
    'payroll_facts': ('doc_id','currency','pay_date','period_start','period_end','gross','net','net_key','body','context_id','source_kind'),
    'payroll_components': ('doc_id','state','reason','explanation_id','account_id','revision'),
    'payroll_dependencies': ('doc_id','currency','net_key','pay_date','active'),
    'payroll_explanations': ('explanation_id','movement','txn_id','source_doc','currency','pay_date','gross','net','signature'),
    'payroll_witnesses': ('doc_id','explanation_id'),
    'payroll_legs': ('explanation_id','leg','account_id','amount','currency','grade','doc_id','page'),
    'payroll_decisions': ('ordinal','explanation_id','action','revision','boundary'),
    'payroll_active': ('explanation_id','movement','active','decision_ordinal','revision'),
}
KEYS = {name: columns[:1] for name,columns in TABLES.items()}
KEYS.update(payroll_witnesses=('doc_id','explanation_id'), payroll_legs=('explanation_id','leg'))
MUTABLE = frozenset({'payroll_components','payroll_dependencies','payroll_active'})
DDL = '''
CREATE TABLE payroll_facts(doc_id TEXT PRIMARY KEY REFERENCES interpretations, currency TEXT NOT NULL, pay_date TEXT NOT NULL, period_start TEXT NOT NULL, period_end TEXT NOT NULL, gross TEXT NOT NULL, net TEXT NOT NULL, net_key TEXT NOT NULL, body TEXT NOT NULL, context_id TEXT NOT NULL REFERENCES read_contexts, source_kind TEXT NOT NULL);
CREATE TABLE payroll_explanations(explanation_id TEXT PRIMARY KEY, movement TEXT NOT NULL REFERENCES transfer_bindings, txn_id TEXT NOT NULL REFERENCES transactions, source_doc TEXT NOT NULL REFERENCES payroll_facts, currency TEXT NOT NULL, pay_date TEXT NOT NULL, gross TEXT NOT NULL, net TEXT NOT NULL, signature TEXT NOT NULL);
CREATE TABLE payroll_components(doc_id TEXT PRIMARY KEY REFERENCES payroll_facts, state TEXT NOT NULL, reason TEXT NOT NULL, explanation_id TEXT REFERENCES payroll_explanations, account_id TEXT REFERENCES accounts, revision INTEGER NOT NULL);
CREATE TABLE payroll_dependencies(doc_id TEXT PRIMARY KEY REFERENCES payroll_facts, currency TEXT NOT NULL, net_key TEXT NOT NULL, pay_date TEXT NOT NULL, active INTEGER NOT NULL CHECK(active IN(0,1)));
CREATE INDEX payroll_dependency_match ON payroll_dependencies(currency,net_key,pay_date,active,doc_id);
CREATE TABLE payroll_witnesses(doc_id TEXT NOT NULL REFERENCES payroll_facts, explanation_id TEXT NOT NULL REFERENCES payroll_explanations, PRIMARY KEY(doc_id,explanation_id));
CREATE INDEX payroll_witness_explanation ON payroll_witnesses(explanation_id,doc_id);
CREATE TABLE payroll_legs(explanation_id TEXT NOT NULL REFERENCES payroll_explanations, leg INTEGER NOT NULL CHECK(leg>=0), account_id TEXT NOT NULL, amount TEXT NOT NULL, currency TEXT NOT NULL, grade TEXT NOT NULL, doc_id TEXT NOT NULL REFERENCES payroll_facts, page INTEGER, PRIMARY KEY(explanation_id,leg));
CREATE TABLE payroll_decisions(ordinal INTEGER PRIMARY KEY CHECK(ordinal>0), explanation_id TEXT NOT NULL REFERENCES payroll_explanations, action TEXT NOT NULL CHECK(action IN('activate','deactivate')), revision INTEGER NOT NULL, boundary TEXT NOT NULL);
CREATE TABLE payroll_active(explanation_id TEXT PRIMARY KEY REFERENCES payroll_explanations, movement TEXT NOT NULL REFERENCES transfer_bindings, active INTEGER NOT NULL CHECK(active IN(0,1)), decision_ordinal INTEGER NOT NULL REFERENCES payroll_decisions, revision INTEGER NOT NULL);
CREATE UNIQUE INDEX payroll_unique_active_movement ON payroll_active(movement) WHERE active=1;
CREATE INDEX payroll_active_movement ON payroll_active(active,movement);
CREATE INDEX payroll_explanation_movement ON payroll_explanations(movement,explanation_id);
'''


def valid_row(table, row):
    from .schema import supported_amount
    if type(row) is not dict or set(row) != set(TABLES[table]):
        return False
    for key,value in row.items():
        if value is None:
            if key == 'page' or (table == 'payroll_components' and key in {'explanation_id','account_id'}):
                continue
            return False
        if key in {'leg','ordinal','revision','decision_ordinal','active','page'}:
            low = 0 if key in {'leg','active'} else 1
            high = 1 if key == 'active' else 200 if key == 'page' else 2**63-1
            if type(value) is not int or not low <= value <= high:
                return False
            continue
        limit = 8*1024*1024 if key in {'body','signature','boundary'} else 16384
        if type(value) is not str or len(value.encode()) > limit:
            return False
        if key in {'doc_id','source_doc','context_id','explanation_id','txn_id'}:
            if len(value) != 64 or any(c not in '0123456789abcdef' for c in value):
                return False
        if key in {'currency'} and (len(value)!=3 or not value.isascii() or not value.isalpha()):
            return False
        if key in {'gross','net','net_key','amount'}:
            try:
                if not value.isascii() or value != value.strip() or len(value)>128 or not supported_amount(Decimal(value)):
                    return False
            except InvalidOperation:
                return False
        if key in {'pay_date','period_start','period_end'}:
            if key != 'pay_date' and value == '':
                continue
            try:
                if date.fromisoformat(value).isoformat()!=value:
                    return False
            except ValueError:
                return False
        if key in {'body','signature','boundary'}:
            try:
                parsed=json.loads(value)
                if json.dumps(parsed,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)!=value:
                    return False
            except (ValueError,TypeError,RecursionError):
                return False
    if table=='payroll_facts':
        if row['source_kind'] not in {'typed','curated'}:
            return False
        from .payroll import decode
        try:
            facts=decode(json.loads(row['body']))
        except (ValueError,TypeError,KeyError,InvalidOperation,OverflowError):
            return False
        from .bank import amount_key
        for key in ('doc_id','currency','pay_date','period_start','period_end','gross','net'):
            expected=str(getattr(facts,key))
            if row[key]!=expected:
                return False
        if row['net_key']!=amount_key(facts.net):
            return False
    if table=='payroll_explanations':
        body=json.loads(row['signature'])
        names={'version','movement','employer','employee_names','pay_date','period_start','period_end','currency','gross','net','deductions'}
        if type(body) is not dict or set(body)!=names or type(body['version']) is not int or body['version']!=1:
            return False
        if any(type(body[k]) is not str for k in names-{'version','employee_names','deductions'}):
            return False
        if type(body['employee_names']) is not list or any(type(n) is not str for n in body['employee_names']):
            return False
        if type(body['deductions']) is not list:
            return False
        from .bank import amount_key
        for deduction in body['deductions']:
            if type(deduction) is not dict or set(deduction)!={'label','category','amount'} or any(type(deduction[k]) is not str for k in deduction):
                return False
            if deduction['category'] not in {'tax','retirement','insurance','other'}:
                return False
            try:
                if not supported_amount(Decimal(deduction['amount'])) or deduction['amount']!=amount_key(deduction['amount']):
                    return False
            except (ValueError,InvalidOperation):
                return False
        if row['explanation_id']!=hashlib.sha256(row['signature'].encode()).hexdigest():
            return False
        if body['movement']!=row['movement'] or body['currency']!=row['currency'] or body['pay_date']!=row['pay_date'] or body['gross']!=amount_key(row['gross']) or body['net']!=amount_key(row['net']):
            return False
    if table=='payroll_components':
        if row['state'] not in {'arithmetic_conflict','awaiting_deposit','ambiguous','accepted','duplicate'}:
            return False
        accepted=row['state'] in {'accepted','duplicate'}
        if row['reason']!=('' if accepted else row['state']):
            return False
        if accepted != (row['explanation_id'] is not None and row['account_id'] is not None):
            return False
        if not accepted and (row['explanation_id'] is not None or row['account_id'] is not None):
            return False
    if table=='payroll_legs' and row['grade'] not in {'verified','unverified'}:
        return False
    if table=='payroll_decisions':
        if row['action'] not in {'activate','deactivate'}:
            return False
        body=json.loads(row['boundary'])
        if type(body) is not dict or set(body)!={'version','causes'} or type(body['version']) is not int or body['version']!=1 or type(body['causes']) is not list or not body['causes']:
            return False
        pairs=[]
        for cause in body['causes']:
            if type(cause) is not dict or set(cause)!={'table','key','source_doc_id'} or type(cause['table']) is not str or cause['table'] not in {'interpretations','transactions','transfer_bindings','transfer_members'}:
                return False
            if any(type(cause[k]) is not str or not cause[k] for k in ('key','source_doc_id')):
                return False
            source=cause['source_doc_id']
            if len(source)!=64 or any(c not in '0123456789abcdef' for c in source):
                return False
            pairs.append((cause['table'],cause['key']))
        if pairs!=sorted(set(pairs)):
            return False
    return True
