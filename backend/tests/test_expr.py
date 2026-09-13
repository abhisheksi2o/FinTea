from fintea.sheet import Book, K, Const, IF, IFERROR, SUM, SLOPE, GT, EQ, RangeRef, CellRef, ABS, MAX
from fintea.sheet.expr import Err, DIV0


def _book():
    b = Book()
    b.set("S", 1, 1, 100, key="a")
    b.set("S", 2, 1, 0.05, key="g")
    b.set("S", 3, 1, K("S", "a") * (1 + K("S", "g")), key="r")
    return b


def test_render_precedence():
    b = _book()
    e = (K("S", "a") - K("S", "g")) / (1 + K("S", "g")) ** 2 - -K("S", "a")
    assert e.render(b, "S") == "(A1-A2)/(1+A2)^2-(-A1)"
    assert e.render(b, "T") == "('S'!A1-'S'!A2)/(1+'S'!A2)^2-(-'S'!A1)"
    assert (K("S", "a") - (K("S", "g") - 1)).render(b, "S") == "A1-(A2-1)"
    assert (K("S", "a") / (K("S", "g") * 2)).render(b, "S") == "A1/(A2*2)"


def test_eval_and_errors():
    b = _book()
    assert b.val("S", "r") == 105.0
    b.set("S", 4, 1, K("S", "a") / 0, key="d")
    assert b.val("S", "d") == DIV0
    b.set("S", 5, 1, IFERROR(K("S", "d"), "n/a"), key="e")
    assert b.val("S", "e") == "n/a"
    b.set("S", 6, 1, IF(GT(K("S", "r"), 100), "PASS", "FAIL"), key="f")
    assert b.val("S", "f") == "PASS"
    assert b.formula(b.get("S", 6, 1)) == '=IF(A3>100,"PASS","FAIL")'


def test_functions():
    b = Book()
    ys, xs = [1, 2, 3, 4], [2, 4.1, 5.9, 8.2]
    for i, (y, x) in enumerate(zip(ys, xs), start=1):
        b.set("D", i, 1, y)
        b.set("D", i, 2, x)
    b.set("D", 6, 1, SLOPE(RangeRef("D", 1, 1, 4, 1), RangeRef("D", 1, 2, 4, 2)), key="slope")
    assert abs(b.val("D", "slope") - 0.489208633093525) < 1e-12
    b.set("D", 7, 1, SUM(RangeRef("D", 1, 1, 4, 1), 10), key="sum")
    assert b.val("D", "sum") == 20
    assert b.formula(b.get("D", 7, 1)) == "=SUM(A1:A4,10)"
    b.set("D", 8, 1, MAX(ABS(Const(-3)), 2), key="max")
    assert b.val("D", "max") == 3


def test_cycle_detection():
    import pytest
    from fintea.sheet.book import CycleError
    b = Book()
    b.set("S", 1, 1, K("S", "b"), key="a")
    b.set("S", 2, 1, K("S", "a"), key="b")
    with pytest.raises(CycleError):
        b.val("S", "a")
