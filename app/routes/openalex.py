# app/routes/openalex.py
from fastapi import APIRouter, Query, HTTPException, status
from typing import Optional, List, Dict, Any
import httpx

from app.logger import logger
from app.database import DatabaseManager
from app.moissonneur import fetch_openalex_articles, reanalyser_tous_les_articles
from app.schemas import ArticleOpenAlex, ControverseOpenAlex, RechercheResult, NLPBatchResponse, ArticleBase
from app.celery_tasks import reanalyser_articles_nlp
from app.nlp import detecter_controverse

router = APIRouter(tags=["OpenAlex"])

OPENALEX_API_URL = "https://api.openalex.org/works"

@router.post(
    "/moissonner",
    summary="Lancer le moissonnage OpenAlex",
    status_code=status.HTTP_200_OK,
    responses={
        200: {
            "description": "Moissonnage réussi",
            "content": {
                "application/json": {
                    "example": {"message": "123 articles moissonnés depuis OpenAlex"}
                }
            }
        },
        500: {"description": "Erreur interne lors du moissonnage"}
    }
)
def moissonner_openalex():
    """
    Moissonne les articles récents depuis OpenAlex et les insère en base.
    """
    try:
        with DatabaseManager() as db:
            total = fetch_openalex_articles(db)
        return {"message": f"{total} articles moissonnés depuis OpenAlex"}
    except Exception as e:
        logger.exception("Erreur lors du moissonnage OpenAlex")
        raise HTTPException(status_code=500, detail=f"Erreur : {e}")

@router.get(
    "/works",
    summary="Récupère des works depuis OpenAlex",
    status_code=status.HTTP_200_OK,
    response_model=Dict[str, Any],
    responses={
        200: {
            "description": "Liste de works retournée par l'API OpenAlex",
            "content": {
                "application/json": {
                    "example": {
                        "meta": {"count": 1, "page": 1, "per_page": 25},
                        "results": [
                            {
                                "id": "https://openalex.org/W1234567890",
                                "display_name": "Titre de l'article exemple",
                                "publication_date": "2024-12-01",
                                "authorships": [{"author": {"display_name": "Dupont, Jean"}}],
                                "abstract_inverted_index": {}
                            }
                        ]
                    }
                }
            }
        },
        400: {"description": "Paramètres invalides"},
        502: {"description": "Erreur de communication avec OpenAlex"}
    }
)
async def get_works(
    search: str = Query(..., description="Terme de recherche dans le titre"),
    per_page: int = Query(25, alias="per-page", ge=1, le=200, description="Nombre de résultats par page")
):
    """
    Appelle l'API OpenAlex de manière asynchrone pour récupérer des articles.
    """
    params = {"filter": f"title.search:{search}", "per-page": per_page}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(OPENALEX_API_URL, params=params)
            response.raise_for_status()
            return response.json()
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=e.response.text)
    except httpx.RequestError as e:
        raise HTTPException(status_code=502, detail=str(e))

@router.get(
    "/articles",
    summary="Articles OpenAlex en base",
    response_model=List[ArticleOpenAlex],
    responses={
        200: {"description": "Liste des articles stockés en base"},
        500: {"description": "Erreur lecture base de données"},
    },
)
def get_articles_openalex(
    limit: int = Query(20, ge=1, description="Nombre max. d'articles à retourner"),
    offset: int = Query(0, ge=0, description="Décalage pour la pagination"),
):
    """
    Récupère les articles OpenAlex présents en base, triés par date décroissante.
    """
    try:
        with DatabaseManager() as db:
            db.cur.execute(
                """
                SELECT
                  id, titre, auteurs, date_publication, resume,
                  lien_pdf, texte_complet, est_controverse,
                  score_controverse, extrait_controverse
                FROM articles_openalex
                ORDER BY date_publication DESC
                LIMIT %s OFFSET %s;
                """,
                (limit, offset),
            )
            rows = db.cur.fetchall()
    except Exception as e:
        logger.exception("Erreur récupération articles OpenAlex")
        raise HTTPException(status_code=500, detail=str(e))

    return [
        ArticleOpenAlex(
            id=r[0],
            titre=r[1],
            auteurs=r[2],
            date_publication=r[3].isoformat(),
            resume=r[4],
            lien_pdf=r[5],
            texte_complet=r[6],
            est_controverse=r[7],
            score_controverse=r[8],
            extrait_controverse=r[9],
        )
        for r in rows
    ]


@router.get(
    "/recherche",
    summary="Recherche en ligne via OpenAlex",
    response_model=List[ArticleBase],
    responses={
        200: {"description": "Liste de résultats de recherche OpenAlex"},
        502: {"description": "Erreur d'appel à l'API OpenAlex"}
    }
)
async def recherche_openalex_enligne(
    keyword: str = Query(..., description="Mot-clé à rechercher"),
    max_results: int = Query(5, ge=1, le=50, alias="per-page", description="Nombre maximum de résultats"),
    sort_by: str = Query(
        "date_desc",
        pattern="^(date_asc|date_desc)$",
        description="Ordre de tri par date"
    )
) -> List[ArticleBase]:
    """
    Recherche asynchrone via l'API OpenAlex, avec reconstruction du résumé
    depuis abstract_inverted_index et détection de controverse.
    """
    sort_param = "publication_date:desc" if sort_by == "date_desc" else "publication_date:asc"
    params = {"filter": f"title.search:{keyword}", "per-page": max_results, "sort": sort_param}

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(OPENALEX_API_URL, params=params)
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=e.response.text)
    except httpx.RequestError as e:
        raise HTTPException(status_code=502, detail=str(e))

    results = data.get("results", [])
    logger.debug(f"🔗 Recherche OpenAlex URL → {resp.url}")

    articles: List[ArticleBase] = []
    for art in results:
        # 1) Titre et auteurs
        titre = art.get("display_name") or art.get("title", "Titre inconnu")
        auteurs = ", ".join(
            a.get("author", {}).get("display_name", "")
            for a in art.get("authorships", [])
        )
        date_pub = art.get("publication_date")

        # si le champ 'abstract' existe, on l’utilise en priorité
        if art.get("abstract"):
            resume = art["abstract"]
        elif isinstance(art.get("abstract_inverted_index"), dict):
            # reconstruction à partir de l’index inversé
            positions = []
            for mot, poses in art["abstract_inverted_index"].items():
                for p in poses:
                    positions.append((p, mot))
            positions.sort()
            resume = " ".join(m for _, m in positions)
        else:
            resume = ""
        # si toujours vide, on met une chaîne vide (ou éventuellement un placeholder)


        # 3) Lien PDF
        lien_pdf = art.get("open_access", {}).get("oa_url", "") or ""

        # 4) Analyse de controverse
        nlp_res = detecter_controverse(resume)
        est = nlp_res.get("est_controverse", False)
        score = nlp_res.get("score_controverse", 0.0)
        extrait = nlp_res.get("extrait_controverse", "")

        # 5) Construction de l'objet de sortie
        articles.append(ArticleBase(
            titre=titre,
            auteurs=auteurs,
            date_publication=date_pub,
            resume=resume,
            lien_pdf=lien_pdf,
            est_controverse=est,
            score_controverse=score,
            extrait_controverse=extrait
        ))

        if len(articles) >= max_results:
            break

    return articles

@router.get(
    "/controverses",
    summary="Articles controversés (OpenAlex)",
    response_model=List[ControverseOpenAlex],
    responses={
        200: {"description": "Articles controversés retournés"},
        500: {"description": "Erreur lecture base de données"}
    }
)
def get_controverses_openalex(
    seuil: float = Query(0.6, ge=0.0, le=1.0, description="Seuil minimal de score de controverse"),
    limit: Optional[int] = Query(50, ge=1, le=200, description="Nombre max d’articles à renvoyer")
):
    """
    Récupère les articles OpenAlex marqués comme controversés.
    """
    try:
        with DatabaseManager() as db:
            db.cur.execute(
                """
                SELECT id, titre, score_controverse, extrait_controverse
                FROM articles_openalex
                WHERE est_controverse = TRUE AND score_controverse >= %s
                ORDER BY score_controverse DESC
                LIMIT %s;
                """, (seuil, limit)
            )
            rows = db.cur.fetchall()
    except Exception as e:
        logger.exception("Erreur récupération controverses OpenAlex")
        raise HTTPException(status_code=500, detail=str(e))

    return [ControverseOpenAlex(id=r[0], titre=r[1], score_controverse=r[2], extrait_controverse=r[3]) for r in rows]


