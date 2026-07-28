import os
import logging
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session
from typing import Generator
from app.config import settings

logger = logging.getLogger("database")

NEON_OFFICIAL_URL = "postgresql://neondb_owner:npg_u0jKzE8lWQfb@ep-misty-night-aw10uqbm.c-12.us-east-1.aws.neon.tech/neondb?sslmode=require"
SQLITE_FALLBACK_URL = "sqlite:///./crm.db"

# Si Neon DB está sobre la cuota o se fuerza SQLite, usar SQLite directamente
use_sqlite = os.getenv("USE_SQLITE", "0") == "1"
db_url = settings.DATABASE_URL or NEON_OFFICIAL_URL

if use_sqlite or "sqlite" in (db_url or "").lower():
    db_url = SQLITE_FALLBACK_URL

pg_engine = None
sqlite_engine = create_engine(SQLITE_FALLBACK_URL, connect_args={"check_same_thread": False})

if db_url and not db_url.startswith("sqlite"):
    try:
        test_engine = create_engine(
            db_url,
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=5,
            connect_args={"connect_timeout": 3}
        )
        with test_engine.connect() as conn:
            conn.execute(text("SELECT count(*) FROM users"))
        pg_engine = test_engine
        logger.info("Conexión a PostgreSQL (Neon) verificada exitosamente.")
    except Exception as e_pg:
        logger.warning(f"Error conectando a PostgreSQL ({e_pg}). Usando respaldo SQLite local.")
        pg_engine = None

# Definir motor primario y secundario
engine = pg_engine if pg_engine is not None else sqlite_engine

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
SqliteSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=sqlite_engine)

def get_db() -> Generator[Session, None, None]:
    # Si PostgreSQL no está disponible, devolver directamente la sesión de SQLite
    if pg_engine is None:
        db = SqliteSessionLocal()
        try:
            yield db
        finally:
            db.close()
        return

    # Si PostgreSQL está configurado, intentar usarlo y conmutar a SQLite en caso de fallo de cuota
    db = SessionLocal()
    try:
        yield db
    except Exception as e_db:
        err_msg = str(e_db).lower()
        if "quota" in err_msg or "operationalerror" in err_msg or "connection to server" in err_msg:
            logger.error("Error de cuota/conexión PostgreSQL detectado. Conmutando sesión a SQLite local...")
            db.close()
            db = SqliteSessionLocal()
            try:
                yield db
            finally:
                db.close()
        else:
            raise
    finally:
        try:
            db.close()
        except Exception:
            pass
