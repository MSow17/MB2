# 📚 SoFa – Scientific Open File Analyzer

Projet réalisé dans le cadre de l'UE MB2 – Université Lyon 1  
Encadrant : Marc Bertin  
Étudiants : Amadou Lamine Faye, Malick Sow

---

## ✨ Présentation

**SoFa** est une plateforme de fouille d’articles scientifiques open access. Le projet moissonne des métadonnées (et parfois les PDF complets) via les protocoles **OAI-PMH** et **OpenAlex**, puis analyse le contenu pour détecter automatiquement des **controverses scientifiques** à l’aide de **modèles NLP** (Transformers).

Le système est entièrement déployé sous Docker avec une API FastAPI, une interface web Jinja2, et un traitement en tâche de fond avec **Celery + Redis**.

---

## ⚙️ Fonctionnalités principales

- 🔄 Moissonnage automatique d’articles (OAI-PMH & OpenAlex)
- 📥 Téléchargement et validation des fichiers PDF
- 🧠 Détection de controverses avec HuggingFace Transformers
- 🗂️ Extraction structurée via GROBID (format TEI)
- 🔍 Interface web de recherche avec filtres avancés
- ⏱️ Traitement asynchrone avec Celery & planification par Celery Beat
- 📊 Supervision des tâches via Flower
- 📁 Journalisation complète (logs, alertes)

---

## 🖥️ Interfaces web

### 🔸 Interface utilisateur
Accessible via `http://localhost:8000`

- Recherche par mot-clé, auteur, source, date
- Résultats avec score de controverse
- Accès aux passages controversés (texte ou TEI)
- Mode clair/sombre intégré

### 🔸 Interface administrateur
- Lancement manuel du moissonnage
- Suivi des logs en temps réel
- Affichage des alertes critiques (via JSON)
- Supervision via Flower (`http://localhost:5555`)

---

## 🐳 Installation & lancement

```bash
git clone https://github.com/MSow17/MB2.git
cd MB2
docker-compose up --build
```

Ensuite :
- Interface Web : http://localhost:8000
- Swagger Docs : http://localhost:8000/docs
- Flower (supervision Celery) : http://localhost:5555

Suivre les logs :
```bash
docker-compose logs -f         # tous les services
docker-compose logs -f web     # uniquement FastAPI
docker-compose logs -f worker  # uniquement le worker Celery
```

---

## 🗂️ Arborescence principale

```
MB2/
├── app/
│   ├── api/                  # Routes FastAPI
│   ├── moissonneur.py        # Moissonnage OAI + OpenAlex
│   ├── database.py           # Connexion PostgreSQL
│   ├── nlp.py                # Détection de controverse
│   ├── logger.py             # Système de logs
│   ├── grobid.py             # Intégration GROBID
│   ├── celery_tasks.py       # Tâches planifiées
│   └── ...
├── templates/                # HTML avec Jinja2
├── logs/                     # Fichier mb2.log
├── Dockerfile
├── docker-compose.yml
└── README.md
```

---

## 👥 Contributions

### 🧑‍💻 Amadou Lamine Faye
- Moissonnage OAI-PMH & OpenAlex
- Téléchargement PDF & gestion des doublons
- Traitement NLP pour la controverse
- Intégration Celery, Flower et interface utilisateur

### 🧑‍💻 Malick Sow
- Intégration de GROBID (serveur externe)
- Extraction des fichiers TEI
- Analyse TEI & affichage dans les templates
- Interface d’administration et suivi des erreurs

---

## 📜 Licence

Projet académique non librement réutilisable.  
© Université Claude Bernard Lyon 1 – 2025

---

## 📌 Remarques

- Toutes les routes API sont documentées sur `/docs`
- Des tests automatiques sont possibles (non fournis dans cette version)
- Le projet est pensé pour être extensible (analyse d'opinion, clusterisation, etc.)

---

> Pour toute question, contactez :  
> 📧 amadou-lamine.faye@etu.univ-lyon1.fr  
> 📧 malick.sow@etu.univ-lyon1.fr
