"""Regression tests for activity data consumed by dashboard screens."""
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from coach.models import Base, Exercise, SetEntry, Workout
from coach.web import stats


class TestActivityStats(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)

    def tearDown(self):
        self.engine.dispose()

    def test_strength_activity_includes_hevy_workout_title(self):
        started = datetime(2026, 6, 17, 16, 0, tzinfo=timezone.utc)
        workout = Workout(
            id="hevy-workout-1",
            title="Upper Body Hypertrophy",
            start_time=started,
            end_time=started + timedelta(minutes=53),
        )
        exercise = Exercise(title="Bench Press", order_index=0)
        exercise.sets.append(SetEntry(set_type="normal", weight_kg=80, reps=8, order_index=0))
        workout.exercises.append(exercise)
        with self.Session() as session:
            session.add(workout)
            session.commit()

        with patch.object(stats, "SessionLocal", self.Session):
            result = stats.activity("2026-06-17", "2026-06-17")

        self.assertEqual("Upper Body Hypertrophy", result["days"][0]["strength"]["title"])


if __name__ == "__main__":
    unittest.main()
