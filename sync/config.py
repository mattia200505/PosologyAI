"""
Configuration partagée des composants de synchronisation.

Les valeurs de cadence réseau proviennent des mesures de la phase P1 :
3 workers et un intervalle global de 180 ms donnent ~5,5 requêtes/seconde,
soit un cycle complet de 29 minutes sur les 9 698 fiches.
"""

import os

from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(BASE_DIR, '.env'))
load_dotenv(os.path.join(BASE_DIR, 'frontend_backend', '.env'), override=True)

# ── MongoDB ────────────────────────────────────────────────────────────
MONGO_URI = os.getenv('MONGO_URI') or 'mongodb://localhost:27017/'
DB_NAME = os.getenv('MONGO_DB') or 'medicsearch'
MONGO_TIMEOUT_MS = 5000

COLL_JOBS = 'sync_jobs'
COLL_LOCKS = 'sync_locks'
COLL_CONTROL = 'sync_control'
COLL_MEDICINES = 'medicines'

# ── Cadence réseau ─────────────────────────────────────────────────────
WORKERS = 3
REQUEST_INTERVAL = 0.18          # secondes entre deux requêtes, tous workers confondus
HTTP_TIMEOUT = (10, 30)          # (connexion, lecture) — aligné sur P0-3
USER_AGENT = 'MedicSearchSync/1.0 (projet universitaire; base publique des medicaments)'

ANSM_BASE = 'https://base-donnees-publique.medicaments.gouv.fr'
ANSM_DOWNLOAD = ANSM_BASE + '/download/file/'
ANSM_NOTICE = ANSM_BASE + '/affichageDoc.php?specid=%s&typedoc=R'

# ── File de travaux ────────────────────────────────────────────────────
JOB_TYPES = (
    'collecte_initiale',        # CIS au catalogue officiel, absent de la base
    'rafraichissement',         # date de révision divergente
    'reparation_champ',         # champ autoritaire divergent (dénomination, forme, titulaire)
    'verification_retrait',     # CIS en base, absent du catalogue
    'enrichissement_catalogue', # attributs administratifs divergents ou absents
)

# 'cancelled' couvre les tâches traitées mais non publiables : notice sans
# contenu exploitable, hors périmètre. Les distinguer de 'done' évite de les
# recompter comme des succès et de retélécharger leur page à chaque cycle.
JOB_STATES = ('pending', 'reserved', 'done', 'failed', 'cancelled')

MAX_ATTEMPTS = 3
BACKOFF_SECONDS = (60, 300, 1500)   # 1 min, 5 min, 25 min

LEASE_SECONDS = {
    'collecte_initiale': 300,
    'rafraichissement': 300,
    'reparation_champ': 120,
    'verification_retrait': 120,
    'enrichissement_catalogue': 120,   # aucun accès réseau : le bail peut être court
}
DEFAULT_LEASE = 300

# ── Verrous de cycle ───────────────────────────────────────────────────
LOCK_RECONCILIATION = 'reconciliation'
LOCK_FULL_PROBE = 'sonde_complete'
LOCK_CYCLE = 'cycle'
LOCK_TTL_SECONDS = 3600

# ── Journal des exécutions ─────────────────────────────────────────────
COLL_RUNS = 'sync_runs'

# ── Seuils d'alerte ────────────────────────────────────────────────────
# Le taux d'anomalie, et non le taux d'extraction, est le signal de
# surveillance : une fiche retirée du catalogue n'a légitimement pas de date
# de révision et ne doit pas peser sur l'alerte.
ALERT_ANOMALY_RATE = 1.0        # % de fiches au catalogue devenues illisibles
ALERT_EXTRACTION_RATE = 98.0    # % minimum d'extraction réussie
ALERT_FAILED_JOBS = 50          # tâches en échec définitif
ALERT_PENDING_GROWTH = 20000    # file qui enfle sans être consommée
ALERT_CYCLE_MINUTES = 120       # durée anormale d'un cycle
