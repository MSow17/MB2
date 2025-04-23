# app/routes/stats.py

from fastapi import APIRouter, HTTPException, status
from typing import Dict, Any

from psycopg2 import ProgrammingError
from app.database import DatabaseManager
from app.schemas import GlobalStats

router = APIRouter(
    tags=["Statistiques"]
)

@router.get(
    "/",
    summary="Statistiques globales sur les articles et controverses",
    response_model=GlobalStats,
    responses={
        200: {
            "description": "Statistiques calculées avec succès",
            "content": {
                "application/json": {
                    "example": {
                        "openalex": {"total": 1200, "controverses": 150},
                        "oai":      {"total":  800, "controverses":  75},
                        "total": 2000,
                        "total_controverses": 225
                    }
                }
            }
        },
        500: {"description": "Erreur interne lors du calcul des statistiques"}
    }
)
def get_stats() -> Dict[str, Any]:
    """
    Récupère le nombre total d'articles et de controverses
    pour OpenAlex et OAI-PMH. Si une table n'existe pas, on
    considère 0 article et on continue.
    """
    with DatabaseManager() as db:
        def safe_count(query: str) -> int:
            """
            Exécute un COUNT(*) et retourne 0 si la table n'existe pas.
            """
            try:
                db.cur.execute(query)
                return db.cur.fetchone()[0] or 0
            except ProgrammingError:
                # Rollback pour permettre d'autres requêtes
                db.conn.rollback()
                return 0

        total_openalex = safe_count(
            "SELECT COUNT(*) FROM articles_openalex;"
        )
        controverses_openalex = safe_count(
            "SELECT COUNT(*) "
            "FROM articles_openalex "
            "WHERE est_controverse = TRUE;"
        )
        total_oai = safe_count(
            "SELECT COUNT(*) FROM articles_oai;"
        )
        controverses_oai = safe_count(
            "SELECT COUNT(*) "
            "FROM articles_oai "
            "WHERE est_controverse = TRUE;"
        )

    try:
        return {
            "openalex": {
                "total": total_openalex,
                "controverses": controverses_openalex
            },
            "oai": {
                "total": total_oai,
                "controverses": controverses_oai
            },
            "total": total_openalex + total_oai,
            "total_controverses": controverses_openalex + controverses_oai
        }
    except Exception as e:
        # Très improbable, mais on le capture pour respecter la spec
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de l'assemblage des statistiques : {e}"
        )
