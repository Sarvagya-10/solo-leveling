"""Build the bundled, verified GATE DA PYQ bank from OFFICIAL sources.

Pipeline (run from the project root):

1. ``python scripts/build_pyq_bank.py keys``
   Parse the official answer-key PDFs in ``var/pyq_src/<year>/DA_Keys.pdf`` into
   ``data/pyq/keys/gate_da_<year>_key.json`` (question number, type, section, key/range, marks).
2. Transcribe question text/options from the official master question paper
   ``var/pyq_src/<year>/DA.pdf`` into ``var/pyq_src/<year>/transcription.json``.
3. ``python scripts/build_pyq_bank.py build``
   Merge transcriptions with the official keys into ``data/pyq/gate_da_<year>.json``.
   Answers, question types and marks ALWAYS come from the official key — never from the
   transcription. Questions whose key is MTA (marks to all) or that depend on a figure that
   cannot be represented as text are excluded and listed in the report.

Source PDFs are not committed; their official URLs and SHA-256 checksums are recorded.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "var" / "pyq_src"
KEYS_DIR = ROOT / "data" / "pyq" / "keys"
OUT_DIR = ROOT / "data" / "pyq"

SOURCES = {
    2024: {
        "paper_url": "https://gate2026.iitg.ac.in/doc/download/2024/DA24S1.pdf",
        "paper_note": "Official GATE 2024 DA master question paper (organizing institute IISc Bengaluru), "
                      "as re-hosted on the official GATE 2026 (IIT Guwahati) site",
        "key_url": "https://gate2024.iisc.ac.in/wp-content/uploads/2024/DAFinalAnswerKey.pdf",
        "key_note": "Official GATE 2024 DA final answer key (IISc Bengaluru)",
    },
    2025: {
        "paper_url": "https://gate2025.iitr.ac.in/doc/2025/2025_QP/DA.pdf",
        "paper_note": "Official GATE 2025 DA master question paper (IIT Roorkee)",
        "key_url": "https://gate2025.iitr.ac.in/doc/2025/2025_Key/DA_Keys.pdf",
        "key_note": "Official GATE 2025 DA answer key (IIT Roorkee)",
    },
    2026: {
        "paper_url": "https://gate2026.iitg.ac.in/doc/download/2026/QPs/DA.pdf",
        "paper_note": "Official GATE 2026 DA master question paper (IIT Guwahati)",
        "key_url": "https://gate2026.iitg.ac.in/doc/download/2026/Keys/DA_Keys.pdf",
        "key_note": "Official GATE 2026 DA answer key (IIT Guwahati)",
    },
}
_NUM = re.compile(r"^-?\d+(\.\d+)?$")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parse_key_text(text: str, expected: int = 65) -> list[dict]:
    """Parse an official answer-key PDF's text into rows. Robust to page headers/line breaks."""
    tokens = text.replace(" ", " ").split()
    rows: list[dict] = []
    i = 0
    qno = 1
    while qno <= expected:
        found = False
        while i + 4 < len(tokens):
            if (tokens[i] == str(qno) and tokens[i + 1].isdigit() and tokens[i + 2] in ("MCQ", "MSQ", "NAT")
                    and tokens[i + 3] in ("GA", "DA")):
                found = True
                break
            i += 1
        if not found:
            raise ValueError(f"Could not find answer-key row for Q.{qno}")
        qtype, section = tokens[i + 2], tokens[i + 3]
        j = i + 4
        if tokens[j].upper() == "MTA":
            key, low, high = "MTA", None, None
            j += 1
        elif qtype == "NAT":
            if not (_NUM.match(tokens[j]) and tokens[j + 1].lower() == "to" and _NUM.match(tokens[j + 2])):
                raise ValueError(f"Q.{qno}: unexpected NAT range tokens {tokens[j:j + 3]}")
            low, high = float(tokens[j]), float(tokens[j + 2])
            key = f"{tokens[j]} to {tokens[j + 2]}"
            j += 3
        else:
            key, low, high = tokens[j].upper(), None, None
            if not re.fullmatch(r"[A-D](;[A-D])*", key):
                raise ValueError(f"Q.{qno}: unexpected key {key!r}")
            j += 1
        marks = int(tokens[j])
        if marks not in (1, 2):
            raise ValueError(f"Q.{qno}: unexpected marks {tokens[j]!r}")
        rows.append({"qno": qno, "qtype": qtype, "section": section, "key": key, "nat_low": low,
                     "nat_high": high, "marks": marks})
        i = j + 1
        qno += 1
    ga = [r for r in rows if r["section"] == "GA"]
    da = [r for r in rows if r["section"] == "DA"]
    assert len(ga) == 10 and sum(r["marks"] for r in ga) == 15, "GA must be 10 questions / 15 marks"
    assert len(da) == 55 and sum(r["marks"] for r in da) == 85, "DA must be 55 questions / 85 marks"
    return rows


def cmd_keys() -> None:
    from pypdf import PdfReader

    KEYS_DIR.mkdir(parents=True, exist_ok=True)
    for year, meta in SOURCES.items():
        pdf = SRC / str(year) / "DA_Keys.pdf"
        text = "\n".join(page.extract_text() or "" for page in PdfReader(str(pdf)).pages)
        rows = parse_key_text(text)
        out = {
            "exam": f"GATE {year}", "paper": "DA", "source_url": meta["key_url"], "source_note": meta["key_note"],
            "sha256": sha256(pdf), "paper_url": meta["paper_url"],
            "paper_sha256": sha256(SRC / str(year) / "DA.pdf"), "rows": rows,
        }
        path = KEYS_DIR / f"gate_da_{year}_key.json"
        path.write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
        mta = [r["qno"] for r in rows if r["key"] == "MTA"]
        print(f"{year}: {len(rows)} rows -> {path.relative_to(ROOT)} (MTA: {mta or 'none'})")


def _answer_fields(row: dict) -> dict:
    if row["qtype"] == "NAT":
        return {"answer_key": None, "nat_low": row["nat_low"], "nat_high": row["nat_high"]}
    return {"answer_key": row["key"].replace(";", ","), "nat_low": None, "nat_high": None}


def build_year(year: int) -> dict:
    key = json.loads((KEYS_DIR / f"gate_da_{year}_key.json").read_text(encoding="utf-8"))
    rows = {r["qno"]: r for r in key["rows"]}
    trans_path = SRC / str(year) / "transcription.json"
    items = json.loads(trans_path.read_text(encoding="utf-8"))
    meta = SOURCES[year]
    out, skipped = [], []
    seen: set[int] = set()
    for it in items:
        qno = int(it["qno"])
        if qno in seen:
            raise ValueError(f"{year} Q.{qno} transcribed twice")
        seen.add(qno)
        row = rows[qno]
        if row["key"] == "MTA":
            skipped.append((qno, "official key: MTA (marks to all) — no valid answer"))
            continue
        if it.get("skip"):
            skipped.append((qno, it.get("skip_reason", "not representable as text")))
            continue
        options = [o.strip() for o in it.get("options", []) if str(o).strip()]
        if row["qtype"] in ("MCQ", "MSQ") and len(options) != 4:
            raise ValueError(f"{year} Q.{qno}: expected 4 options, got {len(options)}")
        if row["qtype"] == "NAT":
            options = []
        expected_section = "GA" if row["section"] == "GA" else "DA"
        codes = [c for c in it["topic_codes"]]
        if not codes or not all(c.startswith(expected_section + ".") for c in codes):
            raise ValueError(f"{year} Q.{qno}: topic codes {codes} do not match section {row['section']}")
        out.append({
            "source_type": "official_pyq",
            "verification_status": "verified",
            "topic_codes": codes,
            "exam_year": year,
            "exam_name": f"GATE {year} DA",
            "question_ref": f"Q.{qno}",
            "qtype": row["qtype"],
            "marks": row["marks"],
            "stem": it["stem"].strip(),
            "options": options,
            **_answer_fields(row),
            "explanation": (it.get("explanation") or "").strip() or None,
            "explanation_source": "ai_authored" if (it.get("explanation") or "").strip() else None,
            "source_url": meta["paper_url"],
            "source_note": (f"{meta['paper_note']}, Q.{qno} (paper sha256 {key['paper_sha256'][:12]}…). "
                            f"Answer/type/marks from the {meta['key_note']} ({meta['key_url']}). "
                            "Question text transcribed by Claude from the official PDF; explanation written by "
                            "Claude, not official."),
        })
    missing = sorted(set(rows) - seen)
    if missing:
        raise ValueError(f"{year}: questions not transcribed or explicitly skipped: {missing}")
    path = OUT_DIR / f"gate_da_{year}.json"
    path.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return {"year": year, "included": len(out), "skipped": skipped, "path": str(path.relative_to(ROOT))}


def cmd_build(years: list[int]) -> None:
    for year in years:
        report = build_year(year)
        print(f"{year}: {report['included']} questions -> {report['path']}")
        for qno, why in report["skipped"]:
            print(f"   skipped Q.{qno}: {why}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "keys":
        cmd_keys()
    elif cmd == "build":
        cmd_build([int(y) for y in sys.argv[2:]] or sorted(SOURCES))
    else:
        raise SystemExit("usage: build_pyq_bank.py keys | build [year ...]")
