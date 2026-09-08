"""
File de travaux persistée dans MongoDB.

Un document par tâche, identifié par `<type>:<cis>` — ce choix vaut garantie
d'idempotence : rejouer la réconciliation met à jour les tâches existantes au
lieu d'en créer des doublons.

La réservation repose sur `find_one_and_update`, atomique au niveau du
document : deux workers concurrents obtiennent nécessairement deux tâches
différentes, sans verrou applicatif.
"""

import datetime
import os
import socket
import uuid

from pymongo import ASCENDING, MongoClient, ReturnDocument, UpdateOne

from . import config


def connect():
    """
    Ouvre une connexion à la base de synchronisation.

    `tz_aware` est indispensable : sans lui, MongoDB renvoie des dates sans
    fuseau que l'on ne peut pas comparer aux dates de référence, elles-mêmes
    en UTC explicite.
    """
    client = MongoClient(config.MONGO_URI,
                         serverSelectionTimeoutMS=config.MONGO_TIMEOUT_MS,
                         tz_aware=True)
    return client[config.DB_NAME]


def worker_identity():
    """Identifie un worker : hôte, processus, et UUID pour distinguer les fils."""
    return '%s:%d:%s' % (socket.gethostname(), os.getpid(), uuid.uuid4().hex[:8])


def ensure_indexes(db):
    """Crée les index de service. Idempotent."""
    jobs = db[config.COLL_JOBS]
    jobs.create_index(
        [('state', ASCENDING), ('available_at', ASCENDING),
         ('priority', ASCENDING), ('created_at', ASCENDING)],
        name='idx_reservation')
    jobs.create_index([('state', ASCENDING), ('lease_expires_at', ASCENDING)],
                      name='idx_lease')
    jobs.create_index([('cis', ASCENDING)], name='idx_cis')
    jobs.create_index([('type', ASCENDING), ('state', ASCENDING)],
                      name='idx_type_state')


def job_id(job_type, cis):
    return '%s:%s' % (job_type, cis)


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


def build(job_type, cis, url=None, priority=5, payload=None):
    """Prépare une opération d'insertion ou de mise à jour pour un lot."""
    if job_type not in config.JOB_TYPES:
        raise ValueError('type de tâche inconnu : %s' % job_type)
    now = _now()
    return UpdateOne(
        {'_id': job_id(job_type, cis)},
        {
            # Champs rafraîchis à chaque détection
            '$set': {
                'type': job_type,
                'cis': cis,
                'url': url,
                'priority': priority,
                'payload': payload or {},
                'updated_at': now,
            },
            # Champs posés uniquement à la création : une tâche déjà traitée
            # ou en cours n'est pas réarmée par une simple redétection.
            '$setOnInsert': {
                'state': 'pending',
                'attempts': 0,
                'max_attempts': config.MAX_ATTEMPTS,
                'available_at': now,
                'lease_expires_at': None,
                'worker': None,
                'created_at': now,
                'last_error': None,
            },
        },
        upsert=True,
    )


def add_many(db, operations):
    """Applique un lot d'opérations préparées par build(). Retourne (créées, mises à jour)."""
    if not operations:
        return 0, 0
    result = db[config.COLL_JOBS].bulk_write(operations, ordered=False)
    return result.upserted_count, result.modified_count


def add(db, job_type, cis, url=None, priority=5, payload=None):
    """Ajoute une tâche unique."""
    created, updated = add_many(db, [build(job_type, cis, url, priority, payload)])
    return created > 0


def rearm(db, job_ids):
    """
    Remet en attente des tâches déjà terminées ou en échec définitif.

    `build()` pose l'état en `$setOnInsert` : une tâche traitée n'est jamais
    réarmée par une simple redétection, ce qui est le bon défaut pour une
    collecte ou une réparation — le travail a été fait une fois pour toutes.

    Certains écarts se reforment pourtant après coup : un médicament passe en
    rupture d'approvisionnement ou cesse d'être commercialisé longtemps après
    sa première synchronisation. Détecter à nouveau l'écart signifie alors que
    la base diverge *aujourd'hui* du catalogue officiel, et la tâche doit
    repartir.

    Le filtre exclut volontairement les états `pending` et `reserved` : une
    tâche en cours appartient à son worker, la lui retirer produirait une
    double publication.
    """
    if not job_ids:
        return 0
    now = _now()
    result = db[config.COLL_JOBS].update_many(
        {'_id': {'$in': list(job_ids)}, 'state': {'$in': ['done', 'failed', 'cancelled']}},
        {'$set': {'state': 'pending', 'attempts': 0, 'available_at': now,
                  'lease_expires_at': None, 'worker': None, 'updated_at': now}},
    )
    return result.modified_count


def reserve(db, worker, types=None, lease_seconds=None):
    """
    Réserve la tâche disponible la plus prioritaire, de façon atomique.

    Le filtre couvre deux cas : les tâches en attente dont l'heure de mise à
    disposition est passée, et les tâches réservées dont le bail a expiré —
    c'est ce second cas qui assure la reprise après la mort d'un worker.

    Retourne le document réservé, ou None si la file est vide.
    """
    now = _now()
    conditions = [
        {'state': 'pending', 'available_at': {'$lte': now}},
        {'state': 'reserved', 'lease_expires_at': {'$lt': now}},
    ]
    query = {'$or': conditions}
    if types:
        query['type'] = {'$in': list(types)}

    # Le bail dépend du type ; sans filtre de type on retient la valeur par défaut.
    if lease_seconds is None:
        if types and len(types) == 1:
            lease_seconds = config.LEASE_SECONDS.get(types[0], config.DEFAULT_LEASE)
        else:
            lease_seconds = config.DEFAULT_LEASE

    return db[config.COLL_JOBS].find_one_and_update(
        query,
        {
            '$set': {
                'state': 'reserved',
                'worker': worker,
                'lease_expires_at': now + datetime.timedelta(seconds=lease_seconds),
                'updated_at': now,
            },
            '$inc': {'attempts': 1},
        },
        sort=[('priority', ASCENDING), ('created_at', ASCENDING)],
        return_document=ReturnDocument.AFTER,
    )


def extend(db, job, worker, lease_seconds=None):
    """
    Prolonge le bail d'une tâche en cours.

    À appeler passé la moitié du bail pour un traitement long. La condition sur
    `worker` empêche un worker de prolonger le bail d'un autre.
    """
    lease = lease_seconds or config.LEASE_SECONDS.get(job.get('type'), config.DEFAULT_LEASE)
    now = _now()
    result = db[config.COLL_JOBS].update_one(
        {'_id': job['_id'], 'worker': worker, 'state': 'reserved'},
        {'$set': {'lease_expires_at': now + datetime.timedelta(seconds=lease),
                  'updated_at': now}},
    )
    return result.modified_count == 1


def complete(db, job, worker, result=None):
    """Marque une tâche terminée. Sans effet si le bail a été repris entre-temps."""
    now = _now()
    outcome = db[config.COLL_JOBS].update_one(
        {'_id': job['_id'], 'worker': worker, 'state': 'reserved'},
        {'$set': {'state': 'done', 'updated_at': now, 'completed_at': now,
                  'result': result or {}, 'lease_expires_at': None}},
    )
    return outcome.modified_count == 1


def fail(db, job, worker, error):
    """
    Signale l'échec d'une tâche.

    Sous le plafond de tentatives, la tâche retourne en attente avec un repli
    exponentiel — ce délai évite qu'un worker s'acharne sur une tâche qui
    échoue en boucle. Au-delà, elle passe en échec définitif.
    """
    now = _now()
    attempts = job.get('attempts', 1)
    max_attempts = job.get('max_attempts', config.MAX_ATTEMPTS)
    message = str(error)[:500]

    if attempts < max_attempts:
        index = min(attempts - 1, len(config.BACKOFF_SECONDS) - 1)
        delay = config.BACKOFF_SECONDS[max(index, 0)]
        update = {'$set': {
            'state': 'pending',
            'worker': None,
            'lease_expires_at': None,
            'available_at': now + datetime.timedelta(seconds=delay),
            'updated_at': now,
            'last_error': {'message': message, 'at': now, 'attempt': attempts},
        }}
    else:
        update = {'$set': {
            'state': 'failed',
            'worker': None,
            'lease_expires_at': None,
            'updated_at': now,
            'last_error': {'message': message, 'at': now, 'attempt': attempts},
        }}

    outcome = db[config.COLL_JOBS].update_one(
        {'_id': job['_id'], 'worker': worker, 'state': 'reserved'}, update)
    return outcome.modified_count == 1


def stats(db):
    """Répartition des tâches par type et par état."""
    pipeline = [{'$group': {'_id': {'type': '$type', 'state': '$state'},
                            'n': {'$sum': 1}}}]
    table = {}
    for row in db[config.COLL_JOBS].aggregate(pipeline):
        key = row['_id']
        table.setdefault(key.get('type'), {})[key.get('state')] = row['n']
    return table


def reclaimable(db):
    """Nombre de tâches dont le bail a expiré et qui sont récupérables."""
    return db[config.COLL_JOBS].count_documents(
        {'state': 'reserved', 'lease_expires_at': {'$lt': _now()}})
