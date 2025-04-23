# app/moissonneur.py
import re
import requests
import time
import datetime
from sickle.oaiexceptions import OAIError
import socket
from sickle import Sickle
from app.logger import logger
from app.database import DatabaseManager
from app.text_extraction import download_pdf, extract_text_from_pdf
from app.utils import corriger_lien_pdf, nettoyer_texte
from app.nlp import detecter_controverse
import os
from typing import Optional

# URLs des services
OAI_URL = "https://export.arxiv.org/oai2"
OPENALEX_URL = "https://api.openalex.org/works"

# Paramètres
MAX_ARTICLES = 10
REQUEST_DELAY = 1

# Adresse email pour OpenAlex (bonne pratique)
OPENALEX_EMAIL = os.getenv("OPENALEX_EMAIL")


def fetch_oai_pmh_articles(db: DatabaseManager, retries: int = 3, retry_delay: int = 10) -> int:
    """
    Moissonne les articles via OAI-PMH (ArXiv par défaut).
    """
    db.create_tables()
    if not db.conn:
        logger.error("⚠️ Connexion PostgreSQL échouée. Abandon du moissonnage OAI.")
        return 0

    last_date = db.get_last_moisson_date()
    if not last_date:
        last_date = (datetime.datetime.utcnow() - datetime.timedelta(days=7)).strftime("%Y-%m-%d")
    logger.info(f"📅 Dernier moissonnage (OAI-PMH) : {last_date}")

    count = 0
    attempt = 0
    while attempt < retries:
        try:
            logger.info(f"🔄 Tentative {attempt+1}/{retries} de moissonnage OAI-PMH...")
            sickle = Sickle(OAI_URL)

            # Paramètres pour ListRecords
            params = {"metadataPrefix": "oai_dc", "from": last_date}
            for record in sickle.ListRecords(**params):
                if count >= MAX_ARTICLES:
                    break

                meta = record.metadata
                titre = meta.get("title", ["Inconnu"])[0]
                auteurs = ", ".join(meta.get("creator", ["Auteur inconnu"]))
                date = meta.get("date", [None])[0]
                lien_pdf = "https://arxiv.org/pdf/" + record.header.identifier.split(":")[-1] + ".pdf"

                if db.article_exists("articles_oai", lien_pdf):
                    logger.info(f"🔁 Doublon ignoré : {titre}")
                    continue

                article_id = db.insert_article("articles_oai", titre, auteurs, date, "", lien_pdf)
                if not article_id:
                    continue

                pdf_path = download_pdf(lien_pdf, article_id)
                if not pdf_path:
                    logger.warning(f"❌ Échec téléchargement PDF : {lien_pdf}")
                    continue

                texte = extract_text_from_pdf(pdf_path)
                if not texte:
                    logger.warning(f"❌ Texte vide extrait : {lien_pdf}")
                    continue

                texte = nettoyer_texte(texte)
                # Détection via NLP
                res_nlp = detecter_controverse(texte)
                db.save_text_to_db(article_id, texte, table_name="articles_oai")
                db.save_controverse_to_db(
                    "articles_oai",
                    article_id,
                    res_nlp["est_controverse"],
                    res_nlp["score_controverse"],
                    res_nlp["extrait_controverse"]
                )

                count += 1
                logger.info(f"✅ Article inséré : {titre} (score controverse = {res_nlp['score_controverse']})")
                time.sleep(REQUEST_DELAY)

            break  # succès -> on sort des retries

        except (OAIError, socket.error, ConnectionError) as e:
            logger.warning(f"⏳ Tentative {attempt+1}/{retries} échouée : {e}")
            attempt += 1
            if attempt < retries:
                logger.info(f"⏳ Nouvelle tentative dans {retry_delay}s...")
                time.sleep(retry_delay)
        except Exception as e:
            logger.error(f"❌ Erreur inattendue OAI-PMH : {e}")
            break

    # Mise à jour si nouveaux articles récupérés
    if count > 0:
        new_date = datetime.datetime.utcnow().strftime("%Y-%m-%d")
        db.set_last_moisson_date(new_date)
        logger.info(f"📌 Moissonnage terminé : {count} articles. Date mise à jour : {new_date}")
    else:
        logger.info("ℹ️ Aucun nouvel article OAI-PMH, date non mise à jour.")

    
    return count

def fetch_openalex_articles(db: DatabaseManager) -> int:
    """
    Moissonne les articles depuis OpenAlex et les insère en base.
    Nouveau: récupère landing_page_url + parsing HTML.
    """
    db.create_tables()
    if not db.conn:
        logger.error("⚠️ Impossible de moissonner : pas de connexion PG.")
        return 0

    last_date = db.get_last_moisson_date()
    if not last_date:
        last_date = (datetime.datetime.utcnow() - datetime.timedelta(days=7)).strftime("%Y-%m-%d")
    logger.info(f"📅 Date de départ OpenAlex : {last_date}")

    # On retire le filtre is_oa pour inclure landing pages
    params = {
        "filter": f"from_publication_date:{last_date}",
        "per-page": MAX_ARTICLES,
        "mailto": OPENALEX_EMAIL
    }

    try:
        response = requests.get(OPENALEX_URL, params=params)
        response.raise_for_status()
        articles = response.json().get("results", [])
        logger.info(f"✅ {len(articles)} articles OpenAlex récupérés")
    except Exception as e:
        logger.error(f"❌ Erreur récupération OpenAlex : {e}")
        return 0

    count = 0
    for art in articles:
        titre = art.get("title", "Sans titre")
        auteurs = ", ".join(
            [a.get("author", {}).get("display_name", "?") for a in art.get("authorships", [])]
        )
        date = art.get("publication_date", last_date)

        # 1. PDF direct via primary_location
        primary = art.get("primary_location", {})
        pdf_url = primary.get("pdf_url")
        # 2. fallback landing page
        if not pdf_url:
            pdf_url = primary.get("landing_page_url")
        # 3. fallback OA URLs
        if not pdf_url:
            oa_urls = art.get("open_access", {}).get("oa_url") or art.get("open_access", {}).get("oa_urls")
            if isinstance(oa_urls, list) and oa_urls:
                entry = oa_urls[0]
                pdf_url = entry.get("url") if isinstance(entry, dict) else entry

        if not pdf_url:
            logger.info(f"⏭️ Ignoré (pas de lien PDF) : {titre}")
            continue

        # Correction et insertion
        pdf_url = corriger_lien_pdf(pdf_url)
        if db.article_exists("articles_openalex", pdf_url):
            logger.info(f"🔁 Doublon ignoré : {titre}")
            continue

        article_id = db.insert_article(
            "articles_openalex", titre, auteurs, date, "", pdf_url
        )
        if not article_id:
            logger.warning(f"❌ Échec insertion DB : {titre}")
            continue

        # Téléchargement + extraction
        pdf_path = download_pdf(pdf_url, article_id)
        if not pdf_path:
            logger.warning(f"❌ Échec téléchargement PDF : {pdf_url}")
            continue
        texte = extract_text_from_pdf(pdf_path)
        if not texte:
            logger.warning(f"❌ Texte vide extrait : {pdf_url}")
            continue

        texte = nettoyer_texte(texte)
        res_nlp = detecter_controverse(texte)
        db.save_text_to_db(article_id, texte, table_name="articles_openalex")
        db.save_controverse_to_db(
            "articles_openalex", article_id,
            res_nlp["est_controverse"], res_nlp["score_controverse"], res_nlp["extrait_controverse"]
        )

        count += 1
        logger.info(f"✅ Article inséré : {titre} (score controverse = {res_nlp['score_controverse']})")
        time.sleep(REQUEST_DELAY)

    if count > 0:
        new_date = datetime.datetime.utcnow().strftime("%Y-%m-%d")
        db.set_last_moisson_date(new_date)
        logger.info(f"📌 Moissonnage OpenAlex terminé : {count} articles. Date mise à jour : {new_date}")
    else:
        logger.info("ℹ️ Aucun nouvel article OpenAlex, date non mise à jour.")

   
    return count

def reanalyser_tous_les_articles(table: str, db: DatabaseManager, limite: int = 100):
    """Réanalyse les articles existants et met à jour les scores de controverse."""
    if table not in ["articles_openalex", "articles_oai"]:
        raise ValueError("Table non autorisée")

    db.cur.execute(f"""
        SELECT id, texte_complet
        FROM {table}
        WHERE texte_complet IS NOT NULL
        LIMIT %s;
    """, (limite,))
    articles = db.cur.fetchall()

    resultats = []
    for article_id, texte in articles:
        try:
            texte_nettoye = nettoyer_texte(texte)
            res = detecter_controverse(texte_nettoye)
            db.save_controverse_to_db(table, article_id, **res)
            resultats.append({
                "id": article_id,
                "score_controverse": res["score"],
                "est_controverse": res["est_controverse"]
            })
        except Exception as e:
            resultats.append({
                "id": article_id,
                "error": str(e)
            })

    return resultats


if __name__ == "__main__":
    logger.info("✅ Test du logger OK (moissonneur.py)")

