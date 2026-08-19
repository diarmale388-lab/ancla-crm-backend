import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.database import SessionLocal
from app.models.base import User, PipelineStage
from app.core.security import get_password_hash

def inspect_and_seed():
    db = SessionLocal()
    try:
        users = db.query(User).all()
        print(f"Total usuarios en BD: {len(users)}")
        for u in users:
            print(f"ID: {u.id}, Email: '{u.email}', Rol: '{u.role}', Nombre: '{u.full_name}'")

        if not users:
            print("No hay usuarios en la BD. Creando usuario admin por defecto...")
            admin = User(
                email="admin@crm.com",
                hashed_password=get_password_hash("adminpassword"),
                full_name="Administrador Principal",
                role="admin",
                is_active=True
            )
            db.add(admin)
            db.commit()
            print("Usuario admin creado: admin@crm.com")
        else:
            print(f"Usuarios verificados ({len(users)} existentes). Preservando credenciales intactas.")

        stages = db.query(PipelineStage).all()
        print(f"Total etapas de Pipeline: {len(stages)}")
        if not stages:
            print("Creando etapas por defecto de Pipeline...")
            default_stages = [
                PipelineStage(name="Lead Nuevo", position=1),
                PipelineStage(name="Contacto Iniciado", position=2),
                PipelineStage(name="Llamada Agendada", position=3),
                PipelineStage(name="Propuesta Enviada", position=4),
                PipelineStage(name="Negociación", position=5),
                PipelineStage(name="Ganado (Cierre)", position=6),
                PipelineStage(name="Perdido", position=7)
            ]
            db.add_all(default_stages)
            db.commit()
            print("Etapas Kanban creadas exitosamente.")

    finally:
        db.close()

if __name__ == "__main__":
    inspect_and_seed()
