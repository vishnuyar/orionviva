"""What a person can do to a vault, as functions from a vault to plain data.

The other half of `viva/questions.py`. That module builds what is asked; this one
takes what a person said back and records it. `answer_question` is the single
inbound door — one question, one sentence, one reply — and every write path
beneath it works from values that have already been checked against the slot
types the question declared.

It sits beside the vault rather than under any surface. A terminal and any
future presentation layer call the same functions, and neither imports the
other: nothing here renders a page, holds a session, or knows what a caller
intends to draw. Every return is plain dicts of JSON-safe values; money is
carried as strings, never floats; a refusal carries Viva's own words for the
person and a machine reason beside them for a log.
"""

from __future__ import annotations

import logging

from . import reply
from .env import locale_from_env
from .ingest import (apply_human_correction, apply_identity_ruling,
                     assign_category, assign_merchant_category,
                     capture_and_ingest, confirm_transfer, reject_transfer)
from .ledger.merchants import normalize_merchant as normalize
from .persona import moment
from .reply import MAX_REPLY_TOKENS, Slot, read_reply
from .schemas import ANSWER_YES_NO
from .vault import Vault

log = logging.getLogger("viva.engine")


# ------------------------------------------------------------- the one door


def answer_question(vault: Vault, question_id: str, said: str = "") -> dict:
    """One reply to one question, read into the slots that question declared.

    The single inbound door, and the only one: there is no button path and no
    second way in. The question says what structure an answer to it has; the
    model fills those slots from what the person actually wrote; deterministic
    code checks every value against its slot's type; and only then does a write
    path run. A value that does not survive the check is asked again in Viva's
    voice rather than coerced into something nobody stated.

    The question is looked up in the live queue rather than taken from the
    caller, so a stale caller cannot answer something that is no longer being
    asked, or answer it with slots it is no longer being asked with."""
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
    parsed = reply.answer(
        spoken, q.slots, asked=q.text, context=_context_for(vault, q),
        extract_fn=_interpreter(), currency=q.currency,
        locale=locale_from_env(),
        resolve_link=_link_resolver(vault.ledger.projection(),
                                    _links_to(vault, q)))
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
        # Yes means the statement belongs to an account already held; no means
        # it opens one of its own. Which word stands for which ruling is decided
        # here, in code, rather than offered to a person as a machine value.
        same = parsed.value("same_account") == "yes"
        return confirm_identity(vault, refs["doc_id"], "same" if same else "new")

    if q.kind == TRANSFER:
        if parsed.value("same_money") == "yes":
            made = confirm_transfer(vault.ledger, refs["movement"],
                                    refs["candidates"][0])
            if not made:
                # A movement belongs to at most one transfer, so the pair was
                # already settled. That is a thing to say in Viva's voice — a
                # reply that recorded nothing and carries no sentence reads to a
                # caller as one she could not understand.
                return {"ok": False, "linked": False, "why": "already_linked",
                        "message": moment("reply_already_linked")}
            return {"ok": True, "linked": True}
        reject_transfer(vault.ledger, refs["movement"])
        return {"ok": True, "linked": False}

    if q.kind == MERCHANT:
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
            # The identity this question was asked under, and the movements
            # it grouped, travel with the answer: what a person was shown is
            # then what the answer speaks about, rather than something derived
            # a second time from a raw line.
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
            # Nothing to record: the document is what settles this, and saying
            # so is honest where a cheerful "done" would not be.
            return {"ok": True, "recorded": False,
                    "document": refs.get("document", ""),
                    "message": moment("reply_document_awaited")}
        return decline_question(vault, q.id, "not_now")

    if q.kind == INTERVIEW:
        if refs.get("opens"):
            # Nothing to answer about yet: the words NAME the thing.
            return open_kind(vault, refs["opens"], name=parsed.value("name"),
                             secures=refs.get("account", ""))
        # The currency goes with the value. An amount that arrived at the door
        # in one currency must not reach the ledger in another.
        return answer_attribute(vault, refs["account"], refs["key"],
                                value=parsed.value(refs["key"]),
                                currency=parsed.currency(refs["key"]),
                                said=spoken)

    return {"ok": False, "why": "not_in_words",
            "message": moment("reply_not_in_words")}


# What a confirmation wants back: a yes or a no, and nothing else. A proposal is
# not a question in the queue, so no builder declares this slot for it — but the
# reply to it is read exactly the way every other reply is, which is why a
# person who writes "yes, that's right" is understood and no code here looks at
# the letters they typed.
CONFIRM_SLOT = Slot(name="confirm", type=ANSWER_YES_NO, required=True)


def confirm_proposal(vault: Vault, proposal: dict, said: str = "",
                     asked: str = "") -> dict:
    """The yes or the no that stands between a proposal and the ledger.

    The second half of the same door. An answer that would bring an account into
    being comes back as a proposal rather than a write, and only a reply that
    reads as a yes applies it. A proposal is what an answer WOULD record: it is
    held for the length of this exchange and is never itself written down, so a
    confirmation that never arrives leaves the ledger exactly as it was.

    A reply that reads as neither a yes nor a no is refused in Viva's voice and
    asked again, on the same path as every other reply that does not fill the
    slot its question declared."""
    spoken = (said or "").strip()
    if not spoken:
        return {"ok": False, "why": "empty", "message": moment("reply_empty")}
    parsed = reply.answer(spoken, (CONFIRM_SLOT,), asked=asked,
                          extract_fn=_interpreter(), locale=locale_from_env())
    if not parsed.ok:
        return parsed.to_dict()
    if parsed.value("confirm") != "yes":
        # Anything but a yes writes nothing. The proposal goes out of scope with
        # this reply, so there is nothing to undo and nothing to clean up.
        return {"ok": True, "confirmed": False,
                "message": moment("reply_not_confirmed")}
    return {"confirmed": True, **apply_ruling(vault, proposal)}


# ----------------------------------------------------- what the door needs


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
    """Whether the vault holds the account a link points at, and whether it is
    of the kind the schema says this one may be tied to.

    The type owns the boundary: nobody is ever asked for an account NUMBER, only
    for an account, and an answer that resolves to nothing is refused."""
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
    """The one-shot extractor that reads a typed sentence, or None.

    Configured per field: `VIVA_INTERPRET_<FIELD>` if set, else the matching
    `VIVA_MODEL_<FIELD>`, so the sentence reader and the document reader can be
    different models. Returns None when neither VIVA_INTERPRET_MODEL nor
    VIVA_MODEL is set, and the filler then degrades to the identity: a plainly
    written reply still lands, and everything else is refused rather than
    guessed at.

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

    from .listen import one_shot_extractor
    # "none" or empty declares a keyless endpoint, so no API key is looked up.
    key_env = cfg("KEY_ENV", "OPENROUTER_API_KEY")
    return one_shot_extractor(ModelSpec(
        name="viva-listen", adapter=cfg("ADAPTER", "openai-compatible"),
        model=model, base_url=cfg("BASE_URL"),
        api_key_env=None if (key_env or "").lower() in ("", "none") else key_env,
        # The answer itself is ~60 tokens; the headroom is for models that
        # reason before answering, which the reply parser reads past. A slot
        # holding several of something is a materially harder task than a single
        # value, and a reply cut off mid-reason yields no slots at all rather
        # than partial ones, so the ceiling is set well clear of what any
        # observed reply has needed.
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


# ------------------------------------------------------------ the write paths


def answer_attribute(vault: Vault, account: str, key: str, value: str = "",
                     said: str = "", currency: str = "") -> dict:
    """Record one thing the person told us about an account they hold.

    The interview's write path. It validates what it is about to write against
    the schema's own declared type, so a figure that is in nobody's words cannot
    reach the ledger and an answer outside a closed vocabulary is refused with
    the alternatives rather than guessed at. Checking here as well as at the
    door costs nothing — the check is idempotent — and means the writer never
    trusts a value merely because something upstream said it was fine.

    **An amount arrives as a value AND its currency**, because that is what an
    amount is. Handing the writer a bare figure would let the check behind it
    re-derive a currency from the account, which is how a currency the person
    never said gets into a permanent record."""
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
    # The currency travels WITH the value, in the shape the check reads an
    # amount in, so the second check sees exactly what the first one did — and
    # a currency that disagrees with the account's is refused here too, rather
    # than dropped and re-derived.
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
        # The ledger's own guard: an attribute value may carry no figure the
        # sentence did not. A reading that normalised an amount past what was
        # written is refused here rather than recorded, and the person is asked
        # for the figure in their own words.
        log.info("attribute %s:%s refused by the ledger's figure guard",
                 account, key)
        return {"ok": False, "why": "figure_not_said",
                "message": moment("reply_figure_not_said")}
    vault.ledger.append(event)
    return {"ok": True, "account": account, "key": key,
            "value": parsed.value(key), "currency": parsed.currency(key)}


def record_rhythm(vault: Vault, merchant: str, direction: str, periods,
                  said: str = "", prompt_version: str = "") -> dict:
    """Record what kind of arrangement a person holds with one counterparty,
    one way round.

    The whole answer is one ruling: the subject is the counterparty and the
    direction, and the value carries every periodicity they confirmed. A
    relationship holding a monthly arrangement and an annual one is one subject
    with both, and a correction is a re-answer on that same subject.

    Writes nothing when the reading landed no periodicity, and refuses in
    Viva's voice rather than recording an empty confirmation."""
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
                  currency: str = "", merchant: str = "", movements=()) -> dict:
    """Turn a checked reading of what money became into a proposal, or write it.

    Deterministic from here on: every leg's major has already landed in the
    ledger's own vocabulary, and nothing in this function asks a model anything.

    ``merchant`` is the key the question grouped its movements under, and
    ``movements`` are the movements it grouped. Given, they are the counterparty
    and the payments this answer is about; absent, the descriptor names the
    counterparty and the population is derived.

    **An answer never opens an account by itself.** Where it would bring one
    into being, the proposal comes back for confirmation with the name the
    person would see, and existing accounts are offered first. Where it names
    nothing at all, the reply is the question rather than a placeholder path.
    Only an answer that changes nothing structural applies in this request."""
    from .listen import apply_proposal, propose
    proj = vault.ledger.projection()
    # A `movement_key` scopes the answer to one transaction rather than to every
    # movement sharing the descriptor. The unknown tier — a cheque, an ATM
    # withdrawal, a peer — is asked one at a time for that reason.
    proposal = propose(proj, interp, descriptor, amount, currency,
                       movement_key, locale=locale_from_env(),
                       merchant_key=merchant, movements=movements)
    if proposal.needs_name:
        return {"ok": False, "why": "needs_name",
                "message": proposal.summary(),
                "proposal": proposal.to_dict()}
    if proposal.new_accounts or proposal.confirm_accounts:
        return {"ok": True, "confirm": True, "proposal": proposal.to_dict()}
    applied = apply_proposal(vault.ledger, proposal, _today())
    return {"ok": True, "confirm": False, **applied}


def open_kind(vault: Vault, kind: str, name: str = "", secures: str = "",
              said: str = "") -> dict:
    """Propose the account a yes has opened. Writes nothing.

    A yes to "is there a loan against it?" says the loan exists; it does not
    say what it is called, and this product does not name a person's accounts
    for them. So the reply is either the naming question, or a Proposal that
    creates the account and records what it secures in the same confirmation.

    The naming reply carries Viva's words for it: a refusal that hands back only
    a machine reason leaves whoever asked with nothing to show a person."""
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
        # Punctuation and invisible characters are not a name a person could
        # read back, and an account they cannot read is one they cannot check.
        return needs_name()
    proj = vault.ledger.projection()
    # Through the same builder the rest of the ledger uses, so a name carrying
    # a colon cannot inject a level into the hierarchy.
    from .ledger.postings import account_path
    root, _, group = schema.account_shape.partition(":")
    major = {"Assets": "asset", "Liabilities": "liability"}.get(root, "asset")
    account = account_path(major, group, label)
    if len(account.split(":")) < 3:
        # The cleaner dropped every character of the name — punctuation alone
        # is not a name, and what is left is the group.
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
        said=label, value=label, currency=currency, attributes=attributes,
        locale=locale_from_env())
    return {"ok": True, "confirm": True, "proposal": proposal.to_dict()}


def apply_ruling(vault: Vault, proposal: dict) -> dict:
    """Apply a proposal a nature answer produced. The only path from a sentence
    to the ledger. `summary` is dropped; it is display text, not a field."""
    from .listen import Proposal, apply_proposal
    fields = {k: v for k, v in proposal.items() if k != "summary"}
    return {"ok": True, **apply_proposal(vault.ledger, Proposal(**fields), _today())}


def decline_question(vault: Vault, question_id: str,
                     reason: str = "not_now") -> dict:
    """Record that a question was set aside, and reply in Viva's voice.

    The stake snapshot (amount, count) is read from the live queue rather than
    taken from the caller, so a stale caller cannot record the wrong figures.
    Declining a question that is no longer open is a no-op, not an error: it
    returns `{"ok": False, "why": "not_open", "message": ...}`."""
    from .ledger.events import question_declined
    from .persona import ACTIVE_PACK
    from .questions import open_questions
    qs = open_questions(vault.ledger, limit=100000)
    q = next((x for x in qs["questions"] if x["id"] == question_id), None)
    if q is None:
        return {"ok": False, "why": "not_open",
                "message": "That question is no longer open — nothing to set aside."}
    vault.ledger.append(question_declined(
        q["id"], q["kind"], _today(), reason=reason,
        amount=q["amount"], count=q["count"], pack_version=ACTIVE_PACK))
    ack = "dont_know_ack" if reason == "dont_know" else "not_now_ack"
    # This is a settled action, but it is not an answered question.  Carry the
    # disposition explicitly so every caller can distinguish a recorded answer
    # from a question that was deliberately set aside.
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
    res = apply_human_correction(vault.ledger, doc_id, field, value, target_index)
    return {
        "action": res.action, "grade": res.grade, "account": res.account,
        "message": res.message,
    }


def confirm_identity(vault: Vault, doc_id: str, decision: str) -> dict:
    """Apply a person's ruling on an ambiguous account identity ('same' / 'new')."""
    res = apply_identity_ruling(vault.ledger, doc_id, decision)
    return {"ok": True, "action": res.action, "grade": res.grade,
            "account": res.account, "message": res.message}


def upload(vault: Vault, filename: str, data: bytes, read_fn) -> dict:
    """Ingest an uploaded file: capture, read, then post, park or hold.

    Returns the outcome — `action`, `grade`, `doc_type`, `account`,
    `auto_corrected`, `message`, and the `finding` when one was raised."""
    res = capture_and_ingest(vault.raw, vault.ledger, data, read_fn,
                             filename=filename, captured_at=_today())
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
