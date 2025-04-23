# app/services/harvester.py
"""
Module de service pour orchestrer l'intégralité du pipeline:
- Moissonnage OpenAlex + OAI-PMH
- Extraction de texte depuis les PDFs
- Analyse via GROBID + détection de controverses
"""
from app.database import DatabaseManager
from app.text_extraction import download_pdf, extract_text_from_pdf
from app.moissonneur import fetch_openalex_articles, fetch_oai_pmh_articles
from app.nlp_grobid import detecter_controverse_via_tei
from app.logger import logger

import httpx
import feedparser
from datetime import date
from typing import Optional, List, Dict



def run_full_pipeline(db: DatabaseManager, limit_oai: int = 20):
    """
    Exécute l'ensemble du pipeline:
      1. Moissonnage OpenAlex et OAI-PMH
      2. Extraction de texte pour les articles OAI
      3. Analyse GROBID + détection de controverses via TEI
    """
    # 1. Harvest
    count_openalex = fetch_openalex_articles(db)
    count_oai = fetch_oai_pmh_articles(db)
    logger.info(f"✅ Moissonnage terminé (OpenAlex={count_openalex}, OAI={count_oai})")

    # 2. Extraction de texte pour les articles OAI
    cur = db.cur
    cur.execute(
        """
        SELECT id, lien_pdf
        FROM articles_oai
        WHERE texte_complet IS NULL AND lien_pdf IS NOT NULL
        LIMIT %s;
        """, (limit_oai,)
    )
    for article_id, pdf_url in cur.fetchall():
        path = download_pdf(pdf_url, article_id)
        if not path:
            logger.warning(f"⚠️ Download échoué pour article {article_id}")
            continue
        text = extract_text_from_pdf(path)
        if text:
            db.save_text_to_db(article_id, text, table_name="articles_oai")

    # 3. Analyse GROBID + NLP controverses via TEI
    cur.execute(
        """
        SELECT source, article_id, tei_xml
        FROM grobid_metadata
        WHERE tei_xml IS NOT NULL;
        """
    )
    for source, article_id, tei_xml in cur.fetchall():
        res = detecter_controverse_via_tei(tei_xml)
        db.save_controverse_to_db(source, article_id, **res)

    logger.info("✅ Pipeline complet exécuté.")


