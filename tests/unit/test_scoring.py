from __future__ import annotations

from fractions import Fraction

import pytest

from shogun.services.scoring import check_response, negative_marks, normalize_msq, score_response


@pytest.mark.parametrize(
    "qtype,marks,key,lo,hi,response,expected",
    [
        ("MCQ", 1, "B", None, None, "B", Fraction(1)),
        ("MCQ", 1, "B", None, None, "C", Fraction(-1, 3)),
        ("MCQ", 2, "B", None, None, "A", Fraction(-2, 3)),
        ("MCQ", 2, "B", None, None, None, Fraction(0)),
        ("MCQ", 2, "B", None, None, " b ", Fraction(2)),
        ("MSQ", 2, "A,C", None, None, "C,A", Fraction(2)),
        ("MSQ", 2, "A,C", None, None, "A", Fraction(0)),  # no partial marking
        ("MSQ", 2, "A,C", None, None, "A,B,C", Fraction(0)),  # no negative marking
        ("MSQ", 1, "A,C", None, None, "", Fraction(0)),
        ("NAT", 2, None, 0.49, 0.51, "0.5", Fraction(2)),
        ("NAT", 2, None, 0.49, 0.51, "0.49", Fraction(2)),  # inclusive bounds
        ("NAT", 2, None, 0.49, 0.51, "0.52", Fraction(0)),  # no negative marking
        ("NAT", 1, None, 3, 3, "3", Fraction(1)),
        ("NAT", 1, None, 3, 3, "abc", Fraction(0)),
    ],
)
def test_official_marking(qtype, marks, key, lo, hi, response, expected):
    assert score_response(qtype, marks, key, lo, hi, response).marks == expected


def test_negative_marks_table():
    assert negative_marks("MCQ", 1) == Fraction(1, 3)
    assert negative_marks("MCQ", 2) == Fraction(2, 3)
    assert negative_marks("MSQ", 2) == 0
    assert negative_marks("NAT", 1) == 0


def test_exact_totals_have_no_float_drift():
    wrongs = [score_response("MCQ", 1, "A", None, None, "B").marks for _ in range(3)]
    assert sum(wrongs) == Fraction(-1)


def test_unanswered_detection():
    assert check_response("MSQ", "A", None, None, " , ") is None
    assert check_response("NAT", None, 1, 2, "  ") is None
    assert normalize_msq("c; a ,b") == frozenset({"A", "B", "C"})


def test_invalid_marks_rejected():
    with pytest.raises(ValueError):
        score_response("MCQ", 3, "A", None, None, "A")
