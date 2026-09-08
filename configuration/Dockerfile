FROM python:3.10-slim

WORKDIR /app

# Attention au contexte de build : ce Dockerfile est fait pour etre construit
# avec la racine du depot comme contexte (voir docker-compose.yml a la
# racine : build.context = ., build.dockerfile = configuration/Dockerfile).
# Les chemins ci-dessous sont donc relatifs a la racine du depot, pas au
# dossier configuration/ ou se trouve ce fichier -- un `../frontend_backend`
# ici sortirait du contexte de build et ferait echouer le COPY.

# Copier requirements depuis frontend_backend
COPY frontend_backend/requirements.txt .

# Installer les dependances
RUN pip install --no-cache-dir -r requirements.txt

# Copier tout le code de frontend_backend
COPY frontend_backend .

# Definir l'environnement Python
ENV PYTHONUNBUFFERED=1

EXPOSE 5000

# Lancer Flask
CMD ["python", "app.py"]
