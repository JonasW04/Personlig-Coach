"""One-off: dump raw Garmin Connect responses to inspect what your watch returns.

Run it the same way you ran auth (token comes from the DB, no re-login):

    DATABASE_URL="<railway public url>" .venv/bin/python scripts/garmin_probe.py

It hits a curated set of recovery/training endpoints for the last few days and
writes everything to ``garmin_probe_output.json`` in the repo root. That file is
just for inspection — safe to delete afterwards.
"""
from __future__ import annotations

import json
from datetime import date, timedelta

from coach.integrations.garmin import _client_from_token

# Getters that take a single ISO date.
_DATE_GETTERS = [
    "get_sleep_data",
    "get_hrv_data",
    "get_training_readiness",
    "get_morning_training_readiness",
    "get_training_status",
    "get_max_metrics",
    "get_user_summary",
    "get_stats",
    "get_stats_and_body",
    "get_all_day_stress",
    "get_stress_data",
    "get_body_battery",
    "get_respiration_data",
    "get_spo2_data",
    "get_intensity_minutes_data",
    "get_floors",
    "get_rhr_day",
    "get_endurance_score",
    "get_hill_score",
    "get_race_predictions",
    "get_running_tolerance",
    "get_lactate_threshold",
    "get_fitnessage_data",
    "get_daily_steps",
]
# Getters that take no arguments.
_NOARG_GETTERS = [
    "get_primary_training_device",
    "get_devices",
]


def _call(client, name, *args):
    fn = getattr(client, name, None)
    if fn is None:
        return {"__error__": "method not found"}
    try:
        return fn(*args)
    except Exception as exc:  # noqa: BLE001 - probe: capture every failure
        return {"__error__": f"{type(exc).__name__}: {exc}"}


def main() -> None:
    client = _client_from_token()
    today = date.today()
    out: dict = {"days": {}, "global": {}}

    for offset in (1, 2, 3):
        d = (today - timedelta(days=offset)).isoformat()
        day_out: dict = {}
        for name in _DATE_GETTERS:
            day_out[name] = _call(client, name, d)
        out["days"][d] = day_out

    for name in _NOARG_GETTERS:
        out["global"][name] = _call(client, name)

    path = "garmin_probe_output.json"
    with open(path, "w") as f:
        json.dump(out, f, indent=2, default=str)
    print(f"Wrote {path}")
    # Quick console summary: which endpoints returned real data vs error/empty.
    for d, getters in out["days"].items():
        print(f"\n=== {d} ===")
        for name, val in getters.items():
            if isinstance(val, dict) and "__error__" in val:
                tag = f"ERROR: {val['__error__']}"
            elif not val:
                tag = "empty"
            else:
                size = len(val) if isinstance(val, (list, dict)) else 1
                tag = f"data ({type(val).__name__}, {size} keys/items)"
            print(f"  {name:32s} {tag}")


if __name__ == "__main__":
    main()
