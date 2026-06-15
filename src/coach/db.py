from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from coach.config import settings
from coach.models import Base

engine = create_engine(settings.database_url, future=True)
SessionLocal = sessionmaker(bind=engine, future=True, expire_on_commit=False)


def init_db() -> None:
    Base.metadata.create_all(engine)
