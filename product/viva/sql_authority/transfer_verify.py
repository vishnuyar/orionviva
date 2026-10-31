"""Explicit full-evidence reconstruction independent of indexed selection."""
from __future__ import annotations
from decimal import Decimal
import json
from ..ledger.identity import account_tokens, distinctive_tokens
from ..ledger.movement_identity import movement_key
from ..ledger.transfer_admission import (TRANSFER_CANDIDATE_LIMIT,
    recognized_link_origin, account_reference_available, counterpart_reference_complete,
    relationship_complete)
from ..ledger.events import Provenance, transfer_linked, transfer_suggested
from ..ledger.projection.movements import MovementInfo
from ..ingest.transfers import _flow, is_transfer_candidate, weigh, decide, _evidence
from .store import canonical, IntegrityError
from .transfers import Context, transport


def verify(store,state,export):
    from ..crypto import open_sealed
    operations=[]
    for sequence,previous,envelope,_hash in export["records"]:
        payload=json.loads(open_sealed(store._audit_key,json.loads(envelope),aad=canonical([sequence,previous]).encode()))
        operations.append(payload["operations"])
    inventory={}; bindings={}; endpoints={}; tokens=set(); edges=set(); dirty=set()
    pairs={}; suggestions={}; members={}; assertion_expected=[]; run_expected={}
    seen_docs=set(); admission_buckets={}
    account_rows={}; transaction_rows={}; keymap={row["account_id"]:row["logical_key"] for row in state["account_keys"].values()}

    def fail(message):
        raise IntegrityError("transfer semantic mismatch: "+message)

    def m(key):
        row=bindings[key]; info=inventory[row["account"]]
        return MovementInfo(key=key,account=row["account"],kind=info["kind"],date=row["date"],amount=Decimal(row["amount"]),description=row["description"],currency=info["currency"],provenance=Provenance(row["doc_id"],row["page"]),linked=key in members)

    def visible():
        return {a for a,body in suggestions.items() if a not in members and (not body["candidates"] or not all(c in members for c in body["candidates"]))}

    def fold_assertion(row):
        body=row["body"]; a=body["a"]
        assertion_expected.append(row)
        if row["event_type"]=="TransferSuggested":
            suggestions[a]=body
            return
        b=body["b"]; pair=tuple(sorted((a,b)))
        if row["event_type"]=="TransferLinked":
            if a in members or b in members:
                fail("duplicate live member")
            pairs[pair]=dict(status="linked",grade=body["grade"],by=body["by"],decided_by=body["evidence"].get("decided_by",""))
            members[a]=pair; members[b]=pair
        else:
            pairs[pair]=dict(status="unlinked")
            for key in (a,b):
                if members.get(key)==pair:
                    members.pop(key)
        suggestions.pop(a,None); suggestions.pop(b,None)
        for key in (a,b):
            if key in bindings:
                dirty.add(key)
            for x,y in edges:
                if key==x:
                    dirty.add(y)
                if key==y:
                    dirty.add(x)

    # Required order comes from ordinary financial promotion assertions and
    # original transaction line indices, never transfer-family operation order.
    expected_inventory={}; expected_bindings={}; promoted=set(); source_order=0
    from ..ledger.postings import counter_account
    for ops in operations:
        for operation in ops:
            source=operation["row"]
            if operation["table"]!="items" or source["state"]!="accepted" or source["doc_id"] in promoted:
                continue
            doc=source["doc_id"]; physical=source["account_id"]
            promoted.add(doc); logical=keymap[physical]
            facts=json.loads(state["interpretations"][(doc,)]["facts"])
            kind=state["accounts"][(physical,)]["kind"]
            expected_inventory.setdefault(logical,dict(account=logical,kind=kind,currency=facts["currency"],institution=facts["institution"],number=facts["account_number"],name=facts["account_ref"],source_doc=doc,source_order=len(expected_inventory)+1))
            required=sorted((row for row in state["transactions"].values() if row["doc_id"]==doc),key=lambda row:row["line_index"])
            occurrences={}
            for txn in required:
                signature=(txn["date"],txn["amount"],txn["description"])
                occurrence=occurrences.get(signature,0); occurrences[signature]=occurrence+1
                source_order+=1
                expected_bindings[txn["txn_id"]]=dict(movement=movement_key(doc,logical,txn["date"],Decimal(txn["amount"]),txn["description"],occurrence),account=logical,physical_account=physical,txn_id=txn["txn_id"],doc_id=doc,page=txn["page"],date=txn["date"],amount=txn["amount"],description=txn["description"],occurrence=occurrence,source_order=source_order)
                counter=counter_account(kind,Decimal(txn["amount"]))
                expected_inventory.setdefault(counter,dict(account=counter,kind="",currency="",institution="",number="",name="",source_doc=doc,source_order=len(expected_inventory)+1))

    def add_inventory(row):
        key=row["account"]
        if key in inventory:
            fail("immutable inventory rewrite")
        if row!=expected_inventory.get(key):
            fail("inventory admission")
        new_tokens=account_tokens(row["institution"],row["number"],row["name"])
        owners={owner for token,owner in tokens if token in new_tokens}
        dirty.update(k for k,b in bindings.items() if b["account"] in owners and k not in members)
        tokens.update((token,key) for token in new_tokens)
        inventory[key]=row

    def complete_reference(source,counterpart,*,relationship=True):
        def available(movement):
            info=inventory.get(movement.account)
            return bool(info and account_reference_available(info["account"],info["name"],info["number"]))
        counterpart_available=available(counterpart)
        if not counterpart_reference_complete(counterpart,counterpart_available):
            return False
        return not relationship or relationship_complete(
            source,counterpart,available(source),counterpart_available)

    for ops in operations:
        admissions=[]; actual_assertions=[]; actual_runs=[]
        for op in ops:
            table,row=op["table"],op["row"]
            if table=="accounts":
                account_rows[row["account_id"]]=row
            elif table=="transactions":
                transaction_rows[row["txn_id"]]=row
            elif table=="transfer_inventory":
                add_inventory(row)
            elif table=="transfer_bindings":
                expected=expected_bindings.get(row["txn_id"])
                if row!=expected:
                    fail("source movement identity/order")
                key=row["movement"]; bindings[key]=row
                new=m(key); dirty.add(key)
                flow=_flow(new)
                opposite="destination" if flow=="source" else "source"
                if flow!="neither":
                    for other in admission_buckets.get((new.currency,abs(new.amount),opposite),()):
                        old=m(other)
                        if is_transfer_candidate(new,old):
                            edges.add((key,other)); dirty.add(other)
                        elif is_transfer_candidate(old,new):
                            edges.add((other,key)); dirty.add(other)
                admission_buckets.setdefault((new.currency,abs(new.amount),flow),[]).append(key)
            elif table=="items" and row["state"]=="accepted" and row["doc_id"] not in seen_docs:
                doc=row["doc_id"]
                physical=row["account_id"]
                logical=keymap[physical]
                if logical not in inventory:
                    fail("accepted source account inventory omitted")
                from ..ledger.postings import counter_account
                required=[txn for txn in transaction_rows.values() if txn["doc_id"]==doc]
                actual=[binding for binding in bindings.values() if binding["doc_id"]==doc]
                if {binding["txn_id"] for binding in actual}!={txn["txn_id"] for txn in required}:
                    fail("accepted source movement omitted")
                for txn in required:
                    counter=counter_account(account_rows[physical]["kind"],Decimal(txn["amount"]))
                    if counter not in inventory:
                        fail("accepted source counteraccount omitted")
                admissions.append(doc); seen_docs.add(doc)
            elif table=="transfer_assertions":
                actual_assertions.append({**row,"body":json.loads(row["body"]),"provenance":json.loads(row["provenance"])})
            elif table=="transfer_runs":
                actual_runs.append(row)
        if admissions:
            # Rebuild the complete graph and global population from immutable
            # admission evidence; no candidate index or candidate export is used.
            graph={}; sources={}
            ordered=sorted((m(k) for k in bindings if k not in members),key=lambda x:(x.account,x.date,x.description,str(x.amount),bindings[x.key]["source_order"]))
            destinations={}
            for dst in ordered:
                if _flow(dst)=="destination":
                    destinations.setdefault((dst.currency,abs(dst.amount)),[]).append(dst)
            for src in ordered:
                if _flow(src)!="source":
                    continue
                sources[src.key]=src
                candidates=[dst for dst in destinations.get((src.currency,abs(src.amount)),()) if is_transfer_candidate(src,dst)]
                if candidates:
                    graph[src.key]=candidates
            dist=distinctive_tokens({key:account_tokens(row["institution"],row["number"],row["name"]) for key,row in inventory.items()},{key:row["institution"] for key,row in inventory.items()})
            strength,why=weigh(Context(list(inventory.values())),graph,sources,dist,profile_for=lambda _m:None)
            verdicts=decide(graph,strength); initial=visible(); consumed=set(); expected_actions=[]
            for key in sorted(graph):
                if key in consumed:
                    continue
                cands=[candidate for candidate in graph[key] if candidate.key not in consumed]
                if not cands:
                    continue
                dstkey=verdicts.get(key); src=sources[key]
                if dstkey and dstkey not in consumed:
                    dst=next(candidate for candidate in cands if candidate.key==dstkey)
                    expected_actions.append(transport(transfer_linked(key,dstkey,"corroborated",_evidence(src,dst,"decisive",why[key,dstkey]),max(src.date,dst.date),by="auto")))
                    consumed.update((key,dstkey))
                elif key not in initial:
                    expected_actions.append(transport(transfer_suggested(key,[c.key for c in cands],_evidence(src,cands[0],"suggested"),max(src.date,cands[0].date))))
            actual_actions=[{key:row[key] for key in ("event_type","occurred_at","body","provenance")} for row in actual_assertions]
            if expected_actions!=actual_actions:
                fail("full-context automatic assertions/wakeup")
            visited=set(dirty); queue=list(dirty)
            while queue:
                key=queue.pop()
                if key in members:
                    continue
                for a,b in edges:
                    other=b if a==key else a if b==key else None
                    if other is not None and other not in members and other not in visited:
                        visited.add(other); queue.append(other)
            if len(actual_runs)!=int(bool(visited)):
                fail("decision run scheduling")
            if actual_runs:
                run=actual_runs[0]; body=json.loads(run["body"])
                if run["boundary"]!=admissions[0]:
                    fail("outer source boundary")
                selected={key:vals for key,vals in graph.items() if key in visited}
                endpoint_accounts={bindings[key]["account"] for key in visited if key not in members}
                raw={token for token,owner in tokens if owner in endpoint_accounts}
                owner_accounts=endpoint_accounts|{owner for token,owner in tokens if token in raw}
                expected_body=dict(context=store._implementation_identity,endpoints=sorted(visited),owners=[inventory[key] for key in sorted(owner_accounts)],graph={key:[candidate.key for candidate in selected[key]] for key in sorted(selected)},strength=[dict(a=key,b=c.key,score=strength[key,c.key]) for key in sorted(selected) for c in selected[key]],why=[dict(a=key,b=c.key,rule=why[key,c.key]) for key in sorted(selected) for c in selected[key]],verdicts={key:verdicts[key] for key in sorted(selected) if key in verdicts},initial_open=sorted(initial&set(selected)),assertions=expected_actions,admissions=admissions)
                if body!=expected_body:
                    fail("graph/owner/score/verdict/order witnesses")
                run_expected[run["run_id"]]=run
                for row in actual_assertions:
                    if row["run_id"]!=run["run_id"] or row["boundary"]!=run["boundary"]:
                        fail("assertion boundary binding")
                    fold_assertion(row)
            dirty.difference_update(visited)
        elif actual_runs:
            fail("orphan decision run")
        elif actual_assertions:
            if actual_runs:
                fail("manual action invented automatic scan")
            for row in actual_assertions:
                if row["run_id"] or row["event_type"]=="TransferSuggested":
                    fail("manual assertion provenance")
                body=row["body"]; a=body["a"]; b=body.get("b","")
                if a not in bindings or row["boundary"]!=bindings[a]["doc_id"]:
                    fail("manual source reference")
                if row["event_type"]=="TransferLinked" or not b:
                    cands=suggestions.get(a,{}).get("candidates",[])
                    if a not in visible() or not cands or len(cands)>TRANSFER_CANDIDATE_LIMIT or len(set(cands))!=len(cands):
                        fail("manual suggestion admission")
                    for key in cands:
                        if key not in bindings or key in members or not is_transfer_candidate(m(a),m(key)) or not complete_reference(m(a),m(key)):
                            fail("manual complete references")
                    if row["event_type"]=="TransferLinked" and (b not in cands or body!={"a":a,"b":b,"grade":"verified","evidence":{"kind":"confirmed"},"by":"human","status":"linked"}):
                        fail("manual confirmation")
                else:
                    pair=tuple(sorted((a,b)))
                    info=pairs.get(pair,{})
                    if (info.get("status")!="linked" or members.get(a)!=pair or members.get(b)!=pair
                            or b not in bindings or not recognized_link_origin(info)
                            or not complete_reference(m(a),m(b))
                            or not (is_transfer_candidate(m(a),m(b)) or is_transfer_candidate(m(b),m(a)))):
                        fail("manual reversal admission")
                fold_assertion(row)
    if state["transfer_runs"]!={(key,):row for key,row in run_expected.items()}:
        fail("decision run inventory")
    if set(state["transfer_inventory"])!={(key,) for key in inventory} or any(state["transfer_inventory"][(key,)]!=value for key,value in inventory.items()):
        fail("inventory view")
    if state["transfer_bindings"]!={(key,):row for key,row in bindings.items()}:
        fail("movement bindings")
    if set(state["transfer_tokens"])!=tokens or set(state["transfer_edges"])!=edges:
        fail("token ownership/candidate edges")
    from .bank import amount_key
    expected_endpoints={}
    for key in bindings:
        mov=m(key)
        expected_endpoints[(key,)]=dict(movement=key,account=mov.account,currency=mov.currency,magnitude=amount_key(abs(mov.amount)),flow=_flow(mov),date=mov.date,active=int(key not in members))
    if state["transfer_endpoints"]!=expected_endpoints:
        fail("eligible endpoints/live membership")
    actual_dirty={row["movement"] for row in state["transfer_dirty"].values() if row["active"]}
    if actual_dirty!=dirty:
        fail("dirty dependency state")
    expected_pairs={}
    first_pairs={}; resident_suggestions={}
    for row in assertion_expected:
        body=row["body"]
        if row["event_type"]=="TransferSuggested":
            if body["a"] not in resident_suggestions:
                resident_suggestions[body["a"]]=row["ordinal"]
        else:
            first_pairs.setdefault(tuple(sorted((body["a"],body["b"]))),row["ordinal"])
            resident_suggestions.pop(body["a"],None); resident_suggestions.pop(body["b"],None)
    for (a,b),info in pairs.items():
        expected_pairs[a,b]=dict(a=a,b=b,status=info["status"],grade=info.get("grade",""),by=info.get("by",""),decided_by=info.get("decided_by",""),resident=first_pairs[a,b])
    if state["transfer_pairs"]!=expected_pairs:
        fail("current pair/resident order")
    actual_active_suggestions={key[0]:row for key,row in state["transfer_suggestions"].items() if row["active"]}
    expected_suggestions={key:dict(a=key,body=canonical(body),active=1,resident=resident_suggestions[key]) for key,body in suggestions.items()}
    if actual_active_suggestions!=expected_suggestions:
        fail("stored suggestions/resident order")
    actual_members={key[0]:(row["a"],row["b"]) for key,row in state["transfer_members"].items() if row["active"]}
    if actual_members!=members:
        fail("unique live membership")
    if len(assertion_expected)!=len(state["transfer_assertions"]) or any(row["ordinal"]!=index for index,row in enumerate(assertion_expected,1)):
        fail("assertion source order")
