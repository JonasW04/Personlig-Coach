"""Deterministic readiness score used by daily reviews and the Today screen."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ReadinessResult:
    score: int
    components: dict[str, float]


def _clamp(value: float, low: float = 0, high: float = 100) -> float:
    return max(low, min(high, value))


def _number(value) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _hrv_score(day: dict) -> float | None:
    value = _number(day.get("hrv"))
    low = _number(day.get("hrv_baseline_low"))
    high = _number(day.get("hrv_baseline_high"))
    if value is not None and low is not None and high is not None and high > low:
        midpoint = (low + high) / 2
        # Mid-baseline is strong readiness; each 10% below it costs 20 points.
        return _clamp(80 + ((value / midpoint) - 1) * 200)

    status = str(day.get("hrv_status") or "").strip().lower()
    return {
        "balanced": 80,
        "unbalanced": 55,
        "low": 35,
        "poor": 20,
    }.get(status)


def _resting_hr_score(day: dict) -> float | None:
    resting = _number(day.get("resting_hr"))
    baseline = _number(day.get("resting_hr_7d_avg"))
    if resting is None or baseline is None:
        return None
    # Baseline is healthy/neutral. A higher resting HR is penalised faster than a
    # lower one is rewarded.
    diff = resting - baseline
    return _clamp(80 - diff * (6 if diff > 0 else 2))


def _load_score(day: dict) -> float | None:
    acwr = _number(day.get("acwr"))
    if acwr is None:
        return None
    if acwr <= 1.3:
        return 80
    return _clamp(80 - (acwr - 1.3) * 100)


def calculate(health_day: dict | None) -> ReadinessResult:
    """Calculate a stable 0-100 score from locally available recovery signals.

    Missing inputs are omitted and the remaining weights are re-normalised. When
    no component exists, return a neutral 50 rather than presenting Garmin's raw
    readiness value as Coach's calculated score.
    """
    day = health_day or {}
    candidates = {
        "sleep": (_number(day.get("sleep_score")), 0.25),
        "hrv": (_hrv_score(day), 0.25),
        "body_battery": (_number(day.get("body_battery_high")), 0.20),
        "resting_hr": (_resting_hr_score(day), 0.15),
        "training_load": (_load_score(day), 0.15),
    }
    components = {
        name: round(_clamp(value), 1)
        for name, (value, _weight) in candidates.items()
        if value is not None
    }
    if not components:
        return ReadinessResult(score=50, components={})

    weight_total = sum(
        weight for name, (_value, weight) in candidates.items() if name in components
    )
    weighted = sum(
        components[name] * candidates[name][1] for name in components
    ) / weight_total
    return ReadinessResult(score=round(_clamp(weighted)), components=components)
