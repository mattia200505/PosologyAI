"""
Cycle de synchronisation complet, métriques et alertes.

Enchaîne les composants des phases précédentes sous un verrou unique, mesure
chaque étape, consigne un rapport et évalue les conditions d'alerte.

Le cycle est conçu pour tourner sans surveillance. Ce qui suppose deux choses :
qu'une interruption ne perde rien — garanti par la file de travaux de P2 — et
qu'une panne se signale au lieu de passer inaperçue. C'est l'objet des alertes
de la section correspondante : un cycle qui « réussit » en ne traitant rien
parce que la structure des pages ANSM a changé doit lever une alerte, pas
renvoyer un compte rendu vert.
"""

import datetime
import time

from . import config, jobs, locks


class Stage:
    """Mesure la durée d'une étape et capture son éventuel échec."""

    def __init__(self, report, name):
        self.report = report
        self.name = name
        self.started = None

    def __enter__(self):
        self.started = time.time()
        self.report['stages'][self.name] = {'statut': 'en_cours'}
        return self.report['stages'][self.name]

    def __exit__(self, exc_type, exc, tb):
        entry = self.report['stages'][self.name]
        entry['duree_s'] = round(time.time() - self.started, 1)
        if exc_type is None:
            entry['statut'] = 'ok'
        else:
            entry['statut'] = 'echec'
            entry['erreur'] = '%s: %s' % (exc_type.__name__, str(exc)[:300])
        return False        # l'exception remonte : un échec d'étape arrête le cycle


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


def run(db, do_reconcile=True, do_probe=False, publish_limit=0,
        do_propagate=False, probe_sample=None, emit=print):
    """
    Exécute un cycle. Retourne le rapport, qui est aussi consigné en base.

    `probe_sample` limite la sonde à un échantillon — utile pour un cycle de
    contrôle rapide sans parcourir les 12 000 notices.
    """
    from . import probe, propagation, reconciliation

    report = {
        'demarre_le': _now(),
        'worker': jobs.worker_identity(),
        'parametres': {'reconcile': do_reconcile, 'probe': do_probe,
                       'publish_limit': publish_limit, 'propagate': do_propagate,
                       'probe_sample': probe_sample},
        'stages': {},
        'alertes': [],
    }

    if locks.paused(db):
        report['statut'] = 'suspendu'
        report['termine_le'] = _now()
        _persist(db, report)
        emit('Cycle suspendu : le drapeau de pause est pose.')
        return report

    jobs.ensure_indexes(db)

    try:
        with locks.cycle_lock(db, config.LOCK_CYCLE, report['worker']):
            if do_reconcile:
                with Stage(report, 'reconciliation') as entry:
                    emit('  reconciliation...')
                    diff = reconciliation.diff(db)
                    outcome = reconciliation.enqueue(db, diff)
                    entry.update(diff['totals'])
                    entry.update(outcome)

            if do_probe:
                with Stage(report, 'sonde') as entry:
                    emit('  sonde de revision...')
                    projection = {'url': 1, 'update_date': 1}
                    if probe_sample:
                        documents = list(db[config.COLL_MEDICINES].aggregate(
                            [{'$sample': {'size': probe_sample}},
                             {'$project': projection}]))
                    else:
                        documents = list(db[config.COLL_MEDICINES].find({}, projection))
                    results = probe.run(db, documents)
                    catalogue, _ = _catalogue(db)
                    verdict = probe.interpret(results, catalogue)
                    entry.update(verdict['totals'])
                    entry.update(probe.enqueue(db, verdict))

            if publish_limit:
                with Stage(report, 'publication') as entry:
                    emit('  publication...')
                    entry.update(_publish(db, publish_limit, report['worker']))

            if do_propagate:
                with Stage(report, 'propagation') as entry:
                    emit('  propagation...')
                    entry.update(propagation.propagate_qdrant(
                        db, {'_sync': {'$exists': True}}))

            with Stage(report, 'convergence') as entry:
                entry.update(convergence(db))

        report['statut'] = 'termine'
    except locks.LockUnavailable as error:
        report['statut'] = 'refuse'
        report['motif'] = str(error)
    except Exception as error:                              # noqa: BLE001
        report['statut'] = 'echec'
        report['motif'] = '%s: %s' % (type(error).__name__, str(error)[:300])

    report['termine_le'] = _now()
    report['duree_s'] = round((report['termine_le'] - report['demarre_le']).total_seconds(), 1)
    report['alertes'] = evaluate(db, report)
    _persist(db, report)
    return report


def _catalogue(db):
    from . import ansm_dumps
    catalogue, meta = ansm_dumps.load_master()
    return set(catalogue), meta


def _publish(db, limit, worker):
    """
    Publie les tâches en attente, sans accès réseau.

    Le cycle automatique se limite volontairement aux types hors réseau :
    les réparations et les constats de retrait. Les collectes et
    rafraîchissements téléchargent des notices et méritent une exécution
    surveillée, avec ses paliers.
    """
    from . import publication

    offline = ('reparation_champ', 'verification_retrait', 'enrichissement_catalogue')
    tasks = list(db[config.COLL_JOBS].find(
        {'state': 'pending', 'type': {'$in': list(offline)}}).limit(limit))

    now = _now()
    published = failed = breached = 0
    for task in tasks:
        current = db[config.COLL_MEDICINES].find_one({'url': task.get('url')})
        if task['type'] == 'reparation_champ':
            source = publication.source_from_repair(task.get('payload'))
        elif task['type'] == 'enrichissement_catalogue':
            # La valeur cible est portée par la tâche : aucun téléchargement.
            source = publication.source_from_catalogue(
                (task.get('payload') or {}).get('record') or {})
        else:
            source = publication.source_from_withdrawal(now)

        item = publication.plan(current, source, task['type'], cis=task['cis'])
        compliant, _ = publication.check_invariants([item], item['untouched'])
        if not compliant:
            breached += 1
            continue
        if not item['would_write']:
            continue
        try:
            publication.apply(db, item, current, source, task['cis'], worker)
            db[config.COLL_JOBS].update_one(
                {'_id': task['_id']},
                {'$set': {'state': 'done', 'updated_at': now, 'completed_at': now,
                          'worker': worker, 'lease_expires_at': None}})
            published += 1
        except Exception:                                   # noqa: BLE001
            failed += 1

    if published:
        publication.bump_catalogue_version(db)
    return {'examinees': len(tasks), 'publiees': published,
            'echecs': failed, 'controles_en_echec': breached}


def convergence(db):
    """Compare la source et ses index dérivés."""
    total = db[config.COLL_MEDICINES].count_documents({})
    state = {'medicines': total,
             'medicine_enrichment': db.medicine_enrichment.count_documents({})}

    try:
        from qdrant_client import QdrantClient
        client = QdrantClient(host='127.0.0.1', port=6333, timeout=30)
        state['qdrant'] = client.get_collection('medicines').points_count
    except Exception:                                       # noqa: BLE001
        state['qdrant'] = None

    try:
        from . import propagation
        counts = propagation.neo4j_counts() or {}
        state['neo4j'] = counts.get('Medicine')
    except Exception:                                       # noqa: BLE001
        state['neo4j'] = None

    state['ecarts'] = {name: total - value
                       for name, value in state.items()
                       if name != 'medicines' and isinstance(value, int) and value != total}
    return state


# ── Alertes ────────────────────────────────────────────────────────────

def evaluate(db, report):
    """
    Évalue les conditions d'alerte sur un rapport de cycle.

    Une alerte n'est pas une erreur : elle signale ce qui doit être regardé.
    L'absence d'alerte sur un cycle qui n'a rien traité serait au contraire
    le symptôme le plus trompeur — d'où la condition sur le taux d'anomalie.
    """
    alerts = []

    if report.get('statut') == 'echec':
        alerts.append({'niveau': 'critique', 'code': 'cycle_en_echec',
                       'message': report.get('motif', '')})

    sonde = report['stages'].get('sonde') or {}
    if sonde.get('statut') == 'ok':
        anomaly = sonde.get('taux_anomalie')
        if anomaly is not None and anomaly > config.ALERT_ANOMALY_RATE:
            alerts.append({
                'niveau': 'critique', 'code': 'structure_ansm',
                'message': "taux d'anomalie %.2f %% au-dessus du seuil %.2f %% : "
                           "des fiches presentes au catalogue sont devenues illisibles"
                           % (anomaly, config.ALERT_ANOMALY_RATE)})
        extraction = sonde.get('taux_extraction')
        if extraction is not None and extraction < config.ALERT_EXTRACTION_RATE:
            alerts.append({
                'niveau': 'alerte', 'code': 'extraction_degradee',
                'message': "taux d'extraction %.2f %% sous le seuil %.2f %%"
                           % (extraction, config.ALERT_EXTRACTION_RATE)})

    failed = db[config.COLL_JOBS].count_documents({'state': 'failed'})
    if failed > config.ALERT_FAILED_JOBS:
        alerts.append({'niveau': 'alerte', 'code': 'taches_en_echec',
                       'message': '%d taches en echec definitif' % failed})

    pending = db[config.COLL_JOBS].count_documents({'state': 'pending'})
    if pending > config.ALERT_PENDING_GROWTH:
        alerts.append({'niveau': 'alerte', 'code': 'file_qui_enfle',
                       'message': '%d taches en attente' % pending})

    conv = report['stages'].get('convergence') or {}
    for name, gap in (conv.get('ecarts') or {}).items():
        alerts.append({'niveau': 'alerte', 'code': 'index_desynchronise',
                       'message': '%s accuse %d fiches d ecart avec la source' % (name, gap)})
    for name in ('qdrant', 'neo4j'):
        if conv.get(name) is None and conv:
            alerts.append({'niveau': 'alerte', 'code': 'index_injoignable',
                           'message': '%s injoignable pendant le cycle' % name})

    duration = report.get('duree_s') or 0
    if duration > config.ALERT_CYCLE_MINUTES * 60:
        alerts.append({'niveau': 'information', 'code': 'cycle_long',
                       'message': 'cycle de %.0f min' % (duration / 60)})

    return alerts


def _persist(db, report):
    db[config.COLL_RUNS].insert_one(dict(report))


def history(db, limit=10):
    return list(db[config.COLL_RUNS].find().sort('demarre_le', -1).limit(limit))
