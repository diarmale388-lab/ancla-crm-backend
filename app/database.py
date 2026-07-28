import os
import logging
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session
from typing import Generator
from app.config import settings

logger = logging.getLogger("database")

NEON_OFFICIAL_URL = "postgresql://neondb_owner:npg_u0jKzE8lWQfb@ep-misty-night-aw10uqbm.c-12.us-east-1.aws.neon.tech/neondb?sslmode=require"
SQLITE_FALLBACK_URL = "sqlite:///./crm.db"

# Usar SQLite como base de datos por defecto para garantizar 100% disponibilidad cuando Neon excede cuota
# Para usar Neon Postgres explícitamente cuando esté activa la cuota, configurar USE_NEON=1
use_neon = os.getenv("USE_NEON", "0") == "1"

if use_neon:
    db_url = settings.DATABASE_URL or NEON_OFFICIAL_URL
else:
    db_url = SQLITE_FALLBACK_URL

if db_url.startswith("sqlite"):
    engine = create_engine(
        db_url,
        connect_args={"check_same_thread": False}
    )
    logger.info("Base de datos SQLite activa: ./crm.db")
else:
    try:
        engine = create_engine(
            db_url,
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=5,
            connect_args={"connect_timeout": 3}
        )
        logger.info("Conexión a PostgreSQL (Neon) activa.")
    except Exception as e_pg:
        logger.warning(f"Error conectando a PostgreSQL ({e_pg}). Usando respaldo SQLite local.")
        engine = create_engine(
            SQLITE_FALLBACK_URL,
            connect_args={"check_same_thread": False}
        )

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
