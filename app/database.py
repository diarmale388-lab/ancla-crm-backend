import os
import logging
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session
from typing import Generator
from app.config import settings

logger = logging.getLogger("database")

NEON_OFFICIAL_URL = "postgresql://neondb_owner:npg_u0jKzE8lWQfb@ep-misty-night-aw10uqbm.c-12.us-east-1.aws.neon.tech/neondb?sslmode=require"
SQLITE_FALLBACK_URL = "sqlite:///./crm.db"

use_neon = os.getenv("USE_NEON", "0") == "1"
raw_db_url = settings.DATABASE_URL or NEON_OFFICIAL_URL

if use_neon and raw_db_url and not raw_db_url.startswith("sqlite"):
    try:
        test_engine = create_engine(
            raw_db_url,
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=5,
            connect_args={"connect_timeout": 3}
        )
        with test_engine.connect() as conn:
            conn.execute(text("SELECT count(*) FROM users"))
        engine = test_engine
        logger.info("Conexión a PostgreSQL (Neon) verificada y activa.")
    except Exception as e_pg:
        logger.warning(f"No se pudo consultar PostgreSQL ({e_pg}). Activando respaldo automático a SQLite local.")
        engine = create_engine(
            SQLITE_FALLBACK_URL,
            connect_args={"check_same_thread": False}
        )
else:
    engine = create_engine(
        SQLITE_FALLBACK_URL,
        connect_args={"check_same_thread": False}
    )
    logger.info("Base de datos SQLite activa por defecto: ./crm.db")

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
