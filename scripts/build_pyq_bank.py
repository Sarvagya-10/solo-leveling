"""Build the bundled, verified GATE PYQ bank from OFFICIAL sources.

Bundles: GATE DA 2024-2026 (all syllabus areas) and GATE CS 2020-2026 restricted to the
areas shared with the DA 2027 syllabus — General Aptitude, Probability & Statistics,
Linear Algebra, Calculus & Optimization, Database Management & Warehousing. CS questions
on AI, ML, Programming/DSA or topics outside the DA syllabus are excluded.

Pipeline (run from the project root; official PDFs live in git-ignored ``var/pyq_src/<bundle>/``):

1. ``python scripts/build_pyq_bank.py keys``
   Parse official answer keys into ``data/pyq/keys/gate_<bundle>_key.json``. Image-only keys
   (GATE 2021 CS) are read from a visual transcription ``key_transcribed.json`` instead.
2. Transcribe in-scope question text into ``var/pyq_src/<bundle>/transcription.json``.
3. ``python scripts/build_pyq_bank.py build [bundle ...]``
   Merge with the keys into ``data/pyq/gate_<bundle>.json``. Answers, question types and marks
   ALWAYS come from the official key. MTA questions, keys with alternative answers, figure-only
   questions, out-of-scope questions and duplicates of earlier bundles are excluded and reported.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SRC = ROOT / "var" / "pyq_src"
KEYS_DIR = ROOT / "data" / "pyq" / "keys"
OUT_DIR = ROOT / "data" / "pyq"
IITG = "https://gate2026.iitg.ac.in/doc/download"
IITR = "https://gate2025.iitr.ac.in/doc/2025"
CS_SCOPE = ("GA.", "DA.1.", "DA.2.", "DA.3.", "DA.5.")
DA_SCOPE = ("GA.", "DA.")


def _cs(year: int, set_no: int | None, paper_url: str, key_url: str, institute: str, *, src: str | None = None,
        key_in_paper: bool = False, key_visual: bool = False) -> dict:
    set_txt = f" (Set {set_no})" if set_no else ""
    return {
        "paper": "CS", "year": year, "set": set_no, "src": src or (f"cs_{year}" + (f"_{set_no}" if set_no else "")),
        "paper_file": "CS.pdf", "key_file": "CS.pdf" if key_in_paper else "CS_Keys.pdf", "key_visual": key_visual,
        "exam_name": f"GATE {year} CS{set_txt}", "scope": CS_SCOPE, "paper_url": paper_url, "key_url": key_url,
        "paper_note": f"Official GATE {year} CS{set_txt} master question paper ({institute})",
        "key_note": f"Official GATE {year} CS{set_txt} answer key ({institute})",
    }


BUNDLES: dict[str, dict] = {
    "da_2024": {
        "paper": "DA", "year": 2024, "set": None, "src": "2024", "paper_file": "DA.pdf", "key_file": "DA_Keys.pdf",
        "key_visual": False, "exam_name": "GATE 2024 DA", "scope": DA_SCOPE,
        "paper_url": f"{IITG}/2024/DA24S1.pdf",
        "paper_note": "Official GATE 2024 DA master question paper (organizing institute IISc Bengaluru), "
                      "as re-hosted on the official GATE 2026 (IIT Guwahati) site",
        "key_url": "https://gate2024.iisc.ac.in/wp-content/uploads/2024/DAFinalAnswerKey.pdf",
        "key_note": "Official GATE 2024 DA final answer key (IISc Bengaluru)",
    },
    "da_2025": {
        "paper": "DA", "year": 2025, "set": None, "src": "2025", "paper_file": "DA.pdf", "key_file": "DA_Keys.pdf",
        "key_visual": False, "exam_name": "GATE 2025 DA", "scope": DA_SCOPE,
        "paper_url": f"{IITR}/2025_QP/DA.pdf", "paper_note": "Official GATE 2025 DA master question paper (IIT Roorkee)",
        "key_url": f"{IITR}/2025_Key/DA_Keys.pdf", "key_note": "Official GATE 2025 DA answer key (IIT Roorkee)",
    },
    "da_2026": {
        "paper": "DA", "year": 2026, "set": None, "src": "2026", "paper_file": "DA.pdf", "key_file": "DA_Keys.pdf",
        "key_visual": False, "exam_name": "GATE 2026 DA", "scope": DA_SCOPE,
        "paper_url": f"{IITG}/2026/QPs/DA.pdf",
        "paper_note": "Official GATE 2026 DA master question paper (IIT Guwahati)",
        "key_url": f"{IITG}/2026/Keys/DA_Keys.pdf", "key_note": "Official GATE 2026 DA answer key (IIT Guwahati)",
    },
    "cs_2020": _cs(2020, None, f"{IITG}/2020/cs_2020.pdf", f"{IITG}/2020/cs_2020.pdf",
                   "IIT Delhi; answer key appended in the same official PDF; archived on the GATE 2026 site",
                   key_in_paper=True),
    "cs_2021_1": _cs(2021, 1, f"{IITG}/2021/cs_2021.pdf", f"{IITG}/Answer_keys2021/cs_merged_2021.pdf",
                     "IIT Bombay; archived on the GATE 2026 site", src="cs_2021", key_visual=True),
    "cs_2021_2": _cs(2021, 2, f"{IITG}/2021/cs_2021.pdf", f"{IITG}/Answer_keys2021/cs_merged_2021.pdf",
                     "IIT Bombay; archived on the GATE 2026 site", src="cs_2021", key_visual=True),
    "cs_2022": _cs(2022, None, f"{IITG}/2022/cs_2022.pdf", f"{IITG}/Answer_keys2022/cs_2022.pdf",
                   "IIT Kharagpur; archived on the GATE 2026 site"),
    "cs_2023": _cs(2023, None, f"{IITG}/2023/cs_2023.pdf", f"{IITG}/Answer_keys2023/CS_ANS_GATE2023.pdf",
                   "IIT Kanpur; archived on the GATE 2026 site"),
    "cs_2024_1": _cs(2024, 1, f"{IITG}/2024/CS124S5.pdf", f"{IITG}/2024/CS1FinalAnswerKey.pdf",
                     "IISc Bengaluru; archived on the GATE 2026 site"),
    "cs_2024_2": _cs(2024, 2, f"{IITG}/2024/CS224S6.pdf", f"{IITG}/2024/CS2FinalAnswerKey.pdf",
                     "IISc Bengaluru; archived on the GATE 2026 site"),
    "cs_2025_1": _cs(2025, 1, f"{IITR}/2025_QP/CS1.pdf", f"{IITR}/2025_Key/CS1_Keys.pdf", "IIT Roorkee"),
    "cs_2025_2": _cs(2025, 2, f"{IITR}/2025_QP/CS2.pdf", f"{IITR}/2025_Key/CS2_Keys.pdf", "IIT Roorkee"),
    "cs_2026_1": _cs(2026, 1, f"{IITG}/2026/QPs/CS1.pdf", f"{IITG}/2026/Keys/CS1_Keys.pdf", "IIT Guwahati"),
    "cs_2026_2": _cs(2026, 2, f"{IITG}/2026/QPs/CS2.pdf", f"{IITG}/2026/Keys/CS2_Keys.pdf", "IIT Guwahati"),
}
ORDER = list(BUNDLES)  # DA first, then CS chronologically — earlier bundles win duplicates

_NUM = r"-?\d+(?:\.\d+)?"
_LETTERS = re.compile(r"^[A-D](?:[;,][A-D])*[;,]?$")
_QTYPES = ("MCQ", "MSQ", "NAT")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _row_start(toks: list[str], i: int) -> bool:
    return (i + 4 < len(toks) and re.fullmatch(r"\d{1,2}", toks[i]) is not None and toks[i + 1].isdigit()
            and toks[i + 2] in _QTYPES and re.fullmatch(r"[A-Z]{2,3}(?:-?[12])?", toks[i + 3]) is not None)


def parse_key_text(text: str, expected: int = 65) -> list[dict]:
    """Parse an official answer-key text into rows (robust to headers, line breaks, numbering style)."""
    toks = text.replace(" ", " ").replace("–", "-").replace("−", "-").split()
    rows: list[dict] = []
    i = 0
    while len(rows) < expected:
        while i < len(toks) and not _row_start(toks, i):
            i += 1
        if i >= len(toks):
            raise ValueError(f"Only {len(rows)} answer-key rows found")
        qno, qtype, section = int(toks[i]), toks[i + 2], toks[i + 3]
        j = i + 4
        alternatives = False
        if toks[j].upper() == "MTA":
            key, low, high = "MTA", None, None
            j += 1
        elif qtype == "NAT":
            if not (re.fullmatch(_NUM, toks[j]) and toks[j + 1].lower() == "to" and re.fullmatch(_NUM, toks[j + 2])):
                raise ValueError(f"{section} Q.{qno}: unexpected NAT range tokens {toks[j:j + 3]}")
            low, high = float(toks[j]), float(toks[j + 2])
            key = f"{toks[j]} to {toks[j + 2]}"
            j += 3
            while j < len(toks) and toks[j].upper() == "OR":  # alternative accepted range
                alternatives = True
                key += f" OR {toks[j + 1]} to {toks[j + 3]}"
                j += 4
        else:
            parts = []
            while j < len(toks) and (_LETTERS.match(toks[j]) or toks[j].upper() == "OR"):
                if toks[j].upper() == "OR":
                    alternatives = True
                    parts.append(" OR ")
                else:
                    parts.append(toks[j])
                j += 1
            key = re.sub(r"[;,]+", ";", "".join(parts)).strip(";")
            low = high = None
            if not key:
                raise ValueError(f"{section} Q.{qno}: missing key")
        if toks[j] not in ("1", "2"):
            raise ValueError(f"{section} Q.{qno}: unexpected marks token {toks[j]!r}")
        rows.append({"qno": qno, "qtype": qtype, "section": section, "key": key, "nat_low": low,
                     "nat_high": high, "marks": int(toks[j]), "alternatives": alternatives})
        i = j + 1
    return finalize_rows(rows)


def finalize_rows(rows: list[dict]) -> list[dict]:
    ga = [r for r in rows if r["section"] == "GA"]
    sub = [r for r in rows if r["section"] != "GA"]
    assert len(rows) == 65, f"expected 65 rows, got {len(rows)}"
    assert (len(ga), sum(r["marks"] for r in ga)) == (10, 15), "GA must be 10 questions / 15 marks"
    assert (len(sub), sum(r["marks"] for r in sub)) == (55, 85), "Subject must be 55 questions / 85 marks"
    continuous = [r["qno"] for r in rows] == list(range(1, 66))
    sectioned = [r["qno"] for r in ga] == list(range(1, 11)) and [r["qno"] for r in sub] == list(range(1, 56))
    assert continuous or sectioned, "unexpected question numbering"
    for idx, r in enumerate(rows, start=1):
        r["index"] = idx
        r["ref"] = f"Q.{r['qno']}" if continuous else f"{r['section']} Q.{r['qno']}"
    return rows


def cmd_keys(only: list[str]) -> None:
    from pypdf import PdfReader

    KEYS_DIR.mkdir(parents=True, exist_ok=True)
    for bid in only or ORDER:
        meta = BUNDLES[bid]
        src = SRC / meta["src"]
        key_pdf = src / meta["key_file"]
        if not key_pdf.exists():
            print(f"{bid}: key PDF missing — skipped")
            continue
        if meta["key_visual"]:
            vis = src / f"key_transcribed_set{meta['set']}.json"
            if not vis.exists():
                print(f"{bid}: image-only key; waiting for {vis.relative_to(ROOT)}")
                continue
            raw = json.loads(vis.read_text(encoding="utf-8"))
            rows = finalize_rows([{**r, "alternatives": " OR " in str(r["key"])} for r in raw])
            method = "visually transcribed from the official key image"
        else:
            text = "\n".join(page.extract_text() or "" for page in PdfReader(str(key_pdf)).pages)
            rows = parse_key_text(text)
            method = "parsed from the official key PDF text"
        out = {"exam": meta["exam_name"], "paper": meta["paper"], "source_url": meta["key_url"],
               "source_note": meta["key_note"], "sha256": sha256(key_pdf), "paper_url": meta["paper_url"],
               "paper_sha256": sha256(src / meta["paper_file"]), "method": method, "rows": rows}
        path = KEYS_DIR / f"gate_{bid}_key.json"
        path.write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
        flagged = [r["ref"] for r in rows if r["key"] == "MTA" or r["alternatives"]]
        print(f"{bid}: 65 rows -> {path.relative_to(ROOT)} (MTA/alternatives: {flagged or 'none'})")


def _content_hash(qtype: str, stem: str, options: list[str]) -> str:
    from shogun.services.question_service import content_hash

    return content_hash(qtype, stem, options)


def _answer_fields(row: dict) -> dict:
    if row["qtype"] == "NAT":
        return {"answer_key": None, "nat_low": row["nat_low"], "nat_high": row["nat_high"]}
    return {"answer_key": row["key"].replace(";", ","), "nat_low": None, "nat_high": None}


def _earlier_hashes(bid: str) -> dict[str, str]:
    seen: dict[str, str] = {}
    for other in ORDER[: ORDER.index(bid)]:
        path = OUT_DIR / f"gate_{other}.json"
        if path.exists():
            for q in json.loads(path.read_text(encoding="utf-8")):
                seen[_content_hash(q["qtype"], q["stem"], q["options"])] = f"{q['exam_name']} {q['question_ref']}"
    return seen


def build_bundle(bid: str) -> dict:
    meta = BUNDLES[bid]
    key = json.loads((KEYS_DIR / f"gate_{bid}_key.json").read_text(encoding="utf-8"))
    rows = {r["ref"]: r for r in key["rows"]}
    trans_name = "transcription.json" if not meta["set"] or meta["src"] == bid else f"transcription_set{meta['set']}.json"
    items = json.loads((SRC / meta["src"] / trans_name).read_text(encoding="utf-8"))
    earlier = _earlier_hashes(bid)
    out, skipped, seen = [], [], set()
    for it in items:
        ref = it.get("ref") or f"Q.{int(it['qno'])}"
        if ref not in rows:
            raise ValueError(f"{bid}: transcription ref {ref!r} is not in the official key")
        if ref in seen:
            raise ValueError(f"{bid}: {ref} transcribed twice")
        seen.add(ref)
        row = rows[ref]
        if row["key"] == "MTA":
            skipped.append((ref, "official key: MTA (marks to all) — no valid answer"))
            continue
        if row["alternatives"]:
            skipped.append((ref, f"official key accepts alternative answers ({row['key']})"))
            continue
        if it.get("skip"):
            skipped.append((ref, it.get("skip_reason") or "not representable as text"))
            continue
        options = [str(o).strip() for o in it.get("options", []) if str(o).strip()]
        if row["qtype"] in ("MCQ", "MSQ") and len(options) != 4:
            raise ValueError(f"{bid} {ref}: expected 4 options, got {len(options)}")
        if row["qtype"] == "NAT":
            options = []
        codes = list(it["topic_codes"])
        section_prefix = "GA." if row["section"] == "GA" else "DA."
        if not codes or not all(c.startswith(section_prefix) for c in codes):
            raise ValueError(f"{bid} {ref}: topic codes {codes} do not match section {row['section']}")
        if not all(c.startswith(meta["scope"]) for c in codes):
            raise ValueError(f"{bid} {ref}: topic codes {codes} are outside this bundle's scope {meta['scope']}")
        stem = it["stem"].strip()
        digest = _content_hash(row["qtype"], stem, options)
        if digest in earlier:
            skipped.append((ref, f"duplicate of {earlier[digest]} (same question in an earlier bundle)"))
            continue
        explanation = (it.get("explanation") or "").strip()
        concern = (it.get("key_concern") or "").strip()
        if concern:  # keep the official answer, but be transparent about a debatable key
            explanation += f"\n\n**Note on the official key:** {concern}"
        out.append({
            "source_type": "official_pyq",
            "verification_status": "verified",
            "topic_codes": codes,
            "exam_year": meta["year"],
            "exam_name": meta["exam_name"],
            "question_ref": ref,
            "key_row": row["index"],
            "qtype": row["qtype"],
            "marks": row["marks"],
            "stem": stem,
            "options": options,
            **_answer_fields(row),
            "explanation": explanation or None,
            "explanation_source": "ai_authored" if explanation else None,
            "source_url": meta["paper_url"],
            "source_note": (f"{meta['paper_note']}, {ref} (paper sha256 {key['paper_sha256'][:12]}…). "
                            f"Answer/type/marks from the {meta['key_note']} ({meta['key_url']}; "
                            f"{key['method']}). Question text transcribed by Claude from the official PDF; "
                            "explanation written by Claude, not official."),
        })
    missing = sorted(set(rows) - seen, key=lambda r: rows[r]["index"])
    if missing:
        raise ValueError(f"{bid}: questions neither transcribed nor explicitly skipped: {missing}")
    path = OUT_DIR / f"gate_{bid}.json"
    path.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return {"bundle": bid, "included": len(out), "skipped": skipped, "path": str(path.relative_to(ROOT))}


def cmd_build(only: list[str], verbose: bool) -> None:
    for bid in only or ORDER:
        meta = BUNDLES[bid]
        trans = SRC / meta["src"] / ("transcription.json" if not meta["set"] or meta["src"] == bid
                                     else f"transcription_set{meta['set']}.json")
        if not trans.exists():
            print(f"{bid}: no transcription yet — skipped")
            continue
        report = build_bundle(bid)
        print(f"{bid}: {report['included']} questions -> {report['path']}")
        for ref, why in report["skipped"]:
            if verbose or not why.startswith("Out of scope"):
                print(f"   skipped {ref}: {why}")


if __name__ == "__main__":
    args = sys.argv[1:]
    verbose = "-v" in args
    args = [a for a in args if a != "-v"]
    cmd = args[0] if args else ""
    unknown = [a for a in args[1:] if a not in BUNDLES]
    if unknown:
        raise SystemExit(f"unknown bundle(s): {unknown}; known: {ORDER}")
    if cmd == "keys":
        cmd_keys(args[1:])
    elif cmd == "build":
        cmd_build(args[1:], verbose)
    else:
        raise SystemExit("usage: build_pyq_bank.py keys [bundle ...] | build [-v] [bundle ...]")
