"""Vault actions returning plain, JSON-safe data.

Question replies use checked slots; selected corrections and document actions
use their own validated entry points. Money is returned as strings. Refusals
include a person-facing message and a machine-readable reason."""

from __future__ import annotations

import logging
import json
import uuid

from . import reply
from .env import locale_from_env
from .ingest import (BALANCE_IDENTITY, POSTED, apply_human_correction,
                     apply_identity_ruling, assign_category,
                     assign_merchant_category, capture_and_ingest,
                     confirm_transfer, profile_for, reject_transfer)
from .ledger.merchants import normalize_merchant as normalize
from .persona import moment
from .reply import MAX_REPLY_TOKENS, Slot, read_reply
from .schemas import ANSWER_YES_NO
from .vault import Vault

log = logging.getLogger("viva.engine")


# Question replies


def answer_question(vault: Vault, question_id: str, said: str = "") -> dict:
    """Validate a reply against the current question and dispatch its checked slots.

    The live queue supplies the question and slot types. Missing or stale questions
    and invalid replies return a refusal without applying the requested action."""
    from .questions import find_question
    q = find_question(vault.ledger, question_id, as_of=_today()[:10],
                      jurisdiction=_jurisdiction())
    if q is None:
        return {"ok": False, "why": "not_open",
                "message": moment("reply_question_closed")}
    spoken = (said or "").strip()
    if not spoken:
        return {"ok": False, "why": "empty", "message": moment("reply_empty")}
    if not q.slots:
        return {"ok": False, "why": "not_in_words",
                "message": moment("reply_not_in_words")}
    extractor = _interpreter()
    parsed = reply.answer(
        spoken, q.slots, asked=q.text, context=_context_for(vault, q),
        extract_fn=extractor, currency=q.currency,
        locale=locale_from_env(),
        resolve_link=_link_resolver(vault.ledger.projection(),
                                    _links_to(vault, q)))
    _record_interpret(vault, extractor, q.text, spoken, parsed)
    if not parsed.ok:
        return parsed.to_dict()
    return _write_answer(vault, q, parsed, spoken)


def _write_answer(vault: Vault, q, parsed, spoken: str) -> dict:
    """The write path for one checked answer, chosen by what was asked.

    Every branch here works from validated slot values and writes through the
    writers that already exist. Nothing reads the sentence again."""
    from .questions import (CORROBORATION, EXPECTATION, IDENTITY, INTERVIEW,
                            MERCHANT, NATURE, RHYTHM, TRANSFER)
    refs = q.refs

    if q.kind == IDENTITY:
        if "account_choice" in parsed.values:
            choice = parsed.value("account_choice")
            decision = refs.get("identity_choices", {}).get(choice, "")
            if not decision:
                return {"ok": False, "why": "invalid_identity_choice",
                        "message": moment("reply_question_closed")}
            return confirm_identity(vault, refs["doc_id"], decision)
        # Map the parsed yes/no answer to existing/new account identity.
        same = parsed.value("same_account") == "yes"
        return confirm_identity(vault, refs["doc_id"], "same" if same else "new")

    if q.kind == TRANSFER:
        if parsed.value("same_money") == "yes":
            made = confirm_transfer(vault.ledger, refs["movement"],
                                    refs["candidates"][0])
            if not made:
                # Return the already-settled transfer result without recording another link.
                return {"ok": False, "linked": False, "why": "already_linked",
                        "message": moment("reply_already_linked")}
            return {"ok": True, "linked": True}
        reject_transfer(vault.ledger, refs["movement"])
        return {"ok": True, "linked": False}

    if q.kind == MERCHANT:
        from .question_evidence import decide, group_decision

        projection = vault.ledger.projection()
        members = [m for m in projection.uncategorized_expenses()
                   if projection.merchant_key_of(m) == refs["merchant"]]
        decision = group_decision(decide(m.description, projection.counterparty_kind(m))
                                  for m in members)
        if q.scope != "one" and not decision.generalizes:
            return {"ok": False, "why": "question_changed",
                    "message": moment("reply_question_changed")}
        category = parsed.value("category")
        movement_keys = tuple(refs.get("movements") or ())
        if q.scope == "one":
            # A one-scoped merchant answer assigns the category only to the
            # exact movement population carried by the question.
            for movement_key in movement_keys:
                assign_category(vault.ledger, movement_key, category,
                                by="human")
        else:
            assign_merchant_category(vault.ledger, refs["merchant"],
                                     category, by="human")
        return {"ok": True, "merchant": refs["merchant"],
                "category": category, "scope": q.scope,
                "settled_movements": list(movement_keys)}

    if q.kind == NATURE:
        from .listen import ruling_from
        interp = ruling_from(parsed, spoken)
        return record_ruling(
            vault, interp,
            descriptor=refs.get("descriptor") or refs.get("example", ""),
            # Retain the question's merchant identity and selected movement keys.
            merchant=refs.get("merchant", ""),
            movements=refs.get("movements", ()),
            movement_key=refs.get("movement", ""),
            amount=str(q.amount), currency=q.currency)

    if q.kind == RHYTHM:
        return record_rhythm(
            vault, refs["merchant"], refs["direction"],
            [member.get("period", "") for member in parsed.values.get("periods", [])],
            said=spoken, prompt_version=parsed.version)

    if q.kind in (CORROBORATION, EXPECTATION):
        if parsed.value("have_it") == "yes":
            # Return the document-based resolution message without recording a ruling.
            return {"ok": True, "recorded": False,
                    "document": refs.get("document", ""),
                    "message": moment("reply_document_awaited")}
        return decline_question(vault, q.id, "not_now")

    if q.kind == INTERVIEW:
        if refs.get("opens"):
            # Return clarification for the unnamed target.
            return open_kind(vault, refs["opens"], name=parsed.value("name"),
                             secures=refs.get("account", ""))
        # Retain the checked amount's explicit currency.
        return answer_attribute(vault, refs["account"], refs["key"],
                                value=parsed.value(refs["key"]),
                                currency=parsed.currency(refs["key"]),
                                said=spoken)

    return {"ok": False, "why": "not_in_words",
            "message": moment("reply_not_in_words")}


# Proposal confirmation accepts the same parsed yes-or-no slot as a question.
CONFIRM_SLOT = Slot(name="confirm", type=ANSWER_YES_NO, required=True)


def confirm_proposal(vault: Vault, proposal: dict, said: str = "",
                     asked: str = "") -> dict:
    """Interpret confirmation of a retained proposal and apply an accepted reply.

    A rejected or unrecognized confirmation leaves the financial ledger unchanged.
    The retained proposal supplies the structure to apply."""
    spoken = (said or "").strip()
    if not spoken:
        return {"ok": False, "why": "empty", "message": moment("reply_empty")}
    extractor = _interpreter()
    parsed = reply.answer(spoken, (CONFIRM_SLOT,), asked=asked,
                          extract_fn=extractor, locale=locale_from_env())
    _record_interpret(vault, extractor, asked, spoken, parsed)
    if not parsed.ok:
        return parsed.to_dict()
    if parsed.value("confirm") != "yes":
        # Anything but a yes writes no financial ruling. The conversation layer
        # settles the persisted proposal as set aside.
        return {"ok": True, "confirmed": False,
                "message": moment("reply_not_confirmed")}
    return {"confirmed": True, **apply_ruling(vault, proposal)}


def _record_interpret(vault: Vault, extractor, asked: str, said: str,
                      parsed) -> None:
    """Capture interpretation exchanges as technical outbound evidence."""
    if extractor is None:
        return
    exchanges = list(getattr(extractor, "exchanges", ()))
    if not exchanges:
        return
    from .ledger.events import read_recorded

    spec = getattr(extractor, "spec", None)
    configured_model = str(getattr(spec, "model", "") or "")
    for index, exchange in enumerate(exchanges):
        result = exchange["result"]
        is_last = index == len(exchanges) - 1
        body = {
            "asked": asked,
            "said": said,
            "prompt": exchange["prompt"],
            "request": getattr(result, "request", {}),
            "response": getattr(result, "response", {}),
            "text": getattr(result, "text", "") or "",
        }
        response = getattr(result, "response", {})
        usage = isinstance(response, dict) and isinstance(
            response.get("usage"), dict)
        vault.ledger.append(read_recorded(
            doc_id=f"interpret:{uuid.uuid4().hex}",
            model=configured_model or str(
                getattr(result, "resolved_model", "") or ""),
            resolved_model=str(getattr(result, "resolved_model", "") or ""),
            prompt_version=str(getattr(parsed, "version", "") or ""),
            input_mode="text",
            response_text=json.dumps(body, sort_keys=True, separators=(",", ":")),
            cost_usd=float(getattr(result, "cost_usd", 0.0) or 0.0),
            input_tokens=int(getattr(result, "input_tokens", 0) or 0),
            output_tokens=int(getattr(result, "output_tokens", 0) or 0),
            parse_ok=bool(is_last and getattr(parsed, "ok", False)),
            parse_error=(None if is_last and getattr(parsed, "ok", False)
                         else str(getattr(parsed, "why", "")
                                  or getattr(parsed, "detail", "")
                                  or "retry")),
            occurred_at=_today(), phase="interpret",
            usage_reported=usage))


# Question context and interpretation dependencies


def _context_for(vault: Vault, q) -> tuple:
    """What is already known about this question's subject, as data.

    Only the nature question has anything to add: every other question carries
    its whole subject in the sentence Viva already said."""
    from .listen import ruling_context
    from .questions import NATURE
    if q.kind != NATURE:
        return ()
    refs = q.refs
    descriptor = refs.get("descriptor") or refs.get("example", "")
    return ruling_context(descriptor, refs.get("category", ""),
                          refs.get("subcategory", ""),
                          _source_of(vault, refs, descriptor))


def _source_of(vault: Vault, refs: dict, descriptor: str) -> str:
    """The instrument the movement being ruled on sat in."""
    proj = vault.ledger.projection()
    movement_key = refs.get("movement", "")
    for m in proj.movements():
        if movement_key and m.key == movement_key:
            return _describe_source(proj, m.account)
        if not movement_key and normalize(m.description) == normalize(descriptor):
            return _describe_source(proj, m.account)
    return ""


def _describe_source(proj, account: str) -> str:
    """A plain-language name for the instrument a movement sat in.

    Derived from the account's kind, so a card, a brokerage and a bank account
    each describe themselves. Returns "" for an account that cannot be read."""
    try:
        info = proj.account_info(account)
    except Exception:                              # noqa: BLE001
        return ""
    kind = {"depository": "a bank or cash account", "liability": "a credit account",
            "investment": "an investment account"}.get(info.kind, "an account they hold")
    return f"{info.name or account} — {kind}" if info.name else kind


def _links_to(vault: Vault, q) -> str:
    """The kind of account a link slot on this question may point at, or ""."""
    from .questions import INTERVIEW
    if q.kind != INTERVIEW or not q.refs.get("key"):
        return ""
    question = _schema_question(vault, q.refs["account"], q.refs["key"])
    return question.links_to if question is not None else ""


def _schema_question(vault: Vault, account: str, key: str):
    """The schema's own question for one attribute of one account, or None."""
    from .interview import interviews
    iv = next((i for i in interviews(vault.ledger.projection(), _jurisdiction())
               if i.account == account), None)
    if iv is None or iv.schema is None:
        return None
    return iv.schema.question(key)


def _link_resolver(proj, links_to: str):
    """Return whether a resolved account exists and has the required schema kind.

    An unresolved identity returns false."""
    from . import schemas

    def resolve(target: str) -> str:
        if not proj.seen_account(target):
            return reply.UNKNOWN_ACCOUNT
        info = proj.account_info(target)
        kind = schemas.kind_of_account(
            target, info.jurisdiction or _jurisdiction(),
            ledger_kind=info.kind, doc_types=proj.document_types_of(target))
        return reply.WRONG_KIND if links_to and kind != links_to else ""

    return resolve


def _interpreter():
    """Return a one-shot sentence extractor, or None when no model is configured.

    Field-specific interpretation settings precede matching model settings.
    A configured local base URL can keep sentence interpretation on the machine."""
    import os

    def cfg(field, default=None):
        return (os.environ.get(f"VIVA_INTERPRET_{field}")
                or os.environ.get(f"VIVA_MODEL_{field}" if field != "MODEL" else "VIVA_MODEL")
                or default)

    model = os.environ.get("VIVA_INTERPRET_MODEL") or os.environ.get("VIVA_MODEL")
    if not model:
        return None
    from vivacore.models import ModelSpec

    from .listen import one_shot_extractor
    # "none" or empty declares a keyless endpoint, so no API key is looked up.
    key_env = cfg("KEY_ENV", "OPENROUTER_API_KEY")
    return one_shot_extractor(ModelSpec(
        name="viva-listen", adapter=cfg("ADAPTER", "openai-compatible"),
        model=model, base_url=cfg("BASE_URL"),
        api_key_env=None if (key_env or "").lower() in ("", "none") else key_env,
        # Reserve response tokens for reasoning and multi-value slots.
        # Truncated responses supply no partial slot values.
        max_tokens=MAX_REPLY_TOKENS, json_mode=True))


def _jurisdiction() -> str:
    """The region the vault's locale names, or '' — the one locale accessor,
    reused so the queue and the interview never disagree about where we are."""
    from .env import jurisdiction_from_env
    return jurisdiction_from_env()


def _vault_currency(proj) -> str:
    """The currency this vault keeps its money in, read from the accounts it
    already holds — the most common one, ties broken by name so two reads
    agree. Derived from evidence, never from a country-to-currency table."""
    from collections import Counter
    counts: Counter = Counter(i.currency for i in proj.account_infos()
                              if i.currency)
    if not counts:
        return ""
    best = max(counts.values())
    return sorted(c for c, n in counts.items() if n == best)[0]


def _today() -> str:
    import time
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# Validated write paths


def answer_attribute(vault: Vault, account: str, key: str, value: str = "",
                     said: str = "", currency: str = "") -> dict:
    """Validate and record a checked account-attribute answer.

    Closed choices use the schema vocabulary. Amount values include the currency
    explicitly supplied by the answer; invalid values return a refusal."""
    from .ledger.events import SCOPE_ATTRIBUTE, VERIFIED, ruling_recorded
    proj = vault.ledger.projection()
    from .interview import interviews
    iv = next((i for i in interviews(proj, _jurisdiction())
               if i.account == account), None)
    if iv is None or iv.schema is None:
        return {"ok": False, "why": "no_schema",
                "message": "I don't have a shape for that account yet, so I "
                           "wouldn't know what to do with the answer."}
    question = iv.schema.question(key)
    if question is None:
        return {"ok": False, "why": "unknown_key",
                "message": "That isn't something I ask about this one."}
    spoken = (said or "").strip()
    proposed = (value or "").strip() or spoken
    if not proposed:
        return {"ok": False, "why": "empty", "message": moment("reply_empty")}
    slot = Slot(name=key, type=question.answer, choices=tuple(question.choices),
                required=True, asks=question.asks)
    # Validate the same explicit amount/currency pair supplied by the reply.
    filled = {key: {"value": proposed, "currency": currency} if currency
              else proposed}
    parsed = read_reply((slot,), filled, currency=iv.currency,
                        locale=locale_from_env(),
                        resolve_link=_link_resolver(proj, question.links_to))
    if not parsed.ok:
        return parsed.to_dict()
    try:
        event = ruling_recorded(
            SCOPE_ATTRIBUTE, f"{account}:{key}", _today(), by="human",
            grade=VERIFIED, said=spoken or proposed, value=parsed.value(key),
            currency=parsed.currency(key),
            corroborates=(question.corroborated_by[0]
                          if question.corroborated_by else ""))
    except ValueError:
        # Refuse an attribute figure absent from the submitted sentence.
        log.info("attribute %s:%s refused by the ledger's figure guard",
                 account, key)
        return {"ok": False, "why": "figure_not_said",
                "message": moment("reply_figure_not_said")}
    vault.ledger.append(event)
    return {"ok": True, "account": account, "key": key,
            "value": parsed.value(key), "currency": parsed.currency(key)}


def record_rhythm(vault: Vault, merchant: str, direction: str, periods,
                  said: str = "", prompt_version: str = "") -> dict:
    """Record one counterparty-direction arrangement with its supplied periodicities.

    An answer with no periodicity returns a refusal without recording a ruling."""
    from .ledger.events import (SCOPE_RHYTHM, VERIFIED, periodicities_in,
                                periodicity_value, rhythm_subject,
                                ruling_recorded)
    value = periodicity_value(periods)
    if not value:
        return {"ok": False, "why": "unanswered",
                "message": moment("reply_unanswered")}
    vault.ledger.append(ruling_recorded(
        SCOPE_RHYTHM, rhythm_subject(merchant, direction), _today(),
        by="human", grade=VERIFIED, said=said, value=value,
        prompt_version=prompt_version))
    return {"ok": True, "merchant": merchant, "direction": direction,
            "periods": list(periodicities_in(value))}


def record_ruling(vault: Vault, interp, descriptor: str = "",
                  movement_key: str = "", amount: str = "",
                  currency: str = "", merchant: str = "", movements=(),
                  ordinary_counterpart: bool = False) -> dict:
    """Resolve a checked interpretation into a proposal or selected correction.

    ``merchant`` and ``movements`` retain a question's identity and selection;
    without them the descriptor supplies the derived population. Unambiguous
    selected corrections apply immediately. Missing or ambiguous account identity
    returns clarification. Private future learning retains its scoped context."""
    from .listen import MovementSelectionRequired, propose
    proj = vault.ledger.projection()
    # An explicit movement key scopes the correction to one transaction.
    try:
        explicit_key = movement_key or (next(iter(movements), "") if movements else "")
        proposal = propose(proj, interp, descriptor, amount, currency,
                           explicit_key, locale=locale_from_env(),
                           merchant_key=merchant, movements=movements,
                           ordinary_counterpart=ordinary_counterpart)
    except MovementSelectionRequired:
        return {"ok": False, "why": "movement_required",
                "message": moment("reply_select_transaction")}
    if proposal.needs_name:
        return {"ok": False, "why": "needs_name",
                "message": proposal.summary(),
                "proposal": proposal.to_dict()}
    if proposal.confirm_accounts:
        return {"ok": False, "why": "account_required",
                "message": "Several accounts could match that explanation. Identify the account to change.",
                "proposal": proposal.to_dict()}
    from .accounting_intelligence import correction_targets, save_correction
    selected = correction_targets(proj, descriptor, movement_key, movements)
    if not selected:
        return {"ok": False, "why": "movement_required",
                "message": moment("reply_select_transaction")}
    previous = {key: {"ruling": next((r for r in proj.rulings("movement")
                         if r["subject"] == key), {}),
                      "category": dict(proj._core._categories.get(key, {}))} for key in selected}
    from .accounting_intelligence import context_key
    anchor = next(m for m in proj.movements() if m.key == selected[0])
    original_context = context_key(proj, anchor)
    if interp.ends and (interp.starts or anchor.date) > interp.ends:
        return {"ok": False, "why": "invalid_scope", "message": "The ending date precedes the starting date."}
    from .ledger.events import accounting_rule_recorded, accounting_correction_recorded
    try:
        if interp.future_scope != "one" and interp.said.strip() and original_context["party"]:
            accounting_rule_recorded("validation", anchor.key, anchor.date, original_context,
                proposal.legs, _today(), category=proposal.category,
                starts=interp.starts or anchor.date, ends=interp.ends,
                recurrence=interp.recurrence, said=interp.said, prompt_version=interp.version)
        accounting_correction_recorded("validation", "", selected, previous,
            proposal.legs, interp.said, _today(), context=original_context)
    except ValueError:
        return {"ok": False, "why": "invalid_scope", "message": "That correction has an invalid future scope. Your transactions are unchanged."}
    scoped_proposals = [propose(proj, interp, descriptor, amount, currency, key,
                        locale=locale_from_env(), merchant_key=merchant,
                        ordinary_counterpart=ordinary_counterpart) for key in selected]
    if any(not scoped.applicable or scoped.confirm_accounts for scoped in scoped_proposals):
        return {"ok": False, "why": "account_required", "message": "Identify the destination account for each selected transaction."}
    accounts_before = set(proj.accounts())
    applied = {}
    for scoped in scoped_proposals:
        applied = apply_ruling(vault, scoped.to_dict())
        if not applied.get("ok"):
            return applied
    correction_id, rule_id = save_correction(vault.ledger, interp, scoped,
                                             selected, previous, original_context,
                                             sorted(set(vault.ledger.projection().accounts()) - accounts_before))
    from .accounting_intelligence import apply_learned_rules
    learned = apply_learned_rules(vault.ledger)
    return {"confirm": False, **applied, "correction_id": correction_id,
            "rule_id": rule_id, "changed": len(selected), "learned": learned}



def open_kind(vault: Vault, kind: str, name: str = "", secures: str = "",
              said: str = "") -> dict:
    """Build a named account proposal or return the missing-name clarification.

    This function writes nothing. The proposal includes the stated secured-account
    relationship when the answer supplies one."""
    from . import schemas
    from .listen import Proposal
    from .ledger.events import SCOPE_ATTRIBUTE
    juris = _jurisdiction()
    schema = schemas.schema_for(kind, juris)
    if schema is None:
        return {"ok": False, "why": "no_schema",
                "message": "I don't have a shape for that kind yet."}
    naming = schema.naming_question()
    if naming is None:
        return {"ok": False, "why": "unnameable",
                "message": "I wouldn't know what to call it."}

    def needs_name() -> dict:
        return {"ok": False, "why": "needs_name", "asks": naming.asks,
                "message": moment("reply_needs_name", asks=naming.asks),
                "key": naming.key, "kind": kind, "kind_label": schema.label}

    label = (name or said or "").strip()
    if not label:
        return needs_name()
    if len(label) > schemas.MAX_FREE_FORM:
        return {"ok": False, "why": "too_long",
                "message": moment("reply_too_long")}
    if not any(ch.isalnum() for ch in label):
        # Remove punctuation and invisible characters from the proposed name.
        return needs_name()
    proj = vault.ledger.projection()
    # Build a hierarchy-safe account path from the cleaned name.
    from .ledger.postings import account_path
    root, _, group = schema.account_shape.partition(":")
    major = {"Assets": "asset", "Liabilities": "liability"}.get(root, "asset")
    account = account_path(major, group, label)
    if len(account.split(":")) < 3:
        # Return clarification when cleaning leaves no account name.
        return needs_name()
    if secures and not proj.seen_account(secures):
        return {"ok": False, "why": "unknown_account",
                "message": moment("reply_unknown_account")}
    existing = [a for a in proj.accounts()
                if a.lower() == account.lower()]
    account = existing[0] if existing else account
    currency = (proj.account_info(secures).currency if secures else "") \
        or _vault_currency(proj)
    if not currency:
        # Require an explicit currency when no existing account supplies one.
        return {"ok": False, "why": "no_currency",
                "message": "I don't know what currency to record this in yet — "
                           "add a statement first, and I'll follow it."}
    attributes = []
    # The link whose `links_to` matches the secured account's kind, if any.
    secured_kind = (schemas.kind_of_account(
        secures, proj.account_info(secures).jurisdiction or juris,
        ledger_kind=proj.account_info(secures).kind,
        doc_types=proj.document_types_of(secures)) if secures else "")
    link = next((q for q in schema.questions
                 if q.answer == schemas.ANSWER_LINK
                 and q.links_to == secured_kind), None)
    if link is not None:
        attributes.append({"key": link.key, "value": secures, "currency": "",
                           "said": secures})
    proposal = Proposal(
        scope=SCOPE_ATTRIBUTE, subject=f"{account}:{naming.key}",
        new_accounts=[] if existing else [account],
        corroborates=(naming.corroborated_by[0]
                      if naming.corroborated_by else ""),
        said=label, value=label, currency=currency, attributes=attributes,
        locale=locale_from_env())
    return {"ok": True, "confirm": True, "proposal": proposal.to_dict()}


def apply_ruling(vault: Vault, proposal: dict) -> dict:
    """Apply a resolved nature proposal and return its plain-data outcome.

    ``summary`` is display text and is not recorded as a financial field."""
    from .listen import InvalidAccountRegistration, Proposal, apply_proposal
    fields = {k: v for k, v in proposal.items() if k != "summary"}
    try:
        applied = apply_proposal(vault.ledger, Proposal(**fields), _today())
    except InvalidAccountRegistration:
        return {"ok": False, "why": "invalid_proposal",
                "message": moment("reply_invalid_proposal")}
    return {"ok": True, **applied}


def decline_question(vault: Vault, question_id: str,
                     reason: str = "not_now") -> dict:
    """Record a live question's set-aside event using its current stake snapshot.

    A question no longer open returns ``ok=False`` and ``why=not_open``."""
    from .ledger.events import question_declined
    from .persona import ACTIVE_PACK
    from .questions import find_question
    requested = find_question(vault.ledger, question_id)
    q = requested.to_dict() if requested else None
    if q is None:
        return {"ok": False, "why": "not_open",
                "message": "That question is no longer open — nothing to set aside."}
    vault.ledger.append(question_declined(
        q["id"], q["kind"], _today(), reason=reason,
        amount=q["amount"], count=q["count"], pack_version=ACTIVE_PACK))
    ack = "dont_know_ack" if reason == "dont_know" else "not_now_ack"
    # Return the set-aside disposition separately from an answered question.
    return {"ok": True, "disposition": "set_aside",
            "message": moment(ack, name_part="")}


def tag(vault: Vault, subject: str, tags: list, scope: str = "movement") -> dict:
    """Tag one movement, or every movement from a merchant.

    ``tags`` is the complete set for that subject, not an addition: removing a
    tag means sending the set without it. Returns the normalized set that was
    stored (stripped, lower-cased, sorted, blanks dropped)."""
    from .ingest import tag_merchant, tag_movement
    if scope == "merchant":
        tag_merchant(vault.ledger, subject, tags, by="human")
    else:
        tag_movement(vault.ledger, subject, tags, by="human")
    return {"ok": True, "tags": sorted({t.strip().lower() for t in tags if t.strip()})}


def assign_category_to(vault: Vault, movement_key: str, category: str) -> dict:
    """A person assigns a category to one movement, at grade `verified`."""
    ok = assign_category(vault.ledger, movement_key, category, by="human")
    return {"ok": ok}


def assign_merchant(vault: Vault, merchant: str, category: str) -> dict:
    """Categorize a whole merchant at grade `verified`, covering every movement
    that normalizes to it."""
    assign_merchant_category(vault.ledger, merchant, category, by="human")
    return {"ok": True}


def confirm_correction(vault: Vault, doc_id: str, field: str, value: str,
                       target_index: int | None = None) -> dict:
    """Apply a person's ruling on a held statement and re-post it."""
    posted_before = vault.ledger.projection().posted_doc_ids()
    res = apply_human_correction(vault.ledger, doc_id, field, value, target_index)
    _finalize_new_documents(vault, posted_before)
    return {
        "action": res.action, "grade": res.grade, "account": res.account,
        "message": res.message,
    }


def confirm_identity(vault: Vault, doc_id: str, decision: str) -> dict:
    """Apply a person's account-identity ruling."""
    posted_before = vault.ledger.projection().posted_doc_ids()
    res = apply_identity_ruling(vault.ledger, doc_id, decision)
    _finalize_new_documents(vault, posted_before)
    return {"ok": res.action == POSTED, "action": res.action, "grade": res.grade,
            "account": res.account, "message": res.message}


def _finalize_new_documents(vault: Vault, posted_before: set[str]) -> None:
    """Apply priors and complete merchant enrichment before review is read."""
    projection = vault.ledger.projection()
    captured_types = projection.captured_docs()
    newly_posted = projection.posted_doc_ids() - posted_before
    from .enrich import enrich_live_merchants, sync_installed_merchants
    from .ingest import assign_default_categories
    for doc_id in sorted(newly_posted):
        profile = profile_for(captured_types.get(doc_id, ""))
        if profile is not None and profile.identity == BALANCE_IDENTITY:
            sync_installed_merchants(vault, doc_id)
        assign_default_categories(vault.ledger, doc_id)
    if newly_posted:
        # Complete bounded enrichment before reading newly posted activity.
        try:
            enrich_live_merchants(vault)
        except Exception:  # noqa: BLE001
            # Semantic enrichment cannot hold a reconciled statement.
            log.exception("merchant enrichment did not complete")
    from .accounting_intelligence import interpret_activity
    interpret_activity(vault)


def upload(vault: Vault, filename: str, data: bytes, read_fn, *,
           on_captured=None, before_read=None) -> dict:
    """Ingest an uploaded file: capture, read, then post, park or hold.

    Returns the outcome — `action`, `grade`, `doc_type`, `account`,
    `auto_corrected`, `message`, and the `finding` when one was raised."""
    posted_before = vault.ledger.projection().posted_doc_ids()
    res = capture_and_ingest(vault.raw, vault.ledger, data, read_fn,
                             filename=filename, captured_at=_today(),
                             on_captured=on_captured, before_read=before_read)
    # Every posted movement leaves ingestion with a complete two-level claim.
    _finalize_new_documents(vault, posted_before)
    projection = vault.ledger.projection()
    attempted = res.doc_id in projection.read_attempted_docs()
    parsed = res.doc_id in projection.read_parsed_docs()
    reading = ("read" if parsed else "read_yielded_nothing" if attempted
               else "never_read")
    return {
        "doc_id": res.doc_id, "action": res.action, "reading": reading,
        "grade": res.grade, "doc_type": res.doc_type,
        "account": res.account, "auto_corrected": res.auto_corrected,
        "message": res.message,
        "finding": res.finding.to_dict() if res.finding else None,
    }
