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

# The identities a profile can name. v0 has exactly one; the point of naming it
# is that a divergent type (brokerage: positions×price + cash = total) registers
# its own without the balance family knowing.
BALANCE_IDENTITY = "balance"      # opening + Σ(effect on balance) = closing

# Account kinds — our interpretation, not the model's.
DEPOSITORY = "depository"         # an asset; balance = money held
LIABILITY = "liability"          # a card/loan; balance = money owed


@dataclass(frozen=True)
class DocProfile:
    """What the pipeline needs to project one classified document type. Data."""

    doc_type: str                 # canonical type (e.g. 'credit_card_statement')
    account_kind: str             # DEPOSITORY | LIABILITY
    identity: str = BALANCE_IDENTITY
    profile_version: str = "bal-v1"
    aliases: frozenset[str] = field(default_factory=frozenset)

    @property
    def is_liability(self) -> bool:
        return self.account_kind == LIABILITY


# The seed registry. Every row is the whole balance family — one shared identity,
# distinguished only by kind. Adding a fourth balance-shaped type is a row here.
_SEED: tuple[DocProfile, ...] = (
    DocProfile(
        "checking_statement", DEPOSITORY,
        aliases=frozenset({
            "checking", "bank_statement", "combined_bank_statement",
            "checking_account_statement", "bank_account_statement",
        })),
    DocProfile(
        "savings_statement", DEPOSITORY,
        aliases=frozenset({
            "savings", "savings_account_statement", "money_market_statement",
        })),
    DocProfile(
        "credit_card_statement", LIABILITY,
        aliases=frozenset({
            "credit_card", "card_statement", "creditcard_statement",
            "credit_card_account_statement",
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
    """True when a balance-identity projector can handle this type."""
    p = profile_for(doc_type)
    return p is not None and p.identity == BALANCE_IDENTITY
