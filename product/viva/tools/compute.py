"""Exact arithmetic as a tool, so no model ever adds two numbers itself.

The expression is parsed, never evaluated as Python: only +, -, *, /,
parentheses, integer literals and names are accepted, and every name must be
bound in ``inputs``.

An operand is not a number the caller typed. It is either a **figure** some
tool emitted in this run, named by its id, or a value the **person** stipulated
in this turn's question. A raw decimal refuses, and the refusal names the
figures that are available.

Provenance, grade and unit are consequences of the arithmetic, never of the
call. Every value carried through the walk is a quantity — an amount, what it
measures, the records it depends on, the weakest grade among them, whether any
part of it was supposed, and how the arithmetic came out — and each operator
combines those annotations for itself.

What a result rests on follows the shape of the operator. Multiplying or
dividing by a bare magnitude is a change of units: it rescales an attested
quantity and leaves it attested, so the result rests on every record either
operand carries and takes the weakest grade among those that carry one — a
count that is itself graded contributes its evidence rather than losing it.
Adding or subtracting a bare magnitude injects a quantity nothing measured, so
a total is attested only when every term is: one term standing on no record
leaves the whole standing on none, with no grade either, and a claim about
money that stands on nothing cannot be said at all.

How the arithmetic came out is a separate question with no bearing on that one.
A quotient that does not terminate is returned rather than refused, marked as
rounded, and whatever speaks it is answerable for saying so; its grade and its
records are untouched. The working precision is far wider than the scale the
value is finally written at, so the rounding happens once at the end rather
than compounding through the walk.

What a quantity measures is money in one currency, or a dimensionless scalar —
a count, a ratio, or a literal. Money adds to money and scales by a scalar;
two amounts of money divide into a ratio and cannot be multiplied; a scalar and
an amount cannot be added at all. A value the person supposed is money whose
currency nothing has stated, and it taints everything it reaches.

Three things the arithmetic refuses: combining unlike quantities, adding across
currencies since nothing here converts between them, and mixing a claim about
the person's money with a claim about the agent's own behaviour. A currency
clash is a property of the expression rather than of the call — binding a
figure the expression never names decides nothing about it.
"""

from __future__ import annotations

import ast
import decimal
import operator
import re
from dataclasses import dataclass, field, replace
from decimal import (Decimal, DecimalException, DivisionByZero, Inexact,
                     InvalidOperation)

from .envelope import (ACTIVITY, COMPUTED, EXACT, HYPOTHETICAL, ROUNDED,
                       ToolResult, figure, refusal, weakest)

# Each nesting level of the expression costs one Python frame in the walk.
# Deeper than this refuses as `bad_expression`.
MAX_DEPTH = 100

# The length is checked before `ast.parse` runs, because the parser recurses
# before this module's own walk begins.
MAX_EXPRESSION = 2000

# Enough significant digits that adding, subtracting and multiplying money is
# always exact, and wide enough that a division carried on through further
# operators loses nothing a final rounding would not have lost anyway.
PRECISION = 400

# The scale a money value that does not come out exactly is finally written at.
MONEY_SCALE = Decimal("0.01")

# How many significant figures a dimensionless value that does not come out
# exactly is finally written to.
SIGNIFICANT_FIGURES = 6

COMPUTE_PARAMS = {
    "type": "object",
    "properties": {
        "expression": {"type": "string"},
        "inputs": {"type": "object"},
    },
    "required": ["expression", "inputs"],
}

TOOL = "compute"

STIPULATED = "stipulated"

# What a quantity measures. "" is dimensionless — a count, a ratio, a literal.
# Anything else is money in that currency, and UNSTATED is money whose currency
# nothing named: it combines with money in any currency and claims none.
SCALAR = ""
UNSTATED = "?"

MIXED_DIMENSIONS = "mixed_dimensions"
MIXED_CURRENCIES = "mixed_currencies"


class _Refuse(Exception):
    """A refusal raised inside the walk, carrying the tag and the sentence the
    envelope will speak."""

    def __init__(self, tag: str, text: str) -> None:
        super().__init__(text)
        self.tag = tag
        self.text = text


@dataclass(frozen=True)
class _Q:
    """A value and everything true of it: what it measures, which records it
    depends on, the weakest grade among them, whether any part of it was
    supposed rather than read, and whether the arithmetic that produced it
    terminated. A literal depends on nothing and carries nothing, which is what
    makes an invented magnitude citable by no document."""

    amount: Decimal
    dimension: str = SCALAR
    records: frozenset = field(default_factory=frozenset)
    grade: str = ""
    supposed: bool = False
    exactness: str = EXACT

    @property
    def money(self) -> bool:
        return self.dimension != SCALAR

    @property
    def attested(self) -> bool:
        """Whether anything on record determined this value. Records are the
        proxy: every figure a tool emits about money stands on at least one,
        so a quantity holding none is a magnitude nothing measured."""
        return bool(self.records)


def _rescaled(left: _Q, right: _Q) -> tuple:
    """What a product or a quotient rests on. A bare magnitude here changes the
    units and takes nothing away, so the result rests on every record either
    side carries and takes the weakest grade among those that carry one."""
    return left.records | right.records, weakest([left.grade, right.grade])


def _summed(left: _Q, right: _Q) -> tuple:
    """What a total rests on: every record both sides carry at the weaker
    grade, or nothing at all when either side carries none. A term nothing
    measured injects a magnitude rather than rescaling one, so however well
    evidenced the other terms were, they answer for a different number."""
    if left.attested and right.attested:
        return left.records | right.records, weakest([left.grade, right.grade])
    return frozenset(), ""


def _carried(left: _Q, right: _Q, came_out: str = EXACT) -> tuple:
    """What travels through any operator regardless of its shape: a supposition
    either side carried, and the fact that something along the way did not come
    out exactly."""
    return (left.supposed or right.supposed,
            EXACT if EXACT == left.exactness == right.exactness == came_out
            else ROUNDED)


def _carefully(step) -> tuple:
    """The value one operation gives, and whether it came out. An operation the
    working precision cannot hold exactly is redone with the trap lifted, and
    what comes back says it was rounded."""
    try:
        return step(), EXACT
    except Inexact:
        with decimal.localcontext() as ctx:
            ctx.traps[Inexact] = False
            return step(), ROUNDED


def _written(amount: Decimal, money: bool) -> Decimal:
    """A value that did not come out exactly, at the scale it is finally
    written at: hundredths for money, which is what money is counted in, and a
    fixed count of significant figures for a dimensionless quantity.

    Significant figures rather than decimal places, because a fixed scale
    writes a small enough ratio as zero and zero is a different claim. Counting
    from the leading digit also means a power of ten moves the point without
    moving the digits, so a proportion and the same proportion per hundred
    agree. Applied once, to the result, so no intermediate step compounds a
    rounding of its own."""
    if money:
        return amount.quantize(MONEY_SCALE)
    if not amount:
        return amount
    return amount.quantize(
        Decimal(1).scaleb(amount.adjusted() - SIGNIFICANT_FIGURES + 1))


def _same_currency(left: _Q, right: _Q) -> str:
    """The currency two amounts share. A supposed value takes the currency of
    whatever it meets; two different currencies meet at no operator."""
    if UNSTATED in (left.dimension, right.dimension):
        return (right.dimension if left.dimension == UNSTATED
                else left.dimension)
    if left.dimension != right.dimension:
        raise _Refuse(MIXED_CURRENCIES,
                      "These amounts are in different currencies, and nothing "
                      "here converts between them. Compute within one currency "
                      "at a time.")
    return left.dimension


def _added(left: _Q, right: _Q, step) -> _Q:
    if left.money != right.money:
        # The sentence names what the figures state rather than what the plain
        # side might be counting, which nothing here knows.
        raise _Refuse(MIXED_DIMENSIONS,
                      "Adding or subtracting needs both sides to be the same "
                      "kind of quantity — two amounts of money, or two plain "
                      "numbers. One of these states a currency and the other "
                      "states none, so the result would be neither. Scale the "
                      "amount by the plain number instead, if that is the "
                      "question.")
    dimension = _same_currency(left, right) if left.money else SCALAR
    records, grade = _summed(left, right)
    amount, came_out = _carefully(lambda: step(left.amount, right.amount))
    supposed, exactness = _carried(left, right, came_out)
    return _Q(amount, dimension, records, grade, supposed, exactness)


def _multiplied(left: _Q, right: _Q) -> _Q:
    if left.money and right.money:
        raise _Refuse(MIXED_DIMENSIONS,
                      "Multiplying one amount of money by another gives a "
                      "quantity no money measures. Multiply an amount by a "
                      "plain number to scale it, or divide the two amounts to "
                      "compare them.")
    money = left if left.money else right if right.money else None
    dimension = money.dimension if money is not None else SCALAR
    records, grade = _rescaled(left, right)
    amount, came_out = _carefully(lambda: left.amount * right.amount)
    supposed, exactness = _carried(left, right, came_out)
    return _Q(amount, dimension, records, grade, supposed, exactness)


def _divided(left: _Q, right: _Q) -> _Q:
    if right.money and not left.money:
        raise _Refuse(MIXED_DIMENSIONS,
                      "Dividing a plain number by an amount of money gives a "
                      "quantity no money measures. Divide an amount by an "
                      "amount to compare them, or an amount by a plain number "
                      "to split it.")
    if left.money and right.money:
        # Two amounts compare to a ratio: how many times over, not an amount
        # of anything.
        _same_currency(left, right)
        dimension = SCALAR
    else:
        dimension = left.dimension
    records, grade = _rescaled(left, right)
    amount, came_out = _carefully(lambda: left.amount / right.amount)
    supposed, exactness = _carried(left, right, came_out)
    return _Q(amount, dimension, records, grade, supposed, exactness)


def _evaluate(node: ast.AST, bound: dict, depth: int = 0) -> _Q:
    """Walk the whitelisted node kinds, combining each operand's annotations at
    every operator. Unusable syntax raises ValueError with the reason and an
    impossible combination raises `_Refuse`; the caller turns either into a
    refusal."""
    if depth > MAX_DEPTH:
        raise ValueError(f"the expression nests deeper than {MAX_DEPTH} levels")
    if isinstance(node, ast.Expression):
        return _evaluate(node.body, bound, depth + 1)
    if isinstance(node, ast.BinOp):
        left = _evaluate(node.left, bound, depth + 1)
        right = _evaluate(node.right, bound, depth + 1)
        if isinstance(node.op, ast.Add):
            return _added(left, right, operator.add)
        if isinstance(node.op, ast.Sub):
            return _added(left, right, operator.sub)
        if isinstance(node.op, ast.Mult):
            return _multiplied(left, right)
        if isinstance(node.op, ast.Div):
            return _divided(left, right)
        raise ValueError("only +, -, * and / are supported")
    if isinstance(node, ast.UnaryOp):
        value = _evaluate(node.operand, bound, depth + 1)
        if isinstance(node.op, ast.USub):
            amount, came_out = _carefully(lambda: -value.amount)
            supposed, exactness = _carried(value, value, came_out)
            return _Q(amount, value.dimension, value.records, value.grade,
                      supposed, exactness)
        if isinstance(node.op, ast.UAdd):
            return value
        raise ValueError("only unary + and - are supported")
    if isinstance(node, ast.Name):
        if node.id not in bound:
            raise ValueError(f"name '{node.id}' is not bound in inputs")
        return bound[node.id]
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, int):
            raise ValueError(
                "only integer literals are allowed in the expression; every "
                "decimal figure arrives through inputs as a figure id")
        return _Q(Decimal(node.value))
    raise ValueError(f"unsupported syntax: {type(node).__name__}")


def _numbers_in(text: str) -> set:
    """The digits the person wrote, commas stripped — the only values a
    stipulation may take."""
    return {t.replace(",", "") for t in re.findall(r"\d[\d,]*(?:\.\d+)?",
                                                   str(text or ""))}


def _bad_input(message: str, figures: dict) -> ToolResult:
    return refusal(TOOL, "bad_input", message,
                   available_figures=[{"id": f["id"], "what": f["what"],
                                       "kind": f["kind"]}
                                      for f in figures.values()])


def compute(args: dict, figures: dict, question: str = "") -> ToolResult:
    expression = args["expression"]
    inputs = args.get("inputs") or {}
    if not isinstance(inputs, dict):
        return _bad_input("inputs must be an object binding each name to a "
                          "figure id or a stipulated value.", figures)
    said = _numbers_in(question)
    bound: dict[str, _Q] = {}
    used: list = []
    for name, value in inputs.items():
        if isinstance(value, dict) and STIPULATED in value:
            amount = str(value[STIPULATED])
            if not _numbers_in(amount) <= said or not _numbers_in(amount):
                return _bad_input(
                    f"input '{name}' is stipulated as {amount!r}, but you did "
                    "not say that in this question.", figures)
            try:
                # An amount the person named is money in whatever currency the
                # rest of the expression is in, resting on their premise rather
                # than on any record.
                bound[name] = _Q(Decimal(amount.replace(",", "")), UNSTATED,
                                 supposed=True)
            except InvalidOperation:
                return _bad_input(f"the stipulated value for '{name}' is not a "
                                  f"number: {amount!r}", figures)
            continue
        fid = str(value)
        if fid not in figures:
            return _bad_input(
                f"input '{name}' is {value!r}; an operand is the id of a figure "
                "some tool returned in this turn, or an object "
                f"{{\"{STIPULATED}\": \"<what you said>\"}} — never a number "
                "typed in directly.", figures)
        fig = figures[fid]
        try:
            # A figure stating a currency is an amount of money; one stating
            # none — a count of accounts, of documents, of movements — is a
            # plain number, and the two do not add.
            bound[name] = _Q(Decimal(str(fig["value"])),
                             str(fig["currency"] or SCALAR),
                             frozenset(fig["record_ids"]), fig["grade"],
                             fig["kind"] == HYPOTHETICAL, fig["exactness"])
        except InvalidOperation:
            return _bad_input(f"figure {fid} does not hold a number: "
                              f"{fig['value']!r}", figures)
        used.append(fig)

    if len(expression) > MAX_EXPRESSION:
        return refusal(TOOL, "bad_expression",
                       f"the expression is longer than {MAX_EXPRESSION} "
                       "characters; no question about money needs that.")
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as err:
        return refusal(TOOL, "bad_expression",
                       f"could not parse the expression: {err.msg}")
    except (RecursionError, MemoryError, ValueError):
        return refusal(TOOL, "bad_expression",
                       "the expression is nested too deeply to read.")
    kinds = {fig["kind"] for fig in used}
    if ACTIVITY in kinds and kinds - {ACTIVITY}:
        return refusal(TOOL, "mixed_kinds",
                       "One of these figures is about my own behaviour and "
                       "another is about your money; a number combining them "
                       "would be a claim of neither kind.")

    try:
        with decimal.localcontext() as ctx:
            ctx.prec = PRECISION
            ctx.traps[Inexact] = True
            result_q = _evaluate(tree, bound)
            if result_q.exactness != EXACT:
                # Carried at the working precision the whole way and written at
                # its final scale once, here.
                ctx.traps[Inexact] = False
                result_q = replace(result_q,
                                   amount=_written(result_q.amount,
                                                   result_q.money))
    except _Refuse as refused:
        return refusal(TOOL, refused.tag, refused.text)
    except ValueError as err:
        return refusal(TOOL, "bad_expression", str(err))
    except (DivisionByZero, ZeroDivisionError):
        return refusal(TOOL, "division_by_zero",
                       "the expression divides by zero")
    except InvalidOperation:
        return refusal(TOOL, "bad_expression",
                       "the arithmetic is not representable exactly")
    except (DecimalException, ArithmeticError, RecursionError):
        # Every path out of this function is an envelope; no arithmetic
        # failure crosses the boundary as an exception.
        return refusal(TOOL, "bad_expression",
                       "the arithmetic is too large to carry out exactly")

    record_ids = sorted(result_q.records)
    # A supposition survives every hop it is carried through: a result any
    # supposed value reached is itself hypothetical, however many times it is
    # recomputed.
    kind = HYPOTHETICAL if result_q.supposed else (
        ACTIVITY if kinds == {ACTIVITY} else COMPUTED)
    result = figure(
        result_q.amount, f"the result of {expression}", kind=kind,
        grade=result_q.grade,
        currency="" if result_q.dimension == UNSTATED else result_q.dimension,
        record_ids=record_ids, exactness=result_q.exactness)
    return ToolResult(
        tool=TOOL, ok=True, figures=[result],
        data={"expression": expression,
              "inputs": {k: str(q.amount) for k, q in sorted(bound.items())}},
        grade=result["grade"], record_ids=record_ids,
        # A tool's own prose is sayable by the answer, so these sentences name
        # no number and do not restate the expression's literals.
        text=("Computed exactly; the result is this call's figure."
              if result["exactness"] == EXACT else
              "This does not come out exactly; the result is this call's "
              "figure, written at the scale it is carried to."))
