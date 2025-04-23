import logging, os
from logging.handlers import RotatingFileHandler

LOG_DIR = os.getenv("LOG_DIR", "./logs")
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOG_DIR, "mb2.log")

logger = logging.getLogger("mb2")
level = os.getenv("LOG_LEVEL", "INFO").upper()
logger.setLevel(getattr(logging, level, logging.INFO))

formatter = logging.Formatter(
    '%(asctime)s %(levelname)s [%(name)s:%(lineno)d] %(message)s'
)

file_handler = RotatingFileHandler(LOG_FILE, maxBytes=1_000_000, backupCount=3)
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)

console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)


# 🧪 Message de test (exécuté une seule fois)

if __name__ == "__main__":

    logger.info("✅ Logger initialisé correctement - fichier de log : %s", LOG_FILE)

