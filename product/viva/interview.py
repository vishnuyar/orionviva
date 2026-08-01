"""The interview — a question with a next step, derived rather than stored.

There is no interview object and no interview event. For an account whose kind
has a schema, the projection already holds which of that kind's questions are
answered, which were set aside, and which remain, and this module reads it.

    schema pack    what may be asked        reviewed, versioned, impersonal
    this module    what is still owed       derived from rulings and declines
    the person     whether anything is made  a Proposal, always confirmed

An answer is a ``RulingRecorded`` at attribute scope — the generic scoped
ruling with another scope, not a new event type.

Three states, all derived:

* **Answered** — an attribute ruling exists for the key, or the ledger already
  holds the fact.
* **Set aside** — the key's question was declined. It returns when the stake it
  was declined against moves.
* **Settled** — no essential is outstanding. A conditional essential is not
  owed until the answer it depends on has arrived.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from . import schemas
from .ledger.events import SCOPE_ATTRIBUTE

# One question id shape, so the surface can keep its place between reads and a
# decline can be remembered against the thing it was about.
ID_PREFIX = "interview"

# The account kinds a person holds or owes. A spending or income bucket is a
# destination, not an instrument, and has nothing to be interviewed about.
HELD_KINDS = ("depository", "liability", "investment", "asset")


def question_id(account: str, key: str) -> str:
    return f"{ID_PREFIX}:{account}:{key}"


@dataclass
class Interview:
    """One account's interview, entirely derived.

    ``answered`` maps a question key to what is known — either what the person
    said or what a document already attested. ``gap`` is set when the kind has
    no schema: nothing is asked, and the absence is recorded rather than
    silently passed over."""

    account: str
    kind: str
    name: str = ""
    currency: str = ""
    stake: Decimal = Decimal("0")     # cash recorded against it — the ranking key
    settles: int = 0                  # movements touching it — the return trigger
    answered: dict = field(default_factory=dict)
    declined: set = field(default_factory=set)
    schema: object = None
    gap: str = ""

    @property
    def outstanding(self) -> tuple:
        if self.schema is None:
            return ()
        return self.schema.outstanding(self.answered, self.declined)

    @property
    def terminated(self) -> bool:
        """Over when every essential is answered or set aside. A kind with no
        schema is over before it starts."""
        return not self.outstanding

    @property
    def next_question(self):
        """The next essential owed, in pack order, or None.

        Pack order *is* the deterministic selector: a schema is written with
        the question that unlocks the most first. A model reordering this is a
        later cycle, and it has to beat this on a measured number."""
        return self.outstanding[0] if self.outstanding else None

    def unfilled_essentials(self) -> tuple:
        """Every essential with no answer — outstanding or set aside. What net
        worth reads to decide whether an asserted account is a disclosed gap."""
        if self.schema is None:
            return ()
        return tuple(q for q in self.schema.questions
                     if q.required(self.answered) and q.key not in self.answered)

    def value_of(self, key: str) -> str:
        return str((self.answered.get(key) or {}).get("value", ""))


def _why_no_schema(kind: str) -> str:
    """The sentence for a coverage gap: the pack has no schema for a kind that
    resolved, or nothing resolved a kind at all."""
    if kind:
        return f"the pack has no schema for a {kind} here yet"
    return ("I can't tell what kind of thing this account is yet — no document "
            "has said, and its shape alone does not")


def _is_yes(value) -> bool:
    return str(value or "").strip().lower() in ("yes", "true", "y")


def attributes(proj, account: str = "", as_of: str = "") -> dict:
    """Attribute rulings, as ``{account: {key: {value, currency, grade, said,
    at}}}``. Filtered to one account when named, and to what was known at a
    date when one is given — a later answer never rewrites an earlier reading
    of the ledger."""
    out: dict[str, dict] = {}
    # Read the WHOLE history in order, keeping the last answer dated at or
    # before the date asked about. A correction recorded later is the answer
    # today and was not the answer then.
    for ruling in proj._attribute_history:
        subject = ruling.get("subject", "")
        acct, _, key = subject.rpartition(":")
        if not acct or not key:
            continue
        if account and acct != account:
            continue
        at = str(ruling.get("occurred_at", ""))[:10]
        if as_of and at and at > as_of:
            continue
        out.setdefault(acct, {})[key] = {
            "value": ruling.get("value", ""),
            "currency": ruling.get("currency", ""),
            "grade": ruling.get("grade", ""),
            "said": ruling.get("said", ""),
            "at": at, "source": "said"}
    return out


def _from_ledger(info, schema, doc_types=()) -> dict:
    """What the ledger already answers about this account.

    Two sources, both declared by the schema so no key names live here: an
    account field (``known_from``), and the answer a classified document type
    itself gives (``answered_by_document``). Each entry carries a ``source`` of
    ``ledger`` or ``document``."""
    known: dict = {}
    if schema is None or info is None:
        return known
    seen = {str(d) for d in (doc_types or ())}
    for q in schema.questions:
        if q.known_from:
            value = getattr(info, q.known_from, "") or ""
            if value:
                known[q.key] = {"value": value, "currency": "", "grade": "",
                                "said": "", "source": "ledger"}
        for doc, answer in (q.answered_by_document or {}).items():
            if doc in seen:
                known[q.key] = {"value": answer, "currency": "", "grade": "",
                                "said": "", "source": "document"}
                break
    return known


def interviews(proj, jurisdiction: str = "", with_stakes: bool = True,
               as_of: str = "") -> list[Interview]:
    """Every account that has an interview, whether or not anything is owed.

    An account whose path matches no schema shape yields an Interview with a
    ``gap`` — the coverage record that says a kind exists here and nothing can
    be asked about it yet.

    ``with_stakes`` false skips the ranking figures, which are the only part
    that costs a movement replay — for a caller that needs to know what is
    unanswered and will not read a stake."""
    # An account opened before the ledger recorded where its instrument lives
    # falls back to the vault's own locale rather than to nowhere, which would
    # silently drop every jurisdiction-tagged question and document.
    if not jurisdiction:
        from .env import jurisdiction_from_env
        jurisdiction = jurisdiction_from_env()
    juris = (jurisdiction or "").lower()
    ruled = proj.ruled_accounts() if with_stakes else {}
    # How many movements touch each account — the count a declined question
    # is remembered against, so it returns when new evidence arrives.
    touching: dict = {}
    if with_stakes:
        for m in proj.movements():
            touching[m.account] = touching.get(m.account, 0) + 1
    out: list[Interview] = []
    declined = set(proj.declined_questions())
    answers = attributes(proj, as_of=as_of)

    for account in proj.accounts():
        try:
            info = proj.account_info(account)
        except Exception:                            # noqa: BLE001
            continue
        # Only things a person holds or owes have an interview. A spending
        # bucket is a place money went, not an instrument with a shape.
        if info.kind not in HELD_KINDS:
            continue
        # The instrument's own jurisdiction decides which schema applies; the
        # caller's is the fallback for an account that never recorded one.
        where = (info.jurisdiction or juris).lower()
        docs = proj.document_types_of(account)
        kind = schemas.kind_of_account(account, where, ledger_kind=info.kind,
                                       doc_types=docs)
        row = ruled.get(account, {})
        schema = schemas.schema_for(kind, where) if kind else None
        answered = dict(_from_ledger(info, schema, docs))
        answered.update(answers.get(account, {}))
        iv = Interview(
            account=account, kind=kind,
            name=info.name or account.split(":")[-1],
            currency=info.currency or row.get("currency", ""),
            stake=row.get("paid", Decimal("0")),
            settles=max(int(row.get("count", 0)), touching.get(account, 0)),
            answered=answered,
            declined={q.key for q in (schema.questions if schema else ())
                      if question_id(account, q.key) in declined},
            schema=schema,
            gap="" if schema else _why_no_schema(kind))
        out.append(iv)
    return sorted(out, key=lambda i: i.account)


def opens_pending(proj, jurisdiction: str = "",
                  known: list | None = None) -> list[tuple]:
    """Interviews a yes has opened that still have no account.

    ``financed: yes`` on a property means a loan exists; it does not mean an
    account for it does. The pairing is read from the link the loan's own
    interview records, so the ask disappears the moment the loan account names
    what it secures — and nothing is created to make it disappear."""
    ivs = known if known is not None else interviews(proj, jurisdiction)
    secured: set = set()
    for iv in ivs:
        if iv.schema is None:
            continue
        for q in iv.schema.questions:
            if q.answer != schemas.ANSWER_LINK:
                continue
            target = iv.value_of(q.key)
            if target:
                secured.add((iv.kind, target))
    out: list[tuple] = []
    for iv in ivs:
        if iv.schema is None:
            continue
        for q in iv.schema.questions:
            if not q.opens or not _is_yes(iv.value_of(q.key)):
                continue
            if (q.opens, iv.account) in secured:
                continue
            out.append((iv, q.opens))
    return out


def coverage_gaps(proj, jurisdiction: str = "") -> list[dict]:
    """Accounts the pack cannot yet ask about. Recorded, never guessed at."""
    return [{"account": iv.account, "why": iv.gap}
            for iv in interviews(proj, jurisdiction) if iv.gap]
