import os
import json
import requests
from datetime import date
from typing import Any, List, Dict
from fastapi import APIRouter, Request, Form, Depends, HTTPException, status, Path
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.routes.recherche import recherche_locale
from app.celery_tasks import moissonner
from app.auth import authentifier
from app.routes.stats import get_stats
from app.database import DatabaseManager

router = APIRouter(prefix="", tags=["Interface Web"])
templates = Jinja2Templates(directory="templates")

# Nombre max d'articles à afficher (configurable via variable d'env)
MAX_RESULTS: int = int(os.getenv("MB2_MAX_RESULTS", 10))
# URL interne vers l'API moissonneur (pour recherche globale, GROBID)
MOISSONNEUR_URL: str = os.getenv("MB2_API_URL", "http://localhost:8000")


@router.get("/", response_class=HTMLResponse, summary="Formulaire de recherche d'articles")
async def get_interface(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("interface.html", {"request": request})


@router.post("/", response_class=HTMLResponse, summary="Soumettre la recherche d'articles")
async def post_interface(
    request: Request,
    keyword: str = Form(None),
    auteur: str = Form(None),
    source: str = Form(None),
    date_debut: str = Form(None),
    date_fin: str = Form(None),
    sort_by: str = Form("date_desc"),
    en_ligne: str = Form(None),
) -> HTMLResponse:
    # Conversion des dates
    start = date.fromisoformat(date_debut) if date_debut else None
    end = date.fromisoformat(date_fin) if date_fin else None

    detail = "Recherche locale uniquement."
    results_raw: List[Dict[str, Any]] = []

    # Recherche locale
    locaux = recherche_locale(
        keyword=keyword, auteur=auteur, source=source,
        date_debut=start, date_fin=end, sort_by=sort_by
    )

    if en_ligne == "true" and keyword:
        # Recherche globale si demandée
        try:
            resp = requests.get(
                f"{MOISSONNEUR_URL}/recherche/global",
                params={
                    "keyword": keyword,
                    "auteur": auteur,
                    "date_debut": date_debut,
                    "date_fin": date_fin,
                    "limit": MAX_RESULTS
                },
                timeout=10
            )
            if resp.status_code == 200:
                data = resp.json()
                results_raw = data.get("resultats", [])
                detail = f"Résultats en ligne : {len(results_raw)} articles."
            else:
                detail = f"Erreur API globale : {resp.status_code}"
        except Exception as e:
            detail = f"Exception recherche globale : {e}"
    else:
        # On utilise la recherche locale
        results_raw = [r.dict() for r in locaux]

    # Limitation du nombre de résultats
    resultats = results_raw[:MAX_RESULTS]

    # Renvoi du template
    return templates.TemplateResponse("interface.html", {
        "request": request,
        "keyword": keyword,
        "auteur": auteur,
        "source": source,
        "date_debut": date_debut,
        "date_fin": date_fin,
        "sort_by": sort_by,
        "en_ligne": en_ligne,
        "resultats": resultats,
        "detail": detail,
        "max_results": MAX_RESULTS,
    })


@router.get(
    "/admin",
    response_class=HTMLResponse,
    summary="Page admin avec stats et alertes"
)
async def admin_page(
    request: Request,
    user: str = Depends(authentifier)
) -> HTMLResponse:
    # Chargement des alertes
    alert: Dict[str, Any] = {}
    try:
        with open(os.getenv("MB2_ALERT_FILE", "app/alerts.json"), encoding="utf-8") as f:
            alert = json.load(f)
    except Exception:
        alert = {}

    # Stats globales
    try:
        stats = get_stats()
    except Exception:
        stats = {}

    return templates.TemplateResponse("admin.html", {
        "request": request,
        "alert": alert,
        "stats": stats
    })


@router.post(
    "/moissonner",
    summary="Lancer moissonnage depuis l'interface"
)
async def lancer_moissonnage_depuis_interface(
    user: str = Depends(authentifier)
) -> RedirectResponse:
    moissonner.delay()
    return RedirectResponse(
        url="/admin",
        status_code=status.HTTP_303_SEE_OTHER
    )


@router.get(
    "/grobid/{source}/{article_id}",
    response_class=HTMLResponse,
    summary="Vue GROBID d'un article"
)
async def interface_grobid(
    request: Request,
    source: str = Path(..., description="articles_openalex ou articles_oai"),
    article_id: int = Path(...)
) -> HTMLResponse:
    try:
        resp = requests.get(
            f"{MOISSONNEUR_URL}/grobid/{source}/{article_id}",
            timeout=30
        )
        resp.raise_for_status()
        data = resp.json()
        return templates.TemplateResponse(
            "grobid_view.html",
            {"request": request, **data}
        )
    except requests.RequestException as e:
        return templates.TemplateResponse(
            "grobid_view.html", {"request": request, "erreur": str(e)}
        )


@router.post(
    "/grobid/analyser_batch",
    summary="Lancer batch GROBID depuis l'interface",
    responses={303: {"description": "Redirection vers /admin"}, 401: {"description": "Authentification requise"}}
)
async def lancer_batch_grobid(
    user: str = Depends(authentifier)
) -> RedirectResponse:
    from app.celery_tasks import analyser_batch_grobid
    analyser_batch_grobid.delay()
    return RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)


@router.post(
    "/reset_logs",
    summary="Réinitialiser le fichier de logs",
    responses={303: {"description": "Redirection vers /admin"}, 500: {"description": "Erreur"}, 401: {"description": "Authentification requise"}}
)
async def reset_logs(
    user: str = Depends(authentifier)
) -> RedirectResponse:
    try:
        log_file = os.path.join(os.getenv("LOG_DIR", "logs"), "mb2.log")
        with open(log_file, "w", encoding="utf-8") as f:
            f.write("")
        return RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/reset_articles",
    summary="Supprimer tous les articles stockés",
    responses={303: {"description": "Redirection vers /admin"}, 500: {"description": "Erreur"}, 401: {"description": "Authentification requise"}}
)
async def reset_articles(
    user: str = Depends(authentifier)
) -> RedirectResponse:
    try:
        with DatabaseManager() as db:
            for table in ["grobid_metadata", "articles_openalex", "articles_oai"]:
                db.cur.execute(f"DELETE FROM {table};")
            db.conn.commit()
        return RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/docs",
    response_class=HTMLResponse,
    summary="Documentation des pages HTML"
)
async def interface_docs(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("docs_interface.html", {"request": request})
