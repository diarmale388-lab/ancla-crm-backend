import os
import logging
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session
from typing import Generator
from app.config import settings

logger = logging.getLogger("database")

NEON_OFFICIAL_URL = "postgresql://neondb_owner:npg_u0jKzE8lWQfb@ep-misty-night-aw10uqbm.c-12.us-east-1.aws.neon.tech/neondb?sslmode=require"
SQLITE_FALLBACK_URL = "sqlite:///./crm.db"

db_url = settings.DATABASE_URL or NEON_OFFICIAL_URL
engine = None

if db_url and not db_url.startswith("sqlite"):
    try:
        test_engine = create_engine(
            db_url,
            pool_pre_ping=True,
            pool_size=20,
            max_overflow=10,
            connect_args={"connect_timeout": 3}
        )
        with test_engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        engine = test_engine
        logger.info("Conexión a PostgreSQL (Neon) verificada exitosamente.")
    except Exception as e_pg:
        logger.warning(f"Error conectando a PostgreSQL ({e_pg}). Activando respaldo automático a SQLite local.")

if engine is None:
    db_url = SQLITE_FALLBACK_URL
    engine = create_engine(
        db_url,
        connect_args={"check_same_thread": False}
    )

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
