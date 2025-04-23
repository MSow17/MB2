# app/nlp_grobid.py
from lxml import etree
from app.utils import nettoyer_texte
from app.logger import logger
from app.nlp import detecter_controverse

def extraire_texte_depuis_tei(tei_xml: str) -> str:
    """
    Extrait un texte concaténé depuis <abstract> et <body> d’un TEI XML.
    """
    try:
        root = etree.fromstring(tei_xml.encode("utf-8"))
        ns = {"tei": "http://www.tei-c.org/ns/1.0"}

        resume = root.findtext(".//tei:abstract", namespaces=ns) or ""
        body_parts = root.findall(".//tei:body//tei:p", namespaces=ns)
        body = "\n".join([p.text for p in body_parts if p is not None and p.text])

        full_text = resume + "\n" + body
        return full_text.strip()

    except Exception as e:
        logger.error(f"❌ Erreur extraction texte TEI : {e}")
        return ""

def detecter_controverse_via_tei(tei_xml: str) -> dict:
    """
    Analyse NLP d’un article scientifique à partir de son fichier TEI.
    Retourne un dictionnaire : score, est_controverse, extrait.
    """
    texte = extraire_texte_depuis_tei(tei_xml)
    if not texte:
        return {
            "score": 0.0,
            "est_controverse": False,
            "extrait": ""
        }

    texte_nettoye = nettoyer_texte(texte)
    return detecter_controverse(texte_nettoye)

