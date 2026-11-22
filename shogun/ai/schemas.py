"""Pydantic schemas for structured LLM output."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

LETTERS = ("A", "B", "C", "D", "E", "F")


class FormulaItem(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    expression: str = Field(min_length=1, max_length=600)
    note: str | None = Field(default=None, max_length=600)


class QuestionTypeItem(BaseModel):
    type: str = Field(min_length=1, max_length=200)
    recognition: str = Field(min_length=1, max_length=800)


class PracticeQuestionDraft(BaseModel):
    qtype: Literal["MCQ", "MSQ", "NAT"]
    marks: Literal[1, 2]
    stem: str = Field(min_length=10, max_length=4000)
    options: list[str] = Field(default_factory=list, max_length=6)
    answer_key: str | None = None
    nat_low: float | None = None
    nat_high: float | None = None
    explanation: str = Field(min_length=5, max_length=4000)

    @field_validator("answer_key")
    @classmethod
    def _upper(cls, v: str | None) -> str | None:
        return v.strip().upper().replace(" ", "") if v else v

    @model_validator(mode="after")
    def _consistent(self) -> PracticeQuestionDraft:
        if self.qtype in ("MCQ", "MSQ"):
            if len(self.options) < 2:
                raise ValueError("MCQ/MSQ need options")
            valid = set(LETTERS[: len(self.options)])
            keys = {k for k in (self.answer_key or "").split(",") if k}
            if not keys or not keys <= valid:
                raise ValueError("answer_key must use option letters")
            if self.qtype == "MCQ" and len(keys) != 1:
                raise ValueError("MCQ needs exactly one answer")
        else:
            if self.nat_low is None or self.nat_high is None:
                raise ValueError("NAT needs nat_low and nat_high")
            if self.nat_low > self.nat_high:
                self.nat_low, self.nat_high = self.nat_high, self.nat_low
            self.options = []
            self.answer_key = None
        return self


class RevisionCardDraft(BaseModel):
    basic_idea: str = Field(min_length=20, max_length=4000)
    essential_formulae: list[FormulaItem] = Field(default_factory=list, max_length=20)
    question_types: list[QuestionTypeItem] = Field(default_factory=list, max_length=15)
    common_traps: list[str] = Field(default_factory=list, max_length=15)
    extra_observations: list[str] = Field(default_factory=list, max_length=15)
    connected_topic_codes: list[str] = Field(default_factory=list, max_length=15)
    practice_questions: list[PracticeQuestionDraft] = Field(default_factory=list, max_length=3)


class PracticeSet(BaseModel):
    questions: list[PracticeQuestionDraft] = Field(min_length=1, max_length=10)


class PYQCandidate(BaseModel):
    exam_year: int = Field(ge=2000, le=2100)
    question_ref: str = Field(min_length=1, max_length=40)
    qtype: Literal["MCQ", "MSQ", "NAT"]
    marks: Literal[1, 2]
    stem: str = Field(min_length=10, max_length=4000)
    options: list[str] = Field(default_factory=list, max_length=6)
    answer_key: str | None = None
    nat_low: float | None = None
    nat_high: float | None = None
    explanation: str | None = Field(default=None, max_length=4000)
    evidence: str = Field(min_length=10, max_length=1200, description="Verbatim excerpt from the source page")


class PYQCandidateList(BaseModel):
    candidates: list[PYQCandidate] = Field(default_factory=list, max_length=10)


class ReflectionAdvice(BaseModel):
    observations: list[str] = Field(default_factory=list, max_length=5)
    next_smallest_step: str = Field(min_length=3, max_length=600)
    encouragement: str = Field(min_length=3, max_length=600)
