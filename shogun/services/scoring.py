"""Official GATE scoring rules (pure functions, exact arithmetic).

Source: https://gate2027.iitm.ac.in/question_paper_pattern

* MCQ: correct → +marks; wrong → −1/3 (1-mark) or −2/3 (2-mark); unanswered → 0.
* MSQ: credit only if the selected set exactly equals the key; no partial
  marking; no negative marking.
* NAT: credit if the value lies within the inclusive key range; no negative marking.

Arithmetic uses :class:`fractions.Fraction` so totals such as ``-1/3 - 2/3``
are exact; values are rounded only for display.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from fractions import Fraction

QTYPES = ("MCQ", "MSQ", "NAT")
OPTION_KEYS = ("A", "B", "C", "D", "E", "F")


@dataclass(frozen=True)
class ScoredResponse:
    answered: bool
    is_correct: bool | None  # None when unanswered
    marks: Fraction

    @property
    def marks_float(self) -> float:
        return float(self.marks)


def normalize_msq(value: str | None) -> frozenset[str]:
    if not value:
        return frozenset()
    return frozenset(p.strip().upper() for p in value.replace(";", ",").split(",") if p.strip())


def encode_msq(keys: list[str] | set[str] | frozenset[str]) -> str:
    return ",".join(sorted(k.strip().upper() for k in keys if k.strip()))


def parse_nat(value: str | None) -> float | None:
    if value is None or not str(value).strip():
        return None
    try:
        number = float(str(value).strip())
    except ValueError:
        return None
    return number if math.isfinite(number) else None


def is_answered(qtype: str, response: str | None) -> bool:
    if qtype == "MSQ":
        return bool(normalize_msq(response))
    if qtype == "NAT":
        return parse_nat(response) is not None
    return bool(response and response.strip())


def check_response(
    qtype: str, answer_key: str | None, nat_low: float | None, nat_high: float | None, response: str | None
) -> bool | None:
    """True/False for an answered question, None if unanswered."""
    if qtype not in QTYPES:
        raise ValueError(f"Unknown question type {qtype!r}")
    if not is_answered(qtype, response):
        return None
    if qtype == "MCQ":
        return (response or "").strip().upper() == (answer_key or "").strip().upper()
    if qtype == "MSQ":
        return normalize_msq(response) == normalize_msq(answer_key)
    value = parse_nat(response)
    if value is None or nat_low is None or nat_high is None:
        return False
    lo, hi = min(nat_low, nat_high), max(nat_low, nat_high)
    eps = 1e-9 * max(1.0, abs(lo), abs(hi))
    return lo - eps <= value <= hi + eps


def negative_marks(qtype: str, marks: int) -> Fraction:
    """Marks deducted for a wrong answer (as a positive number)."""
    if qtype == "MCQ":
        return Fraction(marks, 3)
    return Fraction(0)


def score_response(
    qtype: str, marks: int, answer_key: str | None, nat_low: float | None, nat_high: float | None,
    response: str | None,
) -> ScoredResponse:
    if marks not in (1, 2):
        raise ValueError("GATE questions carry 1 or 2 marks")
    verdict = check_response(qtype, answer_key, nat_low, nat_high, response)
    if verdict is None:
        return ScoredResponse(answered=False, is_correct=None, marks=Fraction(0))
    if verdict:
        return ScoredResponse(answered=True, is_correct=True, marks=Fraction(marks))
    return ScoredResponse(answered=True, is_correct=False, marks=-negative_marks(qtype, marks))


def round_marks(value: Fraction | float) -> float:
    return round(float(value), 2)
