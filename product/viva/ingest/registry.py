"""The doc-type registry — how a new statement type becomes DATA, not code.

v0 hardcoded a single projector (checking). To hold a whole financial life the
product must read many statement types, and adding one must be a *registry row*,
not a code change. This module is that registry and the claim the Slice 2
architecture rests on (docs/doc-type-registry-and-format-profiles.md).

The shape:

    classify → look up the profile → extract → run the profile's identity → post

A **profile** binds a classified ``doc_type`` to the three things the pipeline
needs and nothing more:

  - ``account_kind`` — our *interpretation* of the account (``depository`` = an
    asset whose balance is money held; ``liability`` = a card whose balance is
    money owed). Derived here, never asked of the model — we own the schema.
  - ``identity``     — which deterministic reconciliation gate certifies it. The
    whole balance family (checking / savings / credit card) shares ONE identity,
    ``opening + Σ(effect on balance) = closing``, because a card is just a
    liability whose "effect on balance" inverts (a charge raises what's owed).
    Divergent families (brokerage, pay stub) will register their own identity.
  - ``profile_version`` — a frozen version, so the claims layer can record which
    profile read each document and a later field addition triggers a *surgical*
    re-read of only the affected docs (the raw-capture payoff), never a rewrite.

``aliases`` absorb the label variants a model may emit for the same type
("credit_card", "card_statement", …) so classification stays forgiving while the
canonical ``doc_type`` stays clean. Profiles carry NO personal data — they are
format knowledge, which is what makes a shared format-commons possible later
without touching the local-first personal core.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# The identities a profile can name. The point of naming them is that a divergent
# type registers its own without the others knowing. The balance family shares
# one; a pay stub is the first that doesn't (Slice 4). Brokerage
# (positions×price + cash = total), 1099 (box sums) join later, each as data.
BALANCE_IDENTITY = "balance"      # opening + Σ(effect on balance) = closing
PAYSTUB_IDENTITY = "paystub"      # gross − Σ(deductions) = net
BROKERAGE_IDENTITY = "brokerage"  # Σ(position market_value) + cash = total

# Identities the pipeline has a projector for. Adding a projector is what turns a
# parked type into a posted one — a registry concern, not a routing rewrite.
PROJECTABLE_IDENTITIES = frozenset({BALANCE_IDENTITY, PAYSTUB_IDENTITY,
                                    BROKERAGE_IDENTITY})

# Account kinds — our interpretation, not the model's.
DEPOSITORY = "depository"         # an asset; balance = money held
LIABILITY = "liability"          # a card/loan; balance = money owed
INVESTMENT = "investment"        # an asset holding cash + positions (Slice 6)


@dataclass(frozen=True)
class DocProfile:
    """What the pipeline needs to project one classified document type. Data.

    ``extract_base`` / ``type_fragment`` are version ids into the prompt library:
    the profile *owns* the prompt used to read it (composed from a shared base +
    its own fragment), which is what makes a profile self-contained enough to
    version and, later, share. ``type_fragment`` defaults to the generic balance
    fragment, so registering a new balance type stays a data-only row even before
    it authors bespoke guidance."""

    doc_type: str                 # canonical type (e.g. 'credit_card_statement')
    account_kind: str             # DEPOSITORY | LIABILITY
    identity: str = BALANCE_IDENTITY
    profile_version: str = "bal-v1"
    aliases: frozenset[str] = field(default_factory=frozenset)
    extract_base: str = "base-v1"
    type_fragment: str = "balance-generic-v1"

    @property
    def is_liability(self) -> bool:
        return self.account_kind == LIABILITY


# The seed registry. Every row is the whole balance family — one shared identity,
# distinguished only by kind. Adding a fourth balance-shaped type is a row here.
_SEED: tuple[DocProfile, ...] = (
    DocProfile(
        "checking_statement", DEPOSITORY, type_fragment="checking-v1",
        aliases=frozenset({
            "checking", "bank_statement", "combined_bank_statement",
            "checking_account_statement", "bank_account_statement",
        })),
    DocProfile(
        "savings_statement", DEPOSITORY, type_fragment="savings-v1",
        aliases=frozenset({
            "savings", "savings_account_statement", "money_market_statement",
        })),
    DocProfile(
        "credit_card_statement", LIABILITY, type_fragment="card-v1",
        aliases=frozenset({
            "credit_card", "card_statement", "creditcard_statement",
            "credit_card_account_statement",
        })),
    # The first DIVERGENT profile: a different shape AND a different identity, as
    # data. `account_kind` is empty — a pay stub is an income document, not an
    # account. (Slice 4.)
    DocProfile(
        "pay_stub", "", identity=PAYSTUB_IDENTITY,
        extract_base="paystub-base-v1", type_fragment="paystub-v1",
        aliases=frozenset({
            "paystub", "pay_slip", "payslip", "salary_slip", "earnings_statement",
            "wage_statement", "payroll_statement",
        })),
    # The second DIVERGENT profile (Slice 6): its own shape (positions + cash) and
    # a snapshot identity (Σ market_value + cash = total). Kind INVESTMENT — an
    # asset that holds cash AND positions, distinct from a plain depository.
    DocProfile(
        "brokerage_statement", INVESTMENT, identity=BROKERAGE_IDENTITY,
        profile_version="brk-v2", extract_base="brokerage-base-v2",
        type_fragment="brokerage-v2",
        aliases=frozenset({
            "brokerage", "brokerage_account_statement", "investment_statement",
            "investment_account_statement", "retirement_statement",
            "retirement_account_statement", "ira_statement", "401k_statement",
        })),
)

# Flat index: canonical name and every alias resolve to the same profile.
_INDEX: dict[str, DocProfile] = {}


def register(profile: DocProfile) -> None:
    """Add (or replace) a profile. This is the seam that makes a new type *data*:
    a test — or a later data-driven loader / the format-commons — calls this, and
    the pipeline projects the type with no change to the reconciliation gate."""
    _INDEX[profile.doc_type] = profile
    for alias in profile.aliases:
        _INDEX[alias] = profile


for _p in _SEED:
    register(_p)


def profile_for(doc_type: str) -> DocProfile | None:
    """The profile for a classified doc_type (canonical or alias), or None when
    no projector exists yet — the caller parks the document honestly."""
    return _INDEX.get((doc_type or "").strip().lower())


def account_kind_for(doc_type: str) -> str:
    """The account kind for a doc_type, defaulting to depository when unknown so
    a legacy/held statement without a registered profile still opens sanely."""
    p = profile_for(doc_type)
    return p.account_kind if p else DEPOSITORY


def can_project(doc_type: str) -> bool:
    """True when the pipeline has a projector for this type's identity."""
    p = profile_for(doc_type)
    return p is not None and p.identity in PROJECTABLE_IDENTITIES


def identity_of_facts(facts: dict | None) -> str:
    """Which reconciliation family a *held* document belongs to, read from its
    stored facts.

    Held documents are polymorphic — a balance statement, a pay stub and a
    brokerage statement can all be held for review, and their facts have entirely
    different shapes. Consumers must route on this rather than assume (a real
    crash: the corroboration heal rebuilt every conflict-hold as a
    ``StatementFacts`` and died on a held brokerage statement's missing
    ``opening_amount``). The registry is the routing authority, so the answer
    lives here."""
    p = profile_for((facts or {}).get("doc_type", ""))
    return p.identity if p else ""


def doc_type_for_prompt_version(version: str) -> str:
    """Recover the document type from a stored read's PROMPT VERSION.

    The extract version is the self-describing composite `extract:<base>+<frag>`
    (T8), and a profile's `type_fragment` is unique to it — a read recorded
    under `card-v1` was, by construction, a credit-card statement. So a claim
    that has lost its classify phase can still say what it is, with certainty
    rather than inference: this reads a fact we wrote down, it does not guess.

    Why this exists (2026-07-26): a real vault held 40 documents whose claims
    carried an EXTRACT phase and no CLASSIFY phase. The balance family's extract
    JSON does not name its own type, so every one replayed as `unknown`, had no
    projector, and parked — a rebuild that produced an empty vault out of forty
    perfectly good stored reads. The type was in the vault the whole time, one
    field away, because T8 required the version to be self-describing.

    Returns "" when the version names no known fragment; the caller must treat
    that as unknown rather than as a default."""
    if not version or not version.startswith("extract:"):
        return ""
    fragment = version[len("extract:"):].split("+", 1)[-1]
    for profile in set(_INDEX.values()):
        if profile.type_fragment == fragment:
            return profile.doc_type
    return ""


def extraction_prompt_for(doc_type: str) -> tuple[str, str] | None:
    """Compose the extraction prompt (text, version) a classified type's profile
    owns, or None if there is no projector for it yet. The version is the
    self-describing ``extract:<base>+<fragment>`` composite (T8)."""
    from .prompt_library import compose_extraction
    p = profile_for(doc_type)
    if p is None:
        return None
    return compose_extraction(p.extract_base, p.type_fragment)
