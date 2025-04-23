import os
import json
import argparse
from datetime import datetime
import fcntl
from app.logger import logger

# === Configuration via variables d'environnement ===
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.getenv("MB2_LOG_FILE", os.path.join(BASE_DIR, "..", "logs", "mb2.log"))
ALERT_FILE = os.getenv("MB2_ALERT_FILE", os.path.join(BASE_DIR, "alerts.json"))
STATE_FILE = os.getenv("MB2_STATE_FILE", os.path.join(BASE_DIR, "log_watcher_state.json"))
SEUIL_ERREUR = int(os.getenv("MB2_LOG_ERROR_THRESHOLD", "1"))


def load_state():
    """Charge l'état précédent (offset de lecture)."""
    if not os.path.exists(STATE_FILE):
        return {"offset": 0}
    try:
        with open(STATE_FILE, "r") as f:
            # lock en lecture
            fcntl.flock(f, fcntl.LOCK_SH)
            data = json.load(f)
            fcntl.flock(f, fcntl.LOCK_UN)
        return data
    except Exception:
        return {"offset": 0}


def save_state(state: dict):
    """Sauvegarde atomique de l'état (offset)"""
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        json.dump(state, f)
        f.flush()
        os.fsync(f.fileno())
        fcntl.flock(f, fcntl.LOCK_UN)
    os.replace(tmp, STATE_FILE)


def write_alert(message: str, count: int = 1):
    """Crée un fichier d'alerte JSON de façon atomique."""
    alert_data = {
        "has_error": True,
        "message": f"{message} - {datetime.now().strftime('%d/%m %H:%M')}",
        "count": count
    }
    tmp = ALERT_FILE + ".tmp"
    with open(tmp, "w") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        json.dump(alert_data, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
        fcntl.flock(f, fcntl.LOCK_UN)
    os.replace(tmp, ALERT_FILE)


def clear_alert():
    """Réinitialise les alertes de façon atomique."""
    data = {"has_error": False, "message": "Aucune erreur détectée", "count": 0}
    tmp = ALERT_FILE + ".tmp"
    with open(tmp, "w") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
        fcntl.flock(f, fcntl.LOCK_UN)
    os.replace(tmp, ALERT_FILE)


def check_log_for_errors():
    """Vérifie uniquement les nouvelles lignes du log et déclenche une alerte si nécessaire."""
    if not os.path.exists(LOG_FILE):
        logger.warning("⚠️ Aucun fichier de log trouvé : %s", LOG_FILE)
        return

    state = load_state()
    offset = state.get("offset", 0)
    errors = []

    # Lecture des nouvelles lignes
    with open(LOG_FILE, "r") as log:
        log.seek(offset)
        lines = log.readlines()
        new_offset = log.tell()

    # Met à jour l'état
    state["offset"] = new_offset
    save_state(state)

    # Filtrage des erreurs
    for line in lines:
        if any(k in line for k in ["ERROR", "CRITICAL", "Exception"]):
            errors.append(line)

    # Génération ou réinitialisation de l'alerte
    if len(errors) >= SEUIL_ERREUR:
        logger.error("🚨 %d erreurs détectées dans les logs.", len(errors))
        for err in errors[-5:]:
            logger.error(err.strip())
        write_alert("Erreur critique détectée dans les logs", count=len(errors))
    else:
        logger.info("✅ [%s] Aucun problème critique détecté.", datetime.now().isoformat())
        clear_alert()

    logger.info("📊 Bilan : %d erreurs détectées - Alerte = %s", len(errors), len(errors) >= SEUIL_ERREUR)
    logger.info("🧹 Surveillance des logs terminée.")


def main():
    parser = argparse.ArgumentParser(description="Surveillance des logs MB2")
    parser.add_argument("--quiet", action="store_true", help="Désactiver les logs console")
    args = parser.parse_args()

    if args.quiet:
        import logging
        logger.setLevel(logging.ERROR)

    check_log_for_errors()


if __name__ == "__main__":
    main()
