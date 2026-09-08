"""
Matching batch entre medicines (FR) et DRUGBANKS (EN)
Stratégie : DCI (INN) prioritaires, score 0-100, transparence, sécurité > couverture
"""

import re
import time
import sys
from collections import defaultdict
from pymongo import MongoClient, UpdateOne
from rapidfuzz import fuzz, process
from scripts.normalize_shared import normalize, normalize_dci, reduce_salt

MONGO_URI = "mongodb://localhost:27017/"
MONGO_DB = "medicsearch"
BATCH_SIZE = 500

# Seuil de sécurité : aucun match en-dessous n'est conservé
MIN_CONFIDENCE_SAFE = 80  # 0-100

client = MongoClient(MONGO_URI)
db = client[MONGO_DB]


# ═══════════════════════════════════════════════
# GARDE-FOU DU MATCHING FLOU
# ═══════════════════════════════════════════════

# Mots qui nomment une famille chimique sans désigner la molécule : deux acides
# différents partagent « acide », deux carbonates partagent « carbonate », et
# `fuzz.ratio` compte ces caractères communs. Ramenés ici à une classe unique
# quelle que soit la langue, puisque c'est leur partage qu'il faut détecter.
_FAMILLE_CANON = {}
for _classe, _formes in {
    'ACID': ('acide', 'acides', 'acid', 'acido', 'acidum', 'saeure'),
    'CARBONATE': ('carbonate', 'carbonato'),
    'CHLORHYDRATE': ('chlorhydrate', 'hydrochloride', 'hidrocloruro'),
    'SULFATE': ('sulfate', 'sulphate', 'sulfato'),
    'CITRATE': ('citrate', 'citrato'),
    'TARTRATE': ('tartrate', 'tartrato'),
    'MALEATE': ('maleate', 'maleato'),
    'FUMARATE': ('fumarate', 'fumarato'),
    'SUCCINATE': ('succinate', 'succinato'),
    'ACETATE': ('acetate', 'acetato'),
    'PHOSPHATE': ('phosphate', 'fosfato'),
    'NITRATE': ('nitrate', 'nitrato'),
    'BROMURE': ('bromure', 'bromide', 'bromhydrate', 'bromuro'),
    'CHLORURE': ('chlorure', 'chloride', 'cloruro'),
    'OXYDE': ('oxyde', 'oxide', 'oxido', 'hydroxyde', 'hydroxide'),
}.items():
    for _f in _formes:
        _FAMILLE_CANON[_f] = _classe

# Mots de liaison et précisions galéniques : toujours retirés de la partie
# distinctive, mais leur présence ne déclenche pas le contrôle — ils ne
# désignent aucune famille chimique.
_LIAISON = frozenset({
    'de', 'du', 'des', 'd', 'la', 'le', 'les', 'of', 'and', 'et', 'y',
    'sodique', 'sodium', 'potassique', 'potassium', 'calcique',
    'enrobe', 'enrobee', 'anhydre', 'anhydrous', 'monohydrate', 'dihydrate',
    'trihydrate', 'hydrate', 'micronise', 'micronisee', 'purifie', 'purifiee',
})

# Seuil du contrôle discriminant. Il ne juge pas la ressemblance globale mais
# le seul résidu, une fois le mot de famille retiré — résidu qui compare
# souvent deux langues, d'où un seuil distinct de celui du matching.
#
# Calibré sur les 502 appariements flous du catalogue. Le contrôle ne concerne
# que les 47 où les deux noms partagent une famille chimique ; les deux
# populations y sont séparées :
#
#   38 appariements erronés   : 57,1 → 83,3  (« zolédronique » / « alendronique »)
#    9 appariements corrects  : 83,9 → 100,0 (« aminolévulinique » / « aminolevulinico »)
#
# L'écart est mince — 0,6 point. Le seuil reste donc aligné sur celui du
# matching plutôt que glissé dans cet intervalle : régler une constante sur
# 0,6 point mesuré sur 47 observations serait du surajustement. Le prix est
# connu et nommé : EFFALA (« acide 5-aminolévulinique », 83,9) perd son
# appariement. Il se récupère en ajoutant la DCI au dictionnaire FR→EN, pas en
# desserrant un contrôle de sécurité.
MIN_DISCRIMINANT = 85

# Locants : « 5-aminolévulinique » désigne la même molécule qu'« aminolevulinic ».
# Le préfixe positionnel ne distingue pas deux molécules ici, il décale la
# comparaison caractère à caractère.
_RE_LOCANT = re.compile(r'^(?:\d+|[nrsoz]|alpha|beta|gamma|cis|trans)-')


def _decompose(nom: str):
    """Sépare un nom entre ses familles chimiques et sa partie distinctive."""
    familles, toks = set(), []
    for t in normalize_dci(nom).split():
        t = _RE_LOCANT.sub('', t)
        if not t:
            continue
        if t in _FAMILLE_CANON:
            familles.add(_FAMILLE_CANON[t])
        elif t not in _LIAISON:
            toks.append(t)
    return familles, ' '.join(toks)


def _partie_distinctive(nom: str) -> str:
    return _decompose(nom)[1]


def _fuzzy_discriminant(candidat: str, trouve: str, seuil: int) -> bool:
    """Le score flou tient-il encore une fois le mot de famille retiré ?

    Sans ce contrôle, `fuzz.ratio` à 85 apparie « acide salicylique » à
    « acide acétylsalicylique » (85,0), « acide zolédronique » à « acide
    alendronique » (88,9) et « carbonate de lithium » à « carbonate de
    calcium » (85,0) : le mot de famille commun fournit à lui seul l'essentiel
    des caractères identiques. Sur la partie distinctive, ces mêmes paires
    tombent à 78,6, 83,3 et 57,1 — toutes sous le seuil.

    Mesuré : la règle `dci_fuzzy_medium` produisait 22,5 % de faux positifs
    (40 sur 178), soit la totalité des appariements erronés du catalogue.

    Le contrôle ne s'applique **que si les deux noms partagent une famille**.
    C'est ce partage qui fausse le score ; ailleurs il n'y a rien à corriger.
    Sans cette condition, le garde rejetterait « aminolévulinate de méthyle »
    apparié au synonyme espagnol « aminolevulinato de metilo » — même molécule,
    orthographe d'une autre langue.
    """
    fam_a, a = _decompose(candidat)
    fam_b, b = _decompose(trouve)
    if not (fam_a & fam_b):
        return True
    if not a or not b:
        # Le nom n'était qu'un mot de famille : rien à discriminer, on s'en
        # remet au score initial plutôt que de rejeter à l'aveugle.
        return True
    # `token_set_ratio` en complément : le français et l'anglais inversent
    # l'ordre des mots (« aminolévulinate de méthyle » / « methyl
    # aminolevulinate »), ce que `ratio`, sensible à l'ordre, sanctionne à tort.
    return max(fuzz.ratio(a, b), fuzz.token_set_ratio(a, b)) >= seuil


# ═══════════════════════════════════════════════
# EXTRACTION DES SUBSTANCES (côté FR)
# ═══════════════════════════════════════════════

SUBSTANCE_SOURCE_ORDER = [
    'medicine_details.substances_actives',  # priorité 1 : DCI explicite
    'composition',                           # priorité 2 : composition
    'title',                                 # priorité 3 : nom commercial
]


# Dilutions homéopathiques : « Arnica montana 3DH », « Carbo vegetabilis 5 CH ».
_RE_DILUTION = re.compile(r'\b\d+\s*(?:DH|CH|K|LM)\b', re.I)


def _est_homeopathique(medicine: dict) -> bool:
    """Toutes les substances déclarées portent-elles une dilution ?

    La condition est volontairement stricte — *toutes*, non *au moins une* :
    une spécialité qui associerait une souche diluée à un principe actif
    dosé garde son appariement sur ce dernier.
    """
    details = medicine.get('medicine_details', {}) or {}
    substances = details.get('substances_actives', []) or []
    if isinstance(substances, str):
        substances = [substances]
    substances = [s for s in substances if s and s.strip()]
    if not substances:
        return False
    return all(_RE_DILUTION.search(s) for s in substances)


def extract_substances(medicine: dict) -> list:
    """
    Extrait TOUTES les substances candidates depuis un document medicines.
    Retourne une liste de dicts : {text, source, priority}
    priorité 0 = DCI (fiable), 1 = composition, 2 = nom commercial
    """
    candidates = []

    # Priorité 0 : substances_actives (DCI, le plus fiable)
    details = medicine.get('medicine_details', {}) or {}
    substances_list = details.get('substances_actives', []) or []
    if isinstance(substances_list, str):
        substances_list = [substances_list]
    for s in substances_list:
        if s and len(s.strip()) > 2:
            candidates.append({
                'text': normalize_dci(s),
                'original': s.strip(),
                'source': 'substance_active',
                'priority': 0,
            })

    # Priorité 1 : composition
    comp = medicine.get('composition', '') or ''
    if comp and comp != 'Non spécifié':
        parts = re.split(r'[;,]+', comp)
        for p in parts:
            p = p.strip()
            if p and len(p) > 2:
                candidates.append({
                    'text': normalize_dci(p),
                    'original': p,
                    'source': 'composition',
                    'priority': 1,
                })

    # Priorité 2 : titre (nom commercial)
    title = medicine.get('title', '')
    if title:
        candidates.append({
            'text': normalize_dci(title),
            'original': title,
            'source': 'title',
            'priority': 2,
        })

    return candidates


# ═══════════════════════════════════════════════
# CONSTRUCTION DE L'INDEX DRUGBANK
# ═══════════════════════════════════════════════

def build_drugbank_index() -> dict:
    """
    Construit un index DrugBank pour matching rapide.

    Structure :
    {
        'by_dci': { 'paracetamol': [('DB00316', 'name'), ...] },
        'by_synonym': { 'acetaminophen': [('DB00316', 'synonym'), ...] },
        'fuzzy_names': [ ('paracetamol', 'DB00316'), ('acetaminophen', 'DB00316'), ... ],
    }
    """
    print("🔍 Construction de l'index DrugBank...")
    index = {
        'by_dci': defaultdict(list),
        'by_synonym': defaultdict(list),
        # Index préfixé pour fuzzy : { 'par': [('paracetamol', 'DB00316'), ...] }
        'fuzzy_prefix': defaultdict(list),
    }

    total = db.DRUGBANKS.count_documents({})

    cursor = db.DRUGBANKS.find(
        {},
        {'drugbank_id': 1, 'name': 1, 'synonyms': 1}
    ).batch_size(2000)

    for doc in cursor:
        db_id = doc.get('drugbank_id')
        if not db_id:
            continue

        # Nom DCI principal → by_dci + fuzzy_prefix
        name = doc.get('name', '')
        name_norm = normalize_dci(name)
        if name_norm and len(name_norm) >= 3:
            index['by_dci'][name_norm].append({
                'drugbank_id': db_id,
                'source': 'name',
                'original': name,
            })
            prefix = name_norm[:3]
            index['fuzzy_prefix'][prefix].append((name_norm, db_id))

        # Synonymes → by_synonym + fuzzy_prefix
        for syn in (doc.get('synonyms', []) or []):
            if not syn or not syn.strip():
                continue
            syn_norm = normalize_dci(syn)
            if syn_norm and len(syn_norm) >= 3:
                index['by_synonym'][syn_norm].append({
                    'drugbank_id': db_id,
                    'source': 'synonym',
                    'original': syn,
                })
                prefix = syn_norm[:3]
                index['fuzzy_prefix'][prefix].append((syn_norm, db_id))

    print(f"   DCI uniques : {len(index['by_dci'])}")
    print(f"   Synonymes uniques : {len(index['by_synonym'])}")
    print(f"   Groupes préfixés (fuzzy) : {len(index['fuzzy_prefix'])}")
    return index


# ═══════════════════════════════════════════════
# MATCHING DCI / EN → FR
# ═══════════════════════════════════════════════

# Dictionnaire de correspondance FR → EN pour les DCI courantes
DCI_FR_EN = {
    'paracetamol': 'acetaminophen',
    'paracétamol': 'acetaminophen',
    'ibuprofene': 'ibuprofen',
    'ibuprofène': 'ibuprofen',
    'amoxicilline': 'amoxicillin',
    'metformine': 'metformin',
    'cetirizine': 'cetirizine',
    'cétirizine': 'cetirizine',
    'loratadine': 'loratadine',
    'domperidone': 'domperidone',
    'dompéridone': 'domperidone',
    'metoclopramide': 'metoclopramide',
    'métoclopramide': 'metoclopramide',
    'omeprazole': 'omeprazole',
    'oméprazole': 'omeprazole',
    'salbutamol': 'albuterol',
    'furosemide': 'furosemide',
    'furosémide': 'furosemide',
    'prednisolone': 'prednisolone',
    'prednisone': 'prednisone',
    'codeine': 'codeine',
    'codéine': 'codeine',
    'morphine': 'morphine',
    'tramadol': 'tramadol',
    'aspirine': 'aspirin',
    'warfarine': 'warfarin',
    'clopidogrel': 'clopidogrel',
    'atorvastatine': 'atorvastatin',
    'simvastatine': 'simvastatin',
    'levothyroxine': 'levothyroxine',
    'lévothyroxine': 'levothyroxine',
    'hydrochlorothiazide': 'hydrochlorothiazide',
    'ramipril': 'ramipril',
    'losartan': 'losartan',
    'bisoprolol': 'bisoprolol',

    # ── Ajoutées le 12/08/2026, à l'issue de l'audit P9-4 ──────────────
    #
    # Ces DCI n'étaient pas traduites : le matching tombait dans la bande
    # floue et les appariait à une molécule voisine de la même famille
    # chimique — l'acide salicylique à l'acide acétylsalicylique, l'acide
    # zolédronique à l'acide alendronique, le carbonate de lithium au
    # carbonate de calcium. Le garde-fou discriminant rejette désormais ces
    # rapprochements ; ces entrées leur substituent le bon appariement plutôt
    # que de laisser un trou.
    #
    # Chaque cible a été vérifiée : elle résout vers un identifiant unique
    # dans `index['by_dci']`.
    'acide salicylique': 'salicylic acid',            # DB00936, ≠ DB00945 aspirine
    'acide zoledronique': 'zoledronic acid',          # DB00399, ≠ DB00630 alendronique
    'acide gadoterique': 'gadoteric acid',            # DB09132, ≠ DB00743 gadobénique
    'acide pentetique': 'pentetic acid',              # DB14007, ≠ DB00789 gadopentétique
    'acide borique': 'boric acid',                    # DB11326, ≠ DB01942 formique
    'acide levofolinique': 'levoleucovorin',          # DB11596, ≠ DB00650 leucovorine
    'acide 5-aminolevulinique': 'aminolevulinic acid',  # DB00855
    'carbonate de lithium': 'lithium carbonate',      # DB14509, ≠ DB06724 carbonate de calcium
    'lidocaine chlorhydrate': 'lidocaine',            # DB00281, ≠ DB19083 mescaline
    # `reduce_salt` ne réduit que « chlorhydrate de X », pas « X chlorhydrate ».
    'lidocaine': 'lidocaine',

    # ── Les trente substances les plus fréquentes chez les non-appariés ────
    #
    # Le français inverse l'ordre de l'anglais et nomme souvent la forme
    # salifiée : « dipropionate de béclométasone » pour « beclometasone
    # dipropionate », « losartan potassium » pour « losartan ».
    #
    # **La cible est le principe actif, jamais le contre-ion.** Une génération
    # automatique par position proposait Arginine pour « périndopril
    # arginine », Trometamol pour « fosfomycine trométamol » et Potassium pour
    # « losartan potassium » : le sel plutôt que la molécule. Chaque entrée
    # ci-dessous a donc été relue, et vérifiée comme résolvant vers un
    # identifiant unique.
    'chlorure de sodium': 'sodium chloride',              # DB09153
    'chlorure de potassium': 'potassium chloride',        # DB00761, ≠ potassium seul
    'chlorure de calcium dihydrate': 'calcium chloride',  # DB01164
    'bicarbonate de sodium': 'sodium bicarbonate',        # DB01390
    'diclofenac de diethylamine': 'diclofenac',           # DB00586
    'perindopril tert-butylamine': 'perindopril',         # DB00790
    'perindopril arginine': 'perindopril',                # DB00790, ≠ arginine
    'digluconate de chlorhexidine': 'chlorhexidine',      # DB00878
    'de digluconate de chlorhexidine': 'chlorhexidine',   # variante d'extraction
    'valproate de sodium': 'valproic acid',               # DB00313
    'ciclopirox olamine': 'ciclopirox',                   # DB01188, ≠ olamine
    'estradiol hemihydrate': 'estradiol',                 # DB00783
    'cromoglicate de sodium': 'cromoglicic acid',         # DB01003
    'paroxetine base': 'paroxetine',                      # DB00715
    'fosfomycine trometamol': 'fosfomycin',               # DB00828, ≠ trometamol
    'hydrogenosuccinate de doxylamine': 'doxylamine',     # DB00366
    'succinate de solifenacine': 'solifenacin',           # DB01591
    'bisoprolol fumarate': 'bisoprolol',                  # DB00612
    'losartan potassium': 'losartan',                     # DB00678, ≠ potassium
    'sildenafil citrate': 'sildenafil',                   # DB00203
    'folinate de calcium': 'leucovorin',                  # DB00650, ≠ calcium
    'acetylsalicylate de dl-lysine': 'acetylsalicylic acid',   # DB00945
    'metasulfobenzoate sodique de prednisolone': 'prednisolone',  # DB00860
    'enoxaparine sodique d activite anti-xa': 'enoxaparin',      # DB01225
    'olmesartan medoxomil': 'olmesartan',                 # DB00275
    'alginate de sodium': 'alginic acid',                 # DB13518
    # Formes où l'ester fait partie de la molécule nommée par DrugBank.
    'dipropionate de beclometasone': 'beclometasone dipropionate',         # DB00394
    'dipropionate de beclometasone anhydre': 'beclometasone dipropionate',  # DB00394
    'acetate de cyproterone': 'cyproterone acetate',      # DB04839
    'fumarate de dimethyle': 'dimethyl fumarate',         # DB08908
    'gluconate de manganese': 'manganese gluconate',      # DB11141
    'charbon active': 'activated charcoal',               # DB09278
}


def try_dci_translation(text: str) -> list:
    """
    Essaie de traduire une DCI FR vers EN via le dictionnaire.
    Retourne une liste de formes candidats EN.
    """
    candidates = [text]
    if text in DCI_FR_EN:
        candidates.append(DCI_FR_EN[text])
    return list(set(candidates))


def match_medicine_to_drugbank(medicine: dict, index: dict) -> dict:
    """
    Match un document medicines vers DRUGBANKS.
    Priorité absolue : DCI (substance active) → name DrugBank.
    Retourne un dict transparent avec score, règle, et source.

    Règles de matching (par ordre de priorité décroissante) :
      1. dci_exact      : substance_active = drugbank.name (score 100)
      2. dci_translated : DCI FR → EN via dictionnaire (score 98)
      3. synonym_exact  : substance = drugbank.synonym (score 95)
      4. dci_fuzzy_high : substance ≥ 93% fuzzy du name (score 93-99)
      5. dci_fuzzy_med  : substance ≥ 85% fuzzy du name (score 85-92)
      6. synonym_fuzzy  : titre ≥ 85% fuzzy d'un synonym (score 85-89)

    Seuil de sécurité : < 80 → rejeté (pas de match forcé).
    """
    title = medicine.get('title', '')
    if not title:
        return _no_match('title_missing')

    # Préparations homéopathiques : aucun appariement.
    #
    # « Carbo vegetabilis 5 CH » n'est pas du charbon activé, « Aurum
    # metallicum 30 DH » n'est pas de l'or : au-delà de quelques dilutions il
    # ne reste aucune molécule, et prêter à la préparation le profil
    # d'interactions de sa souche est une affirmation fausse. Mesuré sur le
    # catalogue : 15 préparations appariées, dont COCYNTAL qui affichait les
    # 4 interactions du charbon activé et DIABENE les 20 de l'acide acétique.
    #
    # Le rejet est prononcé **au niveau du médicament**, avant toute autre
    # règle. Se contenter d'ignorer la substance ne suffirait pas : le matching
    # se rabattrait sur le nom commercial, et c'est ainsi que « NicoSan » —
    # souche Tabacum 5 DH — s'appariait à un produit sans rapport.
    if _est_homeopathique(medicine):
        return _no_match('preparation_homeopathique')

    substances = extract_substances(medicine)
    # Trier par priorité (0 = DCI d'abord)
    substances.sort(key=lambda x: x['priority'])

    matches = []  # [{drugbank_id, score, rule, matched_on, source, original_fr}]

    # ── ÉTAPE 1 : Match par DCI (substance_active) ──
    for sub in substances:
        if sub['priority'] > 0:
            continue  # seulement DCI explicite
        dci_norm = sub['text']
        if len(dci_norm) < 3:
            continue

        # 1a. DCI exact (même nom EN → EN)
        for dci_candidate in try_dci_translation(dci_norm):
            if dci_candidate in index['by_dci']:
                for entry in index['by_dci'][dci_candidate]:
                    matches.append({
                        'drugbank_id': entry['drugbank_id'],
                        'score': 100,
                        'rule': 'dci_exact',
                        'matched_on': entry['original'],
                        'source': entry['source'],
                        'original_fr': sub['original'],
                    })

        # 1b. DCI exact par synonyme
        for dci_candidate in try_dci_translation(dci_norm):
            if dci_candidate in index['by_synonym']:
                for entry in index['by_synonym'][dci_candidate]:
                    matches.append({
                        'drugbank_id': entry['drugbank_id'],
                        'score': 98,
                        'rule': 'dci_translated',
                        'matched_on': entry['original'],
                        'source': entry['source'],
                        'original_fr': sub['original'],
                    })

        # 1c. Forme salifiée ou estérifiée réduite à sa molécule.
        #
        # DrugBank nomme la molécule, l'ANSM la forme réellement présente dans
        # le comprimé : « Chlorhydrate de tramadol » contre « tramadol ». La
        # règle n'est tentée qu'après échec des correspondances directes, et
        # `reduce_salt` refuse d'elle-même les réductions abusives — un sel
        # minéral dont le sel est le principe actif reste intact.
        if not matches:
            reduced = reduce_salt(sub['original'])
            if reduced and len(reduced) >= 3:
                # La réduction rend une DCI française ; le dictionnaire FR→EN
                # doit donc s'y appliquer aussi. Sans cela « Warfarine sodique »
                # se réduisait bien en « warfarine », mais la traduction vers
                # « warfarin » n'était jamais tentée et COUMADINE restait non
                # apparié — alors que les deux mécanismes étaient présents.
                #
                # La forme réduite est essayée seule d'abord : la traduction
                # n'intervient qu'à défaut, pour ne rien changer aux
                # appariements que la règle produisait déjà.
                for candidat in (reduced, *[c for c in try_dci_translation(reduced)
                                            if c != reduced]):
                    for source_key, rule_score in (('by_dci', 94), ('by_synonym', 92)):
                        for entry in index[source_key].get(candidat, []):
                            matches.append({
                                'drugbank_id': entry['drugbank_id'],
                                'score': rule_score,
                                'rule': 'dci_sel_reduit',
                                'matched_on': entry['original'],
                                'source': entry['source'],
                                'original_fr': sub['original'],
                            })
                        if matches:
                            break
                    if matches:
                        break

        if matches:
            break  # DCI trouvé, on arrête

    # ── ÉTAPE 2 : Synonym exact sur substance ──
    if not matches:
        for sub in substances:
            for dci_candidate in try_dci_translation(sub['text']):
                if len(dci_candidate) < 3:
                    continue
                # Chercher dans les synonymes DrugBank
                for syn_key, entries in index['by_synonym'].items():
                    if dci_candidate == syn_key:
                        for entry in entries:
                            matches.append({
                                'drugbank_id': entry['drugbank_id'],
                                'score': 95,
                                'rule': 'synonym_exact',
                                'matched_on': entry['original'],
                                'source': entry['source'],
                                'original_fr': sub['original'],
                            })
                        break
            if matches:
                break

    # ── ÉTAPE 3 : Fuzzy DCI (substance vs drugbank.name) — préfixé ──
    if not matches:
        fuzzy_prefix = index['fuzzy_prefix']
        for sub in substances:
            for dci_candidate in try_dci_translation(sub['text']):
                if len(dci_candidate) < 4:
                    continue
                # Ne chercher que dans le groupe de même préfixe (3 premiers caractères)
                prefix = dci_candidate[:3]
                group = fuzzy_prefix.get(prefix, [])
                if not group:
                    # Fallback : essayer le préfixe tronqué
                    for plen in (2, 1):
                        group = fuzzy_prefix.get(dci_candidate[:plen], [])
                        if group:
                            break
                if not group:
                    continue

                result = process.extractOne(
                    dci_candidate,
                    [n for n, _ in group],
                    scorer=fuzz.ratio,
                    score_cutoff=85,
                )
                if result and not _fuzzy_discriminant(dci_candidate, result[0], MIN_DISCRIMINANT):
                    result = None
                if result:
                    best_name, score, _ = result
                    for name_val, db_id in group:
                        if name_val == best_name:
                            rule = 'dci_fuzzy_high' if score >= 93 else 'dci_fuzzy_medium'
                            matches.append({
                                'drugbank_id': db_id,
                                'score': score,
                                'rule': rule,
                                'matched_on': best_name,
                                'source': 'fuzzy_name',
                                'original_fr': sub['original'],
                            })
                            break
            if matches:
                break

    # ── ÉTAPE 4 : Fuzzy titre vs synonymes (préfixé) ──
    if not matches:
        title_norm = normalize_dci(title)
        if len(title_norm) >= 4:
            prefix = title_norm[:3]
            # Collecter les synonymes du même préfixe
            syn_group = defaultdict(list)
            for p_key, entries in index['fuzzy_prefix'].items():
                # Prendre le même préfixe + les préfixes adjacents (1 lettre diff)
                if abs(len(p_key) - len(prefix)) <= 1 and (
                    p_key == prefix or
                    (len(p_key) >= 2 and len(prefix) >= 2 and p_key[:2] == prefix[:2])
                ):
                    for name_val, db_id in entries:
                        syn_group[name_val].append(db_id)

            if syn_group:
                syn_list = list(syn_group.keys())
                result = process.extractOne(
                    title_norm, syn_list,
                    scorer=fuzz.ratio,
                    score_cutoff=85,
                )
                if result and not _fuzzy_discriminant(title_norm, result[0], MIN_DISCRIMINANT):
                    result = None
                if result:
                    best_syn, score, _ = result
                    for db_id in syn_group[best_syn]:
                        matches.append({
                            'drugbank_id': db_id,
                            'score': score,
                            'rule': 'synonym_fuzzy',
                            'matched_on': best_syn,
                            'source': 'fuzzy_synonym',
                            'original_fr': title,
                        })

    # ── FILTRE DE SÉCURITÉ : garder seulement les matchs ≥ 80 ──
    safe_matches = [m for m in matches if m['score'] >= MIN_CONFIDENCE_SAFE]

    if not safe_matches:
        if matches:
            best = max(matches, key=lambda x: x['score'])
            return _no_match(
                f'below_threshold_{best["score"]}',
                detail=f'Meilleur score: {best["score"]}/100 (seuil: {MIN_CONFIDENCE_SAFE})',
            )
        return _no_match('no_match')

    # Dédupliquer par drugbank_id, garder le meilleur score
    seen = {}
    for m in safe_matches:
        db_id = m['drugbank_id']
        if db_id not in seen or m['score'] > seen[db_id]['score']:
            seen[db_id] = m

    best = max(seen.values(), key=lambda x: x['score'])

    return {
        'drugbank_ids': list(seen.keys())[:3],
        'match_confidence': best['score'],
        'match_type': _classify_match_type(best['rule'], best['score']),
        'match_rule': best['rule'],
        'match_score': best['score'],
        'match_source': best['source'],
        'matched_on': best['matched_on'],
        'original_fr': best['original_fr'],
    }


def _classify_match_type(rule: str, score: int) -> str:
    if rule in ('dci_exact',):
        return 'exact'
    elif rule in ('dci_translated', 'synonym_exact'):
        return 'synonym'
    # Réduction déterministe d'un sel à sa molécule : ce n'est ni une
    # correspondance exacte de chaînes, ni une approximation. Le type propre
    # permet de mesurer la règle séparément et de la retirer si besoin.
    elif rule == 'dci_sel_reduit':
        return 'sel_reduit'
    elif rule.startswith('dci_fuzzy') or rule == 'synonym_fuzzy':
        return 'fuzzy'
    return 'fallback'


def _no_match(reason: str, detail: str = '') -> dict:
    result = {
        'drugbank_ids': [],
        'match_confidence': 0,
        'match_type': 'none',
        'match_rule': reason,
        'match_score': 0,
        'match_source': '',
        'matched_on': '',
        'original_fr': '',
    }
    if detail:
        result['match_detail'] = detail
    return result


# ═══════════════════════════════════════════════
# EXÉCUTION DU MATCHING BATCH
# ═══════════════════════════════════════════════

def run_matching(dry_run: bool = False):
    """Exécute le matching batch entre medicines et DRUGBANKS"""
    print("=" * 60)
    print("🚀 MATCHING MEDICINES ↔ DRUGBANKS")
    print("   Fiabilité > Couverture | Seuil minimum: {}%".format(MIN_CONFIDENCE_SAFE))
    print("=" * 60)

    # 0. Indexer DRUGBANKS.drugbank_id si pas déjà fait (indispensable pour la vitesse)
    print("📌 Vérification des index DrugBank...")
    existing_indexes = db.DRUGBANKS.index_information()
    if 'idx_drugbank_id' not in existing_indexes:
        print("   Création de l'index drugbank_id...")
        db.DRUGBANKS.create_index('drugbank_id', name='idx_drugbank_id', background=True)
    else:
        print("   Index drugbank_id déjà présent")

    # 1. Construire l'index DrugBank
    t0 = time.time()
    index = build_drugbank_index()
    print(f"   ⏱  Index construit en {time.time() - t0:.1f}s")

    # 2. Récupérer tous les médicaments
    total_meds = db.medicines.count_documents({})
    print(f"\n📊 {total_meds} médicaments à matcher\n")

    # 3. Matcher par lots
    stats = {
        'total': 0,
        'matched': 0,
        'unmatched': 0,
        'below_threshold': 0,
        'by_type': defaultdict(int),
        'by_rule': defaultdict(int),
        'by_score_bucket': defaultdict(int),
        't_exact': 0.0,
        't_fuzzy': 0.0,
    }

    cursor = db.medicines.find({}, {
        'title': 1, 'composition': 1,
        'medicine_details.substances_actives': 1,
        'classe_therapeutique': 1,
    }).batch_size(500)

    batch_ops = []
    unmatched_list = []

    # Pré-trier les médicaments : d'abord ceux avec substance_active (plus faciles)
    meds_to_match = list(cursor)
    print(f"   📥 {len(meds_to_match)} documents chargés depuis MongoDB, tri en cours...")
    meds_to_match.sort(key=lambda m: 0 if (m.get('medicine_details', {}) or {}).get('substances_actives') else 1)
    print(f"   ✅ Triage terminé, démarrage du matching...")
    sys.stdout.flush()

    PROGRESS_INTERVAL = 10
    print(f"   Démarrage... progression toutes les {PROGRESS_INTERVAL} itérations")
    sys.stdout.flush()

    for medicine in meds_to_match:
        stats['total'] += 1
        med_id = medicine['_id']
        title = medicine.get('title', '')

        # Progression visuelle : un point tous les 5
        if stats['total'] % 5 == 0:
            print('.', end='', flush=True)

        result = match_medicine_to_drugbank(medicine, index)

        enrichment_doc = {
            'medicine_id': med_id,
            'medicine_name': title,
            'drugbank_ids': result['drugbank_ids'],
            'match_confidence': result['match_confidence'],
            'match_type': result['match_type'],
            'match_rule': result['match_rule'],
            'match_score': result['match_score'],
            'match_source': result['match_source'],
            'matched_on': result.get('matched_on', ''),
            'original_fr_matched': result.get('original_fr', ''),
            'matched_at': time.time(),
        }

        if result['drugbank_ids']:
            stats['matched'] += 1
            stats['by_type'][result['match_type']] += 1
            stats['by_rule'][result['match_rule']] += 1
            bucket = (result['match_score'] // 10) * 10
            stats['by_score_bucket'][f'{bucket}-{bucket+9}'] += 1

            # Pas d'enrichissement en dry-run (évite les requêtes MongoDB lentes)
            if not dry_run:
                enriched_data = fetch_drugbank_enrichment(result['drugbank_ids'])
                enrichment_doc['enriched'] = enriched_data
        else:
            stats['unmatched'] += 1
            if result['match_rule'] and 'below_threshold' in result['match_rule']:
                stats['below_threshold'] += 1
            if title:
                unmatched_list.append({
                    'name': title,
                    'reason': result.get('match_detail', result['match_rule']),
                })
            enrichment_doc['enriched'] = {}

        if not dry_run:
            batch_ops.append(
                UpdateOne(
                    {'medicine_id': med_id},
                    {'$set': enrichment_doc},
                    upsert=True,
                )
            )

        if len(batch_ops) >= BATCH_SIZE or (stats['total'] % PROGRESS_INTERVAL == 0 and batch_ops):
            if not dry_run and batch_ops:
                db.medicine_enrichment.bulk_write(batch_ops)
            batch_ops = []
        if stats['total'] % PROGRESS_INTERVAL == 0:
            elapsed = time.time() - t0
            rate = stats['total'] / elapsed if elapsed > 0 else 0
            eta = (total_meds - stats['total']) / rate if rate > 0 else 0
            pct = stats['total'] / total_meds * 100
            matched_pct = stats['matched'] / stats['total'] * 100 if stats['total'] else 0
            print(f"   {stats['total']:5d}/{total_meds} ({pct:5.1f}%) | "
                  f"OK: {stats['matched']:4d} ({matched_pct:4.1f}%) | "
                  f"BdS: {stats['below_threshold']:3d} | "
                  f"⏱{elapsed:4.0f}s ETA{eta:5.0f}s")
            sys.stdout.flush()

    # Dernier lot
    if batch_ops and not dry_run:
        db.medicine_enrichment.bulk_write(batch_ops)

    # 4. Index
    if not dry_run:
        print("\n📌 Création des index...")
        db.medicine_enrichment.create_index('medicine_id', unique=True)
        db.medicine_enrichment.create_index('match_confidence')
        db.medicine_enrichment.create_index('match_type')
        db.medicine_enrichment.create_index('drugbank_ids')

    # 5. Créer dci_lookup pour les fallbacks runtime
    if not dry_run:
        build_dci_lookup_collection()

    # 6. Stats finales
    t = time.time() - t0
    print(f"\n{'=' * 60}")
    print(f"✅ MATCHING TERMINÉ en {t:.1f}s")
    print(f"{'=' * 60}")
    print(f"Total médicaments      : {stats['total']}")
    print(f"Matchés (≥ {MIN_CONFIDENCE_SAFE}%)      : {stats['matched']} ({_pct(stats['matched'], stats['total'])})")
    print(f"  dont exact           : {stats['by_type'].get('exact', 0)}")
    print(f"  dont synonym         : {stats['by_type'].get('synonym', 0)}")
    print(f"  dont fuzzy           : {stats['by_type'].get('fuzzy', 0)}")
    print(f"  dont sel reduit      : {stats['by_type'].get('sel_reduit', 0)}")
    print(f"Sous seuil (< {MIN_CONFIDENCE_SAFE}%)   : {stats['below_threshold']} ({_pct(stats['below_threshold'], stats['total'])})")
    print(f"Non matchés            : {stats['unmatched'] - stats['below_threshold']} ({_pct(stats['unmatched'] - stats['below_threshold'], stats['total'])})")

    if stats['by_score_bucket']:
        print(f"\nDistribution des scores :")
        for bucket in ['100-100', '90-99', '80-89']:
            count = stats['by_score_bucket'].get(bucket, 0)
            if count:
                print(f"  {bucket:<12s} : {count}")

    if unmatched_list:
        print(f"\n⚠️  Échantillon non matchés (max 15) :")
        for u in unmatched_list[:15]:
            print(f"   ❌ {u['name']:<40s} ({u['reason']})")
        if len(unmatched_list) > 15:
            print(f"   ... et {len(unmatched_list) - 15} autres")

    return stats


def _pct(val: int, total: int) -> str:
    return f"{val / total * 100:.1f}%" if total else "0%"


def fetch_drugbank_enrichment(drugbank_ids: list) -> dict:
    """
    Récupère les données DrugBank enrichies pour une liste d'IDs.
    """
    docs = list(db.DRUGBANKS.find(
        {'drugbank_id': {'$in': drugbank_ids}},
        {
            'mechanism_of_action': 1,
            'pharmacodynamics': 1,
            'indication': 1,
            'toxicity': 1,
            'half_life': 1,
            'protein_binding': 1,
            'metabolism': 1,
            'absorption': 1,
            'route_of_elimination': 1,
            'clearance': 1,
            'volume_of_distribution': 1,
            'classification': 1,
            'atc_codes': 1,
            'interactions': 1,
            'targets': 1,
            'enzymes': 1,
            'transporters': 1,
            'groups': 1,
            'products': 1,
            'pathways': 1,
            'synonyms': 1,
            'external_identifiers': 1,
        }
    ))

    if not docs:
        return {}

    primary = docs[0]

    all_interactions = []
    seen_interactions = set()
    for doc in docs:
        for inter in (doc.get('interactions') or []):
            key = inter.get('drugbank_id', '') + inter.get('name', '')
            if key not in seen_interactions:
                seen_interactions.add(key)
                all_interactions.append(inter)

    all_atc = []
    seen_atc = set()
    for doc in docs:
        for atc in (doc.get('atc_codes') or []):
            code = atc.get('code', '')
            if code and code not in seen_atc:
                seen_atc.add(code)
                all_atc.append(atc)

    return {
        'drugbank_id': primary.get('drugbank_id'),
        'name': primary.get('name'),
        'description': primary.get('description'),
        'mechanism_of_action': primary.get('mechanism_of_action'),
        'pharmacodynamics': primary.get('pharmacodynamics'),
        'indication': primary.get('indication'),
        'toxicity': primary.get('toxicity'),
        'half_life': primary.get('half_life'),
        'protein_binding': primary.get('protein_binding'),
        'metabolism': primary.get('metabolism'),
        'absorption': primary.get('absorption'),
        'route_of_elimination': primary.get('route_of_elimination'),
        'clearance': primary.get('clearance'),
        'volume_of_distribution': primary.get('volume_of_distribution'),
        'classification': primary.get('classification'),
        'groups': primary.get('groups'),
        'synonyms': primary.get('synonyms', [])[:20],
        'atc_codes': all_atc[:10],
        'interactions': all_interactions[:50],
        'targets': docs[0].get('targets', [])[:5],
        'enzymes': docs[0].get('enzymes', [])[:5],
        'transporters': docs[0].get('transporters', [])[:5],
        'products': docs[0].get('products', [])[:10],
        'external_identifiers': primary.get('external_identifiers', {}),
    }


def build_dci_lookup_collection():
    """
    Crée la collection dci_lookup (pré-calculée) :
    mapping normalized_name → drugbank_ids
    Utilisée au runtime par enrichment_service pour les non-matchés.
    Collection petite (~20k docs), O(1) index lookup.
    """
    print("\n📌 Création de dci_lookup (DCI → drugbank_id)...")
    
    db.dci_lookup.drop()  # Reconstruction complète
    
    cursor = db.DRUGBANKS.find(
        {},
        {'drugbank_id': 1, 'name': 1, 'synonyms': 1},
    ).batch_size(2000)

    seen = set()
    entries = {}  # _id -> doc (premier gagnant)
    
    for doc in cursor:
        db_id = doc.get('drugbank_id')
        if not db_id:
            continue
        
        # Nom principal → DCI
        name = doc.get('name', '')
        name_norm = normalize_dci(name)
        if name_norm and len(name_norm) >= 3 and name_norm not in seen:
            seen.add(name_norm)
            entries[name_norm] = {
                '_id': name_norm,
                'drugbank_ids': [db_id],
                'source': 'name',
                'original': name,
            }
        
        # Synonymes
        for syn in (doc.get('synonyms', []) or []):
            if not syn or not syn.strip():
                continue
            syn_norm = normalize_dci(syn)
            if syn_norm and len(syn_norm) >= 3 and syn_norm not in seen:
                seen.add(syn_norm)
                entries[syn_norm] = {
                    '_id': syn_norm,
                    'drugbank_ids': [db_id],
                    'source': 'synonym',
                    'original': syn,
                }
    
    batch = list(entries.values())
    
    if batch:
        # Insérer par lots de 10000 pour éviter les timeouts
        for i in range(0, len(batch), 10000):
            db.dci_lookup.insert_many(batch[i:i+10000], ordered=False)
    
    db.dci_lookup.create_index('_id')
    
    print(f"   ✅ dci_lookup créée : {len(batch)} entrées DCI")
    return len(batch)


if __name__ == '__main__':
    dry = '--dry-run' in sys.argv
    if dry:
        print("🧪 MODE DRY RUN — aucune écriture en base\n")
    run_matching(dry_run=dry)
