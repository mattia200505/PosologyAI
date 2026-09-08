"""
Vérification des invariants du socle d'exécution.

Contrôle les garanties de concurrence énoncées dans les spécifications P2 :
réservation exclusive entre processus, reprise après interruption, exclusion
mutuelle des cycles.

Tout se déroule dans une base dédiée, jamais dans `medicsearch` :

    python -m sync.selftest
"""

import multiprocessing
import sys
import time

from . import config, jobs, locks

TEST_DB = 'medicsearch_synctest'


def _out(text=''):
    encoding = sys.stdout.encoding or 'utf-8'
    sys.stdout.write(str(text).encode(encoding, 'replace').decode(encoding) + '\n')


def _use_test_db():
    """Bascule le paquet sur la base de test. Appelé aussi dans les sous-processus."""
    config.DB_NAME = TEST_DB
    return jobs.connect()


def _drain(worker_index, count, queue):
    """Sous-processus : réserve et achève des tâches jusqu'à épuisement."""
    db = _use_test_db()
    worker = 'worker-%d' % worker_index
    seen = []
    idle = 0
    while len(seen) < count and idle < 20:
        job = jobs.reserve(db, worker, types=['rafraichissement'])
        if job is None:
            idle += 1
            time.sleep(0.02)
            continue
        idle = 0
        seen.append(job['_id'])
        jobs.complete(db, job, worker, {'par': worker})
    queue.put((worker, seen))


def _grab_lock(worker_index, queue):
    """Sous-processus : tente de prendre le verrou de réconciliation."""
    db = _use_test_db()
    holder = 'lock-worker-%d' % worker_index
    queue.put((holder, locks.acquire(db, config.LOCK_RECONCILIATION, holder, ttl_seconds=60)))


def test_exclusive_reservation(db, total=500, workers=2):
    """Deux processus concurrents ne doivent jamais réserver la même tâche."""
    db[config.COLL_JOBS].delete_many({})
    jobs.add_many(db, [jobs.build('rafraichissement', 'T%05d' % i, url='http://test/%d' % i)
                       for i in range(total)])

    queue = multiprocessing.Queue()
    procs = [multiprocessing.Process(target=_drain, args=(i, total, queue))
             for i in range(workers)]
    started = time.time()
    for p in procs:
        p.start()
    collected = [queue.get() for _ in procs]
    for p in procs:
        p.join(timeout=60)
    elapsed = time.time() - started

    all_ids, per_worker = [], {}
    for name, ids in collected:
        per_worker[name] = len(ids)
        all_ids.extend(ids)

    duplicates = len(all_ids) - len(set(all_ids))
    done = db[config.COLL_JOBS].count_documents({'state': 'done'})

    ok = duplicates == 0 and len(set(all_ids)) == total and done == total
    _out('  reservees au total   : %d' % len(all_ids))
    _out('  distinctes           : %d / %d' % (len(set(all_ids)), total))
    _out('  doublons             : %d   (exige 0)' % duplicates)
    _out('  repartition          : %s' % per_worker)
    _out('  achevees en base     : %d' % done)
    _out('  duree                : %.2f s' % elapsed)
    return ok


def test_resume_after_crash(db):
    """Une tâche dont le worker meurt doit redevenir réservable à l'expiration du bail."""
    db[config.COLL_JOBS].delete_many({})
    jobs.add_many(db, [jobs.build('rafraichissement', 'CRASH1', url='http://test/crash')])

    job = jobs.reserve(db, 'worker-mort', types=['rafraichissement'], lease_seconds=1)
    reserved_ok = job is not None

    immediately = jobs.reserve(db, 'worker-vivant', types=['rafraichissement'])
    protected = immediately is None          # bail encore valide : personne d'autre ne l'obtient

    time.sleep(1.3)                          # on laisse le bail expirer
    reclaimable = jobs.reclaimable(db)
    recovered = jobs.reserve(db, 'worker-vivant', types=['rafraichissement'])
    recovered_ok = recovered is not None and recovered['_id'] == job['_id']
    attempts_ok = recovered is not None and recovered['attempts'] == 2

    _out('  reservation initiale        : %s' % reserved_ok)
    _out('  protegee pendant le bail    : %s' % protected)
    _out('  recuperables apres expiration: %d' % reclaimable)
    _out('  reprise par un autre worker : %s' % recovered_ok)
    _out('  compteur de tentatives      : %s (attendu 2)'
         % (recovered['attempts'] if recovered else '-'))
    return reserved_ok and protected and recovered_ok and attempts_ok


def test_backoff(db):
    """Après un échec, la tâche n'est pas resservie avant son délai de repli."""
    db[config.COLL_JOBS].delete_many({})
    jobs.add_many(db, [jobs.build('rafraichissement', 'RETRY1', url='http://test/retry')])

    job = jobs.reserve(db, 'w1', types=['rafraichissement'])
    jobs.fail(db, job, 'w1', 'panne simulee')
    state = db[config.COLL_JOBS].find_one({'_id': job['_id']})

    immediate = jobs.reserve(db, 'w2', types=['rafraichissement'])
    deferred = immediate is None             # available_at repousse la remise en service

    _out('  etat apres echec       : %s (attendu pending)' % state['state'])
    _out('  tentatives             : %d' % state['attempts'])
    _out('  differee par le repli  : %s' % deferred)
    _out('  erreur consignee       : %s' % bool(state.get('last_error')))
    return state['state'] == 'pending' and deferred and bool(state.get('last_error'))


def test_exhaustion(db):
    """Au-delà du plafond de tentatives, la tâche passe en échec définitif."""
    db[config.COLL_JOBS].delete_many({})
    jobs.add_many(db, [jobs.build('rafraichissement', 'DEAD1', url='http://test/dead')])

    for _ in range(config.MAX_ATTEMPTS):
        db[config.COLL_JOBS].update_one({'_id': 'rafraichissement:DEAD1'},
                                        {'$set': {'available_at': jobs._now()}})
        job = jobs.reserve(db, 'w', types=['rafraichissement'])
        if job is None:
            break
        jobs.fail(db, job, 'w', 'echec repete')

    state = db[config.COLL_JOBS].find_one({'_id': 'rafraichissement:DEAD1'})
    _out('  etat final   : %s (attendu failed)' % state['state'])
    _out('  tentatives   : %d / %d' % (state['attempts'], config.MAX_ATTEMPTS))
    return state['state'] == 'failed'


def test_idempotent_enqueue(db):
    """Rejouer une détection ne doit pas dupliquer les tâches."""
    db[config.COLL_JOBS].delete_many({})
    batch = [jobs.build('collecte_initiale', 'IDEM%03d' % i) for i in range(50)]
    first_created, _ = jobs.add_many(db, batch)
    second_created, second_updated = jobs.add_many(db, batch)
    total = db[config.COLL_JOBS].count_documents({})

    _out('  premier passage  : %d creees' % first_created)
    _out('  second passage   : %d creees, %d mises a jour' % (second_created, second_updated))
    _out('  total en base    : %d (attendu 50)' % total)
    return first_created == 50 and second_created == 0 and total == 50


def test_no_rearm_of_done(db):
    """Une tâche déjà traitée ne doit pas être réarmée par une redétection."""
    db[config.COLL_JOBS].delete_many({})
    jobs.add_many(db, [jobs.build('rafraichissement', 'KEEP1', url='http://test/keep')])
    job = jobs.reserve(db, 'w', types=['rafraichissement'])
    jobs.complete(db, job, 'w')

    jobs.add_many(db, [jobs.build('rafraichissement', 'KEEP1', url='http://test/keep')])
    state = db[config.COLL_JOBS].find_one({'_id': 'rafraichissement:KEEP1'})

    _out('  etat apres redetection : %s (attendu done)' % state['state'])
    return state['state'] == 'done'


def test_cycle_lock(db, workers=4):
    """Un seul processus doit obtenir le verrou de cycle."""
    db[config.COLL_LOCKS].delete_many({})
    queue = multiprocessing.Queue()
    procs = [multiprocessing.Process(target=_grab_lock, args=(i, queue))
             for i in range(workers)]
    for p in procs:
        p.start()
    outcomes = [queue.get() for _ in procs]
    for p in procs:
        p.join(timeout=30)

    winners = [name for name, ok in outcomes if ok]
    _out('  candidats : %d' % workers)
    _out('  obtenu    : %d (exige 1) -> %s' % (len(winners), winners))

    # Relecture du détenteur : vérifie que les dates relues restent comparables
    holder = locks.holder_of(db, config.LOCK_RECONCILIATION)
    _out('  detenteur relu : %s' % holder)

    released = locks.release(db, config.LOCK_RECONCILIATION, winners[0]) if winners else False
    freed = locks.holder_of(db, config.LOCK_RECONCILIATION) is None
    _out('  libere puis relu comme libre : %s' % (released and freed))
    return len(winners) == 1 and holder == winners[0] and released and freed


def test_alerts(db):
    """
    Une panne doit lever une alerte, pas passer pour un succès.

    Le cas le plus trompeur est un cycle qui se termine normalement alors que
    la structure des pages ANSM a changé : la sonde ne lit plus aucune date,
    donc rien n'est signalé comme modifié, et le compte rendu paraît sain.
    C'est le taux d'anomalie qui doit trahir la situation.
    """
    from . import cycle

    db[config.COLL_JOBS].delete_many({})
    cases = []

    # Structure ANSM modifiée : le cycle "réussit" mais n'a rien pu lire
    structure = {'statut': 'termine', 'duree_s': 60, 'stages': {
        'sonde': {'statut': 'ok', 'taux_anomalie': 12.5, 'taux_extraction': 87.5,
                  'modifiees': 0}}}
    alerts = cycle.evaluate(db, structure)
    codes = {a['code'] for a in alerts}
    cases.append(('changement de structure ANSM', 'structure_ansm' in codes
                  and any(a['niveau'] == 'critique' for a in alerts)))

    # Index désynchronisé
    desync = {'statut': 'termine', 'duree_s': 10, 'stages': {
        'convergence': {'statut': 'ok', 'medicines': 12046, 'qdrant': 9804,
                        'ecarts': {'qdrant': 2242}}}}
    codes = {a['code'] for a in cycle.evaluate(db, desync)}
    cases.append(('index desynchronise', 'index_desynchronise' in codes))

    # Index injoignable
    unreachable = {'statut': 'termine', 'duree_s': 10, 'stages': {
        'convergence': {'statut': 'ok', 'medicines': 12046, 'qdrant': None,
                        'ecarts': {}}}}
    codes = {a['code'] for a in cycle.evaluate(db, unreachable)}
    cases.append(('index injoignable', 'index_injoignable' in codes))

    # Cycle en échec
    broken = {'statut': 'echec', 'motif': 'ConnectionError: refus', 'duree_s': 3,
              'stages': {}}
    alerts = cycle.evaluate(db, broken)
    cases.append(('cycle en echec', any(a['code'] == 'cycle_en_echec'
                                        and a['niveau'] == 'critique' for a in alerts)))

    # Tâches en échec au-delà du seuil
    jobs.add_many(db, [jobs.build('rafraichissement', 'F%04d' % i)
                       for i in range(config.ALERT_FAILED_JOBS + 5)])
    db[config.COLL_JOBS].update_many({}, {'$set': {'state': 'failed'}})
    codes = {a['code'] for a in cycle.evaluate(db, {'statut': 'termine',
                                                   'duree_s': 5, 'stages': {}})}
    cases.append(('taches en echec', 'taches_en_echec' in codes))
    db[config.COLL_JOBS].delete_many({})

    # Cycle sain : aucune alerte
    healthy = {'statut': 'termine', 'duree_s': 60, 'stages': {
        'sonde': {'statut': 'ok', 'taux_anomalie': 0.0, 'taux_extraction': 100.0},
        'convergence': {'statut': 'ok', 'medicines': 12046, 'qdrant': 12046,
                        'neo4j': 12046, 'ecarts': {}}}}
    cases.append(('cycle sain sans alerte', not cycle.evaluate(db, healthy)))

    for label, ok in cases:
        _out('  [%s] %s' % ('OK' if ok else '  ', label))
    return all(ok for _, ok in cases)


def test_pause_suspends_cycle(db):
    """Le drapeau de pause doit arrêter un cycle avant toute action."""
    from . import cycle

    locks.set_pause(db, True, 'test')
    report = cycle.run(db, do_reconcile=True, emit=lambda *a: None)
    suspended = report['statut'] == 'suspendu' and not report['stages']
    locks.set_pause(db, False)

    _out('  statut du cycle : %s (attendu suspendu)' % report['statut'])
    _out('  etapes executees : %d (attendu 0)' % len(report['stages']))
    return suspended


def main():
    _out('Base de test : %s  (la base de production n est jamais touchee)' % TEST_DB)
    db = _use_test_db()
    jobs.ensure_indexes(db)

    checks = [
        ('Reservation exclusive entre 2 processus', lambda: test_exclusive_reservation(db)),
        ('Reprise apres mort d un worker', lambda: test_resume_after_crash(db)),
        ('Repli exponentiel apres echec', lambda: test_backoff(db)),
        ('Echec definitif au plafond de tentatives', lambda: test_exhaustion(db)),
        ('Alimentation idempotente de la file', lambda: test_idempotent_enqueue(db)),
        ('Pas de rearmement d une tache terminee', lambda: test_no_rearm_of_done(db)),
        ('Exclusion mutuelle du verrou de cycle', lambda: test_cycle_lock(db)),
        ('Les pannes levent une alerte', lambda: test_alerts(db)),
        ('La pause suspend le cycle', lambda: test_pause_suspends_cycle(db)),
    ]

    results = []
    for title, check in checks:
        _out('')
        _out('=== %s ===' % title)
        try:
            ok = bool(check())
        except Exception as error:                  # noqa: BLE001
            _out('  EXCEPTION : %s: %s' % (type(error).__name__, error))
            ok = False
        results.append((title, ok))
        _out('  --> %s' % ('CONFORME' if ok else 'NON CONFORME'))

    db.client.drop_database(TEST_DB)

    _out('')
    _out('=== SYNTHESE ===')
    for title, ok in results:
        _out('  [%s] %s' % ('OK' if ok else '  ', title))
    passed = sum(1 for _, ok in results if ok)
    _out('')
    _out('  %d / %d invariants verifies' % (passed, len(results)))
    _out('  base de test supprimee')
    return 0 if passed == len(results) else 1


if __name__ == '__main__':
    sys.exit(main())
