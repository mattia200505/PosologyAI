# --- Filtre Jinja2 pour traduction dynamique Google Translate ---

# Les nombreux print() du module portent des emojis et des accents :
# des que la sortie est redirigee (service, pipe, fichier de log), la
# console Windows repasse en cp1252 et chaque emoji levait
# UnicodeEncodeError — l'application mourait au demarrage. Forcer
# l'UTF-8 sur les deux flux supprime cette dependance au terminal.
import sys as _sys
for _flux in (_sys.stdout, _sys.stderr):
    try:
        _flux.reconfigure(encoding='utf-8', errors='replace')
    except (AttributeError, ValueError):
        pass

from ai_summary import get_or_generate_summary, call_mistral_reformulate, call_mistral_summarize, summary_is_fresh
# --- Initialisation Flask et Qdrant ---

from flask import Flask, request, render_template, jsonify, abort, redirect, url_for, stream_with_context, Response, session, g, send_file
from flask_cors import CORS
from qdrant_client import QdrantClient
from sentence_transformers import SentenceTransformer
from pymongo import MongoClient
from bson.objectid import ObjectId
from bson.errors import InvalidId
import gzip
import json
from bson import json_util
import time
import hashlib
from functools import lru_cache
import os
import datetime
from models import init_db, mongo, User
import interaction_i18n
import users  # Importer le module users complet
from users import users_bp  # Importer le blueprint users_bp
from users import role_required  # Importer la fonction spécifique role_required
from config import get_config
# Import the AI summary module
from ai_summary import get_or_generate_summary
# Import blueprints
from prescription_helper import prescription_bp, get_clinical_fallback
from chatbot import chatbot_bp
from ordonnance_generator import OrdonnanceGenerator
from neo4j_connector import Neo4jConnector
from difflib import SequenceMatcher
import re
# CHANGÉ : Google Translate au lieu de Mistral pour traduction instantanée
from live_translator_google import translate_medicines_live_google
import live_translator_google
from medicine_categories import MEDICINE_CATEGORIES, get_category_for_type, get_all_types
from source_links import SOURCE_URLS, get_source_info
import regulatory
import pharmacogenomique


#: Langues servies par le site. Une valeur hors de cette liste est ignoree
#: plutot que propagee : `libelle()` rendrait l'anglais pour un code
#: inconnu, ce qui donnerait une page a moitie traduite sans le dire.
LANGUES = ('fr', 'en', 'ar')


def langue_demandee():
    """La langue de la requete : l'URL d'abord, le cookie ensuite.

    Les routes lisaient chacune `request.args.get('lang', 'fr')`, et six
    sur sept ignoraient le cookie. Le selecteur de langue, lui, n'ecrit
    pas dans l'URL : son choix n'atteignait donc jamais le rendu serveur,
    et les 148 libelles poses par `libelle()` restaient en francais quelle
    que soit la langue affichee ailleurs.

    L'URL garde la priorite : un lien partage avec `?lang=en` doit
    s'ouvrir en anglais chez qui a choisi le francais.
    """
    from flask import request as _rq
    demande = (_rq.args.get('lang')
               or _rq.form.get('lang')
               or _rq.cookies.get('preferred_lang')
               or 'fr')
    demande = demande.strip().lower()
    return demande if demande in LANGUES else 'fr'
from enrichment_service import EnrichmentService

# --- Initialisation Flask et Qdrant ---
app = Flask(__name__)
# Charger la configuration

# --- Filtre Jinja2 pour traduction dynamique Google Translate ---
from deep_translator import GoogleTranslator

# Memoire des traductions deja obtenues, pour la duree du processus.
#
# Chaque appel part sur le reseau. Les libelles qu'on traduit ici sont
# pourtant tres repetitifs — les memes formes pharmaceutiques et les memes
# substances reviennent a chaque page. Sans cette memoire, afficher un menu
# de filtres en anglais coutait une requete HTTP par entree, a chaque
# chargement de page.
_TRADUCTIONS_VUES = {}
_TRADUCTIONS_MAX = 5000


def google_translate(text, src='fr', dest='en'):
    if not text or not isinstance(text, str):
        return text

    cle = (text, src, dest)
    if cle in _TRADUCTIONS_VUES:
        return _TRADUCTIONS_VUES[cle]

    try:
        traduit = GoogleTranslator(source=src, target=dest).translate(text)
    except Exception as e:
        # `TranslationNotFound` notamment : le service ne rend rien pour
        # certains libelles — « Vitamine A synthetique - forme huileuse » en
        # est un. Rendre le texte d'origine laisse la page s'afficher en
        # francais a cet endroit precis, ce qui est toujours preferable a
        # une erreur 500 sur la page entiere.
        print(f"[JINJA TRANSLATE] Erreur: {e}")
        return text

    # Une reponse vide n'est pas une traduction : on garde l'original.
    if not traduit:
        return text

    if len(_TRADUCTIONS_VUES) < _TRADUCTIONS_MAX:
        _TRADUCTIONS_VUES[cle] = traduit
    return traduit


app.jinja_env.filters['google_translate'] = google_translate

app_config = get_config()
app.config.from_object(app_config)

# Enable CORS for all routes
CORS(app, resources={
    r"/api/*": {
        "origins": ["http://127.0.0.1:5000", "http://localhost:5000", "http://192.168.1.122:5000"],
        "methods": ["GET", "POST", "OPTIONS"],
        "allow_headers": ["Content-Type"]
    }
})


# ─── Compression des réponses ─────────────────────────────────────────
# Rien n'était compressé : une fiche complète partait en 565 031 octets sur le
# fil, une feuille de style en 43 409. En gzip, 90 840 et 8 798 — six fois
# moins, sans rien retirer de la page. C'est le seul allègement qui ne coûte
# aucune fonctionnalité : la recherche du navigateur, l'impression et les
# lecteurs d'écran continuent de voir le document entier.
#
# Écrit à la main plutôt qu'avec flask-compress : quinze lignes contre une
# dépendance de plus, et surtout le contrôle exact des exclusions — la route
# de résumé en `text/event-stream` ne doit jamais être tamponnée, sans quoi
# le flux n'arrive qu'à la fin.
TAILLE_MINIMALE_GZIP = 1024          # en deçà, l'en-tête coûte plus qu'il ne gagne
PLAFOND_TAMPON = 4 * 1024 * 1024     # au-delà, on laisse passer sans charger en mémoire
TYPES_COMPRESSIBLES = ('text/', 'application/json', 'application/javascript',
                       'application/xml', 'image/svg+xml')


@app.after_request
def ne_pas_garder_les_pages(response):
    """Interdit au navigateur de conserver une page HTML.

    Les pages ne portaient aucun en-tête de cache : ni `Cache-Control`, ni
    `ETag`, ni `Last-Modified`. Le navigateur était donc libre d'appliquer sa
    propre heuristique et de resservir une version conservée. Un correctif
    déployé restait alors invisible, et le défaut paraissait persister alors
    qu'il était corrigé.

    Le scénario s'est produit : un défaut de script corrigé côté serveur
    continuait de se manifester à l'écran.

    Les scripts et les feuilles de style, eux, gardent leur cache : ils
    portent une empreinte et se rechargent quand ils changent. Seul le
    document HTML est concerné, et il est bâti à chaque requête de toute
    façon.
    """
    if response.mimetype == 'text/html':
        response.headers['Cache-Control'] = 'no-store, must-revalidate'
    return response


@app.after_request
def compresser(response):
    accepte = request.headers.get('Accept-Encoding', '')
    if 'gzip' not in accepte.lower():
        return response
    if response.status_code < 200 or response.status_code >= 300:
        return response
    if response.headers.get('Content-Encoding'):
        return response
    type_contenu = (response.headers.get('Content-Type') or '').split(';')[0]
    # Le flux de résumé n'est jamais tamponné : lire son corps le consommerait,
    # et l'attente ne servirait plus à rien puisque tout arriverait d'un coup
    # à la fin.
    if type_contenu == 'text/event-stream':
        return response
    if not type_contenu.startswith(TYPES_COMPRESSIBLES):
        return response
    if response.content_length is not None and response.content_length < TAILLE_MINIMALE_GZIP:
        return response

    # Les fichiers statiques passent par `send_file`, qui laisse le corps en
    # `direct_passthrough` et le déclare « en flux » puisque sa longueur ne se
    # déduit pas de l'itérable. Un `is_streamed` en tête de fonction les avait
    # donc tous exclus — c'est-à-dire les 152 Ko de feuilles de style, qui se
    # compriment cinq fois. On lève le drapeau quand la longueur est connue et
    # sous un plafond, de sorte qu'un gros téléchargement continue de partir
    # sans être chargé en mémoire.
    if response.direct_passthrough:
        if response.content_length is None or response.content_length > PLAFOND_TAMPON:
            return response
        response.direct_passthrough = False
    elif response.is_streamed:
        return response

    corps = response.get_data()
    if len(corps) < TAILLE_MINIMALE_GZIP:
        return response
    # Niveau 6 : au-delà, le gain se compte en pour-cent et le coût en
    # millisecondes. Mesuré sur la fiche ACTISKENAN, 6 rend 90 840 octets,
    # 9 en rend 88 601 pour quatre fois le temps de calcul.
    response.set_data(gzip.compress(corps, 6))
    response.headers['Content-Encoding'] = 'gzip'
    response.headers['Content-Length'] = str(len(response.get_data()))
    # Sans `Vary`, un cache intermédiaire servirait la version compressée à un
    # client qui ne l'accepte pas.
    response.headers.add('Vary', 'Accept-Encoding')
    return response


# ─── Notice patient dupliquée ─────────────────────────────────────────
# Le collecteur ANSM a rangé la notice patient entière, non découpée, dans un
# unique bloc de texte — 34 143 caractères sur ACTISKENAN, jusqu'à 67 876
# ailleurs. Le titre sous lequel elle atterrit est presque toujours le même :
# « 12. INSTRUCTIONS POUR LA PREPARATION DES RADIOPHARMACEUTIQUES », dont le
# contenu réel tient en deux mots — « Sans objet. » Le parseur a visiblement
# pris tout ce qui suivait cette section jusqu'à la fin du document.
#
# La fiche affichait donc la notice deux fois : une fois en mur de texte
# illisible sous un intitulé parlant de radiopharmaceutiques, une fois
# correctement structurée dans les sections suivantes.
#
# 11 708 fiches sur 13 594 sont concernées, soit 752 Mo de texte. ACTISKENAN
# en porte six copies : trois du corps entier, deux du sommaire, une du même
# corps collecté sous une autre forme.
#
# Vérifié avant d'écrire ce filtre : aucune fiche où l'un de ces blocs serait
# la seule copie, une couverture médiane de 86 % des phrases par les sections
# structurées, et un reliquat fait uniquement d'apprêt ANSM identique d'une
# fiche à l'autre (« Vous pourriez avoir besoin de la relire. ») et
# d'artefacts de collecte (« Redirection vers le haut de page », « Imprimer »).
#
# Le filtre agit au rendu, pas en base : les données restent intactes, et
# corriger le collecteur reste le vrai remède.

#: Un bloc est un rebut de collecte quand il *commence* par l'une de ces
#: amorces. Elles ont été relevées sur quatre mille fiches, où elles ouvrent
#: 27 363 blocs de plus de 300 caractères ; aucune autre amorce fréquente n'est
#: un artefact — « Si vous ressentez un quelconque effet indésirable… » ouvre
#: 2 359 blocs, mais à l'intérieur des sections structurées, où il a sa place.
#:
#: Le début du texte sert de critère, pas sa longueur : les trois variantes
#: vont de 350 à 59 789 caractères. Un seuil de 8 000 laissait passer les
#: sommaires de notice de 505 caractères, aussi recopiés qu'inutiles.
AMORCES_NOTICE_DUPLIQUEE = (
    'Sommaire de la notice',                 # le corps entier de la notice
    'Imprimer Notice patient ANSM',          # la même, collectée autrement
    'Dénomination du médicament Encadré',    # son sommaire seul
)


def _est_notice_dupliquee(item):
    return (item.get('text') or '').strip().startswith(AMORCES_NOTICE_DUPLIQUEE)


def retirer_notice_dupliquee(medicine):
    """Retire les blocs de notice recopiée. Rend le nombre de blocs écartés.

    Une section vidée de tout contenu est retirée elle aussi : laisser
    « 12. INSTRUCTIONS POUR LA PREPARATION DES RADIOPHARMACEUTIQUES » suivi de
    « Cette section ne contient pas de contenu » n'apprend rien au lecteur.
    On ne retire que les sections devenues vides — celles qui portaient une
    vraie information à côté du bloc la gardent.
    """
    sections = medicine.get('sections')
    if not sections:
        return 0

    retires = 0
    conservees = []
    for section in sections:
        contenu = section.get('content') or []
        propre = [it for it in contenu if not _est_notice_dupliquee(it)]
        retires += len(contenu) - len(propre)
        if len(propre) != len(contenu):
            section['content'] = propre
        if propre or section.get('subsections'):
            conservees.append(section)

    if retires:
        medicine['sections'] = conservees
    return retires


# Helper function to translate medicines on-the-fly with Mistral
def translate_medicines_live(medicines, lang):
    """
    Traduit les médicaments avec Google Translate (GRATUIT):
    1. Utilise les champs *_en s'ils existent en base
    2. Sinon utilise Google Translate pour traduction instantanée
    """
    if lang != 'en' or not medicines:
        return medicines
    
    translated = []
    medicines_to_translate = []
    
    for medicine in medicines:
        # Check for stored translation
        if medicine.get('title_en'):
            # Create a shallow copy to modify for display
            med_en = medicine.copy()
            
            # Swap fields
            if med_en.get('title_en'): med_en['title'] = med_en['title_en']
            if med_en.get('medicine_details_en'): med_en['medicine_details'] = med_en['medicine_details_en']
            if med_en.get('sections_en'): med_en['sections'] = med_en['sections_en']
            if med_en.get('type_medicament_en'): med_en['type_medicament'] = med_en['type_medicament_en']
            if med_en.get('groupe_anatomique_en'): med_en['groupe_anatomique'] = med_en['groupe_anatomique_en']
            if med_en.get('famille_therapeutique_en'): med_en['famille_therapeutique'] = med_en['famille_therapeutique_en']

            translated.append(med_en)
        else:
            # Marquer pour traduction live avec Google Translate
            medicines_to_translate.append(medicine)
    
    # Traduire avec Google Translate si nécessaire
    if medicines_to_translate:
        try:
            print(f"[GOOGLE TRANSLATE] 🔄 Traduction de {len(medicines_to_translate)} médicaments...")
            translated_batch = translate_medicines_live_google(medicines_to_translate, lang)
            translated.extend(translated_batch)
            print(f"[GOOGLE TRANSLATE] ✅ Traduction terminée")
        except Exception as e:
            print(f"[GOOGLE TRANSLATE] ⚠️ Erreur: {e}")
            # En cas d'erreur, garder les originaux
            translated.extend(medicines_to_translate)
            
    return translated

# Helper function to get category emoji for medicine type
def get_type_display(type_medicament):
    """
    Retourne le type avec son emoji de catégorie
    
    Args:
        type_medicament: Le type de médicament
        
    Returns:
        dict avec 'emoji', 'type' et 'category'
    """
    if not type_medicament:
        return None
    
    category_info = get_category_for_type(type_medicament)
    if category_info:
        return {
            'emoji': category_info['emoji'],
            'type': type_medicament,
            'category': category_info['category_name']
        }
    return {
        'emoji': '💊',
        'type': type_medicament,
        'category': 'Autre'
    }

# Register the helper function as a Jinja2 filter
app.jinja_env.filters['get_type_display'] = get_type_display

# Initialize Qdrant with configuration from config
qdrant_client = QdrantClient(
    host=app_config.QDRANT_HOST,
    port=app_config.QDRANT_PORT,
    timeout=app_config.QDRANT_TIMEOUT,
    prefer_grpc=app_config.QDRANT_PREFER_GRPC,
    api_key=app_config.QDRANT_API_KEY if app_config.QDRANT_API_KEY else None
)
embedding_model = SentenceTransformer("all-MiniLM-L6-v2")

# Initialize Neo4j connection
neo4j_connector = None
try:
    neo4j_connector = Neo4jConnector(
        uri=app_config.NEO4J_URI,
        user=app_config.NEO4J_USER,
        password=app_config.NEO4J_PASSWORD,
        database=app_config.NEO4J_DATABASE
    )
    try:
        if neo4j_connector.connect():
            print("[INFO] ✅ Neo4j connecté avec succès")
        else:
            print("[WARNING] ⚠️ Neo4j non disponible")
            neo4j_connector = None
    except (ConnectionRefusedError, TimeoutError, KeyboardInterrupt, Exception) as err:
        print(f"[WARNING] ⚠️ Neo4j non disponible: {err}")
        neo4j_connector = None
except Exception as e:
    print(f"[WARNING] ⚠️ Impossible d'initialiser Neo4j: {e}")
    neo4j_connector = None

# Exposer le connecteur dans l'app pour les blueprints
app.neo4j = neo4j_connector

# Import scraper API
try:
    from scraper_api import scraper_bp
    app.register_blueprint(scraper_bp)
except Exception as e:
    print(f"[WARNING] ⚠️ Impossible d'initialiser le scraper: {e}")

# Register blueprints
#
# `users_bp` n'est **pas** enregistré ici : `users.init_users(app)` s'en charge
# en fin de fichier, dans le bloc `if __name__ == '__main__'`. L'enregistrer
# une seconde fois lève `ValueError: The name 'users' is already registered`
# et empêche tout démarrage du serveur.
#
# Piège à connaître : ce bloc ne s'exécute pas lorsque `app` est importé comme
# module — dans un client de test, par exemple. Les règles `users.*` sont alors
# absentes, `url_for('users.login')` échoue, et la fiche médicament rend une
# erreur 500. C'est un artefact du contexte de test, pas le comportement du
# serveur : vérifier une hypothèse sur l'enregistrement des blueprints demande
# de lancer réellement l'application.
app.register_blueprint(prescription_bp)
app.register_blueprint(chatbot_bp)

# Vérification d'ordonnance : l'inverse de `prescription_bp`, qui va du
# symptôme vers le traitement. Celui-ci part d'une ordonnance écrite et se
# contente de croiser des faits, sans modèle de langage.
from ordonnance import ordonnance_bp  # noqa: E402
app.register_blueprint(ordonnance_bp)

# Register colleague's blueprints (adapted to our schema)
try:
    from blueprints.neo4j_graph import neo4j_graph_bp
    app.register_blueprint(neo4j_graph_bp)
except Exception as e:
    print(f"[WARNING] Neo4j graph blueprint: {e}")

try:
    from blueprints.database_viewer import db_viewer_bp
    app.register_blueprint(db_viewer_bp)
except Exception as e:
    print(f"[WARNING] Database viewer blueprint: {e}")

# Pass embedding_model to prescription_helper
import prescription_helper
prescription_helper.embedding_model = embedding_model

# Route for dashboard (new feature)
@app.route('/dashboard')
def dashboard():
    return render_template('dashboard.html')


#: Collections comptées sur la page « Infrastructure ». Les nommer plutôt que
#: de balayer `list_collection_names()` : la base en porte une trentaine, dont
#: des files de travail et des verrous de synchronisation qui n'apprennent rien
#: à un lecteur et changent au gré des traitements.
COLLECTIONS_MONTREES = ['medicines', 'medicines_en', 'medicines_ar',
                        'interactions', 'DRUGBANKS', 'dci_lookup',
                        'medicine_enrichment', 'translation_cache']

#: Un seul relevé par processus. Les agrégations balaient les 13 594 fiches ;
#: les refaire à chaque affichage referait le défaut du § 2.9 du rapport de
#: l'assistant, où une page rechargeait le catalogue entier à chaque appel.
_infrastructure = {}


def relever_infrastructure():
    """Compose le `db_status` que `databases.html` attend.

    Le gabarit lit trois blocs — `mongodb`, `qdrant`, `neo4j` — dont chacun
    porte au minimum `status` et `error`. Chaque base est relevée dans son
    propre `try` : une base éteinte doit donner une page qui le dit, pas une
    erreur 500 qui masque les deux autres.

    Les trois séries de graphiques (`collections`, `type_distribution`,
    `top_labs`) sont des dictionnaires nom → nombre : le script de la page les
    lit avec `Object.keys` et `Object.values`.
    """
    if _infrastructure:
        return _infrastructure

    releve = {
        'mongodb': {'status': 'disconnected', 'error': '', 'total_docs': 0,
                    'collections': {}, 'type_distribution': {}, 'top_labs': {}},
        'qdrant': {'status': 'disconnected', 'error': '', 'collections': []},
        'neo4j': {'status': 'disconnected', 'error': ''},
    }

    try:
        base = collection.database
        comptes = {}
        for nom in COLLECTIONS_MONTREES:
            try:
                comptes[nom] = base[nom].estimated_document_count()
            except Exception:
                continue
        releve['mongodb']['collections'] = {n: c for n, c in comptes.items() if c}
        releve['mongodb']['total_docs'] = sum(comptes.values())

        # `document_type` et `medicine_details.laboratoire` existent bien sur
        # les fiches — vérifié avant d'être interrogés. Une requête sur un
        # champ absent ne lève aucune erreur : elle rend zéro résultat
        # indéfiniment, et c'est ainsi que trois champs inexistants ont pu
        # être interrogés pendant des mois sans que rien ne le signale.
        releve['mongodb']['type_distribution'] = {
            (d['_id'] or 'non renseigné'): d['n']
            for d in collection.aggregate([
                {'$group': {'_id': '$document_type', 'n': {'$sum': 1}}},
                {'$sort': {'n': -1}}, {'$limit': 8}])}

        releve['mongodb']['top_labs'] = {
            (d['_id'] or 'non renseigné'): d['n']
            for d in collection.aggregate([
                {'$group': {'_id': '$medicine_details.laboratoire',
                            'n': {'$sum': 1}}},
                {'$sort': {'n': -1}}, {'$limit': 8}])}

        releve['mongodb']['status'] = 'connected'
    except Exception as err:
        releve['mongodb']['error'] = str(err)

    try:
        from qdrant_client import QdrantClient
        client = QdrantClient(host=app_config.QDRANT_HOST, port=app_config.QDRANT_PORT, timeout=5)
        cols = []
        for c in client.get_collections().collections:
            detail = client.get_collection(c.name)
            dimension = 0
            try:
                vecteurs = detail.config.params.vectors
                dimension = getattr(vecteurs, 'size', 0) or 0
            except Exception:
                pass
            cols.append({'name': c.name,
                         'points_count': detail.points_count or 0,
                         'dimension': dimension})
        releve['qdrant']['collections'] = cols
        releve['qdrant']['status'] = 'connected'
    except Exception as err:
        releve['qdrant']['error'] = str(err)

    try:
        if neo4j_connector and neo4j_connector.driver:
            with neo4j_connector.driver.session(
                    database=neo4j_connector.database) as session:
                session.run("RETURN 1").single()
            releve['neo4j']['status'] = 'connected'
        else:
            releve['neo4j']['error'] = 'connecteur non initialisé'
    except Exception as err:
        releve['neo4j']['error'] = str(err)

    _infrastructure.update(releve)
    return _infrastructure


@app.route('/databases')
def databases():
    """Page « Infrastructure des données ».

    Le gabarit existait depuis `3be1b87` sans qu'aucune route ne le rende ni
    qu'aucun menu n'y mène. Ses quatre appels de graphe (`/api/neo4j/stats`,
    `full-graph`, `substance-network`, `medicine-graph`) étaient bien servis
    par `neo4j_graph_bp` : seule la fonction de vue manquait, et avec elle le
    `db_status` que la page lit dès sa vingtième ligne.
    """
    return render_template('databases.html',
                           db_status=relever_infrastructure(),
                           active_page='databases')

# Context processor pour passer SOURCE_URLS au template
@app.context_processor
def inject_source_urls():
    return {
        'SOURCE_URLS': SOURCE_URLS,
        'get_source_info': get_source_info
    }


@app.context_processor
def inject_libelle():
    """
    Expose `libelle(en, fr)` aux gabarits.

    Remplace la forme `{{ 'X' if lang == 'en' else 'Y' }}`, qui ne connaissait
    que deux langues et rendait le français pour toute autre — la fiche
    restait donc à moitié en français en arabe, contenu traduit compris.
    """
    import ui_labels
    return {'libelle': ui_labels.libelle}

# Jinja2 filter for source info
@app.template_filter('source_info')
def source_info_filter(source_name):
    return get_source_info(source_name)

@app.route('/vector-search', methods=['GET', 'POST'])
def vector_search():
    """Recherche vectorielle sémantique via Qdrant avec pagination et affichage enrichi + recherche floue"""
    results = []
    query = request.args.get('query', '').strip()
    lang = langue_demandee()
    family_filter = request.args.get('family', '').strip()  # Filtre par famille thérapeutique
    type_med = request.args.get('type_med', '').strip()  # Filtre par type de médicament
    substance = request.args.get('substance', '').strip()
    forme = request.args.get('forme', '').strip()
    laboratoire = request.args.get('laboratoire', '').strip()
    dosage = request.args.get('dosage', '').strip()
    initial_count = 10
    load_more_count = 10
    total = 0
    


    # Utiliser le traducteur optimisé pour tous les résultats si EN (pour mini description et champs courts)
    from live_translator_google import translate_medicines_live_google


    if query:
        print(f"[SEARCH] Recherche pour: '{query}' (langue: {lang})")

        # 1. Recherche vectorielle Qdrant
        query_vector = embedding_model.encode(query).tolist()

        # Augmenter la limite pour avoir plus de résultats
        qdrant_results = qdrant_client.query_points(
            collection_name="medicines",
            query=query_vector,
            limit=500
        )

        print(f"[SEARCH] Qdrant a trouvé {len(qdrant_results.points)} résultats")

        min_score = 0.05
        results_with_details = []

        for res in qdrant_results.points:
            if not (hasattr(res, 'score') and res.score >= min_score):
                continue

            mongo_id = res.payload.get('mongo_id')
            med = None

            if mongo_id:
                try:
                    mongo_filter = {'_id': ObjectId(mongo_id)}
                    if family_filter:
                        mongo_filter['groupe_anatomique'] = family_filter
                    if type_med:
                        mongo_filter['type_medicament'] = type_med
                    if substance:
                        mongo_filter['medicine_details.substances_actives'] = {'$regex': substance, '$options': 'i'}
                    if forme:
                        mongo_filter['medicine_details.forme'] = {'$regex': forme, '$options': 'i'}
                    if laboratoire:
                        mongo_filter['medicine_details.laboratoire'] = {'$regex': laboratoire, '$options': 'i'}
                    if dosage:
                        mongo_filter['medicine_details.dosages'] = {'$regex': dosage, '$options': 'i'}

                    med = collection.find_one(mongo_filter)
                    if med and '_id' in med:
                        med['_id'] = str(med['_id'])
                except Exception as e:
                    print(f"[SEARCH] Erreur MongoDB: {e}")
                    pass

            vector_score = getattr(res, 'score', 0)
            if med:
                relevance_score = calculate_relevance_score(med, query)
                combined_score = (vector_score * 0.4) + (min(relevance_score / 100, 1.0) * 0.6)
            else:
                combined_score = vector_score

            results_with_details.append({
                'score': vector_score,
                'combined_score': combined_score,
                'title': res.payload.get('title', ''),
                'mongo_id': str(mongo_id) if mongo_id else '',
                'medicine': med
            })

        results_with_details.sort(key=lambda x: x.get('combined_score', 0), reverse=True)
        results = [r for r in results_with_details if r.get('combined_score', 0) >= 0.15]

        mongo_fuzzy_results = fuzzy_search_mongodb(query, limit=100)
        existing_ids = {r['mongo_id'] for r in results if r.get('mongo_id')}

        for fuzzy_med in mongo_fuzzy_results:
            med_id = str(fuzzy_med.get('_id', ''))
            if med_id not in existing_ids:
                fuzzy_score = fuzzy_search_in_text(query, fuzzy_med.get('title', ''))
                combined_score = fuzzy_score * 0.8

                if combined_score >= 0.15:
                    results.append({
                        'score': fuzzy_score,
                        'combined_score': combined_score,
                        'title': fuzzy_med.get('title', ''),
                        'mongo_id': med_id,
                        'medicine': fuzzy_med,
                        'source': 'mongodb_fuzzy'
                    })
                    print(f"[SEARCH] MongoDB fuzzy a ajouté: {fuzzy_med.get('title', 'Inconnu')} (score: {fuzzy_score:.3f})")

        results.sort(key=lambda x: x.get('combined_score', 0), reverse=True)
        total = len(results)
        print(f"[SEARCH] Total final: {total} résultats")




    # Get filter options
    available_filters = extract_filter_options()

    # Traduction dynamique des options de filtres si anglais.
    #
    # Deux defauts corriges ici, tous deux invisibles tant qu'on restait en
    # francais :
    #
    # 1. `translator.translate()` etait appele sans protection. Le service
    #    leve `TranslationNotFound` sur certains libelles — il l'a fait sur
    #    « Vitamine A synthetique - forme huileuse » — et l'exception
    #    remontait jusqu'au routeur : toute la page de recherche vectorielle
    #    repondait 500 a cause d'une seule entree de menu. On passe par
    #    `google_translate`, qui rend le texte d'origine en cas d'echec :
    #    une entree reste en francais, la page s'affiche.
    #
    # 2. `extract_filter_options()` met son resultat en cache et le rend
    #    **par reference**. Ecrire `available_filters['substances'] = ...`
    #    modifiait donc le cache partage : apres une seule visite en
    #    anglais, tous les visiteurs suivants — francais compris — voyaient
    #    des filtres anglais, jusqu'au redemarrage du serveur. Et la visite
    #    anglaise suivante retraduisait de l'anglais vers l'anglais. D'ou la
    #    copie : la traduction ne quitte pas la requete en cours.
    #
    # Seules deux des quatre listes sont traduites. Les laboratoires sont des
    # noms propres — SANOFI, PIERRE FABRE, pas plus traduisibles qu'un nom de
    # personne — et les dosages sont des valeurs chiffrees suivies d'une unite
    # internationale (« 500 mg »). Les faire passer par un traducteur
    # automatique ne peut que les abimer : le filtre porte sur une valeur
    # exacte de la base, et un libelle deforme ne correspondrait plus a rien.
    TRADUISIBLES = ('substances', 'formes')

    if lang == 'en':
        available_filters = dict(available_filters)

        def traduire_liste(valeurs):
            return [google_translate(str(x)) if x else x for x in valeurs]

        for cle in TRADUISIBLES:
            if cle in available_filters:
                available_filters[cle] = traduire_liste(available_filters[cle])

    return render_template(
        "vector_search.html",
        results=results,
        query=query,
        total=total,
        initial_count=initial_count,
        load_more_count=load_more_count,
        substance=substance,
        forme=forme,
        laboratoire=laboratoire,
        dosage=dosage,
        family=family_filter,
        type_med=type_med,
        available_filters=available_filters,
        lang=lang,
    )


# Important: Initialiser la base de données avant d'accéder à mongo.db
try:
    init_db(app)
    db = mongo.db
    collection = db['medicines'] if db is not None else None
    app.db = db
    # `medicines_en` n'avait que son index d'identifiant : la recherche par
    # `original_id`, faite à chaque affichage en anglais, balayait la collection.
    live_translator_google.ensure_indexes(db)
except Exception as e:
    print(f"[WARNING] ⚠️ Impossible d'initialiser MongoDB dans app.py: {e}")
    db = None
    collection = None
    app.db = None

# Sync Neo4j (après init MongoDB)
try:
    if neo4j_connector and neo4j_connector.driver and db is not None:
        # Le garde comptait les nœuds `Drug`, que plus rien n'alimente, alors
        # que la synchronisation écrit des `Medicine` : il mesurait autre chose
        # que ce qu'il déclenchait.
        with neo4j_connector.driver.session(database=neo4j_connector.database) as s:
            medicine_count = s.run("MATCH (m:Medicine) RETURN count(m) AS c").single()['c']
        if medicine_count < 10:
            print(f"[INFO] Neo4j contient {medicine_count} Medicine → sync de tous les médicaments...")
            neo4j_connector.sync_all_medicines(db)

        # Le garde des interactions comptait `INTERACTS_WITH` **globalement**,
        # et de façon non dirigée : il annonçait 1 383 914 relations pour les
        # 691 957 qui existaient, et concluait que le travail était fait.
        # Il ne compte plus que la couche substance, la seule en service.
        with neo4j_connector.driver.session(database=neo4j_connector.database) as s:
            rel_count = s.run("""
                MATCH (:DrugbankSubstance)-[r:INTERACTS_WITH]-(:DrugbankSubstance)
                RETURN count(r)/2 AS c
            """).single()['c']
        if rel_count < 100:
            # `sync_interactions()` n'est volontairement pas rappelée ici : elle
            # reconstruirait le modèle spécialité–spécialité que P9-3 remplace.
            print(f"[WARNING] Couche d'interactions absente ou incomplète "
                  f"({rel_count} relations). La reconstruire au niveau substance ; "
                  f"voir rapport/RAPPORT_P9-3_RECONSTRUCTION.md.")
        else:
            print(f"[INFO] Neo4j : {rel_count} interactions substance–substance en service")
except Exception as sync_err:
    print(f"[WARNING] Erreur sync Neo4j: {sync_err}")

# Service d'enrichissement DrugBank (0 requête DRUGBANKS au runtime)
enrichment_service = EnrichmentService()

# Fonction pour convertir les objets BSON en JSON serializable
def bson_to_json(data):
    """Convertit les objets BSON en dictionnaires JSON serialisables"""
    return json.loads(json_util.dumps(data))

# Fonction pour extraire le nom du médicament
def extract_medicine_name(medicine):
    """Extrait le nom du médicament."""
    # Utiliser le titre s'il est disponible (dans la nouvelle structure)
    if 'title' in medicine and medicine['title']:
        return medicine['title']
    
    # Chercher dans la section 1 (DÉNOMINATION DU MÉDICAMENT)
    if 'sections' in medicine and medicine['sections']:
        for section in medicine['sections']:
            if section['title'] == "1. DENOMINATION DU MEDICAMENT" and section.get('content'):
                for content in section['content']:
                    if 'text' in content:
                        return content['text']
    
    # Si aucun nom n'est trouvé, utiliser l'ID comme nom par défaut
    return f"Médicament {medicine['_id']}"

#: Le compte des substances distinctes est calculé une fois par processus.
#:
#: Il l'était à chaque affichage de la page d'accueil : un balayage des
#: 13 594 fiches pour normaliser les libellés, sur la page la plus vue du
#: site. Le catalogue ne bouge qu'aux imports, ce compte n'avait aucune
#: raison d'être refait à chaque visite — et il a fini par faire tomber la
#: route en mémoire.
_substances_normalisees = None


def compter_substances_normalisees():
    """Substances actives distinctes, libellés normalisés.

    « Paracétamol » et « paracétamol » désignent la même substance : sans ce
    repli, l'accueil et le tableau de bord annonceraient deux nombres
    différents pour la même chose.
    """
    global _substances_normalisees
    if _substances_normalisees is not None:
        return _substances_normalisees
    noms = set()
    try:
        for doc in collection.find(
                {'medicine_details.substances_actives': {'$exists': True}},
                {'medicine_details.substances_actives': 1}):
            for nom in (doc.get('medicine_details', {})
                        .get('substances_actives') or []):
                if nom:
                    noms.add(nom.strip().lower())
    except Exception as err:
        print(f"[ACCUEIL] Comptage des substances : {err}")
        return 0
    _substances_normalisees = len(noms)
    return _substances_normalisees


@app.route('/accueil-classique')
def accueil_classique():
    """L'ancienne page d'accueil, gardée jointe.

    Elle a servi `/` jusqu'ici. `accueil_essai()` a pris sa place, mais la
    supprimer d'un coup priverait de tout recours si quelque chose manquait à
    la nouvelle : elle reste donc atteignable, et le jour où plus rien ne la
    réclame, il n'y aura qu'une route et un gabarit à retirer.
    """
    # Utiliser la connexion MongoDB déjà établie au lieu de models.mongo.db
    
    # Obtenir des statistiques sur la base de données
    # Le compte des documents DRUGBANKS y était ajouté : la page la plus vue du
    # site annonçait **1 027 922 médicaments** pour 13 594 réels. Même défaut
    # que la carte de tête du tableau de bord, au même endroit du code.
    total_medicines = collection.count_documents({})

    lab_count = len(db.medicines.distinct("medicine_details.laboratoire"))
    substance_count = compter_substances_normalisees()
    
    # Récupérer les médicaments les plus récemment mis à jour pour la section "featured"
    featured_medicines = list(db.medicines.find({}, {"title": 1, "update_date": 1})
                           .sort("update_date", -1).limit(3))
    
    return render_template('index.html',
                          total_medicines=total_medicines,
                          lab_count=lab_count,
                          substance_count=substance_count,
                          featured_medicines=featured_medicines)

def extract_filter_options():
    """Extrait les options de filtre disponibles à partir de l'ensemble de la base de données"""
    # Vérifier si nous avons déjà extrait les options de filtrage
    cached_filters = getattr(extract_filter_options, 'cached_filters', None)
    if cached_filters:
        return cached_filters
    
    # Initialiser les ensembles pour stocker les valeurs uniques
    substances_actives = set()
    formes_pharma = set()
    laboratoires = set()
    dosages = set()
    
    # Analyser un échantillon représentatif de la base de données
    try:
        sample_size = 100
        medicines = list(collection.find().limit(sample_size))
        
        for medicine in medicines:
            # Extraction directement depuis medicine_details
            if 'medicine_details' in medicine:
                # Substances actives
                if 'substances_actives' in medicine['medicine_details'] and medicine['medicine_details']['substances_actives']:
                    for substance in medicine['medicine_details']['substances_actives']:
                        if substance and len(substance) > 2:  # Ignorer les valeurs trop courtes
                            substances_actives.add(substance)
                
                # Formes pharmaceutiques
                if 'forme' in medicine['medicine_details'] and medicine['medicine_details']['forme']:
                    forme = medicine['medicine_details']['forme']
                    if forme and len(forme) > 2:  # Ignorer les valeurs trop courtes
                        formes_pharma.add(forme)
                
                # Laboratoires
                if 'laboratoire' in medicine['medicine_details'] and medicine['medicine_details']['laboratoire']:
                    laboratoire = medicine['medicine_details']['laboratoire']
                    if laboratoire and len(laboratoire) > 2:
                        laboratoires.add(laboratoire)
                
                # Dosages
                if 'dosages' in medicine['medicine_details'] and medicine['medicine_details']['dosages']:
                    for dosage in medicine['medicine_details']['dosages']:
                        if dosage and len(str(dosage)) > 1:
                            dosages.add(dosage)
    except Exception as e:
        print(f"Erreur lors de l'extraction des filtres: {e}")
    
    # Convertir en listes triées
    result = {
        'substances': sorted(list(substances_actives)),
        'formes': sorted(list(formes_pharma)),
        'laboratoires': sorted(list(laboratoires)),
        'dosages': sorted(list(dosages)),
        'voies': voies_administration_disponibles()
    }

    # Cacher les résultats comme attribut de la fonction pour les prochains appels
    extract_filter_options.cached_filters = result
    return result


def voies_administration_disponibles():
    """Liste des voies d'administration atomiques présentes au catalogue.

    Les quatre autres listes de filtres viennent d'un échantillon de cent
    fiches — assez pour peupler un menu, trop peu pour être exhaustif. Ici on
    balaie le catalogue entier : l'agrégation ne parcourt que l'index
    `voies_administration` (147 clés) et rend la main en 40 ms, contre 92
    voies vues sur six mille fiches pour 64 réellement distinctes une fois les
    valeurs composées éclatées.
    """
    voies = set()
    try:
        groupes = collection.aggregate([
            {'$unwind': '$voies_administration'},
            {'$group': {'_id': '$voies_administration'}}
        ])
        for groupe in groupes:
            valeur = groupe.get('_id')
            if not valeur:
                continue
            for part in str(valeur).split(';'):
                part = part.strip()
                if part:
                    voies.add(part)
    except Exception as e:
        print(f"Erreur lors de l'extraction des voies d'administration: {e}")
    return sorted(voies)

def extract_filter_options_from_results(medicines):
    """Extrait les options de filtre disponibles uniquement à partir des résultats actuels"""
    # Initialiser les ensembles pour stocker les valeurs uniques
    substances_actives = set()
    formes_pharma = set()
    laboratoires = set()
    dosages = set()
    
    # Parcourir les résultats de recherche actuels
    for medicine in medicines:
        # Extraction depuis medicine_details
        if 'medicine_details' in medicine:
            # Substances actives
            if 'substances_actives' in medicine['medicine_details'] and medicine['medicine_details']['substances_actives']:
                for substance in medicine['medicine_details']['substances_actives']:
                    if substance and len(substance) > 2:  # Ignorer les valeurs trop courtes
                        substances_actives.add(substance)
            
            # Formes pharmaceutiques
            if 'forme' in medicine['medicine_details'] and medicine['medicine_details']['forme']:
                forme = medicine['medicine_details']['forme']
                if forme and len(forme) > 2:  # Ignorer les valeurs trop courtes
                    formes_pharma.add(forme)
            
            # Laboratoires
            if 'laboratoire' in medicine['medicine_details'] and medicine['medicine_details']['laboratoire']:
                laboratoire = medicine['medicine_details']['laboratoire']
                if laboratoire and len(laboratoire) > 2:
                    laboratoires.add(laboratoire)
            
            # Dosages
            if 'dosages' in medicine['medicine_details'] and medicine['medicine_details']['dosages']:
                for dosage in medicine['medicine_details']['dosages']:
                    if dosage and len(str(dosage)) > 1:
                        dosages.add(dosage)
    
    # Convertir en listes triées
    result = {
        'substances': sorted(list(substances_actives)),
        'formes': sorted(list(formes_pharma)),
        'laboratoires': sorted(list(laboratoires)),
        'dosages': sorted(list(dosages))
    }
    
    return result

@app.route('/search')
def search():
    # Récupérer les paramètres pour les passer au template
    search_query = request.args.get('search', '')
    page = int(request.args.get('page', 1))
    per_page = int(request.args.get('per_page', 10))
    substance = request.args.get('substance', '')
    forme = request.args.get('forme', '')
    laboratoire = request.args.get('laboratoire', '')
    dosage = request.args.get('dosage', '')
    family_filter = request.args.get('family', '')
    type_med = request.args.get('type_med', '')
    sort_option = request.args.get('sort', 'date_desc')
    voie = request.args.get('voie', '')
    commercialisation = request.args.get('commercialisation', '')
    surveillance = request.args.get('surveillance', '')
    advanced_search = (substance or forme or laboratoire or dosage or family_filter
                       or type_med or voie or commercialisation or surveillance
                       or sort_option != 'date_desc')

    # Get filter options
    available_filters = extract_filter_options()

    # Rendre le template sans les résultats
    return render_template('classic_search.html',
                          search=search_query,
                          substance=substance,
                          forme=forme,
                          laboratoire=laboratoire,
                          dosage=dosage,
                          family=family_filter,
                          type_med=type_med,
                          voie=voie,
                          commercialisation=commercialisation,
                          surveillance=surveillance,
                          sort=sort_option,
                          advanced_search=advanced_search,
                          current_page=page,
                          per_page=per_page,
                          available_filters=available_filters)

@lru_cache(maxsize=1024)
def convert_french_date_cached(date_str):
    """Version mise en cache de la conversion de date française"""
    if not date_str or not isinstance(date_str, str):
        return 0
    
    try:
        if '/' in date_str:
            day, month, year = map(int, date_str.split('/'))
            # Retourner une clé de tri au format AAAAMMJJ
            return year * 10000 + month * 100 + day
    except (ValueError, AttributeError):
        return 0
    return 0

def sort_medicines_by_date(medicines, sort_direction):
    """Trie les médicaments par date au format français (JJ/MM/AAAA)"""
    sort_start_time = time.time()
    
    def convert_french_date(medicine):
        # Vérifier si update_date existe dans le document
        if 'update_date' not in medicine:
            return 0
        
        # Utiliser la version mise en cache de la conversion
        return convert_french_date_cached(medicine['update_date'])
    
    # Utiliser la fonction de conversion pour trier
    sorted_medicines = sorted(
        medicines, 
        key=convert_french_date,
        reverse=(sort_direction == -1)  # True si sort_direction est -1 (descendant)
    )
    
    sort_duration = time.time() - sort_start_time
    print(f"TRI PAR DATE: {len(medicines)} documents triés en {sort_duration:.3f} secondes")
    
    return sorted_medicines

def fuzzy_similarity(str1, str2):
    """
    Calcule la similarité entre deux chaînes (0.0 à 1.0)
    Tolère les fautes d'orthographe
    """
    return SequenceMatcher(None, str1.lower(), str2.lower()).ratio()


def normalize_text(text):
    """
    Normalise le texte pour la recherche floue
    - Supprime les accents
    - Normalise les espaces
    - Supprime les caractères spéciaux
    """
    import unicodedata
    # Supprimer les accents
    text = ''.join(
        c for c in unicodedata.normalize('NFD', text)
        if unicodedata.category(c) != 'Mn'
    )
    # Tout en minuscule
    text = text.lower()
    # Remplacer les caractères spéciaux par des espaces
    text = re.sub(r'[^a-z0-9\s]', ' ', text)
    # Normaliser les espaces
    text = ' '.join(text.split())
    return text


def fuzzy_search_in_text(query, text, threshold=0.7):
    """
    Recherche floue d'une requête dans un texte
    Retourne le meilleur score de similarité trouvé
    
    Args:
        query: Terme recherché
        text: Texte où chercher
        threshold: Seuil minimum de similarité (0.0 à 1.0)
    
    Returns:
        Meilleur score trouvé (0.0 à 1.0)
    """
    if not query or not text:
        return 0.0
    
    query_normalized = normalize_text(query)
    text_normalized = normalize_text(text)
    
    # Recherche exacte d'abord
    if query_normalized in text_normalized:
        return 1.0
    
    # Recherche floue par mots
    text_words = text_normalized.split()
    query_words = query_normalized.split()
    
    best_score = 0.0
    
    # Comparer avec chaque mot du texte
    for text_word in text_words:
        for query_word in query_words:
            similarity = fuzzy_similarity(query_word, text_word)
            if similarity > best_score and similarity >= threshold:
                best_score = similarity
    
    # Recherche par n-grams (pour les mots composés)
    if best_score < threshold and len(query_words) > 1:
        # Essayer la requête complète
        for i in range(len(text_words) - len(query_words) + 1):
            text_ngram = ' '.join(text_words[i:i+len(query_words)])
            similarity = fuzzy_similarity(query_normalized, text_ngram)
            if similarity > best_score:
                best_score = similarity
    
    return best_score


def create_fuzzy_regex(query):
    """
    Crée un pattern regex flexible pour la recherche floue
    Exemple: "doliprane" -> "d.{0,2}o.{0,2}l.{0,2}i.{0,2}p.{0,2}r.{0,2}a.{0,2}n.{0,2}e"
    Permet des insertions/suppressions de caractères
    """
    # Normaliser la requête
    normalized = normalize_text(query)
    
    # Créer un pattern flexible: chaque caractère peut avoir 0-2 caractères entre
    pattern_parts = []
    for char in normalized:
        if char.isalnum():
            pattern_parts.append(f"{char}.{{0,2}}")
    
    pattern = ''.join(pattern_parts)
    return pattern


def fuzzy_search_mongodb(query, limit=100, search_collection=None):
    """
    Recherche floue dans MongoDB pour compenser les limites de Qdrant
    Utilise des regex flexibles pour trouver les médicaments malgré les fautes
    
    Args:
        query: Terme de recherche
        limit: Nombre maximum de résultats
        search_collection: Collection MongoDB à utiliser (par défaut: collection)
    
    Returns:
        Liste de documents MongoDB
    """
    if not query or len(query) < 3:
        return []
    
    # Utiliser la collection par défaut si non spécifiée
    if search_collection is None:
        search_collection = collection
    
    try:
        normalized_query = normalize_text(query)
        
        # Stratégie 1: Regex souple (permet quelques erreurs)
        # Ex: "doliprane" peut matcher "dolipranne", "dolipran", etc.
        fuzzy_pattern = create_fuzzy_regex(query)
        
        # Stratégie 2: Recherche par sous-chaînes
        # Découper la requête en parties et chercher chacune
        query_parts = normalized_query.split()
        
        # Construire la requête MongoDB
        conditions = []
        
        # Recherche avec pattern flexible
        if len(fuzzy_pattern) > 0:
            conditions.append({'title': {'$regex': fuzzy_pattern, '$options': 'i'}})
        
        # Recherche par parties de mots
        for part in query_parts:
            if len(part) >= 3:
                # Pattern flexible pour chaque partie
                part_pattern = '.*'.join(list(part))
                conditions.append({'title': {'$regex': part_pattern, '$options': 'i'}})
        
        # Recherche avec $text si disponible (full-text search)
        try:
            conditions.append({'$text': {'$search': query}})
        except:
            pass
        
        if not conditions:
            return []
        
        # Exécuter la requête avec OR
        mongo_query = {'$or': conditions}
        
        results = list(search_collection.find(mongo_query).limit(limit))
        
        # Filtrer et trier par similarité
        filtered_results = []
        for doc in results:
            title = doc.get('title', '')
            similarity = fuzzy_search_in_text(query, title, threshold=0.6)
            if similarity >= 0.6:
                doc['fuzzy_score'] = similarity
                filtered_results.append(doc)
        
        # Trier par score de similarité
        filtered_results.sort(key=lambda x: x.get('fuzzy_score', 0), reverse=True)
        
        return filtered_results
        
    except Exception as e:
        print(f"[ERROR] Erreur MongoDB fuzzy search: {e}")
        return []


def calculate_relevance_score(medicine, search_query):
    """
    Calcule un score de pertinence amélioré pour le classement des résultats.
    Utilise un système de pondération sophistiqué avec plusieurs facteurs.
    AMÉLIORATION: Inclut maintenant la recherche floue pour tolérer les fautes d'orthographe
    """
    score = 0
    search_terms = search_query.lower().split()
    total_matches = 0
    match_details = {
        'title_matches': 0,
        'substance_matches': 0,
        'section_matches': 0
    }
    
    # ===== POIDS DES DIFFÉRENTS FACTEURS (ajustables) =====
    WEIGHTS = {
        'title_exact': 100,           # Match exact du titre
        'title_contains': 50,         # Titre contient le terme
        'title_word_start': 40,       # Terme au début d'un mot du titre
        'title_fuzzy_high': 70,       # Match flou fort (>0.85)
        'title_fuzzy_medium': 45,     # Match flou moyen (>0.75)
        'title_fuzzy_low': 25,        # Match flou faible (>0.65)
        'substance_exact': 80,        # Match exact substance active
        'substance_contains': 35,     # Substance contient le terme
        'substance_fuzzy': 50,        # Match flou substance
        'forme_contains': 15,         # Forme pharmaceutique
        'dosage_contains': 12,        # Dosage
        'section_title': 10,          # Titre de section
        'section_content': 3,         # Contenu section
        'subsection_match': 5,        # Sous-section
    }
    
    # ===== 1. RECHERCHE DANS LE TITRE (très important) =====
    if 'title' in medicine:
        title = medicine['title'].lower()
        title_words = title.split()
        
        for term in search_terms:
            term_len = len(term)
            matched = False
            
            # Match exact du titre complet
            if title == term:
                score += WEIGHTS['title_exact']
                match_details['title_matches'] += 1
                total_matches += 1
                matched = True
            
            # Le terme est un mot complet du titre
            elif term in title_words:
                score += WEIGHTS['title_contains'] * 1.5
                match_details['title_matches'] += 1
                total_matches += 1
                matched = True
            
            # Titre commence par le terme
            elif title.startswith(term):
                score += WEIGHTS['title_contains'] * 1.2
                match_details['title_matches'] += 1
                total_matches += 1
                matched = True
            
            # Terme au début d'un mot du titre
            elif any(word.startswith(term) for word in title_words):
                score += WEIGHTS['title_word_start']
                match_details['title_matches'] += 1
                total_matches += 1
                matched = True
            
            # Le titre contient le terme
            elif term in title:
                count = title.count(term)
                score += WEIGHTS['title_contains'] * count * 0.8
                match_details['title_matches'] += count
                total_matches += count
                matched = True
            
            # NOUVEAU: Recherche floue si pas de match exact
            if not matched and len(term) >= 4:  # Seulement pour les termes >= 4 caractères
                fuzzy_score = fuzzy_search_in_text(term, medicine.get('title', ''), threshold=0.65)
                
                if fuzzy_score >= 0.85:
                    score += WEIGHTS['title_fuzzy_high']
                    match_details['title_matches'] += 1
                    total_matches += 1
                elif fuzzy_score >= 0.75:
                    score += WEIGHTS['title_fuzzy_medium']
                    match_details['title_matches'] += 1
                    total_matches += 1
                elif fuzzy_score >= 0.65:
                    score += WEIGHTS['title_fuzzy_low']
                    match_details['title_matches'] += 0.5
                    total_matches += 0.5
    
    # ===== 2. RECHERCHE DANS LES SUBSTANCES ACTIVES (très important) =====
    if 'medicine_details' in medicine and 'substances_actives' in medicine['medicine_details']:
        substances = medicine['medicine_details'].get('substances_actives', [])
        
        for substance in substances:
            if not substance:
                continue
            
            substance_lower = substance.lower()
            substance_words = substance_lower.split()
            
            for term in search_terms:
                # Match exact de la substance
                if substance_lower == term:
                    score += WEIGHTS['substance_exact']
                    match_details['substance_matches'] += 1
                    total_matches += 1
                
                # La substance est exactement un mot
                elif term in substance_words:
                    score += WEIGHTS['substance_contains'] * 1.3
                    match_details['substance_matches'] += 1
                    total_matches += 1
                
                # Substance commence par le terme
                elif substance_lower.startswith(term):
                    score += WEIGHTS['substance_contains'] * 1.1
                    match_details['substance_matches'] += 1
                    total_matches += 1
                
                # Substance contient le terme
                elif term in substance_lower:
                    count = substance_lower.count(term)
                    score += WEIGHTS['substance_contains'] * count
                    match_details['substance_matches'] += count
                    total_matches += count
    
    # ===== 3. RECHERCHE DANS LA FORME PHARMACEUTIQUE =====
    if 'medicine_details' in medicine:
        forme = medicine['medicine_details'].get('forme', '').lower()
        if forme:
            for term in search_terms:
                if term in forme:
                    count = forme.count(term)
                    score += WEIGHTS['forme_contains'] * count
                    total_matches += count
        
        # ===== 4. RECHERCHE DANS LES DOSAGES =====
        dosages = medicine['medicine_details'].get('dosages', [])
        for dosage in dosages:
            dosage_str = str(dosage).lower() if dosage else ""
            for term in search_terms:
                if term in dosage_str:
                    count = dosage_str.count(term)
                    score += WEIGHTS['dosage_contains'] * count
                    total_matches += count
        
        # ===== 5. RECHERCHE DANS LE LABORATOIRE =====
        laboratoire = medicine['medicine_details'].get('laboratoire', '').lower()
        if laboratoire:
            for term in search_terms:
                if term in laboratoire:
                    score += WEIGHTS['substance_contains'] * 0.6
                    total_matches += 1
    
    # ===== 6. RECHERCHE DANS LES SECTIONS =====
    if 'sections' in medicine:
        for section in medicine['sections']:
            section_title = section.get('title', '').lower()
            
            # Sections importantes pour la recherche
            important_keywords = [
                'denomination', 'composition', 'proprietes', 'indications',
                'posologie', 'contre-indication', 'effet', 'interaction'
            ]
            is_important_section = any(kw in section_title for kw in important_keywords)
            
            # Recherche dans le titre de la section
            for term in search_terms:
                if term in section_title:
                    weight = WEIGHTS['section_title'] * (2 if is_important_section else 1)
                    score += weight
                    match_details['section_matches'] += 1
                    total_matches += 1
            
            # Recherche dans le contenu de la section
            content_items = section.get('content', [])
            for content_item in content_items:
                if isinstance(content_item, dict):
                    text = content_item.get('text', '').lower()
                elif isinstance(content_item, str):
                    text = content_item.lower()
                else:
                    continue
                
                for term in search_terms:
                    if term in text:
                        count = text.count(term)
                        weight = WEIGHTS['section_content'] * (1.5 if is_important_section else 1)
                        score += weight * count
                        match_details['section_matches'] += count
                        total_matches += count
            
            # Recherche dans les sous-sections
            subsections = section.get('subsections', [])
            for subsection in subsections:
                subsection_title = subsection.get('title', '').lower()
                
                for term in search_terms:
                    if term in subsection_title:
                        weight = WEIGHTS['subsection_match'] * (1.5 if is_important_section else 1)
                        score += weight
                        match_details['section_matches'] += 1
                        total_matches += 1
                
                # Contenu sous-section
                sub_content = subsection.get('content', [])
                for content_item in sub_content:
                    if isinstance(content_item, dict):
                        text = content_item.get('text', '').lower()
                    else:
                        text = str(content_item).lower()
                    
                    for term in search_terms:
                        if term in text:
                            count = text.count(term)
                            score += WEIGHTS['subsection_match'] * count * 0.8
                            match_details['section_matches'] += count
                            total_matches += count
    
    # ===== 7. BONUS MULTIPLICATEUR =====
    # Si plusieurs termes correspondent, appliquer un bonus
    matching_terms = set()
    title = medicine.get('title', '').lower()
    substances = str(medicine.get('medicine_details', {}).get('substances_actives', [])).lower()
    all_text = title + ' ' + substances
    
    for term in search_terms:
        if term in all_text:
            matching_terms.add(term)
    
    # Bonus pour plusieurs termes trouvés
    if len(matching_terms) > 1:
        bonus_multiplier = 1 + (len(matching_terms) - 1) * 0.1
        score *= bonus_multiplier
    
    # ===== 8. PÉNALITÉ POUR FAIBLE PERTINENCE =====
    # Si très peu de correspondances, réduire le score
    if total_matches == 0:
        score = 0
    elif total_matches == 1 and score < 5:
        score *= 0.5
    
    # Stocker les informations de correspondance
    medicine['match_count'] = total_matches
    medicine['match_details'] = match_details
    medicine['relevance_score'] = score
    
    return score
def find_search_term_locations(medicine, search_query):
    """Identifie les endroits où les termes de recherche ont été trouvés dans un médicament, sans doublons visuels."""
    if not search_query:
        return []

    matches_dict = {}
    search_terms = search_query.lower().split()

    def add_match(location, text, term, count, priority):
        key = (location, term)
        if key in matches_dict:
            matches_dict[key]['count'] += count
            # On ne remplace pas l'extrait, on garde le premier
        else:
            matches_dict[key] = {
                'location': location,
                'text': text,  # Premier extrait rencontré
                'term': term,
                'count': count,
                'priority': priority
            }

    # Vérifier dans le titre
    if 'title' in medicine:
        title_lower = medicine['title'].lower()
        for term in search_terms:
            if term in title_lower:
                term_count = title_lower.count(term)
                add_match('Titre', medicine['title'], term, term_count, 1)

    # Vérifier dans les détails du médicament
    if 'medicine_details' in medicine:
        # Chercher dans substances_actives
        if 'substances_actives' in medicine['medicine_details'] and medicine['medicine_details']['substances_actives']:
            for substance in medicine['medicine_details']['substances_actives']:
                substance_lower = substance.lower() if substance else ""
                for term in search_terms:
                    if term in substance_lower:
                        term_count = substance_lower.count(term)
                        add_match('Substance active', substance, term, term_count, 2)

        # Chercher dans laboratoire
        if 'laboratoire' in medicine['medicine_details'] and medicine['medicine_details']['laboratoire']:
            lab_lower = medicine['medicine_details']['laboratoire'].lower()
            for term in search_terms:
                if term in lab_lower:
                    term_count = lab_lower.count(term)
                    add_match('Laboratoire', medicine['medicine_details']['laboratoire'], term, term_count, 3)

        # Chercher dans forme
        if 'forme' in medicine['medicine_details'] and medicine['medicine_details']['forme']:
            forme_lower = medicine['medicine_details']['forme'].lower()
            for term in search_terms:
                if term in forme_lower:
                    term_count = forme_lower.count(term)
                    add_match('Forme pharmaceutique', medicine['medicine_details']['forme'], term, term_count, 3)

        # Chercher dans dosages
        if 'dosages' in medicine['medicine_details'] and medicine['medicine_details']['dosages']:
            for dosage in medicine['medicine_details']['dosages']:
                dosage_str = str(dosage).lower() if dosage else ""
                for term in search_terms:
                    if term in dosage_str:
                        term_count = dosage_str.count(term)
                        add_match('Dosage', str(dosage), term, term_count, 3)

    # Chercher dans le contenu des sections
    if 'sections' in medicine:
        for section in medicine['sections']:
            section_title = section.get('title', '')

            # Vérifier d'abord dans le titre de la section
            section_title_lower = section_title.lower()
            for term in search_terms:
                if term in section_title_lower:
                    term_count = section_title_lower.count(term)
                    add_match(f"Section: {section_title}", section_title, term, term_count, 3)

            # Chercher dans le contenu de la section
            if 'content' in section and section['content']:
                for content_item in section['content']:
                    if 'text' in content_item and content_item['text']:
                        text_lower = content_item['text'].lower()
                        for term in search_terms:
                            if term in text_lower:
                                term_count = text_lower.count(term)
                                excerpt = extract_excerpt(content_item['text'], term)
                                add_match(section_title, excerpt, term, term_count, 4)

            # Chercher dans le contenu des sous-sections
            if 'subsections' in section and section['subsections']:
                for subsection in section['subsections']:
                    subsection_title = subsection.get('title', '')

                    # Vérifier dans le titre de la sous-section
                    subsection_title_lower = subsection_title.lower()
                    for term in search_terms:
                        if term in subsection_title_lower:
                            term_count = subsection_title_lower.count(term)
                            add_match(f"{section_title} > {subsection_title}", subsection_title, term, term_count, 3)

                    if 'content' in subsection and subsection['content']:
                        for content_item in subsection['content']:
                            if 'text' in content_item and content_item['text']:
                                text_lower = content_item['text'].lower()
                                for term in search_terms:
                                    if term in text_lower:
                                        term_count = text_lower.count(term)
                                        excerpt = extract_excerpt(content_item['text'], term)
                                        add_match(f"{section_title} > {subsection_title}", excerpt, term, term_count, 4)

    # Retourner la liste des matches uniques (par location et terme)
    return list(matches_dict.values())


def extract_excerpt(text, term):
    """Extrait un court extrait du texte autour du terme recherché."""
    term_lower = term.lower()
    text_lower = text.lower()
    
    # Trouver la position du terme dans le texte
    pos = text_lower.find(term_lower)
    if pos == -1:
        return text[:100] + "..."  # Retourner le début du texte si terme non trouvé
    
    # Trouver le début and la fin de la phrase contenant le terme
    sentence_start = max(0, text_lower.rfind('.', 0, pos))
    if sentence_start == 0:
        # Si pas de point trouvé, essayer d'autres délimiteurs
        sentence_start = max(0, text_lower.rfind('!', 0, pos))
        sentence_start = max(0, text_lower.rfind('?', 0, pos))
    
    sentence_end = text_lower.find('.', pos)
    if sentence_end == -1:
        # Si pas de point trouvé, chercher d'autres délimiteurs ou prendre la fin du texte
        sentence_end = text_lower.find('!', pos)
        if sentence_end == -1:
            sentence_end = text_lower.find('?', pos)
            if sentence_end == -1:
                sentence_end = len(text)
    else:
        sentence_end += 1  # Inclure le point final
    
    # Si la phrase est trop longue, créer un extrait plus court autour du terme
    if sentence_end - sentence_start > 150:
        # Calculer les positions de début and de fin pour l'extrait
        start_pos = max(0, pos - 60)
        end_pos = min(len(text), pos + len(term) + 60)
    else:
        start_pos = sentence_start
        end_pos = sentence_end
    
    # Créer l'extrait
    excerpt = ""
    if start_pos > 0:
        excerpt += "..."
    excerpt += text[start_pos:end_pos]
    if end_pos < len(text):
        excerpt += "..."
    
    return excerpt

#: Index des titres réduits à leur forme d'adresse, par collection.
#:
#: La route accepte trois formes d'identifiant : l'identifiant Mongo, le titre
#: exact, et le titre réduit à sa forme d'adresse, du type
#: `bisacodyl-arrow-conseil-5-mg`. La troisième était résolue par
#: `list(collection.find())`, qui chargeait les 13 594 fiches **entières** en
#: mémoire, soit 1,13 Go, pour n'en comparer que le titre. Un identifiant
#: inconnu demandait ainsi de 56 à 70 secondes avant de rendre 404, et faisait
#: peser sur la base la charge qui l'avait déjà arrêtée une fois.
#:
#: L'index ne retient que le titre, se construit une fois par processus, et
#: rend la recherche immédiate.
_index_adresses = {}


def _forme_adresse(titre):
    """Réduit un titre à la forme employée dans les adresses."""
    return re.sub(r'[^a-zA-Z0-9]+', '-', (titre or '').lower()).strip('-')


def fiche_par_adresse(collection_mongo, adresse):
    """Retrouve une fiche par la forme d'adresse de son titre.

    L'index est bâti avec une projection sur le seul titre : c'est la
    différence entre lire quelques centaines de kilo-octets et la collection
    entière.
    """
    if not adresse:
        return None
    nom = collection_mongo.name
    if nom not in _index_adresses:
        table = {}
        try:
            for doc in collection_mongo.find({}, {'title': 1}):
                cle = _forme_adresse(doc.get('title'))
                if cle and cle not in table:
                    table[cle] = doc['_id']
        except Exception as err:
            print(f"[FICHE] Index des adresses ({nom}) : {err}")
            return None
        _index_adresses[nom] = table
        print(f"[FICHE] Index des adresses ({nom}) : {len(table)} titres")

    identifiant = _index_adresses[nom].get(adresse)
    return collection_mongo.find_one({'_id': identifiant}) if identifiant else None


@app.route('/medicine/<id>')
def medicine_details(id):
    """Route pour les détails d'un médicament spécifique"""
    try:
        # Détecter la langue
        lang = langue_demandee()
        
        medicine = None
        
        # Si la langue demandée n'est pas le français, chercher d'abord dans la
        # collection traduite correspondante : `medicines_en`, `medicines_ar`…
        if lang and lang != 'fr' and db is not None:
            traduites = db[live_translator_google.collection_traduite(lang)]
            try:
                medicine = traduites.find_one({'_id': ObjectId(id)})
            except Exception as e:
                medicine = None
            # Si pas trouvé, essayer par title exact
            if not medicine:
                medicine = traduites.find_one({'title': id})
            # Si pas trouvé, essayer par slug (pour les URLs type /medicine/bisacodyl-arrow-conseil-5-mg)
            if not medicine:
                medicine = fiche_par_adresse(traduites, id)
            if medicine:
                print(f"[TRADUCTION] fiche {lang} servie directement : {id}")
        
        # Si pas trouvé en anglais ou langue française, chercher dans medicines (français)
        if not medicine:
            from bson.errors import InvalidId
            # Essayer comme ObjectId
            try:
                medicine = collection.find_one({'_id': ObjectId(id)})
            except (InvalidId, Exception):
                medicine = None
            # Si pas trouvé, essayer par title exact
            if not medicine:
                medicine = collection.find_one({'title': id})
            # Si pas trouvé, essayer par slug (pour les URLs type /medicine/bisacodyl-arrow-conseil-5-mg)
            if not medicine:
                medicine = fiche_par_adresse(collection, id)
            if not medicine:
                abort(404)
            # Fiche française trouvée mais langue étrangère demandée : chercher
            # la version traduite, la produire si elle manque.
            if lang and lang != 'fr' and db is not None:
                try:
                    # La fraîcheur est vérifiée : une traduction dont la notice
                    # a changé depuis n'est pas servie. Même discipline que pour
                    # le résumé IA (P0), et pour la même raison — sans elle, une
                    # version périmée est servie indéfiniment.
                    translated_medicine = live_translator_google.stored_translation(db, medicine, lang)
                    if translated_medicine:
                        medicine = translated_medicine
                        print(f"[TRADUCTION] version {lang} conservee servie (notice inchangee)")
                    else:
                        # Traduction à la volée, puis conservation : le premier
                        # visiteur dans cette langue paie l'attente, pas les suivants.
                        try:
                            source = medicine
                            translated_list = translate_medicines_live_google([medicine], lang)
                            if translated_list and len(translated_list) > 0:
                                medicine = translated_list[0]
                                live_translator_google.store_translation(db, source, medicine, lang)
                        except Exception as e:
                            print(f"[TRADUCTION] echec de la traduction a la volee : {e}")
                except Exception as e:
                    print(f"[TRANSLATION] Erreur recherche version traduite: {e}")

        
        # Ajouter le nom extrait comme attribut du médicament
        medicine['name'] = extract_medicine_name(medicine)
        
        # Enrichissement DrugBank (pré-calculé dans medicine_enrichment, 0 requête DRUGBANKS)
        enrichment_service.enrich_medicine(medicine)
        
        # Check if we already have a summary, but don't wait for generation
        # This allows the page to load quickly
        existing_summary = None
        if db is not None:
            try:
                # La projection doit inclure la traduction de la langue
                # demandée, sinon une version arabe déjà conservée resterait
                # invisible et serait retraduite à chaque visite.
                projection_resume = {"ai_summary": 1, "ai_summary_en": 1}
                if lang and lang != 'fr':
                    projection_resume["ai_summary_%s" % lang] = 1
                stored_medicine = db.medicines.find_one(
                    {"_id": ObjectId(id)}, projection_resume
                )
                if stored_medicine and 'ai_summary' in stored_medicine:
                    existing_summary = stored_medicine['ai_summary']

                    # Le résumé est rédigé en français : le traduire vers la
                    # langue demandée, quelle qu'elle soit.
                    if lang and lang != 'fr' and existing_summary and medicine.get('language') != lang:
                        # Une traduction déjà conservée dans la fiche prime.
                        deja = stored_medicine.get('ai_summary_%s' % lang)
                        if deja:
                            existing_summary = deja
                        else:
                            # Passe par le traducteur groupé : il découpe les
                            # résumés dépassant la limite du service, ce qu'un
                            # appel direct tronquait silencieusement.
                            try:
                                moteur = live_translator_google.GoogleLiveTranslator(lang)
                                existing_summary = moteur.translate_text(existing_summary)
                            except Exception as e:
                                print(f"[TRADUCTION] echec sur le resume IA : {e}")
            except Exception as e:
                print(f"Error checking for cached summary: {e}")
        
        # Set the summary if it exists, otherwise it will be loaded via AJAX
        medicine['ai_summary'] = existing_summary
        
        # Vérifier si le médicament est un favori pour l'utilisateur connecté
        is_favorite = False
        comments = []
        user_role = None
        
        # Si l'utilisateur est connecté, récupérer ses interactions.
        # Le rôle vient de `g.user`, donc de la base : il décide ici quels
        # commentaires sont visibles, et se lisait auparavant dans un cookie
        # que le lecteur pouvait fabriquer lui-même.
        if g.get('user'):
            from models import Interaction, Comment
            user_id = str(g.user['_id'])
            is_favorite = Interaction.is_favorite(user_id, str(medicine['_id']))
            try:
                user_role = int(g.user.get('role'))
            except (TypeError, ValueError):
                user_role = None

            # Récupérer les commentaires pour ce médicament visibles par l'utilisateur
            comments = Comment.get_for_medicine(str(medicine['_id']), user_role)
        else:
            # Même pour les utilisateurs non connectés, récupérer les commentaires publics
            from models import Comment
            comments = Comment.get_for_medicine(str(medicine['_id']))
        
        # Ajouter les informations utilisateur à chaque commentaire, que l'utilisateur soit connecté ou non
        for comment in comments:
            try:
                comment_user = User.get_by_id(comment['user_id'])
                if comment_user:
                    comment['user'] = {
                        'first_name': comment_user.get('first_name', 'Utilisateur'),
                        'last_name': comment_user.get('last_name', '')
                    }
            except Exception as e:
                print(f"Erreur lors de la récupération des données utilisateur: {e}")
                # Si on ne peut pas récupérer l'utilisateur, on met un placeholder
                comment['user'] = {
                    'first_name': 'Utilisateur',
                    'last_name': ''
                }
        
        # S'assurer que chaque élément de contenu a un champ html_content
        if 'sections' in medicine:
            for section in medicine['sections']:
                if 'content' in section:
                    for content_item in section['content']:
                        # Traiter le texte normal
                        if 'text' in content_item and 'html_content' not in content_item:
                            # Créer un contenu HTML basique si manquant
                            text = content_item['text']
                            # Convertir les sauts de ligne en <br>
                            html_text = text.replace('\n', '<br>')
                            # Garder le texte simple en HTML mais avec les sauts de ligne
                            content_item['html_content'] = f"<p>{html_text}</p>"
                        
                        # S'assurer que les tableaux sont correctement formatés
                        if 'table' in content_item and isinstance(content_item['table'], list):
                            # Le tableau est déjà bien formaté, pas besoin de le modifier
                            pass
                
                # Traiter également les sous-sections
                if 'subsections' in section:
                    for subsection in section['subsections']:
                        if 'content' in subsection:
                            for content_item in subsection['content']:
                                # Traiter le texte normal
                                if 'text' in content_item and 'html_content' not in content_item:
                                    text = content_item['text']
                                    html_text = text.replace('\n', '<br>')
                                    content_item['html_content'] = f"<p>{html_text}</p>"
                                
                                # S'assurer que les tableaux sont correctement formatés
                                if 'table' in content_item and isinstance(content_item['table'], list):
                                    # Le tableau est déjà bien formaté, pas besoin de le modifier
                                    pass
        
        # `medicine_json` a été retiré : une sérialisation indentée de la fiche
        # entière — 183 Ko en moyenne, jusqu'à plusieurs mégaoctets — était
        # calculée à chaque consultation pour un gabarit qui ne la lit nulle
        # part. L'« affichage brut » qu'annonçait le commentaire n'existe pas
        # dans medicine_details.html.
        # Détection du statut de prescription depuis le texte de la notice
        prescription_status = None
        try:
            import re as _re
            status_keywords = {
                'stupéfiant': 'Stupéfiants',
                'stup\u00e9fiant': 'Stupéfiants',
                'liste i': 'Liste I',
                'liste ii': 'Liste II',
            }
            full_text = ''
            for section in (medicine.get('sections') or []):
                for item in (section.get('content') or []):
                    full_text += ' ' + (item.get('text') or '')
                for sub in (section.get('subsections') or []):
                    for item in (sub.get('content') or []):
                        full_text += ' ' + (item.get('text') or '')
            lower_text = full_text.lower()
            for keyword, label in status_keywords.items():
                if keyword in lower_text:
                    prescription_status = label
                    break
            # Retour de vente / rétrocession
            if not prescription_status and any(k in lower_text for k in ['rétrocession', 'collectivités']):
                prescription_status = 'Collectivités / rétrocession'
        except Exception:
            prescription_status = None
        medicine['prescription_status'] = prescription_status

        # Un résumé désaligné de la notice n'est pas affiché : le gabarit bascule
        # alors sur le bloc d'attente, qui déclenche sa régénération via l'API.
        if medicine.get('ai_summary') and not summary_is_fresh(medicine, medicine.get('content_hash')):
            medicine.pop('ai_summary', None)

        # Une fiche servie depuis `medicines_en` n'a pas les attributs du
        # catalogue : on les lit dans la collection française plutôt que d'en
        # entretenir une copie qui divergerait.
        regulatory.merge_catalogue(medicine, collection)

        # `lang` est calculé en tête de route mais n'était pas transmis : toutes
        # les alternatives « ... if lang == 'en' else ... » du gabarit tombaient
        # sur la branche française, l'anglais restant inatteignable sur la fiche.
        # Le sommaire n'offrait aucune entrée vers les contre-indications, que
        # le RCP enfouit en 4.3 sous « DONNÉES CLINIQUES », alors qu'il en
        # proposait une vers « Données techniques ». Le drapeau est calculé ici
        # plutôt que dans le gabarit : Jinja n'a pas de quoi chercher dans les
        # sous-sections sans se contorsionner.
        a_contre_indications = any(
            'contre-indication' in (sub.get('title') or '').lower()
            or 'contre indication' in (sub.get('title') or '').lower()
            for section in (medicine.get('sections') or [])
            for sub in (section.get('subsections') or [])
        )

        retirer_notice_dupliquee(medicine)

        # Les contre-indications sont extraites pour être présentées avant la
        # monographie, et non plus seulement enfouies en 4.3. Le bloc de
        # « synthèse médicale » qui devait les porter n'a jamais rien affiché :
        # `synthesis.contre_indications` est absent des 13 594 fiches. La
        # rubrique 4.3, elle, existe sur 99 % d'entre elles.
        from ordonnance import (contre_indications_de,  # noqa: E402
                                rang_section_contre_indications)
        contre_indications = contre_indications_de(medicine)
        rang_ci = rang_section_contre_indications(medicine)

        # Structures moléculaires, portées par la substance et non par la
        # spécialité : il y a 13 594 spécialités pour 1 633 substances, et les
        # cinq dosages d'ACTISKENAN afficheraient sinon cinq fois la même
        # molécule de morphine (§12 du plan P9).
        structures = []
        if neo4j_connector and neo4j_connector.driver and medicine.get('url'):
            try:
                with neo4j_connector.driver.session(
                        database=neo4j_connector.database) as session:
                    structures = [dict(r) for r in session.run("""
                        MATCH (:Medicine {url: $url})-[:HAS_DRUGBANK_SUBSTANCE]->(s)
                        WHERE s.formule IS NOT NULL OR s.smiles IS NOT NULL
                        RETURN s.name AS nom, s.formule AS formule, s.masse AS masse,
                               s.smiles AS smiles, s.inchikey AS inchikey,
                               s.svg AS svg
                        ORDER BY s.name
                    """, url=medicine['url'])]
            except Exception as struct_err:
                print(f"[STRUCTURE] {struct_err}")

        # Pharmacogenomique : deux recherches indexees, jamais un calcul. La
        # section reste absente quand la specialite n'atteint aucune molecule
        # PharmGKB — voir `pharmacogenomique.profil` pour les trois absences.
        try:
            pgx = pharmacogenomique.profil(medicine, db)
        except Exception as pgx_err:
            print(f"[PGx] {pgx_err}")
            pgx = None

        return render_template('medicine_details.html',
                               medicine=medicine,
                               is_favorite=is_favorite,
                               comments=comments,
                               lang=lang,
                               a_contre_indications=a_contre_indications,
                               contre_indications=contre_indications,
                               rang_ci=rang_ci,
                               structures=structures,
                               pgx=pgx,
                               safety_flags=regulatory.safety_flags(medicine, lang),
                               regulatory_facts=regulatory.regulatory_facts(medicine, lang))
    
    except Exception as e:
        print(f"Erreur dans medicine_details: {e}")
        abort(404)

@app.route('/structure/<cle>.svg')
def structure_svg(cle):
    """Sert une formule topologique comme image, plutôt qu'inline dans la fiche.

    Le SVG pèse 25 Ko en moyenne et ne change jamais : une molécule a une
    structure, et l'InChIKey en est le condensat. Inline, il repartait à chaque
    consultation, y compris pour les cinq dosages d'ACTISKENAN qui montrent la
    même morphine. Servi ici, le navigateur le garde.

    La clé est l'InChIKey quand elle existe, le nom de la substance sinon —
    toutes les substances n'en portent pas. Le SVG part en `image/svg+xml`
    dans une balise `<img>`, contexte où un navigateur n'exécute ni script ni
    lien externe : c'est plus sûr que le `|safe` qu'imposait l'inline.
    """
    if not (neo4j_connector and neo4j_connector.driver):
        abort(404)
    try:
        with neo4j_connector.driver.session(
                database=neo4j_connector.database) as session:
            ligne = session.run("""
                MATCH (s:DrugbankSubstance)
                WHERE (s.inchikey = $cle OR s.name = $cle) AND s.svg IS NOT NULL
                RETURN s.svg AS svg
                LIMIT 1
            """, cle=cle).single()
    except Exception as err:
        print(f"[STRUCTURE SVG] {err}")
        abort(503)
    if not ligne:
        abort(404)

    reponse = Response(ligne['svg'], mimetype='image/svg+xml')
    # Immuable : la clé identifie la molécule, donc le dessin. Un changement de
    # rendu passerait par une nouvelle clé, pas par une invalidation.
    reponse.headers['Cache-Control'] = 'public, max-age=31536000, immutable'
    return reponse


#: Nombre d'interactions renvoyées au plus. Un médicament très connecté en
#: compte plus d'un millier ; la fiche en devient illisible et la réponse
#: pèse plusieurs mégaoctets. `total_count` dit toujours la vérité.
INTERACTIONS_DISPLAY_LIMIT = 100


def _interactions_analysis_state(session, url):
    """Dit pourquoi un médicament n'a aucune interaction à afficher.

    « Aucune interaction connue » et « nous n'avons pas la donnée » ne disent
    pas la même chose à un prescripteur. Cette fonction produit la seconde
    information, que l'interface confondait jusqu'ici avec la première.

    - `not_matched` : aucune substance DrugBank rattachée, rien n'a pu être
      cherché pour ce médicament ;
    - `none`        : ses substances sont connues et n'ont aucune interaction
      recensée ;
    - `not_loaded`  : cas résiduel, la couche substance n'a pas été construite.
    """
    rattache = session.run("""
        MATCH (m:Medicine {url: $url})-[:HAS_DRUGBANK_SUBSTANCE]->(s)
        RETURN count(s) AS n
    """, url=url).single()['n']
    if not rattache:
        return 'not_matched'
    return 'none'


@app.route('/api/medicine-interactions/<medicine_id>')
def get_medicine_interactions(medicine_id):
    """Interactions d'un médicament, avec l'état de l'analyse.

    Une interaction est un fait entre deux molécules, pas entre deux boîtes :
    la route la restitue donc au niveau de la substance. L'ancienne version
    listait des spécialités, ce qui affichait la même interaction autant de
    fois qu'il existe de présentations de la molécule concernée — 1 432 lignes
    pour un dropéridol, toutes redondantes.

    `status` vaut :
      - `ok`          : des interactions sont connues, elles sont listées ;
      - `none`        : les substances du médicament sont connues et n'ont
                        aucune interaction recensée ;
      - `not_matched` : aucune substance DrugBank rattachée, rien n'a pu être
                        cherché ;
      - `not_loaded`  : le graphe est indisponible ou incomplet.

    Les trois derniers cas doivent se lire différemment à l'écran : seul
    `none` est une information ; les autres sont des lacunes.
    """
    try:
        if collection is None:
            return jsonify({'success': False, 'status': 'not_loaded',
                            'interactions': [], 'total_count': 0}), 503

        try:
            medicine = collection.find_one({'_id': ObjectId(medicine_id)},
                                           {'url': 1, 'title': 1})
        except (InvalidId, TypeError):
            return jsonify({'success': False, 'error': 'Identifiant invalide'}), 400
        if not medicine:
            return jsonify({'success': False, 'error': 'Not found'}), 404

        url = medicine.get('url')
        if not neo4j_connector or not neo4j_connector.driver or not url:
            return jsonify({'success': True, 'status': 'not_loaded',
                            'interactions': [], 'total_count': 0,
                            'displayed_count': 0, 'substances': []})

        with neo4j_connector.driver.session(
                database=neo4j_connector.database) as session:
            substances = [r['name'] for r in session.run("""
                MATCH (:Medicine {url: $url})-[:HAS_DRUGBANK_SUBSTANCE]->(s)
                RETURN s.name AS name ORDER BY s.name
            """, url=url)]
            total_count = session.run("""
                MATCH (:Medicine {url: $url})-[:HAS_DRUGBANK_SUBSTANCE]->()
                      -[r:INTERACTS_WITH]-(s2:DrugbankSubstance)
                RETURN count(DISTINCT s2) AS n
            """, url=url).single()['n']

            if not total_count:
                return jsonify({'success': True,
                                'status': _interactions_analysis_state(session, url),
                                'interactions': [], 'total_count': 0,
                                'displayed_count': 0, 'substances': substances})

            # `medicine_count` : combien de spécialités françaises portent la
            # substance en regard. C'est ce chiffre qui rend l'information
            # actionnable, sans recopier l'interaction sur chaque boîte.
            rows = list(session.run("""
                MATCH (:Medicine {url: $url})-[:HAS_DRUGBANK_SUBSTANCE]->(s1)
                      -[r:INTERACTS_WITH]-(s2:DrugbankSubstance)
                OPTIONAL MATCH (m2:Medicine)-[:HAS_DRUGBANK_SUBSTANCE]->(s2)
                WITH s1, s2, r, count(DISTINCT m2) AS medicine_count
                RETURN s1.name AS from_substance, s2.name AS substance,
                       r.description AS description, medicine_count
                ORDER BY medicine_count DESC, s2.name
                LIMIT $limit
            """, url=url, limit=INTERACTIONS_DISPLAY_LIMIT))

        # `r.severity` n'est pas renvoyé, et n'est plus écrit : la source
        # DrugBank ne porte aucun niveau de gravité (cf. rapport P9-1).
        # Afficher une gradation de risque sans source serait plus trompeur
        # que de n'en afficher aucune.
        # Les énoncés DrugBank sont en anglais. Ils sont traduits ici par
        # substitution dans des phrases françaises écrites d'avance — jamais
        # par une traduction automatique, qui toucherait aux noms de
        # substance (cf. interaction_i18n). Ce qui n'est pas reconnu reste en
        # anglais : `description_fr` vaut alors `None`, et l'interface le dit.
        result = []
        non_traduits = 0
        for r in rows:
            en = r['description'] or ''
            fr = interaction_i18n.traduire(en)
            if not fr:
                non_traduits += 1
            result.append({
                'from_substance': r['from_substance'],
                'substance': r['substance'],
                'description': en,
                'description_fr': fr,
                'medicine_count': r['medicine_count'],
            })

        return jsonify({
            'success': True,
            'status': 'ok',
            'substances': substances,
            'interactions': result,
            'total_count': total_count,
            'displayed_count': len(result),
            # Ce que l'interface doit annoncer : « tout est traduit »,
            # « rien ne l'est », ou « une partie l'est ». Le compte exact
            # permet de ne pas afficher un avertissement sur l'anglais quand
            # aucun énoncé n'est resté en anglais.
            'description_lang': ('en' if non_traduits == len(result)
                                 else 'fr' if non_traduits == 0 else 'mixte'),
            'untranslated_count': non_traduits,
        })
    except Exception as e:
        print(f"Erreur lors de la récupération des interactions: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/medicine-alternatives/<medicine_id>')
def get_medicine_alternatives(medicine_id):
    """Retourne les médicaments alternatifs (même substance ATC ou même principe actif)"""
    try:
        medicine = collection.find_one({'_id': ObjectId(medicine_id)})
        if not medicine:
            return jsonify({'success': False, 'error': 'Not found'}), 404

        substances = (medicine.get('medicine_details', {}) or {}).get('substances_actives', [])
        title = medicine.get('title', '')
        alternatives = []
        seen_titles = {title}

        # 1) MongoDB : médicaments avec mêmes substances actives
        if substances:
            for sub in substances:
                if sub:
                    same_sub = list(collection.find({
                        'medicine_details.substances_actives': sub,
                        'title': {'$ne': title}
                    }, {
                        'title': 1, '_id': 1,
                        'medicine_details.forme': 1,
                        'medicine_details.laboratoire': 1,
                        'medicine_details.dosages': 1,
                        'medicine_details.substances_actives': 1,
                    }).limit(6))
                    for m in same_sub:
                        t = m.get('title', '')
                        if t not in seen_titles:
                            seen_titles.add(t)
                            details = m.get('medicine_details', {}) or {}
                            alternatives.append({
                                'id': str(m['_id']),
                                'title': t,
                                'forme': details.get('forme', ''),
                                'laboratoire': details.get('laboratoire', ''),
                                'substances': (details.get('substances_actives', []) or [])[:2],
                                'source': 'Même substance active'
                            })

        # 2) Neo4j : même ingrédient actif
        if neo4j_connector and neo4j_connector.driver and substances:
            with neo4j_connector.driver.session(database=neo4j_connector.database) as session:
                for sub in substances[:2]:
                    if sub:
                        # `CONTAINS` a été migrée de `Drug` vers `Medicine` :
                        # le laboratoire vient désormais de la relation
                        # MANUFACTURED_BY, et la forme du champ `forme`.
                        result = session.run("""
                            MATCH (i:ActiveIngredient {name: $name})<-[:CONTAINS]-(m:Medicine)
                            WHERE m.url IS NOT NULL
                            OPTIONAL MATCH (m)-[:MANUFACTURED_BY]->(l:Laboratory)
                            RETURN m.title AS title, m.forme AS form,
                                   l.name AS lab, m.url AS url
                            ORDER BY m.title LIMIT 8
                        """, {'name': sub})
                        for alt in result:
                            t = alt['title'] or ''
                            if t and t not in seen_titles:
                                seen_titles.add(t)
                                alternatives.append({
                                    'title': t,
                                    'forme': alt['form'] or '',
                                    'laboratoire': alt['lab'] or '',
                                    'source': 'Neo4j Knowledge Graph'
                                })

        return jsonify({'success': True, 'alternatives': alternatives[:12]})
    except Exception as e:
        print(f"Erreur alternatives: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/neo4j-test-query')
def neo4j_test_query():
    """Test si les données exemples sont trouvables par le fallback"""
    if not neo4j_connector or not neo4j_connector.driver:
        return jsonify({'error': 'Neo4j not connected'})
    try:
        driver = neo4j_connector.driver
        db_name = neo4j_connector.database
        results = {}
        with driver.session(database=db_name) as session:
            for term in ['DOLIPRANE', 'Paracetamol', 'Paracétamol']:
                rows = list(session.run("""
                    MATCH (m:Medicine)
                    WHERE toLower(coalesce(m.title, '')) CONTAINS toLower($term)
                    RETURN m.url AS id, m.title AS display
                    LIMIT 5
                """, {'term': term}))
                results[term] = [{'id': r['id'], 'display': r['display']} for r in rows]
            # Count total drugs and interactions
            total_drugs = session.run("MATCH (m:Medicine) RETURN count(m) AS c").single()['c']
            total_inter = session.run(
                "MATCH (:DrugbankSubstance)-[r:INTERACTS_WITH]-(:DrugbankSubstance) "
                "RETURN count(r)/2 AS c").single()['c']
            total_effects = session.run("MATCH ()-[r:CAUSES]->() RETURN count(r) AS c").single()['c']
        return jsonify({
            'database': db_name,
            'total_drugs': total_drugs,
            'total_interactions': total_inter,
            'total_causes': total_effects,
            'search_results': results
        })
    except Exception as e:
        return jsonify({'error': str(e)})


@app.route('/api/neo4j-load-sample')
def neo4j_load_sample():
    """Charge sample_data.cypher dans Neo4j (medicament)"""
    if not neo4j_connector or not neo4j_connector.driver:
        return jsonify({'success': False, 'error': 'Neo4j non connecté'})
    try:
        cypher_path = os.path.join(os.path.dirname(__file__), '..', 'neo4j_kg', 'cypher', 'sample_data.cypher')
        with open(cypher_path, 'r', encoding='utf-8') as f:
            content = f.read()
        # Découper en statements individuels (séparés par ;)
        statements = [s.strip() for s in content.replace('\n', ' ').split(';') if s.strip()]
        with neo4j_connector.driver.session(database=neo4j_connector.database) as session:
            executed = 0
            for stmt in statements:
                if stmt.upper().startswith('MERGE') or stmt.upper().startswith('MATCH'):
                    try:
                        session.run(stmt)
                        executed += 1
                    except Exception as stmt_err:
                        print(f"[NEO4J] Stmt error: {stmt_err}")
        return jsonify({'success': True, 'statements_executed': executed, 'message': 'Sample data loaded! Refresh the graph page.'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/neo4j-debug')
def neo4j_debug():
    """Diagnostic : voir ce qu'il y a dans Neo4j"""
    info = {'connected': False, 'error': '', 'counts': {}}
    if not neo4j_connector or not neo4j_connector.driver:
        info['error'] = 'Neo4j non connecté'
        return jsonify(info)
    try:
        # Essayer la database configurée, puis la default
        dbs_to_try = [neo4j_connector.database, 'neo4j']
        info['connected'] = True
        info['dbs_tried'] = []
        for db_name in dbs_to_try:
            try:
                with neo4j_connector.driver.session(database=db_name) as s:
                    s.run("RETURN 1").single()
                    info['dbs_tried'].append(f"{db_name} ✅")
                    info['database'] = db_name
                    break
            except Exception:
                info['dbs_tried'].append(f"{db_name} ❌")
        if not info.get('database'):
            info['error'] = 'Aucune database accessible'
            return jsonify(info)

        with neo4j_connector.driver.session(database=info['database']) as s:
            for label in ['Drug', 'ActiveIngredient', 'AdverseEvent', 'Effect', 'ATC']:
                r = s.run(f"MATCH (n:{label}) RETURN count(n) AS c").single()
                info['counts'][label] = r['c'] if r else 0
            r = s.run("MATCH ()-[r:INTERACTS_WITH]-() RETURN count(r) AS c").single()
            info['counts']['INTERACTS_WITH'] = r['c'] if r else 0
            r = s.run("MATCH ()-[r:CAUSES]-() RETURN count(r) AS c").single()
            info['counts']['CAUSES'] = r['c'] if r else 0
            # Échantillon de Drug nodes
            sample = s.run("MATCH (m:Medicine) RETURN m.url AS id, coalesce(m.title, '?') AS name LIMIT 10").data()
            info['sample_drugs'] = [{'id': x['id'], 'name': x['name']} for x in sample]
            # Échantillon d'interactions
            inter_samples = s.run("""
                MATCH (s1:DrugbankSubstance)-[r:INTERACTS_WITH]-(s2:DrugbankSubstance)
                RETURN s1.name AS a, s2.name AS b, null AS sev LIMIT 5
            """).data()
            info['sample_interactions'] = [f"{x['a']} <-> {x['b']} ({x.get('sev','?')})" for x in inter_samples]
    except Exception as e:
        info['error'] = str(e)
    return jsonify(info)


@app.route('/api/medicine-graph/<medicine_id>')
def get_medicine_graph(medicine_id):
    """Route pour récupérer les données du Knowledge Graph Neo4j"""
    try:
        medicine = collection.find_one({'_id': ObjectId(medicine_id)})
        if not medicine:
            return jsonify({'success': False, 'error': 'Médicament non trouvé'}), 404

        nodes = []
        edges = []
        seen = set()

        medicine_url = medicine.get('url', '')
        title = medicine.get('title', '')
        substances = (medicine.get('medicine_details', {}) or {}).get('substances_actives', [])

        def add_node(nid, label, group, title_extra=''):
            if nid not in seen:
                seen.add(nid)
                nodes.append({'id': nid, 'label': label, 'group': group, 'title': title_extra or label})

        # Central drug node
        drug_id = f"drug-{medicine_id}"
        add_node(drug_id, title[:30], 'current', title)

        # ── Ingredients (toujours, depuis MongoDB) ──
        for sub in substances:
            if sub:
                ing_id = f"ing-{sub[:20]}"
                add_node(ing_id, sub[:25], 'ingredient')
                edges.append({'from': drug_id, 'to': ing_id, 'label': 'CONTAINS', 'color': '#6366f1'})

                # Alternatives MongoDB (même substance)
                same_sub = list(collection.find({
                    'medicine_details.substances_actives': sub,
                    '_id': {'$ne': ObjectId(medicine_id)}
                }, {'title': 1}).limit(5))
                for alt in same_sub:
                    alt_title = alt.get('title', '')
                    if alt_title:
                        alt_id = f"alt-{alt_title[:30].replace(' ', '_')}"
                        add_node(alt_id, alt_title[:30], 'alternative')
                        edges.append({'from': drug_id, 'to': alt_id, 'label': 'SAME_ING', 'color': '#22c55e', 'dashes': True})

        # ── Compléter avec Neo4j (Knowledge Graph) ──
        if neo4j_connector and neo4j_connector.driver:
            driver = neo4j_connector.driver
            db_name = neo4j_connector.database

            # Sync ce médicament dans Neo4j (crée/MERGE Medicine + Drug)
            try:
                neo4j_connector.sync_medicine_from_mongo(medicine)
            except Exception as sync_err:
                print(f"[GRAPH] Sync error: {sync_err}")

            known_url = medicine_url if medicine_url else None
            with driver.session(database=db_name) as session:
                # ── 1. Interactions, au niveau de la substance ──
                #
                # Elles ne pendent plus à la spécialité : une interaction est
                # un fait entre deux molécules (cf. rapport P9-3). Le graphe
                # montre donc la substance du médicament, puis les substances
                # avec lesquelles elle interagit — ce qui est aussi bien plus
                # lisible qu'une liste de boîtes.
                #
                # Aucune couleur de gravité : la source n'en porte aucune, et
                # un code couleur de risque sans source trompe le lecteur.
                if known_url:
                    try:
                        rows = session.run("""
                            MATCH (:Medicine {url: $url})-[:HAS_DRUGBANK_SUBSTANCE]->(s1)
                                  -[:INTERACTS_WITH]-(s2:DrugbankSubstance)
                            OPTIONAL MATCH (m2:Medicine)-[:HAS_DRUGBANK_SUBSTANCE]->(s2)
                            WITH s1, s2, count(DISTINCT m2) AS nb
                            RETURN s1.name AS from_name, s2.name AS other_name, nb
                            ORDER BY nb DESC, s2.name
                            LIMIT 25
                        """, {'url': known_url})
                        for row in rows:
                            other = (row['other_name'] or '').strip()
                            if not other:
                                continue
                            src = (row['from_name'] or '').strip()
                            sid = f"sub-{hash(src) & 0x7FFFFFFF}"
                            add_node(sid, src[:30], 'ingredient', src)
                            edges.append({'from': drug_id, 'to': sid,
                                          'label': 'SUBSTANCE', 'color': '#6366f1'})
                            oid = f"sub-int-{hash(other) & 0x7FFFFFFF}"
                            nb = row['nb'] or 0
                            add_node(oid, other[:30], 'interaction',
                                     f"{other} — {nb} médicament(s) concerné(s)")
                            edges.append({'from': sid, 'to': oid,
                                          'label': 'interagit', 'color': '#6b7280',
                                          'title': other})
                    except Exception as med_err:
                        print(f"[GRAPH] Substance interaction query error: {med_err}")

                # ── 2. Laboratoire et principes actifs ──
                #
                # Les nœuds `Drug` ne sont plus interrogés : ils ne portaient
                # aucune interaction, et les relations `CAUSES` vers les effets
                # indésirables n'existent pas dans ce graphe — la rubrique en
                # cherchait sous deux libellés, sans jamais rien trouver.
                # `CONTAINS` a été migrée de `Drug` vers `Medicine`, qui porte
                # désormais tout ce dont l'affichage a besoin.
                if known_url:
                    try:
                        for row in session.run("""
                            MATCH (:Medicine {url: $url})-[:MANUFACTURED_BY]->(l:Laboratory)
                            RETURN l.name AS name LIMIT 3
                        """, {'url': known_url}):
                            lab = (row['name'] or '').strip()
                            if lab:
                                lid = f"lab-{hash(lab) & 0x7FFFFFFF}"
                                add_node(lid, lab[:30], 'laboratory', lab)
                                edges.append({'from': drug_id, 'to': lid,
                                              'label': 'LABORATOIRE', 'color': '#0ea5e9'})

                        for row in session.run("""
                            MATCH (:Medicine {url: $url})-[:CONTAINS]->(i:ActiveIngredient)
                            RETURN i.name AS name ORDER BY i.name LIMIT 10
                        """, {'url': known_url}):
                            ing = (row['name'] or '').strip()
                            if ing:
                                iid = f"ai-{hash(ing) & 0x7FFFFFFF}"
                                add_node(iid, ing[:30], 'ingredient', ing)
                                edges.append({'from': drug_id, 'to': iid,
                                              'label': 'CONTIENT', 'color': '#6366f1'})
                    except Exception as graph_err:
                        print(f"[GRAPH] Medicine graph query error: {graph_err}")

        return jsonify({'success': True, 'graph': {'nodes': nodes, 'edges': edges}})
    except Exception as e:
        print(f"Erreur graphe Neo4j: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/raw/<id>')
def raw_medicine(id):
    """Route pour voir les données brutes d'un médicament en JSON"""
    try:
        medicine = collection.find_one({'_id': ObjectId(id)})
        if not medicine:
            abort(404)
        return jsonify(json.loads(json_util.dumps(medicine)))
    except:
        abort(404)

@app.route('/debug')
def debug_info():
    """Page de debug pour afficher la structure de la base de données"""
    collection_stats = db.command("collStats", "medicines")
    sample_doc = collection.find_one()
    sample_json = json_util.dumps(sample_doc, indent=2)
    
    # Liste des champs présents dans les documents
    fields = set()
    for doc in collection.find().limit(100):
        fields.update(doc.keys())
    
    # Get filter options
    available_filters = extract_filter_options()
    
    return render_template('debug.html', 
                          stats=collection_stats,
                          sample=sample_json,
                          fields=sorted(list(fields)),
                          available_filters=available_filters)

@app.route('/api/quick-search')
def quick_search_api():
    """Autocomplete rapide pour la palette de commande (Cmd+K)"""
    q = request.args.get('q', '').strip()
    if not q or len(q) < 2:
        return jsonify({'results': []})
    
    try:
        lang = langue_demandee()
        search_coll = db['medicines_en'] if (lang == 'en' and db is not None and 'medicines_en' in db.list_collection_names()) else collection
        
        if search_coll is None:
            return jsonify({'results': []})
            
        regex = {'$regex': re.escape(q), '$options': 'i'}
        cursor = search_coll.find(
            {'$or': [{'title': regex}, {'medicine_details.substances_actives': regex}]},
            {'title': 1, 'medicine_details.substances_actives': 1, 'medicine_details.forme': 1, 'type_medicament': 1}
        ).limit(6)
        
        results = []
        for doc in cursor:
            substances = doc.get('medicine_details', {}).get('substances_actives', [])
            sub_str = ', '.join(substances[:2]) if isinstance(substances, list) else str(substances)
            results.append({
                'id': str(doc['_id']),
                'title': doc.get('title', 'Médicament'),
                'substances': sub_str,
                'forme': doc.get('medicine_details', {}).get('forme', ''),
                'type': doc.get('type_medicament', '')
            })
        return jsonify({'results': results})
    except Exception as e:
        return jsonify({'results': [], 'error': str(e)})


@app.route('/api/search-results')
def search_results_api():
    try:
        search_query = request.args.get('search', '')
        page = int(request.args.get('page', 1))
        per_page = int(request.args.get('per_page', 10))
        substance = request.args.get('substance', '')
        forme = request.args.get('forme', '')
        laboratoire = request.args.get('laboratoire', '')
        dosage = request.args.get('dosage', '')
        family_filter = request.args.get('family', '')  # Filtre par famille thérapeutique
        type_med = request.args.get('type_med', '')  # Filtre par type de médicament (groupe anatomique)
        sort_option = request.args.get('sort', 'date_desc')
        lang = langue_demandee()  # Détecter la langue

        # Sélectionner la collection en fonction de la langue
        search_collection = db['medicines_en'] if lang == 'en' else collection

        query = {}
        pipeline_filters = []

        # Construction de la requête de recherche
        #
        # La recherche passait par une expression régulière sur `title`, les
        # substances **et le texte intégral des RCP**. Sur 2,55 Go sans index,
        # elle prenait de 3,9 s à 28,7 s selon le terme.
        #
        # Elle cherchait aussi la mauvaise chose : « warfarine » figure dans la
        # rubrique Interactions de milliers de notices, d'où 3 708 résultats
        # annoncés dont **deux** contenaient réellement de la warfarine.
        # Chercher une molécule renvoyait les médicaments qui en parlent autant
        # que ceux qui en contiennent.
        #
        # L'index de texte porte sur le titre et les substances — sur ce que le
        # médicament est, non sur ce que sa notice mentionne. Le plein texte
        # reste en repli lorsque l'index ne rend rien, pour ne pas fermer la
        # porte aux recherches par symptôme ou par excipient.
        if search_query:
            search_regex = {'$regex': search_query, '$options': 'i'}
            repli_plein_texte = {'$or': [
                {'title': search_regex},
                {'medicine_details.substances_actives': search_regex},
                {'sections.content.text': search_regex},
                {'sections.subsections.content.text': search_regex},
                {'sections.subsections.subsections.content.text': search_regex}
            ]}
            try:
                # Ordonnés par le score de l'index, qui pondère déjà le titre
                # au double des substances. Cet ordre sert de classement.
                ids = [d['_id'] for d in search_collection.find(
                    {'$text': {'$search': search_query}},
                    {'_id': 1, 'score': {'$meta': 'textScore'}}
                ).sort([('score', {'$meta': 'textScore'})])]
            except Exception as err:
                # Index absent sur cette collection : on retombe sans casser.
                print(f"[SEARCH] index de texte indisponible: {err}")
                ids = None
            if ids:
                pipeline_filters.append({'_id': {'$in': ids}})
            else:
                pipeline_filters.append(repli_plein_texte)
        if substance:
            pipeline_filters.append({'medicine_details.substances_actives': {'$regex': substance, '$options': 'i'}})
        if forme:
            pipeline_filters.append({'medicine_details.forme': {'$regex': forme, '$options': 'i'}})
        if laboratoire:
            pipeline_filters.append({'medicine_details.laboratoire': {'$regex': laboratoire, '$options': 'i'}})
        if dosage:
            pipeline_filters.append({'medicine_details.dosages': {'$regex': dosage, '$options': 'i'}})
        if family_filter:
            pipeline_filters.append({'groupe_anatomique': family_filter})
        if type_med:
            pipeline_filters.append({'type_medicament': type_med})

        # Trois axes déjà normalisés en base, qu'aucun filtre n'exposait :
        # 11 940 fiches portent une voie d'administration (92 valeurs) et un
        # statut de commercialisation, 13 488 un indicateur de surveillance
        # renforcée. Un praticien qui cherche une forme injectable, ou qui veut
        # écarter ce qui n'est plus distribué, n'avait aucun moyen de le dire.
        voie = request.args.get('voie', '')
        commercialisation = request.args.get('commercialisation', '')
        surveillance = request.args.get('surveillance', '')
        if voie:
            # Le champ est un tableau, mais ses éléments sont eux-mêmes des
            # listes jointes par des points-virgules : une seule fiche porte
            # « endosinusale;intraarticulaire;intralésionnelle;… ». Une égalité
            # stricte manquerait ces 113 valeurs composées. On cherche donc la
            # voie comme jeton délimité, jamais comme sous-chaîne — sans quoi
            # « intraveineuse » attraperait aussi « intraveineuse stricte ».
            jeton = re.escape(voie)
            pipeline_filters.append(
                {'voies_administration': {'$regex': f'(^|;){jeton}($|;)'}})
        if commercialisation:
            pipeline_filters.append({'commercialisation': commercialisation})
        if surveillance:
            pipeline_filters.append({'surveillance_renforcee': surveillance})

        # Combiner les filtres avec $and
        if pipeline_filters:
            query['$and'] = pipeline_filters

        # Calculer le nombre de documents correspondant à la requête
        total_results = search_collection.count_documents(query)

        # Gestion du tri
        if sort_option == 'relevance' and search_query:
            # Le classement suit l'ordre rendu par l'index de texte.
            #
            # La version précédente chargeait **tous** les documents
            # correspondants — 220 pour « paracétamol », 183 Ko pièce, soit
            # 44 Mo — puis calculait pour chacun un score en Python parcourant
            # le texte intégral des sections. Coût mesuré : 64 ms par document,
            # 14 s pour la seule mise en ordre. L'index avait accéléré la
            # sélection, ce calcul annulait le gain.
            #
            # L'index pondère déjà le titre au double des substances, ce qui
            # est précisément le critère du score détaillé. Celui-ci reste
            # calculé, mais seulement pour les résultats de la page affichée,
            # où il sert à l'affichage et non au tri.
            if ids:
                debut = (page - 1) * per_page
                page_ids = ids[debut:debut + per_page]
                par_id = {d['_id']: d for d in search_collection.find(
                    {'_id': {'$in': page_ids}})}
                medicines = [par_id[i] for i in page_ids if i in par_id]
            else:
                all_medicines = list(search_collection.find(query))
                for medicine in all_medicines:
                    medicine['relevance_score'] = calculate_relevance_score(medicine, search_query)
                all_medicines.sort(key=lambda x: x.get('relevance_score', 0), reverse=True)
                medicines = all_medicines[(page - 1) * per_page:page * per_page]
        elif sort_option.startswith('name'):
            # Tri par nom
            sort_field = 'title'
            sort_direction = 1 if sort_option == 'name_asc' else -1
            medicines = list(search_collection.find(query).sort([(sort_field, sort_direction)]).skip((page - 1) * per_page).limit(per_page))
        else:
            # Tri par date (par défaut)
            sort_direction = -1 if sort_option == 'date_desc' else 1
            medicines = list(search_collection.find(query).skip((page - 1) * per_page).limit(per_page))
            medicines = sort_medicines_by_date(medicines, sort_direction)

        # TRADUCTION LIVE: Désactivée si on utilise déjà medicines_en
        if lang == 'en' and medicines and search_collection == collection:
            # Seulement si on a cherché dans 'medicines' (collection française)
            medicines = translate_medicines_live(medicines, lang)

        # Préparer les résultats formatés
        formatted_results = []
        for medicine in medicines:
            # Calculer le score de pertinence si la recherche est effectuée
            if search_query:
                relevance_score = calculate_relevance_score(medicine, search_query)
                medicine['search_matches'] = find_search_term_locations(medicine, search_query)
            else:
                relevance_score = 0
                medicine['search_matches'] = []
            formatted_results.append({
                'id': str(medicine['_id']) if '_id' in medicine else medicine.get('original_id', ''),
                'title': medicine['title'] if 'title' in medicine else medicine.get('denomination', ''),
                'update_date': medicine.get('update_date', 'Non disponible'),
                'medicine_details': medicine.get('medicine_details', {}),
                'relevance_score': relevance_score,  # Inclure le score de pertinence
                'match_count': medicine.get('match_count', 0),
                'search_matches': medicine['search_matches'],
                # Un seul signal, le plus grave : dans une liste, un empilement
                # de pastilles coûterait en lisibilité ce qu'il apporterait.
                'availability': regulatory.availability_badge(medicine, lang),
            })

        # Calculer s'il y a plus de résultats
        has_more = (page * per_page) < total_results

        return jsonify({
            'results': formatted_results,
            'has_more': has_more,
            'total_results': total_results,
            'total_pages': (total_results + per_page - 1) // per_page
        })
    except Exception as e:
        import traceback
        print("[API ERROR /api/search-results]", e)
        traceback.print_exc()
        return jsonify({'error': str(e), 'traceback': traceback.format_exc()}), 500

@app.route('/api/therapeutic-families')
def get_therapeutic_families():
    """Récupère la liste des groupes anatomiques (ATC) disponibles"""
    try:
        # Agréger les groupes anatomiques avec leur nombre de médicaments
        pipeline = [
            {'$match': {'groupe_anatomique': {'$exists': True, '$ne': None}}},
            {'$group': {
                '_id': '$groupe_anatomique',
                'count': {'$sum': 1}
            }},
            {'$sort': {'count': -1}}
        ]
        
        families = list(collection.aggregate(pipeline))
        
        # Formater les résultats
        result = [
            {
                'name': family['_id'],
                'count': family['count']
            }
            for family in families
        ]
        
        return jsonify({
            'success': True,
            'families': result,
            'total': len(result)
        })
        
    except Exception as e:
        print(f"Erreur récupération familles thérapeutiques: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/medicine-types')
def get_medicine_types():
    """Récupère la structure hiérarchique des types de médicaments"""
    try:
        return jsonify({
            'success': True,
            'categories': MEDICINE_CATEGORIES
        })
    except Exception as e:
        print(f"Erreur récupération types de médicaments: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/search-results-stream')
def search_results_api_stream():
    search_query = request.args.get('search', '')
    page = int(request.args.get('page', 1))
    per_page = int(request.args.get('per_page', 10))
    substance = request.args.get('substance', '')
    forme = request.args.get('forme', '')
    laboratoire = request.args.get('laboratoire', '')
    dosage = request.args.get('dosage', '')
    sort_option = request.args.get('sort', 'date_desc')

    query = {}
    pipeline_filters = []

    # Construction de la requête de recherche
    if search_query:
        search_regex = {'$regex': search_query, '$options': 'i'}
        pipeline_filters.append({'$or': [
            {'title': search_regex},
            {'medicine_details.substances_actives': search_regex},
            {'sections.content.text': search_regex},  # Recherche dans les sections
            {'sections.subsections.content.text': search_regex},
            {'sections.subsections.subsections.content.text': search_regex}
        ]})
    if substance:
        pipeline_filters.append({'medicine_details.substances_actives': {'$regex': substance, '$options': 'i'}})
    if forme:
        pipeline_filters.append({'medicine_details.forme': {'$regex': forme, '$options': 'i'}})
    if laboratoire:
        pipeline_filters.append({'medicine_details.laboratoire': {'$regex': laboratoire, '$options': 'i'}})
    if dosage:
        pipeline_filters.append({'medicine_details.dosages': {'$regex': dosage, '$options': 'i'}})

    # Combiner les filtres avec $and
    if pipeline_filters:
        query['$and'] = pipeline_filters

    def generate():
        total_results = collection.count_documents(query) # Calculer le nombre total de résultats
        
        # Envoyer le nombre total de résultats
        total_update = json.dumps({'total': total_results})
        yield f"event: total\ndata: {total_update}\n\n"

        medicines = collection.find(query).skip((page - 1) * per_page).limit(per_page) # Charger les résultats par page
        
        result_count = 0
        for medicine in medicines:
            if search_query:
                relevance_score = calculate_relevance_score(medicine, search_query)
                medicine['search_matches'] = find_search_term_locations(medicine, search_query)
            else:
                relevance_score = 0
                medicine['search_matches'] = []
            
            formatted_result = {
                'id': str(medicine['_id']),
                'title': medicine['title'],
                'update_date': medicine.get('update_date', 'Non disponible'),
                'medicine_details': medicine.get('medicine_details', {}),
                'relevance_score': relevance_score,
                'match_count': medicine.get('match_count', 0),
                'search_matches': medicine['search_matches']
            }
            
            # Convertir le résultat en JSON
            json_result = json.dumps(formatted_result, ensure_ascii=False)
            
            # Envoyer le résultat via le flux d'événements
            yield f"data: {json_result}\n\n"
            
            result_count += 1
            
            # Envoyer la mise à jour du compteur
            count_update = json.dumps({'count': result_count})
            yield f"event: count\ndata: {count_update}\n\n"

        # Envoyer un événement de fin de flux
        yield "data: end\n\n"

    return Response(stream_with_context(generate()), mimetype='text/event-stream')

# Ajout de la page d'erreur 404
@app.errorhandler(404)
def page_not_found(e):
    return render_template('errors/404.html'), 404

# Ajout de la page d'erreur 500
@app.errorhandler(500)
def internal_server_error(e):
    return render_template('errors/500.html'), 500

# Fonction pour créer un context processor qui sera disponible dans tous les templates
@app.context_processor
def inject_user_and_date():
    return {
        'user': g.get('user', None),
        'now': datetime.datetime.now()
    }

@app.route('/api/toggle-favorite/<medicine_id>', methods=['POST'])
def toggle_favorite(medicine_id):
    """Ajoute ou supprime un médicament des favoris de l'utilisateur connecté"""
    # Vérifier si l'utilisateur est connecté
    if not g.get('user'):
        return jsonify({"success": False, "message": "Utilisateur non connecté"}), 401

    user_id = str(g.user['_id'])
    
    try:
        # Vérifier si le médicament existe
        medicine = collection.find_one({'_id': ObjectId(medicine_id)})
        if not medicine:
            return jsonify({"success": False, "message": "Médicament non trouvé"}), 404
        
        from models import Interaction
        
        # Vérifier si le médicament est déjà un favori
        if Interaction.is_favorite(user_id, medicine_id):
            # Supprimer des favoris
            if Interaction.remove_favorite(user_id, medicine_id):
                return jsonify({"success": True, "is_favorite": False})
            else:
                return jsonify({"success": False, "message": "Erreur lors de la suppression des favoris"}), 500
        else:
            # Ajouter aux favoris
            if Interaction.add_favorite(user_id, medicine_id):
                return jsonify({"success": True, "is_favorite": True})
            else:
                return jsonify({"success": False, "message": "Erreur lors de l'ajout aux favoris"}), 500
    except Exception as e:
        print(f"Erreur lors de la gestion des favoris: {e}")
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/api/medicine-summary/<id>')
def get_medicine_summary(id):
    """API endpoint to get the AI summary of a medicine"""
    try:
        # Get language from request
        lang = langue_demandee()
        
        # First check if we already have the summary in the database.
        # Il n'est servi que s'il correspond encore au contenu courant de la notice.
        stored_medicine = db.medicines.find_one(
            {'_id': ObjectId(id)},
            {'ai_summary': 1, 'ai_summary_en': 1,
             'summary_content_hash': 1, 'content_hash': 1}
        )

        if (stored_medicine and stored_medicine.get('ai_summary')
                and summary_is_fresh(stored_medicine, stored_medicine.get('content_hash'))):
            summary = stored_medicine['ai_summary']
            
            # Translate to English if requested
            if lang == 'en':
                # Check for stored English summary first
                if stored_medicine.get('ai_summary_en'):
                    summary = stored_medicine['ai_summary_en']
                else:
                    # Translate live
                    try:
                        from deep_translator import GoogleTranslator
                        translator = GoogleTranslator(source='fr', target='en')
                        summary = translator.translate(summary)
                    except Exception as e:
                        print(f"[SUMMARY] Erreur traduction résumé: {e}")
            
            return jsonify({
                "success": True,
                "summary": summary
            })
        
        # If not, generate a new summary
        medicine = collection.find_one({'_id': ObjectId(id)})
        if not medicine:
            return jsonify({"success": False, "message": "Médicament non trouvé"}), 404
        
        # Generate summary but don't wait for it in the page load
        summary = get_or_generate_summary(medicine, db=db)
        
        # Translate if English requested
        if lang == 'en' and summary:
            try:
                from deep_translator import GoogleTranslator
                translator = GoogleTranslator(source='fr', target='en')
                summary = translator.translate(summary)
            except Exception as e:
                print(f"[SUMMARY] Erreur traduction résumé: {e}")
        
        # Return the generated summary
        return jsonify({
            "success": True,
            "summary": summary
        })
    except Exception as e:
        print(f"Error retrieving medicine summary: {e}")
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/api/medicine-sources/<id>')
def get_medicine_sources(id):
    """API endpoint to get all sources for a medicine"""
    try:
        lang = langue_demandee()
        
        # Get medicine from database
        medicine = db.medicines.find_one({'_id': ObjectId(id)})
        if not medicine:
            return jsonify({"success": False, "message": "Médicament non trouvé"}), 404
        
        # Extract sources from enrichment data
        sources = []
        enrichment = medicine.get('enrichment', {})
        
        # Add sources from enrichment
        if 'sources' in enrichment:
            sources = enrichment['sources']
        
        # Add default French medical sources
        if not sources:
            medicine_name = medicine.get('title') or medicine.get('name', '')
            
            if lang == 'en':
                # English sources
                sources = [
                    {
                        'type': 'ANSM',
                        'url': 'https://base-donnees-publique.medicaments.gouv.fr',
                        'description': 'French National Agency for Medicines Safety',
                        'icon': '🏥'
                    },
                    {
                        'type': 'Thériaque',
                        'url': 'https://www.therique.org',
                        'description': 'Comprehensive French medication database',
                        'icon': '📚'
                    },
                    {
                        'type': 'HAS',
                        'url': 'https://www.has-sante.fr',
                        'description': 'French National Health Authority',
                        'icon': '⚕️'
                    },
                    {
                        'type': 'VIDAL',
                        'url': 'https://www.vidal.fr',
                        'description': 'French medical database',
                        'icon': '💊'
                    }
                ]
            else:
                # French sources
                sources = [
                    {
                        'type': 'ANSM',
                        'url': 'https://base-donnees-publique.medicaments.gouv.fr',
                        'description': 'Agence Nationale de Sécurité du Médicament',
                        'icon': '🏥'
                    },
                    {
                        'type': 'Thériaque',
                        'url': 'https://www.therique.org',
                        'description': 'Base de données complète sur les médicaments',
                        'icon': '📚'
                    },
                    {
                        'type': 'HAS',
                        'url': 'https://www.has-sante.fr',
                        'description': 'Haute Autorité de Santé',
                        'icon': '⚕️'
                    },
                    {
                        'type': 'VIDAL',
                        'url': 'https://www.vidal.fr',
                        'description': 'Base de données médicales françaises',
                        'icon': '💊'
                    }
                ]
        
        return jsonify({
            "success": True,
            "sources": sources,
            "medicine_name": medicine.get('title') or medicine.get('name')
        })
    except Exception as e:
        print(f"Error retrieving medicine sources: {e}")
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/ai-search', methods=['GET', 'POST'])
def ai_search():
    """Recherche IA avec reformulation, recherche multi-requêtes et synthèse RAG.

    Pipeline :
    1. reformulation de la question en mots-clés + synonymes (Mistral) ;
    2. recherche vectorielle Qdrant sur la question ET sa reformulation,
       fusionnées par meilleur score — la phrase naturelle et les mots-clés
       ne réveillent pas les mêmes notices, l'union améliore le rappel ;
    3. scoring hybride vectoriel + textuel (le textuel est calculé sur la
       question d'origine : ses mots sont ceux de l'utilisateur, pas ceux
       des synonymes ajoutés par le modèle) ;
    4. synthèse Mistral alimentée par les extraits de notices les plus
       proches de la question (voir ai_summary._extraits_pertinents).
    """
    debut = time.time()
    user_query = ''
    reformulated_query = ''
    ai_answer = ''
    results = []
    total = 0
    duree_recherche = duree_synthese = None
    lang = langue_demandee()

    # La requête arrive en POST depuis le formulaire de la page, en GET depuis
    # la barre de modes : passer de la recherche exacte à l'assistant reporte
    # la requête par l'URL. Sans cette lecture, l'onglet ouvrait une page vide
    # et il fallait retaper ce qu'on venait d'écrire.
    user_query = (request.form.get('query', '') if request.method == 'POST'
                  else request.args.get('query', '')).strip()
    if user_query:
        # 1. Reformulation (mots-clés enrichis de synonymes médicaux)
        reformulated_query = call_mistral_reformulate(user_query)

        # 2. Recherche vectorielle multi-requêtes avec déduplication :
        # chaque notice n'est gardée qu'une fois, sous son meilleur score.
        candidats = {}
        for variante in dict.fromkeys([user_query, reformulated_query]):
            embedding = embedding_model.encode(variante).tolist()
            search_results = qdrant_client.query_points(
                collection_name="medicines",
                query=embedding,
                limit=40,
                score_threshold=0.1
            )
            for hit in search_results.points:
                mongo_id = str(hit.payload.get('mongo_id') or '') if hasattr(hit, 'payload') else ''
                cle = mongo_id or f"qdrant:{hit.id}"
                score_vectoriel = getattr(hit, 'score', 0)
                deja_vu = candidats.get(cle)
                if deja_vu is None or score_vectoriel > deja_vu['vector_score']:
                    doc = dict(hit.payload) if hasattr(hit, 'payload') else {}
                    doc['vector_score'] = score_vectoriel
                    doc['mongo_id'] = mongo_id
                    candidats[cle] = doc

        # 3. Scoring hybride sur les candidats dédupliqués
        docs = []
        for cle, doc in candidats.items():
            doc['score'] = doc['vector_score']
            try:
                full_doc = None
                if doc.get('mongo_id'):
                    try:
                        full_doc = collection.find_one({'_id': ObjectId(doc['mongo_id'])})
                    except (InvalidId, TypeError):
                        full_doc = collection.find_one({'_id': doc['mongo_id']})

                if full_doc:
                    text_relevance = calculate_relevance_score(full_doc, user_query)
                    doc['text_score'] = text_relevance
                    doc['score'] = (doc['vector_score'] * 0.35) + (min(text_relevance / 100, 1.0) * 0.65)
                    doc['title'] = full_doc.get('title', doc.get('title', 'Sans titre'))
                    doc['full_medicine'] = full_doc
                else:
                    doc['text_score'] = 0
            except Exception as e:
                print(f"Erreur scoring AI: {e}")
                doc['text_score'] = 0

            docs.append(doc)

        # 5. Trier par score (descendant) et limiter au top 12
        docs.sort(key=lambda x: x.get('score', 0), reverse=True)
        results = docs[:12]
        total = len(results)
        duree_recherche = round(time.time() - debut, 1)

        # TRADUCTION LIVE: TEMPORAIREMENT DÉSACTIVÉE (trop lent)
        # TODO: Implémenter cache ou traduction asynchrone
        # if lang == 'en' and results:
        #     medicines_to_translate = [r['full_medicine'] for r in results if r.get('full_medicine')]
        #     if medicines_to_translate:
        #         translated_medicines = translate_medicines_live(medicines_to_translate, lang)
        #
        #         # Remplacer dans results
        #         for i, result in enumerate(results):
        #             if result.get('full_medicine') and i < len(translated_medicines):
        #                 result['title'] = translated_medicines[i].get('title', result.get('title'))
        #                 result['full_medicine'] = translated_medicines[i]

        # 6. Générer la réponse IA dans la langue appropriée
        t_synthese = time.time()
        ai_answer = call_mistral_summarize(user_query, results, language=lang)
        duree_synthese = round(time.time() - t_synthese, 1)
    return render_template(
        "AI_search.html",
        query=user_query,
        reformulated_query=reformulated_query,
        ai_answer=ai_answer,
        results=results,
        total=total,
        initial_count=10,
        duree_recherche=duree_recherche,
        duree_synthese=duree_synthese,
        lang=lang
    )


@app.route('/api/generate-ordonnance', methods=['POST'])
def generate_ordonnance():
    """
    Génère une ordonnance PDF à partir des données du patient et du diagnostic IA
    
    Expected JSON payload:
    {
        "patient": {
            "name": "Nom Prénom",
            "age": "25",
            "symptoms": "Symptômes",
            "medical_history": "Antécédents",
            "current_medications": "Médicaments actuels"
        },
        "diagnostic": {
            "diagnostic_principal": "...",
            "diagnostic_differentiel": "...",
            "recommandations": "..."
        },
        "medications": [
            {
                "title": "Nom du médicament",
                "posologie": "Posologie",
                "duration": "Durée"
            }
        ]
    }
    """
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({'error': 'Données manquantes'}), 400
        
        patient_data = data.get('patient', {})
        diagnostic_data = data.get('diagnostic', {})
        medications_data = data.get('medications', [])
        language = data.get('language', 'fr')  # Langue pour le PDF (fr ou en)
        
        # Valider les données minimales
        if not patient_data.get('name'):
            return jsonify({'error': 'Le nom du patient est requis'}), 400
        
        # Récupérer les informations du médecin connecté
        doctor_data = {
            'name': 'Dr. Mattia Checchia',  # Valeur par défaut
            'specialty': 'Médecin Généraliste',
            'address': '68 Rue Velpeau',
            'city': '92160 Antony'
        }
        
        # Si un utilisateur est connecté, utiliser ses informations
        if hasattr(g, 'user') and g.user:
            first_name = g.user.get('first_name', '')
            last_name = g.user.get('last_name', '')
            if first_name and last_name:
                doctor_data['name'] = f'Dr. {first_name} {last_name}'
            # Utiliser les autres infos si disponibles
            if g.user.get('specialty'):
                doctor_data['specialty'] = g.user.get('specialty')
            if g.user.get('address'):
                doctor_data['address'] = g.user.get('address')
            if g.user.get('city'):
                doctor_data['city'] = g.user.get('city')
        
        # Utiliser directement les médicaments suggérés par l'IA
        # (pas besoin de generate_treatment_from_diagnosis qui génère des traitements génériques)
        print(f"[ORDONNANCE] Génération avec {len(medications_data)} médicaments suggérés par l'IA")
        
        # Formater les médicaments pour l'ordonnance
        treatment_medications = []
        for med in medications_data:
            treatment_medications.append({
                'title': med.get('title', med.get('name', 'Médicament')),
                'posologie': med.get('posologie', med.get('posology', 'Selon prescription')),
                'duration': med.get('duration', med.get('duree', ''))
            })
            print(f"[ORDONNANCE] - {treatment_medications[-1]['title']}")
        
        # Si aucun médicament suggéré, utiliser le fallback
        if not treatment_medications:
            print("[ORDONNANCE] Aucun médicament suggéré, utilisation du fallback")
            diagnostic_principal = diagnostic_data.get('diagnostic_principal', '')
            treatment_medications = generate_treatment_from_diagnosis(diagnostic_principal, [])
        
        # Générer l'ordonnance avec les infos du médecin
        generator = OrdonnanceGenerator()
        pdf_buffer = generator.generate(patient_data, diagnostic_data, treatment_medications, doctor_data, language)
        
        # Créer un nom de fichier avec le nom du patient et la date
        patient_name = patient_data.get('name', 'Patient').replace(' ', '_')
        filename = f"Ordonnance_{patient_name}_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        
        # Retourner le PDF
        return send_file(
            pdf_buffer,
            mimetype='application/pdf',
            as_attachment=True,
            download_name=filename
        )
        
    except Exception as e:
        print(f"Erreur lors de la génération de l'ordonnance: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': f'Erreur lors de la génération du PDF: {str(e)}'}), 500


def generate_treatment_from_diagnosis(diagnostic_text, suggested_medications):
    """
    Génère un traitement médical réel basé sur le diagnostic IA
    
    Args:
        diagnostic_text: Le texte du diagnostic de l'IA
        suggested_medications: Liste des médicaments suggérés par l'IA
    
    Returns:
        Liste de médicaments avec posologie et durée adaptées au diagnostic
    """
    treatments = []
    
    # Extraire le diagnostic principal
    diagnostic_lower = diagnostic_text.lower()
    
    # GASTRO-ENTÉRITE
    if 'gastro' in diagnostic_lower or 'vomissement' in diagnostic_lower or 'diarrhée' in diagnostic_lower:
        treatments = [
            {
                'title': 'SMECTA (Diosmectite)',
                'posologie': '1 sachet 3 fois par jour dans un verre d\'eau',
                'duration': '3 à 5 jours'
            },
            {
                'title': 'SPASFON (Phloroglucinol)',
                'posologie': '2 comprimés 3 fois par jour en cas de douleurs abdominales',
                'duration': '2 à 3 jours'
            },
            {
                'title': 'TIORFAN (Racécadotril)',
                'posologie': '1 gélule 3 fois par jour avant les repas',
                'duration': 'Jusqu\'à arrêt de la diarrhée (max 7 jours)'
            }
        ]
    
    # INFECTION RESPIRATOIRE / GRIPPE
    elif 'grippe' in diagnostic_lower or 'rhume' in diagnostic_lower or 'respiratory' in diagnostic_lower:
        treatments = [
            {
                'title': 'DOLIPRANE 1000mg (Paracétamol)',
                'posologie': '1 comprimé toutes les 6 heures en cas de fièvre ou douleur',
                'duration': '3 à 5 jours'
            },
            {
                'title': 'HUMEX Rhume',
                'posologie': '1 comprimé matin et soir',
                'duration': '5 jours'
            }
        ]
    
    # DOULEUR / INFLAMMATION
    elif 'douleur' in diagnostic_lower or 'inflammation' in diagnostic_lower or 'traumatisme' in diagnostic_lower:
        treatments = [
            {
                'title': 'IBUPROFENE 400mg',
                'posologie': '1 comprimé 3 fois par jour pendant les repas',
                'duration': '3 à 5 jours'
            },
            {
                'title': 'DOLIPRANE 1000mg (Paracétamol)',
                'posologie': '1 comprimé toutes les 6 heures si douleur',
                'duration': '5 jours maximum'
            }
        ]
    
    # ALLERGIE
    elif 'allergi' in diagnostic_lower or 'urticaire' in diagnostic_lower:
        treatments = [
            {
                'title': 'AERIUS (Desloratadine)',
                'posologie': '1 comprimé par jour le matin',
                'duration': '7 jours'
            },
            {
                'title': 'CETIRIZINE 10mg',
                'posologie': '1 comprimé par jour le soir',
                'duration': '5 à 7 jours'
            }
        ]
    
    # INFECTION URINAIRE
    elif 'urinaire' in diagnostic_lower or 'cystite' in diagnostic_lower:
        treatments = [
            {
                'title': 'MONURIL 3g (Fosfomycine)',
                'posologie': '1 sachet en une prise unique le soir à jeun',
                'duration': 'Traitement monodose'
            },
            {
                'title': 'SPASFON',
                'posologie': '2 comprimés 3 fois par jour si douleurs',
                'duration': '2 à 3 jours'
            }
        ]
    
    # Si aucun diagnostic reconnu, utiliser les médicaments suggérés
    if not treatments and suggested_medications:
        treatments = suggested_medications
    
    # Si toujours pas de traitement, mettre un traitement générique
    if not treatments:
        treatments = [
            {
                'title': 'Traitement symptomatique',
                'posologie': 'À adapter selon l\'évolution clinique',
                'duration': 'Selon prescription médicale'
            }
        ]
    
    return treatments


@app.route('/api/prescription/menu')
def prescription_menu():
    """Affiche le menu de choix entre aide au diagnostic et prescription par diagnostic"""
    return render_template('prescription_menu.html')


@app.route('/api/diagnostic-prescription/view')
def diagnostic_prescription_view():
    """Affiche la page de prescription par diagnostic"""
    return render_template('diagnostic_prescription.html')


@app.route('/api/diagnostic-prescription/analyze', methods=['POST'])
def analyze_diagnostic_for_prescription():
    """
    Analyse un diagnostic médical et suggère les médicaments appropriés
    avec des explications détaillées basées sur notre base de données
    
    Expected JSON:
    {
        "diagnostic": "Gastro-entérite aiguë avec déshydratation...",
        "patient_name": "Jean Dupont" (optionnel),
        "age": 45,
        "taille": 170,
        "poids": 75,
        "sexe": "M",
        "antecedents": "Diabète de type 2...",
        "medicaments_actuels": "Metformine..."
    }
    
    Returns:
    {
        "medications": [
            {
                "name": "SMECTA",
                "substance": "Diosmectite",
                "posology": "1 sachet 3 fois par jour",
                "duration": "5 jours",
                "explanation": "Médicament antidiarrhéique qui protège..."
            }
        ],
        "summary": "Traitement complet pour gastro-entérite..."
    }
    """
    try:
        data = request.get_json()
        
        if not data or not data.get('diagnostic'):
            return jsonify({'error': 'Le diagnostic est requis'}), 400
        
        diagnostic = data.get('diagnostic', '').strip()
        patient_name = data.get('patient_name', '').strip()
        age = data.get('age', '')
        taille = data.get('taille', '')
        poids = data.get('poids', '')
        sexe = data.get('sexe', '')
        antecedents = data.get('antecedents', '').strip()
        medicaments_actuels = data.get('medicaments_actuels', '').strip()

        # Détection de la langue utilisateur (par défaut FR)
        user_lang = data.get('lang', 'fr')
        # Si la langue est l'anglais, traduire les champs en FR pour la recherche
        if user_lang == 'en':
            from deep_translator import GoogleTranslator
            # Traduire uniquement si le texte est détecté en anglais (simple heuristique)
            def is_english(text):
                import re
                # Si beaucoup de mots anglais courants, on considère que c'est de l'anglais
                common_en = ['the', 'and', 'with', 'for', 'patient', 'history', 'medication', 'diagnosis', 'years', 'old', 'male', 'female', 'man', 'woman']
                return any(word in text.lower() for word in common_en)
            if is_english(diagnostic):
                diagnostic = GoogleTranslator(source='en', target='fr').translate(diagnostic)
            if is_english(antecedents):
                antecedents = GoogleTranslator(source='en', target='fr').translate(antecedents)
            if is_english(medicaments_actuels):
                medicaments_actuels = GoogleTranslator(source='en', target='fr').translate(medicaments_actuels)
            if is_english(patient_name):
                patient_name = GoogleTranslator(source='en', target='fr').translate(patient_name)
        
        print(f"\n[INFO] ===== NOUVELLE ANALYSE =====")
        print(f"[INFO] Diagnostic: {diagnostic[:100]}...")
        print(f"[INFO] Patient: {patient_name if patient_name else 'Non spécifié'}")
        print(f"[INFO] Âge: {age}, Taille: {taille}cm, Poids: {poids}kg, Sexe: {sexe}")
        print(f"[INFO] Antécédents: {antecedents[:50] if antecedents else 'Aucun'}...")
        print(f"[INFO] Médicaments actuels: {medicaments_actuels[:50] if medicaments_actuels else 'Aucun'}...")
        
        # Contexte patient pour l'analyse
        patient_context = {
            'name': patient_name,
            'age': age,
            'taille': taille,
            'poids': poids,
            'sexe': sexe,
            'antecedents': antecedents,
            'medicaments_actuels': medicaments_actuels
        }
        
        # 1. Rechercher dans MongoDB les médicaments potentiels
        # Extraire les mots-clés du diagnostic
        keywords = extract_medical_keywords(diagnostic)
        print(f"[INFO] Mots-clés extraits: {keywords}")
        
        # 2. Recherche vectorielle dans Qdrant pour trouver les médicaments pertinents
        relevant_medications, ecartes_generation = search_medications_for_diagnostic(
            diagnostic, keywords)
        print(f"[INFO] {len(relevant_medications)} médicaments pertinents trouvés")
        
        # 2 bis. Phase P3 : filtre par classe ATC, **avant** l'appel au modèle.
        #
        # C'est l'inversion que la roadmap appelle. Jusqu'ici le modèle
        # choisissait 2 à 4 médicaments parmi 20 candidats bruts, et la note
        # arrivait après : elle constatait, elle ne décidait pas. La règle
        # constitue désormais le vivier, et le modèle n'intervient qu'à
        # l'intérieur.
        #
        # La génération et le filtrage par classe vivent dans
        # `search_medications_for_diagnostic` : c'est elle, l'étage 1 de
        # l'architecture, et le vivier doit sortir constitué de la fonction qui
        # le constitue. Les placer ici les aurait laissés hors de portée de tout
        # appelant qui ne passe pas par la route.

        # 3. Utiliser Mistral AI pour analyser et sélectionner les meilleurs médicaments
        ai_suggestions = generate_ai_prescription_suggestions(diagnostic, relevant_medications, patient_context)
        print(f"[INFO] Suggestions générées avec succès")

        # 4. Les mêmes contrôles que l'assistant de prescription.
        #
        # Cet écran collectait les antécédents et les traitements en cours, les
        # transmettait au modèle comme contexte libre, et ne vérifiait rien.
        # Les interactions elles-mêmes portaient sur les suggestions **entre
        # elles** : un patient sous warfarine à qui l'écran proposait de
        # l'ibuprofène n'était averti de rien.
        #
        # Les deux écrans vont en sens inverse — celui-ci part d'un diagnostic
        # posé, l'autre des symptômes — mais ils n'ont aucune raison de
        # différer sur ce qui est vérifié une fois la liste constituée.
        propositions = ai_suggestions.get('medications') or []
        for med in propositions:
            # `normaliser_medicament` lit `id` ; le chemin diagnostic pose
            # `_id`. Sans ce report, le lien vers la fiche et la lecture du
            # RCP 4.3 tomberaient tous les deux.
            if med.get('_id') and not med.get('id'):
                med['id'] = str(med['_id'])

        # `contexte` déclenche la notation des candidats, à l'intérieur du
        # tuyau : ils arrivaient **sans note**, choisis par le modèle parmi les
        # résultats de la recherche, et rien ne mesurait leur rapport au
        # diagnostic. L'écran présentait un antihypertenseur pour une pneumonie
        # sans que rien ne l'en distingue.
        #
        # La note est calculée sur le texte du diagnostic, ce qui n'était
        # possible qu'une fois `classes_attendues()` élargie aux conduites
        # cliniques et aux pathologies : « pneumonie » ne figure dans aucune
        # table de symptômes.
        #
        # Elle est calculée **après** la confrontation des substances, que
        # `appliquer_controles` fait pour les deux écrans. L'ordre compte : le
        # modèle annonce la substance de ce qu'il propose et il se trompe, et
        # noter sur son annonce revenait à récompenser l'invention.
        #
        # Les candidats sans lien thérapeutique ne sont **pas** retirés. Le
        # modèle les a choisis, et un médicament écarté en silence emporte avec
        # lui la raison de son retrait (§ 2.8). Ils portent leur note à
        # l'écran, qui vaut zéro et le dit.
        controles = prescription_helper.appliquer_controles(
            propositions,
            antecedents=antecedents,
            traitements_en_cours=prescription_helper.decouper_traitements(
                medicaments_actuels),
            age=int(age) if str(age).isdigit() else 0,
            contexte=diagnostic,
            # Résultats biologiques, tous facultatifs.
            mesures={cle: data.get(cle)
                     for cle in prescription_helper.MESURES_BIOLOGIQUES},
            # Phase P7 : les écartés des étages amont rejoignent la réponse.
            ecartes_generation=ecartes_generation)

        reponse = dict(controles)
        reponse['summary'] = ai_suggestions.get('summary', '')
        # Le contrôle entre suggestions est conservé, sous son propre nom : les
        # deux questions sont différentes et toutes deux légitimes. Confondues
        # dans un seul champ `interactions`, elles laissaient croire que les
        # traitements du patient avaient été regardés.
        reponse['interactions_entre_suggestions'] = ai_suggestions.get(
            'interactions_entre_suggestions') or []

        print(f"[INFO] Controles : {len(reponse['medications'])} propose(s), "
              f"{len(reponse['medicaments_ecartes'])} ecarte(s), "
              f"{len(reponse['interactions'])} interaction(s) avec les traitements")
        print(f"[INFO] ===== FIN ANALYSE =====\n")

        # Si la langue utilisateur est l'anglais, traduire la réponse IA en anglais
        if user_lang == 'en':
            from live_translator_google import GoogleLiveTranslator
            translator = GoogleLiveTranslator()
            reponse = translator._translate_recursive(reponse)
        return jsonify(reponse)
        
    except Exception as e:
        print(f"Erreur lors de l'analyse du diagnostic: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': f'Erreur lors de l\'analyse: {str(e)}'}), 500


def extract_medical_keywords(diagnostic_text):
    """
    Extrait les mots-clés médicaux importants du diagnostic
    """
    # Mots-clés courants à rechercher
    keywords = []
    diagnostic_lower = diagnostic_text.lower()
    
    # Pathologies communes
    pathologies = [
        'gastro-entérite', 'gastro', 'diarrhée', 'vomissement',
        'grippe', 'rhume', 'infection', 'angine', 'bronchite',
        'douleur', 'inflammation', 'fièvre', 'migraine', 'céphalée',
        'allergie', 'urticaire', 'rhinite', 'asthme',
        'hypertension', 'diabète', 'cholestérol',
        'infection urinaire', 'cystite',
        'anxiété', 'dépression', 'insomnie'
    ]
    
    for pathology in pathologies:
        if pathology in diagnostic_lower:
            keywords.append(pathology)
    
    # Symptômes
    symptoms = [
        'nausée', 'vomissement', 'diarrhée', 'constipation',
        'fièvre', 'toux', 'mal de gorge', 'congestion',
        'douleur', 'fatigue', 'vertige', 'maux de tête'
    ]
    
    for symptom in symptoms:
        if symptom in diagnostic_lower:
            keywords.append(symptom)
    
    return list(set(keywords))  # Éliminer les doublons


def search_medications_for_diagnostic(diagnostic, keywords):
    """
    Recherche les médicaments pertinents dans MongoDB et Qdrant
    basé sur le diagnostic et les mots-clés
    """
    relevant_meds = []
    
    try:
        # 1. Recherche vectorielle avec Qdrant (sémantique)
        query_vector = embedding_model.encode(diagnostic).tolist()
        qdrant_results = qdrant_client.query_points(
            collection_name="medicines",
            query=query_vector,
            limit=50  # Top 50 médicaments similaires
        )
        
        print(f"[DEBUG] Qdrant a trouvé {len(qdrant_results.points)} résultats")
        
        # Récupérer les détails depuis MongoDB
        for res in qdrant_results.points:
            if hasattr(res, 'score') and res.score >= 0.2:  # Score abaissé de 0.3 à 0.2
                mongo_id = res.payload.get('mongo_id')
                if mongo_id:
                    try:
                        med = collection.find_one({'_id': ObjectId(mongo_id)})
                        if med:
                            med['_id'] = str(med['_id'])
                            # Phase P4 : la similarité cosinus a son propre
                            # champ. Elle partageait `relevance_score` avec la
                            # note clinique — deux grandeurs, deux échelles,
                            # un seul nom.
                            med['similarite'] = res.score
                            relevant_meds.append(med)
                            # Le champ est 'title' dans MongoDB, pas 'name'
                            med_name = med.get('title', med.get('name', 'Inconnu'))
                            print(f"[DEBUG] Médicament ajouté: {med_name} (score: {res.score:.3f})")
                    except Exception as e:
                        print(f"[DEBUG] Erreur lors de la récupération MongoDB: {e}")
                        continue
        
        # 2. Recherche par mots-clés dans MongoDB
        if keywords:
            print(f"[DEBUG] Recherche avec mots-clés: {keywords}")
            keyword_query = {
                '$or': [
                    {'indications': {'$regex': '|'.join(keywords), '$options': 'i'}},
                    {'description': {'$regex': '|'.join(keywords), '$options': 'i'}},
                    {'composition': {'$regex': '|'.join(keywords), '$options': 'i'}},
                    {'title': {'$regex': '|'.join(keywords), '$options': 'i'}}
                ]
            }
            
            keyword_results = collection.find(keyword_query).limit(30)
            
            for med in keyword_results:
                med['_id'] = str(med['_id'])
                # Vérifier si pas déjà dans les résultats
                if not any(m.get('_id') == med['_id'] for m in relevant_meds):
                    # Similarité par défaut pour la recherche par mots-clés.
                    med['similarite'] = 0.5
                    relevant_meds.append(med)
                    med_name = med.get('title', med.get('name', 'Inconnu'))
                    print(f"[DEBUG] Médicament ajouté (mots-clés): {med_name}")
        
        # Phase P3b : la génération par classe attendue.
        #
        # Un filtre retire, il n'ajoute jamais. Mesuré avant cette phase : pour
        # « pneumonie communautaire », le vivier comptait 19 candidats et
        # **zéro antibiotique**. Aucun filtrage ne pouvait faire apparaître un
        # J01 absent.
        #
        # Le graphe est donc interrogé dans l'autre sens : quelles spécialités
        # portent une substance dont la classe répond au diagnostic. Ces
        # candidats-là passent devant : ils viennent d'une règle, quand les
        # autres viennent d'une similarité de texte.
        attendues = prescription_helper.classes_atc_attendues(diagnostic)
        if attendues:
            par_classe = prescription_helper.candidats_par_classe(attendues)
            deja = {(m.get('title') or '') for m in relevant_meds}
            nouveaux = [m for m in par_classe if m['title'] not in deja]
            print(f"[INFO] Classes attendues {sorted(attendues)} : "
                  f"{len(nouveaux)} candidat(s) generes")
            relevant_meds = nouveaux + relevant_meds

        # Phase P1 de la roadmap : filtre d'éligibilité, dès la constitution du
        # vivier et **avant** que le modèle ne choisisse.
        #
        # C'est ici que SUBSOL SANS POTASSIUM entrait dans la liste : non
        # commercialisé et de voie extracorporelle, il était pourtant proposé
        # pour une décompensation cardiaque. Deux faits administratifs
        # suffisaient à l'écarter, et aucun n'était lu.
        relevant_meds, ineligibles = prescription_helper.filtrer_eligibilite(
            relevant_meds)
        if ineligibles:
            print(f"[INFO] Eligibilite : {len(ineligibles)} candidat(s) ecarte(s)")

        # Phase P3a et P3b : filtre par classe. Les deux marqueurs qui se
        # passent du diagnostic — V04 agents diagnostiques, B05 solutions de
        # perfusion — et les classes que le diagnostic appelle quand la table
        # les connaît.
        #
        # Sans classes attendues — diagnostic hors table — le filtre s'en tient
        # aux marqueurs. Ne rien savoir n'est pas savoir que rien ne convient.
        relevant_meds, hors_classe = prescription_helper.filtrer_par_classe(
            relevant_meds, attendues=attendues)
        if hors_classe:
            print(f"[INFO] Classe ATC : {len(hors_classe)} candidat(s) ecarte(s)")

        # Les candidats venus d'une règle passent devant ceux venus d'une
        # similarité : un antibiotique appelé par le diagnostic vaut mieux
        # qu'une spécialité dont le texte ressemblait.
        relevant_meds.sort(key=lambda m: (
            0 if m.get('origine') == 'classe_atc' else 1,
            1 if m.get('sans_classe') else 0,
            -(m.get('similarite') or 0)))

        print(f"[DEBUG] Total médicaments trouvés: {len(relevant_meds)}")

        # Phase P7 : les écartés remontent avec le vivier.
        #
        # Ils étaient **jetés ici**. Trois étages — éligibilité, classe, et le
        # seuil plus loin — retiraient des candidats sans que rien n'en
        # parvienne à l'écran : le médecin voyait une liste courte sans savoir
        # ce qui l'avait raccourcie. C'est ce que le § 2.8 reproche depuis le
        # début, appliqué aux étages amont.
        return relevant_meds[:20], ineligibles + hors_classe
        
    except Exception as e:
        print(f"Erreur lors de la recherche de médicaments: {e}")
        import traceback
        traceback.print_exc()
        return [], []


def check_interactions_neo4j(medication_urls):
    """
    Vérifie les interactions entre médicaments via Neo4j
    
    Args:
        medication_urls: Liste des URLs des médicaments
        
    Returns:
        Dict avec les interactions trouvées
    """
    if not neo4j_connector or not neo4j_connector.driver:
        print("[DEBUG] Neo4j non disponible pour vérifier les interactions")
        return {'has_interactions': False, 'interactions': []}
    
    try:
        with neo4j_connector.driver.session(database=neo4j_connector.database) as session:
            # Requête pour trouver les interactions entre les médicaments de la liste
            # L'interaction relie deux substances, non deux spécialités : la
            # requête passait par des relations Medicine→Medicine que la
            # reconstruction P9-3 a supprimées, et ne rendait donc plus rien.
            result = session.run("""
                UNWIND $urls as url1
                UNWIND $urls as url2
                WITH url1, url2 WHERE url1 < url2
                MATCH (m1:Medicine {url: url1})-[:HAS_DRUGBANK_SUBSTANCE]->(s1:DrugbankSubstance)
                MATCH (m2:Medicine {url: url2})-[:HAS_DRUGBANK_SUBSTANCE]->(s2:DrugbankSubstance)
                MATCH (s1)-[r:INTERACTS_WITH]-(s2)
                RETURN DISTINCT m1.title as med1, m2.title as med2,
                       s1.name as sub1, s2.name as sub2,
                       r.description as description
            """, {'urls': medication_urls})

            # Pas de `severity` : la source n'en porte aucune, et une gradation
            # inventée orienterait une décision de prescription.
            interactions = []
            for record in result:
                interactions.append({
                    'medicine1': f"{record['med1']} ({record['sub1']})",
                    'medicine2': f"{record['med2']} ({record['sub2']})",
                    'description': record['description']
                })
            
            print(f"[DEBUG] Neo4j a trouvé {len(interactions)} interactions")
            return {
                'has_interactions': len(interactions) > 0,
                'interactions': interactions
            }
    except Exception as e:
        print(f"[WARNING] Erreur lors de la vérification des interactions Neo4j: {e}")
        return {'has_interactions': False, 'interactions': []}


def enrich_with_neo4j_data(medications_list):
    """
    Enrichit les médicaments avec des données de Neo4j (substances, laboratoires)
    
    Args:
        medications_list: Liste des médicaments
        
    Returns:
        Liste enrichie avec données Neo4j
    """
    if not neo4j_connector or not neo4j_connector.driver:
        print("[DEBUG] Neo4j non disponible pour enrichissement")
        return medications_list
    
    try:
        enriched = []
        with neo4j_connector.driver.session(database=neo4j_connector.database) as session:
            for med in medications_list:
                url = med.get('url', '')
                if url:
                    # Récupérer les substances et le laboratoire depuis Neo4j
                    result = session.run("""
                        MATCH (m:Medicine {url: $url})
                        OPTIONAL MATCH (m)-[:CONTAINS_SUBSTANCE]->(s:Substance)
                        OPTIONAL MATCH (m)-[:MANUFACTURED_BY]->(l:Laboratory)
                        RETURN collect(DISTINCT s.name) as substances,
                               l.name as laboratory
                    """, {'url': url})
                    
                    record = result.single()
                    if record:
                        med['neo4j_substances'] = record['substances']
                        med['neo4j_laboratory'] = record['laboratory']
                        print(f"[DEBUG] Neo4j enrichissement: {med.get('title', 'Inconnu')} - {len(record['substances'])} substances")
                
                enriched.append(med)
        
        return enriched
    except Exception as e:
        print(f"[WARNING] Erreur lors de l'enrichissement Neo4j: {e}")
        return medications_list


def generate_ai_prescription_suggestions(diagnostic, medications_list, patient_context=None):
    """
    Utilise Mistral AI pour analyser le diagnostic et suggérer les meilleurs médicaments
    avec des explications détaillées. Enrichit avec Neo4j et Qdrant.
    Prend en compte le contexte patient (âge, poids, antécédents, médicaments actuels).
    """
    try:
        from mistralai import Mistral
        
        print(f"[DEBUG] Génération suggestions IA avec {len(medications_list)} médicaments")
        
        # Si aucun médicament trouvé, utiliser le fallback clinique
        if not medications_list:
            print("[DEBUG] Aucun médicament en base, utilisation du fallback clinique")
            fallback = get_clinical_fallback(diagnostic)
            # Ignorer le scoring IA et retourner directement le fallback
            return {
                'medications': fallback,
                'summary': 'Aucun médicament spécifique trouvé dans la base de données. Suggestions basées sur les recommandations cliniques standard.'
            }
        
        # Enrichir avec Neo4j (substances actives, laboratoires)
        print("[DEBUG] Enrichissement avec Neo4j...")
        enriched_meds = enrich_with_neo4j_data(medications_list)
        
        # Préparer le contexte patient
        patient_info = ""
        if patient_context:
            patient_info = "\nINFORMATIONS PATIENT:\n"
            if patient_context.get('age'):
                patient_info += f"- Âge: {patient_context['age']} ans\n"
            if patient_context.get('poids'):
                patient_info += f"- Poids: {patient_context['poids']} kg\n"
            if patient_context.get('taille'):
                patient_info += f"- Taille: {patient_context['taille']} cm\n"
            if patient_context.get('sexe'):
                sexe_label = {'M': 'Masculin', 'F': 'Féminin', 'A': 'Autre'}.get(patient_context['sexe'], patient_context['sexe'])
                patient_info += f"- Sexe: {sexe_label}\n"
            if patient_context.get('antecedents'):
                patient_info += f"- Antécédents: {patient_context['antecedents']}\n"
            if patient_context.get('medicaments_actuels'):
                patient_info += f"- Médicaments actuels: {patient_context['medicaments_actuels']}\n"
            print(f"[DEBUG] Contexte patient ajouté")
        
        # Préparer le contexte avec les médicaments disponibles (enrichis Neo4j)
        meds_context = ""
        for i, med in enumerate(enriched_meds[:15], 1):  # Top 15 médicaments
            # MongoDB utilise 'title' pour le nom du médicament
            name = med.get('title', med.get('name', 'Nom inconnu'))
            composition = med.get('composition', 'Non spécifié')
            indications = med.get('indications', 'Non spécifié')
            
            # Ajouter les données Neo4j si disponibles
            neo4j_substances = med.get('neo4j_substances', [])
            neo4j_lab = med.get('neo4j_laboratory', '')
            
            # Limiter la longueur pour éviter un contexte trop long
            if composition and composition != 'Non spécifié':
                composition = composition[:300]
            if indications and indications != 'Non spécifié':
                indications = indications[:300]
            
            meds_context += f"\n{i}. {name}\n"
            meds_context += f"   Composition: {composition}\n"
            meds_context += f"   Indications: {indications}\n"
            
            # Enrichissement Neo4j
            if neo4j_substances and len(neo4j_substances) > 0:
                meds_context += f"   Substances actives (Neo4j): {', '.join(neo4j_substances[:3])}\n"
            if neo4j_lab:
                meds_context += f"   Laboratoire (Neo4j): {neo4j_lab}\n"
        
        print(f"[DEBUG] Contexte médicaments préparé ({len(meds_context)} caractères)")
        
        # Créer le prompt pour Mistral
        prompt = f"""Tu es un médecin expert en prescription médicale. Analyse le diagnostic suivant et suggère les 2 à 4 médicaments les PLUS APPROPRIÉS parmi la liste fournie.

DIAGNOSTIC DU PATIENT:
{diagnostic}
{patient_info}

MÉDICAMENTS DISPONIBLES DANS LA BASE:
{meds_context}

RÈGLES STRICTES DE SÉLECTION:
1. Ne sélectionner QUE les médicaments DIRECTEMENT indiqués pour le diagnostic principal ou les diagnostics différentiels listés ci-dessus.
2. EXCLURE formellement les médicaments destinés à des pathologies chroniques sans lien avec l'épisode aigu actuel (asthme, allergie, HTA, diabète, etc.) sauf s'ils font partie du traitement de l'épisode en cours.
3. Utiliser les informations patient UNIQUEMENT pour adapter la posologie et vérifier les contre-indications, PAS pour ajouter des médicaments pour des comorbidités sans lien avec le diagnostic actuel.
4. Chaque médicament doit avoir un lien thérapeutique DIRECT et JUSTIFIÉ avec le diagnostic posé.
5. Pour CHAQUE médicament sélectionné, fournis:
   - Le nom exact du médicament
   - La substance active principale
   - La posologie précise ADAPTÉE au patient
   - La durée du traitement
   - Une explication claire (1-2 phrases) du lien DIRECT avec le diagnostic

6. Termine avec un résumé du traitement (1-2 phrases) centré uniquement sur l'épisode actuel.

FORMAT DE RÉPONSE (JSON UNIQUEMENT):
```json
{{
  "medications": [
    {{
      "name": "NOM DU MÉDICAMENT",
      "substance": "Substance active",
      "posology": "Posologie précise adaptée au patient",
      "duration": "Durée du traitement",
      "explanation": "Lien direct avec le diagnostic actuel (1-2 phrases)"
    }}
  ],
  "summary": "Résumé du traitement pour l'épisode en cours"
}}
```

IMPORTANT: Réponds UNIQUEMENT avec le JSON. Aucun médicament pour des comorbidités chroniques sans lien avec l'épisode aigu."""

        # Appeler Mistral AI
        print("[DEBUG] Appel à Mistral AI...")
        client = Mistral(api_key=app.config['MISTRAL_API_KEY'])
        
        chat_response = client.chat.complete(
            model="mistral-small-2503",
            messages=[
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            temperature=0.3,  # Basse température pour des réponses précises
            max_tokens=2000
        )
        
        response_text = chat_response.choices[0].message.content.strip()
        print(f"[DEBUG] Réponse Mistral reçue: {response_text[:200]}...")
        
        # Extraire le JSON de la réponse
        import re
        json_match = re.search(r'```json\s*(.*?)\s*```', response_text, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
        else:
            # Si pas de balises, essayer de parser directement
            json_str = response_text
        
        print(f"[DEBUG] Parsing JSON...")
        # Parser le JSON
        result = json.loads(json_str)
        print(f"[DEBUG] JSON parsé avec succès! {len(result.get('medications', []))} médicaments suggérés")
        
        # Si l'IA n'a suggéré aucun médicament, utiliser le fallback clinique
        if not result.get('medications'):
            print("[DEBUG] L'IA n'a suggéré aucun médicament, fallback clinique")
            clinical = get_clinical_fallback(diagnostic)
            return {
                'medications': clinical,
                'summary': 'Les suggestions ci-dessus sont basées sur les recommandations cliniques standard (aucune correspondance trouvée dans la base de données spécifique).'
            }
        
        # Ensure every suggested medicine has a valid '_id' and 'url' field (like vector search)
        suggested_urls = []
        for suggested_med in result.get('medications', []):
            med_name = suggested_med.get('name', '')
            found = False
            for med in enriched_meds:
                if med.get('title', '').lower() == med_name.lower():
                    # Ajoute l'_id MongoDB si présent
                    if med.get('_id'):
                        suggested_med['_id'] = str(med['_id'])
                        url = f"/medicine/{med['_id']}"
                    else:
                        url = med.get('url', '')
                        if not url:
                            import re
                            slug = re.sub(r'[^a-zA-Z0-9]+', '-', med.get('title', med_name)).strip('-').lower()
                            url = f"/medicine/{slug}"
                    med['url'] = url
                    suggested_urls.append(url)
                    suggested_med['url'] = url
                    found = True
                    break
            if not found:
                # Fallback: slugify name
                import re
                slug = re.sub(r'[^a-zA-Z0-9]+', '-', med_name).strip('-').lower()
                url = f"/medicine/{slug}"
                suggested_urls.append(url)
                suggested_med['url'] = url

        # Interactions des médicaments suggérés **entre eux**. C'est une autre
        # question que celle des interactions avec les traitements du patient,
        # posée plus loin par `appliquer_controles`. Les deux sont légitimes,
        # et elles ne doivent pas être confondues : réunies sous un seul champ
        # `interactions`, elles laissaient croire que les traitements en cours
        # avaient été regardés, alors qu'ils ne l'étaient jamais.
        if len(suggested_urls) > 1:
            print(f"[DEBUG] Vérification des interactions Neo4j pour {len(suggested_urls)} médicaments...")
            interactions_check = check_interactions_neo4j(suggested_urls)

            if interactions_check['has_interactions']:
                # Aucun niveau de gravité n'est rendu : la source n'en porte
                # pas (rapport P9-1). « Sévérité : Inconnue » était affiché,
                # ce qui laisse croire qu'il en existe un et qu'on l'ignore.
                # Le commentaire du gabarit disait déjà l'inverse du code.
                result['interactions_entre_suggestions'] = [
                    {k: v for k, v in inter.items() if k != 'severity'}
                    for inter in interactions_check['interactions']
                ]
                # Le résumé n'est plus gonflé du relevé des interactions : il
                # a son panneau, et un texte qui grossit d'avertissements
                # finit par ne plus être lu.
                print(f"[INFO] {len(interactions_check['interactions'])} interaction(s) entre suggestions")

        return result
        
    except Exception as e:
        print(f"[ERROR] Erreur lors de l'appel à Mistral AI: {e}")
        import traceback
        traceback.print_exc()
        
        # Fallback: retourner des suggestions basiques basées sur le diagnostic
        print("[DEBUG] Utilisation du fallback...")
        return generate_fallback_suggestions(diagnostic, medications_list)


def generate_fallback_suggestions(diagnostic, medications_list):
    """
    Génère des suggestions de secours si l'IA échoue
    Utilise les vraies données des médicaments trouvés
    """
    diagnostic_lower = diagnostic.lower()
    suggestions = []
    
    print(f"[DEBUG] Génération fallback avec {len(medications_list)} médicaments")
    
    # Sélectionner les médicaments les plus pertinents (top 3-5)
    for med in medications_list[:5]:
        # MongoDB utilise 'title' pour le nom du médicament
        name = med.get('title', med.get('name', 'Médicament inconnu'))
        composition = med.get('composition', '')
        indications = med.get('indications', '')
        description = med.get('description', '')
        
        # Extraire la substance active de la composition
        substance = 'Voir notice'
        if composition and composition != 'Non spécifié':
            # Prendre les premiers mots de la composition
            substance = composition.split('.')[0][:100]
        
        # Créer une explication basée sur les indications
        explanation = "Ce médicament est suggéré car il correspond au diagnostic"
        if indications and len(indications) > 10:
            explanation = f"Indications : {indications[:200]}"
        elif description and len(description) > 10:
            explanation = f"{description[:200]}"
        
        # Essayer de déterminer une posologie basique
        posology = 'Selon prescription médicale'
        duration = 'À déterminer selon l\'évolution'
        
        # Patterns courants pour extraire la posologie si disponible
        if description:
            if 'posologie' in description.lower():
                # Chercher la section posologie
                parts = description.lower().split('posologie')
                if len(parts) > 1:
                    posology_text = parts[1][:200]
                    posology = posology_text.strip()
        
        suggestions.append({
            'name': name,
            'substance': substance,
            'posology': posology,
            'duration': duration,
            'explanation': explanation
        })
        
        print(f"[DEBUG] Fallback - Médicament: {name}")
    
    if not suggestions:
        print("[DEBUG] Fallback vide, utilisation des recommandations cliniques standard")
        suggestions = get_clinical_fallback(diagnostic)
    
    return {
        'medications': suggestions,
        'summary': f'Traitement suggéré basé sur l\'analyse de {len(suggestions)} médicament(s) dans notre base de données. Ces suggestions sont basées sur la pertinence sémantique avec votre diagnostic. Veuillez adapter selon votre jugement clinique et les antécédents du patient.'
    }


# === NOUVEAUX ENDPOINTS DASHBOARD SÉCURITÉ & PHARMA ===

#: Substances les plus portées par les fiches, pour les suggestions de
#: recherche. Calculées une fois par processus, comme le compte des
#: substances distinctes : le catalogue ne bouge qu'aux imports.
_frequentes = None


def _substances_frequentes(combien=6):
    global _frequentes
    if _frequentes is not None:
        return _frequentes
    from collections import Counter
    compte = Counter()
    try:
        for doc in collection.find(
                {'medicine_details.substances_actives': {'$exists': True}},
                {'medicine_details.substances_actives': 1}):
            for nom in (doc.get('medicine_details', {})
                        .get('substances_actives') or []):
                # Les libellés longs sont des associations, illisibles en
                # pastille : « chlorhydrate de … monohydraté » ne tient pas.
                if nom and len(nom) < 20:
                    compte[nom.strip().lower()] += 1
    except Exception as err:
        print(f"[ACCUEIL ESSAI] Substances fréquentes : {err}")
        return []
    _frequentes = [nom for nom, _ in compte.most_common(combien)]
    return _frequentes


@app.route('/', endpoint='index')
@app.route('/accueil-essai')
def accueil_essai():
    """La page d'accueil du site.

    L'`endpoint` reste `index` : sept endroits font `url_for('index')` pour
    dire « l'accueil » — les deux pages d'erreur et les cinq redirections de
    connexion et de déconnexion. Laisser le nom sur l'ancienne page les aurait
    tous envoyés sur `/accueil-classique` sans qu'aucun ne le demande.

    Elle est née sur `/accueil-essai` comme second parti pris visuel, à
    comparer avec l'accueil d'alors. C'est elle qui a été retenue : elle sert
    désormais `/`, et l'ancienne page est jointe sur `/accueil-classique`.

    L'ancienne adresse reste valide. Elle a été partagée, et un lien qui
    tombe en 404 parce qu'une page a été promue est une régression pour qui
    l'avait gardé.
    """
    fiches = laboratoires = 0
    interactions = substances = structures = 0
    molecule_nom, molecule_cle = 'Morphine', 'BQJCRHHNABKAKU-KBQPJGBKSA-N'
    substances_liees = []
    # Suggestions de recherche tirees du catalogue, calculees une fois par
    # processus : parcourir les fiches a chaque visite pour proposer six mots
    # est precisement l erreur qui a fait tomber la page d accueil.
    substances_frequentes = _substances_frequentes()
    try:
        fiches = collection.count_documents({})
        laboratoires = len(collection.distinct('medicine_details.laboratoire'))
    except Exception as err:
        print(f"[ESSAI] Mongo : {err}")
    if neo4j_connector and neo4j_connector.driver:
        try:
            with neo4j_connector.driver.session(
                    database=neo4j_connector.database) as session:
                interactions = session.run(
                    "MATCH ()-[r:INTERACTS_WITH]->() RETURN count(r) AS c"
                ).single()['c']
                substances = session.run(
                    "MATCH (n:DrugbankSubstance) RETURN count(n) AS c"
                ).single()['c']
                structures = session.run(
                    "MATCH (n:DrugbankSubstance) WHERE n.svg IS NOT NULL "
                    "RETURN count(n) AS c").single()['c']
                ligne = session.run("""
                    MATCH (n:DrugbankSubstance)
                    WHERE n.svg IS NOT NULL AND n.inchikey IS NOT NULL
                    RETURN n.name AS nom, n.inchikey AS cle
                    ORDER BY CASE WHEN n.inchikey = $prefere THEN 0 ELSE 1 END, n.name
                    LIMIT 1
                """, prefere=molecule_cle).single()
                if ligne:
                    molecule_nom, molecule_cle = ligne['nom'], ligne['cle']
                # Le bandeau défilant porte de vraies données : les substances
                # que le graphe relie le plus. Un texte décoratif inventé
                # aurait été plus simple et aurait menti.
                substances_liees = [r['nom'] for r in session.run("""
                    MATCH (n:DrugbankSubstance)-[i:INTERACTS_WITH]-()
                    WITH n, count(i) AS degre
                    RETURN n.name AS nom ORDER BY degre DESC LIMIT 22
                """)]
        except Exception as err:
            print(f"[ESSAI] Neo4j : {err}")

    return render_template('accueil_essai.html',
                           fiches=fiches,
                           laboratoires=laboratoires,
                           interactions=interactions,
                           substances=substances,
                           structures=structures,
                           molecule_nom=molecule_nom,
                           molecule_cle=molecule_cle,
                           substances_liees=substances_liees,
                           substances_frequentes=substances_frequentes)


#: Relevé d'architecture, calculé une fois par processus.
#:
#: La page « À propos » décrit la structure interne du projet et cite des
#: chiffres qui la décrivent : effectifs par collection, règles d'appariement,
#: vecteurs indexés. Les obtenir demande des agrégations sur plusieurs dizaines
#: de milliers de documents, ce qui n'a rien à faire dans une requête HTTP.
#:
#: La leçon est récente : la page d'accueil comptait les substances distinctes
#: en parcourant les 13 594 fiches à chaque visite, et MongoDB s'est arrêté
#: faute de mémoire. Un chiffre juste payé à chaque affichage reste un défaut.
_releve_architecture = None


def relever_architecture():
    """Compte ce que la page « À propos » affiche, puis le retient.

    Chaque bloc est isolé : un magasin indisponible laisse sa clé à ``None``,
    et le gabarit dit alors que la donnée manque au lieu d'afficher un zéro
    qui se lirait comme une mesure.
    """
    global _releve_architecture
    if _releve_architecture is not None:
        return _releve_architecture

    releve = {'collections': None, 'octets_mongo': None, 'regles': None,
              'apparies': None, 'non_apparies': None, 'vecteurs': None,
              'dimension': None, 'etiquettes': None, 'aretes': None,
              'lignes': None, 'fichiers': None, 'routes': None}

    # Le volume de code et le nombre de routes changent à chaque commit.
    # Les écrire dans le gabarit reviendrait à publier un chiffre qui devient
    # faux sans que personne ne s'en aperçoive, exactement ce que cette page
    # reproche par ailleurs. Quatre-vingts fichiers se comptent en un clin
    # d'œil, et le résultat est retenu comme le reste.
    try:
        racine = os.path.dirname(os.path.abspath(__file__))
        ignores = ('__pycache__', 'node_modules', '.git', 'qdrant_storage',
                   'ressources', 'archive')
        lignes = fichiers = 0
        for dossier, _, noms in os.walk(racine):
            if any(x in dossier for x in ignores):
                continue
            for nom in noms:
                if not nom.endswith(('.py', '.html', '.css', '.js')):
                    continue
                try:
                    with open(os.path.join(dossier, nom), encoding='utf-8',
                              errors='replace') as fichier:
                        lignes += sum(1 for _ in fichier)
                    fichiers += 1
                except Exception:
                    continue
        releve['lignes'], releve['fichiers'] = lignes, fichiers
    except Exception as err:
        print(f"[A PROPOS] Volume de code : {err}")

    try:
        # Les règles statiques et le point d'échec ne sont pas des routes de
        # l'application : les compter gonflerait le chiffre d'un tiers.
        releve['routes'] = len({r.endpoint for r in app.url_map.iter_rules()
                                if r.endpoint != 'static'})
    except Exception as err:
        print(f"[A PROPOS] Table des routes : {err}")

    try:
        noms = db.list_collection_names()
        releve['collections'] = len(noms)
        total = 0
        for nom in noms:
            try:
                total += db.command('collstats', nom).get('storageSize', 0)
            except Exception:
                continue
        releve['octets_mongo'] = total
    except Exception as err:
        print(f"[A PROPOS] Inventaire Mongo : {err}")

    # Les règles d'appariement sont l'endroit où le projet est le plus
    # exposé : un nom français doit retrouver une substance anglaise. Le
    # détail par règle est conservé document par document, ce qui permet de
    # dire comment chaque fiche a été appariée, et combien ne l'ont pas été.
    try:
        regles = [(d['_id'], d['n']) for d in db.medicine_enrichment.aggregate([
            {'$group': {'_id': '$match_rule', 'n': {'$sum': 1}}},
            {'$sort': {'n': -1}}]) if d['_id']]
        releve['regles'] = regles
        releve['apparies'] = db.medicine_enrichment.count_documents(
            {'drugbank_ids.0': {'$exists': True}})
        releve['non_apparies'] = sum(n for r, n in regles if r == 'no_match')
    except Exception as err:
        print(f"[A PROPOS] Règles d'appariement : {err}")

    try:
        points = dimension = 0
        for c in qdrant_client.get_collections().collections:
            info = qdrant_client.get_collection(c.name)
            points += info.points_count or 0
            dimension = info.config.params.vectors.size
        releve['vecteurs'], releve['dimension'] = points, dimension
    except Exception as err:
        print(f"[A PROPOS] Qdrant : {err}")

    # Le schéma du graphe est dessiné sur la page. Les effectifs portés par le
    # dessin sont lus ici plutôt qu'écrits dans le gabarit : un import qui
    # ajoute des arêtes rendrait le schéma faux sans rien casser, et c'est
    # précisément le genre de dérive que cette page reproche au reste.
    releve['noeuds'], releve['liens'] = {}, {}
    if neo4j_connector and neo4j_connector.driver:
        try:
            with neo4j_connector.driver.session(
                    database=neo4j_connector.database) as session:
                etiquettes = [r['label'] for r in session.run(
                    "CALL db.labels() YIELD label RETURN label")]
                types = [r['t'] for r in session.run(
                    "CALL db.relationshipTypes() YIELD relationshipType AS t "
                    "RETURN t")]
                releve['etiquettes'], releve['aretes'] = len(etiquettes), len(types)
                for nom in etiquettes:
                    releve['noeuds'][nom] = session.run(
                        f"MATCH (n:`{nom}`) RETURN count(n) AS c").single()['c']
                for nom in types:
                    releve['liens'][nom] = session.run(
                        f"MATCH ()-[r:`{nom}`]->() RETURN count(r) AS c").single()['c']
        except Exception as err:
            print(f"[A PROPOS] Schéma du graphe : {err}")

    _releve_architecture = releve
    return releve


@app.route('/a-propos')
def a_propos():
    """Page « À propos ».

    Les chiffres sont comptés à l'affichage plutôt qu'écrits dans le gabarit :
    une page qui raconte le refus d'afficher une donnée sans source ne peut pas
    porter des nombres figés qui dérivent silencieusement de la base.

    Les comptages coûteux passent par `relever_architecture`, qui ne les fait
    qu'une fois par processus.
    """
    fiches = interactions = substances = structures = 0
    molecule_nom, molecule_cle = 'Morphine', 'BQJCRHHNABKAKU-KBQPJGBKSA-N'
    try:
        fiches = collection.count_documents({})
    except Exception as err:
        print(f"[A PROPOS] Mongo : {err}")
    if neo4j_connector and neo4j_connector.driver:
        try:
            with neo4j_connector.driver.session(
                    database=neo4j_connector.database) as session:
                interactions = session.run(
                    "MATCH ()-[r:INTERACTS_WITH]->() RETURN count(r) AS c"
                ).single()['c']
                substances = session.run(
                    "MATCH (n:DrugbankSubstance) RETURN count(n) AS c"
                ).single()['c']
                structures = session.run(
                    "MATCH (n:DrugbankSubstance) WHERE n.svg IS NOT NULL "
                    "RETURN count(n) AS c").single()['c']
                # La molécule illustrée est tirée du graphe : si son dessin
                # venait à manquer, la page prendrait la première disponible
                # plutôt que d'afficher une image cassée.
                ligne = session.run("""
                    MATCH (n:DrugbankSubstance)
                    WHERE n.svg IS NOT NULL AND n.inchikey = $cle
                    RETURN n.name AS nom, n.inchikey AS cle
                """, cle=molecule_cle).single()
                if not ligne:
                    ligne = session.run("""
                        MATCH (n:DrugbankSubstance)
                        WHERE n.svg IS NOT NULL AND n.inchikey IS NOT NULL
                        RETURN n.name AS nom, n.inchikey AS cle
                        ORDER BY n.name LIMIT 1
                    """).single()
                if ligne:
                    molecule_nom, molecule_cle = ligne['nom'], ligne['cle']
        except Exception as err:
            print(f"[A PROPOS] Neo4j : {err}")

    return render_template('a_propos.html',
                           lang=langue_demandee(),
                           fiches=fiches,
                           interactions=interactions,
                           substances=substances,
                           structures=structures,
                           molecule_nom=molecule_nom,
                           molecule_cle=molecule_cle,
                           **relever_architecture())


@app.route('/api/dashboard/data', methods=['GET'])
def get_dashboard_data():
    """Endpoint unifié pour le dashboard - agrège les vraies données MongoDB et Neo4j"""
    mongo_data = {
        'medicines_count': 0,
        'drugbank_count': 0,
        'types_count': 0,
        'labs_count': 0,
        'type_distribution': {},
        'top_labs': {}
    }
    
    # 1. Données MongoDB
    try:
        if db is not None and collection is not None:
            # `medicines_count` compte les médicaments du catalogue, et rien
            # d'autre. Il y était ajouté le nombre de documents DRUGBANKS —
            # 1 014 328 fiches d'interaction, qui ne sont pas des médicaments —
            # et la carte de tête du tableau de bord annonçait ainsi
            # **1 027 922 médicaments pour 13 594 réels**, un facteur 75.
            mongo_data['medicines_count'] = collection.count_documents({})
            mongo_data['drugbank_count'] = 0
            try:
                if 'DRUGBANKS' in db.list_collection_names():
                    mongo_data['drugbank_count'] = db['DRUGBANKS'].count_documents({})
            except Exception as e:
                print(f"[DASHBOARD] Erreur DRUGBANKS: {e}")

            # Nombres réels de types et de laboratoires. Les cartes comptaient
            # jusqu'ici les clés des palmarès ci-dessous, lesquels portent un
            # `$limit: 10` : elles affichaient donc « 10 » quels que soient les
            # 56 types et 1 308 laboratoires du catalogue. Un palmarès des dix
            # premiers ne dit pas combien il y en a.
            try:
                mongo_data['types_count'] = len(collection.distinct('type_medicament'))
                mongo_data['labs_count'] = len(
                    collection.distinct('medicine_details.laboratoire'))
            except Exception as e:
                print(f"[DASHBOARD] Erreur distinct: {e}")
            
            # Distribution des types
            type_pipeline = [
                {'$match': {'type_medicament': {'$exists': True, '$ne': None, '$ne': ''}}},
                {'$group': {'_id': '$type_medicament', 'count': {'$sum': 1}}},
                {'$sort': {'count': -1}},
                {'$limit': 10}
            ]
            type_results = list(collection.aggregate(type_pipeline))
            mongo_data['type_distribution'] = {doc['_id']: doc['count'] for doc in type_results if doc['_id']}
            
            # Top laboratoires
            lab_pipeline = [
                {'$match': {'medicine_details.laboratoire': {'$exists': True, '$ne': None, '$ne': ''}}},
                {'$group': {'_id': '$medicine_details.laboratoire', 'count': {'$sum': 1}}},
                {'$sort': {'count': -1}},
                {'$limit': 10}
            ]
            lab_results = list(collection.aggregate(lab_pipeline))
            mongo_data['top_labs'] = {doc['_id']: doc['count'] for doc in lab_results if doc['_id']}
    except Exception as e:
        print(f"[DASHBOARD] Erreur MongoDB stats: {e}")

    # 2. Données Neo4j
    neo4j_data = {
        'total_nodes': 0,
        'total_rels': 0,
        'interactions_count': 0,
        'nodes_by_label': [],
        'rels_by_type': [],
        'top_interactions': []
    }
    
    try:
        if neo4j_connector and neo4j_connector.driver:
            db_name = neo4j_connector.database
            with neo4j_connector.driver.session(database=db_name) as s:
                nodes_res = s.run("MATCH (n) RETURN labels(n) AS lbl, count(*) AS c ORDER BY c DESC").data()
                rels_res = s.run("MATCH ()-[r]->() RETURN type(r) AS t, count(*) AS c ORDER BY c DESC").data()
                # `r.severity` n'existe plus : la gravité a été retirée du
                # graphe (rapport P9-1), la source DrugBank n'en portant
                # aucune. La requête rendait donc une unique catégorie
                # « null » de 538 542 relations, et le tableau de bord en
                # dressait un graphique. On compte désormais les relations
                # elles-mêmes, sans prétendre les hiérarchiser.
                # Sans contrainte de label aux extrémités : Neo4j répond alors
                # depuis ses métadonnées, en 0,07 s contre 0,56 s si l'on
                # précise `(:DrugbankSubstance)` des deux côtés. Le graphe ne
                # porte aucune autre relation de ce type, le compte est le même.
                inter_res = s.run(
                    "MATCH ()-[r:INTERACTS_WITH]->() RETURN count(r) AS c").single()
                
                tot_n = s.run("MATCH (n) RETURN count(n) AS total").single()
                tot_r = s.run("MATCH ()-[r]->() RETURN count(r) AS total").single()
                
                top_int = s.run("""
                    MATCH (d)-[r:INTERACTS_WITH]-()
                    RETURN coalesce(d.title, d.name, d.id, '') AS t, count(r) AS c
                    ORDER BY c DESC LIMIT 10
                """).data()
                if not top_int:
                    top_int = s.run("""
                        MATCH ()-[r:INTERACTS_WITH]-()
                        WITH r, startNode(r) AS d
                        RETURN coalesce(d.title, d.name, d.id, '') AS t, count(r) AS c
                        ORDER BY c DESC LIMIT 10
                    """).data()

                neo4j_data['nodes_by_label'] = nodes_res or []
                neo4j_data['rels_by_type'] = rels_res or []
                neo4j_data['interactions_count'] = inter_res['c'] if inter_res else 0
                neo4j_data['total_nodes'] = tot_n['total'] if tot_n else 0
                neo4j_data['total_rels'] = tot_r['total'] if tot_r else 0
                neo4j_data['top_interactions'] = top_int or []
    except Exception as e:
        print(f"[DASHBOARD] Erreur Neo4j stats: {e}")

    return jsonify({
        'mongodb': mongo_data,
        'neo4j': neo4j_data
    }), 200


@app.route('/api/dashboard/total-medicines', methods=['GET'])
def get_total_medicines():
    """Nombre de médicaments au catalogue."""
    try:
        count = collection.count_documents({}) if collection is not None else 0
    except Exception:
        count = 0
    return jsonify({'count': count}), 200


@app.route('/api/dashboard/monitored-medicines', methods=['GET'])
def get_monitored_medicines():
    """Médicaments sous surveillance renforcée.

    Rendait `243`, écrit en dur. Le catalogue en compte 491.
    """
    try:
        count = collection.count_documents({'surveillance_renforcee': 'Oui'})
    except Exception:
        count = 0
    return jsonify({'count': count}), 200


@app.route('/api/dashboard/active-substances', methods=['GET'])
def get_active_substances():
    """Substances actives distinctes.

    Rendait `2156`, écrit en dur. Le catalogue en porte 3 473, comptées sur
    le libellé normalisé — deux fiches écrivant « Paracétamol » et
    « paracétamol » désignent la même.
    """
    return jsonify({'count': compter_substances_normalisees()}), 200


@app.route('/api/dashboard/medicines-by-atc', methods=['GET'])
def get_medicines_by_atc():
    """Répartition par classe ATC, calculée sur la première lettre du code.

    Rendait une répartition inventée de huit classes. Seules 1 531 fiches
    portent un code ATC : le total renvoyé le dit, pour qu'on ne lise pas
    cette répartition comme celle du catalogue entier.
    """
    libelles = {
        'A': 'A — Voies digestives et métabolisme',
        'B': 'B — Sang et organes hématopoïétiques',
        'C': 'C — Système cardiovasculaire',
        'D': 'D — Dermatologie',
        'G': 'G — Système génito-urinaire',
        'H': 'H — Hormones systémiques',
        'J': 'J — Anti-infectieux',
        'L': 'L — Antinéoplasiques',
        'M': 'M — Système musculo-squelettique',
        'N': 'N — Système nerveux',
        'P': 'P — Antiparasitaires',
        'R': 'R — Système respiratoire',
        'S': 'S — Organes sensoriels',
        'V': 'V — Divers',
    }
    compte = {}
    total = 0
    try:
        for doc in collection.find({'atc_code': {'$nin': [None, '']}},
                                   {'atc_code': 1}):
            code = str(doc.get('atc_code') or '').strip().upper()
            if not code:
                continue
            total += 1
            lettre = code[0]
            compte[lettre] = compte.get(lettre, 0) + 1
    except Exception as e:
        print(f"[DASHBOARD] Erreur ATC: {e}")
    classes = sorted(
        ({'name': libelles.get(k, f'{k} — classe inconnue'), 'count': v}
         for k, v in compte.items()),
        key=lambda x: -x['count'])
    return jsonify({'classes': classes, 'total_avec_code': total,
                    'total_catalogue': collection.count_documents({})}), 200


# ─── Routes de pharmacovigilance et de ruptures : retirées ────────────
#
# Neuf routes rendaient ici des chiffres entièrement inventés, présentés
# comme des données : 45 832 déclarations d'effets indésirables par an, une
# évolution sur six ans, un palmarès des dix médicaments les plus déclarés,
# une répartition « 18 % graves / 34 % modérés / 48 % légers », 287 ruptures
# de stock, leur chronologie et leur palmarès.
#
# Ces données n'existent nulle part dans ce projet. Ni MongoDB ni Neo4j ne
# portent la moindre déclaration de pharmacovigilance ou de rupture
# d'approvisionnement, et aucun calcul ne pouvait les produire. Aucune page
# ne les consommait — mais elles restaient servies sur HTTP, prêtes à être
# lues comme des faits.
#
# La répartition de gravité est le cas le plus net : c'est exactement ce que
# le rapport P9-1 avait retiré du graphe d'interactions, faute de source. La
# réintroduire par une route de tableau de bord aurait annulé cette
# correction.
#
# Les rétablir demanderait une source réelle — l'ANSM publie les données de
# pharmacovigilance et les ruptures d'approvisionnement — et un import, comme
# pour l'EMA. C'est un travail, pas une constante.


@app.route('/api/translate/batch', methods=['POST'])
def translate_batch():
    try:
        payload = request.get_json(force=True) or {}
        texts = payload.get('texts', [])
        target = payload.get('target', 'en')
        source = payload.get('source', 'fr')
        if not texts or target == source:
            return jsonify({'success': True, 'translations': texts})
        from deep_translator import GoogleTranslator
        gt = GoogleTranslator(source=source, target=target)
        translations = []
        for t in texts:
            try:
                translations.append(gt.translate(t) if t else t)
            except Exception:
                translations.append(t)
        return jsonify({'success': True, 'translations': translations})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

if __name__ == '__main__':
    # Initialiser la base de données
    init_db(app)
    
    # Initialiser le système d'utilisateurs
    users.init_users(app)  # Maintenant users est correctement défini
    
    app.config['TEMPLATES_AUTO_RELOAD'] = True
    app.run(host='0.0.0.0', port=5000, debug=True)

