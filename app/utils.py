import re
import unicodedata
import requests
from urllib.parse import urlparse, urlunparse
from app.logger import logger

def corriger_lien_pdf(url: str) -> str:
    """Corrige les liens HAL pour pointer vers le vrai fichier PDF."""
    try:
        parsed = urlparse(url)
        netloc = parsed.netloc.lower()
        path = parsed.path.rstrip("/")
        # Cas HAL: ajouter '/file' si absent
        if netloc.endswith("hal.science") and not path.endswith("/file"):
            path = path + "/file"
            corrected = urlunparse(parsed._replace(path=path))
            # Vérifier que c'est bien un PDF
            try:
                head = requests.head(corrected, allow_redirects=True, timeout=5)
                content_type = head.headers.get("Content-Type", "")
                if "application/pdf" in content_type:
                    return corrected
                else:
                    logger.warning(
                        f"URL corrigée non-PDF ({content_type}), retour au lien original : {url}"
                    )
            except Exception as e:
                logger.warning(f"Échec HEAD pour {corrected} : {e}")
            # Si fallback ou erreur, on retourne l'URL d'origine
            return url
    except Exception as e:
        logger.error(f"Erreur correction lien PDF {url} : {e}")
    return url

def nettoyer_texte(texte_brut: str) -> str:
    """Nettoie le texte brut extrait depuis un PDF scientifique pour une meilleure analyse NLP."""
    if not texte_brut:
        return ""

    logger.debug(f"🔍 Texte brut original : {len(texte_brut)} caractères")

    # 1. Supprimer les lignes très courtes
    lignes = texte_brut.splitlines()
    lignes_filtrees = [ligne.strip() for ligne in lignes if len(ligne.strip()) > 10]

    # 2. Fusionner les lignes filtrées
    texte_nettoye = " ".join(lignes_filtrees)

    # 3. Nettoyages classiques
    texte_nettoye = re.sub(r"Downloaded by.*?(\n|$)", "", texte_nettoye, flags=re.IGNORECASE)
    texte_nettoye = re.sub(r"Page \d+ of \d+", "", texte_nettoye, flags=re.IGNORECASE)
    texte_nettoye = re.sub(r"All rights reserved.*?(\n|$)", "", texte_nettoye, flags=re.IGNORECASE)

    # 4. Supprimer les références entre crochets
    texte_nettoye = re.sub(r"\[[^\]]*\d+[^\]]*\]", "", texte_nettoye)

    # 5. Apostrophes typographiques
    texte_nettoye = texte_nettoye.replace("’", "'")

    # 6. Caractères non imprimables
    texte_nettoye = ''.join(c for c in texte_nettoye if unicodedata.category(c)[0] != "C")

    # 7. Caractères spéciaux bizarres
    texte_nettoye = re.sub(r"[^a-zA-Z0-9À-ÿ\s.,;:!?()\"'%-]", " ", texte_nettoye)

    # 8. Nettoyages avancés
    texte_nettoye = re.sub(r"\b[\w\.-]+@[\w\.-]+\.\w+\b", "", texte_nettoye)
    texte_nettoye = re.sub(r"(©|Copyright|All rights reserved).*?\.", "", texte_nettoye, flags=re.IGNORECASE)
    texte_nettoye = re.sub(r"\$.*?\$", "", texte_nettoye)
    texte_nettoye = re.sub(r"\\\[.*?\\\]", "", texte_nettoye)
    texte_nettoye = re.sub(r"\\begin\{.*?\}.*?\\end\{.*?\}", "", texte_nettoye, flags=re.DOTALL)
    texte_nettoye = re.sub(r"<[^>]+>", "", texte_nettoye)
    texte_nettoye = re.sub(r"Figure\s?\d+\s?:.*?(\.|\n)", "", texte_nettoye, flags=re.IGNORECASE)
    texte_nettoye = re.sub(r"Table\s?\d+\s?:.*?(\.|\n)", "", texte_nettoye, flags=re.IGNORECASE)

    # 9. Réduire les multiples espaces
    texte_nettoye = re.sub(r"\s{2,}", " ", texte_nettoye)

    texte_final = texte_nettoye.strip()
    logger.debug(f"✅ Texte nettoyé : {len(texte_final)} caractères")

    return texte_final