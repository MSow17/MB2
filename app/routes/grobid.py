# app/routes/grobid.py
import os
import json
import time
import requests
from typing import Dict, Any, List

from fastapi import APIRouter, HTTPException, Request, File, UploadFile, status, Query
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from lxml import etree

from app.database import DatabaseManager
from app.utils import nettoyer_texte
from app.nlp_grobid import detecter_controverse_via_tei
from app.logger import logger

# Configuration
templates = Jinja2Templates(directory="templates")
PDF_DIR = os.getenv("PDF_DIR", "./pdfs")
GROBID_URL = os.getenv("GROBID_URL")

router = APIRouter(tags=["GROBID"])

def check_grobid_config():
    if not GROBID_URL:
        logger.critical("GROBID_URL n'est pas configuré")
        raise HTTPException(status_code=500, detail="Configuration GROBID manquante")

async def process_content(content: bytes, filename: str) -> Dict[str, Any]:
    check_grobid_config()
    try:
        logger.info(f"[process_content] Début de traitement pour {filename}")
        start_time = time.perf_counter()

        resp = requests.post(
            GROBID_URL,
            files={"input": (filename, content, "application/pdf")},
            timeout=(120, 300)
        )

        if resp.status_code != 200:
            logger.error(f"Erreur GROBID {resp.status_code}: {resp.text}")
            raise HTTPException(status_code=500, detail="Erreur de traitement GROBID")

        tei_xml = resp.text
        if "<TEI" not in tei_xml:
            raise HTTPException(status_code=500, detail="Réponse TEI invalide")

        root = etree.fromstring(tei_xml.encode("utf-8"))
        ns = {"tei": "http://www.tei-c.org/ns/1.0"}

        title = root.findtext(".//tei:titleStmt/tei:title", namespaces=ns) or ""
        authors = ", ".join([
            " ".join([n.text for n in pers.iterchildren() if n.text])
            for pers in root.findall(".//tei:author/tei:persName", namespaces=ns)
        ])
        date_pub = root.findtext(".//tei:sourceDesc//tei:date", namespaces=ns) or None

        citations: List[Dict[str, Any]] = []
        for bibl in root.xpath(".//tei:listBibl/tei:biblStruct", namespaces=ns):
            cit_title = bibl.findtext(".//tei:title", namespaces=ns)
            cit_author = bibl.findtext(".//tei:author/tei:persName/tei:surname", namespaces=ns)
            cit_year = bibl.findtext(".//tei:date", namespaces=ns)
            if cit_title:
                citations.append({"titre": cit_title, "auteur": cit_author, "annee": cit_year})

        analysis = detecter_controverse_via_tei(tei_xml)

        elapsed = time.perf_counter() - start_time
        logger.info(f"Traitement terminé en {elapsed:.2f}s")

        return {
            "filename": filename,
            "titre": title,
            "auteurs": authors,
            "date_publication": date_pub,
            "citations": citations,
            "tei_brut": tei_xml,
            "score_tei": analysis.get("score"),
            "extrait_controverse_tei": analysis.get("extrait")
        }

    except Exception as e:
        logger.exception("Erreur lors du traitement")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/upload", summary="Upload PDF utilisateur", response_model=Dict[str, Any])
async def upload_file(file: UploadFile = File(...)) -> Dict[str, Any]:
    if file.content_type != "application/pdf":
        raise HTTPException(400, "Seuls les PDF sont acceptés")
    content = await file.read()
    return await process_content(content, file.filename)

@router.post("/process-local", summary="Traiter PDF local", response_model=Dict[str, Any])
async def process_local_file(filename: str = Query(..., description="Nom du fichier PDF")) -> Dict[str, Any]:
    file_path = os.path.join(PDF_DIR, filename)
    if not os.path.isfile(file_path):
        raise HTTPException(404, "Fichier introuvable")
    with open(file_path, "rb") as f:
        content = f.read()
    return await process_content(content, filename)


