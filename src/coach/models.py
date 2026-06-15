from datetime import date, datetime, timezone

from sqlalchemy import BigInteger, Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Workout(Base):
    __tablename__ = "workouts"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # Hevy workout id
    title: Mapped[str | None] = mapped_column(String)
    start_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    end_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    exercises: Mapped[list["Exercise"]] = relationship(
        back_populates="workout", cascade="all, delete-orphan"
    )


class Exercise(Base):
    __tablename__ = "exercises"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    workout_id: Mapped[str] = mapped_column(ForeignKey("workouts.id"))
    template_id: Mapped[str | None] = mapped_column(String)  # exercise_template_id
    title: Mapped[str] = mapped_column(String)
    order_index: Mapped[int] = mapped_column(Integer, default=0)

    workout: Mapped["Workout"] = relationship(back_populates="exercises")
    sets: Mapped[list["SetEntry"]] = relationship(
        back_populates="exercise", cascade="all, delete-orphan"
    )


class SetEntry(Base):
    __tablename__ = "sets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    exercise_id: Mapped[int] = mapped_column(ForeignKey("exercises.id"))
    set_type: Mapped[str | None] = mapped_column(String)  # normal / warmup / failure
    weight_kg: Mapped[float | None] = mapped_column(Float)
    reps: Mapped[int | None] = mapped_column(Integer)
    distance_m: Mapped[float | None] = mapped_column(Float)
    duration_s: Mapped[int | None] = mapped_column(Integer)
    rpe: Mapped[float | None] = mapped_column(Float)
    order_index: Mapped[int] = mapped_column(Integer, default=0)

    exercise: Mapped["Exercise"] = relationship(back_populates="sets")


class Activity(Base):
    """A Strava activity (run, ride, etc.)."""

    __tablename__ = "activities"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)  # Strava activity id
    name: Mapped[str | None] = mapped_column(String)
    sport_type: Mapped[str | None] = mapped_column(String)  # Run, Ride, Workout...
    start_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    distance_m: Mapped[float | None] = mapped_column(Float)
    moving_time_s: Mapped[int | None] = mapped_column(Integer)
    elapsed_time_s: Mapped[int | None] = mapped_column(Integer)
    elevation_gain_m: Mapped[float | None] = mapped_column(Float)
    average_speed_ms: Mapped[float | None] = mapped_column(Float)
    average_hr: Mapped[float | None] = mapped_column(Float)
    max_hr: Mapped[float | None] = mapped_column(Float)
    average_watts: Mapped[float | None] = mapped_column(Float)
    suffer_score: Mapped[float | None] = mapped_column(Float)  # relative effort


class BodyMeasurement(Base):
    """A Withings measurement group (one weigh-in). Body-composition fields are
    populated only for scales that measure them."""

    __tablename__ = "body_measurements"

    grpid: Mapped[int] = mapped_column(BigInteger, primary_key=True)  # Withings group id
    measured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    weight_kg: Mapped[float | None] = mapped_column(Float)
    fat_ratio: Mapped[float | None] = mapped_column(Float)  # percent
    fat_mass_kg: Mapped[float | None] = mapped_column(Float)
    fat_free_mass_kg: Mapped[float | None] = mapped_column(Float)
    muscle_mass_kg: Mapped[float | None] = mapped_column(Float)
    bone_mass_kg: Mapped[float | None] = mapped_column(Float)
    hydration_kg: Mapped[float | None] = mapped_column(Float)


class Report(Base):
    """A generated coaching report (daily readiness or weekly review), persisted so
    the web UI can show history."""

    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String, index=True)  # 'readiness' | 'weekly'
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    content: Mapped[str] = mapped_column(Text)


class Goal(Base):
    """User-editable dashboard target, keyed to a known app metric."""

    __tablename__ = "goals"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    target_value: Mapped[float | None] = mapped_column(Float)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )


class ActionItem(Base):
    """A concrete coaching action that can be checked off by the user.

    Actions belonging to a weekly review carry ``week_start`` (the Monday of the
    week they apply to) and may be linked to a dashboard goal via ``metric`` +
    ``target_value`` so the UI can show live progress instead of a manual tick.
    ``auto`` marks items created from a generated review (vs. typed by hand).
    """

    __tablename__ = "action_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String, default="open", index=True)
    due_date: Mapped[date | None] = mapped_column(Date)
    week_start: Mapped[date | None] = mapped_column(Date, index=True)
    metric: Mapped[str | None] = mapped_column(String)  # linked goal key, if any
    target_value: Mapped[float | None] = mapped_column(Float)
    auto: Mapped[bool] = mapped_column(Boolean, default=False)
    source_report_id: Mapped[int | None] = mapped_column(ForeignKey("reports.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CoachProfile(Base):
    """Singleton (id=1) holding the athlete's training focus.

    ``focus_raw`` is what the user typed in plain language; ``directive`` is the
    model-ready coaching instruction generated from it, injected into the
    coordinator + subagent prompts so every report reflects the current goal.
    """

    __tablename__ = "coach_profile"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    focus_raw: Mapped[str] = mapped_column(Text)
    directive: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )


class PushSubscription(Base):
    """Browser Web Push subscription for report notifications."""

    __tablename__ = "push_subscriptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    endpoint: Mapped[str] = mapped_column(Text, unique=True, index=True)
    p256dh: Mapped[str] = mapped_column(Text)
    auth: Mapped[str] = mapped_column(Text)
    user_agent: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )


class OAuthToken(Base):
    """Persisted OAuth tokens, one row per provider (e.g. 'strava')."""

    __tablename__ = "oauth_tokens"

    provider: Mapped[str] = mapped_column(String, primary_key=True)
    access_token: Mapped[str] = mapped_column(String)
    refresh_token: Mapped[str] = mapped_column(String)
    expires_at: Mapped[int] = mapped_column(BigInteger)  # unix epoch seconds
