import re
import logging
from typing import Dict, Optional, Tuple
from sqlalchemy.orm import Session
from app.models.base import Contact

logger = logging.getLogger("form_parser")

def parse_form_text_to_dict(raw_text: str) -> Dict[str, str]:
    """
    Parsea un texto que contiene pares clave: valor de formularios de Meta Ads o mensajes pre-llenados de WhatsApp.
    Ejemplo:
    ¿Ya cuentas con un terreno o lote propio?: Sí, ya tengo
    Full name: Juan Manuel Uribe Tarazona
    Email: correo@domain.com
    """
    parsed_fields: Dict[str, str] = {}
    if not raw_text:
        return parsed_fields

    lines = raw_text.splitlines()
    for line in lines:
        line_str = line.strip()
        if not line_str or line_str.startswith("¡Hola!") or line_str.startswith("http"):
            continue
        
        if ":" in line_str:
            parts = line_str.split(":", 1)
            key = parts[0].strip()
            val = parts[1].strip()
            
            # Quitar viñetas u caracteres especiales si los hay
            key = re.sub(r'^[•\-\*\>]\s*', '', key).strip()
            
            if key and val and key.lower() not in ["inbox url", "url"]:
                parsed_fields[key] = val
                
    return parsed_fields

def parse_and_update_contact_from_text(contact: Contact, raw_text: str, db: Session) -> bool:
    """
    Extrae dinámicamente todas las preguntas y respuestas del texto y actualiza el objeto Contact.
    Persiste en qualification_notes un bloque formateado completo con TODA la información entregada por el cliente.
    """
    parsed = parse_form_text_to_dict(raw_text)
    if not parsed:
        return False

    updated = False

    # Mapear campos conocidos a atributos de Contact
    for key, val in parsed.items():
        k_lower = key.lower()
        val_str = val.strip()
        if not val_str:
            continue

        # 1. Nombre Completo
        if any(w in k_lower for w in ["full name", "full_name", "nombre completo", "nombre"]):
            if not contact.first_name or len(contact.first_name) < 3 or contact.first_name.lower() in ["cliente", "lead"]:
                parts = val_str.split()
                contact.first_name = parts[0] if parts else "Cliente"
                contact.last_name = " ".join(parts[1:]) if len(parts) > 1 else ""
                updated = True

        # 2. Correo Electrónico
        elif any(w in k_lower for w in ["email", "correo"]):
            if not contact.email or "@" not in contact.email:
                contact.email = val_str.lower()
                updated = True

        # 3. Ciudad / Ubicación Lote
        elif any(w in k_lower for w in ["ciudad", "departamento", "construir", "city", "ubicación", "ubicacion", "dónde", "donde"]):
            if not contact.lot_city or contact.lot_city.lower() in ["armenia", "por definir"]:
                contact.lot_city = val_str
                updated = True

        # 4. Estado del Lote
        elif any(w in k_lower for w in ["terreno", "lote", "propio"]):
            if not contact.lot_status or contact.lot_status.lower() in ["por definir", "sí, ya tengo"]:
                contact.lot_status = val_str
                updated = True

        # 5. Propósito / Modelo
        elif any(w in k_lower for w in ["propósito", "proposito", "proyecto", "modelo", "interés", "interes"]):
            if not contact.interest_product or contact.interest_product.lower() in ["vivienda / campestre", "flex home"]:
                contact.interest_product = val_str
                updated = True

    # Construir bloque formateado visualmente con TODAS las respuestas del formulario
    notes_lines = ["📋 **RESPUESTAS DEL FORMULARIO META ADS**:"]
    for k, v in parsed.items():
        notes_lines.append(f"• **{k}**: {v}")

    formatted_notes_block = "\n".join(notes_lines)

    # Actualizar qualification_notes preservando etiquetas existentes (ej: [Meta Ads Atribución], [LISTA_ESPERA_VIP])
    current_notes = contact.qualification_notes or ""
    if "📋 **RESPUESTAS DEL FORMULARIO META ADS**:" in current_notes:
        # Reemplazar el bloque existente por el actualizado
        lines_before = []
        for line in current_notes.splitlines():
            if "📋 **RESPUESTAS DEL FORMULARIO META ADS**:" in line:
                break
            lines_before.append(line)
        prefix = "\n".join(lines_before).strip()
        if prefix:
            contact.qualification_notes = f"{prefix}\n\n{formatted_notes_block}"
        else:
            contact.qualification_notes = formatted_notes_block
    else:
        if current_notes.strip():
            contact.qualification_notes = f"{formatted_notes_block}\n\n{current_notes.strip()}"
        else:
            contact.qualification_notes = formatted_notes_block

    updated = True
    db.add(contact)
    db.commit()
    db.refresh(contact)
    logger.info(f"Formulario parseado y guardado exitosamente para Contact ID #{contact.id} ({contact.first_name}).")
    return updated
