"""The question queue — everything Viva needs from you, in the order that matters.

The learning loop's front door (Slice 6.5 Move 2, docs/the-question-queue.md).

The project had built four ask-and-learn loops separately — *whose account is
this?* (Slice 1.5), *are these the same money?* (Slice 3), *what is this
merchant?* (Slice 5.5), *is this spending or moving?* (Slice 6.5) — four queues,
four cards, one primitive. This gathers them into one ranked list.

It is a **read-side projection**: no new event type, no ingest change. Answering
routes to the writers that already exist, so a ruling is recorded exactly as it
was before and the question simply stops being raised (idempotent by
construction — state changed, so the next projection doesn't ask again).

Three rules keep it a butler rather than a chore list:

  1. **Leverage ranking.** Ask what moves the most money first. One ruling on a
     large merchant can settle more than a hundred small ones.
  2. **Scope: one ruling clears many.** A question is raised at the most general
     unit that is still honest — commercial merchants generalize (past and
     future), a peer descriptor or an ambiguous pair does not.
  3. **Silence by ranking, not hiding.** The top N surface; the tail is
     *summarized* with its count and total, never dropped. An unanswered question
     leaves its figure provisional and labelled (Move 1), so silence costs
     precision, never honesty.

Question text is a deterministic template, never a model call: the queue must be
reproducible, free and offline-testable, and a model that phrased a question
could smuggle a claim into it. Slice 9 re-voices these through the persona; the
content — figure, evidence, options — stays deterministic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from .ingest import held_items, other_holds
from .ledger.merchants import is_shareable, normalize_merchant
from .ledger.events import ASSERTED
from .ledger.projection import (BY_CATEGORY, BY_DEFAULT, SPENDING,
                                TIER_SETTLED, TIER_STRUCTURAL,
                                TIER_UNENRICHED, TIER_UNKNOWN)
from .listen import suggest_answers

# How many questions to surface before summarizing the rest. Not a materiality
# threshold in money — that would be a currency- and jurisdiction-shaped guess
# (I1/I5). Rank, show the top, and say honestly what is left.
DEFAULT_LIMIT = 10

# Question kinds, in the order they were originally built as separate loops.
IDENTITY = "identity"              # whose account is this?
RECONCILIATION = "reconciliation"  # this document didn't add up
TRANSFER = "transfer"              # are these two movements the same money?
MERCHANT = "merchant"              # what is this merchant?
NATURE = "nature"                  # is this money spent, or moved?
CORROBORATION = "corroboration"    # do you have the document that proves this?


@dataclass
class Question:
    """One thing Viva needs from the person, with the evidence and the stakes.

    ``id`` is derived from what the question is *about* (not from event ids), so
    it is stable across projections — the same question doesn't churn between
    reads, and a surface can keep its place."""

    id: str
    kind: str
    text: str                      # Viva's voice, deterministic
    why: str                       # the evidence it rests on (T1)
    amount: Decimal                # what answering moves — the ranking key
    currency: str = ""
    count: int = 1                 # how many movements/documents it settles
    scope: str = "one"             # "one" | "pattern"
    options: list = field(default_factory=list)   # {label, action, args}
    free_text: str = ""            # the prompt for an answer no button can hold
    refs: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"id": self.id, "kind": self.kind, "text": self.text,
                "why": self.why, "amount": str(self.amount),
                "currency": self.currency, "count": self.count,
                "scope": self.scope, "options": self.options,
                "free_text": self.free_text, "refs": self.refs}


def _money(amount: Decimal, currency: str) -> str:
    return f"{currency} {abs(amount):,.2f}".strip()


# --------------------------------------------------------------- the sources


def _held_questions(proj) -> list[Question]:
    """Documents we're sitting on. Usually the largest stake: a whole statement
    is not on your books until this is resolved."""
    out: list[Question] = []
    for h in held_items(proj):
        f = h.facts
        amount = abs(f.closing_amount)
        if h.reason == "gap":
            text = (f"Your {f.account_ref} statement for {f.opening_date} – "
                    f"{f.closing_date} doesn't continue from the balance I hold. "
                    "A statement between them looks missing — is one?")
            why = f"It opens at {_money(f.opening_amount, f.currency)}; my chain ends elsewhere."
        elif h.reason == "identity":
            text = (f"I read a statement for {f.account_ref}, but I can't tell "
                    "whose account it is. Is it one you already have, or a new one?")
            why = (h.finding or {}).get("message", "")
        else:
            text = (f"Your {f.account_ref} statement didn't add up, so I haven't "
                    "posted it. Can you check the figure I flagged?")
            why = (h.finding or {}).get("message", "")
        kind = IDENTITY if h.reason == "identity" else RECONCILIATION
        out.append(Question(
            id=f"{kind}:{h.doc_id[:12]}", kind=kind, text=text, why=why,
            amount=amount, currency=f.currency, count=1, scope="one",
            options=([{"label": "Same account", "action": "confirm_identity",
                       "args": {"doc_id": h.doc_id, "decision": "same"}},
                      {"label": "A new account", "action": "confirm_identity",
                       "args": {"doc_id": h.doc_id, "decision": "new"}}]
                     if h.reason == "identity" else
                     [{"label": "Review it", "action": "review",
                       "args": {"doc_id": h.doc_id}}]),
            refs={"doc_id": h.doc_id}))
    # Held documents with no fix-it flow yet (pay stub, brokerage) — still asked
    # about, because a document we're sitting on must never be invisible.
    for b in other_holds(proj):
        out.append(Question(
            id=f"{RECONCILIATION}:{b['doc_id'][:12]}", kind=RECONCILIATION,
            text=(f"I'm holding a {b['doc_type'].replace('_', ' ')} "
                  f"{('for ' + b['account_ref']) if b['account_ref'] else ''}"
                  " that didn't reconcile, so its figures aren't on your books."),
            why=b.get("message", "") or f"held: {b.get('reason', '')}",
            amount=Decimal("0"), currency="", count=1, scope="one",
            options=[{"label": "Show me the document", "action": "review",
                      "args": {"doc_id": b["doc_id"]}}],
            refs={"doc_id": b["doc_id"]}))
    return out


def _transfer_questions(proj) -> list[Question]:
    """Two movements that might be the same money. Genuinely one-off: an
    ambiguous pair generalizes to nothing, so it is scoped to itself."""
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
            text=(f"On {src.date} you moved {_money(amount, src.currency)} "
                  f"({src.description}). Was that money moving between your own "
                  "accounts rather than being spent?"),
            why=(f"{len(cands)} movement(s) of the same amount within a few days "
                 f"on another account you hold."),
            amount=amount, currency=src.currency, count=1, scope="one",
            options=[{"label": "Yes — same money", "action": "confirm_transfer",
                      "args": {"movement_a": src.key, "movement_b": cands[0]}},
                     {"label": "No — that's spending", "action": "reject_transfer",
                      "args": {"movement_a": src.key}}],
            refs={"movement": src.key, "candidates": cands}))
    return out


def _merchant_questions(proj) -> list[Question]:
    """Merchants we have no category for. Scoped to the MERCHANT — one ruling
    fills every transaction from it, past and future (the Slice 5.5 lesson)."""
    from .ingest.categorize import SEED_CATEGORIES
    out: list[Question] = []
    totals: dict[str, Decimal] = {}
    currency: dict[str, str] = {}
    movements: dict[str, list] = {}
    for m in proj.uncategorized_expenses():
        key = normalize_merchant(m.description)
        if key:
            totals[key] = totals.get(key, Decimal("0")) + abs(m.amount)
            currency.setdefault(key, m.currency)
            movements.setdefault(key, []).append(m.key)
    # The picker's options: the shared suggestions PLUS every category this person
    # has actually used. Categories are implicit — one exists by being used — so
    # the vocabulary grows without an event or a migration (Slice 6.7 D2).
    used = sorted({(r.get("category") or "").strip()
                   for r in proj.merchant_categories().values()} - {""})
    categories = list(SEED_CATEGORIES) + [c for c in used if c not in SEED_CATEGORIES]
    for key, row in proj.uncategorized_merchants().items():
        amount = totals.get(key, Decimal("0"))
        cur = currency.get(key, "")
        shareable = row.get("shareable", True)
        out.append(Question(
            id=f"{MERCHANT}:{key}", kind=MERCHANT,
            text=(f"What is {row['example']}? You have {row['count']} "
                  f"transaction(s) with it, {_money(amount, cur)} in total."
                  + ("" if shareable else
                     " (This looks like a payment to a person, so I'll only "
                     "apply your answer here — not as a rule.)")),
            why="I have no category for this merchant yet.",
            amount=amount, currency=cur, count=row["count"],
            # A commercial merchant generalizes; a peer descriptor does not.
            scope="pattern" if shareable else "one",
            options=[{"label": "Categorize it", "action": "assign_merchant",
                      "args": {"merchant": key}}],
            refs={"merchant": key, "example": row["example"],
                  "categories": categories,
                  # A peer is answered per transaction, so the surface needs the
                  # movements; a commercial merchant is answered once, for all.
                  "movements": movements.get(key, []) if not shareable else []}))
    return out


def _nature_questions(proj) -> list[Question]:
    """What is this money, really? — asked ONLY where the counterparty cannot say.

    Rebuilt in Slice 9b. It used to fire for every enriched merchant whose nature
    rested on a hint or a default — which meant asking *"is this spent or
    something you now own?"* about a supermarket we had already identified. We
    knew, and we asked anyway. The tiers make the rule explicit:

      settled     an ordinary counterparty implying nothing  → SILENCE
      structural  the counterparty implies a relationship    → an informed proposal
      unknown     an instrument or a peer                    → a real question, one at a time

    The queue's job is to be *short*. Every question it does not ask is one the
    product answered for you."""
    out: list[Question] = []
    singles: list = []
    groups: dict[str, dict] = {}

    for m in proj.movements():
        if not proj._is_expense(m):
            continue
        tier = proj.tier_of(m)
        if tier == TIER_SETTLED:
            continue                      # we know. asking would be noise.
        if tier == TIER_UNENRICHED:
            continue                      # that is a MERCHANT question, not this
        if tier == TIER_UNKNOWN:
            singles.append(m)             # a check, an ATM, a peer: one at a time
            continue
        if m.nature_reason not in (BY_CATEGORY, BY_DEFAULT):
            continue                      # a link, an own account or a ruling settled it
        key = normalize_merchant(m.description)
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
            text=(f"{m.date}: {m.description} — {_money(abs(m.amount), m.currency)}. "
                  "What was this one for?"),
            why=("This names how the money moved, not who received it — so I "
                 "have to ask about each one separately."),
            amount=abs(m.amount), currency=m.currency, count=1, scope="one",
            options=[{"label": s["label"], "action": "rule_major",
                      "args": {"movement_key": m.key, "major": s["major"]}}
                     for s in suggest_answers()],
            free_text="Or tell me in your own words",
            refs={"movement": m.key, "movements": [m.key],
                  "descriptor": m.description,
                  "category": ruling.get("category", ""),
                  "subcategory": ruling.get("subcategory", "")}))

    # Tier 2 — we have a hypothesis. Say it, name the doubt, offer the choice.
    for key, g in groups.items():
        implied = g["implied"]
        what = implied.get("relationship") or g["subcategory"] or g["category"]
        head = (f"You have {g['count']} payment(s) to {g['example']} totalling "
                f"{_money(g['amount'], g['currency'])}.")
        text = f"{head} These normally mean {what}."
        if implied.get("compound"):
            text += (" A payment like that is usually several things at once, and "
                     "I can't tell the split without the paperwork.")
        text += f" {implied.get('ask') or 'Shall I set that up?'}"
        why = f"Because of who they are, not because of anything you told me."
        if implied.get("documents"):
            why += f" Your {implied['documents']} would let me prove it."
        options = [{"label": f"Yes — {what}", "action": "rule_major",
                    "args": {"merchant": key, "major": implied.get("major", "expense"),
                             "descriptor": g["example"],
                             "group": implied.get("account_group", "")}},
                   {"label": "No — that was money spent", "action": "rule_major",
                    "args": {"merchant": key, "major": "expense",
                             "descriptor": g["example"]}}]
        out.append(Question(
            id=f"{NATURE}:{key}", kind=NATURE, text=text, why=why,
            amount=g["amount"], currency=g["currency"], count=g["count"],
            scope="pattern", options=options,
            free_text="Or tell me in your own words",
            refs={"merchant": key, "movements": g["keys"],
                  "descriptor": g["example"], "category": g["category"],
                  "subcategory": g["subcategory"],
                  "documents": implied.get("documents", "")}))
    return out


def _corroboration_questions(proj) -> list[Question]:
    """Documents that would PROVE what you told us (Slice 9a).

    Every account a ruling created is `asserted` — only you say it exists. That
    is honest and it is enough to run your finances on, but it is not evidence a
    counterparty could ever rely on. The invoice, the 1098, the closing
    disclosure is the ladder from `asserted` to `issued`.

    Two rules keep this from nagging, both deliberate: the ask is **never a
    gate** — the account is already created and the money already recorded — and
    it is **ranked with everything else**, so a large purchase surfaces and a
    small one does not."""
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
        name = account.split(":")[-1]
        text = (f"You told me about {name} — {_money(row['paid'], row['currency'])} "
                f"so far. Do you have the {doc}? It would let me prove this, "
                "not just record it.")
        why = ("This account exists because you said so; nothing has attested it. "
               + ("Its balance also can't be trusted yet, because part of those "
                  "payments was interest." if not row["reliable_balance"] else ""))
        out.append(Question(
            id=f"{CORROBORATION}:{account}", kind=CORROBORATION, text=text.strip(),
            why=why.strip(), amount=row["paid"], currency=row["currency"],
            count=row["count"], scope="one",
            options=[{"label": f"I have the {doc}", "action": "upload",
                      "args": {"account": account, "document": doc}},
                     {"label": "Not right now", "action": "dismiss",
                      "args": {"account": account}}],
            refs={"account": account, "document": doc}))
    return out


# ----------------------------------------------------------------- the queue


def open_questions(source, limit: int = DEFAULT_LIMIT) -> dict:
    """Everything awaiting the person, ranked by how much money answering moves.

    Returns ``{"questions": [...], "tail": {"count": n, "amount": "…"}, "total":
    n}``. The tail is what ranking pushed below the fold — reported with its size
    and value so nothing is hidden, just not pushed (principle 5)."""
    proj = getattr(source, "projection", lambda: source)()
    qs: list[Question] = []
    qs += _held_questions(proj)
    qs += _transfer_questions(proj)
    qs += _merchant_questions(proj)
    qs += _nature_questions(proj)
    qs += _corroboration_questions(proj)
    # Highest stake first; ties broken by id so the order is stable between reads.
    qs.sort(key=lambda q: (-q.amount, q.id))
    shown, rest = qs[:limit], qs[limit:]
    return {
        "questions": [q.to_dict() for q in shown],
        "total": len(qs),
        "tail": {"count": len(rest),
                 "amount": str(sum((q.amount for q in rest), start=Decimal("0")))},
    }
