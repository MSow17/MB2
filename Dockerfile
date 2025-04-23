# Étape 1 : Image builder (installer et compiler uniquement)
FROM python:3.10-slim AS builder

# Dépendances système requises pour la compilation
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    postgresql-client \
    libpoppler-cpp-dev \
 && apt-get clean && rm -rf /var/lib/apt/lists/*

# Définir le répertoire de travail
WORKDIR /app

# Copier et installer les dépendances Python
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Copier le code source
COPY app/ app/
COPY templates/ templates/

# Étape 2 : Image finale allégée
FROM python:3.10-slim

# Dépendances système minimales d'exécution
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    postgresql-client \
    libpoppler-cpp-dev \
 && apt-get clean && rm -rf /var/lib/apt/lists/*

# Configurer UTF-8
ENV LANG=C.UTF-8
ENV LC_ALL=C.UTF-8

# Définir le répertoire de travail
WORKDIR /app

# Copier les dépendances Python du builder
COPY --from=builder /usr/local/lib/python3.10/site-packages /usr/local/lib/python3.10/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copier le code de l'application
COPY --from=builder /app/app app/
COPY --from=builder /app/templates templates/

# Copier et rendre exécutable l'entrypoint
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Variables d'environnement
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

# Commande par défaut : lancement de FastAPI
CMD ["/entrypoint.sh"]
