# PYQ / question import format

The app ships with **no** pre-loaded "real" GATE questions. Real PYQs must come from
the official GATE question papers and answer keys, and are marked **verified** only by
you, inside the app, after checking them. Nothing is ever fabricated and labelled as a
real PYQ.

Ways to add questions:

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
