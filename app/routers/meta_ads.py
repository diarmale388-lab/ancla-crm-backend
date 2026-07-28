import logging
from typing import List, Any
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.base import User, Campaign, Contact
from app.schemas.campaign import CampaignCreate, CampaignUpdate, CampaignResponse
from app.core.deps import get_current_user
from app.services.meta_api import meta_api_service

logger = logging.getLogger("meta_ads_router")

router = APIRouter(prefix="/meta-ads", tags=["meta-ads"])

@router.post("/sync-now")
async def trigger_immediate_leads_sync(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> Any:
    """
    Ejecuta un escaneo inmediato síncrono de todos los formularios registrados en Meta Ads
    para ingresar instantáneamente cualquier lead pendiente al CRM.
    """
    from app.services.meta_lead_poller import get_active_form_ids
    from app.services.whatsapp import VERIFIED_META_TOKEN
    from app.services.leadgen_service import process_leadgen_submission
    from app.models.base import SystemSetting
    import httpx

    setting = db.query(SystemSetting).filter(SystemSetting.key == "meta_access_token").first()
    token = setting.value if (setting and setting.value) else VERIFIED_META_TOKEN
    active_forms = get_active_form_ids(db)
    
    imported_list = []
    async with httpx.AsyncClient() as client:
        for form_id in active_forms:
            leads_url = f"https://graph.facebook.com/v18.0/{form_id}/leads?access_token={token}&limit=50"
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
                                    c_new = await process_leadgen_submission(db, lead_detail)
                                    imported_list.append({"id": c_new.id, "phone": c_new.phone, "name": f"{c_new.first_name} {c_new.last_name or ''}"})

    return {"status": "success", "synced_count": len(imported_list), "new_contacts": imported_list}

@router.post("/register-form")
def register_new_meta_form(
    form_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> Any:
    """
    Registra dinámicamente un nuevo Form ID de Meta Ads en el Poller del CRM.
    """
    from app.services.meta_lead_poller import register_new_form_id
    register_new_form_id(db, form_id)
    return {"status": "success", "message": f"Formulario ID '{form_id}' registrado exitosamente."}

@router.get("/campaigns", response_model=List[CampaignResponse])
def list_campaigns(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> Any:
    """
    Lista todas las campañas publicitarias registradas en el sistema.
    """
    campaigns = db.query(Campaign).order_by(Campaign.created_at.desc()).all()
    return campaigns


@router.post("/campaigns", response_model=CampaignResponse)
async def create_new_campaign(
    payload: CampaignCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> Any:
    """
    Crea una nueva campaña publicitaria tanto en Meta Ads como en la base de datos local.
    """
    # 1. Enviar creación a la Meta Marketing API
    meta_id = await meta_api_service.create_campaign(
        name=payload.name,
        objective=payload.objective,
        budget=payload.budget
    )
    
    if not meta_id:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="No se pudo crear la campaña en Meta Ads."
        )

    # 2. Registrar en la base de datos local
    db_campaign = Campaign(
        meta_campaign_id=meta_id,
        name=payload.name,
        objective=payload.objective,
        budget=payload.budget,
        status="PAUSED",  # Por seguridad se crea inicialmente pausada
        synced_at=datetime.utcnow()
    )
    db.add(db_campaign)
    db.commit()
    db.refresh(db_campaign)
    
    return db_campaign


@router.patch("/campaigns/{campaign_id}/status", response_model=CampaignResponse)
async def toggle_campaign_status(
    campaign_id: int,
    payload: CampaignUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> Any:
    """
    Pausa o activa una campaña publicitaria en Meta Ads y actualiza su estado local.
    """
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaña no encontrada")

    new_status = payload.status.upper() # ACTIVE, PAUSED, etc.
    if new_status not in ["ACTIVE", "PAUSED"]:
        raise HTTPException(status_code=400, detail="Estado inválido. Use ACTIVE o PAUSED.")

    # 1. Enviar actualización a Meta
    success = await meta_api_service.update_campaign_status(
        meta_campaign_id=campaign.meta_campaign_id,
        new_status=new_status
    )
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="No se pudo actualizar el estado en Meta Ads."
        )

    # 2. Actualizar localmente
    campaign.status = new_status
    campaign.updated_at = datetime.utcnow()
    db.add(campaign)
    db.commit()
    db.refresh(campaign)
    
    return campaign


@router.post("/campaigns/sync", response_model=List[CampaignResponse])
async def sync_campaigns_metrics(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> Any:
    """
    Sincroniza el rendimiento (spend, clicks, impressions) de todas las campañas
    locales consumiendo la Meta Marketing API y recalculando métricas de negocio.
    """
    campaigns = db.query(Campaign).all()
    
    for campaign in campaigns:
        # 1. Obtener insights desde la API de Meta
        metrics = await meta_api_service.get_campaign_metrics(campaign.meta_campaign_id)
        if not metrics:
            continue
            
        campaign.impressions = metrics.get("impressions", 0)
        campaign.clicks = metrics.get("clicks", 0)
        campaign.spend = metrics.get("spend", 0.0)
        
        # 2. Calcular número real de leads en el CRM procedentes de esta campaña
        # Para esto, filtramos contactos cuya fuente coincida con el nombre de la campaña
        # o que tengan asociado el ID de la campaña en Meta
        leads_in_db = db.query(Contact).filter(
            (Contact.source == campaign.name) | (Contact.meta_lead_id == campaign.meta_campaign_id)
        ).count()
        
        # Si es simulado/mock, podemos mezclar datos de leads de Meta con los de la base de datos
        if metrics.get("leads_count", 0) > 0 and leads_in_db == 0:
            campaign.leads_count = metrics["leads_count"]
        else:
            campaign.leads_count = max(leads_in_db, metrics.get("leads_count", 0))

        # 3. Calcular CPL, CPA y ROAS
        if campaign.leads_count > 0:
            campaign.cpl = round(campaign.spend / campaign.leads_count, 2)
            # CPA es similar para este negocio, simulemos conversión a cliente del 15% de los leads
            conversions = max(1, int(campaign.leads_count * 0.15))
            campaign.cpa = round(campaign.spend / conversions, 2)
            # ROAS: Retorno = conversiones * valor de ticket promedio ($450 USD) / inversión
            revenue = conversions * 450.0
            campaign.roas = round(revenue / campaign.spend, 2) if campaign.spend > 0 else 0.0
        else:
            campaign.cpl = 0.0
            campaign.cpa = 0.0
            campaign.roas = 0.0
            
        campaign.synced_at = datetime.utcnow()
        db.add(campaign)
        
    db.commit()
    
    # Devolver campañas actualizadas
    return db.query(Campaign).order_by(Campaign.created_at.desc()).all()
