import os
import logging
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session
from typing import Generator
from app.config import settings

logger = logging.getLogger("database")

SQLITE_FALLBACK_URL = "sqlite:///./crm.db"

raw_db_url = os.getenv("DATABASE_URL") or settings.DATABASE_URL

if raw_db_url and not raw_db_url.startswith("sqlite"):
    try:
        test_engine = create_engine(
            raw_db_url,
            pool_pre_ping=True,
            pool_size=20,
            max_overflow=30,
            connect_args={"connect_timeout": 10}
        )
        with test_engine.connect() as conn:
            conn.execute(text("SELECT count(*) FROM users"))
        engine = test_engine
        logger.info("Conexión a PostgreSQL verificada y activa.")
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
