"""
Verrous de cycle et drapeau de pause.

Remplace les variables globales `is_running` et `stop_requested` du scraper,
inopérantes entre processus. Le verrou repose sur le même mécanisme atomique
que la file de travaux, et porte une expiration : un processus tué ne laisse
pas un verrou tenu indéfiniment.
"""

import contextlib
import datetime

from pymongo.errors import DuplicateKeyError

from . import config


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


def acquire(db, name, holder, ttl_seconds=None):
    """
    Tente de prendre un verrou nommé.

    Réussit si le verrou est libre ou si son détenteur précédent l'a laissé
    expirer. Retourne True en cas de succès.
    """
    ttl = ttl_seconds or config.LOCK_TTL_SECONDS
    now = _now()
    expires = now + datetime.timedelta(seconds=ttl)

    result = db[config.COLL_LOCKS].update_one(
        {'_id': name, 'expires_at': {'$lt': now}},
        {'$set': {'holder': holder, 'acquired_at': now, 'expires_at': expires}},
    )
    if result.modified_count == 1:
        return True

    # Verrou encore inexistant : l'insertion fait office de prise.
    try:
        db[config.COLL_LOCKS].insert_one(
            {'_id': name, 'holder': holder, 'acquired_at': now, 'expires_at': expires})
        return True
    except DuplicateKeyError:
        return False


def release(db, name, holder):
    """Libère un verrou. La condition sur le détenteur évite de libérer celui d'un autre."""
    result = db[config.COLL_LOCKS].update_one(
        {'_id': name, 'holder': holder},
        {'$set': {'expires_at': _now(), 'released_at': _now()}},
    )
    return result.modified_count == 1


def renew(db, name, holder, ttl_seconds=None):
    """Prolonge un verrou détenu, pour un cycle plus long que prévu."""
    ttl = ttl_seconds or config.LOCK_TTL_SECONDS
    result = db[config.COLL_LOCKS].update_one(
        {'_id': name, 'holder': holder},
        {'$set': {'expires_at': _now() + datetime.timedelta(seconds=ttl)}},
    )
    return result.modified_count == 1


def holder_of(db, name):
    """Détenteur actuel d'un verrou, ou None s'il est libre ou expiré."""
    doc = db[config.COLL_LOCKS].find_one({'_id': name})
    if not doc or doc.get('expires_at', _now()) < _now():
        return None
    return doc.get('holder')


class LockUnavailable(RuntimeError):
    """Levée lorsqu'un cycle est déjà en cours ailleurs."""


@contextlib.contextmanager
def cycle_lock(db, name, holder, ttl_seconds=None):
    """
    Contexte garantissant qu'un seul cycle du même nom s'exécute à la fois.

    Le verrou est libéré même si le bloc lève une exception.
    """
    if not acquire(db, name, holder, ttl_seconds):
        raise LockUnavailable(
            "cycle '%s' deja en cours (detenteur : %s)" % (name, holder_of(db, name)))
    try:
        yield
    finally:
        release(db, name, holder)


# ── Drapeau de pause ───────────────────────────────────────────────────

def paused(db):
    """Indique si les workers doivent s'arrêter entre deux tâches."""
    doc = db[config.COLL_CONTROL].find_one({'_id': 'pause'})
    return bool(doc and doc.get('active'))


def set_pause(db, active, reason=''):
    """Pose ou lève la pause. L'arrêt est propre : la tâche en cours va à son terme."""
    db[config.COLL_CONTROL].update_one(
        {'_id': 'pause'},
        {'$set': {'active': bool(active), 'reason': reason, 'updated_at': _now()}},
        upsert=True,
    )
