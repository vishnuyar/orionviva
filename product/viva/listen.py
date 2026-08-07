"""Viva listens — a sentence becomes double-entry.

What a movement's counter-leg is — expense, asset, liability, income — has too
many members and too many compound cases for a fixed set of buttons: a mortgage
payment is interest and principal and escrow at once. So the interface is a
sentence, and this module is the path from one to a recorded ruling.

The pipeline, and where the boundary sits:

    1  frame_question      deterministic   the question queue (already built)
    2  RULING_SLOTS        deterministic   the structure an answer to it has
    3  reply.answer        ← THE MODEL     the sentence → those slots, filled,
                                           then checked against their types
    4  resolve_account     deterministic   exact / candidate to confirm / new
    5  propose             deterministic   legs, accounts, what changes
    6  apply               deterministic   RulingRecorded (+ an asserted account)

The model touches step 3 only, and there it fills declared slots rather than
writing anything of its own. It never sees the ledger, never chooses an account,
and never supplies a figure: amounts come from the movement, and
`ruling_recorded` refuses an amount outright.

Two rules this path keeps:

* **A missing document never blocks a ruling.** The account is created, the cash
  is posted, only the *decomposition* is marked provisional, and the 1098 or the
  invoice is asked for as corroboration.
* **Confirmation is scoped to the account, not to every parse.** Binding money
  to an account for the first time is confirmed; after that the learned ruling
  applies in silence.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, replace

from .ledger.events import (ASSERTED, MAJORS, MAJOR_ASSET, MAJOR_EXPENSE,
                            MAJOR_INCOME, MAJOR_LIABILITY, SCOPE_ATTRIBUTE,
                            SCOPE_MERCHANT, SCOPE_MOVEMENT, UNVERIFIED,
                            VERIFIED, account_opened, ruling_recorded)
from .ledger.merchants import is_shareable, normalize_merchant
from .ledger.postings import MAJOR_ROOTS, MAJOR_UNCATEGORIZED, account_path
from .render import (accounts as render_accounts,
                     money as render_money)
from .reply import TRUNCATED_MARK, Slot, answer as read_answer
from .schemas import ANSWER_CHOICE, ANSWER_LABEL, ANSWER_RATE

log = logging.getLogger("viva.listen")

# The plain-language label for each major. The majors are what is stored; these
# are what a person is shown, so the surface never says "asset".
PLAIN = {
    MAJOR_EXPENSE: "Spent — the money is gone",
    MAJOR_ASSET: "I still have it, in another form",
    MAJOR_LIABILITY: "It changed what I owe",
    MAJOR_INCOME: "Money that came to me",
}

# The account group used when the counterparty implies nothing: one level under
# the major's root. Otherwise the group, the corroborating document and the
# ordering of the answers all come from the counterparty's implication
# (`account_group`, `documents`), learned once at enrichment.
_FALLBACK_GROUP = "Other"


# --------------------------------------------------------------------- step 2


# What an answer about the nature of money is MADE OF. A payment can be several
# things at once — interest, principal and an amount held on your behalf — so
# the legs slot holds several of something rather than one of anything, and each
# leg's major must land in the ledger's own closed vocabulary. The plain-language
# meanings travel with the alternatives so the four words are not asked about
# bare.
RULING_SLOTS = (
    Slot(name="legs", required=True, parts=(
        Slot(name="major", type=ANSWER_CHOICE, choices=MAJORS,
             meanings=tuple(PLAIN.items()), required=True),
        Slot(name="account_hint", type=ANSWER_LABEL),
        Slot(name="share", type=ANSWER_RATE))),
    Slot(name="kind", type=ANSWER_LABEL),
    Slot(name="category", type=ANSWER_LABEL),
)


# --------------------------------------------------------------------- step 3


@dataclass
class Interpretation:
    """A ruling's slots, filled and checked — meaning only, never money."""
    legs: list[dict] = field(default_factory=list)   # {major, account_hint, share}
    kind: str = ""                 # vehicle | property | mortgage | loan | ...
    # A label the person named, not a guess about them. One sentence can carry
    # both a major and a label, and both halves reach the ledger.
    category: str = ""
    said: str = ""                 # the person's own words, kept
    # Why there are no legs, when there are none. `unreachable` — the call never
    # landed — is carried distinctly from `unparseable` and `empty`, which are
    # the model answering with something unusable.
    failure: str = ""              # "" | unreachable | unparseable | empty
    detail: str = ""               # the underlying error, verbatim
    raw: str = ""                  # what the model actually said
    version: str = ""              # the prompt version that produced this

    @property
    def compound(self) -> bool:
        return len(self.legs) > 1

    @property
    def shares_known(self) -> bool:
        return bool(self.legs) and all(leg.get("share") for leg in self.legs)


def ruling_context(descriptor: str = "", category: str = "",
                   subcategory: str = "", source: str = "") -> tuple:
    """What is already known about the movement being ruled on, as data.

    The movement may come from a bank, a card, a brokerage, a loan account or a
    wallet, so the source is named where it is known and named as unknown
    otherwise, rather than left to be assumed."""
    return (("counterparty", descriptor or "(unknown)"),
            ("source", source or "(an account they hold)"),
            ("category", category or "(unknown)"),
            ("subcategory", subcategory or "(unknown)"))


def ruling_from(reply, said: str = "") -> Interpretation:
    """A checked reply to a nature question, as the reading the rest of this
    module works on.

    Every value here has already been through its type's deterministic check —
    each leg's major landed in the ledger's own vocabulary, or the leg was
    dropped before it got here. This only renames what survived."""
    legs = [{"major": leg["major"],
             "account_hint": leg.get("account_hint", ""),
             # Carried verbatim. A share is honoured only where the person
             # stated it, which `propose` decides.
             "share": leg.get("share", "")}
            for leg in reply.values.get("legs", [])]
    return Interpretation(
        legs=legs, kind=reply.value("kind").lower(),
        category=reply.value("category").lower()[:40], said=said,
        failure="" if legs else "empty",
        detail="" if legs else "no usable legs",
        version=reply.version)


# --------------------------------------------------------------------- step 4


@dataclass
class AccountMatch:
    """How an account hint resolves — the same verdicts the statement matcher
    uses: `same`, `existing`, `ambiguous`, `new`."""
    account: str
    verdict: str               # "same" | "existing" | "ambiguous" | "new"
    candidate: str = ""
    reason: str = ""


def resolve_account(proj, major: str, hint: str, group: str = "") -> AccountMatch:
    """Which account a leg belongs to.

    Names are normalized before comparison. An exact match on the last segment
    returns `same`; a substring match either way returns `ambiguous` with the
    candidate; nothing matching returns `new` with a proposed path, and that is
    the one verdict this path always confirms."""
    # An expense or income leg with no named thing goes to the Uncategorized
    # bucket the ledger already has, where the category does the descriptive
    # work. Only a major that means "you now own or owe something" brings an
    # account into being.
    if major in (MAJOR_EXPENSE, MAJOR_INCOME) and not hint.strip():
        return AccountMatch(MAJOR_UNCATEGORIZED[major], "existing",
                            reason="ordinary spending needs no account of its own")
    # An answer that says "I still have it" without saying what it is cannot
    # open an account: a path built from a placeholder is a thing nobody named
    # reaching net worth. The verdict is a QUESTION, not a path.
    if not hint.strip():
        return AccountMatch("", "unnamed",
                            reason="you now own or owe something, and it has no name yet")
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
    proposed = account_path(major, group or _FALLBACK_GROUP, hint.strip())
    return AccountMatch(proposed, "new", reason="nothing like this exists yet")


def _norm(text: str) -> str:
    return " ".join((text or "").lower().replace("-", " ").split())


# --------------------------------------------------------------------- step 5


@dataclass
class Proposal:
    """A structured, un-applied intent: what would change, how much money it
    moves, what it rests on, and what it does not know.

    Nothing is written until `apply_proposal` is called with it. `Finding` is
    the read side's equivalent."""
    scope: str
    subject: str
    legs: list[dict] = field(default_factory=list)
    new_accounts: list[str] = field(default_factory=list)
    confirm_accounts: list[str] = field(default_factory=list)
    # Legs whose thing has no name yet. A proposal carrying one cannot be
    # applied: there is a question to ask first.
    needs_name: list[str] = field(default_factory=list)
    # What the person said one attribute of an account IS, at attribute scope.
    value: str = ""
    # Further attributes the same confirmation settles — the link a loan makes
    # to the property it secures, stated in the breath that opened it.
    attributes: list[dict] = field(default_factory=list)
    corroborates: str = ""
    category: str = ""             # what the person called it, if they said
    said: str = ""
    unknown_split: bool = False
    settles: int = 1
    amount: str = ""
    currency: str = ""
    prompt_version: str = ""       # which instructions read the sentence
    # How a figure is written for this person. The confirmation is the last
    # sentence before an irreversible write, so it is written by the same
    # renderer as the question that led to it.
    locale: str = ""

    @property
    def applicable(self) -> bool:
        """False while something in it has no name. Applying then would open an
        account nobody named."""
        return not self.needs_name

    @staticmethod
    def _named(paths) -> str:
        """Accounts as a person reads them. A ledger path is how the machine
        files a thing; the name in it is what the person called it, and that is
        what the renderer shows."""
        return str(render_accounts({"path": p} for p in paths))

    def summary(self) -> str:
        """One sentence back before anything is written: the money moved and
        what it becomes, any account this would create, an unknown split, the
        category, and the document that would corroborate it."""
        if self.needs_name:
            return ("You still have it, so it belongs somewhere of its own — "
                    "but I don't know what to call it yet, and I won't invent "
                    "a name. What is it?")
        if self.scope == SCOPE_ATTRIBUTE:
            parts = []
            if self.new_accounts:
                parts.append("This creates " + self._named(self.new_accounts)
                             + " — new, and only you say it exists.")
            parts.append(f"I'll record it as “{self.value}”.")
            if self.corroborates:
                parts.append(f"Your {self.corroborates} would let me prove this "
                             "— it isn't needed to save it.")
            return " ".join(parts)
        what = ", ".join(PLAIN[leg["major"]].lower() for leg in self.legs)
        head = str(render_money(self.amount or "0", self.currency,
                                locale=self.locale))
        if self.settles > 1:
            head += f" across {self.settles} payments"
        parts = [f"I'd record {head} as: {what}."]
        if self.new_accounts:
            parts.append("This creates " + self._named(self.new_accounts)
                         + " — new, and only you say it exists.")
        # An account picked because it LOOKED like one you have is a guess, and
        # a guess the person confirms without being told about is a guess they
        # did not make.
        if self.confirm_accounts:
            parts.append("I've taken this to be your existing "
                         + self._named(self.confirm_accounts)
                         + " — say so if it is something else.")
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
                "needs_name": self.needs_name, "value": self.value,
                "attributes": self.attributes,
                "corroborates": self.corroborates, "category": self.category,
                "said": self.said,
                "unknown_split": self.unknown_split, "settles": self.settles,
                "amount": self.amount, "currency": self.currency,
                "prompt_version": self.prompt_version, "locale": self.locale,
                "summary": self.summary()}


def propose(proj, interp: Interpretation, descriptor: str, amount: str = "",
            currency: str = "", movement_key: str = "",
            locale: str = "") -> Proposal:
    """Turn a reading into a concrete, reviewable proposal, deterministically.

    A commercial merchant generalizes: the proposal is scoped to the merchant
    and settles every payment to it, past and future. A peer descriptor or an
    instrument is scoped to one movement. Raises ValueError when a
    movement-scoped answer has no key and the descriptor covers more than one
    movement."""
    merchant = normalize_merchant(descriptor)
    # An instrument — a check, an ATM withdrawal, a wire — never generalizes,
    # even when several share a descriptor. The kind comes from enrichment
    # (`counterparty_kind`), not from a list of words kept by hand.
    is_instrument = proj.kind_of_merchant(merchant) in ("instrument", "peer")
    generalizes = bool(merchant) and is_shareable(descriptor) and not is_instrument
    scope = SCOPE_MERCHANT if generalizes and not movement_key else SCOPE_MOVEMENT
    subject = merchant if scope == SCOPE_MERCHANT else movement_key
    if scope == SCOPE_MOVEMENT and not subject:
        # Refuse rather than quietly settle a whole conduit bucket on one answer.
        matches = [m for m in proj.movements()
                   if merchant in proj.merchant_keys_of(m)]
        if len(matches) != 1:
            raise ValueError(
                f"{descriptor!r} needs a specific transaction: it covers "
                f"{len(matches)} movements that may each mean something different")
        subject = matches[0].key

    legs, new_accounts, confirm, unnamed = [], [], [], []
    implied = proj.implication_for(merchant)
    for leg in interp.legs:
        match = resolve_account(proj, leg["major"], leg.get("account_hint", ""),
                                group=(implied or {}).get("account_group", ""))
        legs.append({"major": leg["major"], "account": match.account,
                     "share": leg.get("share", "")})
        if match.verdict == "new":
            new_accounts.append(match.account)
        elif match.verdict == "ambiguous":
            confirm.append(match.candidate)
        elif match.verdict == "unnamed":
            unnamed.append(leg["major"])

    settles = 1
    if scope == SCOPE_MERCHANT:
        settles = sum(1 for m in proj.movements()
                      if merchant in proj.merchant_keys_of(m))
    return Proposal(
        scope=scope, subject=subject, legs=legs, new_accounts=new_accounts,
        confirm_accounts=confirm, needs_name=unnamed,
        # The document comes from the counterparty's implication, learned at
        # enrichment, and never from the interpreter's free text.
        corroborates=(implied or {}).get("documents", ""),
        category=interp.category, said=interp.said,
        unknown_split=interp.compound and not interp.shares_known,
        settles=max(settles, 1), amount=amount, currency=currency,
        prompt_version=interp.version, locale=locale)


def one_shot_extractor(spec):
    """The live model edge for interpretation — one call, never continued.

    The shared driver continues across truncation; this sets
    `max_continuations=0`, so a reply that hits the token limit is reported
    rather than stitched back together. The returned text is prefixed with
    `TRUNCATED_MARK` in that case."""
    from vivacore.models import adapter_for

    adapter = adapter_for(replace(spec, max_continuations=0))

    def _extract(prompt: str) -> str:
        result = adapter.extract([], prompt)
        if result.finish_reason == "length":
            # Neither a transport failure nor a bad reading, but a third case,
            # marked so `interpret` reports it as `too_long` rather than as
            # `unparseable`.
            log.warning("interpret: the model ran past its limit (%d output tokens) "
                        "— refusing to stitch a bounded answer back together",
                        result.output_tokens)
            return TRUNCATED_MARK + (result.text or "")
        return result.text

    return _extract


# --------------------------------------------------------------------- step 6


def apply_proposal(ledger, proposal: Proposal, occurred_at: str,
                   by: str = "human") -> dict:
    """Write it. Deterministic, and the only path from a sentence to the ledger.

    An account the person brought into being is opened with `origin=asserted`,
    which is how the ledger keeps what an issuer attests separate from what a
    person told it. Returns the scope, subject, accounts opened, how many
    movements it settles, and the category, if any.

    Refuses a proposal with an unnamed leg: there is a question to ask first,
    and an account nobody named is the thing this path exists to prevent."""
    if not proposal.applicable:
        raise ValueError("this proposal has something with no name yet — ask "
                         "what it is before writing anything")
    grade = VERIFIED if by == "human" else UNVERIFIED
    opened = []
    for account in proposal.new_accounts:
        # An account path is root, group and the person's name for the thing;
        # anything shorter or emptier names a group.
        parts = account.split(":")
        if (len(parts) < 3 or not all(p.strip() for p in parts)
                or not any(ch.isalnum() for ch in parts[-1])):
            raise ValueError(f"{account!r} names nothing — an account needs a "
                             "name the person gave it")
        if parts[0] not in MAJOR_ROOTS.values():
            raise ValueError(f"{account!r} is outside the chart of accounts; "
                             f"a root is one of {sorted(set(MAJOR_ROOTS.values()))}")
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
        # The account's currency is what it is OPENED in; the naming answer a
        # proposal carries is a word, not an amount, and stamping a currency on
        # it would declare text to be money.
        value=proposal.value, currency="",
        prompt_version=proposal.prompt_version))
    # One confirmation can settle several facts about the same account — the
    # loan's name and what it secures, said in one breath.
    if proposal.attributes:
        account = proposal.subject.rpartition(":")[0]
        for attr in proposal.attributes:
            ledger.append(ruling_recorded(
                SCOPE_ATTRIBUTE, f"{account}:{attr['key']}", occurred_at,
                by=by, grade=grade, said=attr.get("said", ""),
                value=attr.get("value", ""), currency=attr.get("currency", "")))
    # One sentence can carry two rulings — a major and a label. Both are
    # written, through the existing writers, at the scope the ruling used.
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
           extract_fn=None, source: str = "", asked: str = "",
           locale: str = "") -> Proposal | None:
    """Steps 3–5 in one call: sentence in, reviewable Proposal out. Nothing is
    written — applying is a separate, explicit act."""
    read = read_answer(said, RULING_SLOTS, asked=asked,
                       context=ruling_context(descriptor, category,
                                              subcategory, source),
                       extract_fn=extract_fn)
    interp = ruling_from(read, said)
    if not interp.legs:
        return None
    return propose(proj, interp, descriptor, amount, currency, movement_key,
                   locale=locale)
