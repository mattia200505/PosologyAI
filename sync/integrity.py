"""
Garde-fous de forme sur la collection `medicines`.

Vérifie, en lecture seule, que chaque fiche porte ce dont l'application a
besoin pour s'afficher. Ces contrôles sont dérivés de ce que lisent réellement
`templates/medicine_details.html` et les routes de `app.py` :

    medicine['url'], ['title'], ['sections'], ['update_date'],
    medicine['last_scraped'].strftime(...)   ← le type compte
    medicine['medicine_details'].get(...)    ← doit être un dict

À exécuter avant et après chaque palier de publication :

    python -m sync.integrity
"""

import datetime
import sys

from . import config, jobs

# Champs indispensables au rendu d'une fiche
REQUIRED = ('url', 'title', 'medicine_details', 'sections',
            'update_date', 'last_scraped', 'content_hash')

# Sous-champs attendus par les filtres de recherche et la page détail
REQUIRED_DETAILS = ('substances_actives', 'laboratoire', 'dosages', 'forme')


def _out(text=''):
    encoding = sys.stdout.encoding or 'utf-8'
    sys.stdout.write(str(text).encode(encoding, 'replace').decode(encoding) + '\n')


def check(db, scope=None):
    """
    Contrôle la forme des documents. Lecture seule.

    `scope` : filtre MongoDB optionnel, pour ne vérifier qu'un sous-ensemble.
    Retourne un rapport de comptages.
    """
    query = scope or {}
    total = db[config.COLL_MEDICINES].count_documents(query)

    report = {'examinees': total, 'manquants': {}, 'types': {}, 'sous_champs': {}}

    for field in REQUIRED:
        missing = db[config.COLL_MEDICINES].count_documents(
            {**query, '$or': [{field: {'$exists': False}}, {field: None}]})
        report['manquants'][field] = missing

    for field in REQUIRED_DETAILS:
        missing = db[config.COLL_MEDICINES].count_documents(
            {**query, 'medicine_details.%s' % field: {'$exists': False}})
        report['sous_champs'][field] = missing

    # medicine_details doit être un dict, sections une liste : un type inattendu
    # ferait échouer le rendu, pas seulement l'absence du champ.
    report['types']['medicine_details_non_objet'] = db[config.COLL_MEDICINES].count_documents(
        {**query, 'medicine_details': {'$not': {'$type': 'object'}}})
    report['types']['sections_non_liste'] = db[config.COLL_MEDICINES].count_documents(
        {**query, 'sections': {'$not': {'$type': 'array'}}})
    report['types']['last_scraped_non_date'] = db[config.COLL_MEDICINES].count_documents(
        {**query, 'last_scraped': {'$not': {'$type': 'date'}}})

    report['vides'] = {
        'sections_vides': db[config.COLL_MEDICINES].count_documents(
            {**query, 'sections': {'$size': 0}}),
        'titre_sans_valeur': db[config.COLL_MEDICINES].count_documents(
            {**query, 'title': {'$in': ['', 'Document sans titre']}}),
    }

    # L'unicité de l'URL est imposée par l'index, mais on la contrôle par sûreté.
    distinct_urls = len(db[config.COLL_MEDICINES].distinct('url', query))
    report['url_distinctes'] = distinct_urls
    report['url_dupliquees'] = total - distinct_urls

    anomalies = (sum(report['manquants'].values())
                 + sum(report['types'].values())
                 + report['url_dupliquees'])
    report['anomalies_bloquantes'] = anomalies
    report['conforme'] = anomalies == 0
    return report


def render(report, title='CONTROLE DE FORME'):
    _out('=== %s ===' % title)
    _out('  fiches examinees : %s' % f"{report['examinees']:,}")
    _out('')
    _out('  champs indispensables manquants :')
    for field, count in report['manquants'].items():
        _out('    [%s] %-18s %d' % ('OK' if not count else '!!', field, count))
    _out('')
    _out('  types inattendus :')
    for label, count in report['types'].items():
        _out('    [%s] %-32s %d' % ('OK' if not count else '!!', label, count))
    _out('')
    _out('  sous-champs de medicine_details absents :')
    for field, count in report['sous_champs'].items():
        _out('    [%s] %-18s %d' % ('OK' if not count else '  ', field, count))
    _out('')
    _out('  url dupliquees : %d' % report['url_dupliquees'])
    _out('  sections vides : %d   (informatif)' % report['vides']['sections_vides'])
    _out('  titres sans valeur : %d   (informatif)' % report['vides']['titre_sans_valeur'])
    _out('')
    _out('  VERDICT : %s' % ('CONFORME' if report['conforme'] else 'NON CONFORME'))


def main():
    db = jobs.connect()
    report = check(db)
    render(report, 'CONTROLE DE FORME - COLLECTION ENTIERE')

    created = {'_sync.last_job_type': 'collecte_initiale'}
    if db[config.COLL_MEDICINES].count_documents(created):
        _out('')
        render(check(db, created), 'CONTROLE DE FORME - FICHES CREEES PAR LE SOCLE')

    return 0 if report['conforme'] else 1


if __name__ == '__main__':
    sys.exit(main())
