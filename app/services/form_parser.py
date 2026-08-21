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
    updated_any = False

    # Detección directa de emails en mensajes libres (ej: "Jairo Ernesto Garzon forero\njairogarzon972@gmail.com")
    email_pattern = re.search(r'[\w\.-]+@[\w\.-]+\.\w+', raw_text)
    if email_pattern:
        found_email = email_pattern.group().lower().strip()
        if not contact.email or contact.email != found_email:
            contact.email = found_email
            updated_any = True
            logger.info(f"Correo de Contacto #{contact.id} actualizado automáticamente a: {found_email}")

        # Intentar extraer el nombre completo del texto libre si el nombre actual es un apodo/username o está vacío
        text_without_email = raw_text.replace(email_pattern.group(), "").strip()
        clean_lines = [line.strip() for line in text_without_email.splitlines() if line.strip() and not line.strip().startswith("¡") and not line.strip().startswith("http")]
        if clean_lines:
            candidate_name = clean_lines[0]
            words = [w for w in re.split(r'\s+', candidate_name) if w.isalpha()]
            if 1 <= len(words) <= 5:
                is_nickname = not contact.first_name or any(c.isdigit() for c in contact.first_name) or len(contact.first_name) < 3 or contact.first_name.lower() in ["cliente", "lead", "hola"]
                if is_nickname:
                    contact.first_name = words[0].capitalize()[:100]
                    contact.last_name = (" ".join([w.capitalize() for w in words[1:]]))[:100]
                    updated_any = True
                    logger.info(f"Nombre de Contacto #{contact.id} actualizado a: {contact.first_name} {contact.last_name}")

    if updated_any:
        db.add(contact)
        db.commit()

    parsed = parse_form_text_to_dict(raw_text)
    if not parsed:
        return updated_any

    updated = False

    # Mapear campos conocidos a atributos de Contact
    for key, val in parsed.items():
        k_lower = key.lower()
        val_str = val.strip()
        if not val_str:
            continue

        # 1. Nombre Completo Oficial desde Formulario Meta Ads
        if any(w in k_lower for w in ["full name", "full_name", "nombre completo", "nombre"]):
            parts = val_str.split()
            if parts:
                contact.first_name = parts[0][:100]
                contact.last_name = (" ".join(parts[1:]))[:100] if len(parts) > 1 else ""
                updated = True
                logger.info(f"Nombre oficial de Formulario aplicado a Contacto #{contact.id}: {contact.first_name} {contact.last_name}")

        # 2. Correo Electrónico
        elif any(w in k_lower for w in ["email", "correo"]):
            if not contact.email or "@" not in contact.email:
                contact.email = val_str.lower()[:255]
                updated = True

        # 3. Ciudad / Ubicación Lote
        elif any(w in k_lower for w in ["ciudad", "departamento", "construir", "city", "ubicación", "ubicacion", "dónde", "donde"]):
            contact.lot_city = val_str[:100]
            updated = True

        # 4. Estado del Lote
        elif any(w in k_lower for w in ["terreno", "lote", "propio"]):
            contact.lot_status = val_str[:100]
            updated = True

        # 5. Propósito / Modelo de Interés
        elif any(w in k_lower for w in ["propósito", "proposito", "modelo", "interés", "interes", "proyecto"]):
            contact.interest_product = val_str[:100]
            updated = True

        # 6. Presupuesto / Inversión
        elif any(w in k_lower for w in ["presupuesto", "inversión", "inversion", "rango", "dinero", "valor"]):
            num_match = re.search(r'\d[\d\.\,]*', val_str.replace('.', '').replace(',', ''))
            if num_match:
                try:
                    contact.estimated_budget = float(num_match.group())
                    updated = True
                except Exception:
                    pass

        # 7. Método de Contacto Preferido
        elif any(w in k_lower for w in ["prefieres", "asesoría", "asesoria", "recibir", "contacto", "medio"]):
            contact.preferred_contact_method = val_str[:100]
            updated = True

        # 8. Perfil del Cliente (Persona Natural vs Empresa vs Inversionista)
        elif any(w in k_lower for w in ["persona natural", "empresa", "perfil", "tipo de cliente", "contactas como", "visitas como", "titular"]):
            v_lower = val_str.lower()
            if "persona natural" in v_lower or "natural" in v_lower:
                contact.client_type = "Persona Natural"
            elif "inversion" in v_lower or "inversionista" in v_lower:
                contact.client_type = "Inversionista"
            elif "empresa" in v_lower or "empresario" in v_lower or "corporativo" in v_lower:
                contact.client_type = "Empresario"
            else:
                contact.client_type = val_str[:100]
            updated = True

    # 9. Fallback inteligente de client_type si aún no está definido
    if not contact.client_type or contact.client_type in ["Por definir", "None"]:
        prod_lower = (contact.interest_product or "").lower()
        if any(w in prod_lower for w in ["glamping", "turismo", "hotelería", "hotel", "renta"]):
            contact.client_type = "Inversionista"
            updated = True
        elif any(w in prod_lower for w in ["vivienda", "campestre", "propia", "casa", "familiar"]):
            contact.client_type = "Persona Natural"
            updated = True
        elif any(w in prod_lower for w in ["bodega", "oficina", "comercial", "industrial"]):
            contact.client_type = "Empresario"
            updated = True
        else:
            contact.client_type = "Persona Natural"
            updated = True

    # Diagnosticar si es Lead VIP (Tiene terreno propio)
    if contact.lot_status and any(w in contact.lot_status.lower() for w in ["sí", "si", "tengo", "propio"]):
        if not contact.qualification_level or contact.qualification_level.lower() not in ["vip", "alto"]:
            contact.qualification_level = "VIP"
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
