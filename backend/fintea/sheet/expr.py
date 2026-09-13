"""A tiny spreadsheet expression AST.

Every expression can be *evaluated* in Python (so the API can preview values and
tests can assert on them) and *rendered* to an Excel formula string (so the
workbook is fully formula driven). Because both come from one AST, the preview
and the spreadsheet can never disagree.
"""
from __future__ import annotations

import math
import statistics
from typing import Any, Iterable, List

from openpyxl.utils import get_column_letter


class Err:
    """Excel-style error value (#DIV/0!, #VALUE!, #NUM!, #N/A)."""

    __slots__ = ("code",)

    def __init__(self, code: str):
        self.code = code

    def __repr__(self):  # pragma: no cover - debugging aid
        return self.code

    def __eq__(self, other):
        return isinstance(other, Err) and other.code == self.code

    def __hash__(self):
        return hash(self.code)


DIV0 = Err("#DIV/0!")
VALUE = Err("#VALUE!")
NUM = Err("#NUM!")
NA = Err("#N/A")


def is_num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _num(v: Any):
    """Coerce a scalar the way Excel arithmetic does (blank -> 0, bool -> 0/1)."""
    if v is None:
        return 0.0
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    if is_num(v):
        return float(v)
    if isinstance(v, Err):
        return v
    return VALUE


def _flatten(vals: Iterable[Any]) -> List[Any]:
    out: List[Any] = []
    for v in vals:
        if isinstance(v, (list, tuple)):
            out.extend(_flatten(v))
        else:
            out.append(v)
    return out


def _numbers(vals: Iterable[Any]) -> List[float]:
    """Numbers only, ignoring text/blank/bool, the way SUM over a range behaves."""
    out = []
    for v in _flatten(vals):
        if isinstance(v, Err):
            raise _ErrSignal(v)
        if is_num(v):
            out.append(float(v))
    return out


class _ErrSignal(Exception):
    def __init__(self, err: Err):
        self.err = err


def quote_sheet(name: str) -> str:
    return "'" + name.replace("'", "''") + "'"


def fmt_number(x: float) -> str:
    if isinstance(x, bool):
        return "TRUE" if x else "FALSE"
    if float(x).is_integer() and abs(x) < 1e15:
        return str(int(x))
    s = repr(float(x))
    if "e" in s or "E" in s:
        s = format(float(x), ".15g")
    return s


class Expr:
    """Base class. Subclasses implement eval(book) and render(book, sheet)."""

    precedence = 100

    def eval(self, book) -> Any:  # pragma: no cover - abstract
        raise NotImplementedError

    def render(self, book, sheet: str) -> str:  # pragma: no cover - abstract
        raise NotImplementedError

    # arithmetic -----------------------------------------------------------
    def __add__(self, o): return BinOp("+", self, lift(o))
    def __radd__(self, o): return BinOp("+", lift(o), self)
    def __sub__(self, o): return BinOp("-", self, lift(o))
    def __rsub__(self, o): return BinOp("-", lift(o), self)
    def __mul__(self, o): return BinOp("*", self, lift(o))
    def __rmul__(self, o): return BinOp("*", lift(o), self)
    def __truediv__(self, o): return BinOp("/", self, lift(o))
    def __rtruediv__(self, o): return BinOp("/", lift(o), self)
    def __pow__(self, o): return BinOp("^", self, lift(o))
    def __rpow__(self, o): return BinOp("^", lift(o), self)
    def __neg__(self): return Neg(self)


def lift(x: Any) -> Expr:
    if isinstance(x, Expr):
        return x
    return Const(x)


class Const(Expr):
    def __init__(self, value: Any):
        self.value = value

    def eval(self, book):
        return self.value

    def render(self, book, sheet):
        v = self.value
        if isinstance(v, bool):
            return "TRUE" if v else "FALSE"
        if is_num(v):
            return fmt_number(v)
        if v is None:
            return '""'
        return '"' + str(v).replace('"', '""') + '"'


class CellRef(Expr):
    def __init__(self, sheet: str, row: int, col: int, absolute: bool = False):
        self.sheet, self.row, self.col, self.absolute = sheet, row, col, absolute

    def address(self, current_sheet: str | None = None) -> str:
        col = get_column_letter(self.col)
        a = f"${col}${self.row}" if self.absolute else f"{col}{self.row}"
        if current_sheet is not None and current_sheet == self.sheet:
            return a
        return f"{quote_sheet(self.sheet)}!{a}"

    def eval(self, book):
        return book.value(self.sheet, self.row, self.col)

    def render(self, book, sheet):
        return self.address(sheet)


class K(Expr):
    """Symbolic reference resolved through the book registry: (sheet, key, period)."""

    def __init__(self, sheet: str, key: str, period: int | None = None, absolute: bool = False):
        self.sheet, self.key, self.period, self.absolute = sheet, key, period, absolute

    def resolve(self, book) -> CellRef:
        row, col = book.lookup(self.sheet, self.key, self.period)
        return CellRef(self.sheet, row, col, self.absolute)

    def eval(self, book):
        return self.resolve(book).eval(book)

    def render(self, book, sheet):
        return self.resolve(book).render(book, sheet)


class RangeRef(Expr):
    def __init__(self, sheet: str, r0: int, c0: int, r1: int, c1: int):
        self.sheet, self.r0, self.c0, self.r1, self.c1 = sheet, r0, c0, r1, c1

    def eval(self, book):
        return [book.value(self.sheet, r, c)
                for r in range(self.r0, self.r1 + 1) for c in range(self.c0, self.c1 + 1)]

    def render(self, book, sheet):
        a = f"{get_column_letter(self.c0)}{self.r0}:{get_column_letter(self.c1)}{self.r1}"
        if sheet == self.sheet:
            return a
        return f"{quote_sheet(self.sheet)}!{a}"


class RangeK(Expr):
    """Horizontal range over periods p0..p1 (inclusive) of a keyed row."""

    def __init__(self, sheet: str, key: str, p0: int, p1: int):
        self.sheet, self.key, self.p0, self.p1 = sheet, key, p0, p1

    def resolve(self, book) -> RangeRef:
        r0, c0 = book.lookup(self.sheet, self.key, self.p0)
        r1, c1 = book.lookup(self.sheet, self.key, self.p1)
        return RangeRef(self.sheet, r0, c0, r1, c1)

    def eval(self, book):
        return self.resolve(book).eval(book)

    def render(self, book, sheet):
        return self.resolve(book).render(book, sheet)


_PREC = {"^": 4, "*": 3, "/": 3, "+": 2, "-": 2, "=": 1, "<>": 1, "<": 1, "<=": 1, ">": 1, ">=": 1}


class BinOp(Expr):
    def __init__(self, op: str, a: Expr, b: Expr):
        self.op, self.a, self.b = op, a, b
        self.precedence = _PREC[op]

    def eval(self, book):
        a, b = self.a.eval(book), self.b.eval(book)
        op = self.op
        if op in ("=", "<>", "<", "<=", ">", ">="):
            if isinstance(a, Err):
                return a
            if isinstance(b, Err):
                return b
            if isinstance(a, str) or isinstance(b, str):
                if op == "=":
                    return str(a).lower() == str(b).lower()
                if op == "<>":
                    return str(a).lower() != str(b).lower()
                return VALUE
            a, b = _num(a), _num(b)
            return {"=": a == b, "<>": a != b, "<": a < b, "<=": a <= b, ">": a > b, ">=": a >= b}[op]
        a, b = _num(a), _num(b)
        if isinstance(a, Err):
            return a
        if isinstance(b, Err):
            return b
        if op == "+":
            return a + b
        if op == "-":
            return a - b
        if op == "*":
            return a * b
        if op == "/":
            return DIV0 if b == 0 else a / b
        if op == "^":
            try:
                r = a ** b
            except (OverflowError, ZeroDivisionError):
                return NUM
            if isinstance(r, complex):
                return NUM
            return r
        raise ValueError(op)

    def render(self, book, sheet):
        a = self.a.render(book, sheet)
        b = self.b.render(book, sheet)
        pa, pb = self.a.precedence, self.b.precedence
        if pa < self.precedence or (self.op == "^" and isinstance(self.a, BinOp)):
            a = f"({a})"
        if pb < self.precedence or (pb == self.precedence and self.op in ("-", "/", "^")) or isinstance(self.b, Neg):
            b = f"({b})"
        return f"{a}{self.op}{b}"


class Neg(Expr):
    precedence = 5

    def __init__(self, a: Expr):
        self.a = a

    def eval(self, book):
        v = _num(self.a.eval(book))
        return v if isinstance(v, Err) else -v

    def render(self, book, sheet):
        inner = self.a.render(book, sheet)
        if isinstance(self.a, BinOp):
            inner = f"({inner})"
        return f"-{inner}"


def EQ(a, b): return BinOp("=", lift(a), lift(b))
def NE(a, b): return BinOp("<>", lift(a), lift(b))
def LT(a, b): return BinOp("<", lift(a), lift(b))
def LE(a, b): return BinOp("<=", lift(a), lift(b))
def GT(a, b): return BinOp(">", lift(a), lift(b))
def GE(a, b): return BinOp(">=", lift(a), lift(b))


# ---------------------------------------------------------------------------
# Functions
# ---------------------------------------------------------------------------

def _round_half_away(x: float, n: int) -> float:
    m = 10 ** n
    return math.floor(abs(x) * m + 0.5) / m * (1 if x >= 0 else -1)


def _pairs(ys, xs):
    ys, xs = _flatten(ys), _flatten(xs)
    if len(ys) != len(xs):
        raise _ErrSignal(NA)
    pts = [(float(y), float(x)) for y, x in zip(ys, xs) if is_num(y) and is_num(x)]
    if len(pts) < 2:
        raise _ErrSignal(DIV0)
    return pts


def _slope_intercept(ys, xs):
    pts = _pairs(ys, xs)
    n = len(pts)
    my = sum(p[0] for p in pts) / n
    mx = sum(p[1] for p in pts) / n
    sxx = sum((x - mx) ** 2 for _, x in pts)
    if sxx == 0:
        raise _ErrSignal(DIV0)
    sxy = sum((x - mx) * (y - my) for y, x in pts)
    slope = sxy / sxx
    return slope, my - slope * mx


def _correl(ys, xs):
    pts = _pairs(ys, xs)
    n = len(pts)
    my = sum(p[0] for p in pts) / n
    mx = sum(p[1] for p in pts) / n
    sxx = sum((x - mx) ** 2 for _, x in pts)
    syy = sum((y - my) ** 2 for y, _ in pts)
    if sxx == 0 or syy == 0:
        raise _ErrSignal(DIV0)
    sxy = sum((x - mx) * (y - my) for y, x in pts)
    return sxy / math.sqrt(sxx * syy)


def _f_sum(*a): return sum(_numbers(a))
def _f_average(*a):
    n = _numbers(a)
    if not n:
        raise _ErrSignal(DIV0)
    return sum(n) / len(n)
def _f_min(*a):
    n = _numbers(a)
    return min(n) if n else 0.0
def _f_max(*a):
    n = _numbers(a)
    return max(n) if n else 0.0
def _f_count(*a): return float(len(_numbers(a)))
def _f_abs(x):
    x = _num(x)
    return x if isinstance(x, Err) else abs(x)
def _f_sqrt(x):
    x = _num(x)
    if isinstance(x, Err):
        return x
    if x < 0:
        return NUM
    return math.sqrt(x)
def _f_round(x, n=0):
    x, n = _num(x), _num(n)
    if isinstance(x, Err):
        return x
    return _round_half_away(x, int(n))
def _f_and(*a): return all(bool(_num(v)) for v in _flatten(a))
def _f_or(*a): return any(bool(_num(v)) for v in _flatten(a))
def _f_not(a): return not bool(_num(a))
def _f_slope(ys, xs): return _slope_intercept(ys, xs)[0]
def _f_intercept(ys, xs): return _slope_intercept(ys, xs)[1]
def _f_rsq(ys, xs): return _correl(ys, xs) ** 2
def _f_correl(ys, xs): return _correl(ys, xs)
def _f_stdev(*a):
    n = _numbers(a)
    if len(n) < 2:
        raise _ErrSignal(DIV0)
    return statistics.stdev(n)
def _f_varp(*a):
    n = _numbers(a)
    if not n:
        raise _ErrSignal(DIV0)
    return statistics.pvariance(n)
def _f_covar(ys, xs):
    pts = _pairs(ys, xs)
    n = len(pts)
    my = sum(p[0] for p in pts) / n
    mx = sum(p[1] for p in pts) / n
    return sum((x - mx) * (y - my) for y, x in pts) / n


_EAGER = {
    "SUM": _f_sum, "AVERAGE": _f_average, "MIN": _f_min, "MAX": _f_max, "COUNT": _f_count,
    "ABS": _f_abs, "SQRT": _f_sqrt, "ROUND": _f_round, "AND": _f_and, "OR": _f_or, "NOT": _f_not,
    "SLOPE": _f_slope, "INTERCEPT": _f_intercept, "RSQ": _f_rsq, "CORREL": _f_correl,
    "STDEV": _f_stdev, "VARP": _f_varp, "COVAR": _f_covar,
}


class Fn(Expr):
    def __init__(self, name: str, *args: Any):
        self.name = name.upper()
        self.args = [lift(a) for a in args]

    def eval(self, book):
        name = self.name
        if name == "IF":
            c = self.args[0].eval(book)
            if isinstance(c, Err):
                return c
            if bool(_num(c)):
                return self.args[1].eval(book)
            return self.args[2].eval(book) if len(self.args) > 2 else False
        if name == "IFERROR":
            v = self.args[0].eval(book)
            if isinstance(v, Err):
                return self.args[1].eval(book)
            return v
        fn = _EAGER[name]
        vals = [a.eval(book) for a in self.args]
        # scalar error args propagate for scalar functions
        for v in vals:
            if isinstance(v, Err) and name in ("ABS", "SQRT", "ROUND", "AND", "OR", "NOT"):
                return v
        try:
            return fn(*vals)
        except _ErrSignal as e:
            return e.err

    def render(self, book, sheet):
        return f"{self.name}({','.join(a.render(book, sheet) for a in self.args)})"


def SUM(*a): return Fn("SUM", *a)
def AVERAGE(*a): return Fn("AVERAGE", *a)
def MIN(*a): return Fn("MIN", *a)
def MAX(*a): return Fn("MAX", *a)
def COUNT(*a): return Fn("COUNT", *a)
def ABS(a): return Fn("ABS", a)
def SQRT(a): return Fn("SQRT", a)
def ROUND(a, n=0): return Fn("ROUND", a, n)
def IF(c, a, b): return Fn("IF", c, a, b)
def AND(*a): return Fn("AND", *a)
def OR(*a): return Fn("OR", *a)
def NOT(a): return Fn("NOT", a)
def IFERROR(a, b): return Fn("IFERROR", a, b)
def SLOPE(y, x): return Fn("SLOPE", y, x)
def INTERCEPT(y, x): return Fn("INTERCEPT", y, x)
def RSQ(y, x): return Fn("RSQ", y, x)
def CORREL(y, x): return Fn("CORREL", y, x)
def STDEV(*a): return Fn("STDEV", *a)
def VARP(*a): return Fn("VARP", *a)
def COVAR(y, x): return Fn("COVAR", y, x)
