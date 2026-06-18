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
    "ALTER TABLE coach_memories ADD COLUMN IF NOT EXISTS category VARCHAR NOT NULL DEFAULT 'note'",
    "ALTER TABLE coach_profile ADD COLUMN IF NOT EXISTS body_mode VARCHAR",
    "ALTER TABLE coach_profile ADD COLUMN IF NOT EXISTS body_mode_started_at TIMESTAMP WITH TIME ZONE",
    "ALTER TABLE coach_profile ADD COLUMN IF NOT EXISTS body_mode_week_count INTEGER",
    "ALTER TABLE reports ADD COLUMN IF NOT EXISTS review_date DATE",
    "ALTER TABLE reports ADD COLUMN IF NOT EXISTS readiness_score INTEGER",
    "ALTER TABLE reports ADD COLUMN IF NOT EXISTS readiness_details_json TEXT",
    "ALTER TABLE reports ADD COLUMN IF NOT EXISTS plan_week_start DATE",
    "ALTER TABLE reports ADD COLUMN IF NOT EXISTS workflow_status VARCHAR NOT NULL DEFAULT 'complete'",
    "ALTER TABLE reports ADD COLUMN IF NOT EXISTS workflow_error TEXT",
    "CREATE INDEX IF NOT EXISTS ix_reports_review_date ON reports (review_date)",
    "CREATE INDEX IF NOT EXISTS ix_reports_workflow_status ON reports (workflow_status)",
    "ALTER TABLE plan_days ADD COLUMN IF NOT EXISTS published_payload_hash VARCHAR",
    "ALTER TABLE plan_days ADD COLUMN IF NOT EXISTS delivery_status VARCHAR NOT NULL DEFAULT 'pending'",
    "ALTER TABLE plan_days ADD COLUMN IF NOT EXISTS delivery_error TEXT",
    "ALTER TABLE plan_days ADD COLUMN IF NOT EXISTS published_at TIMESTAMP WITH TIME ZONE",
    "CREATE INDEX IF NOT EXISTS ix_plan_days_delivery_status ON plan_days (delivery_status)",
    """DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1
            FROM pg_constraint c
            JOIN pg_attribute a
              ON a.attrelid = c.conrelid AND a.attnum = ANY(c.conkey)
            WHERE c.conrelid = 'plan_days'::regclass
              AND c.contype = 'f'
              AND a.attname = 'block_id'
        ) THEN
            ALTER TABLE plan_days
            ADD CONSTRAINT fk_plan_days_block_id
            FOREIGN KEY (block_id) REFERENCES training_blocks(id);
        END IF;
    END $$""",
]


def init_db() -> None:
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        for stmt in _COLUMN_MIGRATIONS:
            conn.execute(text(stmt))
