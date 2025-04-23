# app/routes/oai.py
import feedparser
import httpx
import anyio
from fastapi import APIRouter, HTTPException, Query, status
from datetime import date
from typing import Optional, List, Dict, Any

from app.logger import logger
from app.database import DatabaseManager
from app.moissonneur import fetch_oai_pmh_articles
from app.schemas import ArticleOAI, ControverseOAI, RechercheResult, NLPBatchResponse, ArticleBase
from app.celery_tasks import reanalyser_articles_nlp
from app.nlp import SEUIL_CONTROVERSE, detecter_controverse

router = APIRouter(
    tags=["OAI-PMH"]
)

OAI_BASE_URL = "https://export.arxiv.org/oai2"
ARXIV_REST_URL = "http://export.arxiv.org/api/query"

@router.post(
    "/moissonner",
    summary="Lancer le moissonnage OAI-PMH",
    status_code=status.HTTP_200_OK,
    responses={
        200: {
            "description": "Moissonnage OAI-PMH réussi",
            "content": {"application/json": {"example": {"message": "50 articles moissonnés depuis ArXiv via OAI-PMH"}}}
        },
        500: {"description": "Erreur interne lors du moissonnage"}
    }
)
def moissonner_oai():
    """
    Moissonne les articles récents depuis ArXiv (OAI-PMH) et les insère en base.
    """
    try:
        with DatabaseManager() as db:
            total = fetch_oai_pmh_articles(db)
        return {"message": f"{total} articles moissonnés depuis ArXiv via OAI-PMH"}
    except Exception as e:
        logger.exception("Erreur lors du moissonnage OAI-PMH")
        raise HTTPException(status_code=500, detail=f"Erreur : {e}")

@router.get(
    "/articles",
    summary="Articles OAI-PMH en base",
    response_model=List[ArticleOAI],
    responses={
        200: {"description": "Liste des articles OAI-PMH stockés en base"},
        500: {"description": "Erreur lecture base de données"}
    }
)
def get_articles_oai(
    limit: int = Query(20, ge=1, description="Nombre maximum d'articles à retourner")
):
    """
    Récupère les articles OAI-PMH présents en base.
    """
    try:
        with DatabaseManager() as db:
            db.cur.execute(
                """
                SELECT * FROM articles_oai
                ORDER BY date_publication DESC
                LIMIT %s;
                """, (limit,)
            )
            rows = db.cur.fetchall()
    except Exception as e:
        logger.exception("Erreur récupération articles OAI-PMH")
        raise HTTPException(status_code=500, detail=str(e))

    results = []
    for row in rows:
        pub = row[3]
        pub_str = pub.isoformat() if isinstance(pub, date) else str(pub)
        results.append(
            ArticleOAI(
                id=row[0],
                titre=row[1],
                auteurs=row[2],
                date_publication=pub_str,
                resume=row[4],
                lien_pdf=row[5],
                texte_complet=row[6],
                est_controverse=row[7],
                score_controverse=row[8],
                extrait_controverse=row[9]
            )
        )
    return results

@router.get(
    "/recherche",
    summary="Recherche en ligne via l'API REST d'ArXiv",
    response_model=List[ArticleBase],
    responses={
        200: {
            "description": "Résultats de recherche ArXiv",
            "content": {
                "application/json": {
                    "example": [
                        {
                            "titre": "Exemple Titre",
                            "auteurs": "Doe, John",
                            "date_publication": "2024-01-01",
                            "resume": "Résumé...",
                            "lien_pdf": "http://...pdf",
                            "est_controverse": True,
                            "score_controverse": 0.85,
                            "extrait_controverse": "Phrase controversée"
                        }
                    ]
                }
            }
        },
        502: {"description": "Erreur d'appel à l'API ArXiv REST"}
    }
)
async def recherche_oai_enligne(
    keyword: str = Query(..., description="Mot-clé à rechercher"),
    max_results: int = Query(
        5,
        ge=1,
        le=50,
        alias="max_results",
        description="Nombre maximum de résultats"
    ),
    sort_by: Optional[str] = Query(
        "date_desc",
        pattern="^(date_asc|date_desc)$",
        description="Tri : 'date_asc' ou 'date_desc'"
    )
) -> List[ArticleBase]:
    """
    Recherche asynchrone sur l'API REST Atom d'ArXiv, avec détection de controverse.
    """
    sort_order = "descending" if sort_by == "date_desc" else "ascending"
    params = {
        "search_query": f"all:{keyword}",
        "start": 0,
        "max_results": max_results,
        "sortBy": "submittedDate",
        "sortOrder": sort_order,
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(ARXIV_REST_URL, params=params)
            resp.raise_for_status()
            xml_text = resp.text
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=e.response.text)
    except httpx.RequestError as e:
        raise HTTPException(status_code=502, detail=str(e))

    feed = feedparser.parse(xml_text)
    articles: List[ArticleBase] = []

    for entry in feed.entries:
        # Titre et auteurs
        titre = entry.title
        auteurs = ", ".join(a.name for a in entry.authors)
        date_pub = entry.published.split("T")[0]

        # Nettoyage du résumé
        resume_raw = entry.summary or ""
        resume = " ".join(resume_raw.split())
        if not resume:
            resume = titre

        # Lien PDF
        pdf_link = next(
            (link.href for link in entry.links if link.type == "application/pdf"),
            entry.id
        )

        # Détection de controverse
        nlp_res = detecter_controverse(resume)
        est = nlp_res.get("est_controverse", False)
        score = nlp_res.get("score_controverse", 0.0)
        extrait = nlp_res.get("extrait_controverse", "")

        # Construction de l'objet ArticleBase
        articles.append(
            ArticleBase(
                titre=titre,
                auteurs=auteurs,
                date_publication=date_pub,
                resume=resume,
                lien_pdf=pdf_link,
                est_controverse=est,
                score_controverse=score,
                extrait_controverse=extrait
            )
        )

        if len(articles) >= max_results:
            break

    return articles


@router.get(
    "/controverses",
    summary="Articles controversés en base (OAI-PMH)",
    response_model=List[ControverseOAI],
    responses={
        200: {"description": "Articles controversés retournés"},
        500: {"description": "Erreur lecture base de données"}
    }
)
def get_controverses_oai(
    seuil: float = Query(
        SEUIL_CONTROVERSE,
        ge=0.0,
        le=1.0,
        description="Seuil minimal de score de controverse (0.0–1.0)"
    ),
    limit: int = Query(
        20,
        ge=1,
        le=100,
        description="Nombre maximum d’articles retournés"
    )
):
    """
    Récupère les articles OAI-PMH marqués comme controversés.
    """
    try:
        with DatabaseManager() as db:
            sql = (
                "SELECT id, titre, score_controverse, extrait_controverse "
                "FROM articles_oai WHERE score_controverse >= %s "
                "ORDER BY score_controverse DESC, date_publication DESC LIMIT %s;"
            )
            db.cur.execute(sql, (seuil, limit))
            rows = db.cur.fetchall()
    except Exception as e:
        logger.exception("Erreur récupération controverses OAI-PMH")
        raise HTTPException(status_code=500, detail=str(e))

    return [
        ControverseOAI(
            id=r[0],
            titre=r[1],
            score_controverse=float(r[2]),
            extrait_controverse=r[3]
        ) for r in rows
    ]


