from celery.schedules import crontab


# 🔧 Connexion Redis (correspond à "redis_mb2" dans docker-compose)
broker_url = "redis://redis_mb2:6379/0"
result_backend = "redis://redis_mb2:6379/0"

# 🕒 Tâches périodiques
beat_schedule = {
    # Pipeline complet (harvest, extraction, GROBID, NLP)
    "pipeline-full-quotidien": {
        "task": "pipeline.full",
        "schedule": crontab(hour=0, minute=30),
        "args": (20,)
    },
    # 1️⃣ Moissonnage OpenAlex + OAI-PMH
    "moissonner-articles-quotidien": {
        "task": "moissonner.articles",
        "schedule": crontab(hour=1, minute=0),
    },
    # 2️⃣ Extraction PDF OAI
    "extraire-textes-quotidien": {
        "task": "extraire.textes",
        "schedule": crontab(hour=1, minute=30),
    },
    # 3️⃣ Batch GROBID
    "grobid-batch-quotidien": {
        "task": "grobid.batch",
        "schedule": crontab(hour=2, minute=0),
        "args": (20,)
    },
    # 4️⃣ Réanalyse NLP OpenAlex
    "reanalyser-articles-openalex-nlp": {
        "task": "reanalyser.batch",
        "schedule": crontab(hour=3, minute=0),
        "args": ("articles_openalex", 50)
    },
    # 5️⃣ Réanalyse controverses TEI
    "reanalyser-controverses-tei-quotidien": {
        "task": "reanalyser.controverses.tei",
        "schedule": crontab(hour=4, minute=0),
    },
    # 6️⃣ Vérification des logs
    "verifier-logs-quotidien": {
        "task": "verifier.logs",
        "schedule": crontab(hour=5, minute=0),
    },
}

# 🌍 Fuseau horaire
timezone = 'Europe/Paris'

# Import des tâches
imports = ("app.celery_tasks",)
