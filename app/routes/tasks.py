# app/routes/tasks.py
from fastapi import APIRouter, HTTPException, status, Query
from typing import List
from app.schemas import ReanalyseRequest, TaskLaunchResponse, TaskStatus
from app.celery_tasks import moissonner, reanalyser_articles_nlp
import os

router = APIRouter(
    tags=["Tâches / Celery"]
)

# Tables autorisées pour la réanalyse
TASK_TABLES = ["articles_openalex", "articles_oai"]

@router.post(
    "/moissonner",
    summary="Lance le moissonnage Celery",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=TaskLaunchResponse,
    responses={
        202: {"description": "Tâche de moissonnage démarrée", "content": {"application/json": {"example": {"message": "✅ Moissonnage lancé via Celery", "task_id": "abcd1234"}}}},
        500: {"description": "Erreur interne lors du lancement de la tâche"}
    }
)
def lancer_moissonnage() -> TaskLaunchResponse:
    """Lance une tâche Celery pour moissonner les articles."""
    try:
        task = moissonner.delay()
        return TaskLaunchResponse(message="✅ Moissonnage lancé via Celery", task_id=task.id)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))

@router.post(
    "/reanalyser",
    summary="Lance la réanalyse NLP Celery",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=TaskLaunchResponse,
    responses={
        202: {"description": "Tâche de réanalyse lancée", "content": {"application/json": {"example": {"message": "🔁 Réanalyse NLP lancée pour articles_openalex", "limit": 50, "task_id": "efgh5678"}}}},
        400: {"description": "Requête invalide (table non autorisée)"},
        500: {"description": "Erreur interne lors du lancement de la tâche"}
    }
)
def relancer_analyse_nlp(request: ReanalyseRequest) -> TaskLaunchResponse:
    """Lance une tâche Celery pour réanalyser les articles (NLP)."""
    if request.table not in TASK_TABLES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Table non autorisée. Tables valides : {', '.join(TASK_TABLES)}"
        )
    try:
        task = reanalyser_articles_nlp.delay(request.table, request.limit)
        return TaskLaunchResponse(message=f"🔁 Réanalyse NLP lancée pour {request.table}", limit=request.limit, task_id=task.id)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))

@router.get(
    "/status",
    summary="Statut des tâches Celery planifiées",
    response_model=TaskStatus,
    responses={
        200: {"description": "Liste des tâches planifiées", "content": {"application/json": {"example": {"planned_tasks": ["moissonner.articles", "reanalyser.batch"], "description": "Tâches exécutées chaque nuit via Celery Beat."}}}},
        500: {"description": "Erreur interne lors de la récupération du statut"}
    }
)
def get_tasks_status() -> TaskStatus:
    """Liste les tâches Celery planifiées."""
    try:
        return TaskStatus(
            planned_tasks=["moissonner.articles", "reanalyser.batch"],
            description="Ces tâches sont exécutées chaque nuit via Celery Beat."
        )
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))

@router.get(
    "/logs",
    summary="Récupère les dernières lignes du log Celery",
    responses={
        200: {"description": "Dernières lignes de log", "content": {"application/json": {"example": {"logs": ["INFO Task succeeded...", "ERROR Something failed..."]}}}},
        500: {"description": "Erreur lecture fichier de log"}
    }
)
def lire_logs(limit: int = Query(50, ge=1, le=500, description="Nombre de lignes à retourner")):
    """Renvoie les dernières lignes du fichier de log Celery."""
    log_path = os.getenv("CELERY_LOG_PATH", "logs/celery_tasks.log")
    if not os.path.exists(log_path):
        return {"message": "Aucun log trouvé."}
    try:
        with open(log_path, "r", encoding="utf-8") as f:
            lines = f.readlines()[-limit:]
        return {"logs": lines}
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))
