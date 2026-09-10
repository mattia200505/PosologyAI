# PosologyAI

Plateforme d'exploration et d'analyse de données médicamenteuses françaises — recherche (texte, sémantique, IA), fiche médicament, aide à la prescription, vérification d'ordonnance, assistant conversationnel.

Trois magasins de données (MongoDB, Neo4j, Qdrant) derrière une application Flask (`frontend_backend/`). Le reste du dépôt (`sync/`, `agent_*.py`, `scripts/`, `scrapers/`) est le moteur qui alimente ces bases — vous n'en avez pas besoin pour faire tourner et modifier l'application web.

Repris d'un projet de stage BUT3 (RoboEye Tec / Maidis), transmis pour servir de base à une SAE.

## Installation

**Seul prérequis : [Docker Desktop](https://www.docker.com/products/docker-desktop/).** Rien d'autre à installer sur la machine — ni Python, ni MongoDB, ni Neo4j : tout tourne en conteneurs.

```bash
git clone <url-de-ce-dépôt>
cd <nom-du-dossier>
cp .env.example .env
```

Ouvrez `.env` et remplissez trois valeurs :

| Variable | Comment l'obtenir |
|---|---|
| `NEO4J_PASSWORD` | un mot de passe de votre choix, au moins 8 caractères |
| `SECRET_KEY` | `python -c "import secrets; print(secrets.token_hex(32))"` — collez le résultat |
| `MISTRAL_API_KEY` | clé gratuite sur [console.mistral.ai/api-keys](https://console.mistral.ai/api-keys/) |

`MISTRAL_API_KEY` n'est nécessaire que pour l'assistant conversationnel, la recherche IA et l'aide à la prescription — sans elle, le reste de l'application fonctionne normalement, ces trois fonctions restent seulement silencieuses.

**Ne recopiez jamais une clé depuis un `.env` reçu par ailleurs.** Chacun génère la sienne — c'est justement ainsi qu'une ancienne clé de ce projet a fini publiée sur GitHub par le passé (voir le commentaire dans `frontend_backend/config.py`).

Puis :

```bash
docker compose up --build
```

Le premier lancement est lent (plusieurs minutes) — l'image installe `sentence-transformers` et `torch`, plusieurs centaines de Mo. Les lancements suivants sont rapides.

Une fois démarré : **http://localhost:5000**

Si `SECRET_KEY` est absente ou mal renseignée, l'application refuse de démarrer et l'affiche clairement dans les logs plutôt que d'échouer silencieusement — ce n'est pas un bug si vous voyez ce message, c'est voulu.

## Les bases de données sont vides au premier lancement

Docker Compose crée MongoDB, Neo4j et Qdrant vides — le catalogue de médicaments n'y est pas encore. Deux options :

1. **Recevoir un export** (le plus simple, à demander à la personne qui vous a transmis ce dépôt — les fichiers sont trop volumineux pour tenir dans le dépôt Git). Une fois les trois exports en main :

   ```bash
   # MongoDB
   docker cp <dossier_mongodump> posologyai-mongo:/tmp/dump
   docker exec posologyai-mongo mongorestore --drop /tmp/dump

   # Neo4j (le service doit être arrêté pendant le chargement)
   docker compose stop neo4j
   docker run --rm \
     -v <nom_du_volume_neo4j_data>:/data \
     -v "<chemin_absolu_vers_le_dossier_backup>:/backups" \
     neo4j:2025.10.1 neo4j-admin database load medicament --from-path=/backups --overwrite-destination=true
   docker compose up -d neo4j

   # Qdrant — attention, la collection doit s'appeler "medicines" et non
   # le nom qu'elle porte peut-être dans l'export (l'application lit
   # exactement ce nom, voir frontend_backend/app.py)
   docker cp <dossier_qdrant_dump> posologyai-qdrant:/qdrant/storage/collections/medicines
   docker compose restart qdrant
   ```

   Pour le nom exact du volume Neo4j : `docker volume ls --filter name=neo4j_data`.

2. **Reconstruire depuis les sources publiques** — plus long, mais autonome. Voir `scripts/` (imports DrugBank, PharmGKB) et `sync/` (synchronisation continue depuis l'ANSM). Cette voie demande de lancer les scripts Python hors Docker (`pip install -r requirements.txt` à la racine) ; elle n'est pas documentée en détail ici, ouvrez une discussion si vous vous y engagez.

## Ce que vous allez probablement modifier

- `frontend_backend/app.py` et `frontend_backend/blueprints/` — les routes
- `frontend_backend/templates/` — les pages (Jinja2)
- `frontend_backend/static/` — CSS et JS
- `frontend_backend/prescription_helper.py` — le moteur d'aide à la prescription
- `frontend_backend/chatbot.py` — l'assistant conversationnel

`frontend_backend/config.py` liste toutes les variables d'environnement lues par l'application, avec leur rôle en commentaire — le premier réflexe utile en cas de comportement inattendu lié à la configuration.

## Problèmes fréquents

| Symptôme | Cause probable |
|---|---|
| `docker compose up` échoue tout de suite | Docker Desktop n'est pas lancé |
| L'app refuse de démarrer, message sur `SECRET_KEY` | `.env` incomplet — voir la section Installation |
| Recherche/fiches vides | Bases de données pas encore restaurées — voir la section précédente |
| Assistant IA muet, aucune erreur visible | `MISTRAL_API_KEY` absente ou invalide |
| Neo4j refuse la connexion | `NEO4J_PASSWORD` doit faire au moins 8 caractères, et être identique dans `.env` des deux côtés (rien à changer normalement si vous n'avez touché qu'une fois à `.env`) |
