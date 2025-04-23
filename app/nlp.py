# app/nlp.py

import re
import warnings
from transformers import pipeline
from transformers.utils import logging as hf_logging
from app.logger import logger

# Silence des UserWarning de Transformers en prod
warnings.filterwarnings("ignore", category=UserWarning)
hf_logging.set_verbosity_error()

# Pipeline chargé en lazy loading
_detecteur = None

# Seuil sur le score de controverse (0.0 à 1.0)
SEUIL_CONTROVERSE = 0.70

def get_detecteur_sentiment():
    global _detecteur
    if _detecteur is None:
        try:
            logger.info("🚀 Chargement du modèle NLP HuggingFace…")
            _detecteur = pipeline(
                "sentiment-analysis",
                model="distilbert/distilbert-base-uncased-finetuned-sst-2-english",
                revision="af0f99b",
                top_k=None,  # équivalent à return_all_scores=True
            )
        except Exception as e:
            logger.error(f"❌ Échec du chargement du modèle HuggingFace : {e}")
            raise
    return _detecteur

def detecter_controverse(texte: str) -> dict:
    """
    Analyse un texte pour détecter une controverse potentielle.
    Retourne un dict avec :
      - est_controverse (bool)
      - score_controverse (float entre 0 et 1)
      - extrait_controverse (phrase la plus controversée)
    """
    try:
        detecteur = get_detecteur_sentiment()
        phrases = re.split(r'(?<=[.!?]) +', texte)

        best_score = 0.0
        best_phrase = ""

        for phrase in phrases:
            mots = phrase.split()
            if len(mots) < 5:
                continue

            # on limite pour ne pas dépasser 512 tokens
            resultats = detecteur(phrase[:512])
            if not resultats:
                continue

            # HuggingFace renvoie une liste de dicts, un par label
            outputs = resultats[0]
            pos = next(o["score"] for o in outputs if o["label"] == "POSITIVE")
            neg = next(o["score"] for o in outputs if o["label"] == "NEGATIVE")

            score = 1.0 - abs(pos - neg)
            logger.debug(
                f"Phrase «{phrase}» → pos={pos:.3f}, neg={neg:.3f}, controverse={score:.3f}"
            )

            if score > best_score:
                best_score = score
                best_phrase = phrase

        est_controverse = best_score >= SEUIL_CONTROVERSE
        final_score = round(best_score, 3)

        logger.info(
            f"🧠 NLP : score_controverse={final_score}, extrait_controverse='{best_phrase}'"
        )

        return {
            "est_controverse": est_controverse,
            "score_controverse": final_score,
            "extrait_controverse": best_phrase or "Aucun extrait significatif",
        }

    except Exception as e:
        logger.error(f"❌ Erreur NLP HuggingFace : {e}")
        return {
            "est_controverse": False,
            "score_controverse": 0.0,
            "extrait_controverse": "Erreur NLP",
        }
