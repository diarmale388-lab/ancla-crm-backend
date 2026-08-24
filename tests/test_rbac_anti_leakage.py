import sys
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.database import SessionLocal
from app.models.base import User, Contact, Appointment, UserRole
from app.core.security import create_access_token

client = TestClient(app)

@pytest.fixture(scope="module")
def db_session():
    db = SessionLocal()
    yield db
    db.close()

@pytest.fixture(scope="module")
def admin_headers(db_session):
    admin = db_session.query(User).filter(User.role == UserRole.ADMIN, User.is_active == True).first()
    token = create_access_token(subject=admin.id)
    return {"Authorization": f"Bearer {token}"}

@pytest.fixture(scope="module")
def asesor_headers(db_session):
    asesor = db_session.query(User).filter(User.role == UserRole.ASESOR, User.is_active == True).first()
    token = create_access_token(subject=asesor.id)
    return {"Authorization": f"Bearer {token}"}

def test_asesor_cannot_view_unassigned_contacts(asesor_headers, db_session):
    """Prueba 1: Un asesor comercial NUNCA puede listar contactos sin asignar"""
    res = client.get("/api/v1/chats/contacts", headers=asesor_headers)
    assert res.status_code == 200
    contacts = res.json()
    asesor = db_session.query(User).filter(User.role == UserRole.ASESOR, User.is_active == True).first()
    for c in contacts:
        assert c["assigned_user_id"] == asesor.id, f"Fuga de contacto detectada: Contacto #{c['id']} visible para asesor {asesor.id}"

def test_asesor_cannot_view_unassigned_chat_messages(asesor_headers, db_session):
    """Prueba 2: Un asesor comercial no puede abrir mensajes de un lead ajeno o sin asignar"""
    unassigned = db_session.query(Contact).filter(Contact.assigned_user_id == None).first()
    if unassigned:
        res = client.get(f"/api/v1/chats/{unassigned.id}/messages", headers=asesor_headers)
        assert res.status_code in [403, 404], "Fuga detectada: Asesor pudo consultar mensajes de lead sin asignar"

def test_asesor_blocked_from_assigning_contacts(asesor_headers, db_session):
    """Prueba 3: Un asesor comercial NO puede reasignar contactos"""
    unassigned = db_session.query(Contact).filter(Contact.assigned_user_id == None).first()
    if unassigned:
        res = client.patch(
            f"/api/v1/chats/{unassigned.id}/details",
            json={"assigned_user_id": 4},
            headers=asesor_headers
        )
        assert res.status_code == 403, "Fuga crítica: Asesor pudo modificar assigned_user_id en chats"

def test_asesor_blocked_from_pipeline_reassignment(asesor_headers, db_session):
    """Prueba 4: Un asesor comercial NO puede reasignar leads en el pipeline"""
    unassigned = db_session.query(Contact).filter(Contact.assigned_user_id == None).first()
    if unassigned:
        res = client.patch(
            f"/api/v1/pipeline/leads/{unassigned.id}/details",
            json={"assigned_user_id": 4},
            headers=asesor_headers
        )
        assert res.status_code == 403, "Fuga crítica: Asesor pudo modificar assigned_user_id en pipeline"

def test_asesor_blocked_from_configuring_availability(asesor_headers):
    """Prueba 5: Un asesor comercial no puede alterar horarios de atención"""
    res = client.post("/api/v1/appointments/availability", json={"days": []}, headers=asesor_headers)
    assert res.status_code == 403, "Fuga crítica: Asesor pudo configurar horarios de atención"

def test_asesor_blocked_from_showroom_endpoints(asesor_headers):
    """Prueba 6: Un asesor comercial no puede acceder al dashboard o JSON del Showroom"""
    res1 = client.get("/dashboard-showroom-2026", headers=asesor_headers)
    assert res1.status_code in [403, 401], "Fuga crítica: Asesor pudo acceder a /dashboard-showroom-2026"
    res2 = client.get("/showroom-citas-json", headers=asesor_headers)
    assert res2.status_code in [403, 401], "Fuga crítica: Asesor pudo acceder a /showroom-citas-json"

def test_admin_has_full_access(admin_headers, db_session):
    """Prueba 7: El Administrador / Liliana León tiene acceso total a todos los prospectos"""
    res = client.get("/api/v1/chats/contacts", headers=admin_headers)
    assert res.status_code == 200
    total_db_contacts = db_session.query(Contact).count()
    assert len(res.json()) == total_db_contacts, "Inconsistencia: El administrador no está viendo el 100% de los contactos"
