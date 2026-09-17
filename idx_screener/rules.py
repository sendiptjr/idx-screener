"""Evaluator ekspresi filter yang aman (tanpa `eval` bawaan Python).

Contoh ekspresi yang didukung:

    per > 0 and per < 12
    close > sma200 and rsi14 between 40 and 60
    sector in ["Keuangan", "Energi"]
    avg_value_20 > 5e9

Hanya simpul AST dalam daftar putih yang dieksekusi, jadi ekspresi dari file
preset atau input UI tidak bisa memanggil kode sembarangan.
"""

from __future__ import annotations

import ast
import operator as op
import re
from dataclasses import dataclass

_BIN_OPS = {
    ast.Add: op.add, ast.Sub: op.sub, ast.Mult: op.mul,
    ast.Div: op.truediv, ast.Mod: op.mod, ast.Pow: op.pow,
    ast.FloorDiv: op.floordiv,
}
_CMP_OPS = {
    ast.Lt: op.lt, ast.LtE: op.le, ast.Gt: op.gt, ast.GtE: op.ge,
    ast.Eq: op.eq, ast.NotEq: op.ne,
}
_FUNCS = {
    "abs": abs, "min": min, "max": max, "round": round,
    "len": len, "lower": lambda s: str(s).lower(),
}
_CONSTANTS = {"True": True, "False": False, "None": None, "true": True, "false": False}

# Gula sintaksis: "x between a and b" -> "(a <= x <= b)".
_BETWEEN = re.compile(
    r"([A-Za-z_][A-Za-z_0-9]*)\s+between\s+(-?[\d._eE+]+)\s+and\s+(-?[\d._eE+]+)"
)


class RuleError(ValueError):
    """Ekspresi filter tidak valid."""


@dataclass(frozen=True)
class Rule:
    expression: str
    _tree: ast.Expression

    @property
    def fields(self) -> set[str]:
        return {
            n.id
            for n in ast.walk(self._tree)
            if isinstance(n, ast.Name) and n.id not in _FUNCS and n.id not in _CONSTANTS
        }

    def evaluate(self, row: dict) -> bool | None:
        """True / False, atau None bila ada metrik yang nilainya tidak tersedia."""
        value = _eval(self._tree.body, row)
        return None if value is None else bool(value)

    def __str__(self) -> str:  # pragma: no cover - tampilan saja
        return self.expression


def compile_rule(expression: str) -> Rule:
    text = _BETWEEN.sub(r"(\2 <= \1 <= \3)", expression.strip())
    if not text:
        raise RuleError("ekspresi kosong")
    try:
        tree = ast.parse(text, mode="eval")
    except SyntaxError as exc:
        raise RuleError(f"sintaks tidak valid pada '{expression}': {exc.msg}") from exc
    _validate(tree.body)
    return Rule(expression=expression.strip(), _tree=tree)


def compile_rules(expressions: list[str]) -> list[Rule]:
    return [compile_rule(e) for e in expressions]


def unknown_fields(rules: list[Rule], known: set[str]) -> set[str]:
    used: set[str] = set()
    for rule in rules:
        used |= rule.fields
    return used - known


# --------------------------------------------------------------------------


_ALLOWED_NODES = (
    ast.Expression, ast.BoolOp, ast.UnaryOp, ast.BinOp, ast.Compare, ast.Name,
    ast.Constant, ast.Call, ast.List, ast.Tuple, ast.Set, ast.Load,
    ast.And, ast.Or, ast.Not, ast.USub, ast.UAdd, ast.In, ast.NotIn,
    *_BIN_OPS, *_CMP_OPS,
)


def _validate(node: ast.AST) -> None:
    for child in ast.walk(node):
        if not isinstance(child, _ALLOWED_NODES):
            raise RuleError(
                f"konstruksi '{type(child).__name__}' tidak diizinkan dalam filter"
            )
        if isinstance(child, ast.Call):
            if not isinstance(child.func, ast.Name) or child.func.id not in _FUNCS:
                raise RuleError("hanya fungsi abs/min/max/round/len/lower yang tersedia")


def _eval(node: ast.AST, row: dict):
    """Kembalikan nilai, atau None bila salah satu operand tidak diketahui."""
    if isinstance(node, ast.Constant):
        return node.value

    if isinstance(node, ast.Name):
        if node.id in _CONSTANTS:
            return _CONSTANTS[node.id]
        if node.id not in row:
            raise RuleError(f"metrik '{node.id}' tidak dikenal")
        value = row[node.id]
        # pandas mengubah None menjadi NaN di kolom numerik; keduanya "data kosong".
        return None if isinstance(value, float) and value != value else value

    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return [_eval(e, row) for e in node.elts]

    if isinstance(node, ast.UnaryOp):
        value = _eval(node.operand, row)
        if isinstance(node.op, ast.Not):
            return None if value is None else (not value)
        if value is None:
            return None
        return -value if isinstance(node.op, ast.USub) else +value

    if isinstance(node, ast.BinOp):
        left, right = _eval(node.left, row), _eval(node.right, row)
        if left is None or right is None:
            return None
        try:
            return _BIN_OPS[type(node.op)](left, right)
        except ZeroDivisionError:
            return None

    if isinstance(node, ast.BoolOp):
        values = [_eval(v, row) for v in node.values]
        if isinstance(node.op, ast.And):
            if any(v is False for v in values):
                return False          # satu saja salah -> pasti salah
            return None if any(v is None for v in values) else True
        if any(v is True for v in values):
            return True               # satu saja benar -> pasti benar
        return None if any(v is None for v in values) else False

    if isinstance(node, ast.Compare):
        left = _eval(node.left, row)
        for operator, comparator in zip(node.ops, node.comparators):
            right = _eval(comparator, row)
            if isinstance(operator, (ast.In, ast.NotIn)):
                if left is None or right is None:
                    return None
                inside = _contains(right, left)
                if isinstance(operator, ast.NotIn):
                    inside = not inside
                if not inside:
                    return False
                left = right
                continue
            if left is None or right is None:
                return None
            if not _CMP_OPS[type(operator)](left, right):
                return False
            left = right
        return True

    if isinstance(node, ast.Call):
        args = [_eval(a, row) for a in node.args]
        if any(a is None for a in args):
            return None
        return _FUNCS[node.func.id](*args)

    raise RuleError(f"konstruksi '{type(node).__name__}' tidak didukung")


def _contains(container, value) -> bool:
    """`in` pada teks bersifat case-insensitive agar sektor mudah dicocokkan."""
    if isinstance(container, str):
        return str(value).lower() in container.lower()
    if isinstance(container, (list, tuple, set)):
        return any(
            str(value).lower() == str(item).lower()
            if isinstance(item, str) or isinstance(value, str)
            else value == item
            for item in container
        )
    return value in container
