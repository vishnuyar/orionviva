"""What a magnitude measures, as a closed vocabulary.

A number's shape and a number's meaning are two different declarations. The
slot types in `render.py` say what SHAPE a thing takes — an amount with a
currency, a whole number of things, a proportion. This module says what the
number is OF. Both are needed, because a real figure put into a hole that
claims it means something else is a false sentence built entirely out of true
parts: the amount is right, its records are right, its grade is right, and the
sentence is a lie about what was measured.

So the tool that emits a figure declares what it measured, a hole that wants a
magnitude declares what it is asking for, and code compares the two. Neither
declaration is a judgement about the other; both are members of the list below.

The list is closed and it grows by editing it here. No member may mean
"whatever fits": a hole asking for a magnitude asks for one of these names, and
a figure declaring none of them can fill no hole.

Every name here is permanent. A figure records the kind it declared, so the
word outlives whatever code chose it.
"""

from __future__ import annotations

from decimal import Decimal

# Money that left the person's hands to somebody else, counted the way the
# spending aggregate counts it: own-account transfers and settlements are not
# in it, and a card purchase is.
SPENDING = "spending"

# Money attributed as coming in. Not every inflow — only what something has
# attributed to a source of income.
INCOME = "income"

# What is held or owed at a moment: an account's balance, a holding's measured
# value, one line of a net-worth point. A stock, never a flow.
BALANCE = "balance"

# What is held less what is owed, at a moment, across everything in scope.
NET_WORTH = "net_worth"

# The sum of postings over a set of movements before anything is netted off,
# each taken in the direction its account gives it. It says which way the money
# went for the set as a whole, and nothing about any one movement in it.
GROSS_FLOW = "gross_flow"

# What a set of movements came to once the postings are netted against each
# other. Still not spending: a settlement and a transfer are in it.
NET_MOVEMENT = "net_movement"

# One movement, signed by which way the money went — negative out, positive in
# — read off the kind of account it sits on rather than off the posting's own
# sign. A single card settlement is one of these, and so is a single purchase.
MOVEMENT = "movement"

# A number of things — accounts, documents, movements, months, counterparties.
# Never an amount of money.
COUNT = "count"

# One quantity divided by another: a share, a proportion, a multiple. Carried
# as the quotient itself, so one half is `0.5`.
RATIO = "ratio"

# A point in time — a day, a month, a year. Not a magnitude of anything: it
# adds to nothing and scales by nothing, and a hole that wants an amount can
# never be filled by one.
TIME = "time"

# The scale between a proportion as it is carried and a proportion as it is
# written and typed. Not a kind. `render.rate` multiplies by it and the reader
# of a typed proportion in `reply` divides by it; nothing else applies it.
PER_HUNDRED = Decimal(100)


def ratio_of(kind: str) -> str:
    """The name for a proportion of one particular kind of thing, as
    ``ratio_of_<kind>``.

    Bare ``RATIO`` is the name for a comparison of two unlike kinds, where no
    single kind is true of the result."""
    return f"{RATIO}_of_{kind}"


# What may be compared with something of its own kind. `TIME` is not among
# them: it measures no magnitude, so nothing is a proportion of it.
COMPARABLE = (SPENDING, INCOME, BALANCE, NET_WORTH, GROSS_FLOW, NET_MOVEMENT,
              MOVEMENT, COUNT)

RATIOS = tuple(ratio_of(kind) for kind in COMPARABLE)

KINDS = (SPENDING, INCOME, BALANCE, NET_WORTH, GROSS_FLOW, NET_MOVEMENT,
         MOVEMENT, COUNT, RATIO, TIME) + RATIOS


def is_ratio(name: str) -> bool:
    """Whether a name is a proportion, of anything or of nothing named."""
    return name == RATIO or name in RATIOS


# What is held at a moment, and what passed through over a stretch. The
# distinction decides what putting two quantities together comes to: a flow
# taken out of a stock is still that stock — what is held, less what was spent,
# is what is left — and that one arrangement is the whole of the rule. A flow
# added to a stock, a stock taken out of a flow, two different flows and two
# different stocks all come to a quantity with no name here, and are refused.
STOCKS = (BALANCE, NET_WORTH)
FLOWS = (SPENDING, INCOME, GROSS_FLOW, NET_MOVEMENT, MOVEMENT)

# What a figure says when nothing has established what it measures — the result
# of arithmetic over a magnitude nobody attributed, and nothing else. It is not
# a kind: no hole may ask for it, so a figure carrying it can fill no hole at
# all.
UNMEASURED = "unmeasured"

# What a figure may declare, which is one more than what a hole may ask for.
MEASURES = KINDS + (UNMEASURED,)
