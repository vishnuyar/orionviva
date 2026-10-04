"""Automatic accounting meaning and private, context-scoped correction memory.

Amounts and identities remain local. A reasoning call receives categorical
context and opaque references; its checked result can change counterpart meaning
but cannot allocate money or select an arbitrary account.
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import uuid
from datetime import date

from vivacore import promptstore, versions

from .ledger.events import (MAJORS, SCOPE_MOVEMENT, UNVERIFIED, VERIFIED, ruling_recorded,
    accounting_rule_recorded, accounting_rule_applied, accounting_correction_recorded,
    accounting_correction_undone, accounting_treatment_restored, Provenance)
from .ledger.postings import MAJOR_UNCATEGORIZED, account_path
from .ledger.projection.movements import money_effect

PACKAGE = pathlib.Path(__file__).parent
MAX_ITEMS = 32


def _today():
    return date.today().isoformat()


def context_key(proj, movement):
    """Private counterparties match exact descriptors and their source account."""
    from .ledger.merchants import is_shareable
    party = proj.merchant_key_of(movement)
    private = proj.is_person(movement) or not party or not is_shareable(party)
    category = proj.derived_category(movement) or {}
    return {"party": movement.description if private else proj.merchant_key_of(movement),
            "private": private,
            "direction": "out" if money_effect(movement) < 0 else "in",
            "source_role": proj.account_info(movement.account).kind or "unknown",
            "source_account": movement.account if private else "",
            "category": category.get("category", "other"),
            "subcategory": category.get("subcategory", "")}


def active_rules(ledger):
    """Replay rule additions/retractions without changing recorded movements."""
    rules = {}
    for event in ledger.store.snapshot_events():
        if event.event_type == "AccountingRuleRecorded":
            rules[event.body["rule_id"]] = event.body
        elif event.event_type == "AccountingCorrectionUndone":
            rules.pop(event.body.get("rule_id", ""), None)
    return list(rules.values())


def _matches(proj, movement, rule):
    if context_key(proj, movement) != rule["context"]:
        return False
    if movement.key == rule["anchor"] or movement.key in rule.get("excluded", []):
        return False
    if rule.get("starts") and movement.date < rule["starts"]:
        return False
    if rule.get("ends") and movement.date > rule["ends"]:
        return False
    recurrence = rule.get("recurrence", "")
    if recurrence:
        anchor = date.fromisoformat(rule["anchor_date"])
        current = date.fromisoformat(movement.date)
        if recurrence == "weekly" and (current - anchor).days % 7:
            return False
        if recurrence == "monthly" and abs(current.day - anchor.day) > 3:
            return False
        if recurrence == "yearly" and (current.month != anchor.month or abs(current.day - anchor.day) > 3):
            return False
    return True


def apply_learned_rules(ledger):
    """Latest context rule wins; explicit movement corrections remain stronger."""
    proj = ledger.projection()
    rules = active_rules(ledger)
    applied = 0
    for movement in proj.movements():
        current = next((r for r in proj.rulings(SCOPE_MOVEMENT) if r["subject"] == movement.key), None)
        if current and current.get("by") == "human":
            continue
        matched = next((r for r in reversed(rules) if _matches(proj, movement, r)), None)
        if not matched or (current and current.get("said") == matched["said"] and current.get("legs") == matched["legs"]):
            continue
        ledger.append(accounting_rule_applied(matched["rule_id"], movement.key, current or {},
            proj._core._categories.get(movement.key, {}), _today()))
        ledger.append(ruling_recorded(SCOPE_MOVEMENT, movement.key, _today(),
            legs=matched["legs"], by="human_rule", grade=VERIFIED,
            said=matched["said"], prompt_version=matched.get("prompt_version", "")))
        if matched.get("category"):
            from .ingest.categorize import assign_category
            assign_category(ledger, movement.key, matched["category"], by="human")
        applied += 1
    return applied


def _semantic_legs(legs):
    """A remembered relationship does not attest another payment's allocation."""
    return [{**leg, "share": ""} for leg in legs]


def save_correction(ledger, interp, proposal, selected, previous, original_context=None, created_accounts=None):
    """Record undo evidence and a narrow reusable rule, never a merchant ruling."""
    proj = ledger.projection()
    anchor = next((m for m in proj.movements() if m.key == selected[0]), None)
    correction_id = uuid.uuid4().hex
    rule_id = ""
    if anchor and interp.future_scope != "one" and interp.said.strip():
        context = original_context or context_key(proj, anchor)
        if context["party"]:
            rule_id = correction_id
            start = interp.starts or anchor.date
            if interp.ends and interp.ends < start:
                raise ValueError("a learned rule cannot end before it starts")
            ledger.append(accounting_rule_recorded(rule_id, anchor.key, anchor.date,
                context, _semantic_legs(proposal.legs), _today(), category=proposal.category,
                starts=start, ends=interp.ends, recurrence=interp.recurrence,
                excluded=[m.key for m in proj.movements()] if interp.future_scope != "recurring" else [],
                said=interp.said, prompt_version=interp.version))
    ledger.append(accounting_correction_recorded(correction_id, rule_id,
        selected, previous, proposal.legs, interp.said, _today(), context=original_context,
        created_accounts=created_accounts))
    return correction_id, rule_id


def undo_correction(ledger, correction_id):
    """Append compensating treatments and retract only this correction's rule."""
    events = ledger.store.snapshot_events()
    if any(e.event_type == "AccountingCorrectionUndone" and e.body.get("correction_id") == correction_id for e in events):
        return {"ok": True, "changed": 0}
    correction = next((e.body for e in reversed(events) if e.event_type == "AccountingCorrectionRecorded" and e.body["correction_id"] == correction_id), None)
    if not correction:
        return {"ok": False, "why": "correction_not_found"}
    proj = ledger.projection()
    restored = 0
    undone = {e.body['correction_id'] for e in events
              if e.event_type == 'AccountingCorrectionUndone'}
    corrections = {e.body['correction_id']: e.body for e in events
                   if e.event_type == 'AccountingCorrectionRecorded'}
    # Event order identifies independent decisions even when their words and
    # legs are identical. Each entry retains the exact preceding treatment.
    histories = {}
    for event in events:
        body = event.body
        if event.event_type == 'AccountingCorrectionRecorded':
            for key in body['movements']:
                histories.setdefault(key, []).append((body['correction_id'],
                    body['previous'].get(key, {})))
        elif event.event_type == 'AccountingRuleApplied' and body['rule_id'] in corrections:
            histories.setdefault(body['movement'], []).append((body['rule_id'],
                {'ruling':body['previous'], 'category':body.get('previous_category', {})}))
    previous_treatments = dict(correction["previous"])
    for event in events:
        if event.event_type == "AccountingRuleApplied" and event.body["rule_id"] == correction["rule_id"]:
            previous_treatments.setdefault(event.body["movement"], {"ruling": event.body["previous"],
                "category": event.body.get("previous_category", {})})
    for key, saved in previous_treatments.items():
        history = histories.get(key, [])
        latest = next((identity for identity, _ in reversed(history)
                       if identity not in undone), None)
        if latest != correction_id:
            continue
        # A later correction's snapshot may refer to an already-undone
        # decision. Follow that decision's own predecessor rather than revive it.
        target_index = next((i for i in range(len(history) - 1, -1, -1)
                             if history[i][0] == correction_id), len(history))
        for identity, earlier in reversed(history[:target_index]):
            if identity not in undone:
                break
            prior = saved.get('ruling', {})
            decision = corrections.get(identity, {})
            if (prior.get('said') == decision.get('said') and
                    prior.get('legs') in (decision.get('legs'), _semantic_legs(decision.get('legs', [])))):
                saved = earlier
        previous = saved.get("ruling", {})
        current = next((r for r in proj.rulings(SCOPE_MOVEMENT) if r["subject"] == key), {})
        expected_legs = (_semantic_legs(correction["legs"])
                         if current.get("by") == "human_rule" else correction["legs"])
        if current.get("legs") != expected_legs or current.get("said") != correction["said"]:
            continue
        ledger.append(accounting_treatment_restored(key, previous, saved.get("category", {}), _today()))
        restored += 1
    ledger.append(accounting_correction_undone(correction_id, correction["rule_id"], _today()))
    return {"ok": True, "changed": restored}


def correction_targets(proj, descriptor, movement_key="", movements=()):
    """Resolve explicit selection; a descriptor alone must name one movement."""
    held = {m.key: m for m in proj.movements()}
    selected = list(dict.fromkeys([movement_key] if movement_key else movements))
    if selected:
        return selected if all(k in held for k in selected) else []
    matches = [m.key for m in held.values() if m.description == descriptor]
    return matches if len(matches) == 1 else []


def correction_examples(ledger, proj, movement):
    """Local matching exposes only categorical lessons from prior corrections."""
    events = ledger.store.snapshot_events()
    undone = {event.body["correction_id"] for event in events
              if event.event_type == "AccountingCorrectionUndone"}
    context = context_key(proj, movement)
    examples = []
    for event in reversed(events):
        if event.event_type != "AccountingCorrectionRecorded":
            continue
        body = event.body
        if (body["correction_id"] in undone or body.get("context") != context
                or movement.key in body["movements"]):
            continue
        examples.append({"majors": [leg["major"] for leg in body["legs"]],
                         "scope": "one_off" if not body["rule_id"] else "matching_context"})
        if len(examples) == 8:
            break
    return examples


def _envelope(proj, movements, examples=None):
    from merchantcore import PRIMARY_CATEGORIES, FALLBACK_CATEGORY, seed_subcategories
    public_categories = set(PRIMARY_CATEGORIES) | {FALLBACK_CATEGORY}
    public_subcategories = set(seed_subcategories())
    rows = []
    for index, movement in enumerate(movements):
        category = proj.derived_category(movement) or {}
        implied = proj.implication_for(proj.merchant_key_of(movement), inflow=money_effect(movement) > 0) or {}
        rows.append({"ref": f"m{index}",
            "source_role": proj.account_info(movement.account).kind or "unknown",
            "direction": "out" if money_effect(movement) < 0 else "in",
            "category": category.get("category", "other") if category.get("category", "") in public_categories else "other",
            "subcategory": category.get("subcategory", "") if category.get("subcategory", "") in public_subcategories else "",
            "implied_major": implied.get("major", "") if implied.get("major", "") in MAJORS else "",
            "compound": bool(implied.get("compound")),
            "linked": bool(movement.linked),
            "correction_examples": (examples or {}).get(movement.key, [])})
    return {"movements": rows}


def research_capability():
    """Configured extraction adapters have no public-search tool contract."""
    return {"supported": False, "status": "unsupported", "reason": "configured_adapters_have_no_search_tools"}


def _configured_extractor():
    from vivacore.models import ModelSpec, adapter_for
    adapter = os.environ.get("VIVA_MODEL_ADAPTER", "").strip()
    model = os.environ.get("VIVA_MODEL", "").strip()
    if not adapter or not model:
        return None
    spec = ModelSpec(name="accounting-interpreter", adapter=adapter, model=model,
        base_url=os.environ.get("VIVA_MODEL_BASE_URL"),
        api_key_env=(None if os.environ.get("VIVA_MODEL_KEY_ENV", "OPENROUTER_API_KEY").lower() in ("", "none")
                     else os.environ.get("VIVA_MODEL_KEY_ENV", "OPENROUTER_API_KEY")),
        max_tokens=4096, max_continuations=0, timeout_s=45, json_mode=True)
    provider = adapter_for(spec)
    def extract(prompt):
        return provider.extract([], prompt)
    extract.spec = spec
    return extract


def _checked(raw, count):
    payload = json.loads(raw)
    if not isinstance(payload, dict) or set(payload) != {"interpretations"}:
        raise ValueError("invalid accounting envelope")
    rows = payload["interpretations"]
    if not isinstance(rows, list) or len(rows) > count:
        raise ValueError("invalid accounting population")
    clean, seen = [], set()
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"ref", "majors", "grounds"}:
            raise ValueError("model may supply only reference, meaning and grounds")
        ref = row["ref"]
        if ref not in {f"m{i}" for i in range(count)} or ref in seen:
            raise ValueError("unknown or duplicated accounting reference")
        majors = row["majors"]
        if not isinstance(majors, list) or not 1 <= len(majors) <= 4 or any(m not in MAJORS for m in majors):
            raise ValueError("invalid accounting meanings")
        if not isinstance(row["grounds"], str) or len(row["grounds"]) > 500:
            raise ValueError("invalid accounting grounds")
        clean.append(row)
        seen.add(ref)
    return clean


def interpret_activity(vault, *, extract_fn=None):
    """Capture one bounded reasoning exchange before applying checked meaning."""
    ledger = vault.ledger
    learned = apply_learned_rules(ledger)
    proj = ledger.projection()
    rulings = {r["subject"]: r for r in proj.rulings(SCOPE_MOVEMENT)}
    source_events = [event for event in ledger.store.snapshot_events()
                     if event.event_type == "TransactionRecorded"]
    def supported(movement):
        if movement.kind == "investment" or movement.nature_reason in ("own_account", "linked"):
            return True
        category = proj._core._categories.get(movement.key, {})
        if category.get("nature") and category.get("by") == "human":
            return True
        for event in source_events:
            if (event.occurred_at != movement.date
                    or event.body.get("description") != movement.description
                    or event.provenance.doc_id != movement.provenance.doc_id):
                continue
            postings = event.body.get("postings", [])
            source = any(p["account"] == movement.account and str(p["amount"]) == str(movement.amount) for p in postings)
            named = any(p["account"] != movement.account
                        and p["account"] not in MAJOR_UNCATEGORIZED.values()
                        and p["account"] != "Transfers:Uncategorized" for p in postings)
            if source and named:
                return True
        return False
    plans, unresolved, signatures, examples = [], [], {}, {}
    version = versions.active(PACKAGE, "accounting_interpret")
    for movement in proj.movements():
        current = rulings.get(movement.key, {})
        if current.get("by") in ("human", "human_rule") or current.get("grade") == VERIFIED:
            continue
        if movement.linked or supported(movement):
            if current.get("by") in ("model", "merchant_prior"):
                ledger.append(accounting_treatment_restored(movement.key, {},
                    proj._core._categories.get(movement.key, {}), _today()))
            continue
        examples[movement.key] = correction_examples(ledger, proj, movement)
        context = _envelope(proj, [movement], examples)["movements"][0]
        signature = hashlib.sha256(json.dumps({"context": context, "version": version}, sort_keys=True).encode()).hexdigest()
        signatures[movement.key] = signature
        if current.get("evidence_signature") == signature:
            continue
        implication = proj.implication_for(proj.merchant_key_of(movement), inflow=money_effect(movement) > 0) or {}
        major = implication.get("major")
        if major in MAJORS:
            majors = ([major, "expense"] if implication.get("compound")
                      and major in ("asset", "liability") and money_effect(movement) < 0 else [major])
            plans.append((movement, majors, "merchant_prior", "Merchant knowledge supplies the relationship; component allocations remain unknown." if len(majors) > 1 else "Merchant knowledge supplies the inferred accounting meaning."))
        else:
            unresolved.append(movement)
    selected = unresolved[:MAX_ITEMS]
    status, detail, result, prompt, rows = "not_configured", "", None, "", []
    try:
        extract = extract_fn or _configured_extractor()
        if extract is not None and selected:
            envelope = _envelope(proj, selected, examples)
            prompt = promptstore.load(PACKAGE / "prompts", version).format(context=json.dumps(envelope, sort_keys=True))
            result = extract(prompt)
            raw = result if isinstance(result, str) else result.text
            if getattr(result, "finish_reason", "") == "length":
                raise ValueError("truncated accounting response")
            rows = _checked(raw, len(selected))
            for row in rows:
                movement = selected[int(row["ref"][1:])]
                plans.append((movement, row["majors"], "model", row["grounds"]))
            status = "completed"
        elif not selected:
            status = "local_evidence"
    except Exception as exc:  # noqa: BLE001
        status, detail = "failed", type(exc).__name__
    claim_id = f"accounting:{uuid.uuid4().hex}"
    from .ledger.events import read_recorded
    body = {"status": status, "error": detail, "prompt": prompt,
            "request": getattr(result, "request", {}), "response": getattr(result, "response", {}),
            "text": result if isinstance(result, str) else getattr(result, "text", ""),
            "research": research_capability(), "deferred": max(0, len(unresolved) - MAX_ITEMS)}
    if plans or prompt or status == "failed":
        ledger.append(read_recorded(doc_id=claim_id,
            model=os.environ.get("VIVA_MODEL", ""), resolved_model=getattr(result, "resolved_model", ""),
            prompt_version=version, input_mode="text", response_text=json.dumps(body, sort_keys=True),
            cost_usd=getattr(result, "cost_usd", 0), input_tokens=getattr(result, "input_tokens", 0),
            output_tokens=getattr(result, "output_tokens", 0), parse_ok=status != "failed",
            parse_error=detail or None, occurred_at=_today(), phase="accounting"))
    for movement, majors, by, grounds in plans:
        ledger.append(ruling_recorded(SCOPE_MOVEMENT, movement.key, _today(),
            legs=[{"major": major, "account": MAJOR_UNCATEGORIZED[major], "share": ""} for major in majors],
            by=by, grade=UNVERIFIED, prompt_version=version, grounds=grounds,
            source_refs=[claim_id, movement.provenance.doc_id],
            evidence_signature=signatures[movement.key], provenance=Provenance(doc_id=claim_id)))
    return {"status": status, "applied": len(plans), "learned": learned,
            "deferred": max(0, len(unresolved) - MAX_ITEMS), "research": research_capability()}


def correct_accounting(vault, said: str, movement_keys: list[str], interpret_fn=None):
    """Interpret a selected correction; selection is resolved locally before send."""
    from . import engine
    from .listen import ruling_from, ruling_slots
    from .reply import interpret, read_reply
    proj = vault.ledger.projection()
    held = {m.key: m for m in proj.movements()}
    selected = list(dict.fromkeys(movement_keys))
    if not selected or any(key not in held for key in selected):
        return {"ok": False, "why": "movement_required", "message": "Select the transaction you want to explain."}
    extractor = interpret_fn or engine._interpreter()
    slots = ruling_slots()
    filled = interpret(said, slots, extract_fn=extractor,
                       context=(("selected_transactions", str(len(selected))),))
    parsed = read_reply(slots, filled.values)
    parsed.version = filled.version
    engine._record_interpret(vault, extractor, "", said, parsed)
    if filled.failure or not parsed.ok:
        return {"ok": False, "why": filled.failure or parsed.why,
                "message": "I could not interpret that explanation. Your transactions are unchanged."}
    interp = ruling_from(parsed, said)
    if not interp.legs:
        return {"ok": False, "why": "empty", "message": "I could not identify an accounting treatment in that explanation."}
    if interp.ends and interp.starts and interp.ends < interp.starts:
        return {"ok": False, "why": "invalid_scope", "message": "The ending date precedes the starting date. Your transactions are unchanged."}
    anchor = held[selected[0]]
    result = engine.record_ruling(vault, interp, anchor.description,
        movement_key=anchor.key if len(selected) == 1 else "", movements=selected,
        amount=str(abs(anchor.amount)), currency=anchor.currency)
    if result.get("ok") and not result.get("confirm"):
        result["message"] = (f"Updated {len(selected)} transaction(s). "
            + ("I will use this explanation for matching future activity. " if result.get("rule_id") else "This change applies to your selection. ")
            + "You can undo this correction.")
    return result


def undo_accounting(vault, correction_id: str):
    result = undo_correction(vault.ledger, correction_id)
    result["message"] = "Undid that accounting correction." if result["ok"] else "That correction was not found."
    return result
