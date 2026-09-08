"""
Chatbot PosologyAI - Assistant intelligent utilisant Mistral AI et les bases de données MongoDB, Qdrant, Neo4j
"""

from flask import Blueprint, request, jsonify, current_app, session
from prescription_helper import get_clinical_fallback
from pymongo import MongoClient
from qdrant_client import QdrantClient
from bson import ObjectId
from sentence_transformers import SentenceTransformer
from mistralai import Mistral
import os
import re
import time
import uuid
from collections import deque
from dotenv import load_dotenv
import logging
from neo4j_connector import Neo4jConnector

logger = logging.getLogger(__name__)
load_dotenv()

# Configuration
MISTRAL_API_KEY = os.getenv('MISTRAL_API_KEY')
MONGO_URI = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
MONGO_DB = os.getenv('MONGO_DB', 'medicsearch')
QDRANT_HOST = os.getenv('QDRANT_HOST', '127.0.0.1')
QDRANT_PORT = int(os.getenv('QDRANT_PORT', 6333))

# Configuration Neo4j
NEO4J_URI = os.getenv('NEO4J_URI', 'neo4j://127.0.0.1:7687')
NEO4J_USER = os.getenv('NEO4J_USER', 'neo4j')
NEO4J_PASSWORD = os.getenv('NEO4J_PASSWORD', '12345678')
NEO4J_DATABASE = os.getenv('NEO4J_DATABASE', 'medicament')

# Clients
mongo_client = MongoClient(MONGO_URI)
db = mongo_client[MONGO_DB]

# Qdrant client with error handling
qdrant_client = None
try:
    qdrant_client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT, timeout=5)
    logger.info("[INFO] ✅ Qdrant connecté pour le chatbot")
except Exception as e:
    logger.warning(f"[WARNING] ⚠️ Qdrant non disponible pour le chatbot: {e}")
    qdrant_client = None

# Embedding model - UTILISE CELUI DE app.py pour éviter de le recharger
embedding_model = None
logger.info("[INFO] ℹ️ Embedding model sera importé de app.py")

# Neo4j connector - NE PAS SE CONNECTER AU DÉMARRAGE pour éviter les timeouts
neo4j_connector = None
try:
    neo4j_connector = Neo4jConnector(
        uri=NEO4J_URI,
        user=NEO4J_USER,
        password=NEO4J_PASSWORD,
        database=NEO4J_DATABASE
    )
    # NE PAS appeler connect() ici - sera fait à la demande dans les routes
    logger.info("[INFO] ℹ️ Neo4j connector initialisé (connexion à la demande)")
except Exception as e:
    logger.warning(f"[WARNING] ⚠️ Impossible d'initialiser Neo4j: {e}")
    neo4j_connector = None


def _neo4j():
    """Rend un connecteur Neo4j **ouvert**, ou None.

    Le commentaire ci-dessus annonce une connexion « à la demande dans les
    routes » ; aucune route ne l'établissait. `neo4j_connector.driver` restait
    donc None, la garde du bloc d'interactions échouait toujours, et cette
    branche n'a jamais tourné en production — le chatbot retombait
    silencieusement sur la collection MongoDB `interactions`, vide.

    On préfère le connecteur de l'application, déjà ouvert au démarrage, plutôt
    que d'entretenir une seconde réserve de connexions vers la même base.
    L'instance locale ne sert plus que de repli, et elle est alors ouverte
    explicitement.
    """
    try:
        partage = getattr(current_app, 'neo4j', None)
        if partage and getattr(partage, 'driver', None):
            return partage
    except RuntimeError:
        # Hors contexte de requête : on se rabat sur l'instance du module.
        pass

    if neo4j_connector and not getattr(neo4j_connector, 'driver', None):
        try:
            neo4j_connector.connect()
        except Exception as err:
            logger.warning(f"Neo4j indisponible pour le chatbot : {err}")
            return None
    return neo4j_connector if getattr(neo4j_connector, 'driver', None) else None

chatbot_bp = Blueprint('chatbot', __name__, url_prefix='/api/chatbot')

# ──────────────────────────────────────────────
# SECURITE — garde-fous d'entree
#
# L'endpoint etait ouvert a tout venant : chaque message declenchait un
# appel Mistral (cout) et un parcours Qdrant + MongoDB. Un script mal
# intentionne — ou un simple double-clic impatient — pouvait saturer le
# service et la facture API. S'y ajoutent deux limites de surface :
# longueur maximale d'un message, et suppression des caracteres de
# controle avant tout traitement.
# ──────────────────────────────────────────────
MESSAGE_LONGUEUR_MAX = 1000

_RATE_LIMIT_MAX = 15            # messages par fenetre et par visiteur
_RATE_LIMIT_FENETRE = 300       # secondes
_RATE_LIMIT_SESSIONS_MAX = 5000 # bornage memoire du registre
_requetes_par_session = {}


def _verifier_rate_limit(cle):
    """Fenetre glissante en memoire ; renvoie (autorise, secondes_attente)."""
    maintenant = time.monotonic()
    if len(_requetes_par_session) > _RATE_LIMIT_SESSIONS_MAX:
        _requetes_par_session.clear()  # registre sature : reset brutal mais borne
    fenetre = _requetes_par_session.setdefault(cle, deque())
    while fenetre and maintenant - fenetre[0] > _RATE_LIMIT_FENETRE:
        fenetre.popleft()
    if len(fenetre) >= _RATE_LIMIT_MAX:
        return False, int(_RATE_LIMIT_FENETRE - (maintenant - fenetre[0])) + 1
    fenetre.append(maintenant)
    return True, 0


def _nettoyer_message(texte):
    """Supprime caracteres de controle et espace superflu, borne la longueur."""
    texte = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', ' ', texte or '')
    return ' '.join(texte.split())[:MESSAGE_LONGUEUR_MAX]


def _cle_visiteur():
    """Cle stable par visiteur : cookie Flask signe (SECRET_KEY).

    Un identifiant aleatoire est pose au premier message puis rejoue ;
    impossible pour le client de forcer la cle d'un autre sans le secret
    de signature.
    """
    if 'cb_sid' not in session:
        session['cb_sid'] = uuid.uuid4().hex
    return 'sess:' + session['cb_sid']


# ──────────────────────────────────────────────
# PERTINENCE — memoire de conversation
#
# Chaque question etait traitee hors contexte : « et pour les enfants ? »
# juste apres une reponse sur le paracetamol n'avait aucun antecedent a
# relire. On conserve les derniers tours par visiteur et on les reinjecte
# dans le prompt, dans la limite d'une fenetre courte.
# ──────────────────────────────────────────────
_HISTORIQUE_TOURS_MAX = 6
_historiques_par_session = {}


def _historique_get(cle):
    return _historiques_par_session.get(cle, [])


def _historique_ajouter(cle, role, contenu):
    if len(_historiques_par_session) > _RATE_LIMIT_SESSIONS_MAX:
        _historiques_par_session.clear()
    fil = _historiques_par_session.setdefault(cle, [])
    fil.append({'role': role, 'content': contenu[:1500]})
    del fil[:-_HISTORIQUE_TOURS_MAX * 2]


def _historique_effacer(cle):
    _historiques_par_session.pop(cle, None)

# ──────────────────────────────────────────────
# MODE URGENCE ABSOLUE
# ──────────────────────────────────────────────
URGENCY_KEYWORDS = [
    'urgence', 'urgent', 'détresse', 'detresse', 'arrêt', 'arret', 'cardiaque',
    'infarctus', 'crise cardiaque', 'douleur thoracique', 'oppression thoracique',
    'intoxication', 'empoisonnement', 'overdose', 'surdose', 'poison',
    'avc', 'accident vasculaire', 'hémiplégie', 'hemiplegie', 'paralysie',
    'dyspnée', 'dyspnee', 'étouffe', 'etouffe', 'suffocation', 'asphyxie',
    'anaphylaxie', 'choc anaphylactique', 'allergie grave', 'oedème', 'œdème',
    'hémorragie', 'hemorragie', 'saignement', 'blessure grave',
    'brûlure', 'brulure', 'grave brûlure',
    'convulsion', 'convulsions', 'crise d\'épilepsie', 'status epilepticus',
    'traumatisme crânien', 'tête grave', 'perte de connaissance', 'inconscient',
    'noyade', 'quasi-noyade',
    'coup de chaleur', 'hyperthermie', 'insolation',
    'hypothermie', 'gelure',
    'suicide', 'tentative de suicide', 'automutilation',
    'grave accident', 'accident grave', 'polytraumatisme',
    'malaise grave', 'malaise cardiaque',
]

def detect_emergency(text: str) -> bool:
    """Détecte si le message correspond à une urgence vitale"""
    text_lower = text.lower()
    for kw in URGENCY_KEYWORDS:
        if kw in text_lower:
            return True
    return False

EMERGENCY_RESPONSES = [
    {
        'keywords': ['intoxication', 'empoisonnement', 'overdose', 'surdose', 'poison', 'toxique'],
        'severity': '🚨 URGENCE VITALE',
        'risk': 'Intoxication aiguë pouvant entraîner une défaillance multiviscérale, un arrêt cardiovasculaire ou un coma profond.',
        'actions': [
            '📞 **Appeler le 15 (SAMU) ou le 112 IMMÉDIATEMENT**',
            'Garder la personne en position latérale de sécurité (PLS) si conscience altérée',
            'Noter l\'heure, la nature et la quantité estimée de la substance ingérée',
            'Garder l\'emballage / le flacon pour identification par les secours',
        ],
        'avoid': [
            '❌ **NE PAS faire vomir** sans avis médical (risque d\'inhalation)',
            '❌ **NE PAS** donner à boire ou à manger',
            '❌ **NE PAS** utiliser d\'antidote "maison"',
            '❌ **NE PAS** laisser la personne seule',
        ],
        'treatment': '**💉 Prise en charge hospitalière spécialisée — SAMU**\nAntidote selon la substance (N-acétylcystéine pour paracétamol, naloxone pour opiacés, flumazénil pour benzodiazépines).\n⏱ **Délai critique : < 6h** pour la plupart des intoxications. Pronostic lié à la précocité de la prise en charge.',
    },
    {
        'keywords': ['douleur thoracique', 'oppression thoracique', 'infarctus', 'crise cardiaque',
                      'arrêt cardiaque', 'arrêt cardio', 'cardio-respiratoire',
                      'douleur poitrine', 'serrement poitrine'],
        'severity': '🚨 URGENCE VITALE',
        'risk': 'Syndrome coronarien aigu (SCA) avec risque d\'arrêt cardiorespiratoire immédiat ou de nécrose myocardique étendue. Chaque minute de myocarde en ischémie augmente la mortalité.',
        'actions': [
            '📞 **Appeler le 15 (SAMU) ou le 112 — NE PAS ATTENDRE**',
            'Asseoir la personne **en position demi-assise**, jambes relevées',
            'Si la personne a de la **trinitrine** prescrite : l\'aider à la prendre (1 prise sublinguale)',
            'Si **aspirine** disponible et pas d\'allergie : faire mâcher 250-500mg',
            'Rassurer et rester au calme en attendant les secours',
        ],
        'avoid': [
            '❌ **NE PAS** laisser la personne seule',
            '❌ **NE PAS** manger, boire ni fumer',
            '❌ **NE PAS** conduire soi-même aux urgences',
            '❌ **NE PAS** appliquer de chaleur ni de froid sur le thorax',
            '❌ **NE PAS** masser le thorax sauf si arrêt cardiaque confirmé',
        ],
        'treatment': '**💉 SMUR en urgence — Délai critique**\nOxygène, dérivés nitrés, aspirine IV, héparine, thrombolyse ou angioplastie primaire.\n⏱ **< 90 min** pour angioplastie primaire. Chaque minute de retard augmente la nécrose myocardique.',
    },
    {
        'keywords': ['détresse respiratoire', 'dyspnée', 'dyspnee', 'étouffe', 'etouffe',
                      'suffocation', 'asphyxie', 'respiration difficile', 'ne respire pas',
                      'apnée', 'apnee', 'arrêt respiratoire'],
        'severity': '🚨 URGENCE VITALE',
        'risk': 'Insuffisance respiratoire aiguë avec risque d\'hypoxémie sévère, d\'arrêt cardiorespiratoire et de séquelles neurologiques irréversibles.',
        'actions': [
            '📞 **Appeler le 15 (SAMU) ou le 112 IMMÉDIATEMENT**',
            'Mettre la personne **en position assise ou demi-assise** pour faciliter la respiration',
            'Ouvrir les fenêtres pour aérer la pièce',
            'Desserrer les vêtements (col, ceinture, cravate)',
            'Si la personne a un **traitement inhalé** (asthme, BPCO) : l\'aider à l\'utiliser',
        ],
        'avoid': [
            '❌ **NE PAS** allonger la personne à plat (aggrave la détresse)',
            '❌ **NE PAS** donner à boire',
            '❌ **NE PAS** laisser la personne seule',
            '❌ **NE PAS** utiliser d\'oreiller qui fléchit la nuque',
        ],
        'treatment': '**💉 SMUR — Oxygénothérapie d\'urgence**\nOxygène masque haute concentration, voire ventilation non invasive (VNI) ou intubation si nécessaire.\n⏱ **Délai critique : < 5 min** si apnée. Oxygène dès que possible.',
    },
    {
        'keywords': ['avc', 'accident vasculaire cérébral', 'hémiplégie', 'hemiplegie',
                      'paralysie visage', 'paralysie bras', 'bouche de travers',
                      'difficulté parler', 'difficulté parler', 'aphasie',
                      'perte vision', 'vision trouble', 'vertige brutal',
                      'maux de tête violent', 'mal de tête violent', 'céphalée brutale'],
        'severity': '🚨 URGENCE VITALE',
        'risk': 'Accident vasculaire cérébral (ischémique ou hémorragique) avec risque de lésions cérébrales irréversibles. La fenêtre thérapeutique est très courte.',
        'actions': [
            '📞 **Appeler le 15 (SAMU) ou le 112 — URGENCE ABSOLUE**',
            'Effectuer le test FAST :',
            '  • **Face** (visage) : demander un sourire — la bouche est-elle tombante ?',
            '  • **Arm** (bras) : demander de lever les bras — un bras tombe-t-il ?',
            '  • **Speech** (parole) : demander de répéter une phrase — la parole est-elle confuse ?',
            '  • **Time** : noter l\'heure exacte du début des symptômes',
            'Allonger la personne, tête légèrement surélevée, calme',
        ],
        'avoid': [
            '❌ **NE PAS** donner d\'aspirine (peut aggraver un AVC hémorragique)',
            '❌ **NE PAS** donner à manger ni à boire (risque de fausse route)',
            '❌ **NE PAS** bouger la personne sauf danger immédiat',
            '❌ **NE PAS** attendre que ça passe — chaque minute compte',
        ],
        'treatment': '**💉 Urgence neurologique — SAMU**\nThrombolyse IV (altéplase) si AVC ischémique < 4h30 ; thrombectomie mécanique si occlusion proximale < 6h (jusqu\'à 24h selon imagerie).\n⏱ **Délai critique : < 4h30** pour thrombolyse. Appeler le 15 dès le premier symptôme.',
    },
    {
        'keywords': ['allergie grave', 'choc anaphylactique', 'anaphylaxie',
                      'oedème', 'œdème', 'gonflement visage', 'gonflement lèvres',
                      'gonflement langue', 'urticaire généralisée', 'rougeur généralisée',
                      'piqûre grave', 'morsure grave', 'venin'],
        'severity': '🚨 URGENCE VITALE',
        'risk': 'Réaction anaphylactique sévère pouvant entraîner un œdème de Quincke (obstruction des voies aériennes), un bronchospasme ou un collapsus cardiovasculaire en quelques minutes.',
        'actions': [
            '📞 **Appeler le 15 (SAMU) ou le 112 IMMÉDIATEMENT**',
            'Allonger la personne **jambes surélevées** sauf si détresse respiratoire (alors position assise)',
            'Si **stylo d\'adrénaline** disponible (type Anapen, Epipen) : injecter immédiatement dans la face externe de la cuisse (à travers le vêtement possible)',
            'Déclencher les secours même si amélioration après adrénaline',
        ],
        'avoid': [
            '❌ **NE PAS** attendre que les symptômes s\'aggravent',
            '❌ **NE PAS** faire boire la personne',
            '❌ **NE PAS** laisser la personne debout',
            '❌ **NE PAS** donner d\'antihistaminique oral (trop lent et inefficace en urgence vitale)',
            '❌ **NE PAS** laisser la personne seule une seconde',
        ],
        'treatment': '**💉 Adrénaline IM — 1ère intention**\nAdrénaline 0.3-0.5mg IM (face antéro-latérale de cuisse), renouvelable à 5-15 min si besoin. Oxygène. Remplissage vasculaire. Corticothérapie IV.\n⏱ **Immédiat** — l\'adrénaline est le seul traitement qui sauve des vies en anaphylaxie.',
    },
    {
        'keywords': ['hémorragie', 'hemorragie', 'saignement abondant', 'saignement grave',
                      'blessure grave', 'plaie profonde', 'coupure artère', 'coupure grave'],
        'severity': '🚨 URGENCE VITALE',
        'risk': 'Hémorragie externe active avec risque de choc hémorragique, défaillance circulatoire et arrêt cardiaque en quelques minutes si non contrôlée.',
        'actions': [
            '📞 **Appeler le 15 (SAMU) ou le 112**',
            'Comprimer la plaie avec un **linge propre** (ou directement avec la main si rien d\'autre)',
            '**Maintenir la compression** — ne pas relâcher pour vérifier',
            'Surélever le membre qui saigne si possible et si pas de fracture',
            'Allonger la personne pour éviter la chute de tension',
        ],
        'avoid': [
            '❌ **NE PAS** enlever un objet planté dans la plaie',
            '❌ **NE PAS** relâcher la compression toutes les X minutes — une fois posée on la tient',
            '❌ **NE PAS** laver la plaie abondante (risque de retarder l\'hémostase)',
            '❌ **NE PAS** garrot sauf si compression inefficace et membre concerné',
            '❌ **NE PAS** donner à boire (nécessite anesthésie générale possible)',
        ],
        'treatment': '**💉 Contrôle de l\'hémorragie — SAMU**\nCompression directe maintenue, garrot si nécessaire (membre), remplissage vasculaire, transfusion si besoin, chirurgie hémostatique en urgence.\n⏱ **Délai critique : < 15 min** avant choc hémorragique irréversible.',
    },
    {
        'keywords': ['brûlure grave', 'brulure grave', 'brûlure 2ème', 'brulure 2eme',
                      'brûlure 3ème', 'brulure 3eme', 'grand brûlé', 'grand brulé',
                      'brûlure étendue', 'brulure etendue'],
        'severity': '🚨 URGENCE VITALE',
        'risk': 'Brûlure grave (2e ou 3e degré étendue) avec risque de déshydratation aiguë, choc hypovolémique, infection locale/généralisée et séquelles fonctionnelles.',
        'actions': [
            '📞 **Appeler le 15 (SAMU) ou le 112**',
            'Éloigner la personne de la source de chaleur',
            '**Arroser la brûlure à l\'eau tiède (15-25°C) pendant 15-20 minutes**',
            'Retirer les vêtements et bijoux non adhérents autour de la brûlure',
            'Couvrir la brûlure avec un linge propre, humide et stérile si possible',
        ],
        'avoid': [
            '❌ **NE PAS** appliquer de glace (aggrave la brûlure)',
            '❌ **NE PAS** percer les cloques',
            '❌ **NE PAS** appliquer de crème, beurre, dentifrice ou pommade',
            '❌ **NE PAS** retirer les vêtements collés à la brûlure',
            '❌ **NE PAS** souffler sur la brûlure pour la refroidir',
        ],
        'treatment': '**💉 Centre de grands brûlés — SAMU**\nRemplissage vasculaire (formule de Parkland), analgésie, parage des lésions, greffe cutanée si nécessaire.\n⏱ **Prise en charge spécialisée en centre de brûlés** idéalement < 24h.',
    },
    {
        'keywords': ['convulsion', 'convulsions', 'crise épilepsie', 'crise d\'épilepsie',
                      'status epilepticus', 'épilepsie', 'epilepsie',
                      'crise convulsive', 'secousses violentes'],
        'severity': '🚨 URGENCE VITALE',
        'risk': 'Crise convulsive généralisée prolongée (> 5 min) ou status epilepticus avec risque d\'hypoxie cérébrale, lésions neuronales irréversibles et détresse respiratoire.',
        'actions': [
            '📞 **Appeler le 15 (SAMU) — si crise > 5 minutes ou première crise**',
            'Protéger la tête de la personne avec un vêtement plié ou vos mains',
            'Éloigner les objets dangereux environnants',
            'Noter l\'heure précise du début de la crise',
            'Mettre en PLS après la fin des mouvements convulsifs',
        ],
        'avoid': [
            '❌ **NE PAS** mettre d\'objet dans la bouche (ne peut pas avaler la langue)',
            '❌ **NE PAS** maintenir la personne immobile de force',
            '❌ **NE PAS** donner de médicament par voie orale',
            '❌ **NE PAS** mettre d\'eau sur le visage',
            '❌ **NE PAS** laisser la personne seule après la crise',
        ],
        'treatment': '**💉 Urgence neurologique — SAMU**\nSi crise > 5 min : Valium (diazépam) intrarectal ou midazolam buccal par les secours. Hospitalisation pour bilan étiologique.\n⏱ **< 5 min** pour déclencher les secours. Status epilepticus = urgence vitale après 30 min.',
    },
    {
        'keywords': ['traumatisme crânien', 'traumatisme crane', 'chute tête', 'coup tête',
                      'perte connaissance', 'inconscient', 'coma', 'trauma crânien'],
        'severity': '🚨 URGENCE VITALE',
        'risk': 'Traumatisme crânien grave avec risque d\'hématome intracrânien (extradural, subdural), d\'hypertension intracrânienne et d\'engagement cérébral mortel.',
        'actions': [
            '📞 **Appeler le 15 (SAMU) ou le 112 IMMÉDIATEMENT**',
            'Ne pas bouger la personne sauf danger vital immédiat',
            'Évaluer la conscience : parle, ouvre les yeux, obéit aux ordres simples ?',
            'Si inconsciente : **PLS** et surveiller la respiration',
            'Noter l\'heure du traumatisme et s\'il y a eu perte de connaissance initiale',
        ],
        'avoid': [
            '❌ **NE PAS** mobiliser le cou (suspicion de lésion cervicale associée)',
            '❌ **NE PAS** laisser la personne se rendormir sans avis médical',
            '❌ **NE PAS** donner d\'aspirine ou d\'anti-inflammatoire',
            '❌ **NE PAS** laisser la personne faire un effort physique',
            '❌ **NE PAS** appliquer de glace directement sur la tête si douleur cervicale associée',
        ],
        'treatment': '**💉 Scanner cérébral en urgence — SAMU**\nImmobilisation cervicale, évaluation neurologique (Glasgow), scanner cérébral, neurochirurgie si hématome.\n⏱ **Délai critique : < 2h** pour évacuation d\'un hématome extradural.',
    },
    {
        'keywords': ['coup de chaleur', 'hyperthermie', 'insolation', 'thermostat'],
        'severity': '🚨 URGENCE VITALE',
        'risk': 'Coup de chaleur avec hyperthermie > 40°C, défaillance multiviscérale (neurologique, cardiovasculaire, rénale) et risque de décès en l\'absence de refroidissement rapide.',
        'actions': [
            '📞 **Appeler le 15 (SAMU) ou le 112**',
            'Mettre la personne à l\'ombre ou dans un endroit frais immédiatement',
            '**Refroidir activement :**',
            '  • Retirer les vêtements',
            '  • Appliquer des linges humides frais sur tout le corps',
            '  • Ventiler/mettre devant un ventilateur',
            '  • Si possible : poche de glace sur aisselles, cou, aine',
            'Faire boire **par petites gorgées** si personne consciente',
        ],
        'avoid': [
            '❌ **NE PAS** faire boire si personne inconsciente',
            '❌ **NE PAS** utiliser d\'eau glacée (risque de choc thermique)',
            '❌ **NE PAS** donner de paracétamol ou d\'ibuprofène (inefficaces sur l\'hyperthermie centrale)',
            '❌ **NE PAS** exposer de nouveau au soleil après refroidissement',
            '❌ **NE PAS** ignorer les signes (peau chaude et rouge, absence de transpiration, confusion)',
        ],
        'treatment': '**💉 Refroidissement actif — SAMU**\nRefroidissement par évaporation, perfusions froides, monitoring en réanimation.\n⏱ **Délai critique : < 30 min** pour abaisser la température < 39°C. Pronostic lié à la durée de l\'hyperthermie.',
    },
    {
        'keywords': ['noyade', 'quasi-noyade', 'eau', 'nager', 'noyé'],
        'severity': '🚨 URGENCE VITALE',
        'risk': 'Noyade ou quasi-noyade avec risque d\'hypoxémie sévère, arrêt cardiorespiratoire, lésions neurologiques irréversibles par anoxie cérébrale. Pronostic vital engagé immédiatement.',
        'actions': [
            '📞 **Appeler le 15 (SAMU) ou le 112 — et les pompiers (18)**',
            'Sortir la personne de l\'eau en se protégeant (ne pas se mettre en danger)',
            'Vérifier la conscience et la respiration',
            'Si **ne respire pas** : commencer la **RCP** (30 compressions thoraciques / 2 insufflations)',
            'Si respire : **PLS** et couvrir pour éviter l\'hypothermie',
        ],
        'avoid': [
            '❌ **NE PAS** se jeter à l\'eau si on ne sait pas nager ou si c\'est dangereux',
            '❌ **NE PAS** perdre de temps à vider l\'eau des poumons (inutile et retarde la RCP)',
            '❌ **NE PAS** arrêter la RCP avant l\'arrivée des secours',
            '❌ **NE PAS** boire d\'alcool pour "se réchauffer"',
            '❌ **NE PAS** sous-estimer une quasi-noyade (complications respiratoires secondaires)',
        ],
        'treatment': '**💉 RCP immédiate + SAMU**\nOxygénothérapie, ventilation artificielle, bilan gazométrique, radiographie pulmonaire. Hospitalisation systématique même si récupération clinique (risque d\'œdème pulmonaire secondaire).\n⏱ **Chaque minute sans oxygène** diminue les chances de survie neurologique.',
    },
]


def generate_emergency_response(question: str) -> str:
    """Génère une réponse au format urgence absolue"""
    text_lower = question.lower()

    best_match = None
    for case in EMERGENCY_RESPONSES:
        for kw in case['keywords']:
            if kw in text_lower:
                best_match = case
                break
        if best_match:
            break

    if not best_match:
        best_match = {
            'severity': '🚨 URGENCE',
            'risk': 'Situation médicale aiguë nécessitant une évaluation rapide par un professionnel de santé.',
            'actions': [
                '📞 **Appeler le 15 (SAMU) ou le 112**',
                'Suivre les instructions du médecin régulateur',
                'Rester au calme et rassurer la personne',
                'Préparer les informations utiles (âge, antécédents, traitements en cours, médicaments pris)',
            ],
            'avoid': [
                '❌ **NE PAS** tenter de soigner par soi-même sans avis médical',
                '❌ **NE PAS** administrer de médicament sans connaître la situation exacte',
            ],
            'treatment': '**💉 Bilan médical urgent — SAMU**\nPrise en charge adaptée à la situation par les services d\'urgence.\n⏱ **Ne pas tarder à appeler le 15.**',
        }

    response = f"""{best_match['severity']}

⚠️ **Risque principal :**
{best_match['risk']}

📞 **Action immédiate :"""
    for action in best_match['actions']:
        response += f"\n• {action}"

    if best_match.get('avoid'):
        response += f"\n\n❌ **À ne surtout pas faire :**"
        for avoid in best_match['avoid']:
            response += f"\n• {avoid}"

    response += f"\n\n💉 **Traitement urgent :**\n{best_match['treatment']}"

    response += """

📞 **Numéros d'urgence :**
• **15** — SAMU (urgence médicale)
• **112** — Numéro d'urgence européen
• **01 45 42 59 59** — Centre antipoison (24h/24)

*En cas de doute, appelez le 15 ou le 112 : une régulation médicale décidera de la prise en charge adaptée.*"""

    return response


@chatbot_bp.route('/chat', methods=['POST'])
def chat():
    """
    Endpoint principal du chatbot
    Répond aux questions en se basant sur les données des BDs
    """
    try:
        data = request.get_json(silent=True) or {}
        user_message = _nettoyer_message(data.get('message', ''))

        if not user_message:
            return jsonify({'success': False, 'error': 'Message vide'}), 400

        # Langue demandee par l'interface ; memorisee par visiteur pour que
        # le modele reponde dans la meme langue aux relances.
        langue = data.get('lang')
        if langue not in LANGUES_SUPPORTS:
            langue = session.get('cb_lang', 'fr')
        if langue not in LANGUES_SUPPORTS:
            langue = 'fr'
        session['cb_lang'] = langue

        # Garde-fou debit : au-dela, reponse 429 sans rappeler l'IA.
        cle = _cle_visiteur()
        autorise, attente = _verifier_rate_limit(cle)
        if not autorise:
            return jsonify({
                'success': False,
                'error': f'Trop de messages envoyés. Merci de patienter {attente} s.',
                'rate_limited': True,
                'retry_after': attente
            }), 429

        logger.info(f"Question du chatbot: {user_message[:120]}")

        historique = _historique_get(cle)

        # Détection d'urgence — réponse immédiate sans IA
        if detect_emergency(user_message):
            logger.info(f"[URGENCE] Détectée dans le message: {user_message}")
            emergency_response = generate_emergency_response(user_message)
            _historique_ajouter(cle, 'user', user_message)
            _historique_ajouter(cle, 'assistant', emergency_response)
            return jsonify({
                'success': True,
                'response': emergency_response,
                'sources': ['🆘 Mode Urgence'],
                'fiches': [],
                'emergency': True
            })
        
        # 1. Rechercher dans les bases de données des informations pertinentes
        context = gather_database_context(user_message)

        # 2. Fiches cliquables pour le client (titre + lien vers la page du medicament)
        fiches = []
        for med in context.get('medications', [])[:4]:
            identifiant = med.get('mongo_id')
            titre = med.get('title')
            if identifiant and titre:
                fiches.append({'id': str(identifiant), 'titre': titre})

        # 3. Générer la réponse avec Mistral AI enrichie du contexte et de l'historique
        response = generate_chatbot_response(user_message, context, historique, langue)

        _historique_ajouter(cle, 'user', user_message)
        _historique_ajouter(cle, 'assistant', response)

        return jsonify({
            'success': True,
            'response': response,
            'sources': context.get('sources', []),
            'fiches': fiches,
            'emergency': False
        })

    except Exception as e:
        logger.error(f"Erreur chatbot: {e}")
        return jsonify({
            'success': False,
            'error': 'Une erreur interne est survenue. Veuillez réessayer.'
        }), 500


LANGUES_SUPPORTS = ('fr', 'en', 'ar')

_CONSIGNE_LANGUE = {
    'fr': "Reponds en francais.",
    'en': "Answer in English.",
    'ar': "أجب باللغة العربية.",
}

_SUGGESTIONS_PAR_LANGUE = {
    'fr': [
        "Quels médicaments pour le diabète ?",
        "Paracétamol vs ibuprofène : quelles différences ?",
        "Quelle posologie du doliprane chez l'adulte ?",
        "Puis-je prendre du paracétamol avec de l'ibuprofène ?",
        "Traitements de l'hypertension artérielle",
        "Antibiotiques pour une infection urinaire",
        "Quels sont les effets secondaires de l'aspirine ?",
        "Médicaments contre le reflux gastrique",
    ],
    'en': [
        "Which medicines treat diabetes?",
        "Paracetamol vs ibuprofen: what are the differences?",
        "What is the adult dosage of paracetamol?",
        "Can I take paracetamol with ibuprofen?",
        "Treatments for high blood pressure",
        "Antibiotics for a urinary tract infection",
        "What are the side effects of aspirin?",
        "Medicines against acid reflux",
    ],
    'ar': [
        "ما هي الأدوية لعلاج السكري؟",
        "الباراسيتامول مقابل الإيبوبروفين: ما الفروق؟",
        "ما جرعة الدوليبران للبالغين؟",
        "هل يمكنني تناول الباراسيتامول مع الإيبوبروفين؟",
        "علاجات ارتفاع ضغط الدم",
        "مضادات حيوية لالتهاب المسالك البولية",
        "ما هي الآثار الجانبية للأسبرين؟",
        "أدوية ارتداد المريء",
    ],
}


@chatbot_bp.route('/suggestions')
def suggestions():
    """Questions d'exemple dans la langue demandee, tournantes par heure."""
    langue = request.args.get('lang', 'fr')
    if langue not in _SUGGESTIONS_PAR_LANGUE:
        langue = 'fr'
    pool = _SUGGESTIONS_PAR_LANGUE[langue]
    rotation = int(time.time() // 3600)
    picks = [pool[(rotation + i) % len(pool)] for i in range(4)]
    return jsonify({'success': True, 'suggestions': picks})


@chatbot_bp.route('/reset', methods=['POST'])
def reset():
    """Efface la memoire de conversation du visiteur."""
    try:
        _historique_effacer(_cle_visiteur())
    except Exception:
        pass
    return jsonify({'success': True})


def gather_database_context(question: str):
    """
    Rassemble le contexte pertinent depuis MongoDB, Qdrant et Neo4j
    """
    context = {
        'medications': [],
        'interactions': [],
        'statistics': {},
        'sources': []
    }
    
    try:
        # 1. Recherche vectorielle dans Qdrant pour trouver les médicaments pertinents
        question_embedding = embedding_model.encode(question).tolist()
        
        search_results = qdrant_client.query_points(
            collection_name="medicines",
            query=question_embedding,
            limit=5
        )
        
        medication_urls = []
        if search_results and hasattr(search_results, 'points'):
            for point in search_results.points:
                if hasattr(point, 'payload'):
                    med_url = point.payload.get('url', '')
                    if med_url:
                        medication_urls.append(med_url)

                    med_info = {
                        'title': point.payload.get('title', ''),
                        'url': med_url,
                        'mongo_id': point.payload.get('mongo_id', ''),
                        'substances': point.payload.get('substances', []),
                        'forme': point.payload.get('forme', ''),
                        'score': point.score if hasattr(point, 'score') else 0
                    }
                    context['medications'].append(med_info)
                    context['sources'].append(f"Qdrant: {med_info['title']}")
        
        # 2. Enrichir avec MongoDB pour des informations complémentaires
        for med in context['medications']:
            mongo_med = None
            identifiant = med.get('mongo_id')
            if identifiant:
                try:
                    mongo_med = db.medicines.find_one(
                        {'_id': ObjectId(identifiant)},
                        {'indications': 1, 'classe_therapeutique': 1,
                         'composition': 1, 'medicine_details.description_courte': 1}
                    )
                except Exception:
                    mongo_med = None
            if not mongo_med and med.get('url'):
                mongo_med = db.medicines.find_one(
                    {'url': med['url']},
                    {'indications': 1, 'classe_therapeutique': 1,
                     'composition': 1, 'medicine_details.description_courte': 1}
                )
            if mongo_med:
                med['indications'] = mongo_med.get('indications', '')
                med['classe'] = mongo_med.get('classe_therapeutique', '')
                med['composition'] = mongo_med.get('composition', '')
                details = mongo_med.get('medicine_details') or {}
                med['description'] = details.get('description_courte', '')
        
        # 3. Statistiques générales
        context['statistics'] = {
            'total_medications': db.medicines.count_documents({}),
            'total_interactions': db.interactions.count_documents({})
        }
        
        # 4. Rechercher des interactions via Neo4j si disponible, sinon MongoDB
        if any(word in question.lower() for word in ['interaction', 'compatible', 'mélanger', 'ensemble', 'combinaison', 'prendre avec']):
            try:
                # Extraire les substances/médicaments de la question
                search_terms = []
                
                # 1. Titres des médicaments trouvés par Qdrant
                for med in context['medications']:
                    if med.get('title'):
                        search_terms.append(med['title'].lower())
                    if med.get('substances'):
                        search_terms.extend([s.lower() for s in med['substances']])
                    if med.get('composition'):
                        comp = med['composition'].lower()
                        search_terms.extend([s.strip() for s in comp.split(',')[:3]])
                
                # 2. Extraire substances de la question
                common_substances = ['paracétamol', 'paracetamol', 'ibuprofène', 'ibuprofen', 
                                    'warfarine', 'warfarin', 'metformine', 'metformin', 
                                    'amoxicilline', 'amoxicillin', 'codéine', 'codeine',
                                    'aspirine', 'aspirin', 'doliprane', 'codoliprane']
                
                question_lower = question.lower()
                for substance in common_substances:
                    if substance in question_lower:
                        search_terms.append(substance)

                # 3. Les mots de la question eux-mêmes.
                #
                # Sans cela, seuls comptaient les seize noms de la liste
                # ci-dessus et les titres remontés par Qdrant — dont la
                # recherche sémantique rapporte souvent autre chose que le
                # médicament cité. « Quelles interactions pour le TERALITHE ? »
                # cherchait ainsi les interactions du norgestimate.
                # Le nom du médicament mène désormais à sa substance par le
                # chemin Medicine → HAS_DRUGBANK_SUBSTANCE.
                MOTS_VIDES = {
                    'quelles', 'quels', 'quelle', 'interaction', 'interactions',
                    'pour', 'avec', 'dans', 'entre', 'compatible', 'ensemble',
                    'prendre', 'puis', 'peut', 'faut', 'est-il', 'sont', 'les',
                    'des', 'une', 'mon', 'mes', 'combinaison', 'melanger',
                    'medicament', 'medicaments', 'traitement',
                }
                for mot in re.findall(r"[A-Za-zÀ-ÿ][\w\-']{3,}", question):
                    if mot.lower() not in MOTS_VIDES:
                        search_terms.append(mot.lower())

                # Nettoyer et dédupliquer.
                #
                # `list(set(...))` rendait un ordre arbitraire, puis seuls les
                # cinq premiers termes étaient interrogés : le médicament cité
                # par l'utilisateur se faisait évincer par les titres que
                # Qdrant avait rapportés par proximité sémantique. Les termes
                # venus de la question passent donc devant, et la déduplication
                # préserve l'ordre.
                termes_question = {
                    t for t in search_terms
                    if t and t.lower() in question_lower
                }
                search_terms = [s.strip() for s in search_terms if s and len(s) > 2]
                ordonnes = ([s for s in search_terms if s in termes_question]
                            + [s for s in search_terms if s not in termes_question])
                vus, search_terms = set(), []
                for s in ordonnes:
                    if s not in vus:
                        vus.add(s)
                        search_terms.append(s)
                search_terms = search_terms[:10]
                
                logger.info(f"[CHATBOT] Recherche interactions pour: {search_terms}")
                
                # Essayer Neo4j d'abord si disponible
                neo4j_success = False
                connecteur = _neo4j() if search_terms else None
                if connecteur:
                    try:
                        with connecteur.driver.session(database=connecteur.database) as session:
                            # Compter les interactions réellement en service.
                            #
                            # Le compte portait sur les nœuds `Interaction`, un
                            # magasin de 566 693 entrées dont 99,99 % sont
                            # classées « low » par une gravité sans source, et
                            # que la reconstruction P9-3 remplace.
                            try:
                                count_result = session.run("""
                                    MATCH (:DrugbankSubstance)-[r:INTERACTS_WITH]-(:DrugbankSubstance)
                                    RETURN count(r)/2 AS total
                                """)
                                count_record = count_result.single()
                                if count_record:
                                    context['statistics']['total_interactions_neo4j'] = count_record['total']
                                    # `total_interactions` comptait la collection
                                    # MongoDB `interactions`, vide : le prompt
                                    # annonçait au modèle « 0 interaction
                                    # répertoriée » alors que le graphe en porte
                                    # plus de cent trente mille.
                                    context['statistics']['total_interactions'] = count_record['total']
                            except:
                                pass

                            # Chercher les interactions dans la couche substance.
                            #
                            # Le terme peut désigner une molécule (« warfarin »)
                            # ou une spécialité (« DOLIPRANE ») : les deux
                            # chemins mènent au même nœud substance.
                            for term in search_terms[:5]:
                                result = session.run("""
                                    MATCH (s1:DrugbankSubstance)
                                    WHERE toLower(s1.name) CONTAINS toLower($term)
                                       OR EXISTS {
                                            MATCH (m:Medicine)-[:HAS_DRUGBANK_SUBSTANCE]->(s1)
                                            WHERE toLower(coalesce(m.title, '')) CONTAINS toLower($term)
                                          }
                                    MATCH (s1)-[r:INTERACTS_WITH]-(s2:DrugbankSubstance)
                                    RETURN s1.name AS substance1, s2.name AS substance2,
                                           r.description AS description
                                    LIMIT 5
                                """, {'term': term})

                                for record in result:
                                    # Pas de `severity` : la source DrugBank n'en
                                    # porte aucune. Le champ est absent plutôt
                                    # que rempli d'une valeur inventée, qui
                                    # partirait telle quelle dans le prompt.
                                    context['interactions'].append({
                                        'medicine1_title': record['substance1'],
                                        'medicine2_title': record['substance2'],
                                        'description': record['description']
                                    })
                            
                            if context['interactions']:
                                # Dédupliquer
                                seen = set()
                                unique_interactions = []
                                for inter in context['interactions']:
                                    key = f"{inter['medicine1_title']}-{inter['medicine2_title']}"
                                    if key not in seen:
                                        unique_interactions.append(inter)
                                        seen.add(key)
                                context['interactions'] = unique_interactions
                                context['sources'].append(f"Neo4j: {len(context['interactions'])} interactions")
                                neo4j_success = True
                                logger.info(f"[CHATBOT] {len(context['interactions'])} interactions trouvées dans Neo4j")
                    
                    except Exception as neo_err:
                        logger.error(f"Erreur Neo4j dans chatbot: {neo_err}")
                
                # Fallback MongoDB si Neo4j échoue ou pas de résultats
                if not neo4j_success and search_terms:
                    interactions_found = []
                    for term in search_terms[:5]:
                        interactions = db.interactions.find({
                            "$or": [
                                {"substance1": {"$regex": term, "$options": "i"}},
                                {"substance2": {"$regex": term, "$options": "i"}}
                            ]
                        }).limit(5)
                        
                        for interaction in interactions:
                            interactions_found.append({
                                'medicine1_title': interaction.get('substance1', 'N/A'),
                                'medicine2_title': interaction.get('substance2', 'N/A'),
                                'severity': interaction.get('severity', 'unknown'),
                                'description': interaction.get('description', 'Pas de description disponible')
                            })
                    
                    # Dédupliquer
                    seen = set()
                    for inter in interactions_found:
                        key = f"{inter['medicine1_title']}-{inter['medicine2_title']}"
                        if key not in seen:
                            context['interactions'].append(inter)
                            seen.add(key)
                    
                    if context['interactions']:
                        context['sources'].append(f"MongoDB: {len(context['interactions'])} interactions")
                        logger.info(f"[CHATBOT] {len(context['interactions'])} interactions trouvées dans MongoDB")
            
            except Exception as err:
                logger.error(f"Erreur recherche interactions dans chatbot: {err}")
        
    except Exception as e:
        logger.error(f"Erreur lors de la collecte du contexte: {e}")
    
    return context


def generate_chatbot_response(question: str, context: dict, historique=None, langue='fr'):
    """
    Génère une réponse intelligente avec Mistral AI basée sur le contexte
    Inclut un système de retry en cas d'erreur 503

    La réponse s'appuie sur :
    - un message système qui fixe le rôle, les interdits, la langue et le format ;
    - l'historique récent de la conversation (fenêtre courte) ;
    - le contexte réel des bases (médicaments, interactions, statistiques).
    """
    if not MISTRAL_API_KEY:
        return "Désolé, le service IA n'est pas configuré. Veuillez contacter l'administrateur."

    # Construire le contexte enrichi
    context_text = f"""
**Base de données POSOLOGYAI:**
- {context['statistics'].get('total_medications', 0)} médicaments disponibles
- {context['statistics'].get('total_interactions', 0)} interactions médicamenteuses répertoriées

**Médicaments pertinents trouvés:**
"""

    for i, med in enumerate(context['medications'][:5], 1):
        context_text += f"\n{i}. **{med.get('title', 'N/A')}**"
        if med.get('description'):
            context_text += f"\n   Description: {med['description']}"
        if 'indications' in med and med['indications']:
            context_text += f"\n   Indications: {med['indications']}"
        if 'substances' in med and med['substances']:
            context_text += f"\n   Substances: {', '.join(med['substances'])}"
        if med.get('classe'):
            context_text += f"\n   Classe: {med['classe']}"

    if context['interactions']:
        # Les interactions sont énoncées entre substances, et sans niveau de
        # gravité — la source n'en porte aucun. L'ancien format injectait
        # `severity` dans le prompt, ce qui faisait reprendre au modèle une
        # gradation de risque que rien n'étaye.
        context_text += "\n\n**Interactions connues (source DrugBank, entre substances actives) :**\n"
        for interaction in context['interactions'][:3]:
            sev = interaction.get('severity')
            niveau = f" [{sev}]" if sev and sev != 'unknown' else ""
            context_text += (f"\n- {interaction.get('medicine1_title')}"
                             f" + {interaction.get('medicine2_title')}{niveau}"
                             f" : {interaction.get('description', '')}")
        context_text += ("\n(Ces libellés ne comportent pas de niveau de gravité : "
                         "ne pas en inventer, et renvoyer au RCP.)")

    systeme = """Tu es POSOLOGYAI L'ASSISTANT, l'assistant medical de la plateforme PosologyAI.

TON ROLE :
- Repondre aux questions sur les medicaments en t'appuyant EN PRIORITE sur les donnees reelles de la base fournies ci-dessous.
- Citer explicitement les noms des medicamentos trouves quand ils sont pertinents.
- Completer avec des connaissances medicales generales fiables si la base ne suffit pas.
- Tenir compte de l'historique de la conversation : « et pour les enfants ? » fait reference au sujet precedent.

INTERDITS ABSOLUS :
- N'invente jamais de nom de medicament, de posologie ou de chiffre absent des donnees ou de tes connaissances etablies.
- Ne fournis jamais de posologie pour un enfant sans le rappeler adapte au poids et avis medical.
- Pas de diagnostic personnel : orienter vers un professionnel de sante.
- Si aucune information ne correspond, dis-le clairement plutot que d'improviser.

FORMAT DE REPONSE — obligatoire :
- Markdown leger uniquement : **gras** pour les noms de medicaments et titres, tirets (- ) pour les listes. Jamais de HTML, jamais de blocs de code.
- Maximum 150 mots sauf question demandant du detail.
- Termine par une courte phrase invitant a consulter un professionnel de sante quand la reponse touche a un traitement.

LANGUE DE REPONSE — obligatoire :
{consigne_langue}""".format(consigne_langue=_CONSIGNE_LANGUE.get(langue, _CONSIGNE_LANGUE['fr']))

    messages = [{"role": "system", "content": systeme}]
    for tour in (historique or [])[-_HISTORIQUE_TOURS_MAX * 2:]:
        if isinstance(tour, dict) and tour.get('role') in ('user', 'assistant') and tour.get('content'):
            messages.append({"role": tour['role'], "content": tour['content']})

    messages.append({"role": "user", "content": f"""**Question de l'utilisateur:** {question}

**Données RÉELLES de notre base de données:**
{context_text}

Réponds maintenant à la question en respectant ton rôle:"""})

    # Système de retry pour gérer les erreurs temporaires de l'API
    max_retries = 3
    retry_delay = 2
    
    for attempt in range(max_retries):
        try:
            client = Mistral(api_key=MISTRAL_API_KEY)
            chat_response = client.chat.complete(
                model="mistral-small-2503",
                messages=messages,
                temperature=0.4,
                max_tokens=450
            )
            
            response = chat_response.choices[0].message.content.strip()
            logger.info(f"Réponse chatbot générée pour: {question}")
            return response
            
        except Exception as e:
            error_message = str(e)
            logger.error(f"Erreur génération réponse Mistral (tentative {attempt + 1}/{max_retries}): {error_message}")
            
            # Vérifier si c'est une erreur 503 (serveur surchargé)
            if "503" in error_message or "unreachable_backend" in error_message:
                if attempt < max_retries - 1:
                    # Attendre avant de réessayer
                    time.sleep(retry_delay)
                    retry_delay *= 2  # Backoff exponentiel
                    continue
                else:
                    # Dernière tentative échouée, réponse de fallback avec connaissances cliniques
                    # Construire une réponse à partir du fallback clinique si aucun médicament trouvé
                    med_count = len(context.get('medications', []))
                    if not context.get('medications'):
                        clinical = get_clinical_fallback(question)
                        return f"""Je suis désolé, le service d'intelligence artificielle est temporairement surchargé.

Voici des informations basées sur les connaissances médicales standard :

{chr(10).join(f"• **{m['name']}** : {m['explanation']}" for m in clinical[:3])}

Notre base contient {context['statistics'].get('total_medications', 0)} médicaments référencés. Vous pouvez les consulter via la recherche.

*Consultez un professionnel de santé pour un avis médical personnalisé.*"""
                    return f"""Je suis désolé, le service d'intelligence artificielle est temporairement surchargé.

Voici ce que j'ai trouvé dans notre base de données :

• {med_count} médicament(s) pertinent(s) trouvé(s)

Notre base contient {context['statistics'].get('total_medications', 0)} médicaments et {context['statistics'].get('total_interactions', 0)} interactions.

Veuillez réessayer dans quelques instants ou utilisez la recherche classique pour plus de détails."""
            else:
                # Autre type d'erreur
                return f"""Désolé, une erreur technique s'est produite. 

Notre base de données contient {context['statistics'].get('total_medications', 0)} médicaments que vous pouvez consulter via la recherche classique.

Erreur technique : {error_message[:100]}"""
    
    # Ne devrait jamais arriver ici, mais par sécurité
    return "Une erreur inattendue s'est produite. Veuillez réessayer."
