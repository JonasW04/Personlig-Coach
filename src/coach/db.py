from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from coach.config import settings
from coach.models import Base

engine = create_engine(
    settings.database_url,
    future=True,
    pool_pre_ping=True,
    # Fail fast instead of hanging forever on an unreachable host (e.g. the
    # internal *.railway.internal URL used from outside Railway's network).
    connect_args={"connect_timeout": 10},
)
SessionLocal = sessionmaker(bind=engine, future=True, expire_on_commit=False)


# Lightweight forward migrations. We don't run Alembic; create_all() makes new
# tables but never alters existing ones, so columns added after a table first
# shipped are applied here. Postgres ADD COLUMN IF NOT EXISTS makes this safe to
# run on every boot.
_COLUMN_MIGRATIONS = [
    "ALTER TABLE action_items ADD COLUMN IF NOT EXISTS week_start DATE",
    "ALTER TABLE action_items ADD COLUMN IF NOT EXISTS metric VARCHAR",
    "ALTER TABLE action_items ADD COLUMN IF NOT EXISTS target_value DOUBLE PRECISION",
    "ALTER TABLE action_items ADD COLUMN IF NOT EXISTS auto BOOLEAN DEFAULT FALSE",
    "CREATE INDEX IF NOT EXISTS ix_action_items_week_start ON action_items (week_start)",
    # garmin_daily already exists in prod, so new columns need explicit ALTERs.
    "ALTER TABLE garmin_daily ADD COLUMN IF NOT EXISTS chronic_load DOUBLE PRECISION",
    "ALTER TABLE garmin_daily ADD COLUMN IF NOT EXISTS acwr DOUBLE PRECISION",
    "ALTER TABLE garmin_daily ADD COLUMN IF NOT EXISTS acwr_status VARCHAR",
    "ALTER TABLE garmin_daily ADD COLUMN IF NOT EXISTS fitness_age DOUBLE PRECISION",
    "ALTER TABLE garmin_daily ADD COLUMN IF NOT EXISTS resting_hr_7d_avg INTEGER",
    "ALTER TABLE garmin_daily ADD COLUMN IF NOT EXISTS avg_sleep_respiration DOUBLE PRECISION",
    "ALTER TABLE garmin_daily ADD COLUMN IF NOT EXISTS avg_sleep_spo2 DOUBLE PRECISION",
]


def init_db() -> None:
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        for stmt in _COLUMN_MIGRATIONS:
            conn.execute(text(stmt))
