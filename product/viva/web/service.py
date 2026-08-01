"""The surface's service layer — functions from a vault to JSON payloads.

Separate from the HTTP plumbing in `server`, so every endpoint's behaviour is
testable without a socket. Each function reads or acts on the vault and returns
plain dicts of JSON-safe values; money is carried as strings, never floats.

Figures, grades and coverage come from the answer path. Provenance is present in
every payload but the page renders it only where it is asked for.
"""

from __future__ import annotations

import logging
from decimal import Decimal

from ..answer import answer_spending, answer_total, coverage_summary
from ..ingest import (SEED_CATEGORIES, apply_human_correction,
                      apply_identity_ruling, assign_category,
                      assign_merchant_category, capture_and_ingest,
                      confirm_transfer, held_items, other_holds,
                      reject_transfer)
from ..ingest.identity import masked
from ..ledger.merchants import normalize_merchant as normalize
from ..ledger import UnknownAccountError
from ..vault import Vault

log = logging.getLogger("viva.web.service")


def overview(vault: Vault) -> dict:
    """The dashboard payload: total, accounts with their grades, coverage,
    spending and income, holdings, and the counts of items awaiting review."""
    proj = vault.ledger.projection()             # the cached live projection
    total = answer_total(proj)
    accounts = []
    for info in proj.account_infos():
        if info.kind not in ("depository", "liability", "investment"):
            continue
        ba = proj.balance(info.account)
        liability = info.kind == "liability"
        investment = info.kind == "investment"
        # An investment account's headline is its total value — cash plus the
        # latest measured holdings — rather than the cash balance alone.
        amount = proj.account_value(info.account) if investment else (
            abs(ba.amount) if liability else ba.amount)
        row = {
            "account": info.account, "name": info.name or info.account,
            "currency": info.currency,
            # A liability's balance is money owed, sent as a positive magnitude
            # for the page to label; `liability` below says which it is.
            "amount": str(amount),
            "kind": info.kind, "liability": liability, "investment": investment,
            "grade": ba.grade, "as_of": ba.dated,
            "institution": info.institution, "number": masked(info.number),
            "holders": info.names}
        if investment:
            ug = proj.unrealized_gain(info.account)
            as_of, mixed = proj.holdings_as_of(info.account)
            row["holdings"] = str(proj.holdings_value(info.account))
            row["cash"] = str(proj.cash_value(info.account))
            row["unrealized_gain"] = str(ug) if ug is not None else None
            # A composed total is as of its oldest part; `mixed_as_of` says
            # whether the parts carry different dates.
            row["as_of"] = as_of or row["as_of"]
            row["mixed_as_of"] = mixed
        accounts.append(row)
    income = proj.income_by_currency()
    pending_paystubs = [b for b in proj.open_holds()
                        if "gross" in b.get("facts", {})]
    return {
        "total": total.to_dict(),
        "accounts": accounts,
        "coverage": coverage_summary(proj).text,
        "spending": answer_spending(proj).to_dict(),
        "spending_by_category": {c: str(a) for c, a
                                 in proj.spending_by_category().items()},
        # How much of the spending figure rests on weak evidence, alongside
        # what was left out of it and why.
        "provisional_spending": str(proj.provisional_spending()),
        # Money whose components are known but whose proportions are not. Its own
        # line rather than part of spending, which would overstate, or dropped,
        # which would understate.
        "undecomposed": {k: (str(v) if not isinstance(v, list) else v)
                         for k, v in proj.undecomposed().items()},
        # The accounts a person's own rulings brought into being.
        "ruled_accounts": [
            {**row, "paid": str(row["paid"])}
            for row in sorted(proj.ruled_accounts().values(),
                              key=lambda r: -r["paid"])],
        "excluded_from_spending": [
            {"description": m.description, "amount": str(abs(m.amount)),
             "account": m.account, "date": m.date, "reason": m.nature_reason,
             "nature": m.nature, "provisional": m.provisional}
            for m in proj.excluded_from_spending()],
        "spending_by_subcategory": {c: str(a) for c, a
                                    in proj.spending_by_subcategory().items()},
        "income": {c: str(v) for c, v in income.items()},
        "income_breakdown": _income_breakdown(proj),
        "positions": [p.to_dict() for p in proj.positions()],
        "review_count": len(held_items(proj)),
        # Held documents with no correction affordance yet (pay stub, brokerage),
        # listed so nothing being held is invisible.
        "other_holds": other_holds(proj),
        "transfer_review_count": len(proj.transfer_suggestions()),
        "paystub_review_count": len(pending_paystubs),
        "uncategorized_count": len(proj.uncategorized_expenses()),
        "unknown_merchant_count": len(proj.uncategorized_merchants()),
    }


def _income_breakdown(proj) -> list[dict]:
    """The deduction buckets carrying a balance, as `[{label, amount}]`.

    Empty buckets and accounts that do not exist are omitted, so the list may be
    empty."""
    from ..ledger.postings import DEDUCTION_ACCOUNTS
    rows = []
    for label, account in [("Retirement", DEDUCTION_ACCOUNTS["retirement"]),
                           ("Tax", DEDUCTION_ACCOUNTS["tax"]),
                           ("Insurance", DEDUCTION_ACCOUNTS["insurance"]),
                           ("Other withheld", DEDUCTION_ACCOUNTS["other"])]:
        try:
            amt = proj.balance(account).amount
        except UnknownAccountError:
            continue
        if amt:
            rows.append({"label": label, "amount": str(amt)})
    return rows


def questions(vault: Vault, limit: int = 10) -> dict:
    """The ranked list of open questions, highest stake first.

    Returns at most `limit` questions plus a summary of the tail."""
    from ..questions import open_questions
    return open_questions(vault.ledger, limit=limit)


# `rule_major` below is the only answer path. The projection still replays
# `MerchantNatureRuled` events in existing vaults, but nothing here writes them.


def net_worth(vault: Vault, as_of: str = "", curve: bool = False) -> dict:
    """Net worth from the projection. Reads only — no model, no writes.

    An empty `as_of` means the latest date there is evidence for. With `curve`
    true, returns `{"points": [...]}` — every point in the series — instead of a
    single point."""
    from ..ledger.networth import net_worth as _net_worth
    from ..ledger.networth import series
    proj = vault.ledger.projection()
    if curve:
        return {"points": [p.to_dict() for p in series(proj)]}
    return _net_worth(proj, as_of or None).to_dict()


def rule_major(vault: Vault, merchant: str, major: str, descriptor: str = "",
               kind: str = "", movement_key: str = "", group: str = "",
               name: str = "") -> dict:
    """Answer with one of the four majors — the button path.

    Deterministic: no model is involved, so this works with nothing configured.
    It goes through the same `propose` / `apply_proposal` pair as `listen_to`, so
    a tapped answer and a typed one produce identical events.

    **A tap never opens an account.** Where the answer would bring one into
    being, the proposal comes back for confirmation with the name the person
    would see, and existing accounts are offered first. Where the answer names
    nothing at all, the reply is the question rather than a placeholder path.
    Only an answer that changes nothing structural applies in this request."""
    from ..listen import Interpretation, apply_proposal, propose
    proj = vault.ledger.projection()
    interp = Interpretation(
        legs=[{"major": major,
               "account_hint": name or group or descriptor or merchant,
               "share": ""}],
        kind=kind, said=name)
    # A `movement_key` scopes the answer to one transaction rather than to every
    # movement sharing the descriptor. The unknown tier — a cheque, an ATM
    # withdrawal, a peer — is asked one at a time for that reason.
    proposal = propose(proj, interp, descriptor or merchant,
                       movement_key=movement_key)
    if proposal.needs_name:
        return {"ok": False, "why": "needs_name",
                "message": proposal.summary(),
                "proposal": proposal.to_dict()}
    if proposal.new_accounts or proposal.confirm_accounts:
        return {"ok": True, "confirm": True, "proposal": proposal.to_dict()}
    applied = apply_proposal(vault.ledger, proposal, _today())
    return {"ok": True, "confirm": False, **applied}


def _jurisdiction() -> str:
    """The region the vault's locale names, or '' — the one locale accessor,
    reused so the queue and the interview never disagree about where we are."""
    from ..env import jurisdiction_from_env
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


def answer_attribute(vault: Vault, account: str, key: str, value: str = "",
                     said: str = "") -> dict:
    """Record one thing the person told us about an account they hold.

    The answer is read from their own words by the same deterministic parsers
    the document path uses, so a figure that is not in the sentence cannot
    reach the ledger. An answer outside a closed vocabulary — a yes/no that is
    neither, a choice that is none of the offered ones — is refused with the
    alternatives rather than guessed at."""
    from ..interview import interviews
    from ..ledger.events import SCOPE_ATTRIBUTE, VERIFIED, ruling_recorded
    juris = _jurisdiction()
    proj = vault.ledger.projection()
    iv = next((i for i in interviews(proj, juris) if i.account == account), None)
    if iv is None or iv.schema is None:
        return {"ok": False, "why": "no_schema",
                "message": "I don't have a shape for that account yet, so I "
                           "wouldn't know what to do with the answer."}
    question = iv.schema.question(key)
    if question is None:
        return {"ok": False, "why": "unknown_key",
                "message": "That isn't something I ask about this one."}
    spoken = (said or value or "").strip()
    if not spoken:
        return {"ok": False, "why": "empty",
                "message": "Nothing came through — nothing was recorded."}
    parsed = _read_answer(question, spoken, value, iv, proj)
    if not parsed["ok"]:
        return parsed
    vault.ledger.append(ruling_recorded(
        SCOPE_ATTRIBUTE, f"{account}:{key}", _today(), by="human",
        grade=VERIFIED, said=spoken, value=parsed["value"],
        currency=parsed["currency"],
        corroborates=(question.corroborated_by[0]
                      if question.corroborated_by else "")))
    return {"ok": True, "account": account, "key": key,
            "value": parsed["value"], "currency": parsed["currency"]}


def _read_answer(question, spoken: str, tapped: str, iv, proj) -> dict:
    """One answer, read by its type. Returns ``{ok, value, currency}`` or a
    refusal carrying what would have been accepted."""
    from .. import schemas
    from ..env import locale_from_env
    from vivacore.verify.normalize import parse_amount, parse_date
    locale = locale_from_env()
    answer = question.answer

    if answer == schemas.ANSWER_MONEY:
        got = parse_amount(spoken, locale=locale, currency=iv.currency or None)
        if not got.ok:
            return {"ok": False, "why": "unreadable_money",
                    "message": f"I couldn't read that as an amount ({got.reason}). "
                               "Could you write it the way it appears on paper?"}
        return {"ok": True, "value": str(got.decimal()),
                "currency": got.currency or iv.currency or ""}

    if answer == schemas.ANSWER_DATE:
        got = parse_date(spoken, locale=locale)
        if not got.ok:
            return {"ok": False, "why": "unreadable_date",
                    "message": f"I couldn't read that as a date ({got.reason})."}
        return {"ok": True, "value": got.value, "currency": ""}

    if answer == schemas.ANSWER_RATE:
        got = parse_amount(spoken.replace("%", " ").strip(), locale=locale)
        if not got.ok:
            return {"ok": False, "why": "unreadable_rate",
                    "message": "I couldn't read that as a rate."}
        return {"ok": True, "value": str(got.decimal()), "currency": ""}

    if answer in (schemas.ANSWER_YES_NO, schemas.ANSWER_CHOICE):
        allowed = (("yes", "no") if answer == schemas.ANSWER_YES_NO
                   else tuple(question.choices))
        for candidate in (tapped, spoken):
            for option in allowed:
                if str(candidate).strip().lower() == option.lower():
                    return {"ok": True, "value": option, "currency": ""}
        if not allowed:
            return {"ok": False, "why": "no_vocabulary", "choices": [],
                    "message": "I don't know which alternatives apply to you "
                               "here, so I won't pretend to offer any."}
        return {"ok": False, "why": "not_in_vocabulary", "choices": list(allowed),
                "message": "I couldn't tell which of those you meant, and I'd "
                           "rather ask again than guess: "
                           + ", ".join(allowed) + "."}

    if answer == schemas.ANSWER_LINK:
        target = (tapped or spoken).strip()
        if not proj.seen_account(target):
            return {"ok": False, "why": "unknown_account",
                    "message": "I don't have that account on file, so I can't "
                               "link this to it."}
        # And of the kind the schema says this points at.
        target_kind = schemas.kind_of_account(
            target, proj.account_info(target).jurisdiction or _jurisdiction(),
            ledger_kind=proj.account_info(target).kind,
            doc_types=proj.document_types_of(target))
        if question.links_to and target_kind != question.links_to:
            return {"ok": False, "why": "wrong_kind",
                    "message": "That isn't the kind of thing this one can be "
                               "tied to."}
        return {"ok": True, "value": target, "currency": ""}

    # The two free-form types: the person's own word, and a company's name.
    if len(spoken) > schemas.MAX_FREE_FORM:
        return {"ok": False, "why": "too_long",
                "message": "That is longer than a name — a few words is plenty."}
    return {"ok": True, "value": spoken, "currency": ""}


def open_kind(vault: Vault, kind: str, name: str = "", secures: str = "",
              said: str = "") -> dict:
    """Propose the account a yes has opened. Writes nothing.

    A yes to "is there a loan against it?" says the loan exists; it does not
    say what it is called, and this product does not name a person's accounts
    for them. So the reply is either the naming question, or a Proposal that
    creates the account and records what it secures in the same confirmation."""
    from .. import schemas
    from ..listen import Proposal
    from ..ledger.events import SCOPE_ATTRIBUTE
    juris = _jurisdiction()
    schema = schemas.schema_for(kind, juris)
    if schema is None:
        return {"ok": False, "why": "no_schema",
                "message": "I don't have a shape for that kind yet."}
    naming = schema.naming_question()
    if naming is None:
        return {"ok": False, "why": "unnameable",
                "message": "I wouldn't know what to call it."}
    label = (name or said or "").strip()
    if not label:
        return {"ok": False, "why": "needs_name", "asks": naming.asks,
                "key": naming.key, "kind": kind, "kind_label": schema.label}
    if len(label) > schemas.MAX_FREE_FORM:
        return {"ok": False, "why": "too_long",
                "message": "That is longer than a name — a few words is plenty."}
    if not any(ch.isalnum() for ch in label):
        # Punctuation and invisible characters are not a name a person could
        # read back, and an account they cannot read is one they cannot check.
        return {"ok": False, "why": "needs_name", "asks": naming.asks,
                "key": naming.key, "kind": kind, "kind_label": schema.label}
    proj = vault.ledger.projection()
    # Through the same builder the rest of the ledger uses, so a name carrying
    # a colon cannot inject a level into the hierarchy.
    from ..ledger.postings import account_path
    root, _, group = schema.account_shape.partition(":")
    major = {"Assets": "asset", "Liabilities": "liability"}.get(root, "asset")
    account = account_path(major, group, label)
    if len(account.split(":")) < 3:
        # The cleaner dropped every character of the name — punctuation alone
        # is not a name, and what is left is the group.
        return {"ok": False, "why": "needs_name", "asks": naming.asks,
                "key": naming.key, "kind": kind, "kind_label": schema.label}
    if secures and not proj.seen_account(secures):
        return {"ok": False, "why": "unknown_account",
                "message": "I don't have that account on file, so I can't tie "
                           "this to it."}
    existing = [a for a in proj.accounts()
                if a.lower() == account.lower()]
    account = existing[0] if existing else account
    currency = (proj.account_info(secures).currency if secures else "") \
        or _vault_currency(proj)
    if not currency:
        # No account exists to take a currency from, and no country-to-money
        # table exists to invent one.
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
        said=label, value=label, currency=currency, attributes=attributes)
    return {"ok": True, "confirm": True, "proposal": proposal.to_dict()}


def pending(vault: Vault) -> dict:
    """Everything set aside and still open — the list the person opens
    themselves, rather than a question that chases them."""
    from ..questions import pending_questions
    return pending_questions(vault.ledger, as_of=_today()[:10],
                             jurisdiction=_jurisdiction())


def listen_to(vault: Vault, said: str, descriptor: str, movement_key: str = "",
              category: str = "", subcategory: str = "",
              amount: str = "", currency: str = "") -> dict:
    """Read a sentence and return a Proposal. Writes nothing.

    Returns `{"understood": True, "proposal": {...}}`, or
    `{"understood": False, "why": ..., "message": ...}` when the sentence could
    not be read — including when no model is configured. `why` is one of
    `unreachable`, `unparseable`, `too_long`, `empty`. Applying a proposal is a
    separate call to `apply_ruling`."""
    from ..listen import interpret, propose
    proj = vault.ledger.projection()
    # Name the instrument the movement sat in — a card, a brokerage, a loan
    # account — so the prompt does not assume a bank account.
    source = ""
    for m in proj.movements():
        if movement_key and m.key == movement_key:
            source = _describe_source(proj, m.account)
            break
        if not movement_key and normalize(m.description) == normalize(descriptor):
            source = _describe_source(proj, m.account)
            break
    interp = interpret(said, descriptor, category, subcategory, _interpreter(),
                       source=source)
    if not interp.legs:
        # One message per failure kind: an unreachable model, a rambling one and
        # one that did not understand have different causes and different fixes.
        message = {
            "unreachable": "I can't reach my reader right now — the buttons "
                           "still work, and nothing was lost.",
            "unparseable": "I got an answer back but couldn't make sense of it. "
                           "Try fewer words, or use a button.",
            "too_long": "My reader went on far longer than this needs and never "
                        "finished the answer. That's a setting on my side, not "
                        "anything you did — the buttons still work.",
            "empty": "I read that, but couldn't tell what the money became. "
                     "Could you say what happened to it?",
        }.get(interp.failure, "I couldn't read that one — the buttons still work.")
        log.warning("listen: %s (%s) said=%r raw=%r", interp.failure,
                    interp.detail, said, (interp.raw or "")[:400])
        return {"understood": False, "why": interp.failure, "message": message}
    proposal = propose(proj, interp, descriptor, amount, currency, movement_key)
    return {"understood": True, "proposal": proposal.to_dict()}


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


def apply_ruling(vault: Vault, proposal: dict) -> dict:
    """Apply a proposal returned by `listen_to`. The only path from a sentence
    to the ledger. `summary` is dropped; it is display text, not a field."""
    from ..listen import Proposal, apply_proposal
    fields = {k: v for k, v in proposal.items() if k != "summary"}
    return {"ok": True, **apply_proposal(vault.ledger, Proposal(**fields), _today())}


def _today() -> str:
    from datetime import date
    return date.today().isoformat()


def _interpreter():
    """The one-shot extractor that reads a typed sentence, or None.

    Configured per field: `VIVA_INTERPRET_<FIELD>` if set, else the matching
    `VIVA_MODEL_<FIELD>`, so the sentence reader and the document reader can be
    different models. Returns None when neither VIVA_INTERPRET_MODEL nor
    VIVA_MODEL is set; the question queue works without it, because free text is
    an addition to the buttons rather than the only way to answer.

    Pointing `VIVA_INTERPRET_BASE_URL` at a local server (Ollama, LM Studio) with
    `VIVA_INTERPRET_KEY_ENV=none` keeps typed sentences on the machine."""
    import os

    def cfg(field, default=None):
        return (os.environ.get(f"VIVA_INTERPRET_{field}")
                or os.environ.get(f"VIVA_MODEL_{field}" if field != "MODEL" else "VIVA_MODEL")
                or default)

    model = os.environ.get("VIVA_INTERPRET_MODEL") or os.environ.get("VIVA_MODEL")
    if not model:
        return None
    from vivacore.models import ModelSpec

    from ..listen import one_shot_extractor
    # "none" or empty declares a keyless endpoint, so no API key is looked up.
    key_env = cfg("KEY_ENV", "OPENROUTER_API_KEY")
    return one_shot_extractor(ModelSpec(
        name="viva-listen", adapter=cfg("ADAPTER", "openai-compatible"),
        model=model, base_url=cfg("BASE_URL"),
        api_key_env=None if (key_env or "").lower() in ("", "none") else key_env,
        # The answer itself is ~60 tokens; the headroom is for models that
        # reason before answering, which the reply parser reads past.
        max_tokens=1024, json_mode=True))


def categorize_review(vault: Vault, limit: int = 50) -> dict:
    """The categorization queue: up to `limit` uncategorized expense movements,
    with the seed categories to choose from."""
    proj = vault.ledger.projection()
    items = []
    for m in proj.uncategorized_expenses()[:limit]:
        items.append({"key": m.key, "descriptor": m.description,
                      "amount": str(abs(m.amount)), "currency": m.currency,
                      "date": m.date, "account": m.account})
    return {"items": items, "categories": list(SEED_CATEGORIES)}


def merchant_transactions(vault: Vault, merchant: str, limit: int = 200) -> dict:
    """Every movement with one merchant — the context behind a question.

    Matched on the normalized merchant, the same unit a ruling generalizes over,
    and drawn from every movement rather than from the categorization queue,
    which holds only uncategorized ones.

    Amounts stay signed as the account recorded them, and each row carries a
    kind-aware `direction` ("out" or "in"). The summary is three figures —
    `money_out`, `money_in`, `net` — because a single total over a counterparty
    money flows both ways with adds the two directions together.
    See docs/net-worth.md on what abs() discards.

    Returns at most `limit` items; `count` is the full number matched."""
    from ..ledger.merchants import normalize_merchant
    proj = vault.ledger.projection()
    key = normalize_merchant(merchant)

    def _direction(m) -> str:
        # Money toward this counterparty ("out") or from it ("in"). An asset-side
        # account records an outflow negative; a liability records a charge —
        # money out to the merchant — positive, so the sign alone is not enough.
        if m.kind == "liability":
            return "out" if m.amount > 0 else "in"
        return "out" if m.amount < 0 else "in"

    items = []
    for m in proj.movements():
        # Any key this counterparty is filed under matches: a merchant named by
        # a grammar's brand slot and the same merchant named by its raw
        # descriptor are one counterparty, and a person asking about it by
        # either name means the same thing.
        if key not in proj.merchant_keys_of(m):
            continue
        ruling = proj.derived_category(m) or {}
        items.append({
            "key": m.key, "date": m.date, "description": m.description,
            "amount": str(m.amount), "currency": m.currency,
            "direction": _direction(m),
            "account": m.account,
            "category": ruling.get("category", ""),
            "subcategory": ruling.get("subcategory", ""),
            "nature": m.nature, "counts_as_spending": proj._counts_as_spending(m),
            "tags": proj.tags_of(m)})
    items.sort(key=lambda i: i["date"])
    zero = Decimal("0")
    money_out = sum((abs(Decimal(i["amount"])) for i in items
                     if i["direction"] == "out"), zero)
    money_in = sum((abs(Decimal(i["amount"])) for i in items
                    if i["direction"] == "in"), zero)
    return {"merchant": key, "items": items[:limit], "count": len(items),
            # `net` is out minus in: positive means money went, on balance,
            # toward this counterparty.
            "money_out": str(money_out), "money_in": str(money_in),
            "net": str(money_out - money_in),
            "currency": items[0]["currency"] if items else "",
            "categories": list(SEED_CATEGORIES),
            # The tags already in use, so the surface can offer them before a
            # new one is minted.
            "known_tags": proj.known_tags(),
            "merchant_tags": proj._merchant_tags.get(key, [])}


def tag(vault: Vault, subject: str, tags: list, scope: str = "movement") -> dict:
    """Tag one movement, or every movement from a merchant.

    ``tags`` is the complete set for that subject, not an addition: removing a
    tag means sending the set without it. Returns the normalized set that was
    stored (stripped, lower-cased, sorted, blanks dropped)."""
    from ..ingest import tag_merchant, tag_movement
    if scope == "merchant":
        tag_merchant(vault.ledger, subject, tags, by="human")
    else:
        tag_movement(vault.ledger, subject, tags, by="human")
    return {"ok": True, "tags": sorted({t.strip().lower() for t in tags if t.strip()})}


def assign_category_to(vault: Vault, movement_key: str, category: str) -> dict:
    """A person assigns a category to one movement, at grade `verified`."""
    ok = assign_category(vault.ledger, movement_key, category, by="human")
    return {"ok": ok}


def merchant_review(vault: Vault, limit: int = 50) -> dict:
    """The categorization queue by merchant: uncategorized merchants with the
    number of transactions each covers, most first, capped at `limit`."""
    proj = vault.ledger.projection()
    rows = sorted(proj.uncategorized_merchants().items(),
                  key=lambda kv: kv[1]["count"], reverse=True)
    items = [{"merchant": k, "example": r["example"], "count": r["count"],
              "shareable": r["shareable"]} for k, r in rows[:limit]]
    return {"items": items, "categories": list(SEED_CATEGORIES)}


def assign_merchant(vault: Vault, merchant: str, category: str) -> dict:
    """Categorize a whole merchant at grade `verified`, covering every movement
    that normalizes to it."""
    assign_merchant_category(vault.ledger, merchant, category, by="human")
    return {"ok": True}


def paystub_review(vault: Vault) -> dict:
    """Pay stubs read but not fully posted: waiting for their deposit, or held
    because gross minus deductions did not equal net."""
    from ..ingest import PayStubFacts
    proj = vault.ledger.projection()
    items = []
    for b in proj.open_holds():
        f = b.get("facts", {})
        if "gross" not in f:
            continue
        facts = PayStubFacts.from_dict(f)
        items.append({
            "doc_id": b["doc_id"], "reason": b.get("reason", ""),
            "employer": facts.employer, "currency": facts.currency,
            "pay_date": facts.pay_date,
            "gross": str(facts.gross), "net": str(facts.net),
            "deductions": [d.to_dict() for d in facts.deductions],
            "finding": b.get("finding")})
    return {"items": items}


def transfer_review(vault: Vault) -> dict:
    """Suggested internal transfers awaiting a ruling, in readable form.

    Candidates already linked under another suggestion are dropped, so a movement
    is never offered twice; a suggestion left with no candidates is omitted."""
    proj = vault.ledger.projection()
    by_key = {m.key: m for m in proj.movements()}
    linked = proj.linked_keys()

    def _describe(key: str) -> dict:
        m = by_key.get(key)
        if m is None:
            return {"key": key, "label": key}
        return {"key": key, "account": m.account, "date": m.date,
                "amount": str(m.amount), "description": m.description}

    items = []
    for s in proj.transfer_suggestions():
        cands = [k for k in s.get("candidates", []) if k not in linked]
        if not cands:
            continue                     # nothing left to match against
        items.append({
            "source": _describe(s["a"]),
            "candidates": [_describe(k) for k in cands],
            "evidence": s.get("evidence", {})})
    return {"items": items}


def confirm_transfer_link(vault: Vault, movement_a: str, movement_b: str) -> dict:
    """A person confirms two movements are one transfer, at grade `verified`.

    A no-op returning `{"ok": False}` if either movement is already linked: a
    movement belongs to at most one transfer."""
    made = confirm_transfer(vault.ledger, movement_a, movement_b)
    return {"ok": made}


def reject_transfer_link(vault: Vault, movement_a: str, movement_b: str = "") -> dict:
    """A person dismisses a suggested transfer, revoking the link if one was
    made. Append-only; nothing is deleted."""
    reject_transfer(vault.ledger, movement_a, movement_b)
    return {"ok": True}


def account_view(vault: Vault, account: str) -> dict:
    """One account: its identity, balance and transactions, each carrying its
    provenance. Returns `{"error": "unknown_account", ...}` for an account the
    projection does not hold."""
    proj = vault.ledger.projection()
    try:
        info = proj.account_info(account)
        ba = proj.balance(account)
        lines = proj.transactions(account)
    except UnknownAccountError:
        return {"error": "unknown_account", "account": account}
    return {
        "account": account, "name": info.name or account,
        "currency": info.currency,
        "institution": info.institution, "number": masked(info.number),
        "holders": info.names,
        "balance": ba.to_dict(),
        "transactions": [ln.to_dict() for ln in lines],
    }


def review_list(vault: Vault) -> dict:
    """Everything held awaiting a human ruling."""
    return {"items": [h.to_dict() for h in held_items(vault.ledger.projection())]}


def confirm_correction(vault: Vault, doc_id: str, field: str, value: str,
                       target_index: int | None = None) -> dict:
    """Apply a person's ruling on a held statement and re-post it."""
    res = apply_human_correction(vault.ledger, doc_id, field, value, target_index)
    return {
        "action": res.action, "grade": res.grade, "account": res.account,
        "message": res.message,
    }


def confirm_identity(vault: Vault, doc_id: str, decision: str) -> dict:
    """Apply a person's ruling on an ambiguous account identity ('same' / 'new')."""
    res = apply_identity_ruling(vault.ledger, doc_id, decision)
    return {"action": res.action, "grade": res.grade, "account": res.account,
            "message": res.message}


def greeting(vault: Vault) -> dict:
    """Viva's opening line — a moment from the persona pack.

    The name is derived from the vault's own account holders: the most common
    first token, title-cased, or "" when there are no holders. No model is
    called. An empty vault gets `welcome_empty`, any other `welcome_back`.
    `all_settled` is returned alongside, for the queue card to use when there is
    nothing to ask."""
    from collections import Counter

    from ..persona import ACTIVE_PACK, moment
    proj = vault.ledger.projection()
    firsts: Counter = Counter()
    for info in proj.account_infos():
        for n in info.names:
            tok = (n.split() or [""])[0].strip()
            if tok:
                firsts[tok.title()] += 1
    name = firsts.most_common(1)[0][0] if firsts else ""
    part = f", {name}" if name else ""
    key = "welcome_back" if proj.accounts() else "welcome_empty"
    return {"moment": key, "text": moment(key, name_part=part),
            "all_settled": moment("all_settled", name_part=part),
            "pack": ACTIVE_PACK}


def decline_question(vault: Vault, question_id: str,
                     reason: str = "not_now") -> dict:
    """Record that a question was set aside, and reply in Viva's voice.

    The stake snapshot (amount, count) is read from the live queue rather than
    taken from the caller, so a stale page cannot record the wrong figures.
    Declining a question that is no longer open is a no-op returning
    `{"ok": False}` with a message, not an error."""
    from ..ledger.events import question_declined
    from ..persona import ACTIVE_PACK, moment
    from ..questions import open_questions
    qs = open_questions(vault.ledger, limit=100000)
    q = next((x for x in qs["questions"] if x["id"] == question_id), None)
    if q is None:
        return {"ok": False,
                "message": "That question is no longer open — nothing to set aside."}
    vault.ledger.append(question_declined(
        q["id"], q["kind"], _today(), reason=reason,
        amount=q["amount"], count=q["count"], pack_version=ACTIVE_PACK))
    ack = "dont_know_ack" if reason == "dont_know" else "not_now_ack"
    return {"ok": True, "message": moment(ack, name_part="")}


def upload(vault: Vault, filename: str, data: bytes, read_fn) -> dict:
    """Ingest an uploaded file: capture, read, then post, park or hold.

    Returns the outcome — `action`, `grade`, `doc_type`, `account`,
    `auto_corrected`, `message`, and the `finding` when one was raised."""
    res = capture_and_ingest(vault.raw, vault.ledger, data, read_fn,
                             filename=filename, captured_at=_today())
    return {
        "action": res.action, "grade": res.grade, "doc_type": res.doc_type,
        "account": res.account, "auto_corrected": res.auto_corrected,
        "message": res.message,
        "finding": res.finding.to_dict() if res.finding else None,
    }


def _today() -> str:
    import time
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
