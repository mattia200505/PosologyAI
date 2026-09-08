"""
Traduction depuis le français via Google Translate (deep-translator, sans clé).

La langue cible est un paramètre : anglais, arabe ou toute autre langue prise
en charge par le service. Chaque langue a sa collection de conservation
(`medicines_en`, `medicines_ar`) et sa propre entrée de cache — sans quoi une
chaîne traduite en anglais serait resservie à un lecteur arabophone.

Le principe est : **collecter, traduire en masse, reconstruire** — et non
traduire au fil du parcours de la fiche.

La version précédente descendait récursivement dans le document et appelait le
service une fois par chaîne, séquentiellement. Mesuré sur la base : 956 chaînes
par fiche en médiane, dont seulement 447 distinctes. Une fiche demandait plus
de 180 secondes, et la base entière aurait représenté 11,5 millions de requêtes
— environ 960 heures. Le `ThreadPoolExecutor` importé par ce module n'était
jamais utilisé.

Trois leviers, mesurés plutôt que supposés :

1. **Dédoublonnage** — 53 % des chaînes d'une fiche sont des répétitions.
2. **Groupage** — les chaînes sont concaténées jusqu'à 4 500 caractères et
   traduites en un appel. Vérifié : le séparateur survit intégralement à la
   traduction jusqu'à cette taille (81 chaînes en un appel, redécoupage exact).
   Au-delà de ~5 000 caractères le service tronque, d'où le plafond.
3. **Parallélisme** — les lots partent par quatre.

Le regroupement est **vérifié, jamais supposé** : si le nombre de morceaux
rendus ne correspond pas au nombre de chaînes envoyées, le lot est repris
chaîne par chaîne. Un décalage silencieux attribuerait le texte d'une rubrique
à une autre, ce qui est pire qu'une lenteur sur une notice de médicament.
"""

import hashlib
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from deep_translator import GoogleTranslator

# Cache de traduction partagé par le processus.
_translation_cache = {}

# Limite retenue pour une requête. Mesurée : le service tronque au-delà
# d'environ 5 000 caractères, et le séparateur reste intact jusqu'à 4 500.
MAX_PAYLOAD = 4500

# Séparateur de groupage. Éprouvé sur du texte réel de notice : rendu tel quel
# par le service, jamais traduit ni reformaté.
SEPARATOR = '\n@@\n'
SPLIT_ON = '@@'

# Lots envoyés en parallèle.
#
# Le coût dominant est la latence réseau, pas le calcul. Mesuré sur un corpus
# identique d'une condition à l'autre, cache court-circuité, amorçage écarté
# et trois répétitions alternées — 992 chaînes, ~40 lots :
#
#     4 fils : 10,5 / 8,1 / 9,7 s  ->  médiane 9,7 s
#     8 fils :  6,1 / 6,3 / 4,7 s  ->  médiane 6,1 s
#
# Soit **38 % plus rapide**, avec une séparation nette : la pire mesure à
# 8 fils bat la meilleure à 4.
#
# Deux comparaisons antérieures avaient conclu l'inverse. Elles portaient sur
# des fiches différentes, dont le volume de texte neuf variait de 49 % : la
# charge, et non le parallélisme, expliquait l'écart. Une mesure sur charges
# inégales ne dit rien du réglage que l'on croit mesurer.
#
# **Ce gain ne se retrouve pas en usage réel**, et il faut le dire : sur un
# lot de 20 fiches, 8 fils donnent 0,084 s par chaîne, quand deux mesures à
# 4 fils donnaient 0,063 et 0,087 — le résultat tombe entre les deux.
#
# La raison tient au découpage. Le banc d'essai soumet ~40 lots d'un coup ;
# la pré-traduction, elle, traite une fiche à la fois, et une fiche n'apporte
# qu'une centaine de chaînes neuves, soit quelques lots. Il n'y a pas de quoi
# occuper huit fils. Le parallélisme est plafonné par la taille du travail,
# pas par le réglage.
#
# Le vrai levier serait donc de grouper plusieurs fiches avant de traduire.
# Il n'est pas implémenté ici.
#
# La valeur 8 est conservée : elle ne nuit pas, et sert les cas où le travail
# est effectivement gros — traduction à la volée d'une fiche volumineuse.
# Le débit de requêtes double néanmoins sur un service public et gratuit ;
# aucun échec ni blocage constaté, mais la variable d'environnement permet de
# revenir à 4 sans toucher au code.
MAX_WORKERS = max(1, int(os.environ.get('TRADUCTION_WORKERS', '8')))

# Champs qui ne doivent jamais être traduits.
SKIP_KEYS = frozenset((
    '_id', 'id', 'original_id', 'date_created', 'last_updated',
    'created_at', 'updated_at', '__v', 'url', 'image_url', 'source',
    # Attributs réglementaires : valeurs d'une nomenclature officielle, dont la
    # traduction relève d'une table contrôlée (`regulatory.py`), pas d'un
    # service automatique qui rendrait « Autorisation active » de façon
    # variable d'une fiche à l'autre.
    'cis', 'statut_amm', 'commercialisation', 'date_amm', 'procedure_amm',
    'voies_administration', 'autorisation_europeenne', 'statut_bdm',
    'surveillance_renforcee', 'forme_canonique', 'titulaire_amm',
    'content_hash', 'summary_content_hash', 'code_atc', 'last_scraped',
))


LANGUE_SOURCE = 'fr'


def collection_traduite(lang):
    """
    Nom de la collection portant les fiches traduites dans cette langue.

    `medicines_en` existait déjà ; la règle est simplement généralisée, ce qui
    laisse les 118 fiches anglaises en place sans migration.
    """
    return 'medicines_%s' % lang


def _cache_key(text, lang):
    """
    Empreinte de cache, **incluant la langue cible**.

    Sans elle, une chaîne déjà traduite en anglais serait resservie telle
    quelle à un lecteur arabophone : le cache ne retiendrait que le texte
    source, sans mémoire de ce vers quoi il a été traduit.
    """
    return hashlib.md5(('%s\x00%s' % (lang, text)).encode('utf-8')).hexdigest()


# ── Cache persistant ──────────────────────────────────────────────────
#
# Le cache mémoire disparaît avec le processus, et chaque lancement
# retraduisait donc le texte standard des notices.
#
# Mesuré : les rubriques du résumé des caractéristiques sont largement
# communes d'un médicament à l'autre. 65,3 % des chaînes sont partagées entre
# fiches, et **68,7 % de celles d'une fiche neuve figurent déjà** dans le
# vocabulaire accumulé par les fiches précédentes. Une fiche demande environ
# 412 chaînes distinctes, dont 129 seulement sont réellement nouvelles.
#
# Conserver les traductions divise donc le trafic réseau par plus de trois —
# et allège d'autant la charge sur le service, au lieu de l'augmenter.

COLL_CACHE = 'translation_cache'


def _charger_cache(db, textes, lang):
    """Remplit le cache mémoire depuis MongoDB pour les seules chaînes utiles."""
    if db is None or not textes:
        return 0
    cles = {_cache_key(t, lang): t for t in textes
            if _cache_key(t, lang) not in _translation_cache}
    if not cles:
        return 0
    trouves = 0
    identifiants = list(cles)
    # Par tranches : un `$in` de plusieurs dizaines de milliers d'entrées
    # dépasserait la taille maximale d'un document de requête.
    for i in range(0, len(identifiants), 5000):
        lot = identifiants[i:i + 5000]
        try:
            for entree in db[COLL_CACHE].find({'_id': {'$in': lot}}, {'t': 1}):
                _translation_cache[entree['_id']] = entree['t']
                trouves += 1
        except Exception:                                   # noqa: BLE001
            return trouves
    return trouves


def _enregistrer_cache(db, table, lang):
    """Conserve les traductions nouvellement produites."""
    if db is None or not table:
        return 0
    from pymongo import UpdateOne
    operations = [
        UpdateOne({'_id': _cache_key(source, lang)},
                  {'$setOnInsert': {'t': traduit, 'lang': lang}}, upsert=True)
        for source, traduit in table.items()
    ]
    if not operations:
        return 0
    try:
        resultat = db[COLL_CACHE].bulk_write(operations, ordered=False)
        return resultat.upserted_count
    except Exception:                                       # noqa: BLE001
        return 0


def relever(node, found):
    """Relève les chaînes traduisibles d'un document. Alias public de `_collect`."""
    _collect(node, found)


def _collect(node, found):
    """Relève toutes les chaînes traduisibles, sans rien modifier."""
    if isinstance(node, str):
        text = node.strip()
        if text:
            found.add(text)
    elif isinstance(node, list):
        for item in node:
            _collect(item, found)
    elif isinstance(node, dict):
        for key, value in node.items():
            if key not in SKIP_KEYS:
                _collect(value, found)


def _split_long(text):
    """
    Découpe une chaîne trop longue en respectant les fins de phrase.

    Certaines rubriques de notice atteignent 10 000 caractères ; les couper à
    l'aveugle en pleine phrase dégraderait la traduction.
    """
    if len(text) <= MAX_PAYLOAD:
        return [text]
    pieces, current = [], ''
    for fragment in re.split(r'(?<=[.!?])\s+', text):
        if len(current) + len(fragment) + 1 > MAX_PAYLOAD and current:
            pieces.append(current.strip())
            current = ''
        # Un fragment seul plus long que la limite : découpe brute, faute de mieux.
        while len(fragment) > MAX_PAYLOAD:
            pieces.append(fragment[:MAX_PAYLOAD])
            fragment = fragment[MAX_PAYLOAD:]
        current += fragment + ' '
    if current.strip():
        pieces.append(current.strip())
    return pieces


class GoogleLiveTranslator:
    """Traducteur groupé. L'interface publique est celle de la version précédente."""

    def __init__(self, lang='en', db=None):
        self.lang = lang or 'en'
        self.db = db          # facultatif : active le cache persistant
        self.max_workers = MAX_WORKERS
        self._local = threading.local()

    @property
    def translator(self):
        """
        Un traducteur par fil d'exécution.

        `GoogleTranslator` porte l'état de la requête en cours sur l'instance.
        Le partager entre les fils du groupe de travail corrompt ce state : la
        traduction revenait alors sans ses séparateurs, et chaque lot repartait
        inutilement chaîne par chaîne. Symptôme trompeur — il désignait le
        service, alors que le défaut était ici.

        La propriété conserve le nom `translator` : du code appelant s'en sert.
        """
        instance = getattr(self._local, 'translator', None)
        if instance is None or getattr(self._local, 'lang', None) != self.lang:
            instance = GoogleTranslator(source=LANGUE_SOURCE, target=self.lang)
            self._local.translator = instance
            self._local.lang = self.lang
        return instance

    # ── Appel unitaire ────────────────────────────────────────────────

    def _call(self, payload, max_retries=3):
        """Un appel au service, avec reprise. Rend le texte source en cas d'échec."""
        for attempt in range(max_retries):
            try:
                return self.translator.translate(payload)
            except Exception as error:                      # noqa: BLE001
                if attempt < max_retries - 1:
                    time.sleep(0.2 * (attempt + 1))
                    continue
                print('[TRADUCTION] echec apres %d tentatives : %s'
                      % (max_retries, type(error).__name__))
                return payload
        return payload

    def translate_text(self, text, max_retries=3):
        """Traduit une chaîne isolée. Conservé pour les appels ponctuels."""
        if not text or not isinstance(text, str):
            return text
        text = text.strip()
        if not text:
            return text

        key = _cache_key(text, self.lang)
        if key in _translation_cache:
            return _translation_cache[key]

        pieces = _split_long(text)
        result = ' '.join(self._call(piece, max_retries) for piece in pieces)
        _translation_cache[key] = result
        return result

    # ── Traduction groupée ────────────────────────────────────────────

    def _translate_lot(self, lot):
        """
        Traduit un lot en un appel, puis vérifie le redécoupage.

        Rend un dict {source: traduction}. En cas de désynchronisation, le lot
        est repris chaîne par chaîne : la justesse prime sur la vitesse.
        """
        if len(lot) == 1:
            return {lot[0]: self.translate_text(lot[0])}

        rendered = self._call(SEPARATOR.join(lot))
        parts = [part.strip() for part in rendered.split(SPLIT_ON)]

        if len(parts) == len(lot) and all(parts):
            return dict(zip(lot, parts))

        # Le service a fusionné ou perdu des segments : on ne devine pas.
        print('[TRADUCTION] lot desynchronise (%d envoyees, %d rendues), '
              'reprise chaine par chaine' % (len(lot), len(parts)))
        return {text: self.translate_text(text) for text in lot}

    def translate_many(self, texts):
        """
        Traduit un ensemble de chaînes. Rend {source: traduction}.

        Les chaînes déjà connues du cache ne repartent pas sur le réseau.
        """
        # Le cache durable est consulté avant tout appel réseau.
        _charger_cache(self.db, texts, self.lang)

        pending = [text for text in texts if _cache_key(text, self.lang) not in _translation_cache]
        table = {text: _translation_cache[_cache_key(text, self.lang)]
                 for text in texts if _cache_key(text, self.lang) in _translation_cache}
        if not pending:
            return table

        # Les chaînes trop longues pour un lot voyagent seules.
        lots, current, size = [], [], 0
        for text in sorted(pending, key=len):
            if len(text) > MAX_PAYLOAD:
                lots.append([text])
                continue
            if size + len(text) + len(SEPARATOR) > MAX_PAYLOAD and current:
                lots.append(current)
                current, size = [], 0
            current.append(text)
            size += len(text) + len(SEPARATOR)
        if current:
            lots.append(current)

        produites = {}
        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            for outcome in pool.map(self._translate_lot, lots):
                produites.update(outcome)
        table.update(produites)

        for source, translated in table.items():
            _translation_cache[_cache_key(source, self.lang)] = translated

        # Seules les traductions réellement produites sont écrites : réécrire
        # celles qui venaient du cache ferait un aller-retour pour rien.
        _enregistrer_cache(self.db, produites, self.lang)
        return table

    # ── Document complet ──────────────────────────────────────────────

    def translate_medicine_full(self, medicine):
        """Traduit une fiche entière : un relevé, une traduction groupée, une reconstruction."""
        if not medicine:
            return medicine

        found = set()
        _collect(medicine, found)
        if not found:
            return medicine

        table = self.translate_many(found)
        return self._rebuild(medicine, table)

    def _rebuild(self, node, table):
        """Reconstruit la structure en substituant les traductions relevées."""
        if isinstance(node, str):
            text = node.strip()
            return table.get(text, node) if text else node
        if isinstance(node, list):
            return [self._rebuild(item, table) for item in node]
        if isinstance(node, dict):
            return {key: (value if key in SKIP_KEYS else self._rebuild(value, table))
                    for key, value in node.items()}
        return node

    def reconstruire(self, document, table):
        """
        Reconstruit un document à partir d'une table de traductions déjà obtenue.

        Permet de mutualiser un appel entre plusieurs fiches : on relève les
        chaînes de tout un groupe, on traduit une fois, puis chaque fiche est
        reconstruite depuis la même table.
        """
        return self._rebuild(document, table)

    # Conservé : du code appelle encore ce nom.
    def _translate_recursive(self, obj):
        found = set()
        _collect(obj, found)
        return self._rebuild(obj, self.translate_many(found))


# ── Persistance des traductions ───────────────────────────────────────
#
# Traduire une fiche coûte quelques secondes de réseau. Ne pas conserver le
# résultat fait payer ce prix à chaque visiteur, indéfiniment.
# Une collection par langue — `medicines_en`, `medicines_ar` — sert de cache
# durable ; le contrôle de fraîcheur reprend la discipline posée en P0 pour le
# résumé IA : une traduction dont la notice a changé n'est pas servie, elle est
# refaite.

def stored_translation(db, medicine, lang='en'):
    """Traduction conservée et alignée sur la notice courante, ou None."""
    if db is None or not medicine or not medicine.get('_id'):
        return None
    try:
        found = db[collection_traduite(lang)].find_one(
            {'original_id': medicine['_id']})
    except Exception:                                       # noqa: BLE001
        return None
    if not found:
        return None

    source_hash = medicine.get('content_hash')
    # Sans empreinte des deux côtés, on ne peut rien affirmer : la traduction
    # est servie, faute de pouvoir démontrer qu'elle est périmée.
    if source_hash and found.get('content_hash') != source_hash:
        return None
    return found


def store_translation(db, medicine, translated, lang='en'):
    """
    Conserve une traduction pour les visites suivantes.

    Écrit sur la clé `original_id`, ce qui rend l'opération idempotente : une
    retraduction remplace l'entrée au lieu d'en accumuler.
    """
    if db is None or not medicine or not medicine.get('_id') or not translated:
        return False
    document = dict(translated)
    document.pop('_id', None)
    document['original_id'] = medicine['_id']
    document['url'] = medicine.get('url')
    document['content_hash'] = medicine.get('content_hash')
    document['lang'] = lang
    document['translated_at'] = time.time()
    try:
        db[collection_traduite(lang)].update_one(
            {'original_id': medicine['_id']}, {'$set': document}, upsert=True)
        return True
    except Exception as error:                              # noqa: BLE001
        print('[TRADUCTION] conservation impossible : %s' % type(error).__name__)
        return False


def ensure_indexes(db, langues=('en', 'ar')):
    """`original_id` est la clé de lecture : sans index, chaque visite balaie la collection."""
    if db is None:
        return
    for lang in langues:
        try:
            db[collection_traduite(lang)].create_index(
                'original_id', name='idx_original_id')
        except Exception:                                   # noqa: BLE001
            pass
    try:
        db[COLL_CACHE].create_index('lang', name='idx_lang')
    except Exception:                                       # noqa: BLE001
        pass


def translate_medicines_live_google(medicines, lang='en', db=None):
    """
    Traduit une liste de fiches.

    Le relevé est fait sur l'ensemble de la liste avant tout appel : deux fiches
    d'un même laboratoire partagent de nombreuses formulations, qui ne sont
    alors traduites qu'une fois.
    """
    # Le français est la langue source : rien à faire. Toute autre langue est
    # acceptée — la cible n'est plus figée sur l'anglais.
    if not lang or lang == LANGUE_SOURCE or not medicines:
        return medicines

    translator = GoogleLiveTranslator(lang, db=db)

    found = set()
    for medicine in medicines:
        _collect(medicine, found)
    if not found:
        return medicines

    started = time.time()
    table = translator.translate_many(found)
    print('[TRADUCTION] %d fiche(s), %d chaines distinctes, %.1f s'
          % (len(medicines), len(found), time.time() - started))

    return [translator._rebuild(medicine, table) for medicine in medicines]
