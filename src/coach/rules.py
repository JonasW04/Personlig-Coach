"""Evaluate structured recovery rules against one health day."""
from __future__ import annotations

import json
import operator

from coach.models import RecoveryRule


METRICS = {
    "training_readiness",
    "acwr",
    "sleep_score",
    "hrv",
    "body_battery_high",
    "resting_hr",
    "avg_stress",
}
OPERATORS = {"<", "<=", ">", ">="}
ACTIONS = {"rest", "swap_to_zone2", "reduce_volume", "cap_intensity"}
_COMPARE = {
    "<": operator.lt,
    "<=": operator.le,
    ">": operator.gt,
    ">=": operator.ge,
}
_ACTION_TEXT = {
    "rest": "Rest",
    "swap_to_zone2": "Swap to Zone 2",
    "reduce_volume": "Reduce volume",
    "cap_intensity": "Cap intensity",
}


def condition(rule: RecoveryRule) -> dict | None:
    if not rule.condition_json:
        return None
    try:
        parsed = json.loads(rule.condition_json)
    except (json.JSONDecodeError, TypeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def matches(rule: RecoveryRule, health_day: dict | None) -> bool:
    parsed = condition(rule)
    if not rule.enabled or parsed is None or health_day is None:
        return False
    metric = parsed.get("metric")
    op = parsed.get("op")
    actual = health_day.get(metric) if metric in METRICS else None
    if op not in _COMPARE or actual is None:
        return False
    try:
        return _COMPARE[op](float(actual), float(parsed["value"]))
    except (KeyError, TypeError, ValueError):
        return False


def evaluate(rules: list[RecoveryRule], health_day: dict | None) -> list[RecoveryRule]:
    return [rule for rule in sorted(rules, key=lambda item: item.order_index) if matches(rule, health_day)]


def message(rule: RecoveryRule) -> str:
    return f"{rule.label}: {_ACTION_TEXT[rule.action]}. {rule.description}"
