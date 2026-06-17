import json
import os
import sys
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from coach import rules
from coach.models import RecoveryRule
from coach.web import app as web_app


def rule(**overrides) -> RecoveryRule:
    values = {
        "label": "Low readiness",
        "description": "Swap hard work for Zone 2.",
        "condition_json": json.dumps({"metric": "training_readiness", "op": "<", "value": 60}),
        "action": "swap_to_zone2",
        "enabled": True,
        "order_index": 0,
    }
    values.update(overrides)
    return RecoveryRule(**values)


class TestRuleEvaluation(unittest.TestCase):
    def test_evaluates_numeric_rules_and_ignores_structural_rules(self):
        numeric = rule()
        structural = rule(label="Strength first", condition_json=None, order_index=1)
        disabled = rule(label="Disabled", enabled=False, order_index=2)

        triggered = rules.evaluate(
            [disabled, structural, numeric], {"training_readiness": 42}
        )

        self.assertEqual([numeric], triggered)
        self.assertEqual([], rules.evaluate([numeric], {"training_readiness": None}))


class TestRulesEndpoints(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
        RecoveryRule.__table__.create(self.engine)
        self.session_factory = sessionmaker(bind=self.engine, future=True, expire_on_commit=False)
        self.session_patch = patch.object(web_app, "SessionLocal", self.session_factory)
        self.health_patch = patch.object(
            web_app, "_latest_health_day", return_value={"training_readiness": 42, "acwr": 1.2}
        )
        self.session_patch.start()
        self.health_patch.start()

    def tearDown(self):
        self.health_patch.stop()
        self.session_patch.stop()
        self.engine.dispose()

    async def test_crud_shapes_thresholds_and_warning(self):
        created = await web_app.create_rule(
            web_app.RuleCreate(
                label="Low readiness",
                description="Swap hard work for Zone 2.",
                condition=web_app.RuleCondition(
                    metric="training_readiness", op="<", value=60
                ),
                action="swap_to_zone2",
            )
        )
        row = created["rules"][0]
        self.assertEqual(60, row["threshold"])
        self.assertEqual(
            "Low readiness: Swap to Zone 2. Swap hard work for Zone 2.",
            created["warning"],
        )
        self.assertEqual([row["id"]], [item["id"] for item in created["triggered"]])

        patched = await web_app.update_rule(
            row["id"], web_app.RuleUpdate(condition=None, enabled=False)
        )
        self.assertIsNone(patched["rules"][0]["condition"])
        self.assertIsNone(patched["rules"][0]["threshold"])
        self.assertIsNone(patched["warning"])

        self.assertEqual({"ok": True}, await web_app.delete_rule(row["id"]))
        with self.session_factory() as session:
            self.assertEqual([], session.execute(select(RecoveryRule)).scalars().all())

    def test_acwr_threshold_is_scaled_and_hrv_has_no_marker(self):
        acwr = rule(
            condition_json=json.dumps({"metric": "acwr", "op": ">", "value": 1.4})
        )
        hrv = rule(condition_json=json.dumps({"metric": "hrv", "op": "<", "value": 40}))
        self.assertEqual(70, web_app._rule_json(acwr)["threshold"])
        self.assertIsNone(web_app._rule_json(hrv)["threshold"])


if __name__ == "__main__":
    unittest.main()
