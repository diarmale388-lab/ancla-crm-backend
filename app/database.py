import os
import logging
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.exc import SQLAlchemyError
from typing import Generator
from app.config import settings

logger = logging.getLogger("database")

SQLITE_FALLBACK_URL = "sqlite:///./crm.db"

raw_db_url = os.getenv("DATABASE_URL") or settings.DATABASE_URL

# Modo de entorno: en producción NO se permite el respaldo silencioso a SQLite.
# Si DATABASE_URL apunta a Postgres/Neon y la conexión falla, se debe fallar de
# forma explícita en lugar de degradar silenciosamente a una base de datos local
# efímera (lo cual causaba pérdida de datos y comportamiento inconsistente).
ENVIRONMENT = os.getenv("ENVIRONMENT", "production").lower()
IS_PRODUCTION = ENVIRONMENT not in ("development", "dev", "local", "test", "testing")

if raw_db_url and not raw_db_url.startswith("sqlite"):
    # Pool ajustado para Neon Serverless / PgBouncer (modo "transaction pooling"):
    # - pool_size bajo: Neon Pooler multiplexa muchas conexiones lógicas sobre
    #   pocas conexiones físicas; pools grandes desde el backend son
    #   contraproducentes y agotan los slots del pooler.
    # - max_overflow bajo: solo un margen pequeño para picos de tráfico.
    # - pool_recycle=300: recicla conexiones cada 5 min para evitar que Neon
    #   las cierre por inactividad (idle timeout) y el driver reciba errores.
    # - pool_pre_ping: valida la conexión antes de usarla (evita "conexión
    #   cerrada por el servidor" tras escalados a cero de Neon).
    try:
        engine = create_engine(
            raw_db_url,
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=5,
            pool_recycle=300,
            connect_args={"connect_timeout": 10},
        )
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        logger.info("Conexión a PostgreSQL (Neon) verificada y activa.")
    except Exception as e_pg:
        if IS_PRODUCTION:
            # Sin respaldo silencioso en producción: un fallo de conexión a
            # Postgres debe detener el arranque de la aplicación, no degradar
            # a SQLite de forma invisible.
            logger.critical(
                f"No se pudo establecer conexión con PostgreSQL/Neon en producción: {e_pg}"
            )
            raise RuntimeError(
                "No se pudo conectar a la base de datos PostgreSQL (Neon) configurada en "
                "DATABASE_URL. Se aborta el arranque para evitar el uso silencioso de un "
                f"respaldo local en producción. Detalle: {e_pg}"
            ) from e_pg
        logger.warning(
            f"No se pudo consultar PostgreSQL ({e_pg}). Entorno de desarrollo detectado: "
            "activando respaldo a SQLite local."
        )
        engine = create_engine(
            SQLITE_FALLBACK_URL,
            connect_args={"check_same_thread": False},
        )
elif IS_PRODUCTION:
    # En producción es obligatorio tener un DATABASE_URL de Postgres válido.
    raise RuntimeError(
        "DATABASE_URL no está configurado (o apunta a SQLite) en un entorno de producción. "
        "Configure la variable de entorno DATABASE_URL con la cadena de conexión de Neon/PostgreSQL."
    )
else:
    engine = create_engine(
        SQLITE_FALLBACK_URL,
        connect_args={"check_same_thread": False},
    )
    logger.info("Base de datos SQLite activa por defecto (entorno de desarrollo): ./crm.db")

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def init_db():
    try:
        from app.models.base import Base
        Base.metadata.create_all(bind=engine)
    except SQLAlchemyError as e:
        if IS_PRODUCTION:
            raise
        logger.warning(f"Advertencia creando tablas en BD: {e}")

init_db()

def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
