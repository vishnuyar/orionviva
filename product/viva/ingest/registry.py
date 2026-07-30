"""The doc-type registry — a statement type as a data row.

    classify → look up the profile → extract → run the profile's identity → post

A profile binds a classified ``doc_type`` to what the pipeline needs:

  - ``account_kind`` — this system's interpretation of the account
    (``depository`` = an asset whose balance is money held; ``liability`` = a
    card whose balance is money owed). Derived here, never asked of the model.
  - ``identity`` — which deterministic reconciliation gate certifies it. The
    balance family (checking / savings / credit card) shares one,
    ``opening + Σ(effect on balance) = closing``, since a card is a liability
    whose effect on balance inverts. Divergent families register their own.
  - ``profile_version`` — frozen, so the claims layer records which profile read
    each document and a later field addition re-reads only affected documents.

``aliases`` absorb the label variants a model may emit for one type
("credit_card", "card_statement", …), keeping the canonical ``doc_type`` clean.
Profiles carry no personal data; they are format knowledge only.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# The identities a profile can name. A divergent type registers its own; the
# balance family shares one.
BALANCE_IDENTITY = "balance"      # opening + Σ(effect on balance) = closing
PAYSTUB_IDENTITY = "paystub"      # gross − Σ(deductions) = net
BROKERAGE_IDENTITY = "brokerage"  # Σ(position market_value) + cash = total

# Identities the pipeline has a projector for. A type whose identity is not
# listed here parks instead of posting.
PROJECTABLE_IDENTITIES = frozenset({BALANCE_IDENTITY, PAYSTUB_IDENTITY,
                                    BROKERAGE_IDENTITY})

# Account kinds — this system's interpretation, not the model's.
DEPOSITORY = "depository"         # an asset; balance = money held
LIABILITY = "liability"          # a card/loan; balance = money owed
INVESTMENT = "investment"        # an asset holding cash + positions


@dataclass(frozen=True)
class DocProfile:
    """What the pipeline needs to project one classified document type.

    ``extract_base`` / ``type_fragment`` are version ids into the prompt
    library: the profile owns the prompt used to read it, composed from a shared
    base plus its own fragment. ``type_fragment`` defaults to the generic
    balance fragment, so a new balance type needs no bespoke prompt to be
    registered."""

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


# The seed registry. A new type is a row here.
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
    # A divergent profile: its own shape and its own identity. `account_kind` is
    # empty — a pay stub is an income document, not an account.
    DocProfile(
        "pay_stub", "", identity=PAYSTUB_IDENTITY,
        extract_base="paystub-base-v1", type_fragment="paystub-v1",
        aliases=frozenset({
            "paystub", "pay_slip", "payslip", "salary_slip", "earnings_statement",
            "wage_statement", "payroll_statement",
        })),
    # A divergent profile: its own shape (positions + cash) and a snapshot
    # identity (Σ market_value + cash = total). Kind INVESTMENT — an asset that
    # holds both cash and positions, distinct from a plain depository.
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
    """Add or replace a profile, indexing it under its canonical name and every
    alias. The pipeline then projects the type with no change to the gate."""
    _INDEX[profile.doc_type] = profile
    for alias in profile.aliases:
        _INDEX[alias] = profile


for _p in _SEED:
    register(_p)


def profile_for(doc_type: str) -> DocProfile | None:
    """The profile for a classified doc_type (canonical or alias), or None when
    the type is not registered — the caller parks the document."""
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
    """Which reconciliation family a held document belongs to, read from its
    stored facts; "" when the type is not registered.

    Held documents are polymorphic — a balance statement, a pay stub and a
    brokerage statement can all be held, and their facts have different shapes —
    so consumers route on this rather than assuming one shape."""
    p = profile_for((facts or {}).get("doc_type", ""))
    return p.identity if p else ""


def doc_type_for_prompt_version(version: str) -> str:
    """Recover the document type from a stored read's prompt version.

    The extract version is the composite `extract:<base>+<frag>` and a profile's
    `type_fragment` is unique to it, so a read recorded under `card-v1` was a
    credit-card statement. This lets a claim that carries an extract phase and
    no classify phase still name its type — the balance family's extract JSON
    does not name its own type.

    Matches on the fragment's family, not its version, so a read recorded under
    a superseded version still resolves. Returns "" when the version names no
    known fragment; the caller must treat that as unknown, not as a default."""
    if not version or not version.startswith("extract:"):
        return ""
    fragment = version[len("extract:"):].split("+", 1)[-1]

    def _family(frag: str) -> str:
        """A fragment's family: `brokerage-v2` -> `brokerage`.

        A family belongs to exactly one profile — `card`, `checking`,
        `savings`, `paystub`, `brokerage` — so the mapping stays unambiguous as
        versions move. A fragment with no `-v<digits>` suffix is its own
        family."""
        stem = frag.rsplit("-v", 1)
        return stem[0] if len(stem) == 2 and stem[1].isdigit() else frag

    want = _family(fragment)
    for profile in set(_INDEX.values()):
        if _family(profile.type_fragment) == want:
            return profile.doc_type
    return ""


def extraction_prompt_for(doc_type: str) -> tuple[str, str] | None:
    """Compose the extraction prompt (text, version) a classified type's profile
    owns, or None if there is no projector for it yet. The version is the
    self-describing ``extract:<base>+<fragment>`` composite."""
    from .prompt_library import compose_extraction
    p = profile_for(doc_type)
    if p is None:
        return None
    return compose_extraction(p.extract_base, p.type_fragment)
