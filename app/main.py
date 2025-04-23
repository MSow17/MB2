# app/main.py

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.database import DatabaseManager
from app.routes import (
    openalex, oai, articles, recherche,
    interface, alert, tasks, stats, grobid
)

# Initialisation de l'application FastAPI
app = FastAPI(
    title="MB2 - API Articles Scientifiques",
    description="API modulaire pour moissonner, analyser et explorer les articles d'OpenAlex ,OAI-PMH et GROBID.",
    version="1.0.0"
)

# Configuration CORS : autoriser toutes les origines (modifiable si besoin)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 🔐 à restreindre si besoin en prod
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialisation (test) base de données
try:
    db = DatabaseManager()
except Exception as e:
    print(f"⚠️ Erreur connexion DB au démarrage : {e}")

# Inclusion des routes organisées par module
app.include_router(openalex.router, prefix="/openalex", tags=["OpenAlex"])
app.include_router(oai.router, prefix="/oai", tags=["OAI-PMH"])
app.include_router(articles.router, prefix="/articles", tags=["Articles"])
app.include_router(recherche.router, prefix="/recherche", tags=["Recherche"])
app.include_router(interface.router, prefix="/interface", tags=["Interface Web"])
app.include_router(alert.router, prefix="/alert", tags=["Alertes / Logs"])
app.include_router(tasks.router, prefix="/tasks", tags=["Tâches / Celery"])
app.include_router(stats.router, prefix="/stats", tags=["Statistiques"])
app.include_router(grobid.router, prefix="/grobid", tags=["GROBID"])

# Route de bienvenue
@app.get("/", summary="Message d'accueil de l'API")
def accueil():
    return {"message": "Bienvenue sur l’API MB2 🚀 – OpenAlex x OAI-PMH x GROBID"}