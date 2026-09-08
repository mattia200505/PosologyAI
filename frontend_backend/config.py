import datetime
import os
from dotenv import load_dotenv

# `override=True` : sans lui, load_dotenv laisse gagner les variables déjà
# présentes dans l'environnement. Des variables utilisateur Windows
# NEO4J_PASSWORD et NEO4J_URI, restées d'une ancienne configuration et
# devenues incorrectes, supplantaient ainsi le .env du projet : la connexion
# Neo4j échouait sur une authentification refusée.
# L'application n'y survivait que par hasard : ai_summary.py et
# prescription_helper.py appellent load_dotenv(override=True) et sont importés
# plus tôt. Ce qui vaut pour eux doit valoir ici — le .env du projet fait foi.
load_dotenv(override=True)

class Config:
    """Configuration de base pour l'application PosologyAI"""
    
    # Configuration MongoDB
    # Connexion locale à MongoDB Compass
    MONGO_URI = 'mongodb://localhost:27017/medicsearch'
    MONGO_HOST = os.environ.get('MONGO_HOST', 'localhost')
    MONGO_PORT = int(os.environ.get('MONGO_PORT', 27017))
    MONGO_DB = os.environ.get('MONGO_DB', 'medicsearch')
    MONGO_TIMEOUT = int(os.environ.get('MONGO_TIMEOUT', 5000))
    MONGO_RETRY_WRITES = os.environ.get('MONGO_RETRY_WRITES', 'true').lower() == 'true'
    
    # Configuration Qdrant
    QDRANT_HOST = os.environ.get('QDRANT_HOST', '127.0.0.1')
    QDRANT_PORT = int(os.environ.get('QDRANT_PORT', 6333))
    QDRANT_TIMEOUT = int(os.environ.get('QDRANT_TIMEOUT', 30))
    QDRANT_PREFER_GRPC = os.environ.get('QDRANT_PREFER_GRPC', 'false').lower() == 'true'
    QDRANT_API_KEY = os.environ.get('QDRANT_API_KEY', '')
    
    # Configuration Neo4j
    NEO4J_URI = os.environ.get('NEO4J_URI', 'neo4j://127.0.0.1:7687')
    NEO4J_USER = os.environ.get('NEO4J_USER', 'neo4j')
    NEO4J_PASSWORD = os.environ.get('NEO4J_PASSWORD', '12345678')
    # Le défaut valait 'medisearch' : une base qui n'existe sur aucun serveur.
    # Un défaut inexistant transforme un .env absent en DatabaseNotFound au
    # premier appel plutôt qu'au démarrage. Le graphe est dans 'medicament'.
    NEO4J_DATABASE = os.environ.get('NEO4J_DATABASE', 'medicament')
    NEO4J_ID = os.environ.get('NEO4J_ID', 'a7aa048e-2334-45b7-ac75-999e6158c2be')
    
    # Configuration Mistral AI
    MISTRAL_API_KEY = os.environ.get('MISTRAL_API_KEY', '')

    # Cette clé a été publiée sur GitHub jusqu'au 11/08/2026, dans le `.env`
    # versionné par les premiers commits. L'historique a été purgé, mais une
    # purge ne révoque rien : quiconque a cloné le dépôt avant cette date en
    # détient encore une copie. Seule une rotation côté Mistral la neutralise.
    #
    # L'empreinte est stockée, jamais la valeur : l'inscrire ici en clair
    # republierait ce que l'on vient précisément de retirer.
    _EMPREINTE_CLE_DIVULGUEE = 'bb2885efb660'

    if MISTRAL_API_KEY:
        import hashlib
        if hashlib.sha256(MISTRAL_API_KEY.encode()).hexdigest()[:12] == _EMPREINTE_CLE_DIVULGUEE:
            import warnings
            warnings.warn(
                "\n" + "!" * 70 +
                "\n  MISTRAL_API_KEY : cette cle a ete publiee sur GitHub."
                "\n  L historique a ete purge, mais la cle reste compromise :"
                "\n  toute copie du depot faite avant le 11/08/2026 la contient."
                "\n"
                "\n  A faire : la revoquer sur https://console.mistral.ai/api-keys/"
                "\n  puis remplacer MISTRAL_API_KEY dans frontend_backend/.env"
                "\n" + "!" * 70,
                stacklevel=2)
    
    # ── Sécurité ──────────────────────────────────────────────────────
    # SECRET_KEY signe la session, qui porte désormais l'identité de
    # l'utilisateur. Une clé connue permet donc de forger une session
    # d'administrateur : elle ne peut plus avoir de valeur par défaut.
    #
    # L'ancienne valeur codée en dur était publiée sur GitHub. Elle est
    # explicitement refusée, pour qu'un déploiement qui la traînerait encore
    # échoue au démarrage au lieu de paraître sain.
    _CLE_COMPROMISE = 'e8b7c9d2f5a3b1e4c6d8f0a9b2e7d5c1'
    SECRET_KEY = os.environ.get('SECRET_KEY')

    if not SECRET_KEY or SECRET_KEY == _CLE_COMPROMISE:
        raise RuntimeError(
            "SECRET_KEY absente ou compromise. Definissez-la dans .env :\n"
            "    python -c \"import secrets; print('SECRET_KEY=' + secrets.token_hex(32))\" >> .env\n"
            "Sans clé propre, la session est falsifiable et l'espace "
            "d'administration ouvert a quiconque."
        )
    
    # Durée d'une session « se souvenir de moi ». Reprend les 30 jours de
    # l'ancien `max_age` de cookie, désormais portés par la session signée.
    PERMANENT_SESSION_LIFETIME = datetime.timedelta(days=30)

    # La session ne doit être lisible que par le serveur, ne pas partir vers
    # un autre site, et n'emprunter le réseau en clair qu'en développement.
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    SESSION_COOKIE_SECURE = os.environ.get('SESSION_COOKIE_SECURE', '').lower() in ('1', 'true', 'yes')

    # Configuration du cache
    CACHE_TYPE = os.environ.get('CACHE_TYPE', 'simple')
    CACHE_DEFAULT_TIMEOUT = 300
    
    # Configuration des logs
    LOG_LEVEL = os.environ.get('LOG_LEVEL', 'INFO')
    
    # Options de pagination par défaut
    DEFAULT_PAGE_SIZE = 10
    MAX_PAGE_SIZE = 100
    
    # Configuration des cookies
    SESSION_COOKIE_SECURE = os.environ.get('SESSION_COOKIE_SECURE', 'False').lower() == 'true'
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'

class DevelopmentConfig(Config):
    """Configuration pour l'environnement de développement"""
    DEBUG = True
    TEMPLATES_AUTO_RELOAD = True
    SEND_FILE_MAX_AGE_DEFAULT = 0

class ProductionConfig(Config):
    """Configuration pour l'environnement de production"""
    DEBUG = False
    
    # En production, assurez-vous de définir SECRET_KEY via une variable d'environnement
    # et n'utilisez pas la valeur par défaut!
    
    # Options de cache plus performantes pour la production
    CACHE_TYPE = 'redis'
    CACHE_REDIS_URL = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')

class TestingConfig(Config):
    """Configuration pour les tests"""
    TESTING = True
    MONGO_URI = 'mongodb://mongo:27017/medicsearch_test'

# Dictionnaire pour sélectionner la configuration selon l'environnement
config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'testing': TestingConfig,
    'default': DevelopmentConfig
}

# Fonction pour obtenir la configuration actuelle
def get_config():
    """Renvoie la configuration selon l'environnement défini"""
    env = os.environ.get('FLASK_ENV', 'default')
    return config.get(env)
