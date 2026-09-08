"""
Réconciliation entre le catalogue officiel et la base locale.

Détecte ce que la sonde de révision ne peut pas voir : créations, retraits, et
divergences sur les champs dont le dump est la source autoritaire.

Le différentiel est une fonction pure : il ne touche pas à la base. Seul
`enqueue()` écrit, et uniquement dans la file de travaux — jamais dans
`medicines`.
"""

import datetime
import re
import unicodedata

from . import ansm_dumps, config, jobs

SPECID = re.compile(r'specid=(\d+)')

# Champs pour lesquels le dump fait autorité, avec le chemin correspondant en base
AUTHORITATIVE = (
    ('denomination', ('title',)),
    ('forme', ('medicine_details', 'forme')),
    ('titulaire', ('medicine_details', 'laboratoire')),
)

# Attributs administratifs : champ du dump -> champ en base.
#
# Ils sont traités à part des champs autoritaires ci-dessus parce que la règle
# de comparaison diffère. Une dénomination se compare à la normalisation près,
# une perte d'accent trahissant un défaut d'extraction et non un changement de
# source. Ces dix valeurs sont au contraire recopiées telles quelles du fichier
# maître : tout écart est un écart réel, et la comparaison doit être exacte.
#
# La forme et le titulaire y figurent sous leur nom canonique. Ils ne
# remplacent jamais les valeurs descriptives de la notice — la phase P3 a
# montré que le dump y est plus pauvre — mais vivent dans leurs propres champs.
CATALOGUE_PATHS = (
    ('statut_amm', 'statut_amm'),
    ('commercialisation', 'commercialisation'),
    ('date_amm', 'date_amm'),
    ('voies_administration', 'voies_administration'),
    ('procedure_amm', 'procedure_amm'),
    ('autorisation_europeenne', 'autorisation_europeenne'),
    ('statut_bdm', 'statut_bdm'),
    ('surveillance_renforcee', 'surveillance_renforcee'),
    ('forme', 'forme_canonique'),
    ('titulaire', 'titulaire_amm'),
)

# Titres manifestement issus d'une extraction ratée
BROKEN_TITLE = re.compile(
    r'^(attention|classe pharmac|adultes?|enfants?|posologie|mode d|voie |'
    r'sans objet|document sans titre|indications|contre-indic|precautions|effets)',
    re.IGNORECASE)


def extract_cis(url):
    """Extrait le code CIS d'une URL de notice. Vérifié fiable sur 9 804 fiches."""
    if not url:
        return None
    found = SPECID.search(url)
    return found.group(1) if found else None


def normalise(value):
    """
    Normalisation insensible aux accents, à la casse et à la ponctuation.

    La phase P1 a montré qu'une comparaison sensible à ces variations gonfle
    les divergences de 355 à 704, l'écart correspondant à des pertes de
    ponctuation et d'accents à l'extraction, non à des changements de source.
    """
    text = unicodedata.normalize('NFKD', str(value or ''))
    text = text.encode('ascii', 'ignore').decode()
    return re.sub(r'[^a-z0-9]', '', text.lower())


def _read_path(document, path):
    node = document
    for key in path:
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    return node


def local_catalogue(db):
    """Indexe la base locale par code CIS."""
    projection = {'url': 1, 'title': 1, 'medicine_details': 1, 'update_date': 1}
    projection.update({local: 1 for _, local in CATALOGUE_PATHS})
    catalogue = {}
    for document in db[config.COLL_MEDICINES].find({}, projection):
        cis = extract_cis(document.get('url'))
        if cis:
            catalogue[cis] = document
    return catalogue


def classify_divergence(field, local_value, official_value):
    """
    Qualifie une divergence.

    Un titre réduit à un fragment de texte, ou dont seuls les espaces diffèrent,
    trahit un défaut d'extraction plutôt qu'un changement à la source.
    """
    if field == 'denomination':
        local_text = str(local_value or '').strip()
        if BROKEN_TITLE.match(local_text) or len(local_text) < 6:
            return 'defaut_extraction'
        if re.sub(r'\s+', '', local_text) == re.sub(r'\s+', '', str(official_value or '')):
            return 'defaut_extraction'
    return 'changement_source'


def diff(db, session=None):
    """
    Calcule le différentiel complet. N'écrit rien.

    Retourne un rapport structuré : créations, orphelins, divergences, totaux.
    """
    official, meta = ansm_dumps.load_master(session)
    local = local_catalogue(db)

    official_ids = set(official)
    local_ids = set(local)

    creations = []
    for cis in sorted(official_ids - local_ids):
        record = official[cis]
        creations.append({
            'cis': cis,
            'denomination': record['denomination'],
            'statut_amm': record['statut_amm'],
            'commercialisation': record['commercialisation'],
            'priority': 0 if ansm_dumps.is_active(record) else 7,
        })

    orphans = []
    for cis in sorted(local_ids - official_ids):
        document = local[cis]
        orphans.append({
            'cis': cis,
            'titre_en_base': document.get('title'),
            'url': document.get('url'),
        })

    catalogue_updates = []
    for cis in sorted(official_ids & local_ids):
        record = official[cis]
        document = local[cis]
        ecarts = [{'champ': local_field,
                   'valeur_base': document.get(local_field),
                   'valeur_dump': record.get(dump_field)}
                  for dump_field, local_field in CATALOGUE_PATHS
                  if (document.get(local_field) or '') != (record.get(dump_field) or '')]
        if ecarts:
            catalogue_updates.append({'cis': cis, 'champs': ecarts, 'record': record})

    divergences = []
    for cis in sorted(official_ids & local_ids):
        record = official[cis]
        document = local[cis]
        for field, path in AUTHORITATIVE:
            local_value = _read_path(document, path)
            official_value = record.get(field)
            if normalise(local_value) != normalise(official_value):
                divergences.append({
                    'cis': cis,
                    'champ': field,
                    'valeur_base': local_value,
                    'valeur_dump': official_value,
                    'nature': classify_divergence(field, local_value, official_value),
                })

    by_field = {}
    for item in divergences:
        by_field[item['champ']] = by_field.get(item['champ'], 0) + 1

    return {
        'generated_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'source': {'CIS_bdpm.txt': meta},
        'creations': creations,
        'orphans': orphans,
        'divergences': divergences,
        'catalogue_updates': catalogue_updates,
        'totals': {
            'catalogue_officiel': len(official_ids),
            'base_locale': len(local_ids),
            'creations': len(creations),
            'creations_prioritaires': sum(1 for c in creations if c['priority'] == 0),
            'orphans': len(orphans),
            'divergences': len(divergences),
            'divergences_par_champ': by_field,
            'attributs_a_aligner': len(catalogue_updates),
        },
    }


def enqueue(db, report):
    """
    Traduit un différentiel en tâches. Seule écriture de ce module.

    Les divergences d'un même CIS sont regroupées en une tâche de réparation :
    un seul document par médicament à corriger.
    """
    operations = []

    for item in report['creations']:
        operations.append(jobs.build(
            'collecte_initiale', item['cis'],
            url=config.ANSM_NOTICE % item['cis'],
            priority=item['priority'],
            payload={'denomination': item['denomination'],
                     'statut_amm': item['statut_amm'],
                     'commercialisation': item['commercialisation']}))

    for item in report['orphans']:
        operations.append(jobs.build(
            'verification_retrait', item['cis'],
            url=item['url'], priority=8,
            payload={'titre_en_base': item['titre_en_base']}))

    # Seule la dénomination donne lieu à une réparation. Pour la forme et le
    # titulaire, la comparaison des valeurs réelles a montré que le dump fournit
    # une normalisation plus pauvre que la notice — « Gel buccal » y devient
    # « gel », « ACCORD HEALTHCARE FRANCE SAS » perd sa forme juridique. Ces
    # valeurs canoniques sont conservées à part par la passe catalogue, jamais
    # substituées aux valeurs descriptives.
    grouped = {}
    for item in report['divergences']:
        if item['champ'] != 'denomination':
            continue
        grouped.setdefault(item['cis'], []).append(item)
    for cis, items in grouped.items():
        operations.append(jobs.build(
            'reparation_champ', cis,
            url=config.ANSM_NOTICE % cis, priority=6,
            payload={'champs': [{'champ': i['champ'],
                                 'valeur_dump': i['valeur_dump'],
                                 'nature': i['nature']} for i in items]}))

    # Attributs administratifs. Aucun accès réseau : la valeur cible voyage
    # dans la tâche elle-même, `$set` la rafraîchissant à chaque redétection.
    catalogue_ids = []
    for item in report.get('catalogue_updates', []):
        operations.append(jobs.build(
            'enrichissement_catalogue', item['cis'],
            url=config.ANSM_NOTICE % item['cis'], priority=4,
            payload={'record': item['record'], 'champs': item['champs']}))
        catalogue_ids.append(jobs.job_id('enrichissement_catalogue', item['cis']))

    created, updated = jobs.add_many(db, operations)

    # Un écart qui se reforme après coup doit relancer sa tâche : sans cela,
    # un passage en rupture d'approvisionnement resterait invisible parce que
    # la tâche du même CIS aurait déjà été marquée terminée.
    rearmed = jobs.rearm(db, catalogue_ids)

    return {'taches_preparees': len(operations),
            'creees': created, 'mises_a_jour': updated, 'rearmees': rearmed}
