"""Exact arithmetic as a tool, so no model ever adds two numbers itself.

The expression is parsed, never evaluated as Python: only +, -, *, /,
parentheses, integer literals and names are accepted, and every name must be
bound in ``inputs`` to an exact decimal string. Decimal values may not appear
as literals — a float literal loses exactness before the arithmetic starts, so
figures arrive through ``inputs``, which is also where their grades and source
documents travel.
"""

from __future__ import annotations

import ast
from decimal import Decimal, DivisionByZero, InvalidOperation

from .envelope import ToolResult, refusal, weakest

COMPUTE_PARAMS = {
    "type": "object",
    "properties": {
        "expression": {"type": "string"},
        "inputs": {"type": "object"},
        "grades": {"type": "object"},
        "record_ids": {"type": "array"},
    },
    "required": ["expression"],
}

TOOL = "compute"


def _evaluate(node: ast.AST, bound: dict) -> Decimal:
    """Walk the whitelisted node kinds; anything else raises ValueError with
    the reason, which the caller turns into a refusal."""
    if isinstance(node, ast.Expression):
        return _evaluate(node.body, bound)
    if isinstance(node, ast.BinOp):
        left, right = _evaluate(node.left, bound), _evaluate(node.right, bound)
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
        value = _evaluate(node.operand, bound)
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
                "only integer literals are allowed in the expression; pass "
                "decimal figures through inputs as exact strings")
        return Decimal(node.value)
    raise ValueError(f"unsupported syntax: {type(node).__name__}")


def compute(args: dict) -> ToolResult:
    expression = args["expression"]
    inputs = args.get("inputs", {})
    grades = args.get("grades", {})
    record_ids = [str(r) for r in args.get("record_ids", [])]
    bound: dict[str, Decimal] = {}
    for name, value in inputs.items():
        try:
            bound[name] = Decimal(str(value))
        except InvalidOperation:
            return refusal(TOOL, "bad_input",
                           f"input '{name}' is not a decimal: {value!r}")
    unknown_grades = sorted(set(grades) - set(inputs))
    if unknown_grades:
        return refusal(TOOL, "bad_input",
                       "grades name inputs that do not exist: "
                       + ", ".join(unknown_grades))
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as err:
        return refusal(TOOL, "bad_expression",
                       f"could not parse the expression: {err.msg}")
    try:
        value = _evaluate(tree, bound)
    except ValueError as err:
        return refusal(TOOL, "bad_expression", str(err))
    except (DivisionByZero, ZeroDivisionError):
        return refusal(TOOL, "division_by_zero",
                       "the expression divides by zero")
    except InvalidOperation:
        return refusal(TOOL, "bad_expression",
                       "the arithmetic is not representable exactly")
    return ToolResult(
        tool=TOOL, ok=True,
        data={"value": str(value), "expression": expression,
              "inputs": {k: str(v) for k, v in sorted(bound.items())}},
        grade=weakest(grades.values()),
        record_ids=sorted(set(record_ids)),
        text=f"{expression} = {value}, computed exactly.")
