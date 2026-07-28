from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from typing import Generator
from app.config import settings

NEON_OFFICIAL_URL = "postgresql://neondb_owner:npg_u0jKzE8lWQfb@ep-misty-night-aw10uqbm.c-12.us-east-1.aws.neon.tech/neondb?sslmode=require"

db_url = settings.DATABASE_URL
if not db_url or "sqlite" in db_url or "localhost" in db_url:
    db_url = NEON_OFFICIAL_URL

if db_url.startswith("sqlite"):
    engine = create_engine(
        db_url, connect_args={"check_same_thread": False}
    )
else:
    engine = create_engine(
        db_url,
        pool_pre_ping=True,
        pool_size=20,
        max_overflow=10
    )

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
