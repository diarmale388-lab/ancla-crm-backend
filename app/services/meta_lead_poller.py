import asyncio
import logging
import json
import httpx
from app.database import SessionLocal
from app.models.base import Contact, SystemSetting
from app.services.meta_api import meta_api_service
from app.services.whatsapp import VERIFIED_META_TOKEN

logger = logging.getLogger("meta_lead_poller")

DEFAULT_FORM_IDS = [
    "4053533344778702", 
    "1746047406714617", 
    "120248029650450318",
    "2474966606041075",
    "1055357215224734"
]

def get_active_form_ids(db) -> list:
    """
    Obtiene la lista dinámica de IDs de formularios desde SystemSetting.
    Si no existe, la inicializa con los formularios conocidos.
    """
    setting = db.query(SystemSetting).filter(SystemSetting.key == "registered_form_ids").first()
    if setting and setting.value:
        try:
            ids = json.loads(setting.value)
            if isinstance(ids, list):
                # Combinar con los por defecto para asegurar cobertura total
                combined = list(set(ids + DEFAULT_FORM_IDS))
                return combined
        except Exception as e:
            logger.error(f"Error parseando registered_form_ids de BD: {e}")
    
    # Si no existe, guardar la lista por defecto
    try:
        setting = SystemSetting(key="registered_form_ids", value=json.dumps(DEFAULT_FORM_IDS))
        db.add(setting)
        db.commit()
    except Exception as e_save:
        logger.error(f"Error inicializando registered_form_ids en BD: {e_save}")
        db.rollback()
        
    return DEFAULT_FORM_IDS

def register_new_form_id(db, new_form_id: str):
    """
    Registra dinámicamente un nuevo Form ID en la base de datos para que el poller lo escanee automáticamente.
    """
    if not new_form_id or not str(new_form_id).strip():
        return
    new_form_id = str(new_form_id).strip()
    
    setting = db.query(SystemSetting).filter(SystemSetting.key == "registered_form_ids").first()
    ids = DEFAULT_FORM_IDS
    if setting and setting.value:
        try:
            ids = json.loads(setting.value)
        except Exception:
            ids = DEFAULT_FORM_IDS
            
    if new_form_id not in ids:
        ids.append(new_form_id)
        if not setting:
            setting = SystemSetting(key="registered_form_ids", value=json.dumps(ids))
            db.add(setting)
        else:
            setting.value = json.dumps(ids)
            db.add(setting)
        try:
            db.commit()
            logger.info(f"✨ Nuevo Form ID '{new_form_id}' registrado dinámicamente en el Poller del CRM.")
        except Exception as e:
            db.rollback()
            logger.error(f"Error guardando nuevo form ID en BD: {e}")

async def poll_meta_leads_loop():
    """
    Poller en segundo plano que consulta Meta Graph API cada 60 segundos 
    para garantizar que NINGÚN lead de formularios de Meta Ads se quede sin ingresar al CRM.
    """
    logger.info("🚀 Iniciando Poller Automático Dinámico de Leads de Meta Ads (Intervalo: 60s)...")
    await asyncio.sleep(5)  # Espera inicial para estabilizar el arranque
    
    while True:
        try:
            db = SessionLocal()
            try:
                # Leer token
                setting = db.query(SystemSetting).filter(SystemSetting.key == "meta_access_token").first()
                token = setting.value if (setting and setting.value) else VERIFIED_META_TOKEN
                
                # Leer lista dinámica de formularios
                active_form_ids = get_active_form_ids(db)
                
                async with httpx.AsyncClient() as client:
                    for form_id in active_form_ids:
                        leads_url = f"https://graph.facebook.com/v18.0/{form_id}/leads?access_token={token}&limit=25"
                        res = await client.get(leads_url, timeout=10.0)
                        if res.status_code == 200:
                            leads_data = res.json().get("data", [])
                            for lead_obj in leads_data:
                                lead_id = lead_obj.get("id")
                                if lead_id:
                                    lead_detail = await meta_api_service.fetch_leadgen_details(lead_id, db)
                                    if lead_detail:
                                        phone = lead_detail.get("phone") or lead_detail.get("phone_number")
                                        if phone:
                                            existing = db.query(Contact).filter(Contact.phone == phone).first()
                                            if not existing:
                                                logger.info(f"✨ Poller automático encontró un nuevo lead en Meta (Form {form_id}): {lead_detail.get('full_name')} ({phone})")
                                                from app.services.leadgen_service import process_leadgen_submission
                                                await process_leadgen_submission(db, lead_detail)
            except Exception as e_poll:
                logger.error(f"Error en ciclo de polling de leads: {e_poll}")
            finally:
                db.close()
        except Exception as e_main:
            logger.error(f"Error general en bucle de polling: {e_main}")

        await asyncio.sleep(60)
