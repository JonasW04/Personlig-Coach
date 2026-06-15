from sqlalchemy import create_engine
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


def init_db() -> None:
    Base.metadata.create_all(engine)
