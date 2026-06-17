"""Persist notification preferences using the UI's canonical keys."""
from __future__ import annotations

from coach.db import SessionLocal
from coach.models import NotificationPref


PREF_SPECS = [
    {
        "key": "dailyPlan",
        "label": "Daily plan",
        "description": "Morning nudge with today's session.",
        "enabled": True,
    },
    {
        "key": "recoveryAlerts",
        "label": "Recovery alerts",
        "description": "When readiness drops below your guardrails.",
        "enabled": True,
    },
    {
        "key": "planDrift",
        "label": "Plan drift",
        "description": "When you miss or change a planned session.",
        "enabled": True,
    },
    {
        "key": "weeklyReview",
        "label": "Weekly review",
        "description": "When your weekly review is ready.",
        "enabled": True,
    },
    {
        "key": "quietHours",
        "label": "Quiet hours 21:00–06:00",
        "description": "Hold non-urgent nudges overnight.",
        "enabled": False,
    },
]
PREF_KEYS = tuple(spec["key"] for spec in PREF_SPECS)
_DEFAULTS = {spec["key"]: spec["enabled"] for spec in PREF_SPECS}


def list_preferences() -> list[dict]:
    with SessionLocal() as session:
        saved = {
            row.key: row.enabled
            for row in session.query(NotificationPref).all()
            if row.key in _DEFAULTS
        }
    return [
        {**spec, "enabled": saved.get(spec["key"], spec["enabled"])}
        for spec in PREF_SPECS
    ]


def is_enabled(key: str) -> bool:
    if key not in _DEFAULTS:
        raise ValueError(f"Unknown notification preference: {key}")
    with SessionLocal() as session:
        row = session.get(NotificationPref, key)
    return row.enabled if row is not None else _DEFAULTS[key]


def set_preference(key: str, enabled: bool) -> list[dict]:
    if key not in _DEFAULTS:
        raise ValueError(f"Unknown notification preference: {key}")
    with SessionLocal() as session:
        row = session.get(NotificationPref, key)
        if row is None:
            row = NotificationPref(key=key)
            session.add(row)
        row.enabled = enabled
        session.commit()
    return list_preferences()
