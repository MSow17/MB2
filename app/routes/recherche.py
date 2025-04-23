# app/routes/recherche.py
from fastapi import APIRouter, Query, HTTPException, status
from datetime import date
from typing import Optional, List, Dict, Any
import requests
from sickle import Sickle
import feedparser
import httpx
from app.logger import logger

from app.database import DatabaseManager
from app.utils import nettoyer_texte
from app.nlp import detecter_controverse
from app.schemas import RechercheLocaleResponse, RechercheEnLigneResponse, ControverseGlobaleResponse, RechercheResult

OAI_BASE_URL = "https://export.arxiv.org/oai2"


router = APIRouter(
    tags=["Recherche"]
)

@router.get(
    "/local",
    summary="Recherche locale dans la base",
    response_model=RechercheLocaleResponse,
    responses={
        200: {"description": "Résultats de la recherche locale", "content": {"application/json": {"example": {
            "page": 1,
            "limit": 10,
            "total": 100,
            "resultats": [
                {"id": 1, "titre": "Titre A", "auteurs": "Dupont, Jean", "date_publication": "2024-01-01", "resume": "Résumé...", "lien_pdf": "http://...pdf", "texte_complet": "Texte..."}
            ]
        }}}},
        400: {"description": "Paramètres invalides"},
        500: {"description": "Erreur interne lors de la recherche"}
    }
)
def recherche_locale(
    mot_cle: Optional[str] = Query(..., alias="keyword", description="Mot-clé à rechercher"),
    auteur: Optional[str] = Query(None, description="Auteur à filtrer"),
    source: Optional[str] = Query(None, pattern="^(openalex|oai)$", description="Source: openalex ou oai"),
    date_debut: Optional[date] = Query(None, description="Date de début (YYYY-MM-DD)"),
    date_fin: Optional[date] = Query(None, description="Date de fin (YYYY-MM-DD)"),
    page: int = Query(1, ge=1, description="Numéro de page"),
    limit: int = Query(10, ge=1, le=100, description="Nombre de résultats par page"),
    sort_by: Optional[str] = Query("date_desc", regex="^(date_asc|date_desc)$", description="Tri par date asc ou desc")
) -> RechercheLocaleResponse:
    if source not in ("openalex", "oai", None):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Source invalide.")
    table = f"articles_{source}" if source else None
    if not table:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Recherche sur toutes les sources désactivée pour performance.")
    # Construction de la requête
    query = f"SELECT * FROM {table} WHERE 1=1"
    count_query = f"SELECT COUNT(*) FROM {table} WHERE 1=1"
    params: List[Any] = []
    if mot_cle:
        clause = "titre ILIKE %s OR resume ILIKE %s"
        query += f" AND ({clause})"
        count_query += f" AND ({clause})"
        params += [f"%{mot_cle}%", f"%{mot_cle}%"]
    if auteur:
        query += " AND auteurs ILIKE %s"
        count_query += " AND auteurs ILIKE %s"
        params.append(f"%{auteur}%")
    if date_debut:
        query += " AND date_publication >= %s"
        count_query += " AND date_publication >= %s"
        params.append(date_debut)
    if date_fin:
        query += " AND date_publication <= %s"
        count_query += " AND date_publication <= %s"
        params.append(date_fin)
    order = "ASC" if sort_by == "date_asc" else "DESC"
    query += f" ORDER BY date_publication {order} LIMIT %s OFFSET %s"
    offset = (page - 1) * limit
    params_with_pagination = params + [limit, offset]
    try:
        with DatabaseManager() as db:
            db.cur.execute(count_query, tuple(params))
            total = db.cur.fetchone()[0]
            db.cur.execute(query, tuple(params_with_pagination))
            rows = db.cur.fetchall()
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Erreur recherche locale : {e}")
    resultats = [
        {"id": r[0], "titre": r[1], "auteurs": r[2], "date_publication": r[3], "resume": r[4], "lien_pdf": r[5], "texte_complet": r[6]}
        for r in rows
    ]
    return {"page": page, "limit": limit, "total": total, "resultats": resultats}


# 1) Recherche OpenAlex
@router.get(
    "/enligne/openalex",
    summary="Recherche en ligne via OpenAlex",
    response_model=List[RechercheResult],
    responses={502: {"description": "Erreur d'appel à l'API OpenAlex"}}
)
async def recherche_openalex_enligne(
    keyword: str = Query(..., description="Mot-clé à rechercher"),
    max_results: int = Query(5, ge=1, le=50, alias="per-page", description="Nombre max de résultats"),
    sort_by: str = Query("date_desc", pattern="^(date_asc|date_desc)$", description="Tri par date")
) -> List[RechercheResult]:
    """
    Recherche via l'API OpenAlex, reconstruction du résumé et détection de controverse.
    """
    OPENALEX_API_URL = "https://api.openalex.org/works"
    sort_param = "publication_date:desc" if sort_by == "date_desc" else "publication_date:asc"
    params = {
        "filter": f"title.search:{keyword}",
        "per-page": max_results,
        "sort": sort_param
    }

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
    articles: List[RechercheResult] = []

    for art in results:
        titre = art.get("display_name") or art.get("title", "Titre inconnu")
        auteurs = ", ".join(a.get("author", {}).get("display_name", "") for a in art.get("authorships", []))
        date_pub = art.get("publication_date")

        # Reconstruction du résumé depuis abstract_inverted_index
        abstract_idx = art.get("abstract_inverted_index") or {}
        if isinstance(abstract_idx, dict) and abstract_idx:
            tokens_pos = [
                (pos, token)
                for token, positions in abstract_idx.items()
                for pos in positions
            ]
            tokens_pos.sort(key=lambda x: x[0])
            resume = " ".join(token for _, token in tokens_pos)
        else:
            resume = art.get("abstract", "") or ""
        if not resume:
            resume = titre

        lien_pdf = art.get("open_access", {}).get("oa_url", "") or ""

        # Détection de la controverse
        nlp_res = detecter_controverse(resume)
        est = nlp_res.get("est_controverse", False)
        score = nlp_res.get("score_controverse", 0.0)
        extrait = nlp_res.get("extrait_controverse", "")

        articles.append(RechercheResult(
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


# 2) Recherche ArXiv OAI
@router.get(
    "/enligne/oai",
    summary="Recherche en ligne via l'API REST d'ArXiv",
    response_model=List[RechercheResult],
    responses={502: {"description": "Erreur d'appel à l'API ArXiv"}}
)
async def recherche_oai_enligne(
    keyword: str = Query(..., description="Mot-clé à rechercher"),
    max_results: int = Query(5, ge=1, le=50, alias="max_results", description="Nombre max de résultats"),
    sort_by: str = Query("date_desc", pattern="^(date_asc|date_desc)$", description="Tri par date")
) -> List[RechercheResult]:
    """
    Recherche via ArXiv REST Atom, nettoyage du résumé et détection de controverse.
    """
    ARXIV_REST_URL = "http://export.arxiv.org/api/query"
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
    articles: List[RechercheResult] = []

    for entry in feed.entries:
        titre = entry.title
        auteurs = ", ".join(a.name for a in entry.authors)
        date_pub = entry.published.split("T")[0]

        # Nettoyage du résumé
        resume_raw = entry.summary or ""
        resume = " ".join(resume_raw.split())
        if not resume:
            resume = titre

        pdf_link = next((link.href for link in entry.links if link.type == "application/pdf"), entry.id)

        # Détection de la controverse
        nlp_res = detecter_controverse(resume)
        est = nlp_res.get("est_controverse", False)
        score = nlp_res.get("score_controverse", 0.0)
        extrait = nlp_res.get("extrait_controverse", "")

        articles.append(RechercheResult(
            titre=titre,
            auteurs=auteurs,
            date_publication=date_pub,
            resume=resume,
            lien_pdf=pdf_link,
            est_controverse=est,
            score_controverse=score,
            extrait_controverse=extrait
        ))

        if len(articles) >= max_results:
            break

    return articles


# 3) Recherche globale (OpenAlex + OAI)
@router.get("/global", response_model=RechercheEnLigneResponse)
async def recherche_globale(
    keyword: str = Query(...),
    limit: int = Query(10, ge=1),
    sort_by: str = Query("date_desc", pattern="^(date_asc|date_desc)$")
):
    # 1) Appel OpenAlex
    openalex_list = await recherche_openalex_enligne(keyword, max_results=limit, sort_by=sort_by)
    # 2) Appel ArXiv
    oai_list = await recherche_oai_enligne(keyword, max_results=limit, sort_by=sort_by)

    # 3) Fusion
    combined = openalex_list + oai_list

    # (facultatif) tri par date si vous voulez regrouper
    if sort_by == "date_desc":
        combined.sort(key=lambda art: art.date_publication, reverse=True)
    else:
        combined.sort(key=lambda art: art.date_publication)

    # 4) Limite finale
    limited = combined[:limit]

    # 5) Retour
    return RechercheEnLigneResponse(total=len(combined), resultats=limited)




