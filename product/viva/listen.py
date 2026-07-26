"""Viva listens — a sentence becomes double-entry (Slice 9a).

Full design: docs/from-your-words-to-the-ledger.md.

The queue asks *"is this money spent, or moved?"* and offers three answers. Real
money immediately produced two questions none of them fit: a mortgage payment
(interest **and** principal **and** escrow, at once) and a car purchase
(something you now *own*, which the ledger had no way to say). More answers in
that vocabulary would only mean more wrong answers.

The diagnosis was that `nature` stood in for something richer: **what the
counter-leg IS**. That has a complete, centuries-old vocabulary — expense,
asset, liability, income — with too many members and too many compound cases to
put behind buttons. But it fits in a sentence. So free text here is not a
convenience; it is the only practical interface to a complete ontology.

The pipeline, and where the boundary sits:

    1  frame_question      deterministic   the question queue (already built)
    2  suggest_answers     deterministic   from merchant category/subcategory
    3  interpret           ← THE MODEL     the sentence → a structured reading
    4  resolve_account     deterministic   exact / candidate to confirm / new
    5  propose             deterministic   legs, accounts, what changes
    6  apply               deterministic   RulingRecorded (+ an asserted account)

**The model touches step 3 only.** It never sees the ledger, never chooses an
account, and never supplies a figure — amounts come from the movement, and
`ruling_recorded` refuses an amount outright, so the boundary is structural
rather than a line in a prompt (T2 / ADR-010).

Two rulings from the author that shaped this (2026-07-25):

* **A missing document never blocks a ruling.** Create the account, post the
  cash, mark only the *decomposition* provisional, and ask for the 1098 or the
  invoice as corroboration. Blocking would be deferential where it doesn't count.
* **Confirmation is scoped to the account, not to every parse.** The expensive,
  hard-to-reverse act is binding money to an account for the first time. After
  that, the learned ruling applies in silence.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, replace

from .ledger.events import (ASSERTED, MAJORS, MAJOR_ASSET, MAJOR_EXPENSE,
                            MAJOR_INCOME, MAJOR_LIABILITY, SCOPE_MERCHANT,
                            SCOPE_MOVEMENT, UNVERIFIED, VERIFIED,
                            account_opened, ruling_recorded)
from .ingest.prompt_library import interpret_prompt
from .ledger.merchants import is_shareable, normalize_merchant
from .ledger.postings import MAJOR_ROOTS, MAJOR_UNCATEGORIZED, account_path

log = logging.getLogger("viva.listen")

# The surface never speaks these words (decision D1): the four majors are stored
# and never shown. A person is asked whether they still *have* it, not whether it
# is "an asset". Nobody should have to learn bookkeeping to use this product.
#
# Forward note: today these strings are fixed templates. A small local model
# should later phrase them in the person's own language and tone — a Swedish user
# getting a Swedish question, not a translated one. That is safe precisely
# because phrasing touches no figure and no account, so it sits entirely outside
# the T2 boundary, and it is small enough to run locally.
PLAIN = {
    MAJOR_EXPENSE: "Spent — the money is gone",
    MAJOR_ASSET: "I still have it, in another form",
    MAJOR_LIABILITY: "It changed what I owe",
    MAJOR_INCOME: "Money that came to me",
}

# The document that would PROVE each kind of claim. Provenance is the product,
# so a created account invites its paperwork — always to prove, never to unblock
# (Vishnu, 2026-07-25). This is also the ladder from `asserted` to `issued`: the
# document arriving is what upgrades the account.
CORROBORATION = {
    "vehicle": "invoice or bill of sale",
    "property": "closing disclosure",
    "mortgage": "mortgage statement or 1098",
    "loan": "loan statement",
    "investment": "brokerage statement",
}

# Where a major's account lives by default when the person gives no better hint.
# One level under the root, free data (I5) — never a jurisdiction-shaped table.
_DEFAULT_GROUP = {MAJOR_ASSET: "Other", MAJOR_LIABILITY: "Other",
                  MAJOR_EXPENSE: "Other", MAJOR_INCOME: "Other"}


# --------------------------------------------------------------------- step 2


def suggest_answers(category: str = "", subcategory: str = "") -> list[dict]:
    """Plain-language answers to offer *before* anyone types anything.

    The common case should still be one tap: what we already know about the
    merchant usually implies the major. Free text is the escape hatch for the
    cases a button genuinely cannot hold, not a replacement for the fast path —
    and because these are deterministic, the queue keeps working with **no model
    configured at all**."""
    cat, sub = (category or "").lower(), (subcategory or "").lower()
    ordered: list[str] = []
    if any(w in f"{cat} {sub}" for w in ("mortgage", "loan", "credit card", "debt")):
        ordered = [MAJOR_LIABILITY, MAJOR_EXPENSE, MAJOR_ASSET]
    elif any(w in f"{cat} {sub}" for w in ("auto", "vehicle", "real estate",
                                           "investment", "transfer")):
        ordered = [MAJOR_ASSET, MAJOR_EXPENSE, MAJOR_LIABILITY]
    elif any(w in f"{cat} {sub}" for w in ("payroll", "salary", "refund", "rent")):
        ordered = [MAJOR_INCOME, MAJOR_ASSET, MAJOR_EXPENSE]
    else:
        ordered = [MAJOR_EXPENSE, MAJOR_ASSET, MAJOR_LIABILITY]
    return [{"major": m, "label": PLAIN[m]} for m in ordered]


# --------------------------------------------------------------------- step 3


@dataclass
class Interpretation:
    """What a model may return from a sentence — meaning only, never money."""
    legs: list[dict] = field(default_factory=list)   # {major, account_hint, share}
    kind: str = ""                 # vehicle | property | mortgage | loan | ...
    # A label the PERSON named ("poker"), not a guess about them. Its absence
    # was a real defect: someone answered "spent on playing poker, add it to
    # poker category" and only the first half reached the ledger.
    category: str = ""
    confidence: float = 0.0
    said: str = ""                 # the person's own words, kept (T3)
    # WHY there are no legs, when there are none. "The model declined" and "we
    # never reached the model" look identical from the outside and mean opposite
    # things — one is a model's honest limit, the other is a broken pipe wearing
    # a model's failure as a costume. Anything that reports on this must be able
    # to tell them apart, so the reason is carried rather than inferred.
    failure: str = ""              # "" | unreachable | unparseable | empty
    detail: str = ""               # the underlying error, verbatim
    raw: str = ""                  # what the model actually said
    version: str = ""              # the prompt version that produced this (T8)

    @property
    def compound(self) -> bool:
        return len(self.legs) > 1

    @property
    def shares_known(self) -> bool:
        return bool(self.legs) and all(leg.get("share") for leg in self.legs)


# The prompt lives in the versioned, append-only library with every other one
# (`viva/ingest/prompt_library.py`), not as a constant here. A recorded ruling
# stamps its `prompt_version`, so tuning the text never silently invalidates the
# readings made before the change — and eval runs stay comparable across time.
INTERPRET_VERSION = "interpret-v2"


def interpret(said: str, descriptor: str = "", category: str = "",
              subcategory: str = "", extract_fn=None,
              source: str = "", version: str = INTERPRET_VERSION) -> Interpretation:
    """The one model call. Turns a sentence into a structured reading.

    Anything the model returns that isn't in the closed vocabulary is dropped
    rather than trusted, and an unparseable reply yields an empty
    Interpretation — the caller then falls back to the buttons. A model being
    unavailable or wrong must degrade the surface, never the ledger."""
    if extract_fn is None:
        return Interpretation(said=said, failure="unreachable",
                              detail="no model configured", version=version)
    text, version = interpret_prompt(version)
    prompt = text.format(
        said=said, counterparty=descriptor or "(unknown)",
        # The movement may come from a bank, a card, a brokerage, a loan account
        # or a wallet — the reading must not assume one (I5). When we do know,
        # say so plainly; when we do not, say that instead of implying a bank.
        source=source or "(an account they hold)",
        category=category or "(unknown)", subcategory=subcategory or "(unknown)")
    try:
        raw = extract_fn(prompt)
    except Exception as exc:                       # noqa: BLE001 - degrade, never raise
        # The call never landed: wrong model name, server down, bad base URL,
        # a rejected parameter. NOT the model declining.
        log.warning("interpret: could not reach the model (%s)", exc)
        return Interpretation(said=said, failure="unreachable", detail=str(exc),
                              version=version)
    body = _first_json_object(raw)
    if body is None:
        log.warning("interpret: no readable JSON object in the reply (%d chars)",
                    len(raw or ""))
        return Interpretation(said=said, failure="unparseable",
                              detail="no complete JSON object in the reply",
                              raw=raw or "", version=version)
    legs = []
    # A model's reply is untrusted input, not a contract: `legs` arriving as a
    # string, a number, or anything but a list of objects must degrade to "I
    # didn't understand", never raise into the caller.
    raw_legs = body.get("legs")
    for leg in raw_legs if isinstance(raw_legs, list) else []:
        if not isinstance(leg, dict):
            log.warning("interpret: dropping a leg that isn't an object")
            continue
        major = str(leg.get("major", "")).strip().lower()
        if major not in MAJORS:
            log.warning("interpret: dropping leg with unknown major %r", major)
            continue
        legs.append({"major": major,
                     "account_hint": str(leg.get("account_hint", "")).strip(),
                     # A share is only ever honoured if the PERSON stated it;
                     # a model-invented ratio is exactly the kind of confident
                     # wrong number this project exists to refuse.
                     "share": str(leg.get("share", "")).strip()})
    return Interpretation(
        legs=legs, kind=str(body.get("kind", "")).strip().lower(),
        category=str(body.get("category", "")).strip().lower()[:40],
        confidence=float(body.get("confidence") or 0.0), said=said,
        failure="" if legs else "empty",
        detail="" if legs else "valid JSON, but no usable legs",
        raw=raw or "", version=version)


def _first_json_object(text: str) -> dict | None:
    """The first COMPLETE, balanced JSON object in a reply, or None.

    Requiring the whole reply to be JSON was too brittle in practice. Models
    wrap objects in code fences, prefix them with reasoning, or append a
    cheerful sentence afterwards — none of which is a failure of understanding,
    and all of which threw away a perfectly good reading.

    Scanning for balance (respecting strings and escapes) also means a reply cut
    off mid-object is correctly rejected rather than half-parsed. That matters
    more than the leniency: a *truncated* reading is not a partial reading, it
    is an unknown one, and guessing at the rest is how a wrong ruling gets
    written."""
    if not text:
        return None
    for start in range(len(text)):
        if text[start] != "{":
            continue
        depth, in_str, escaped = 0, False, False
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        found = json.loads(text[start:i + 1])
                    except Exception:              # noqa: BLE001 - try the next '{'
                        break
                    return found if isinstance(found, dict) else None
        # unbalanced from here — the reply was cut off
    return None


# --------------------------------------------------------------------- step 4


@dataclass
class AccountMatch:
    """How an account hint resolves. Deliberately the same three verdicts as
    Slice 1.5's statement matcher — `same` / `ambiguous` / `new` — because this
    is that matcher pointed at a new target, not a second mechanism."""
    account: str
    verdict: str               # "same" | "existing" | "ambiguous" | "new"
    candidate: str = ""
    reason: str = ""


def resolve_account(proj, major: str, hint: str, group: str = "") -> AccountMatch:
    """Which account does this belong to? — Slice 1.5's problem, re-pointed.

    Exact match posts in silence; a near match asks; nothing matching proposes a
    new account, which is the ONE thing this slice always confirms (D2).

    Account sprawl is the failure mode here — `Assets:Car`, `Assets:Tesla`,
    `Assets:My Car` — so the cure is the same one that tamed merchant
    descriptors: normalize the name, and suggest what exists before offering to
    create anything."""
    # Not every leg names a thing. Ordinary spending — cash at a poker table,
    # a restaurant bill — is an expense, not an asset with a name, and minting
    # `Expenses:Other:Unnamed` for it is exactly how account sprawl starts. Only
    # a major that means "you now OWN or OWE something" can bring an account
    # into being; the rest go to the Uncategorized bucket the ledger already
    # has, where the CATEGORY does the descriptive work.
    if major in (MAJOR_EXPENSE, MAJOR_INCOME) and not hint.strip():
        return AccountMatch(MAJOR_UNCATEGORIZED[major], "existing",
                            reason="ordinary spending needs no account of its own")
    want = _norm(hint)
    known = set(proj.ruled_accounts()) | {
        a for a in proj.accounts() if a.split(":")[0] == MAJOR_ROOTS.get(major)}
    for account in sorted(known):
        tail = _norm(account.split(":")[-1])
        if want and tail == want:
            return AccountMatch(account, "same", reason="an account you already have")
    for account in sorted(known):
        tail = _norm(account.split(":")[-1])
        if want and tail and (want in tail or tail in want):
            return AccountMatch(account, "ambiguous", candidate=account,
                                reason=f"looks like your existing {account}")
    proposed = account_path(major, group or _DEFAULT_GROUP.get(major, "Other"),
                            hint.strip() or "Unnamed")
    return AccountMatch(proposed, "new", reason="nothing like this exists yet")


def _norm(text: str) -> str:
    return " ".join((text or "").lower().replace("-", " ").split())


# --------------------------------------------------------------------- step 5


@dataclass
class Proposal:
    """A structured, *un-applied* intent — what would change, how much money it
    moves, what it rests on, and what it does NOT know.

    `Finding` is the read side's version of this; Proposal is its write-side
    twin, and it is what makes X3 ("nothing irreversible without an explicit
    yes") a property of the type rather than a rule anyone has to remember."""
    scope: str
    subject: str
    legs: list[dict] = field(default_factory=list)
    new_accounts: list[str] = field(default_factory=list)
    confirm_accounts: list[str] = field(default_factory=list)
    corroborates: str = ""
    category: str = ""             # what the person called it, if they said
    said: str = ""
    unknown_split: bool = False
    settles: int = 1
    amount: str = ""
    currency: str = ""
    prompt_version: str = ""       # which instructions read the sentence (T8)

    def summary(self) -> str:
        """What Viva says back before anything is written. It must state the
        money moved and — the part that matters — what it still doesn't know."""
        what = ", ".join(PLAIN[leg["major"]].lower() for leg in self.legs)
        head = (f"{self.currency} {self.amount}".strip()
                + (f" across {self.settles} payments" if self.settles > 1 else ""))
        parts = [f"I'd record {head} as: {what}."]
        if self.new_accounts:
            parts.append("This creates " + ", ".join(self.new_accounts)
                         + " — new, and only you say it exists.")
        if self.unknown_split:
            parts.append("I can't tell how it splits between those, so I won't "
                         "guess: the money is recorded, the split stays open.")
        if self.category:
            parts.append(f"I'll file it under \u201c{self.category}\u201d.")
        if self.corroborates:
            parts.append(f"Your {self.corroborates} would let me prove this "
                         "— it isn't needed to save it.")
        return " ".join(parts)

    def to_dict(self) -> dict:
        return {"scope": self.scope, "subject": self.subject, "legs": self.legs,
                "new_accounts": self.new_accounts,
                "confirm_accounts": self.confirm_accounts,
                "corroborates": self.corroborates, "category": self.category,
                "said": self.said,
                "unknown_split": self.unknown_split, "settles": self.settles,
                "amount": self.amount, "currency": self.currency,
                "prompt_version": self.prompt_version,
                "summary": self.summary()}


def propose(proj, interp: Interpretation, descriptor: str, amount: str = "",
            currency: str = "", movement_key: str = "") -> Proposal:
    """Turn a reading into a concrete, reviewable proposal — deterministically.

    Scope follows the Slice 5.5 rule already in force: a **commercial** merchant
    generalizes (one answer settles every payment to them, past and future), a
    peer descriptor — a person's name on a Zelle — does not, because one payment
    to a friend can be a gift and the next a loan."""
    merchant = normalize_merchant(descriptor)
    generalizes = bool(merchant) and is_shareable(merchant)
    scope = SCOPE_MERCHANT if generalizes and not movement_key else SCOPE_MOVEMENT
    subject = merchant if scope == SCOPE_MERCHANT else movement_key

    legs, new_accounts, confirm = [], [], []
    for leg in interp.legs:
        match = resolve_account(proj, leg["major"], leg.get("account_hint", ""),
                                group=_group_for(interp.kind, leg["major"]))
        legs.append({"major": leg["major"], "account": match.account,
                     "share": leg.get("share", "")})
        if match.verdict == "new":
            new_accounts.append(match.account)
        elif match.verdict == "ambiguous":
            confirm.append(match.candidate)

    settles = 1
    if scope == SCOPE_MERCHANT:
        settles = sum(1 for m in proj.movements()
                      if normalize_merchant(m.description) == merchant)
    return Proposal(
        scope=scope, subject=subject, legs=legs, new_accounts=new_accounts,
        confirm_accounts=confirm,
        # The document is chosen by CODE from the kind, never taken from the
        # model's free text. v1 let the model fill this field and it answered
        # "no", which the surface rendered as "Your no would let me prove this."
        # A model reads meaning; deciding which document proves a claim is ours.
        corroborates=CORROBORATION.get(interp.kind, ""),
        category=interp.category, said=interp.said,
        unknown_split=interp.compound and not interp.shares_known,
        settles=max(settles, 1), amount=amount, currency=currency,
        prompt_version=interp.version)


def one_shot_extractor(spec):
    """The live model edge for interpretation — **one call, never continued.**

    The shared driver continues across truncation, which is right for reading a
    statement (a long transaction list really does get cut off, and stitching
    the tail back is the correct repair) and wrong here. This reply is ~60
    tokens by construction. If it hits the limit the model is rambling, and
    continuing six more times turns one cheap, recoverable failure into
    unparseable garbage at seven times the cost and seven times the latency —
    which is exactly what the first real run produced.

    So: one shot, and truncation is REPORTED rather than repaired."""
    from vivacore.models import adapter_for

    adapter = adapter_for(replace(spec, max_continuations=0))

    def _extract(prompt: str) -> str:
        result = adapter.extract([], prompt)
        if result.finish_reason == "length":
            # Not a transport failure and not a bad reading — a third thing,
            # and it is the caller's job to refuse rather than to guess.
            log.warning("interpret: the model ran past its limit (%d output tokens) "
                        "— refusing to stitch a bounded answer back together",
                        result.output_tokens)
        return result.text

    return _extract


def _group_for(kind: str, major: str) -> str:
    if kind == "vehicle":
        return "Vehicles" if major == MAJOR_ASSET else "Auto"
    if kind == "property":
        return "Property" if major == MAJOR_ASSET else "Mortgage"
    if kind == "mortgage":
        return "Escrow" if major == MAJOR_ASSET else "Mortgage"
    if kind == "loan":
        return "Loans"
    if kind == "investment":
        return "Investments"
    return ""


# --------------------------------------------------------------------- step 6


def apply_proposal(ledger, proposal: Proposal, occurred_at: str,
                   by: str = "human") -> dict:
    """Write it. Deterministic, and the only path from a sentence to the ledger.

    An account the person brought into being is opened with `origin=asserted`
    (A3) — the ledger must never lose track of the difference between what an
    issuer attests and what you told it, because that is precisely what it can
    and cannot vouch for later."""
    grade = VERIFIED if by == "human" else UNVERIFIED
    opened = []
    for account in proposal.new_accounts:
        major_root = account.split(":")[0]
        kind = "liability" if major_root == "Liabilities" else "asset"
        ledger.append(account_opened(
            account, kind, account.split(":")[-1], proposal.currency or "USD",
            occurred_at, origin=ASSERTED))
        opened.append(account)
    ledger.append(ruling_recorded(
        proposal.scope, proposal.subject, occurred_at, legs=proposal.legs,
        by=by, grade=grade, said=proposal.said,
        corroborates=proposal.corroborates,
        prompt_version=proposal.prompt_version))
    # One sentence can carry two rulings — "spent on poker, add it to poker
    # category" is a major AND a label. Both are written, through the writers
    # that already exist, at the same scope the ruling used.
    if proposal.category:
        from .ingest.categorize import assign_category, assign_merchant_category
        if proposal.scope == SCOPE_MERCHANT:
            assign_merchant_category(ledger, proposal.subject, proposal.category,
                                     by=by)
        else:
            assign_category(ledger, proposal.subject, proposal.category, by=by)
    return {"scope": proposal.scope, "subject": proposal.subject,
            "accounts_opened": opened, "settles": proposal.settles,
            "category": proposal.category}


def listen(proj, said: str, descriptor: str, amount: str = "", currency: str = "",
           movement_key: str = "", category: str = "", subcategory: str = "",
           extract_fn=None, source: str = "") -> Proposal | None:
    """Steps 3–5 in one call: sentence in, reviewable Proposal out. Nothing is
    written — applying is a separate, explicit act."""
    interp = interpret(said, descriptor, category, subcategory, extract_fn,
                       source=source)
    if not interp.legs:
        return None
    return propose(proj, interp, descriptor, amount, currency, movement_key)
