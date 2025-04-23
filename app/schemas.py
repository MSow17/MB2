# app/schemas.py

from pydantic import BaseModel, Field, root_validator
from typing import Optional, List, Dict, Any


# 📄 Schémas d'articles OpenAlex & OAI-PMH
class ArticleBase(BaseModel):
    id: Optional[int] = None
    titre: str = Field(..., strip_whitespace=True)
    auteurs: Optional[str] = None
    date_publication: Optional[str] = None
    resume: Optional[str] = None
    lien_pdf: Optional[str] = Field(default=None, strip_whitespace=True)
    texte_complet: Optional[str] = None
    est_controverse: Optional[bool] = False
    score_controverse: Optional[float] = 0.0
    extrait_controverse: Optional[str] = None

    # Pour ORM (SQLAlchemy…) en Pydantic V2
    model_config = {
        "from_attributes": True
    }

    @root_validator(pre=True)
    def _fill_lien_pdf_if_missing(cls, values: Dict[str, Any]) -> Dict[str, Any]:
        if not values.get("lien_pdf"):
            values["lien_pdf"] = "Non disponible"
        return values


class ArticleOpenAlex(ArticleBase):
    pass


class ArticleOAI(ArticleBase):
    pass


# Alias pour compatibilité (ancienne import `RechercheResult`)
RechercheResult = ArticleBase


# 🔥 Schémas controverses
class ControverseBase(BaseModel):
    id: int
    titre: str
    score_controverse: float
    extrait_controverse: Optional[str]

    model_config = {
        "from_attributes": True
    }


class ControverseOpenAlex(ControverseBase):
    pass


class ControverseOAI(ControverseBase):
    pass


# ✅ Requête NLP
class ReanalyseRequest(BaseModel):
    table: str = "articles_openalex"
    limit: int = 100


# ✅ Réponse Tâche Celery
class TaskLaunchResponse(BaseModel):
    message: str
    task_id: str


class TaskStatus(BaseModel):
    planned_tasks: List[str]
    description: str


# 📊 Statistiques
class SourceStats(BaseModel):
    total: int
    controverses: int


class GlobalStats(BaseModel):
    openalex: SourceStats
    oai: SourceStats
    total: int
    total_controverses: int


# 🧠 Analyse NLP d'un article
class AnalyseNLPResponse(BaseModel):
    id: int
    score_controverse: float
    est_controverse: bool
    extrait_controverse: Optional[str]


# 🧠 Batch NLP
class NLPBatchResult(BaseModel):
    id: int
    score_controverse: float
    est_controverse: bool
    extrait_controverse: Optional[str]


class NLPBatchResponse(BaseModel):
    resultats: List[str] = Field(default_factory=list)


# 🧠 Controverse via TEI (extension)
class AnalyseTEIResponse(BaseModel):
    article_id: int
    source: str
    score_tei: float
    est_controverse_tei: bool
    extrait_controverse_tei: Optional[str]


# 🧾 Formulaire interface HTML
class InterfaceSearchForm(BaseModel):
    keyword: Optional[str]
    auteur: Optional[str]
    source: Optional[str]
    date_debut: Optional[str]
    date_fin: Optional[str]
    sort_by: Optional[str]
    en_ligne: Optional[str]


# 🚨 Alertes JSON
class AlertResponse(BaseModel):
    has_error: bool
    message: Optional[str]
    count: Optional[int] = 0


# 🔍 Réponses de recherche
class RechercheLocaleResponse(BaseModel):
    page: int
    limit: int
    total: int
    resultats: List[ArticleBase]


class RechercheEnLigneResponse(BaseModel):
    total: int
    resultats: List[ArticleBase]


# 🔍 Recherche globale de controverses
class ControverseGlobaleResponse(BaseModel):
    source: str
    titre: str
    score_controverse: float
    est_controverse: bool
    auteurs: Optional[str] = None
    date_publication: Optional[str] = None
    resume: Optional[str] = None
    lien_pdf: Optional[str] = None
    extrait_controverse: Optional[str] = None
