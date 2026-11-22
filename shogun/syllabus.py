"""Versioned official-syllabus loading and validation.

The JSON files in ``data/syllabus`` hold the verbatim official text of every
section plus a decomposition into trackable topics. Loading enforces:

* every ``source_phrase`` / ``group`` / ``context`` is an exact substring of the
  section's ``official_text`` (nothing invented);
* every content word of the official text is covered by some topic, group or
  context phrase (nothing omitted);
* topic codes are unique and correctly prefixed.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from shogun.config import SYLLABUS_DIR

DA_FILE = SYLLABUS_DIR / "gate_da_2027.v1.json"
GA_FILE = SYLLABUS_DIR / "gate_ga_2027.v1.json"

# Function words that carry no syllabus content. Everything else must be covered.
_STOPWORDS = frozenset(
    {"and", "of", "the", "in", "such", "as", "a", "an", "to", "their", "through", "for", "s"}
)
_WORD = re.compile(r"[a-z0-9]+")


class TopicSpec(BaseModel):
    code: str
    name: str = Field(min_length=1)
    source_phrase: str = Field(min_length=1)
    group: str | None = None
    context: str | None = None


class SectionSpec(BaseModel):
    number: int
    code: str
    name: str
    official_name: str | None = None
    official_text: str
    topics: list[TopicSpec]

    @model_validator(mode="after")
    def _verbatim(self) -> SectionSpec:
        for topic in self.topics:
            if not topic.code.startswith(self.code + "."):
                raise ValueError(f"{topic.code} must start with {self.code}.")
            for label, phrase in (("source_phrase", topic.source_phrase), ("group", topic.group),
                                  ("context", topic.context)):
                if phrase is not None and phrase not in self.official_text:
                    raise ValueError(f"{topic.code} {label} {phrase!r} is not verbatim official text")
        return self


class SyllabusSpec(BaseModel):
    schema_version: int
    syllabus_version: str
    exam: str
    paper_code: Literal["DA", "GA"]
    paper_name: str
    source: dict[str, str]
    sections: list[SectionSpec]

    @model_validator(mode="after")
    def _unique_codes(self) -> SyllabusSpec:
        codes = [t.code for s in self.sections for t in s.topics] + [s.code for s in self.sections]
        if len(codes) != len(set(codes)):
            raise ValueError("Duplicate topic/section codes in syllabus")
        for section in self.sections:
            missing = uncovered_words(section)
            if missing:
                raise ValueError(f"{section.code} official words not covered by any topic: {sorted(missing)}")
        return self

    @property
    def topic_count(self) -> int:
        return sum(len(s.topics) for s in self.sections)


def _words(text: str) -> set[str]:
    return {w for w in _WORD.findall(text.lower()) if w not in _STOPWORDS}


def uncovered_words(section: SectionSpec) -> set[str]:
    covered: set[str] = set()
    for topic in section.topics:
        for phrase in (topic.source_phrase, topic.group, topic.context):
            if phrase:
                covered |= _words(phrase)
    # Connector words in the official text that structure lists rather than name topics.
    structural = {"other", "methods", "topics", "involving"}
    covered |= structural & _words(section.official_text)
    return _words(section.official_text) - covered


def load_syllabus(path: Path) -> SyllabusSpec:
    with path.open(encoding="utf-8") as fh:
        return SyllabusSpec.model_validate(json.load(fh))


def load_official_syllabi() -> list[SyllabusSpec]:
    return [load_syllabus(DA_FILE), load_syllabus(GA_FILE)]
