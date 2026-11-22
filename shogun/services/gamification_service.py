"""SYSTEM gamification: fixed XP rules, levels, ranks, quests, streaks, badges.

Guarantees
----------
* **Transparent & fixed** — every rule is listed in :data:`XP_RULES`; no randomness.
* **No double counting** — every XP event has a unique ``source_key``.
* **No XP for false completions** — XP is *derived* from source data: the
  ledger for a day is recomputed (``sync_day``) after every change, so
  deleting a log or undoing a revision removes its XP.
* **Read-only towards academic data** — this module never writes progress,
  logs or revisions.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from shogun.db.models import (
    Achievement,
    AttentionSession,
    HabitEntry,
    MockExam,
    Reflection,
    RevisionEvent,
    StudyLog,
    Subject,
    Topic,
    TopicProgress,
    UserAchievement,
    WorkLog,
    XPEvent,
)
from shogun.services import habit_service, settings_service, worklog_service
from shogun.timeutil import local_date_of

XP_RULES: dict[str, tuple[int, str]] = {
    "study_topic": (10, "10 XP per distinct topic studied on a day (minutes or PYQs logged)"),
    "study_time": (5, "5 XP per full 30 minutes of GATE study in a day (max 80 XP/day)"),
    "pyq_correct": (1, "1 XP per correctly solved PYQ in the daily log (max 50 XP/day)"),
    "revision": (15, "15 XP per scheduled revision completed"),
    "habit": (5, "5 XP per habit that meets its target"),
    "finance": (20, "20 XP when the finance target is met (5 XP if logged but below target)"),
    "research": (20, "20 XP when the research target is met (5 XP if logged but below target)"),
    "reflection": (15, "15 XP for a complete Adapt reflection"),
    "mock_full": (50, "50 XP per submitted full-length Weekend Full War"),
    "mock_short": (25, "25 XP per submitted shorter paper"),
    "daily_clear": (30, "30 XP bonus when every applicable daily quest is complete"),
}
STUDY_TIME_CAP = 80
PYQ_CAP = 50

RANKS: tuple[tuple[int, str], ...] = (
    (1, "E"), (5, "D"), (10, "C"), (20, "B"), (30, "A"), (40, "S"), (60, "National Level"),
)


# --------------------------------------------------------------------------- levels
def xp_threshold(level: int) -> int:
    """Total XP required to reach ``level`` (level 1 = 0 XP). Step = 100 + 25·(L−1)."""
    n = level - 1
    return 100 * n + 25 * n * (n - 1) // 2


@dataclass(frozen=True)
class LevelInfo:
    level: int
    total_xp: int
    level_floor: int
    next_threshold: int
    rank: str

    @property
    def into_level(self) -> int:
        return self.total_xp - self.level_floor

    @property
    def span(self) -> int:
        return self.next_threshold - self.level_floor

    @property
    def progress_pct(self) -> float:
        return round(100.0 * self.into_level / self.span, 1) if self.span else 0.0


def rank_for_level(level: int) -> str:
    rank = RANKS[0][1]
    for min_level, name in RANKS:
        if level >= min_level:
            rank = name
    return rank


def level_for_xp(total_xp: int) -> LevelInfo:
    level = 1
    while xp_threshold(level + 1) <= total_xp:
        level += 1
    return LevelInfo(level, total_xp, xp_threshold(level), xp_threshold(level + 1), rank_for_level(level))


# --------------------------------------------------------------------------- quests
@dataclass
class Quest:
    key: str
    title: str
    detail: str
    applicable: bool
    done: bool
    progress: float  # 0..1


def daily_quests(session: Session, day: date, tz: str) -> list[Quest]:
    s = settings_service.get_all(session)
    study_target, pyq_target = int(s["daily_study_target_minutes"]), int(s["daily_pyq_target"])
    minutes, pyq = session.execute(
        select(func.coalesce(func.sum(StudyLog.minutes), 0), func.coalesce(func.sum(StudyLog.pyq_attempted), 0))
        .where(StudyLog.log_date == day)
    ).one()
    revs = list(session.scalars(select(RevisionEvent).where(
        RevisionEvent.due_date <= day,
        (RevisionEvent.completed_on.is_(None)) | (RevisionEvent.completed_on >= day),
    )))
    revs_done = sum(1 for e in revs if e.completed_on == day)
    habits = habit_service.daily_summary(session, day, day)[0]
    fin = worklog_service.daily_minutes(session, "finance", day, day).get(day, 0)
    res = worklog_service.daily_minutes(session, "research", day, day).get(day, 0)
    fin_t, res_t = int(s["finance_target_minutes"]), int(s["research_target_minutes"])
    attention = session.scalar(select(func.count(AttentionSession.id)).where(AttentionSession.session_date == day))
    reflected = session.scalar(select(func.count(Reflection.id)).where(Reflection.entry_date == day))

    def frac(a: float, b: float) -> float:
        return min(1.0, a / b) if b else 0.0

    return [
        Quest("study", "Daily Training", f"{int(minutes)}/{study_target} min of GATE study", study_target > 0,
              minutes >= study_target > 0, frac(minutes, study_target)),
        Quest("pyq", "PYQ Hunt", f"{int(pyq)}/{pyq_target} PYQs attempted", pyq_target > 0,
              pyq >= pyq_target > 0, frac(pyq, pyq_target)),
        Quest("revision", "Clear the Revision Queue", f"{revs_done}/{len(revs)} due revisions completed",
              bool(revs), bool(revs) and revs_done == len(revs), frac(revs_done, len(revs))),
        Quest("habits", "Body & Mind Rituals", f"{habits.done}/{habits.applicable} habits done",
              habits.applicable > 0, habits.applicable > 0 and habits.done == habits.applicable,
              frac(habits.done, habits.applicable)),
        Quest("finance", "Finance Hour", f"{fin}/{fin_t} min", True, fin >= fin_t, frac(fin, fin_t)),
        Quest("research", "Research Hour", f"{res}/{res_t} min", True, res >= res_t, frac(res, res_t)),
        Quest("attention", "Deep Focus Log", "Log your longest focus session", True, bool(attention),
              1.0 if attention else 0.0),
        Quest("adapt", "Adapt", "Write today's reflection", True, bool(reflected), 1.0 if reflected else 0.0),
    ]


# --------------------------------------------------------------------------- XP ledger
@dataclass(frozen=True)
class XPSpec:
    rule: str
    key: str
    amount: int
    description: str


def expected_events(session: Session, day: date, tz: str) -> list[XPSpec]:
    specs: list[XPSpec] = []
    logs = list(session.scalars(select(StudyLog).where(StudyLog.log_date == day)))
    for tid in sorted({lg.topic_id for lg in logs if lg.minutes > 0 or lg.pyq_attempted > 0}):
        name = session.scalar(select(Topic.name).where(Topic.id == tid))
        specs.append(XPSpec("study_topic", f"study_topic:{day}:{tid}", 10, f"Studied {name}"))
    minutes = sum(lg.minutes for lg in logs)
    if minutes >= 30:
        specs.append(XPSpec("study_time", f"study_time:{day}", min(STUDY_TIME_CAP, (minutes // 30) * 5),
                            f"{minutes} min of GATE study"))
    correct = sum(lg.pyq_correct for lg in logs)
    if correct:
        specs.append(XPSpec("pyq_correct", f"pyq_correct:{day}", min(PYQ_CAP, correct), f"{correct} PYQs correct"))
    for ev in session.scalars(select(RevisionEvent).where(RevisionEvent.completed_on == day,
                                                          RevisionEvent.status == "completed")):
        specs.append(XPSpec("revision", f"revision:{ev.id}", 15, f"Revision R{ev.stage} completed"))
    habits = {h.id: h for h in habit_service.list_habits(session, active_only=False)}
    for entry in session.scalars(select(HabitEntry).where(HabitEntry.entry_date == day)):
        habit = habits.get(entry.habit_id)
        if habit is not None and habit_service.entry_state(habit, entry) == "done":
            specs.append(XPSpec("habit", f"habit:{day}:{habit.id}", 5, f"Habit: {habit.name}"))
    for domain in ("finance", "research"):
        mins = int(session.scalar(select(func.coalesce(func.sum(WorkLog.duration_minutes), 0))
                                  .where(WorkLog.domain == domain, WorkLog.log_date == day)) or 0)
        if mins:
            met = mins >= worklog_service.target_minutes(session, domain)
            specs.append(XPSpec(domain, f"{domain}:{day}", 20 if met else 5,
                                f"{domain.title()} {mins} min{' (target met)' if met else ''}"))
    if session.scalar(select(func.count(Reflection.id)).where(Reflection.entry_date == day)):
        specs.append(XPSpec("reflection", f"reflection:{day}", 15, "Adapt reflection"))
    for exam in session.scalars(select(MockExam).where(MockExam.status == "submitted")):
        if exam.submitted_at and local_date_of(exam.submitted_at, tz) == day:
            rule = "mock_full" if exam.mode == "full" else "mock_short"
            specs.append(XPSpec(rule, f"mock:{exam.id}", XP_RULES[rule][0], f"Submitted {exam.title}"))
    quests = [q for q in daily_quests(session, day, tz) if q.applicable]
    if quests and all(q.done for q in quests):
        specs.append(XPSpec("daily_clear", f"daily_clear:{day}", 30, "All daily quests cleared"))
    return specs


def sync_day(session: Session, day: date, tz: str) -> int:
    """Reconcile the XP ledger for one day with source data. Returns net XP change."""
    expected = {s.key: s for s in expected_events(session, day, tz)}
    existing = {e.source_key: e for e in session.scalars(
        select(XPEvent).where((XPEvent.event_date == day) | (XPEvent.source_key.in_(list(expected)))))}
    delta = 0
    for key, row in existing.items():
        if key not in expected and row.event_date == day:
            delta -= row.amount
            session.delete(row)
    for key, spec in expected.items():
        current = existing.get(key)
        if current is None:
            session.add(XPEvent(event_date=day, rule=spec.rule, source_key=key, amount=spec.amount,
                                description=spec.description))
            delta += spec.amount
        else:
            delta += spec.amount - current.amount
            current.amount, current.event_date, current.rule, current.description = spec.amount, day, spec.rule, spec.description
    session.flush()
    return delta


def sync_days(session: Session, days: set[date] | list[date], tz: str) -> None:
    for d in sorted(set(days)):
        sync_day(session, d, tz)


def data_dates(session: Session) -> set[date]:
    days: set[date] = set()
    for col in (StudyLog.log_date, RevisionEvent.completed_on, HabitEntry.entry_date, WorkLog.log_date,
                Reflection.entry_date, AttentionSession.session_date, XPEvent.event_date):
        days |= {d for d in session.scalars(select(col).distinct()) if d is not None}
    return days


def sync_all(session: Session, tz: str, today: date) -> None:
    days = data_dates(session)
    for exam in session.scalars(select(MockExam).where(MockExam.submitted_at.is_not(None))):
        days.add(local_date_of(exam.submitted_at, tz))  # type: ignore[arg-type]
    days.add(today)
    sync_days(session, days, tz)


def total_xp(session: Session) -> int:
    return int(session.scalar(select(func.coalesce(func.sum(XPEvent.amount), 0))) or 0)


def xp_by_day(session: Session, start: date, end: date) -> dict[date, int]:
    rows = session.execute(select(XPEvent.event_date, func.sum(XPEvent.amount))
                           .where(XPEvent.event_date >= start, XPEvent.event_date <= end)
                           .group_by(XPEvent.event_date))
    return {d: int(x) for d, x in rows}


def recent_events(session: Session, limit: int = 30) -> list[XPEvent]:
    return list(session.scalars(select(XPEvent).order_by(XPEvent.event_date.desc(), XPEvent.id.desc()).limit(limit)))


# --------------------------------------------------------------------------- streaks
def _streak(days: set[date], end: date) -> int:
    day = end if end in days else end - timedelta(days=1)
    n = 0
    while day in days:
        n += 1
        day -= timedelta(days=1)
    return n


def _max_streak(days: set[date]) -> int:
    best = run = 0
    prev: date | None = None
    for d in sorted(days):
        run = run + 1 if prev is not None and d - prev == timedelta(days=1) else 1
        best = max(best, run)
        prev = d
    return best


def study_streak(session: Session, today: date) -> int:
    return _streak(set(session.scalars(select(StudyLog.log_date).distinct())), today)


def clear_streak(session: Session, today: date) -> int:
    days = set(session.scalars(select(XPEvent.event_date).where(XPEvent.rule == "daily_clear")))
    return _streak(days, today)


# --------------------------------------------------------------------------- achievements
def _achievement_conditions(session: Session, tz: str) -> dict[str, bool]:
    study_days = set(session.scalars(select(StudyLog.log_date).distinct()))
    max_streak = _max_streak(study_days)
    revisions = int(session.scalar(select(func.count(RevisionEvent.id)).where(RevisionEvent.status == "completed")) or 0)
    mastered = int(session.scalar(select(func.count(TopicProgress.id)).where(TopicProgress.coverage_status == "mastered")) or 0)
    per_subject: dict[int, list[str]] = defaultdict(list)
    for sid, status in session.execute(select(Topic.subject_id, TopicProgress.coverage_status)
                                       .join(TopicProgress).join(Subject).where(Topic.is_active.is_(True))):
        per_subject[sid].append(status)
    subject_done = any(all(s == "mastered" for s in v) for v in per_subject.values() if v)
    pyq_correct = int(session.scalar(select(func.coalesce(func.sum(StudyLog.pyq_correct), 0))) or 0)
    exams = list(session.scalars(select(MockExam).where(MockExam.status == "submitted")))
    best_attention = int(session.scalar(select(func.coalesce(func.max(AttentionSession.minutes), 0))) or 0)
    perfect = 0
    habits = habit_service.list_habits(session)
    if habits:
        by_day: dict[date, int] = defaultdict(int)
        for entry in session.scalars(select(HabitEntry)):
            h = next((x for x in habits if x.id == entry.habit_id), None)
            if h is not None and habit_service.entry_state(h, entry) == "done":
                by_day[entry.entry_date] += 1
        perfect = sum(1 for n in by_day.values() if n >= len(habits))
    reflections = int(session.scalar(select(func.count(Reflection.id))) or 0)
    fin_days = sum(1 for e in session.scalars(select(XPEvent).where(XPEvent.rule == "finance")) if e.amount >= 20)
    res_days = sum(1 for e in session.scalars(select(XPEvent).where(XPEvent.rule == "research")) if e.amount >= 20)
    level = level_for_xp(total_xp(session)).level
    return {
        "first_log": bool(study_days),
        "study_streak_7": max_streak >= 7,
        "study_streak_30": max_streak >= 30,
        "revisions_10": revisions >= 10,
        "revisions_50": revisions >= 50,
        "topics_mastered_10": mastered >= 10,
        "subject_mastered": subject_done,
        "pyq_100": pyq_correct >= 100,
        "first_war": bool(exams),
        "war_60": any(e.mode == "full" and (e.score or 0) >= 0.6 * e.max_marks for e in exams),
        "attention_60": best_attention >= 60,
        "attention_200": best_attention >= 200,
        "habits_perfect_7": perfect >= 7,
        "reflection_7": reflections >= 7,
        "finance_10": fin_days >= 10,
        "research_10": res_days >= 10,
        "level_10": level >= 10,
    }


def evaluate_achievements(session: Session, today: date, tz: str) -> list[Achievement]:
    """Unlock newly satisfied badges, revoke ones whose basis was removed. Returns newly unlocked."""
    conditions = _achievement_conditions(session, tz)
    unlocked = {ua.achievement_id: ua for ua in session.scalars(select(UserAchievement))}
    new: list[Achievement] = []
    for ach in session.scalars(select(Achievement).order_by(Achievement.sort_order)):
        ok = conditions.get(ach.key, False)
        if ok and ach.id not in unlocked:
            session.add(UserAchievement(achievement_id=ach.id, unlocked_on=today))
            new.append(ach)
        elif not ok and ach.id in unlocked:
            session.delete(unlocked[ach.id])
    session.flush()
    return new


def achievements_view(session: Session) -> list[tuple[Achievement, UserAchievement | None]]:
    unlocked = {ua.achievement_id: ua for ua in session.scalars(select(UserAchievement))}
    return [(a, unlocked.get(a.id)) for a in session.scalars(select(Achievement).order_by(Achievement.sort_order))]


# --------------------------------------------------------------------------- status snapshot
@dataclass
class StatusSnapshot:
    level: LevelInfo
    study_streak: int
    clear_streak: int
    today_xp: int


def status(session: Session, today: date) -> StatusSnapshot:
    total = total_xp(session)
    return StatusSnapshot(
        level=level_for_xp(total), study_streak=study_streak(session, today),
        clear_streak=clear_streak(session, today), today_xp=xp_by_day(session, today, today).get(today, 0),
    )


def after_change(session: Session, days: set[date] | list[date], today: date, tz: str) -> list[Achievement]:
    """Call after any data mutation: re-sync XP for affected days and re-evaluate badges."""
    sync_days(session, set(days) | {today}, tz)
    return evaluate_achievements(session, today, tz)


__all__ = [
    "XP_RULES", "RANKS", "xp_threshold", "level_for_xp", "rank_for_level", "daily_quests", "expected_events",
    "sync_day", "sync_days", "sync_all", "total_xp", "status", "after_change", "evaluate_achievements",
    "achievements_view", "study_streak", "clear_streak", "xp_by_day", "recent_events",
]
