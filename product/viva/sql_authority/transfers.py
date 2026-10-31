"""Indexed transfer dependencies and current overlays over accepted source rows."""
from __future__ import annotations
from datetime import date, timedelta
from decimal import Decimal
import json
import secrets
from dataclasses import asdict

from ..ingest.transfers import (_flow, is_transfer_candidate, weigh, decide,
    _evidence, _later)
from ..ledger.identity import account_tokens, distinctive_tokens
from ..ledger.movement_identity import movement_key
from ..ledger.transfer_admission import (TRANSFER_CANDIDATE_LIMIT,
    recognized_link_origin, account_reference_available, counterpart_reference_complete)
from ..ledger.events import Provenance, transfer_linked, transfer_suggested, transfer_unlinked
from ..ledger.projection.accounts import AccountInfo
from ..ledger.projection.movements import MovementInfo
from .store import canonical, AuthorityError, IntegrityError
from .schema import TABLES


def rows(store, table, where="1", parameters=(), order=""):
    columns=TABLES[table]
    sql=f"SELECT {','.join(chr(34)+column+chr(34) for column in columns)} FROM {table} WHERE {where}"
    if order:
        sql += " ORDER BY " + order
    return [dict(zip(columns,row)) for row in store._read(sql,parameters)]


def next_order(store, table, field):
    return store._read(f"SELECT COALESCE(MAX({field}),0)+1 FROM {table} WHERE 1")[0][0]


def dirty(store, key):
    store._put("transfer_dirty",dict(movement=key,active=1))


def immutable_row(store, table, key):
    cache=store._transfer_facts
    if cache is None:
        return store._row(table,KEY_FIELDS[table]+"=?",(key,))
    found=cache[table]
    if key not in found:
        found[key]=store._row(table,KEY_FIELDS[table]+"=?",(key,))
    return found[key]


KEY_FIELDS={"transfer_inventory":"account","transfer_bindings":"movement"}


def remember(store, table, key, row):
    if store._transfer_facts is not None:
        store._transfer_facts[table][key]=row


def inventory_admit(store, account, kind, currency, institution, number, name, doc_id):
    if immutable_row(store,"transfer_inventory",account) is not None:
        return
    row=dict(account=account,kind=kind,currency=currency,institution=institution,number=number,name=name,
        source_doc=doc_id,source_order=next_order(store,"transfer_inventory","source_order"))
    store._put("transfer_inventory",row)
    remember(store,"transfer_inventory",account,row)
    for token in sorted(account_tokens(institution,number,name)):
        # Every raw owner matters, even if the evidence helper later discards it.
        for (key,) in store._read("SELECT e.movement FROM transfer_tokens t JOIN transfer_endpoints e ON e.account=t.account WHERE t.token=? AND e.active=1 ORDER BY e.movement",(token,)):
            dirty(store,key)
        store._put("transfer_tokens",dict(token=token,account=account))
    store._fault("after_transfer_inventory")


def admit(store, account, mapped, facts):
    logical=mapped["logical_key"]
    inventory_admit(store,logical,account["kind"],account["currency"],account["institution"],account["number"],account["label"],facts.doc_id)
    source_order=next_order(store,"transfer_bindings","source_order")
    counts={}
    from .bank import amount_key
    for txn in rows(store,"transactions","doc_id=?",(facts.doc_id,),"line_index"):
        sig=(txn["date"],txn["amount"],txn["description"])
        occurrence=counts.get(sig,0); counts[sig]=occurrence+1
        key=movement_key(facts.doc_id,logical,txn["date"],Decimal(txn["amount"]),txn["description"],occurrence)
        binding=dict(movement=key,account=logical,physical_account=account["account_id"],txn_id=txn["txn_id"],doc_id=facts.doc_id,
            page=txn["page"],date=txn["date"],amount=txn["amount"],description=txn["description"],occurrence=occurrence,source_order=source_order)
        source_order+=1
        store._put("transfer_bindings",binding)
        remember(store,"transfer_bindings",key,binding)
        m=movement(binding,account["kind"],account["currency"])
        endpoint=dict(movement=key,account=logical,currency=m.currency,magnitude=amount_key(abs(m.amount)),flow=_flow(m),date=m.date,active=1)
        store._put("transfer_endpoints",endpoint)
        other="destination" if endpoint["flow"]=="source" else "source"
        if endpoint["flow"]!="neither":
            day=date.fromisoformat(m.date)
            candidates=rows(store,"transfer_endpoints","currency=? AND magnitude=? AND flow=? AND date>=? AND date<=?",
                (m.currency,endpoint["magnitude"],other,(day-timedelta(days=5)).isoformat(),(day+timedelta(days=5)).isoformat()))
            for candidate in candidates:
                if candidate["account"]==logical:
                    continue
                a,b=(key,candidate["movement"]) if endpoint["flow"]=="source" else (candidate["movement"],key)
                store._put("transfer_edges",dict(a=a,b=b))
                dirty(store,candidate["movement"])
        dirty(store,key)
        from ..ledger.postings import counter_account
        inventory_admit(store,counter_account(m.kind,m.amount),"","","","","",facts.doc_id)
    store._fault("after_transfer_bindings")


def movement(binding,kind,currency,linked=False):
    return MovementInfo(key=binding["movement"],account=binding["account"],kind=kind,date=binding["date"],
        amount=Decimal(binding["amount"]),description=binding["description"],currency=currency,
        provenance=Provenance(binding["doc_id"],binding["page"]),linked=linked)


def load_movement(store,key):
    binding=immutable_row(store,"transfer_bindings",key)
    if binding is None:
        return None
    info=immutable_row(store,"transfer_inventory",binding["account"])
    endpoint=store._row("transfer_endpoints","movement=?",(key,))
    return movement(binding,info["kind"],info["currency"],not endpoint["active"])


def movements(store):
    return [load_movement(store,row["movement"]) for row in rows(store,"transfer_bindings",order="account,date,description,amount,source_order")]


class Context:
    def __init__(self,owners):
        self.owners={row["account"]:row for row in owners}
    def account_info(self,key):
        row=self.owners[key]
        return AccountInfo(account=key,kind=row["kind"],currency=row["currency"],name=row["name"],institution=row["institution"],number=row["number"])


def transport(event):
    return dict(event_type=event.event_type,occurred_at=event.occurred_at,body=event.body,provenance=event.provenance.to_dict())


def live_links(store):
    return [{key:row[key] for key in ("a","b","status","grade","by","decided_by")} for row in rows(store,"transfer_pairs","status='linked'",order="resident")]


def suggestions(store,stored=False):
    found=rows(store,"transfer_suggestions","active=1",order="resident")
    if stored:
        return [json.loads(row["body"]) for row in found]
    out=[]
    for row in found:
        body=json.loads(row["body"])
        if is_linked(store,body["a"]):
            continue
        candidates=body["candidates"]
        if candidates and all(is_linked(store,key) for key in candidates):
            continue
        out.append(body)
    return out


def is_linked(store,key):
    member=store._row("transfer_members","movement=?",(key,))
    return member is not None and member["active"]==1


def _clear_suggestion(store,key):
    prior=store._row("transfer_suggestions","a=?",(key,))
    if prior is not None and prior["active"]:
        store._put("transfer_suggestions",{**prior,"active":0})


def wake(store,key):
    endpoint=store._row("transfer_endpoints","movement=?",(key,))
    if endpoint is not None:
        dirty(store,key)
    for (other,) in store._read("SELECT b FROM transfer_edges WHERE a=? UNION SELECT a FROM transfer_edges WHERE b=?",(key,key)):
        dirty(store,other)


def append(store,event,boundary,run_id=""):
    payload=transport(event)
    ordinal=next_order(store,"transfer_assertions","ordinal")
    store._put("transfer_assertions",dict(ordinal=ordinal,event_type=payload["event_type"],occurred_at=payload["occurred_at"],body=canonical(payload["body"]),provenance=canonical(payload["provenance"]),boundary=boundary,run_id=run_id))
    body=event.body; a=body["a"]
    if event.event_type=="TransferSuggested":
        prior=store._row("transfer_suggestions","a=?",(a,))
        resident=prior["resident"] if prior and prior["active"] else ordinal
        store._put("transfer_suggestions",dict(a=a,body=canonical(body),active=1,resident=resident))
    else:
        b=body["b"]; pa,pb=sorted((a,b))
        prior=store._row("transfer_pairs","a=? AND b=?",(pa,pb))
        linked=event.event_type=="TransferLinked"
        if linked and (is_linked(store,a) or is_linked(store,b)):
            raise IntegrityError("transfer member already consumed")
        row=dict(a=pa,b=pb,status="linked" if linked else "unlinked",grade=body.get("grade","") if linked else "",
            by=body.get("by","") if linked else "",decided_by=body.get("evidence",{}).get("decided_by","") if linked else "",resident=prior["resident"] if prior else ordinal)
        store._put("transfer_pairs",row)
        for key in (a,b):
            if not key:
                continue
            member=store._row("transfer_members","movement=?",(key,))
            if linked:
                store._put("transfer_members",dict(movement=key,a=pa,b=pb,active=1))
            elif member and (member["a"],member["b"])==(pa,pb):
                store._put("transfer_members",{**member,"active":0})
            endpoint=store._row("transfer_endpoints","movement=?",(key,))
            if endpoint:
                store._put("transfer_endpoints",{**endpoint,"active":int(not is_linked(store,key))})
            _clear_suggestion(store,key)
            wake(store,key)
    store._fault("after_transfer_assertion")
    return payload


def settle_dirty(store,boundary,admissions):
    seeds=[key for (key,) in store._read("SELECT movement FROM transfer_dirty WHERE active=1 ORDER BY movement")]
    if not seeds:
        return
    visited=set(); queue=list(seeds); endpoint_snapshot={}
    while queue:
        key=queue.pop()
        if key in visited:
            continue
        visited.add(key)
        endpoint=store._row("transfer_endpoints","movement=?",(key,))
        endpoint_snapshot[key]=endpoint
        if not endpoint["active"]:
            continue
        for (other,) in store._read("SELECT x.b FROM transfer_edges x JOIN transfer_endpoints e ON e.movement=x.b WHERE x.a=? AND e.active=1 UNION SELECT x.a FROM transfer_edges x JOIN transfer_endpoints e ON e.movement=x.a WHERE x.b=? AND e.active=1",(key,key)):
            if other not in visited:
                queue.append(other)
    snapshot_bindings={key:immutable_row(store,"transfer_bindings",key) for key in visited if endpoint_snapshot[key]["active"]}
    unlinked={}
    for key,binding in snapshot_bindings.items():
        info=immutable_row(store,"transfer_inventory",binding["account"])
        unlinked[key]=movement(binding,info["kind"],info["currency"])
    def order(m):
        binding=snapshot_bindings[m.key]
        return (m.account,m.date,m.description,str(m.amount),binding["source_order"])
    graph={}; sources={key:m for key,m in unlinked.items() if _flow(m)=="source"}
    for key in sorted(sources):
        candidates=[unlinked[b] for (b,) in store._read("SELECT b FROM transfer_edges WHERE a=?",(key,)) if b in unlinked]
        if candidates:
            graph[key]=sorted(candidates,key=order)
    owner_rows={}
    for account in {m.account for m in unlinked.values()}:
        owner_rows[account]=immutable_row(store,"transfer_inventory",account)
        selected=store._read("SELECT DISTINCT inventory.account,inventory.kind,inventory.currency,inventory.institution,inventory.number,inventory.name,inventory.source_doc,inventory.source_order FROM transfer_tokens endpoint JOIN transfer_tokens owners ON owners.token=endpoint.token JOIN transfer_inventory inventory ON inventory.account=owners.account WHERE endpoint.account=? ORDER BY inventory.account",(account,))
        for raw in selected:
            row=dict(zip(TABLES["transfer_inventory"],raw))
            owner_rows[row["account"]]=row
    owners=[owner_rows[key] for key in sorted(owner_rows)]
    distinctive=distinctive_tokens({row["account"]:account_tokens(row["institution"],row["number"],row["name"]) for row in owners},{row["account"]:row["institution"] for row in owners})
    strength,why=weigh(Context(owners),graph,sources,distinctive,profile_for=lambda _m:None)
    verdicts=decide(graph,strength)
    # Visibility is checked only for relevant sources; unrelated history is never loaded.
    initial_open=set()
    for key in sorted(graph):
        row=store._row("transfer_suggestions","a=?",(key,))
        if row and row["active"] and not is_linked(store,key):
            body=json.loads(row["body"])
            if not body["candidates"] or not all(is_linked(store,c) for c in body["candidates"]):
                initial_open.add(key)
    del endpoint_snapshot, snapshot_bindings
    store._fault("after_transfer_snapshot")
    run_id=secrets.token_hex(16); assertions=[]; consumed=set()
    for key in sorted(graph):
        if key in consumed:
            continue
        src=sources[key]; candidates=[c for c in graph[key] if c.key not in consumed]
        if not candidates:
            continue
        chosen=verdicts.get(key)
        if chosen is not None and chosen not in consumed:
            dst=next(c for c in candidates if c.key==chosen)
            event=transfer_linked(key,chosen,"corroborated",_evidence(src,dst,"decisive",why[key,chosen]),_later(src.date,dst.date),by="auto")
            assertions.append(append(store,event,boundary,run_id)); consumed.update((key,chosen))
        elif key not in initial_open:
            event=transfer_suggested(key,[c.key for c in candidates],_evidence(src,candidates[0],"suggested"),_later(src.date,candidates[0].date))
            assertions.append(append(store,event,boundary,run_id))
    body=dict(context=store._implementation_identity,endpoints=sorted(visited),owners=owners,graph={key:[m.key for m in vals] for key,vals in graph.items()},
        strength=[dict(a=a,b=b,score=score) for (a,b),score in strength.items()],why=[dict(a=a,b=b,rule=rule) for (a,b),rule in why.items()],verdicts=verdicts,initial_open=sorted(initial_open),assertions=assertions,admissions=list(admissions))
    store._put("transfer_runs",dict(run_id=run_id,boundary=boundary,body=canonical(body)))
    # Linked vertices may have dirtied their neighbors while assertions were applied.
    # Those changes are already part of this complete snapshotted boundary.
    for key in visited:
        store._put("transfer_dirty",dict(movement=key,active=0))
    store._fault("after_transfer_settlement")


def assertion_rows(store):
    found=rows(store,"transfer_assertions",order="ordinal")
    return [{**row,"body":json.loads(row["body"]),"provenance":json.loads(row["provenance"])} for row in found]


def fold(assertions,as_of=None):
    pairs={}; pending={}
    for row in assertions:
        if as_of and row["occurred_at"]>as_of:
            continue
        body=row["body"]; a=body["a"]
        if row["event_type"]=="TransferSuggested":
            pending[a]=body
        else:
            b=body["b"]; pair=tuple(sorted((a,b)))
            pairs[pair]=({"status":"linked","grade":body["grade"],"by":body["by"],"decided_by":body["evidence"].get("decided_by","")} if row["event_type"]=="TransferLinked" else {"status":"unlinked"})
            pending.pop(a,None); pending.pop(b,None)
    links=[dict(a=a,b=b,**info) for (a,b),info in pairs.items() if info["status"]=="linked"]
    linked={key for item in links for key in (item["a"],item["b"])}
    visible=[body for body in pending.values() if body["a"] not in linked and (not body["candidates"] or not all(key in linked for key in body["candidates"]))]
    return dict(links=links,suggestions=visible),pairs,pending


def as_of(store,day):
    try:
        valid=type(day) is str and date.fromisoformat(day).isoformat()==day
    except ValueError:
        valid=False
    if not valid:
        raise AuthorityError("ISO effective date required")
    return fold(assertion_rows(store),day)[0]


def reference_complete(store,source,counterpart,relationship=True):
    # Renderers return nonempty output for every finite accepted amount, ISO date,
    # supported currency and account metadata. Only descriptions can be absent.
    if not source or not counterpart:
        return False
    for m in (source,counterpart) if relationship else (counterpart,):
        info=store._row("transfer_inventory","account=?",(m.account,))
        available = bool(info and account_reference_available(info["account"],info["name"],info["number"]))
        if not counterpart_reference_complete(m,available):
            return False
    return True


def admitted_suggestion(store,a):
    source=load_movement(store,a)
    if not source or source.linked:
        return None
    row=store._row("transfer_suggestions","a=?",(a,))
    if not row or not row["active"]:
        return None
    body=json.loads(row["body"]); cands=body["candidates"]
    if not cands or len(cands)>TRANSFER_CANDIDATE_LIMIT or len(set(cands))!=len(cands):
        return None
    for key in cands:
        dst=load_movement(store,key)
        if key==a or not dst or dst.linked or not is_transfer_candidate(source,dst) or not reference_complete(store,source,dst):
            return None
    return body


def manual(store,action,a,b="",today=None):
    if type(a) is not str or not a.strip() or len(a)>16384 or type(b) is not str or len(b)>16384 or (action!="reject" and (not b.strip() or a==b)):
        raise AuthorityError("bounded movement references required")
    day=today if today is not None else date.today().isoformat()
    try:
        valid=type(day) is str and date.fromisoformat(day).isoformat()==day
    except ValueError:
        valid=False
    if not valid:
        raise AuthorityError("ISO test clock required")
    with store._transaction():
        # This format admits no classification overlays. Every movement is bound
        # to an immutable ordinary simple_transaction accepted source posting.
        source=load_movement(store,a)
        if source is None:
            return False
        if action in {"confirm","reject"}:
            suggestion=admitted_suggestion(store,a)
            if not suggestion or (action=="confirm" and b not in suggestion["candidates"]):
                return False
            if action=="confirm":
                event=transfer_linked(a,b,"verified",{"kind":"confirmed"},day,by="human")
            else:
                event=transfer_unlinked(a,"",day)
        else:
            pa,pb=sorted((a,b)); pair=store._row("transfer_pairs","a=? AND b=?",(pa,pb))
            counterpart=load_movement(store,b)
            if not pair or pair["status"]!="linked" or not recognized_link_origin(pair) or not counterpart or not source.linked or not counterpart.linked or not reference_complete(store,source,counterpart):
                return False
            if not (is_transfer_candidate(source,counterpart) or is_transfer_candidate(counterpart,source)):
                return False
            if any((member["a"],member["b"])!=(pa,pb) for member in (store._row("transfer_members","movement=?",(a,)),store._row("transfer_members","movement=?",(b,)))):
                return False
            event=transfer_unlinked(a,b,day)
        append(store,event,source.provenance.doc_id)
        store._fault("after_manual_transfer")
    return True


def plans(store):
    queries={"endpoint":("SELECT movement FROM transfer_endpoints WHERE currency=? AND magnitude=? AND flow=? AND date>=? AND date<=?",("USD","10","source","2000-01-01","2100-01-01")),
        "reverse_edge":("SELECT a FROM transfer_edges WHERE b=?",("x",)),
        "token_owner":("SELECT account FROM transfer_tokens WHERE token=?",("x",)),
        "dirty":("SELECT movement FROM transfer_dirty WHERE active=1 ORDER BY movement",())}
    return {key:[list(row) for row in store._read("EXPLAIN QUERY PLAN "+sql,args)] for key,(sql,args) in queries.items()}
