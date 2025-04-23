from celery import Celery
from app.database import DatabaseManager
from app.services.harvester import run_full_pipeline
from app.moissonneur import fetch_openalex_articles, fetch_oai_pmh_articles, reanalyser_tous_les_articles
from app.logger import logger
from app.nlp_grobid import detecter_controverse_via_tei

# =========================================
# 🔧 CONFIGURATION GLOBALE
# =========================================
BROKER_URL = "redis://redis_mb2:6379/0"
BACKEND_URL = BROKER_URL
SUPPORTED_TABLES = ["articles_openalex", "articles_oai"]

# =========================================
# 🚀 INITIALISATION CELERY
# =========================================
celery_app = Celery("sofa", broker=BROKER_URL, backend=BACKEND_URL)
celery_app.config_from_object("app.celeryconfig")

# =========================================
# 🟢 TÂCHES CELERY
# =========================================

@celery_app.task(name="pipeline.full")
def pipeline_full(limit_oai: int = 20):
    """Exécute l’intégralité du pipeline (moissonnage, extraction, GROBID, NLP)."""
    logger.info("🚀 [Celery] Démarrage du pipeline complet")
    db = DatabaseManager()
    db.create_tables()
    try:
        run_full_pipeline(db, limit_oai)
        logger.info("✅ Pipeline complet terminé")
    except Exception as e:
        logger.exception(f"❌ Erreur pipeline complet : {e}")
    finally:
        db.close()

@celery_app.task(name="moissonner.articles")
def moissonner():
    """Moissonne OpenAlex + OAI-PMH et insère en base"""
    logger.info("🚀 [Celery] Démarrage du moissonnage")
    try:
        db = DatabaseManager()
        db.create_tables()
        fetch_openalex_articles(db)
        fetch_oai_pmh_articles(db)
        logger.info("✅ [Celery] Moissonnage terminé")
    except Exception as e:
        logger.exception("❌ [Celery] Erreur pendant le moissonnage : %s", e)
    finally:
        if 'db' in locals():
            db.close()

@celery_app.task(name="reanalyser.batch")
def reanalyser_articles_nlp(table="articles_openalex", limit=100):
    """Réanalyse NLP sur les articles avec texte complet"""
    logger.info(f"🧠 [Celery] Réanalyse NLP batch sur {table} (max {limit})")
    try:
        if table not in SUPPORTED_TABLES:
            raise ValueError(f"Table non supportée : {table}")
        db = DatabaseManager()
        results = reanalyser_tous_les_articles(table, db, limite=limit)
        logger.info(f"✅ [Celery] Réanalyse NLP terminée ({len(results)} articles)")
        return results
    except Exception as e:
        logger.error(f"❌ Échec de la réanalyse NLP : {e}")
        return {"error": str(e)}
    finally:
        if 'db' in locals():
            db.close()

@celery_app.task(name="grobid.batch")
def analyser_batch_grobid(limit: int = 20):
    """Analyse GROBID des PDFs non encore traités"""
    from app.grobid import analyser_avec_grobid
    logger.info("📦 [Celery] Lancement batch GROBID sur les PDFs manquants")
    db = DatabaseManager()
    cur = db.cur
    cur.execute("""
        SELECT id, 'articles_oai' as source FROM articles_oai
        WHERE texte_complet IS NOT NULL AND id NOT IN (
            SELECT article_id FROM grobid_metadata WHERE source = 'articles_oai'
        )
        LIMIT %s
        UNION
        SELECT id, 'articles_openalex' as source FROM articles_openalex
        WHERE texte_complet IS NOT NULL AND id NOT IN (
            SELECT article_id FROM grobid_metadata WHERE source = 'articles_openalex'
        )
        LIMIT %s;
    """, (limit, limit))
    total = 0
    for article_id, source in cur.fetchall():
        try:
            analyser_avec_grobid(source, article_id, save=True)
            total += 1
        except Exception as e:
            logger.warning(f"⚠️ GROBID échoué pour {source} #{article_id} : {e}")
    db.close()
    logger.info(f"✅ [Celery] GROBID batch terminé ({total} articles analysés)")
    return {"total_analysés": total}

@celery_app.task(name="reanalyser.controverses.tei")
def reanalyser_controverses_tei():
    """Réanalyse des controverses depuis les TEI XML (GROBID)"""
    db = DatabaseManager()
    cur = db.cur
    cur.execute("SELECT article_id, source, tei_xml FROM grobid_metadata WHERE tei_xml IS NOT NULL;")
    total = 0
    for article_id, source, tei_xml in cur.fetchall():
        try:
            analyse = detecter_controverse_via_tei(tei_xml)
            cur.execute(
                """
                UPDATE grobid_metadata
                SET est_controverse_tei = %s,
                    score_controverse_tei = %s,
                    extrait_controverse_tei = %s
                WHERE article_id = %s AND source = %s;
                """,
                (
                    analyse["est_controverse"],
                    analyse["score"],
                    analyse["extrait"],
                    article_id,
                    source
                )
            )
            total += 1
        except Exception as e:
            logger.warning(f"⚠️ Erreur TEI NLP pour {source} #{article_id} : {e}")
    db.conn.commit()
    db.close()
    logger.info(f"✅ [Celery] Réanalyse TEI terminée ({total} articles)")
    return {"articles_analysés": total}

@celery_app.task(name="verifier.logs")
def verifier_logs():
    """Tâche Celery : vérifie les erreurs dans les logs et déclenche une alerte si besoin."""
    from app.log_watcher import check_log_for_errors
    logger.info("🧪 [Celery] Vérification automatique des logs (log_watcher)...")
    check_log_for_errors()
