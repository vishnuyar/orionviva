"""Exact arithmetic as a tool, so no model ever adds two numbers itself.

The expression is parsed, never evaluated as Python: only +, -, *, /,
parentheses, integer literals and names are accepted, and every name must be
bound in ``inputs``.

An operand is not a number the caller typed. It is either a **figure** some
tool emitted in this run, named by its id, or a value the **person** stipulated
in this turn's question. A raw decimal refuses, and the refusal names the
figures that are available.

Because operands are figures, the result inherits its provenance rather than
being told it: the union of its inputs' records, the weakest of their grades.
A sum of corroborated balances is corroborated, and is marked ``computed``. A
result resting on anything the person supposed is marked ``hypothetical``
instead and carries no grade.

Two things the arithmetic refuses: adding across currencies, since nothing
here converts between them; and mixing a claim about the person's money with a
claim about the agent's own behaviour.
"""

from __future__ import annotations

import ast
import decimal
import re
from decimal import (Decimal, DecimalException, DivisionByZero, Inexact,
                     InvalidOperation)

from .envelope import (ACTIVITY, COMPUTED, HYPOTHETICAL, MONEY_KINDS,
                       ToolResult, figure, refusal, weakest)

# Each nesting level of the expression costs one Python frame in the walk.
# Deeper than this refuses as `bad_expression`.
MAX_DEPTH = 100

# The length is checked before `ast.parse` runs, because the parser recurses
# before this module's own walk begins.
MAX_EXPRESSION = 2000

# Enough significant digits that adding, subtracting and multiplying money is
# always exact. Beyond it the context traps `Inexact` rather than rounding, and
# the call refuses.
PRECISION = 400

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


def _evaluate(node: ast.AST, bound: dict, depth: int = 0) -> Decimal:
    """Walk the whitelisted node kinds; anything else raises ValueError with
    the reason, which the caller turns into a refusal."""
    if depth > MAX_DEPTH:
        raise ValueError(f"the expression nests deeper than {MAX_DEPTH} levels")
    if isinstance(node, ast.Expression):
        return _evaluate(node.body, bound, depth + 1)
    if isinstance(node, ast.BinOp):
        left = _evaluate(node.left, bound, depth + 1)
        right = _evaluate(node.right, bound, depth + 1)
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.Div):
            return left / right
        raise ValueError("only +, -, * and / are supported")
    if isinstance(node, ast.UnaryOp):
        value = _evaluate(node.operand, bound, depth + 1)
        if isinstance(node.op, ast.USub):
            return -value
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
        return Decimal(node.value)
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
    bound: dict[str, Decimal] = {}
    used: list = []
    supposed = False
    for name, value in inputs.items():
        if isinstance(value, dict) and STIPULATED in value:
            amount = str(value[STIPULATED])
            if not _numbers_in(amount) <= said or not _numbers_in(amount):
                return _bad_input(
                    f"input '{name}' is stipulated as {amount!r}, but you did "
                    "not say that in this question.", figures)
            try:
                bound[name] = Decimal(amount.replace(",", ""))
            except InvalidOperation:
                return _bad_input(f"the stipulated value for '{name}' is not a "
                                  f"number: {amount!r}", figures)
            supposed = True
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
            bound[name] = Decimal(str(fig["value"]))
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
    currencies = {fig["currency"] for fig in used if fig["currency"]}
    if len(currencies) > 1:
        # No read here converts between currencies, and neither does this.
        return refusal(TOOL, "mixed_currencies",
                       "These figures are in " + ", ".join(sorted(currencies))
                       + ", and nothing here converts between currencies. "
                       "Compute within one currency at a time.")
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
            value = _evaluate(tree, bound)
    except ValueError as err:
        return refusal(TOOL, "bad_expression", str(err))
    except (DivisionByZero, ZeroDivisionError):
        return refusal(TOOL, "division_by_zero",
                       "the expression divides by zero")
    except Inexact:
        return refusal(TOOL, "inexact",
                       "This does not come out exactly — it would have to be "
                       "rounded, and I will not hand back a rounded figure as "
                       "though it were the answer. Ask for it a way that "
                       "divides evenly, or ask me for the parts.")
    except InvalidOperation:
        return refusal(TOOL, "bad_expression",
                       "the arithmetic is not representable exactly")
    except (DecimalException, ArithmeticError, RecursionError):
        # Every path out of this function is an envelope; no arithmetic
        # failure crosses the boundary as an exception.
        return refusal(TOOL, "bad_expression",
                       "the arithmetic is too large to carry out exactly")

    record_ids = sorted({r for fig in used for r in fig["record_ids"]})
    # A supposition survives every hop it is carried through: a result with
    # any hypothetical operand is itself hypothetical, however many times it is
    # recomputed.
    kind = HYPOTHETICAL if (supposed or HYPOTHETICAL in kinds) else (
        ACTIVITY if kinds == {ACTIVITY} else COMPUTED)
    result = figure(
        value, f"the result of {expression}", kind=kind,
        grade=weakest(fig["grade"] for fig in used
                      if fig["kind"] in MONEY_KINDS),
        currency=currencies.pop() if currencies else "",
        record_ids=record_ids)
    return ToolResult(
        tool=TOOL, ok=True, figures=[result],
        data={"expression": expression,
              "inputs": {k: str(v) for k, v in sorted(bound.items())}},
        grade=result["grade"], record_ids=record_ids,
        # A tool's own prose is sayable by the answer, so this sentence names
        # no number and does not restate the expression's literals.
        text="Computed exactly; the result is this call's figure.")
