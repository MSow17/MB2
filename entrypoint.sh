#!/usr/bin/env bash
set -e

# Intercepter SIGINT et SIGTERM pour bien arrêter
trap "echo '🛑 Signal reçu, arrêt du conteneur'; exit 0" SIGINT SIGTERM

# Lancement de l'API FastAPI
echo "🚀 Démarrage de la FastAPI"
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --log-level debug