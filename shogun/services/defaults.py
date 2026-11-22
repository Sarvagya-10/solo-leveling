"""Seed definitions for habits, not-to-do rules and achievement badges."""

from __future__ import annotations

from dataclasses import dataclass

FINANCE_PROJECT = "APE"
"""The single finance project. Every finance log belongs to it."""

FINANCE_TARGET_LABEL = "+1.2%"
"""Default headline target shown on the Finance page (editable in Settings)."""


@dataclass(frozen=True)
class HabitDef:
    key: str
    name: str
    kind: str  # check | numeric
    unit: str | None
    target: float


DEFAULT_HABITS: tuple[HabitDef, ...] = (
    HabitDef("prayer", "Prayer", "check", None, 1),
    HabitDef("brushing", "Brushing", "check", None, 1),
    HabitDef("bathing", "Bathing properly", "check", None, 1),
    HabitDef("water", "Water", "numeric", "litres", 3.0),
    HabitDef("exercise", "Proper exercise", "numeric", "minutes", 30),
    HabitDef("reading", "Reading", "numeric", "minutes", 30),
    HabitDef("speaking", "Speaking practice", "numeric", "minutes", 15),
    HabitDef("socials", "Socials +1", "check", None, 1),
)


@dataclass(frozen=True)
class RuleDef:
    key: str
    name: str
    description: str


DEFAULT_AVOIDANCE_RULES: tuple[RuleDef, ...] = (
    RuleDef("junk_food", "No junk food", "No fried, packaged or fast food."),
    RuleDef("sugar", "No sugar", "No added sugar, sweets or sugary drinks."),
    RuleDef("fap", "No fap", "Private self-discipline commitment."),
    RuleDef("complaining", "No complaining", "No complaining, out loud or in writing."),
    RuleDef("asking_why", "No asking the 'why'", "Act on the task instead of questioning it."),
    RuleDef("youtube", "No YouTube surfing", "No aimless YouTube browsing."),
    RuleDef("social_media", "No social media (Instagram, Pinterest)", "No Instagram or Pinterest."),
)


@dataclass(frozen=True)
class AchievementDef:
    key: str
    name: str
    description: str
    icon: str


ACHIEVEMENTS: tuple[AchievementDef, ...] = (
    AchievementDef("first_log", "Player Awakened", "Log your first GATE study session.", "⚔️"),
    AchievementDef("study_streak_7", "Seven-Day Gate", "Reach a 7-day GATE study streak.", "🔥"),
    AchievementDef("study_streak_30", "Monarch's Discipline", "Reach a 30-day GATE study streak.", "👑"),
    AchievementDef("revisions_10", "Memory Forge", "Complete 10 scheduled revisions.", "🧠"),
    AchievementDef("revisions_50", "Eternal Recall", "Complete 50 scheduled revisions.", "♾️"),
    AchievementDef("topics_mastered_10", "Dungeon Cleared", "Mark 10 syllabus topics as mastered.", "🏰"),
    AchievementDef("subject_mastered", "Section Conquered", "Master every topic of one syllabus section.", "🗡️"),
    AchievementDef("pyq_100", "PYQ Hunter", "Solve 100 PYQs correctly.", "🎯"),
    AchievementDef("first_war", "First War", "Submit your first Weekend Full War paper.", "🛡️"),
    AchievementDef("war_60", "S-Rank Raid", "Score at least 60% in a full-length paper.", "💠"),
    AchievementDef("attention_60", "Deep Focus", "Hold a 60-minute deep-focus session.", "🌀"),
    AchievementDef("attention_200", "Monarch Focus", "Hold a 200-minute deep-focus session.", "🌌"),
    AchievementDef("habits_perfect_7", "Ritual Keeper", "Complete every habit on 7 different days.", "🕯️"),
    AchievementDef("reflection_7", "Self-Aware", "Write 7 Adapt reflections.", "🪞"),
    AchievementDef("finance_10", "Strategist", "Hit the finance target on 10 days.", "📈"),
    AchievementDef("research_10", "Scholar", "Hit the research target on 10 days.", "🔬"),
    AchievementDef("level_10", "C-Rank Hunter", "Reach level 10.", "⭐"),
)
