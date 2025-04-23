# app/routes/alert.py
import os
import json
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from typing import Optional

router = APIRouter(
    tags=["Alertes / Logs"]
)

# Chemin vers le fichier JSON d'alerte (configurable via .env)
ALERT_FILE = os.getenv("MB2_ALERT_FILE", "app/alerts.json")

class AlertStatus(BaseModel):
    has_error: bool
    message: str
    count: Optional[int] = 0

@router.get(
    "/status",
    response_model=AlertStatus,
    summary="Statut actuel des alertes de logs",
    responses={
        200: {"description": "Statut d'alerte retourné avec succès", "content": {"application/json": {"example": {"has_error": True , "message": "Erreur critique détectée - 19/04 14:00", "count": 3}}}},
        500: {"description": "Erreur lecture fichier d'alerte"}
    }
)
def get_alert_status():
    """
    Renvoie le contenu de alerts.json, indiquant s'il y a des erreurs critiques.
    """
    if not os.path.exists(ALERT_FILE):
        return AlertStatus(has_error=False, message="Aucune alerte détectée", count=0)
    try:
        with open(ALERT_FILE, "r") as f:
            data = json.load(f)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Impossible de lire le fichier d'alerte : {e}"
        )
    try:
        return AlertStatus(**data)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Format d'alerte invalide : {e}"
        )
