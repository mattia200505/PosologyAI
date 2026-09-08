"""
Publication additive vers `medicines`.

Ce module ne contient aucune écriture. Il calcule ce qu'une publication
*ferait* et retourne un plan comparable avant/après. L'écriture réelle
relève de l'étape suivante de P3, derrière un drapeau explicite.

Le principe est une **liste blanche par type de tâche** : chaque type déclare
les seuls chemins qu'il a le droit d'écrire. Un champ non déclaré est
intouchable par construction — un oubli préserve donc la donnée au lieu de la
détruire, à l'inverse d'une liste d'exclusions.

Cette contrainte règle la collision identifiée en P3 : `scraper.py:393` écrit
`{"$set": document}` avec `medicine_details` entier, ce qui écraserait la
dénomination et la forme réparées depuis le dump officiel.
"""

import datetime
import hashlib
import json

from pymongo import ReturnDocument

from . import config

# ── Propriétaire de chaque chemin ──────────────────────────────────────
DUMP = 'dump_ansm'
SCRAPE = 'scraping'
DERIVED = 'derive'
PUBLICATION = 'publication'

OWNER = {
    'cis': DERIVED,
    'url': SCRAPE,
    'title': DUMP,
    # La forme et le titulaire restent la propriété du scraping : le dump en
    # donne une version canonique plus courte, conservée à part (voir plus bas).
    'medicine_details.forme': SCRAPE,
    'medicine_details.laboratoire': SCRAPE,
    'forme_canonique': DUMP,
    'titulaire_amm': DUMP,
    'medicine_details.substances_actives': SCRAPE,
    'medicine_details.dosages': SCRAPE,
    'sections': SCRAPE,
    'update_date': SCRAPE,
    'content_hash': SCRAPE,
    'last_scraped': SCRAPE,
    'document_type': SCRAPE,
    'statut_amm': DUMP,
    'commercialisation': DUMP,
    'date_amm': DUMP,
    'voies_administration': DUMP,
    'procedure_amm': DUMP,
    'autorisation_europeenne': DUMP,
    'statut_bdm': DUMP,
    'surveillance_renforcee': DUMP,
    '_sync.absent_du_catalogue': PUBLICATION,
    '_sync.absent_depuis': PUBLICATION,
}

# ── Liste blanche : ce que chaque type de tâche peut écrire ────────────
# Attributs repris tels quels du fichier maître, plus les deux valeurs
# canoniques conservées à côté des valeurs descriptives issues de la notice.
CATALOGUE_FIELDS = ('statut_amm', 'commercialisation', 'date_amm',
                    'voies_administration', 'procedure_amm',
                    'autorisation_europeenne', 'statut_bdm',
                    'surveillance_renforcee', 'forme_canonique', 'titulaire_amm')

WRITABLE = {
    # Répare la seule dénomination. La comparaison des valeurs réelles a montré
    # que le dump ne corrige que ce champ : pour la forme et le titulaire, il
    # fournit une normalisation plus pauvre, pas une correction (voir P3 §11).
    'reparation_champ': ('title',),

    # Re-scrape le contenu. Écrit par chemin imbriqué pour ne pas emporter
    # forme et laboratoire, qui appartiennent au dump.
    'rafraichissement': ('sections', 'update_date', 'content_hash', 'last_scraped',
                         'document_type', 'medicine_details.substances_actives',
                         'medicine_details.dosages'),

    # Création : contenu scrapé plus attributs du catalogue.
    'collecte_initiale': ('cis', 'url', 'title', 'sections', 'update_date',
                          'content_hash', 'last_scraped', 'document_type',
                          'medicine_details.forme', 'medicine_details.laboratoire',
                          'medicine_details.substances_actives',
                          'medicine_details.dosages') + CATALOGUE_FIELDS,

    # Le CIS a disparu du catalogue : on le consigne, sans rien décider d'autre.
    'verification_retrait': ('_sync.absent_du_catalogue', '_sync.absent_depuis'),

    # Aligne les attributs administratifs sur le fichier maître, sans toucher
    # au contenu de la notice. Deux usages : rattraper les fiches antérieures
    # au socle, qui n'ont jamais reçu ces champs, et suivre les valeurs qui
    # évoluent — un médicament passe en rupture d'approvisionnement ou cesse
    # d'être commercialisé sans que sa notice change d'une ligne.
    'enrichissement_catalogue': CATALOGUE_FIELDS,
}

# Champs jamais écrits par la publication, quel que soit le type de tâche.
NEVER_WRITTEN = (
    'code_atc', 'libelle_atc', 'type_medicament', 'groupe_anatomique',
    'groupe_anatomique_original', 'famille_therapeutique',
    'famille_therapeutique_en', 'groupe_anatomique_en',
    'groupe_anatomique_original_en', 'type_medicament_en',
    'ai_summary', 'summary_timestamp', 'summary_content_hash',
    '_ai_summary_source', '_medicine_details_source',
)

# Au-delà de cette taille, une valeur est résumée par son empreinte : inclure
# 200 Ko de sections dans un plan le rendrait illisible.
INLINE_LIMIT = 400


class UnknownJobType(ValueError):
    """Type de tâche sans liste blanche déclarée."""


def read_path(document, path):
    """Lit une valeur par chemin pointé. Retourne None si absente."""
    node = document or {}
    for key in path.split('.'):
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    return node


def _serialise(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def summarise(value):
    """Représente une valeur dans un plan, en la résumant si elle est volumineuse."""
    if value is None:
        return None
    text = _serialise(value)
    if len(text) <= INLINE_LIMIT:
        return value
    return {
        '_resume': True,
        'type': type(value).__name__,
        'octets': len(text),
        'empreinte': hashlib.md5(text.encode('utf-8')).hexdigest(),
        'apercu': text[:160],
    }


def _equal(before, after):
    if before is None and after is None:
        return True
    return _serialise(before) == _serialise(after)


# Valeur sentinelle rendue par l'extracteur historique quand la date manque.
NO_DATE = 'Date not found'


def _viability(source, job_type, exists):
    """
    Une création n'est publiable que si la notice a livré du contenu.

    21,4 % des créations attendues sont des enregistrements homéopathiques dont
    la page ne porte ni date ni sections — environ 43 Ko contre 185 Ko pour une
    notice réelle. Les publier créerait autant de fiches vides. Le cas se
    rencontre aussi hors homéopathie, d'où un contrôle sur le contenu et non
    sur la procédure d'AMM.
    """
    if job_type != 'collecte_initiale' or exists:
        return True, None

    date = source.get('update_date')
    if not date or date == NO_DATE:
        return False, 'notice sans date de revision'
    if not source.get('sections'):
        return False, 'notice sans sections exploitables'
    return True, None


def plan(current, source, job_type, cis=None):
    """
    Calcule le plan de publication. N'écrit rien.

    `current` : document existant, ou None pour une création.
    `source`  : dict plat {chemin: valeur} produit par un constructeur.
    `cis`     : code CIS de la tâche, les documents existants n'en portant pas encore.

    Retourne le contrat de simulation défini dans les spécifications P3.
    """
    allowed = WRITABLE.get(job_type)
    if allowed is None:
        raise UnknownJobType(job_type)

    exists = current is not None
    changes, rejected = [], []

    for path, after in source.items():
        if path not in allowed:
            # La valeur est écartée, jamais écrite : trace pour le contrôle.
            rejected.append(path)
            continue
        before = read_path(current, path)
        if _equal(before, after):
            continue
        changes.append({
            'path': path,
            'before': summarise(before),
            'after': summarise(after),
            'owner': OWNER.get(path, 'inconnu'),
        })

    touched = {c['path'].split('.')[0] for c in changes}
    untouched = sorted(set(current or {}) - touched - {'_id'}) if exists else []

    viable, reason = _viability(source, job_type, exists)

    delta = sum(len(_serialise(source[c['path']]))
                - len(_serialise(read_path(current, c['path'])))
                for c in changes)

    return {
        'cis': cis or (current or {}).get('cis') or source.get('cis'),
        'job_type': job_type,
        'exists': exists,
        'changes': changes,
        'rejected': sorted(rejected),
        'untouched': untouched,
        'bytes_delta': delta,
        'viable': viable,
        'reason': reason,
        'would_write': bool(changes) and viable,
    }


# ── Constructeurs de source ────────────────────────────────────────────

# Seule la dénomination est réparée depuis le dump.
REPAIR_PATHS = {'denomination': 'title'}


def source_from_repair(payload):
    """Source d'une réparation : la dénomination officielle."""
    source = {}
    for item in (payload or {}).get('champs', []):
        path = REPAIR_PATHS.get(item.get('champ'))
        if path:
            source[path] = item.get('valeur_dump')
    return source


def source_from_withdrawal(when):
    """Source d'une vérification de retrait : un simple constat daté."""
    return {'_sync.absent_du_catalogue': True, '_sync.absent_depuis': when}


def source_from_catalogue(record):
    """
    Source des attributs administratifs, issus du fichier maître.

    La forme et le titulaire du dump sont rangés dans des champs distincts :
    ce sont des valeurs canoniques, à conserver *à côté* des valeurs
    descriptives de la notice, non à leur place.
    """
    source = {field: record.get(field)
              for field in CATALOGUE_FIELDS
              if field in record and field not in ('forme_canonique', 'titulaire_amm')}
    if 'forme' in record:
        source['forme_canonique'] = record['forme']
    if 'titulaire' in record:
        source['titulaire_amm'] = record['titulaire']
    return source


def source_from_notice(raw, url, catalogue_record=None):
    """
    Source d'un rafraîchissement ou d'une collecte : le contenu de la notice.

    Réutilise l'analyse du scraper existant, seule implémentation éprouvée du
    découpage en sections. La dénomination, la forme et le titulaire ne sont
    volontairement pas repris d'ici : le dump en est la source autoritaire.
    """
    from bs4 import BeautifulSoup
    from scripts.scraping import scraper as legacy

    soup = BeautifulSoup(raw, 'html.parser')
    substances = legacy.extract_substances_and_dosages(soup)

    source = {
        'sections': legacy.extract_sections(soup),
        'update_date': legacy.extract_update_date(soup),
        'document_type': 'HTML',
        'medicine_details.substances_actives': substances['substances_actives'],
        'medicine_details.dosages': substances['dosages'],
    }

    # L'empreinte porte sur les mêmes champs que le scraper historique, afin
    # que les valeurs déjà en base restent comparables.
    source['content_hash'] = legacy.generate_content_hash({
        'title': legacy.extract_medicine_title(soup),
        'update_date': source['update_date'],
        'medicine_details': {
            'substances_actives': substances['substances_actives'],
            'laboratoire': legacy.extract_laboratory(soup),
            'dosages': substances['dosages'],
            'forme': legacy.extract_pharmaceutical_form(soup),
        },
        'sections': source['sections'],
    })

    if catalogue_record:
        source['url'] = url
        source['cis'] = catalogue_record.get('cis')
        # Dénomination officielle, mais forme et laboratoire descriptifs issus
        # de la notice : les valeurs canoniques du dump vont dans leurs propres champs.
        source['title'] = catalogue_record.get('denomination')
        source['medicine_details.forme'] = legacy.extract_pharmaceutical_form(soup)
        source['medicine_details.laboratoire'] = legacy.extract_laboratory(soup)
        source.update(source_from_catalogue(catalogue_record))

    return source


# ── Écriture réelle ────────────────────────────────────────────────────

def apply(db, plan_item, current, source, cis, worker=None):
    """
    Applique un plan à `medicines`. Seule fonction du module qui écrit.

    L'écriture se fait exclusivement par chemin pointé : le sous-document
    `medicine_details` n'est jamais remplacé en bloc, ce qui préserve la forme
    et le laboratoire lorsqu'un rafraîchissement met à jour les substances.

    Retourne un compte rendu, ou None si le plan ne prévoit rien.
    """
    from . import history

    if not plan_item['would_write']:
        return None

    paths = [change['path'] for change in plan_item['changes']]
    values = {path: source[path] for path in paths}

    now = datetime.datetime.now(datetime.timezone.utc)
    values['_sync.last_published_at'] = now
    values['_sync.last_job_type'] = plan_item['job_type']

    if not plan_item['exists']:
        document = {'cis': cis, '_sync': {'last_published_at': now,
                                          'last_job_type': plan_item['job_type']}}
        for path, value in values.items():
            if path.startswith('_sync.'):
                continue
            _write_path(document, path, value)
        document.setdefault('last_scraped', now)
        inserted = db[config.COLL_MEDICINES].insert_one(document)
        return {'action': 'creation', 'medicine_id': inserted.inserted_id,
                'paths': paths, 'history_id': None}

    medicine_id = current['_id']
    previous = {change['path']: read_path(current, change['path'])
                for change in plan_item['changes']}
    history_id = history.record(db, medicine_id, cis, plan_item['job_type'],
                                previous, paths, worker)

    if 'cis' not in current:
        values['cis'] = cis

    db[config.COLL_MEDICINES].update_one({'_id': medicine_id}, {'$set': values})
    return {'action': 'mise_a_jour', 'medicine_id': medicine_id,
            'paths': paths, 'history_id': history_id}


def _write_path(document, path, value):
    """Pose une valeur par chemin pointé dans un document en construction."""
    node = document
    keys = path.split('.')
    for key in keys[:-1]:
        node = node.setdefault(key, {})
    node[keys[-1]] = value


def bump_catalogue_version(db):
    """
    Incrémente le compteur de version du catalogue.

    L'application conserve les options de filtres dans un cache jamais invalidé
    (`app.py:459-512`). Ce compteur lui donne de quoi détecter qu'il doit le
    reconstruire, faute de quoi les médicaments ajoutés resteraient absents des
    listes de substances, formes et laboratoires jusqu'au redémarrage.
    """
    doc = db[config.COLL_CONTROL].find_one_and_update(
        {'_id': 'catalogue_version'},
        {'$inc': {'value': 1},
         '$set': {'updated_at': datetime.datetime.now(datetime.timezone.utc)}},
        upsert=True, return_document=ReturnDocument.AFTER)
    return (doc or {}).get('value', 1)


# ── Contrôles obligatoires avant toute écriture réelle ─────────────────

def check_invariants(plans, known_fields):
    """
    Applique les cinq contrôles exigés par les spécifications P3.

    Retourne (conforme, détails).
    """
    outside = []
    for item in plans:
        allowed = WRITABLE.get(item['job_type'], ())
        outside.extend(c['path'] for c in item['changes'] if c['path'] not in allowed)

    protected_touched = []
    for item in plans:
        for change in item['changes']:
            root = change['path'].split('.')[0]
            if root in NEVER_WRITTEN:
                protected_touched.append(change['path'])

    # Un chemin qui désigne un sous-document entier remplacerait ses sous-champs.
    # C'est exactement le défaut de scraper.py:393 avec `medicine_details`.
    subdocuments = {path.split('.')[0] for path in OWNER if '.' in path}
    wholesale = []
    for item in plans:
        wholesale.extend(c['path'] for c in item['changes'] if c['path'] in subdocuments)

    # Le document résultant doit conserver tous ses champs de premier niveau.
    lost = []
    for item in plans:
        if not item['exists']:
            continue
        before = set(item['untouched']) | {c['path'].split('.')[0] for c in item['changes']}
        after = before | {c['path'].split('.')[0] for c in item['changes']}
        lost.extend(sorted(before - after))

    sections_on_repair = [
        item['cis'] for item in plans
        if item['job_type'] == 'reparation_champ'
        and any(c['path'] == 'sections' for c in item['changes'])
    ]
    title_on_refresh = [
        item['cis'] for item in plans
        if item['job_type'] == 'rafraichissement'
        and any(c['path'] == 'title' for c in item['changes'])
    ]

    details = {
        'hors_liste_blanche': sorted(set(outside)),
        'champs_proteges_touches': sorted(set(protected_touched)),
        'sous_documents_remplaces': sorted(set(wholesale)),
        'champs_perdus': sorted(set(lost)),
        'sections_modifiees_par_reparation': sections_on_repair,
        'titre_modifie_par_rafraichissement': title_on_refresh,
    }
    compliant = not any(details.values())
    return compliant, details
