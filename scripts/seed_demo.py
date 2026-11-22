"""Populate a SEPARATE database with clearly fake demo data (for screenshots / exploring).

Usage:
    python scripts/seed_demo.py --db var/demo.db
    SHOGUN_DB_PATH=var/demo.db streamlit run app.py

Refuses to touch a database that already contains study logs unless --force.
Demo questions are labelled "user-authored practice" — never official PYQs.
"""

from __future__ import annotations

import argparse
import random
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import func, select  # noqa: E402

from shogun.db.models import Habit, StudyLog, Topic  # noqa: E402
from shogun.db.session import get_engine, run_migrations, session_scope  # noqa: E402
from shogun.services import (  # noqa: E402
    attention_service,
    avoidance_service,
    gamification_service,
    habit_service,
    question_service,
    reflection_service,
    revision_service,
    settings_service,
    study_log_service,
    worklog_service,
)
from shogun.services.errors import ConflictError  # noqa: E402
from shogun.services.question_service import QuestionInput  # noqa: E402
from shogun.services.seed import seed_all  # noqa: E402
from shogun.services.study_log_service import StudyEntryInput  # noqa: E402
from shogun.services.worklog_service import WorkLogInput  # noqa: E402
from shogun.timeutil import local_today  # noqa: E402

TZ = "Asia/Kolkata"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, help="Path of the demo database to create/populate")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    url = f"sqlite:///{Path(args.db).resolve().as_posix()}"
    run_migrations(url)
    engine = get_engine(url)
    rng = random.Random(2027)
    today = local_today(TZ)
    start = today - timedelta(days=20)
    with session_scope(engine) as s:
        if s.scalar(select(func.count(StudyLog.id))) and not args.force:
            raise SystemExit("Database already has study logs; refusing (use --force on a demo DB only).")
        seed_all(s, start)
        settings_service.set_setting(s, "tracking_start_date", start.isoformat())
        topics = list(s.scalars(select(Topic).where(Topic.code.like("DA.%")).order_by(Topic.id)))[:40]
        ga_topics = list(s.scalars(select(Topic).where(Topic.code.like("GA.%")).order_by(Topic.id)))[:8]
        habits = list(s.scalars(select(Habit)))
        rules = avoidance_service.list_rules(s)
        for i in range(21):
            day = start + timedelta(days=i)
            if rng.random() < 0.85:
                chosen = rng.sample(topics, 2) + ([rng.choice(ga_topics)] if rng.random() < 0.4 else [])
                entries = []
                for t in chosen:
                    att = rng.randint(0, 8)
                    entries.append(StudyEntryInput(t.id, rng.choice([45, 60, 75, 90, 120]), att, rng.randint(0, att),
                                                   rng.choice(["in_progress", "mastered", "mastered"])))
                study_log_service.log_study(s, day, entries, today=today)
            for ev in revision_service.due_today(s, day):
                if rng.random() < 0.75:
                    try:  # the service enforces stage order; skip ones whose earlier stage was missed
                        with s.begin_nested():
                            revision_service.complete_revision(s, ev.id, day, minutes=20,
                                                               confidence=rng.randint(2, 5))
                    except ConflictError:
                        pass
            for h in habits:
                if rng.random() < 0.85:
                    val = (rng.choice([1.5, 2.5, 3.0, 3.5]) if h.key == "water" else
                           (rng.choice([0, 20, 30, 45]) if h.kind == "numeric" else float(rng.random() < 0.8)))
                    habit_service.upsert_entry(s, h.id, day, val, None, today=today)
            for r in rules:
                if rng.random() < 0.8:
                    avoidance_service.set_status(s, r.id, day, "complied" if rng.random() < 0.85 else "violated",
                                                 None, today=today)
            if rng.random() < 0.8:
                attention_service.add_session(s, day, min(200, 5 + i * 3 + rng.randint(0, 15)), None, today=today)
            for domain in ("finance", "research"):
                if rng.random() < 0.7:
                    worklog_service.add_log(s, WorkLogInput(domain, day, rng.choice([30, 45, 60, 75]),
                                                            f"Demo {domain} session {i}", project_name="Demo project"),
                                            today=today)
            if rng.random() < 0.6:
                reflection_service.upsert(s, day, "Demo: focused morning block", "Demo: late start",
                                          "Demo: phone in another room", today=today)
        for i, t in enumerate(topics[:12]):
            question_service.add_question(s, QuestionInput(
                topic_codes=[t.code], source_type="user_practice", qtype=["MCQ", "MSQ", "NAT"][i % 3],
                marks=1 + i % 2, stem=f"[DEMO] Practice question {i + 1} on {t.name}. Which option is correct?",
                options=["Option one", "Option two", "Option three", "Option four"] if i % 3 != 2 else [],
                answer_key=["A", "A,C", None][i % 3], nat_low=2.0 if i % 3 == 2 else None,
                nat_high=2.5 if i % 3 == 2 else None, explanation="Demo explanation."))
        gamification_service.sync_all(s, TZ, today)
        gamification_service.evaluate_achievements(s, today, TZ)
    print(f"Demo data written to {args.db}")


if __name__ == "__main__":
    main()
