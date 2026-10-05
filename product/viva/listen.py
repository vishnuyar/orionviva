"""Resolve checked sentence interpretations into accounting proposals and rulings.

Models fill declared slots. Local code validates those slots, resolves account
identity and applies the resulting counterpart treatment. Source movements
supply all amounts; rulings supply no new financial measurement. Explicitly
ordinary selected corrections use generic buckets without opening holdings.
Component proposals retain missing-name and ambiguous-account clarification."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, replace
from decimal import Decimal

from .ledger.events import (ASSERTED, ISSUED, MAJORS, MAJOR_ASSET, MAJOR_EXPENSE,
                            MAJOR_INCOME, MAJOR_LIABILITY, SCOPE_ATTRIBUTE,
                            SCOPE_MERCHANT, SCOPE_MOVEMENT, UNVERIFIED,
                            VERIFIED, account_alias_confirmed, account_opened,
                            ruling_recorded)
from .ledger.merchants import is_shareable, normalize_merchant
from .question_evidence import decide, group_decision
from .ledger.postings import MAJOR_ROOTS, MAJOR_UNCATEGORIZED, account_path
from .ledger.projection import BY_CATEGORY, BY_DEFAULT, BY_RULING
from .ledger.projection.movements import money_effect
from .render import (accounts as render_accounts,
                     money as render_money)
from .reply import TRUNCATED_MARK, Slot, answer as read_answer
from .schemas import ANSWER_CHOICE, ANSWER_DATE, ANSWER_LABEL, ANSWER_RATE

log = logging.getLogger("viva.listen")


_GENERIC_ACCOUNT_WORDS = frozenset({
    "account", "brokerage", "investment", "investments", "bank", "checking",
    "savings", "card", "credit", "debit", "the"})


def _identity_words(value: str) -> frozenset[str]:
    import re
    return frozenset(word for word in re.split(r"[^a-z0-9]+", value.lower())
                     if word and word not in _GENERIC_ACCOUNT_WORDS)


def _asserted_product_kind(value: str) -> str:
    """Return the issued account kind explicitly named by an asserted path."""
    words = set(value.lower().replace(":", " ").split())
    if words & {"brokerage", "investment", "investments", "portfolio"}:
        return "investment"
    if words & {"checking", "savings", "debit"}:
        return "depository"
    if words & {"credit"}:
        return "liability"
    return ""


def repair_asserted_account_aliases(ledger) -> int:
    """Alias each asserted account with one compatible issued identity match.

    Matching requires a unique issued account with the same identity words and
    a compatible product kind. The function appends alias events and is
    idempotent.
    """
    proj = ledger.projection()
    aliases = proj.account_aliases()
    issued = [info for info in proj.account_infos() if info.origin == ISSUED]
    repaired = 0
    for source in proj.ruled_accounts():
        if source in aliases:
            continue
        source_words = _identity_words(source.rsplit(":", 1)[-1])
        if not source_words:
            continue
        liability = source.startswith("Liabilities:")
        product_kind = _asserted_product_kind(source.rsplit(":", 1)[-1])
        candidates = []
        for info in issued:
            if liability != (info.kind == "liability"):
                continue
            if product_kind and info.kind != product_kind:
                continue
            identities = (_identity_words(info.name),
                          _identity_words(info.institution))
            if any(source_words == words for words in identities if words):
                candidates.append(info.account)
        unique = sorted(set(candidates))
        if len(unique) != 1:
            continue
        dates = [movement.date for movement in proj.movements()
                 if movement.ruling_account == source and movement.date]
        ledger.append(account_alias_confirmed(
            source, unique[0], "", max(dates, default=""), by="migration"))
        repaired += 1
        proj = ledger.projection()
        aliases = proj.account_aliases()
    return repaired

# Person-facing labels for stored accounting majors.
PLAIN = {
    MAJOR_EXPENSE: "Spent — the money is gone",
    MAJOR_ASSET: "I still have it, in another form",
    MAJOR_LIABILITY: "It changed what I owe",
    MAJOR_INCOME: "Money that came to me",
}

# Accounting-major clause fragments for longer sentences.
IN_A_SENTENCE = {
    MAJOR_EXPENSE: "money spent and gone",
    MAJOR_ASSET: "something you still have, in another form",
    MAJOR_LIABILITY: "a change in what you owe",
    MAJOR_INCOME: "money that came to you",
}

# Render additional ruled payments and refunds with separate counts/totals.
ALSO_SETTLES = ("It also settles {count} other payment(s) to them, worth "
                "{money} in total, that nothing needed to ask about.")
ALSO_CAME_BACK = ("It also covers {count} movement(s) of money back from them, "
                  "worth {money} in total.")

# Use enrichment account-group/document/order implications, or the fallback group.
_FALLBACK_GROUP = "Other"


# --------------------------------------------------------------------- step 2


# Each counterpart leg has a checked major and person-facing meaning.
RULING_SLOTS = (
    Slot(name="legs", required=True, parts=(
        Slot(name="major", type=ANSWER_CHOICE, choices=MAJORS,
             meanings=tuple(PLAIN.items()), required=True),
        Slot(name="account_hint", type=ANSWER_LABEL),
        Slot(name="share", type=ANSWER_RATE))),
    Slot(name="kind", type=ANSWER_LABEL),
    Slot(name="future_scope", type=ANSWER_CHOICE, choices=("one", "context", "recurring"),
         asks="Whether this is one exception, a narrow matching context, or a recurring relationship"),
    Slot(name="starts", type=ANSWER_DATE),
    Slot(name="ends", type=ANSWER_DATE),
    Slot(name="recurrence", type=ANSWER_CHOICE, choices=("monthly", "weekly", "yearly")),
)


def category_vocabulary(proj) -> tuple:
    """Return seed categories followed by used categories, deduplicated under _norm.

    The first spelling wins, so seed labels precede equivalent later spellings."""
    from .ingest.categorize import SEED_CATEGORIES

    used = sorted({(row.get("category") or "").strip()
                   for row in proj.merchant_categories().values()} - {""})
    known, out = set(), []
    for name in tuple(SEED_CATEGORIES) + tuple(used):
        if _norm(name) and _norm(name) not in known:
            known.add(_norm(name))
            out.append(name)
    return tuple(out)


def shareable_categories(names) -> tuple:
    """Filter a vault's category vocabulary through the shareability boundary.

    The result supplies offered model choices. Local reply validation and
    settled-category matching retain the complete vocabulary."""
    return tuple(name for name in names if is_shareable(name))


def settled_category(proj, named: str) -> str:
    """Return the vocabulary spelling matching a label under _norm.

    Unmatched labels return stripped; an empty label returns empty."""
    want = _norm(named)
    if not want:
        return ""
    for known in category_vocabulary(proj):
        if _norm(known) == want:
            return known
    return named.strip()


def ruling_slots(categories=()) -> tuple:
    """Return ruling slots with local category validation and shareable offered labels.

    ``categories`` is the full vocabulary. Labels outside it remain valid label
    inputs and are normalized by ``settled_category``."""
    return RULING_SLOTS + (Slot(name="category", type=ANSWER_LABEL,
                                choices=tuple(categories),
                                offered=shareable_categories(categories)),)


# --------------------------------------------------------------------- step 3


@dataclass
class Interpretation:
    """A ruling's slots, filled and checked — meaning only, never money."""
    legs: list[dict] = field(default_factory=list)   # {major, account_hint, share}
    future_scope: str = "context"
    starts: str = ""
    ends: str = ""
    recurrence: str = ""
    kind: str = ""                 # vehicle | property | mortgage | loan | ...
    # Retain the submitted product-kind label alongside the major.
    category: str = ""
    said: str = ""                 # the person's own words, kept
    # Distinguish transport, parse and empty-response outcomes.
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
    """Return known categorical context for the movement's source instrument.

    An unreadable source is represented as unknown."""
    return (("counterparty", descriptor or "(unknown)"),
            ("source", source or "(an account they hold)"),
            ("category", category or "(unknown)"),
            ("subcategory", subcategory or "(unknown)"))


def ruling_from(reply, said: str = "") -> Interpretation:
    """Convert a checked reply into the interpretation used by proposal resolution.

    Only values surviving deterministic slot validation are copied."""
    legs = [{"major": leg["major"],
             "account_hint": leg.get("account_hint", ""),
             "share": leg.get("share", "")}
            for leg in reply.values.get("legs", [])]
    _ground_stated_shares(legs, said)
    return Interpretation(
        legs=legs, kind=reply.value("kind").lower(),
        future_scope=reply.value("future_scope") or "context",
        starts=reply.value("starts"), ends=reply.value("ends"),
        recurrence=reply.value("recurrence"),
        category=reply.value("category").lower()[:40], said=said,
        failure="" if legs else "empty",
        detail="" if legs else "no usable legs",
        version=reply.version)


def _ground_stated_shares(legs: list[dict], said: str) -> None:
    """Retain allocations explicitly stated as percentages in the submitted words.

    Repeated equal allocations require repeated explicit percentages. Unstated
    shares, balances and proportions derived from other values are not supplied."""
    import re
    from collections import Counter
    from decimal import InvalidOperation

    # Consume complete numeric expressions, including unsupported punctuation
    # and spaced signs, so a rejected token cannot leave a valid-looking tail.
    tokens = re.findall(
        r"(?<![\w.,/*+\-−\d])((?:[+\-−]\s*)*\d[\d.,/*]*(?:\s*[/,*]\s*\d[\d.,/*]*)?)\s*(?:%|percent\b)",
        said, flags=re.IGNORECASE)
    written = Counter()
    for token in tokens:
        token = token.strip()
        if re.fullmatch(r"\+?\s*\d+(?:\.\d+)?", token):
            value = Decimal(re.sub(r"\s+", "", token)) / 100
            if 0 <= value <= 1:
                written[value] += 1
    try:
        proposed = Counter(Decimal(str(leg["share"])) for leg in legs
                           if leg.get("share") not in (None, ""))
        grounded = all(value.is_finite() and 0 <= value <= 1
                       and count <= written[value]
                       for value, count in proposed.items())
    except (InvalidOperation, ValueError):
        grounded = False
    if not grounded:
        for leg in legs:
            leg["share"] = ""


# --------------------------------------------------------------------- step 4


@dataclass
class AccountMatch:
    """How an account hint resolves — the same verdicts the statement matcher
    uses: `same`, `existing`, `ambiguous`, `new`."""
    account: str
    verdict: str               # "same" | "existing" | "ambiguous" | "new"
    candidate: str = ""
    reason: str = ""
    # Retain the person-facing name separately from the issued account key.
    name: str = ""


def resolve_account(proj, major: str, hint: str, group: str = "") -> AccountMatch:
    """Resolve a leg's normalized name to a local account or an identity verdict.

    One exact candidate returns ``same``. Multiple exact or substring candidates
    return ``ambiguous``; no match returns ``new`` with a proposed path. Empty
    asset/liability names return ``unnamed`` rather than a holding path."""
    # Empty expense/income hints resolve to existing Uncategorized buckets.
    if major in (MAJOR_EXPENSE, MAJOR_INCOME) and not hint.strip():
        return AccountMatch(MAJOR_UNCATEGORIZED[major], "existing",
                            reason="ordinary spending needs no account of its own")
    # Empty asset/liability hints return the unnamed-identity verdict.
    if not hint.strip():
        return AccountMatch("", "unnamed",
                            reason="you now own or owe something, and it has no name yet")
    want = _norm(hint)
    candidates = _candidates(proj, major)
    # Multiple matching accounts return ambiguous identity.
    exact = [(name, account) for name, account in candidates
             if want and _norm(name) == want]
    # Deduplicate name matches by account before checking uniqueness.
    if len({account for _, account in exact}) == 1:
        return AccountMatch(exact[0][1], "same",
                            reason="an account you already have")
    if exact:
        name, account = exact[0]
        return AccountMatch(account, "ambiguous", candidate=account, name=name,
                            reason=f"more than one of your accounts is called "
                                   f"{name}")
    for name, account in candidates:
        known = _norm(name)
        if want and known and (want in known or known in want):
            return AccountMatch(account, "ambiguous", candidate=account,
                                reason=f"looks like your existing {name}",
                                name=name)
    proposed = account_path(major, group or _FALLBACK_GROUP, hint.strip())
    return AccountMatch(proposed, "new", reason="nothing like this exists yet")


def _norm(text: str) -> str:
    return " ".join((text or "").lower().replace("-", " ").split())


# Eligible issued-account kinds for each holding major.
_ISSUED_KINDS = {
    MAJOR_ASSET: ("depository", "investment"),
    MAJOR_LIABILITY: ("liability",),
}


def _candidates(proj, major: str) -> list:
    """Return sorted (name, account) pairs eligible for an interpretation major.

    Ruled paths use their final name segment. Issued accounts use their statement
    name and must have a kind listed under that major in ``_ISSUED_KINDS``."""
    pairs = {(account.split(":")[-1], account)
             for account in set(proj.ruled_accounts())
             | {a for a in proj.accounts()
                if a.split(":")[0] == MAJOR_ROOTS.get(major)}}
    if major in (MAJOR_EXPENSE, MAJOR_INCOME):
        pairs |= {(leg["account"].rsplit(":", 1)[-1], leg["account"])
                  for ruling in proj.rulings() for leg in ruling.get("legs", ())}
        pairs = {(name, account) for name, account in pairs
                 if account.split(":")[0] == MAJOR_ROOTS[major]}
    for info in proj.account_infos():
        if info.kind not in _ISSUED_KINDS.get(major, ()):
            continue
        pairs |= {(name, info.account) for name in _account_aliases(info) if name}
    return sorted(pairs)


def _account_aliases(info) -> set[str]:
    """The names an account record already answers to."""
    aliases = {info.name, info.institution}
    if info.institution:
        product = "brokerage" if info.kind == "investment" else info.kind
        aliases |= {f"{info.institution} {product}",
                    f"{info.institution} {product} account"}
    return aliases


def _source_aliases(proj, selected: set[str], held_movements) -> set[str] | None:
    """Resolve every selected movement locally before trusting component names."""
    found = {m.key: m.account for m in held_movements if m.key in selected}
    if not selected or set(found) != selected:
        return None
    infos = {info.account: info for info in proj.account_infos()}
    if not set(found.values()) <= infos.keys():
        return None
    aliases = set()
    for account in set(found.values()):
        aliases |= _account_aliases(infos[account]) | {account, account.rsplit(":", 1)[-1]}
    return {_norm(name) for name in aliases if _norm(name)}


# --------------------------------------------------------------------- step 5


@dataclass
class Proposal:
    """An unapplied accounting intent with resolved legs, scope and uncertainty.

    ``apply_proposal`` performs its writes; constructing a proposal writes nothing."""
    scope: str
    subject: str
    legs: list[dict] = field(default_factory=list)
    new_accounts: list[str] = field(default_factory=list)
    confirm_accounts: list[str] = field(default_factory=list)
    # Display names aligned with confirm_accounts; empty entries use path tails.
    confirm_names: list[str] = field(default_factory=list)
    # Unnamed legs prevent proposal application.
    needs_name: list[str] = field(default_factory=list)
    # Supplied account-attribute value at attribute scope.
    value: str = ""
    # Additional supplied attributes, including a secured-account link.
    attributes: list[dict] = field(default_factory=list)
    corroborates: str = ""
    category: str = ""             # what the person called it, if they said
    said: str = ""
    unknown_split: bool = False
    # Keep selected and additional movements, payment directions and currencies separate.
    settles: int = 1
    also_settles: int = 0
    also_totals: tuple = ()        # ((currency, total), ...) paid to them
    also_back: int = 0
    also_back_totals: tuple = ()   # ((currency, total), ...) come back
    amount: str = ""
    currency: str = ""
    prompt_version: str = ""       # which instructions read the sentence
    # Figure renderer used by the proposal summary.
    locale: str = ""

    @property
    def applicable(self) -> bool:
        """Return false while any proposed holding lacks its required name."""
        return not self.needs_name

    def _totals(self, totals) -> str:
        """Render separate currency subtotals from ((currency, amount), ...) pairs.

        Empty totals render zero in the proposal's currency. No currency conversion
        or cross-currency addition is performed."""
        written = [str(render_money(amount, currency, locale=self.locale))
                   for currency, amount in totals]
        if len(written) < 2:
            return written[0] if written else str(
                render_money("0", self.currency, locale=self.locale))
        return ", ".join(written[:-1]) + " and " + written[-1]

    def _reads_as(self) -> str:
        """The accounts awaiting confirmation, as the person reads them: the
        name carried with each where there is one, and the path's own last
        segment otherwise."""
        names = list(self.confirm_names) + [""] * len(self.confirm_accounts)
        return str(render_accounts(
            {"name": name} if name else {"path": path}
            for path, name in zip(self.confirm_accounts, names)))

    @staticmethod
    def _named(paths) -> str:
        """Accounts as a person reads them. A ledger path is how the machine
        files a thing; the name in it is what the person called it, and that is
        what the renderer shows."""
        return str(render_accounts({"path": p} for p in paths))

    def summary(self) -> str:
        """Render treatment, proposed accounts, category and allocation uncertainty."""
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
        # Each meaning is named once, however many legs carry it: one payment
        # can be two of the same thing — two expenses, on two accounts.
        what = ", ".join(dict.fromkeys(IN_A_SENTENCE[leg["major"]]
                                       for leg in self.legs))
        head = str(render_money(self.amount or "0", self.currency,
                                locale=self.locale))
        if self.settles > 1:
            head += f" across {self.settles} payments"
        parts = [f"I'd record {head} as: {what}."]
        if self.also_settles:
            parts.append(ALSO_SETTLES.format(
                count=self.also_settles, money=self._totals(self.also_totals)))
        if self.also_back:
            parts.append(ALSO_CAME_BACK.format(
                count=self.also_back, money=self._totals(self.also_back_totals)))
        if self.new_accounts:
            parts.append("This creates " + self._named(self.new_accounts)
                         + " — new, and only you say it exists.")
        for leg in self.legs:
            major = leg["major"]
            if major not in (MAJOR_EXPENSE, MAJOR_INCOME):
                continue
            treatment = "spending" if major == MAJOR_EXPENSE else "income"
            if leg["account"] == MAJOR_UNCATEGORIZED[major]:
                parts.append(f"I'll use ordinary {treatment} with no separate named component.")
            else:
                name = self._named([leg["account"]])
                parts.append(f"I'll record {name} as a {treatment} component.")
        # Guessed existing accounts are named explicitly for confirmation.
        if self.confirm_accounts:
            parts.append("I've taken this to be your existing "
                         + self._reads_as()
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
                "confirm_names": self.confirm_names,
                "needs_name": self.needs_name, "value": self.value,
                "attributes": self.attributes,
                "corroborates": self.corroborates, "category": self.category,
                "said": self.said,
                "unknown_split": self.unknown_split, "settles": self.settles,
                "also_settles": self.also_settles,
                "also_totals": [list(pair) for pair in self.also_totals],
                "also_back": self.also_back,
                "also_back_totals": [list(pair)
                                     for pair in self.also_back_totals],
                "amount": self.amount, "currency": self.currency,
                "prompt_version": self.prompt_version, "locale": self.locale,
                "summary": self.summary()}


def movements_answered_about(proj, merchant: str) -> list:
    """Derive unsettled expense-shaped movements under a counterparty.

    Question-backed callers supply their existing selection instead. Stronger
    links, held accounts and existing rulings exclude movements from this result."""
    return [m for m in proj.movements()
            if merchant in proj.merchant_keys_of(m)
            and proj._is_expense(m)
            and m.nature_reason in (BY_CATEGORY, BY_DEFAULT)]


def _by_currency(movements) -> tuple:
    """The magnitude of these movements, as ``((currency, total), ...)`` sorted
    by currency.

    One subtotal per currency: nothing converts here, so a set spanning two of
    them has no single total any document attests."""
    totals: dict[str, Decimal] = {}
    for m in movements:
        totals[m.currency] = totals.get(m.currency, Decimal("0")) + abs(m.amount)
    return tuple((currency, str(total)) for currency, total in sorted(totals.items()))


def movements_also_settled(proj, merchant: str, asked: set) -> list:
    """Return additional unruled movements reached by a merchant-scoped ruling.

    The result includes both payment directions. Live transfer links and existing
    rulings retain precedence and are excluded."""
    return [m for m in proj.movements()
            if merchant in proj.merchant_keys_of(m)
            and m.key not in asked
            and not m.linked
            and m.nature_reason != BY_RULING]


class MovementSelectionRequired(ValueError):
    """A target lacks identity authority and needs an explicit movement."""


def propose(proj, interp: Interpretation, descriptor: str, amount: str = "",
            currency: str = "", movement_key: str = "", locale: str = "",
            merchant_key: str = "", movements=(),
            ordinary_counterpart: bool = False) -> Proposal:
    """Resolve a checked interpretation into a concrete proposal without writing.

    Commercial merchant scope covers its eligible payments; peer or instrument
    scope covers a movement. A missing movement key with multiple descriptor
    matches raises MovementSelectionRequired. ``merchant_key`` and ``movements``
    retain the caller's identity and selected population; absent values are
    derived locally. Checked ``ordinary_counterpart`` context resolves a generic
    leg on the dedicated correction path. Other callers use account resolution."""
    from merchantcore.resolve import resolve_descriptor

    if ordinary_counterpart and (len(interp.legs) != 1
            or interp.legs[0].get("account_hint", "") != ""
            or interp.legs[0].get("share", "") != ""):
        raise ValueError("ordinary counterpart requires one unnamed, unallocated leg")
    held_movements = proj.movements()
    described = [m for m in held_movements if m.description == descriptor]
    if not described and movement_key:
        described = [m for m in held_movements if m.key == movement_key]
    insufficient = (any(not proj.merchant_key_of(m) for m in described) if described
                    else resolve_descriptor(descriptor).identity_insufficient)
    if insufficient and not movement_key:
        raise MovementSelectionRequired(f"{descriptor!r} needs a specific transaction: "
                         "its description does not establish a counterparty")
    merchant = "" if insufficient else merchant_key or normalize_merchant(descriptor)
    # Enrichment counterparty_kind keeps instrument descriptors movement-scoped.
    matches = (described if insufficient else
               [m for m in held_movements if merchant in proj.merchant_keys_of(m)])
    evidence = [decide(m.description, proj.counterparty_kind(m)) for m in matches]
    decision = (group_decision(evidence) if evidence else
                decide(descriptor, proj.kind_of_merchant(merchant)))
    generalizes = bool(merchant) and decision.generalizes
    scope = SCOPE_MERCHANT if generalizes and not movement_key else SCOPE_MOVEMENT
    subject = merchant if scope == SCOPE_MERCHANT else movement_key
    if scope == SCOPE_MOVEMENT and not subject:
        # Refuse descriptor-wide conduit-bucket settlement.
        if len(matches) != 1:
            raise ValueError(
                f"{descriptor!r} needs a specific transaction: it covers "
                f"{len(matches)} movements that may each mean something different")
        subject = matches[0].key

    selected = {str(key) for key in movements}
    if movement_key:
        selected.add(movement_key)
    elif not selected:
        selected = ({subject} if scope == SCOPE_MOVEMENT else
                    {m.key for m in movements_answered_about(proj, merchant)})
    source_aliases = _source_aliases(proj, selected, held_movements)
    if (source_aliases is None and interp.compound
            and any(leg["major"] in (MAJOR_EXPENSE, MAJOR_INCOME)
                    and leg.get("account_hint", "").strip() for leg in interp.legs)):
        raise MovementSelectionRequired("named components need complete source context")

    legs, new_accounts, confirm, unnamed = [], [], [], []
    confirm_names: list = []
    implied = proj.implication_for(merchant) if merchant else None
    # Explicit merchant keys use the fallback account group for new accounts.
    group = "" if merchant_key else (implied or {}).get("account_group", "")
    for leg in interp.legs:
        hint = leg.get("account_hint", "")
        component = leg["major"] in (MAJOR_EXPENSE, MAJOR_INCOME)
        if component and (source_aliases is None or _norm(hint) in source_aliases):
            hint = ""
        match = (AccountMatch(account=MAJOR_UNCATEGORIZED[leg["major"]], verdict="same")
                 if ordinary_counterpart else
                 resolve_account(proj, leg["major"], hint, group=group))
        legs.append({"major": leg["major"], "account": match.account,
                     "share": leg.get("share", "")})
        if match.verdict == "new" and not component:
            new_accounts.append(match.account)
        elif match.verdict == "ambiguous":
            # Store the resolved path and display the retained account name.
            confirm.append(match.candidate)
            confirm_names.append(match.name)
        elif match.verdict == "unnamed":
            unnamed.append(leg["major"])

    settles, paid, back = 1, [], []
    if scope == SCOPE_MERCHANT:
        asked = ({str(key) for key in movements} if movements
                 else {m.key for m in movements_answered_about(proj, merchant)})
        rest = movements_also_settled(proj, merchant, asked)
        settles = len(asked)
        # Compute payment/refund direction with account-kind-aware money_effect.
        paid = [m for m in rest if money_effect(m) < 0]
        back = [m for m in rest if money_effect(m) > 0]
    return Proposal(
        scope=scope, subject=subject, legs=legs, new_accounts=new_accounts,
        confirm_accounts=confirm, confirm_names=confirm_names,
        needs_name=unnamed,
        # Corroborating document kinds come from enrichment implications.
        corroborates=(implied or {}).get("documents", ""),
        category=settled_category(proj, interp.category), said=interp.said,
        unknown_split=interp.compound and not interp.shares_known,
        settles=max(settles, 1),
        also_settles=len(paid), also_totals=_by_currency(paid),
        also_back=len(back), also_back_totals=_by_currency(back),
        amount=amount, currency=currency,
        prompt_version=interp.version, locale=locale)


def one_shot_extractor(spec):
    """Return an interpretation extractor with continuation disabled.

    Token-limit truncation is reported with ``TRUNCATED_MARK`` rather than joined
    with a subsequent response."""
    from vivacore.models import adapter_for

    adapter = adapter_for(replace(spec, max_continuations=0))
    exchanges = []

    def _extract(prompt: str) -> str:
        result = adapter.extract([], prompt)
        exchanges.append({"prompt": prompt, "result": result})
        if result.finish_reason == "length":
            # Preserve truncation as too_long, separately from parse failure.
            log.warning("interpret: the model ran past its limit (%d output tokens) "
                        "— refusing to stitch a bounded answer back together",
                        result.output_tokens)
            return TRUNCATED_MARK + (result.text or "")
        return result.text

    # Retain checked exchanges and model configuration as extractor metadata.
    _extract.exchanges = exchanges
    _extract.spec = spec
    return _extract


# --------------------------------------------------------------------- step 6


class InvalidAccountRegistration(ValueError):
    """A proposed registration does not name a value-holding relationship."""


def apply_proposal(ledger, proposal: Proposal, occurred_at: str,
                   by: str = "human") -> dict:
    """Append the resolved proposal's ruling and any named asserted accounts.

    Return scope, subject, opened accounts, affected movement count and category.
    An unnamed leg is refused before application."""
    if not proposal.applicable:
        raise ValueError("this proposal has something with no name yet — ask "
                         "what it is before writing anything")
    grade = VERIFIED if by == "human" else UNVERIFIED
    opened = []
    for account in proposal.new_accounts:
        # Require root, group and name segments for a holding-account path.
        if not isinstance(account, str):
            raise InvalidAccountRegistration("an account path must be text")
        parts = account.split(":")
        if (len(parts) < 3 or not all(p.strip() for p in parts)
                or not any(ch.isalnum() for ch in parts[-1])):
            raise InvalidAccountRegistration(f"{account!r} names nothing — an account needs a "
                             "name the person gave it")
        if parts[0] not in ("Assets", "Liabilities"):
            raise InvalidAccountRegistration(
                f"{account!r} does not name an asset or liability relationship")
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
        # Open the account with the explicit currency, separately from its name.
        value=proposal.value, currency="",
        prompt_version=proposal.prompt_version))
    # Record additional supplied attributes and secured-account links.
    if proposal.attributes:
        account = proposal.subject.rpartition(":")[0]
        for attr in proposal.attributes:
            ledger.append(ruling_recorded(
                SCOPE_ATTRIBUTE, f"{account}:{attr['key']}", occurred_at,
                by=by, grade=grade, said=attr.get("said", ""),
                value=attr.get("value", ""), currency=attr.get("currency", "")))
    # Append major and product-kind rulings at the proposal's scope.
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
    read = read_answer(said, ruling_slots(category_vocabulary(proj)),
                       asked=asked,
                       context=ruling_context(descriptor, category,
                                              subcategory, source),
                       extract_fn=extract_fn)
    interp = ruling_from(read, said)
    if not interp.legs:
        return None
    return propose(proj, interp, descriptor, amount, currency, movement_key,
                   locale=locale)
