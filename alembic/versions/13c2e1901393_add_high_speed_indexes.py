"""add_high_speed_indexes

Fase 3 - Rendimiento y Velocidad Máxima: índices de alta velocidad para las
consultas más frecuentes del CRM (bandeja de mensajes, listado de contactos
por asesor/pipeline, y agenda de citas).

Se usa CREATE INDEX ... IF NOT EXISTS / DROP INDEX ... IF EXISTS mediante SQL
crudo en lugar de op.create_index/op.drop_index para que la migración sea
idempotente: el esquema de esta base de datos se gestiona históricamente vía
`Base.metadata.create_all()` en el arranque de la app, por lo que estas tablas
ya existen fuera del historial de Alembic.

Revision ID: 13c2e1901393
Revises: c1c3a5d2b2ee
Create Date: 2026-08-24 00:39:46.782753

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '13c2e1901393'
down_revision: Union[str, Sequence[str], None] = 'c1c3a5d2b2ee'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


INDEXES = [
    # (index_name, table, columns_sql)
    ("ix_messages_contact_id_created_at_desc", "messages", "contact_id, created_at DESC"),
    ("ix_contacts_assigned_user_id", "contacts", "assigned_user_id"),
    ("ix_contacts_updated_at", "contacts", "updated_at"),
    ("ix_appointments_status_datetime", "appointments", "status, datetime"),
    ("ix_contacts_pipeline_stage_id", "contacts", "pipeline_stage_id"),
]


def upgrade() -> None:
    """Upgrade schema: crea los índices de alta velocidad (idempotente)."""
    for index_name, table, columns_sql in INDEXES:
        op.execute(
            sa.text(f"CREATE INDEX IF NOT EXISTS {index_name} ON {table} ({columns_sql})")
        )


def downgrade() -> None:
    """Downgrade schema: elimina los índices de alta velocidad."""
    for index_name, _table, _columns_sql in reversed(INDEXES):
        op.execute(sa.text(f"DROP INDEX IF EXISTS {index_name}"))
