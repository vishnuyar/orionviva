"""The question queue — everything Viva needs from the person, ranked.

Seven ask-and-learn loops — *whose account is this?*, *does this statement
reconcile?*, *are these the same money?*, *what is this merchant?*, *is this
spending or moving?*, *what kind of arrangement is this?*, *what else is true
of this thing you own?* — gathered into one ranked list, alongside corroboration
asks and the knowledge registry's unmet expectations. Eight builders in all,
raising nine kinds of question: a held document raises two.

A **read-side projection**: no new event type, no ingest change. Answering routes
to the writers that already exist, so a ruling is recorded exactly as before and
the question stops being raised on the next projection.

Three rules shape the list:

  1. **Leverage ranking.** Highest stake first. One ruling on a large merchant
     can settle more than a hundred small ones.
  2. **Scope: one ruling clears many.** A question is raised at the most general
     unit that is still honest — commercial merchants generalize, past and
     future; a peer descriptor or an ambiguous pair does not.
  3. **The tail is summarized, not dropped.** The top N surface; the rest is
     reported with its count and total.

Question text is a deterministic template, never a model call. The templates live
in the persona pack (`viva/persona/`): the queue supplies the intent — figures
and evidence — and the pack supplies the words, with a lint test guaranteeing a
phrasing can only place fields the intent supplied, of the kinds it declared.

Nothing here formats a figure. An amount is written by the one renderer
(`viva/render.py`), under the conventions of the configured locale, so a person
reading a question and a person answering one meet the same amount written the
same way.

Every question also declares **the structure an answer to it has**: a list of
typed slots (`viva/reply.py`). That declaration is the whole inbound contract.
It is handed to the model as the structure to fill, and every value that comes
back is checked against its slot's type before anything is written. A question
that declares no slots is one nothing said in words can settle — its document
answers it — and saying so is honest rather than a gap.

**Every question is answered in language.** The queue carries no buttons, no
actions and no arguments for any surface: a surface has the words a person typed
and the question they answered, and nothing else to send.

"Not now" is an answer: a declined question stays suppressed while its stake
(amount, count) is unchanged, and returns the moment new evidence moves it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from merchantcore.enrich import BILLING_PERIODS, BILLING_STANDING

from .ingest import held_items, other_holds
from .ledger.merchants import is_shareable
from .ledger.events import (ASSERTED, PERIOD_ANNUAL, PERIOD_IRREGULAR,
                            PERIOD_MONTHLY, PERIOD_ONE_TIME, PERIODICITIES)
from .ledger.projection import (BY_CATEGORY, BY_DEFAULT, SPENDING,
                                TIER_SETTLED, TIER_STRUCTURAL,
                                TIER_UNENRICHED, TIER_UNKNOWN)
from .ledger.projection.rhythm import IN
from .listen import (category_vocabulary, ruling_slots,
                     shareable_categories)
from .persona import say
from .render import (account as render_account, category as render_category,
                     count as render_count, date as render_date,
                     document as render_document, merchant as render_merchant,
                     money as render_money)
from .reply import Slot
from .schemas import ANSWER_CHOICE, ANSWER_LABEL, ANSWER_LINK, ANSWER_YES_NO

# How many questions to surface before summarizing the rest. A count, never a
# money threshold.
DEFAULT_LIMIT = 10

# Question kinds.
IDENTITY = "identity"              # whose account is this?
RECONCILIATION = "reconciliation"  # this document didn't add up
TRANSFER = "transfer"              # are these two movements the same money?
MERCHANT = "merchant"              # what is this merchant?
NATURE = "nature"                  # is this money spent, or moved?
CORROBORATION = "corroboration"    # do you have the document that proves this?
EXPECTATION = "expectation"        # a document that should exist, somewhere
INTERVIEW = "interview"            # the next thing this account needs known
RHYTHM = "rhythm"                  # what kind of arrangement is this?


@dataclass
class Question:
    """One thing Viva needs from the person, with the evidence and the stakes.

    ``id`` is derived from what the question is *about* (not from event ids), so
    it is stable across projections — the same question doesn't churn between
    reads, and a surface can keep its place."""

    id: str
    kind: str
    text: str                      # Viva's voice, deterministic
    why: str                       # the evidence it rests on
    amount: Decimal                # what answering moves — the ranking key
    currency: str = ""
    count: int = 1                 # how many movements/documents it settles
    scope: str = "one"             # "one" | "pattern"
    # The structure an answer to this has. Empty means nothing said in words
    # settles it — a document does.
    slots: tuple = ()
    refs: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"id": self.id, "kind": self.kind, "text": self.text,
                "why": self.why, "amount": str(self.amount),
                "currency": self.currency, "count": self.count,
                "scope": self.scope,
                "slots": [s.to_dict() for s in self.slots], "refs": self.refs}


# --------------------------------------------------------------- the sources


# Is this the account you already have? A person answers that with a yes or a
# no, so that is what the slot is. Which ruling a yes and a no each stand for is
# decided by code on the write side, where the machine's words belong.
IDENTITY_SLOTS = (Slot(name="same_account", type=ANSWER_YES_NO, required=True),)

# Do you have the document? The document is what settles the question; the
# answer only says whether to expect one.
DOCUMENT_SLOTS = (Slot(name="have_it", type=ANSWER_YES_NO, required=True),)


def _held_questions(proj, locale: str = "") -> list[Question]:
    """Documents held for review — a gap, an identity doubt, or a flagged
    reconciliation. The stake is the statement's closing amount."""
    out: list[Question] = []
    for h in held_items(proj):
        f = h.facts
        amount = abs(f.closing_amount)
        if h.reason == "gap":
            text = say("reconciliation_gap",
                       account_ref=render_account({"name": f.account_ref}),
                       opening_date=render_date(f.opening_date),
                       closing_date=render_date(f.closing_date))
            why = say("reconciliation_gap_why",
                      opening_money=render_money(abs(f.opening_amount),
                                                 f.currency, locale=locale))
        elif h.reason == "identity":
            text = say("identity",
                       account_ref=render_account({"name": f.account_ref}))
            why = (h.finding or {}).get("message", "")
        else:
            text = say("reconciliation_flagged",
                       account_ref=render_account({"name": f.account_ref}))
            why = (h.finding or {}).get("message", "")
        identity = h.reason == "identity"
        kind = IDENTITY if identity else RECONCILIATION
        out.append(Question(
            id=f"{kind}:{h.doc_id[:12]}", kind=kind, text=text, why=why,
            amount=amount, currency=f.currency, count=1, scope="one",
            # An identity doubt is settled by saying whether it is the account
            # already held. A reconciliation is settled by a document, so
            # nothing said in words answers it.
            slots=IDENTITY_SLOTS if identity else (),
            refs={"doc_id": h.doc_id}))
    # Held documents with no fix-it flow yet (pay stub, brokerage) are still
    # asked about, with no option beyond showing the document.
    for b in other_holds(proj):
        out.append(Question(
            id=f"{RECONCILIATION}:{b['doc_id'][:12]}", kind=RECONCILIATION,
            text=_held_text(b),
            why=b.get("message", "") or f"held: {b.get('reason', '')}",
            amount=Decimal("0"), currency="", count=1, scope="one",
            # No slots: nothing said in words settles this one. The document
            # does, and looking at it answers nothing.
            refs={"doc_id": b["doc_id"]}))
    return out


def _held_text(held: dict) -> str:
    """What Viva says about a document she is holding.

    Two whole sentences rather than one with a fragment slotted into it: the
    account is either known or it is not, and a slot that holds an account
    holds an account, never a preposition with a string behind it."""
    doc_type = render_document(held["doc_type"].replace("_", " "))
    if held["account_ref"]:
        return say("reconciliation_held_for", doc_type=doc_type,
                   account_ref=render_account({"name": held["account_ref"]}))
    return say("reconciliation_held", doc_type=doc_type)


def _transfer_questions(proj, locale: str = "") -> list[Question]:
    """Two movements that might be the same money. Scoped to the one movement:
    an ambiguous pair generalizes to nothing. Candidates already linked by
    another ruling are dropped, and a suggestion with none left is skipped."""
    by_key = {m.key: m for m in proj.movements()}
    linked = proj.linked_keys()
    out: list[Question] = []
    for s in proj.transfer_suggestions():
        cands = [k for k in s.get("candidates", []) if k not in linked]
        if not cands:
            continue
        src = by_key.get(s["a"])
        if src is None:
            continue
        ev = s.get("evidence", {})
        amount = abs(src.amount)
        out.append(Question(
            id=f"{TRANSFER}:{src.key}", kind=TRANSFER,
            text=say("transfer", date=render_date(src.date),
                     money=render_money(amount, src.currency, locale=locale),
                     description=render_merchant({"example": src.description})),
            why=say("transfer_why", candidates=render_count(len(cands))),
            amount=amount, currency=src.currency, count=1, scope="one",
            # Was that the same money, or not: one slot, a yes or a no, and a
            # sentence that fills it with neither is asked again rather than
            # read as something else.
            slots=(Slot(name="same_money", type=ANSWER_YES_NO, required=True),),
            refs={"movement": src.key, "candidates": cands}))
    return out


def _merchant_questions(proj, locale: str = "") -> list[Question]:
    """Merchants we have no category for. Scoped to the MERCHANT — one ruling
    fills every transaction from it, past and future.

    The count and the money in the question are over one set of movements: the
    expense-shaped ones. The wider view — every counterparty, inflows and card
    payments included — is what enrichment works from, not what is asked
    about here."""
    out: list[Question] = []
    totals: dict[str, Decimal] = {}
    currency: dict[str, str] = {}
    movements: dict[str, list] = {}
    for m in proj.uncategorized_expenses():
        key = proj.merchant_key_of(m)
        if key:
            totals[key] = totals.get(key, Decimal("0")) + abs(m.amount)
            currency.setdefault(key, m.currency)
            movements.setdefault(key, []).append(m.key)
    # The picker's options, read from the one definition of the vocabulary.
    categories = category_vocabulary(proj)
    for key, row in proj.uncategorized_merchants(expenses_only=True).items():
        amount = totals.get(key, Decimal("0"))
        cur = currency.get(key, "")
        shareable = row.get("shareable", True)
        out.append(Question(
            id=f"{MERCHANT}:{key}", kind=MERCHANT,
            text=(say("merchant",
                      example=render_merchant({"example": row["example"]}),
                      count=render_count(row["count"]),
                      money=render_money(amount, cur, locale=locale))
                  + ("" if shareable else " " + say("merchant_peer_note"))),
            why=say("merchant_why"),
            amount=amount, currency=cur, count=row["count"],
            # A commercial merchant generalizes; a peer descriptor does not.
            scope="pattern" if shareable else "one",
            # What this merchant is, from the categories this vault knows. The
            # vocabulary is validation, not a set of buttons: an answer outside
            # it is asked again with the alternatives named, rather than minting
            # a new category out of a typo.
            slots=(Slot(name="category", type=ANSWER_CHOICE,
                        choices=tuple(categories),
                        # A person answers with any category they hold; only
                        # the shareable part of it is named to a model (T9).
                        offered=shareable_categories(categories),
                        required=True),),
            refs={"merchant": key, "example": row["example"],
                  "categories": categories,
                  # A peer is answered per transaction, so the surface needs the
                  # movements; a commercial merchant is answered once, for all.
                  "movements": movements.get(key, []) if not shareable else []}))
    return out


def _nature_questions(proj, locale: str = "") -> list[Question]:
    """What this money is — asked only where the counterparty cannot say.

    The tier decides:

      settled     an ordinary counterparty implying nothing  → no question
      structural  the counterparty implies a relationship    → one grouped
                                                               proposal per key
      unknown     an instrument or a peer                    → one question per
                                                               movement
      unenriched  → nothing here; it is a merchant question instead"""
    out: list[Question] = []
    singles: list = []
    groups: dict[str, dict] = {}
    # A ruling can name a category, so it is offered from the same vocabulary
    # a merchant question offers; `ruling_slots` holds what reaches a model to
    # what may cross (T9).
    categories = category_vocabulary(proj)

    for m in proj.movements():
        if not proj._is_expense(m):
            continue
        tier = proj.tier_of(m)
        if tier == TIER_SETTLED:
            continue                      # already known; nothing to ask
        if tier == TIER_UNENRICHED:
            continue                      # that is a MERCHANT question, not this
        # Whatever the tier, a movement whose nature something stronger has
        # already decided is not asked about again.
        if m.nature_reason not in (BY_CATEGORY, BY_DEFAULT):
            continue                      # a link, an own account or a ruling settled it
        if tier == TIER_UNKNOWN:
            singles.append(m)             # a check, an ATM, a peer: one at a time
            continue
        key = proj.merchant_key_of(m)
        g = groups.setdefault(key, {
            "amount": Decimal("0"), "count": 0, "currency": m.currency,
            "example": m.description, "keys": [],
            "implied": proj.implication_of(m) or {},
            "category": (proj.derived_category(m) or {}).get("category", ""),
            "subcategory": (proj.derived_category(m) or {}).get("subcategory", "")})
        g["amount"] += abs(m.amount)
        g["count"] += 1
        g["keys"].append(m.key)

    # Tier 3 — genuinely unknown, one transaction at a time.
    for m in singles:
        ruling = proj.derived_category(m) or {}
        out.append(Question(
            id=f"{NATURE}:{m.key}", kind=NATURE,
            text=say("nature_single", date=render_date(m.date),
                     description=render_merchant({"example": m.description}),
                     money=render_money(abs(m.amount), m.currency,
                                        locale=locale)),
            why=say("nature_single_why"),
            amount=abs(m.amount), currency=m.currency, count=1, scope="one",
            # What the money became, in the person's own words. Several slots,
            # because one payment can be several things at once — and that is
            # all "a ruling" ever was.
            slots=ruling_slots(categories),
            refs={"movement": m.key, "movements": [m.key],
                  "descriptor": m.description,
                  "category": ruling.get("category", ""),
                  "subcategory": ruling.get("subcategory", "")}))

    # Tier 2 — an implication exists: state it, then offer the choice.
    for key, g in groups.items():
        implied = g["implied"]
        # What a payment of this kind is, as a category this vault holds. The
        # counterparty's own words for the relationship it implies are a label a
        # model coined, and a category slot holds a category.
        what = g["subcategory"] or g["category"]
        head = say("nature_group_head", count=render_count(g["count"]),
                   example=render_merchant({"example": g["example"]}),
                   money=render_money(g["amount"], g["currency"],
                                      locale=locale))
        text = head
        if what:
            text += " " + say("nature_group_meaning",
                              what=render_category(what))
        if implied.get("compound"):
            text += " " + say("nature_group_compound")
        # The closing ask comes from the pack, like every other sentence Viva
        # says. What the counterparty implies travels with the question as its
        # category and its documents — data a lint can check — never as a
        # sentence written somewhere else and spliced in whole.
        text += " " + say("nature_group_ask")
        why = say("nature_group_why")
        if implied.get("documents"):
            why += " " + say("nature_group_why_documents",
                             documents=render_document(implied["documents"]))
        out.append(Question(
            id=f"{NATURE}:{key}", kind=NATURE, text=text, why=why,
            amount=g["amount"], currency=g["currency"], count=g["count"],
            scope="pattern", slots=ruling_slots(categories),
            refs={"merchant": key, "movements": g["keys"],
                  "descriptor": g["example"], "category": g["category"],
                  "subcategory": g["subcategory"],
                  # What the counterparty implies travels as structure — the
                  # major it suggests, the group an account would sit in, the
                  # document that would corroborate it — and never as a sentence
                  # someone else wrote.
                  "implied_major": implied.get("major", ""),
                  "account_group": implied.get("account_group", ""),
                  "documents": implied.get("documents", "")}))
    return out


# What each of the four stored words means, in the plain terms a person would
# use for it. The meanings travel with the alternatives so none of the four is
# offered bare, and each says only what its own word means.
PERIODICITY_MEANINGS = {
    PERIOD_MONTHLY: "an arrangement that comes round about every month",
    PERIOD_ANNUAL: "an arrangement that comes round about once a year",
    PERIOD_ONE_TIME: "a one-off — it happened once, and repeats no further",
    PERIOD_IRREGULAR: "nothing arranged with them; the money moves as and when",
}

# What arrangement do you have with them? One relationship can hold several at
# once — a monthly one and an annual one with the same counterparty — so the
# slot holds several periodicities rather than one, each landing in the
# ledger's own closed vocabulary.
RHYTHM_SLOTS = (
    Slot(name="periods", required=True, parts=(
        Slot(name="period", type=ANSWER_CHOICE, choices=PERIODICITIES,
             meanings=tuple(PERIODICITY_MEANINGS.items()), required=True),)),
)

# The sentence that states the prior's usual period, one per period the
# catalog's closed vocabulary may name.
PRIOR_PERIOD_SAYS = {period: f"rhythm_prior_period_{period}"
                     for period in BILLING_PERIODS}

# How one part of a mixture is described, chosen by what its own amounts were
# measured to be. Nothing here calls a part a subscription or a purchase: what
# is said is that these amounts repeat and those do not.
MIXTURE_PART_SAYS = {"fixed": "rhythm_mixture_part_repeating",
                     "variable": "rhythm_mixture_part_varying",
                     "unknown": "rhythm_mixture_part_lone"}


def _rhythm_questions(proj, locale: str = "") -> list[Question]:
    """What kind of arrangement a counterparty is — one proposal per
    `(merchant, direction)` the catalog says an arrangement is possible for.

    The prior licenses the question and the measurement proposes its answer, so
    the same mechanism serves a merchant seen once and a merchant seen fourteen
    times, with different evidence and visibly different sentences. A
    relationship with enough movements to have been measured is spoken of as
    measured whether what was found was a rhythm or the absence of one; only a
    relationship below the floor is told what the world knows instead. Where the
    movements did not decompose into one thing there is a fourth shape, which
    describes what it saw of each part and asks which is which, claiming no
    cadence over the whole.

    A pair somebody has already ruled on is not raised again: the answer
    generalizes over every movement with that counterparty, past and future."""
    out: list[Question] = []
    for h in proj.rhythm_hypotheses():
        if h.confirmed:
            continue                      # settled; the ruling is what answers now
        text = say("rhythm_head", count=render_count(h.count),
                   example=render_merchant({"example": h.example}),
                   money=render_money(h.amount, h.currency, locale=locale))
        text += " " + say("rhythm_direction_in" if h.direction == IN
                          else "rhythm_direction_out")
        if h.mixed:
            # Two things on one counterparty, named rather than averaged.
            # Every figure below belongs to one part and was measured over that
            # part alone; no cadence, interval or sameness of amount is claimed
            # over the whole, and which part is an arrangement is what is being
            # asked rather than asserted.
            text += " " + say("rhythm_mixture_lead")
            for part in h.components:
                text += " " + say(
                    MIXTURE_PART_SAYS[part.amount_stability],
                    count=render_count(part.count),
                    money=render_money(part.amount, h.currency, locale=locale))
            text += " " + say("rhythm_mixture_ask")
            why = say("rhythm_why_mixture")
        elif h.measured and h.steady:
            text += " " + say("rhythm_measured",
                              days=render_count(h.interval_days))
            if h.amount_stability == "fixed":
                text += " " + say("rhythm_measured_fixed")
            text += " " + say("rhythm_ask")
            why = say("rhythm_why_measured")
        elif h.measured:
            # Enough was seen, and what it showed is that these do not come
            # round on anything — a measurement, and one of the words a person
            # may confirm. No interval is stated, because none held, and the
            # sentence for having seen almost nothing is not borrowed.
            text += " " + say("rhythm_irregular")
            if h.amount_stability == "fixed":
                text += " " + say("rhythm_measured_fixed")
            text += " " + say("rhythm_irregular_ask")
            why = say("rhythm_why_irregular")
        else:
            # No cadence is claimed here: below the floor nothing was
            # measured, and the world's knowledge of the merchant is not a
            # measurement of this relationship.
            text += " " + say("rhythm_prior_standing"
                              if h.billing == BILLING_STANDING
                              else "rhythm_prior_either")
            period_says = PRIOR_PERIOD_SAYS.get(h.billing_period)
            if period_says:
                text += " " + say(period_says)
            text += " " + say("rhythm_ask")
            why = say("rhythm_why_prior")
        out.append(Question(
            id=f"{RHYTHM}:{h.subject}", kind=RHYTHM, text=text, why=why,
            # Ranked on the money this relationship has already moved; a
            # stake is a ranking key rather than a spoken figure, and nothing
            # here projects what it will move next.
            amount=h.amount, currency=h.currency, count=h.count,
            scope="pattern", slots=RHYTHM_SLOTS,
            refs={"merchant": h.merchant, "direction": h.direction,
                  "movements": list(h.movements), "descriptor": h.example,
                  # The hypothesis travels as structure a lint can check:
                  # what the world says, what the ledger measured, and what the
                  # two together propose.
                  "billing": h.billing, "billing_period": h.billing_period,
                  "measured": h.measured, "steady": h.steady,
                  "cadence": h.cadence if h.measured else "",
                  "proposed": list(h.proposed),
                  # And what the movements decomposed into. One entry is one
                  # thing measured; two is a mixture, and every figure in the
                  # sentence above is traceable to the entry it came from.
                  "components": [
                      {"count": part.count, "amount": str(part.amount),
                       "amount_stability": part.amount_stability,
                       "measured": part.measured, "steady": part.steady,
                       "cadence": part.cadence,
                       "movements": list(part.movements)}
                      for part in h.components]}))
    return out


def _corroboration_questions(proj, locale: str = "") -> list[Question]:
    """Documents that would corroborate a ruling.

    An account a ruling created is `asserted`: only the person says it exists.
    The invoice, the 1098 or the closing disclosure is what carries it from
    `asserted` to `issued`. Raised only for an asserted account whose ruling
    names a corroborating document.

    The ask is never a gate — the account exists and the money is recorded
    already — and it is ranked with every other question by what it settles."""
    out: list[Question] = []
    for account, row in proj.ruled_accounts().items():
        if row.get("origin") != ASSERTED:
            continue
        doc = ""
        for ruling in proj.rulings():
            if ruling.get("corroborates") and any(
                    leg.get("account") == account for leg in ruling.get("legs", [])):
                doc = ruling["corroborates"]
                break
        if not doc:
            continue
        text = say("corroboration", name=render_account({"path": account}),
                   money=render_money(abs(row["paid"]), row["currency"],
                                      locale=locale),
                   document=render_document(doc))
        why = (say("corroboration_why")
               + (" " + say("corroboration_why_unreliable")
                  if not row["reliable_balance"] else ""))
        out.append(Question(
            id=f"{CORROBORATION}:{account}", kind=CORROBORATION, text=text.strip(),
            why=why.strip(), amount=row["paid"], currency=row["currency"],
            count=row["count"], scope="one", slots=DOCUMENT_SLOTS,
            refs={"account": account, "document": doc}))
    return out


def _interview_questions(proj, jurisdiction: str) -> list[Question]:
    """The next thing each account still needs known.

    One question per interview, never the whole form: the schema knows what may
    be asked, and the interview knows what is still owed, so the queue asks for
    exactly one thing and the next follows from the answer. Ranked with
    everything else by the cash a ruling has put against the account — the
    money an answer would make sense of — so an interview never outranks a
    larger finding just for being new. An account whose money a statement
    already explains settles nothing by being described, and says so with a
    stake of zero rather than borrowing its balance."""
    from . import schemas
    from .interview import interviews, opens_pending, question_id
    out: list[Question] = []
    ivs = interviews(proj, jurisdiction)
    for iv in ivs:
        if iv.schema is None:
            continue
        # The next thing owed, plus anything set aside and still unanswered.
        # A set-aside question is still BUILT — the decline filter is what
        # keeps it out of the ranked list — so it can be found in the pending
        # list and can return the moment its stake moves.
        asking = [q for q in (iv.next_question,) if q is not None]
        asking += [q for q in iv.schema.questions
                   if q.key in iv.declined and q.key not in iv.answered]
        for q in asking:
            out.append(_interview_question(iv, q, ivs))

    for iv, opened in opens_pending(proj, jurisdiction, known=ivs):
        schema = schemas.schema_for(opened, jurisdiction)
        if schema is None:
            continue
        out.append(Question(
            id=question_id(iv.account, f"opens:{opened}"), kind=INTERVIEW,
            text=say("interview_opens", name=render_account({"name": iv.name}),
                     kind_label=schema.label or opened),
            why=say("interview_why"), amount=iv.stake, currency=iv.currency,
            count=iv.settles, scope="one",
            # Answering here NAMES the thing rather than saying something about
            # it, so the one slot is the person's own word for it.
            slots=(Slot(name="name", type=ANSWER_LABEL, required=True,
                        asks=naming_asks(schema)),),
            # No `key`: this question is not about an attribute of an account
            # that exists. `opens` is what says the answer names the thing
            # rather than answering about it.
            refs={"account": iv.account, "opens": opened, "key": "",
                  "kind_label": schema.label or opened}))
    return out


def naming_asks(schema) -> str:
    """The schema pack's own words for "what do you call it?", or "".

    Reviewed prose, carried through as data — nothing here writes a sentence."""
    naming = schema.naming_question()
    return naming.asks if naming is not None else ""


def _interview_question(iv, q, ivs) -> Question:
    """One schema question, worded and given the one slot it declares.

    The slot's vocabulary comes from the schema — the alternatives a choice
    enumerates, the accounts a link may point at — so nothing outside what the
    schema permits can be accepted, and the model is told exactly what may
    land."""
    from . import schemas
    from .interview import question_id
    choices = tuple(q.choices)
    if q.answer == ANSWER_LINK:
        # Which accounts this may point at. The vault still decides whether one
        # resolves; this only says which are worth naming.
        choices = tuple(other.account for other in ivs
                        if other.kind == q.links_to
                        and other.account != iv.account)
    text = say("interview", name=render_account({"name": iv.name}),
               asks=q.asks)
    if q.unlocks:
        text += " " + say("interview_unlocks", unlocks=q.unlocks)
    return Question(
            id=question_id(iv.account, q.key), kind=INTERVIEW, text=text,
            why=say("interview_why"), amount=iv.stake, currency=iv.currency,
            count=iv.settles, scope="one",
            # The schema already said what kind of answer this needs and in what
            # words to ask for it, so the question carries both where every
            # other question carries them.
            slots=(Slot(name=q.key, type=q.answer, choices=choices,
                        required=True, asks=q.asks),),
            refs={"account": iv.account, "kind": iv.kind, "key": q.key,
                  "unlocks": q.unlocks,
                  "corroborated_by": list(q.corroborated_by)})


def _expectation_questions(proj, as_of: str, jurisdiction: str,
                           locale: str = "") -> list[Question]:
    """The knowledge registry's unmet expectations, asked as questions and ranked
    with everything else by the money the document would attest.

    The ask is never a gate, and "Not right now" declines it like any other
    question. A cadence expectation carries amount 0, so it ranks below every
    question that settles money."""
    from .knowledge import evaluate
    out: list[Question] = []
    for e in evaluate(proj, as_of, jurisdiction, locale=locale):
        why_fields = {"money": e.fields.get("money", "")} \
            if e.kind == "investment_account" else {}
        out.append(Question(
            id=e.id, kind=EXPECTATION,
            text=say(f"expectation_{e.kind}", **e.fields),
            why=say(f"expectation_{e.kind}_why", **why_fields),
            amount=e.amount, currency=e.currency, count=e.count,
            scope="pattern" if e.count > 1 else "one", slots=DOCUMENT_SLOTS,
            refs={"document": e.document, "subject": e.subject,
                  "registry_entry": e.entry_id}))
    return out


# ----------------------------------------------------------------- the queue


def open_questions(source, limit: int = DEFAULT_LIMIT, as_of: str = "",
                   jurisdiction: str = "", locale: str = "") -> dict:
    """Everything awaiting the person, ranked by how much money answering moves.

    Returns ``{"questions": [...], "tail": {"count": n, "amount": "…"}, "total":
    n}``. The tail is what ranking pushed below the fold — reported with its size
    and value so nothing is hidden, just not pushed.

    ``as_of`` grounds the cadence expectations — it defaults to today,
    and tests pass it explicitly so the queue stays reproducible. ``jurisdiction``
    filters the knowledge registry; it defaults from ``VIVA_LOCALE``'s region.
    ``locale`` decides how a figure is written, and defaults from the same
    setting, so the conventions a question is written in are the conventions an
    answer is read in."""
    if not as_of:
        from datetime import date as _date
        as_of = _date.today().isoformat()
    if not jurisdiction:
        # The one locale accessor. A locale with no region part filters to
        # universal registry entries only.
        from .env import jurisdiction_from_env
        jurisdiction = jurisdiction_from_env().upper()
    locale = locale or _locale()
    proj = getattr(source, "projection", lambda: source)()
    qs: list[Question] = []
    qs += _held_questions(proj, locale)
    qs += _transfer_questions(proj, locale)
    qs += _merchant_questions(proj, locale)
    qs += _nature_questions(proj, locale)
    qs += _rhythm_questions(proj, locale)
    qs += _corroboration_questions(proj, locale)
    qs += _expectation_questions(proj, as_of, jurisdiction, locale)
    qs += _interview_questions(proj, jurisdiction)
    open_qs, pending = _split_declined(proj, qs)
    # Highest stake first; ties broken by id so the order is stable between reads.
    open_qs.sort(key=lambda q: (-q.amount, q.id))
    shown, rest = open_qs[:limit], open_qs[limit:]
    return {
        "questions": [q.to_dict() for q in shown],
        "total": len(open_qs),
        "tail": {"count": len(rest),
                 "amount": str(sum((q.amount for q in rest), start=Decimal("0")))},
        # Questions set aside and still open. Deferring into a place the person
        # can look is how "it always comes back" and "never a nag" are both true.
        "pending": {"count": len(pending)},
        # What the box a person writes in says before they write, and what
        # stands in its place where a question only a document can settle. Both
        # come from the pack with every other sentence Viva says, so no surface
        # keeps person-facing words of its own.
        "invite": say("free_text_invite"),
        "answered_by_document": say("answered_by_document"),
    }


def find_question(source, question_id: str, as_of: str = "",
                  jurisdiction: str = "", locale: str = "") -> Question | None:
    """One question from the live queue, by id, or None.

    Built fresh from the same builders rather than taken from a caller, so an
    answer can only reach a question that is still being asked, with the slots
    it is being asked with. A question set aside is still found: answering one
    the person went looking for is answering it."""
    if not as_of:
        from datetime import date as _date
        as_of = _date.today().isoformat()
    if not jurisdiction:
        from .env import jurisdiction_from_env
        jurisdiction = jurisdiction_from_env().upper()
    locale = locale or _locale()
    proj = getattr(source, "projection", lambda: source)()
    qs: list[Question] = []
    qs += _held_questions(proj, locale)
    qs += _transfer_questions(proj, locale)
    qs += _merchant_questions(proj, locale)
    qs += _nature_questions(proj, locale)
    qs += _rhythm_questions(proj, locale)
    qs += _corroboration_questions(proj, locale)
    qs += _expectation_questions(proj, as_of, jurisdiction, locale)
    qs += _interview_questions(proj, jurisdiction)
    return next((q for q in qs if q.id == question_id), None)


def _locale() -> str:
    """The configured locale, through the one accessor. A figure is written the
    way this person's paperwork writes one."""
    from .env import locale_from_env
    return locale_from_env()


def _split_declined(proj, qs: list) -> tuple:
    """``(open, pending)``.

    A declined question stays declined while its amount and count are what they
    were when it was declined, and returns when either moves. No timers. For an
    interview the stake is the cash on the account and the count is how many
    movements touch it, so "new evidence touching its subject" is the same
    mechanism, not a second one."""
    declined = proj.declined_questions()

    def still_declined(q) -> bool:
        d = declined.get(q.id)
        return (d is not None and d.get("amount") == str(q.amount)
                and int(d.get("count", 0)) == q.count)

    return ([q for q in qs if not still_declined(q)],
            [q for q in qs if still_declined(q)])


def pending_questions(source, as_of: str = "", jurisdiction: str = "",
                      locale: str = "") -> dict:
    """Everything set aside and still open — the list the person opens
    themselves. Same builders, same ranking; only the decline filter is
    inverted, so a pending question cannot drift from its open twin."""
    locale = locale or _locale()
    proj = getattr(source, "projection", lambda: source)()
    qs: list[Question] = []
    qs += _held_questions(proj, locale)
    qs += _transfer_questions(proj, locale)
    qs += _merchant_questions(proj, locale)
    qs += _nature_questions(proj, locale)
    qs += _rhythm_questions(proj, locale)
    qs += _corroboration_questions(proj, locale)
    qs += _interview_questions(proj, jurisdiction)
    if as_of:
        qs += _expectation_questions(proj, as_of, jurisdiction, locale)
    _, pending = _split_declined(proj, qs)
    pending.sort(key=lambda q: (-q.amount, q.id))
    return {"questions": [q.to_dict() for q in pending], "total": len(pending)}
