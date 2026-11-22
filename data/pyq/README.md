# PYQ bank & question import format

## Bundled official bank (GATE DA 2024, 2025, 2026)

`gate_da_2024.json`, `gate_da_2025.json` and `gate_da_2026.json` are imported automatically on
first start (once per file version — deleting a question in the app does not bring it back).
They are built by `scripts/build_pyq_bank.py` from **official sources only**:

| Year | Master question paper | Answer key |
|---|---|---|
| 2024 | `gate2026.iitg.ac.in/doc/download/2024/DA24S1.pdf` (IISc paper, re-hosted by IIT Guwahati) | `gate2024.iisc.ac.in/wp-content/uploads/2024/DAFinalAnswerKey.pdf` |
| 2025 | `gate2025.iitr.ac.in/doc/2025/2025_QP/DA.pdf` | `gate2025.iitr.ac.in/doc/2025/2025_Key/DA_Keys.pdf` |
| 2026 | `gate2026.iitg.ac.in/doc/download/2026/QPs/DA.pdf` | `gate2026.iitg.ac.in/doc/download/2026/Keys/DA_Keys.pdf` |

* **Answers, question types and marks come only from the official answer keys**, parsed
  programmatically into `keys/gate_da_<year>_key.json` (with the PDFs' SHA-256 checksums).
* Question text and options were transcribed from the official master papers by Claude
  (math as LaTeX). Questions marked **MTA** (marks to all) and questions that depend on a figure
  that cannot be represented exactly as text are excluded.
* Explanations were written by Claude and are labelled **"not official"** in the app.
* Tests (`tests/unit/test_pyq_bank.py`) check every bundled question against its official key row.

Rebuild (needs the official PDFs in `var/pyq_src/<year>/`):

```bash
python scripts/build_pyq_bank.py keys     # parse official answer keys
python scripts/build_pyq_bank.py build    # merge transcriptions with official keys
```

## Adding more questions

Nothing is ever fabricated and labelled as a real PYQ. Ways to add questions:

1. **Question Bank → Add official PYQ.** Transcribe from the official paper and tick the
   verification box only if you checked the official answer key.
2. **Question Bank → Find sources (AI).** SerpAPI (DuckDuckGo engine) finds pages; Groq
   may extract candidate questions that appear *verbatim* on the page. Every candidate
   is checked against the page text and saved **unverified**.
3. **Question Bank → Import JSON.** Upload a JSON list in the format below. Imported
   questions always start **unverified**.

## JSON format

```json
[
  {
    "source_type": "official_pyq",
    "topic_codes": ["DA.2.12"],
    "exam_year": 2024,
    "exam_name": "GATE 2024 DA",
    "question_ref": "Q.27",
    "qtype": "MCQ",
    "marks": 2,
    "stem": "Question text exactly as printed in the official paper…",
    "options": ["…", "…", "…", "…"],
    "answer_key": "B",
    "explanation": "Your worked solution (optional).",
    "source_url": "https://… official question paper PDF …",
    "source_note": "Official paper, page 9"
  },
  {
    "source_type": "user_practice",
    "topic_codes": ["GA.2.05"],
    "qtype": "NAT",
    "marks": 1,
    "stem": "A self-written practice question…",
    "nat_low": 2.45,
    "nat_high": 2.55
  }
]
```

Field rules (validated on import):

| Field | Rule |
|---|---|
| `source_type` | `official_pyq`, `user_practice` or `ai_generated` |
| `topic_codes` | Official syllabus codes (see `data/syllabus/*.json`); first is the primary topic; all must be in one paper |
| `qtype` / `marks` | `MCQ`, `MSQ` or `NAT` / `1` or `2` |
| `options` + `answer_key` | MCQ/MSQ: 2–6 options; key uses letters (`"B"`, MSQ `"A,C"`) |
| `nat_low` / `nat_high` | NAT answer range, inclusive |
| official PYQs | require `exam_year`, `question_ref` and `source_url` or `source_note` |

Duplicates (same type, text and options) are skipped.
