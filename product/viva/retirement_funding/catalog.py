"""Bounded source-proven retirement set labels, without financial source payloads."""
from itertools import combinations
from time import monotonic
from .contracts import Request,ANNUAL


def entries(connection,accounts):
    if connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='retirement_plan_members'").fetchone() is None:return [],False
    rows=connection.execute('SELECT account,currency FROM retirement_plan_members ORDER BY account LIMIT 4').fetchall()
    if len(rows)>3:
        return [],False
    info={str(item['id']):item for item in accounts}
    if any(account not in info for account,currency in rows):
        return [],False
    output=[]
    for size in range(1,len(rows)+1):
        for members in combinations([account for account,currency in rows],size):
            subject=Request(ANNUAL,tuple(members),'USD',year=2000).subject
            output.append({'id':subject['account_set_id'],'set_type':'retirement_plans','member_ids':list(members),'label':', '.join(str(info[member].get('name') or member) for member in members)})
    return output,True


def semantic_catalog(base,supplier):
    catalog=dict(base)
    catalog['retirement_plan_sets']=[]
    catalog['coverage']=dict(base['coverage'])
    catalog['coverage']['retirement_plan_sets']={'count':0,'complete':False}
    if supplier is None:
        return catalog
    try:
        deadline=monotonic()+2
        scope=supplier(deadline=deadline) if getattr(supplier,'deadline_aware',False) else supplier()
        with scope as revision:
            revision._store.authenticated_source_identity(revision)
            values,complete=entries(revision.connection,catalog['accounts'])
            revision._store.authenticated_source_identity(revision)
            if monotonic()>deadline:raise ValueError('retirement model catalog deadline')
            catalog['retirement_plan_sets']=values
            catalog['coverage']['retirement_plan_sets']={'count':len(values),'complete':complete}
    except (ValueError,RuntimeError):
        pass
    return catalog
