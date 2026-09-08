"""
Historisation des publications et restauration fiche par fiche.

Le champ `sections` pèse 200 Ko sur les 201 Ko d'un document : conserver une
copie intégrale à chaque version ferait passer la collection de 2 949 Mo à
5 898 Mo après P4. Seules les **valeurs antérieures des champs effectivement
modifiés** sont donc enregistrées, ce qui rend le coût proportionnel au
changement réel et non à la taille du catalogue.

L'historisation sert au retour arrière fiche par fiche. La restauration
complète reste du ressort de `mongodump`.
"""

import datetime

from pymongo import ASCENDING, DESCENDING

from . import config

COLL_HISTORY = 'medicines_history'
RETAINED_VERSIONS = 3


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


def ensure_indexes(db):
    """Index de service. Idempotent."""
    db[COLL_HISTORY].create_index(
        [('cis', ASCENDING), ('published_at', DESCENDING)], name='idx_cis_date')
    db[COLL_HISTORY].create_index([('medicine_id', ASCENDING)], name='idx_medicine')


def record(db, medicine_id, cis, job_type, previous, changed, worker=None):
    """
    Enregistre les valeurs antérieures des champs modifiés.

    `previous` : {chemin: valeur avant modification}. Une création n'a pas
    d'antériorité et ne produit aucune entrée.
    """
    if not previous:
        return None

    entry = {
        'cis': cis,
        'medicine_id': medicine_id,
        'job_type': job_type,
        'published_at': _now(),
        'worker': worker,
        'previous': previous,
        'changed': sorted(changed),
    }
    inserted = db[COLL_HISTORY].insert_one(entry)
    _prune(db, cis)
    return inserted.inserted_id


def _prune(db, cis):
    """Ne conserve que les dernières versions d'une fiche."""
    surplus = list(db[COLL_HISTORY]
                   .find({'cis': cis}, {'_id': 1})
                   .sort('published_at', DESCENDING)
                   .skip(RETAINED_VERSIONS))
    if surplus:
        db[COLL_HISTORY].delete_many({'_id': {'$in': [d['_id'] for d in surplus]}})


def versions(db, cis):
    """Versions disponibles pour une fiche, de la plus récente à la plus ancienne."""
    return list(db[COLL_HISTORY].find({'cis': cis}).sort('published_at', DESCENDING))


def rollback(db, cis, version_id=None):
    """
    Rétablit les valeurs antérieures d'une fiche.

    Sans `version_id`, la version la plus récente est utilisée. L'entrée
    d'historique consommée est supprimée, afin qu'un second appel remonte à la
    version précédente plutôt que de rejouer la même.

    Retourne le nombre de chemins restaurés, ou None si aucune version.
    """
    available = versions(db, cis)
    if not available:
        return None

    if version_id is None:
        entry = available[0]
    else:
        entry = next((v for v in available if v['_id'] == version_id), None)
        if entry is None:
            return None

    restore, remove = {}, {}
    for path, value in entry['previous'].items():
        if value is None:
            remove[path] = ''          # le champ n'existait pas avant
        else:
            restore[path] = value

    update = {}
    if restore:
        update['$set'] = restore
    if remove:
        update['$unset'] = remove
    if not update:
        return 0

    db[config.COLL_MEDICINES].update_one({'_id': entry['medicine_id']}, update)
    db[COLL_HISTORY].delete_one({'_id': entry['_id']})
    return len(entry['previous'])


def stats(db):
    """Volumétrie de l'historique."""
    total = db[COLL_HISTORY].count_documents({})
    if not total:
        return {'entrees': 0, 'fiches': 0, 'octets': 0}
    size = db.command('collStats', COLL_HISTORY).get('size', 0)
    return {
        'entrees': total,
        'fiches': len(db[COLL_HISTORY].distinct('cis')),
        'octets': size,
    }
