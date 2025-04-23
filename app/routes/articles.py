# app/routes/articles.py
from fastapi import APIRouter, HTTPException, Query, Path, status
from typing import List, Dict, Any

from app.database import DatabaseManager
from app.nlp import detecter_controverse
from app.utils import nettoyer_texte
from app.schemas import ArticleOpenAlex, ControverseOpenAlex, AnalyseNLPResponse

router = APIRouter(tags=["Articles"])
TABLES_VALIDES = ["articles_openalex", "articles_oai"]

@router.get(
    "/",
    summary="Retourne tous les articles stockés",
    response_model=List[ArticleOpenAlex],
    responses={
        200: {
            "description": "Liste des articles avec score de controverse",
            "content": {"application/json": {"example": [
                {"id": 1, "titre": "Titre A", "auteurs": "Dupont, Jean", "date_publication": "2024-01-01", "resume": "Résumé...", "lien_pdf": "http://...pdf", "texte_complet": "Texte...", "score_controverse": 0.75, "est_controverse": True, "extrait_controverse": "Extrait..."}
            ]}}
        },
        500: {"description": "Erreur interne lors de la récupération"}
    }
)
def get_all_articles(
    table: str = Query(
        "articles_openalex",
        pattern="^articles_(openalex|oai)$",
        description="Table à interroger"
    )
) -> List[ArticleOpenAlex]:
    try:
        with DatabaseManager() as db:
            db.cur.execute(f"""
                SELECT id, titre, auteurs, date_publication, resume, lien_pdf, texte_complet,
                       score_controverse, est_controverse, extrait_controverse
                FROM {table}
                ORDER BY score_controverse DESC NULLS LAST;
            """)
            rows = db.cur.fetchall()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur récupération articles : {e}")
    return [ArticleOpenAlex(
        id=r[0], titre=r[1], auteurs=r[2], date_publication=r[3].isoformat(), resume=r[4], lien_pdf=r[5],
        texte_complet=r[6], score_controverse=r[7], est_controverse=r[8], extrait_controverse=r[9]
    ) for r in rows]

@router.get(
    "/controverses",
    summary="Retourne les articles marqués comme controversés",
    response_model=List[ControverseOpenAlex],
    responses={
        200: {"description": "Liste des articles controversés", "content": {"application/json": {"example": [
            {"id": 2, "titre": "Titre B", "score_controverse": 0.82, "extrait_controverse": "Extrait..."}
        ]}}},
        500: {"description": "Erreur interne lors de la récupération"}
    }
)
def get_controverses(
    table: str = Query(
        "articles_openalex", pattern="^articles_(openalex|oai)$",
        description="Table à interroger"
    ),
    seuil: float = Query(
        0.6, ge=0.0, le=1.0,
        description="Seuil minimal de score de controverse"
    )
) -> List[ControverseOpenAlex]:
    try:
        with DatabaseManager() as db:
            db.cur.execute(f"""
                SELECT id, titre, score_controverse, extrait_controverse
                FROM {table}
                WHERE est_controverse = TRUE AND score_controverse >= %s
                ORDER BY score_controverse DESC;
            """, (seuil,))
            rows = db.cur.fetchall()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur récupération controverses : {e}")
    return [ControverseOpenAlex(
        id=r[0], titre=r[1], score_controverse=r[2], extrait_controverse=r[3]
    ) for r in rows]

@router.get(
    "/{table}/{article_id}",
    summary="Retourne les détails d’un article",
    response_model=ArticleOpenAlex,
    responses={
        200: {"description": "Détails complets de l'article"},
        400: {"description": "Table non autorisée"},
        404: {"description": "Article non trouvé"},
        500: {"description": "Erreur interne lors de la récupération"}
    }
)
def get_article_by_id(
    table: str = Path(..., pattern="^articles_(openalex|oai)$", description="Table à interroger"),
    article_id: int = Path(..., ge=1, description="ID de l'article")
) -> ArticleOpenAlex:
    if table not in TABLES_VALIDES:
        raise HTTPException(status_code=400, detail="Table non autorisée")
    try:
        with DatabaseManager() as db:
            db.cur.execute(f"""
                SELECT id, titre, auteurs, date_publication, resume, lien_pdf, texte_complet,
                       score_controverse, est_controverse, extrait_controverse
                FROM {table} WHERE id = %s;
            """, (article_id,))
            row = db.cur.fetchone()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur récupération article : {e}")
    if not row:
        raise HTTPException(status_code=404, detail="Article non trouvé")
    return ArticleOpenAlex(
        id=row[0], titre=row[1], auteurs=row[2], date_publication=row[3].isoformat(), resume=row[4],
        lien_pdf=row[5], texte_complet=row[6], score_controverse=row[7],
        est_controverse=row[8], extrait_controverse=row[9]
    )


