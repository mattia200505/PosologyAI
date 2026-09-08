"""
Point d'entrée en ligne de commande du socle de synchronisation.

    python -m sync.cli reconcile [--dry-run]
    python -m sync.cli probe [--limit N] [--sample N] [--dry-run]
    python -m sync.cli status
    python -m sync.cli pause [--off] [--reason "..."]

Aucune commande n'écrit dans `medicines` : la publication relève de P3.
"""

import argparse
import sys

from . import config, jobs, locks, probe, reconciliation


def _out(text=''):
    """Écrit sans échouer sur les consoles Windows en page de code héritée."""
    sys.stdout.write(str(text).encode(sys.stdout.encoding or 'utf-8',
                                      'replace').decode(sys.stdout.encoding or 'utf-8')
                     + '\n')


def cmd_reconcile(args):
    db = jobs.connect()
    jobs.ensure_indexes(db)
    holder = jobs.worker_identity()

    try:
        with locks.cycle_lock(db, config.LOCK_RECONCILIATION, holder):
            _out('Telechargement du catalogue officiel...')
            report = reconciliation.diff(db)
            totals = report['totals']

            _out('')
            _out('=== DIFFERENTIEL ===')
            _out('  catalogue officiel      : %s' % f"{totals['catalogue_officiel']:,}")
            _out('  base locale             : %s' % f"{totals['base_locale']:,}")
            _out('  creations               : %s' % f"{totals['creations']:,}")
            _out('    dont prioritaires     : %s' % f"{totals['creations_prioritaires']:,}")
            _out('  orphelins               : %s' % f"{totals['orphans']:,}")
            _out('  divergences             : %s' % f"{totals['divergences']:,}")
            for field, count in sorted(totals['divergences_par_champ'].items()):
                _out('    %-20s %s' % (field, f'{count:,}'))
            _out('  attributs a aligner     : %s' % f"{totals['attributs_a_aligner']:,}")

            if args.dry_run:
                _out('')
                _out('Mode simulation : aucune tache creee.')
                return 0

            outcome = reconciliation.enqueue(db, report)
            _out('')
            _out('=== FILE DE TRAVAUX ===')
            _out('  taches preparees : %s' % f"{outcome['taches_preparees']:,}")
            _out('  creees           : %s' % f"{outcome['creees']:,}")
            _out('  mises a jour     : %s' % f"{outcome['mises_a_jour']:,}")
            _out('  rearmees         : %s' % f"{outcome['rearmees']:,}")
            return 0
    except locks.LockUnavailable as error:
        _out('Refus : %s' % error)
        return 1


def cmd_probe(args):
    db = jobs.connect()
    jobs.ensure_indexes(db)
    holder = jobs.worker_identity()

    projection = {'url': 1, 'update_date': 1}
    if args.sample:
        pipeline = [{'$sample': {'size': args.sample}}, {'$project': projection}]
        documents = list(db[config.COLL_MEDICINES].aggregate(pipeline))
    else:
        cursor = db[config.COLL_MEDICINES].find({}, projection)
        if args.limit:
            cursor = cursor.limit(args.limit)
        documents = list(cursor)

    if not documents:
        _out('Aucune fiche a sonder.')
        return 0

    try:
        with locks.cycle_lock(db, config.LOCK_FULL_PROBE, holder):
            _out('Sondage de %s fiches (%d workers, %.0f ms entre requetes)...'
                 % (f'{len(documents):,}', config.WORKERS, config.REQUEST_INTERVAL * 1000))
            import time
            started = time.time()
            results = probe.run(db, documents)
            elapsed = time.time() - started

            official = None
            if args.cross_check:
                from . import ansm_dumps
                catalogue, _ = ansm_dumps.load_master()
                official = set(catalogue)

            verdict = probe.interpret(results, official)
            totals = verdict['totals']

            _out('')
            _out('=== SONDE ===')
            _out('  duree            : %.1f s (%.1f req/s)' % (elapsed, len(documents) / max(elapsed, 0.001)))
            _out('  taux extraction  : %.2f %%' % totals['taux_extraction'])
            _out('  taux anomalie    : %.2f %%   (signal d alerte)' % totals['taux_anomalie'])
            _out('  modifiees        : %s' % f"{totals['modifiees']:,}")
            _out('  inchangees       : %s' % f"{totals['inchangees']:,}")
            _out('  retirees         : %s' % f"{totals['retirees']:,}")
            _out('  anomalies        : %s' % f"{totals['anomalies']:,}")
            _out('  erreurs          : %s' % f"{totals['erreurs']:,}")

            if totals['anomalies']:
                _out('')
                _out('  ATTENTION : %d fiches presentes au catalogue sont illisibles.'
                     % totals['anomalies'])
                _out('  Verifier que la structure des pages ANSM n a pas change.')

            if args.dry_run:
                _out('')
                _out('Mode simulation : aucune tache creee.')
                return 0

            outcome = probe.enqueue(db, verdict)
            _out('')
            _out('  taches de rafraichissement : %s creees, %s mises a jour'
                 % (f"{outcome['creees']:,}", f"{outcome['mises_a_jour']:,}"))
            return 0
    except locks.LockUnavailable as error:
        _out('Refus : %s' % error)
        return 1


def cmd_simulate(args):
    """Calcule ce qu'une publication ferait, sans rien ecrire."""
    import datetime

    from . import ansm_dumps, publication

    db = jobs.connect()
    query = {'state': 'pending'}
    if args.type:
        query['type'] = args.type
    tasks = list(db[config.COLL_JOBS].find(query).limit(args.limit))
    if not tasks:
        _out('Aucune tache correspondante.')
        return 0

    catalogue = None
    if any(t['type'] in ('collecte_initiale', 'rafraichissement') for t in tasks):
        _out('Chargement du catalogue officiel...')
        catalogue, _ = ansm_dumps.load_master()

    session = None
    plans = []
    fetched = 0
    now = datetime.datetime.now(datetime.timezone.utc)

    for task in tasks:
        current = db[config.COLL_MEDICINES].find_one({'url': task.get('url')})
        job_type = task['type']

        if job_type == 'reparation_champ':
            source = publication.source_from_repair(task.get('payload'))
        elif job_type == 'verification_retrait':
            source = publication.source_from_withdrawal(now)
        elif job_type == 'enrichissement_catalogue':
            source = publication.source_from_catalogue(
                (task.get('payload') or {}).get('record') or {})
        else:
            if session is None:
                from . import probe as probe_module
                session = probe_module.build_session()
            try:
                response = session.get(task['url'], timeout=config.HTTP_TIMEOUT)
                fetched += 1
            except Exception as error:                      # noqa: BLE001
                _out('  echec reseau sur %s : %s' % (task['cis'], type(error).__name__))
                continue
            record = (catalogue or {}).get(task['cis'])
            source = publication.source_from_notice(
                response.content, task['url'],
                record if job_type == 'collecte_initiale' else None)

        plans.append(publication.plan(current, source, job_type, cis=task.get('cis')))

    known = sorted({field for plan_item in plans for field in plan_item['untouched']})
    compliant, details = publication.check_invariants(plans, known)

    by_type = {}
    for item in plans:
        entry = by_type.setdefault(item['job_type'],
                                   {'n': 0, 'ecrirait': 0, 'creerait': 0, 'ecarte': 0})
        entry['n'] += 1
        entry['ecrirait'] += 1 if item['would_write'] else 0
        entry['creerait'] += 1 if (not item['exists'] and item['would_write']) else 0
        entry['ecarte'] += 0 if item['viable'] else 1

    _out('')
    _out('=== SIMULATION SUR %d TACHES ===' % len(plans))
    if fetched:
        _out('  notices telechargees : %d' % fetched)
    for job_type in sorted(by_type):
        row = by_type[job_type]
        _out('  %-22s %4d tache(s) | %4d ecriraient | %4d creeraient | %4d ecartees'
             % (job_type, row['n'], row['ecrirait'], row['creerait'], row['ecarte']))

    discarded = [item for item in plans if not item['viable']]
    if discarded:
        motifs = {}
        for item in discarded:
            motifs[item['reason']] = motifs.get(item['reason'], 0) + 1
        _out('')
        _out('  ecartees, par motif :')
        for motif, count in sorted(motifs.items()):
            _out('    %-42s %d' % (motif, count))

    _out('')
    _out('=== CONTROLES OBLIGATOIRES ===')
    labels = {
        'hors_liste_blanche': 'chemins hors liste blanche',
        'champs_proteges_touches': 'champs proteges touches',
        'sous_documents_remplaces': 'sous-documents remplaces en entier',
        'champs_perdus': 'champs de premier niveau perdus',
        'sections_modifiees_par_reparation': 'sections modifiees par une reparation',
        'titre_modifie_par_rafraichissement': 'titre modifie par un rafraichissement',
    }
    for key, label in labels.items():
        found = details[key]
        _out('  [%s] %-42s %d' % ('OK' if not found else '!!', label, len(found)))
        if found:
            _out('       %s' % list(found)[:6])

    _out('')
    _out('  verdict : %s' % ('CONFORME' if compliant else 'NON CONFORME'))

    if args.show:
        _out('')
        _out('=== DETAIL DES %d PREMIERS PLANS ===' % min(args.show, len(plans)))
        for item in plans[:args.show]:
            _out('  CIS %s [%s] existe=%s ecrirait=%s'
                 % (item['cis'], item['job_type'], item['exists'], item['would_write']))
            for change in item['changes']:
                before = change['before']
                after = change['after']
                if isinstance(before, dict) and before.get('_resume'):
                    before = '<%s octets, %s>' % (before['octets'], before['empreinte'][:8])
                if isinstance(after, dict) and after.get('_resume'):
                    after = '<%s octets, %s>' % (after['octets'], after['empreinte'][:8])
                _out('     %-38s [%s]' % (change['path'], change['owner']))
                _out('       avant : %s' % str(before)[:88])
                _out('       apres : %s' % str(after)[:88])
            if item['untouched']:
                _out('     intacts : %s' % ', '.join(item['untouched']))

    _out('')
    _out('Aucune ecriture effectuee.')
    return 0 if compliant else 1


def _build_source(task, catalogue, session_holder, now):
    """Construit la source d'un plan. Peut effectuer une requête réseau."""
    from . import config as cfg
    from . import probe as probe_module
    from . import publication

    job_type = task['type']
    if job_type == 'reparation_champ':
        return publication.source_from_repair(task.get('payload')), False
    if job_type == 'verification_retrait':
        return publication.source_from_withdrawal(now), False
    if job_type == 'enrichissement_catalogue':
        return publication.source_from_catalogue(
            (task.get('payload') or {}).get('record') or {}), False

    if session_holder[0] is None:
        session_holder[0] = probe_module.build_session()
    response = session_holder[0].get(task['url'], timeout=cfg.HTTP_TIMEOUT)
    record = (catalogue or {}).get(task['cis'])
    return publication.source_from_notice(
        response.content, task['url'],
        record if job_type == 'collecte_initiale' else None), True


def cmd_publish(args):
    """Publie reellement dans medicines. Exige --confirm."""
    import datetime

    from . import ansm_dumps, history, publication

    db = jobs.connect()
    history.ensure_indexes(db)
    worker = jobs.worker_identity()

    query = {'state': 'pending'}
    if args.type:
        query['type'] = args.type
    tasks = list(db[config.COLL_JOBS].find(query).limit(args.limit))
    if not tasks:
        _out('Aucune tache correspondante.')
        return 0

    catalogue = None
    if any(t['type'] in ('collecte_initiale', 'rafraichissement') for t in tasks):
        _out('Chargement du catalogue officiel...')
        catalogue, _ = ansm_dumps.load_master()

    session_holder = [None]

    # Traitement en flux : chaque tâche est préparée puis publiée avant de
    # passer à la suivante. Tout charger d'abord aurait retenu jusqu'à 200 Ko
    # de sections par tâche en mémoire et laissé un long intervalle sans rien
    # de commité — donc rien de repris en cas d'interruption.
    created = updated = discarded = failed = 0
    examined = 0
    breaches = {}

    _out('')
    _out('=== PUBLICATION ===' if args.confirm else '=== SIMULATION ===')

    for task in tasks:
        now = datetime.datetime.now(datetime.timezone.utc)
        examined += 1
        current = db[config.COLL_MEDICINES].find_one({'url': task.get('url')})
        try:
            source, _ = _build_source(task, catalogue, session_holder, now)
        except Exception as error:                          # noqa: BLE001
            failed += 1
            _out('  echec de preparation sur %s : %s' % (task['cis'], type(error).__name__))
            continue

        item = publication.plan(current, source, task['type'], cis=task['cis'])

        compliant, details = publication.check_invariants([item], item['untouched'])
        if not compliant:
            failed += 1
            for key, found in details.items():
                if found:
                    breaches.setdefault(key, []).extend(found)
            _out('  CONTROLE ECHOUE sur %s : %s'
                 % (task['cis'], {k: v for k, v in details.items() if v}))
            continue

        if not item['viable']:
            discarded += 1
            if args.confirm:
                db[config.COLL_JOBS].update_one(
                    {'_id': task['_id']},
                    {'$set': {'state': 'cancelled', 'updated_at': now,
                              'lease_expires_at': None, 'worker': None,
                              'result': {'action': 'ecartee', 'motif': item['reason']}}})
            continue

        if not item['would_write']:
            continue

        if not args.confirm:
            created += 1 if not item['exists'] else 0
            updated += 1 if item['exists'] else 0
            continue

        try:
            outcome = publication.apply(db, item, current, source, task['cis'], worker)
            if outcome['action'] == 'creation':
                created += 1
            else:
                updated += 1
            db[config.COLL_JOBS].update_one(
                {'_id': task['_id']},
                {'$set': {'state': 'done', 'worker': worker, 'updated_at': now,
                          'completed_at': now, 'lease_expires_at': None,
                          'result': {'action': outcome['action']}}})
        except Exception as error:                          # noqa: BLE001
            failed += 1
            _out('  ECHEC sur %s : %s: %s' % (task['cis'], type(error).__name__, error))

        if args.progress and examined % args.progress == 0:
            _out('  ... %d/%d examinees | %d creees | %d ecartees | %d echecs'
                 % (examined, len(tasks), created, discarded, failed))

    if breaches:
        _out('')
        _out('  CONTROLES EN ECHEC : %s' % {k: len(v) for k, v in breaches.items()})

    _out('')
    _out('  examinees   : %d' % examined)
    _out('  creees      : %d' % created)
    _out('  mises a jour: %d' % updated)
    _out('  ecartees    : %d' % discarded)
    _out('  echecs      : %d' % failed)

    if not args.confirm:
        _out('')
        _out('Mode simulation (ajouter --confirm pour ecrire). Aucune ecriture.')
        return 0

    version = publication.bump_catalogue_version(db)
    _out('  version du catalogue : %d' % version)

    stats = history.stats(db)
    _out('')
    _out('=== HISTORIQUE ===')
    _out('  entrees : %d sur %d fiches, %.1f Ko'
         % (stats['entrees'], stats['fiches'], stats['octets'] / 1024))
    return 0


def cmd_rollback(args):
    """Retablit la version anterieure d'une fiche."""
    from . import history

    db = jobs.connect()
    available = history.versions(db, args.cis)
    if not available:
        _out('Aucune version enregistree pour le CIS %s.' % args.cis)
        return 1

    _out('=== VERSIONS DISPONIBLES POUR %s ===' % args.cis)
    for entry in available:
        _out('  %s  %-22s champs: %s'
             % (entry['published_at'].strftime('%Y-%m-%d %H:%M:%S'),
                entry['job_type'], ', '.join(entry['changed'])))

    if not args.confirm:
        _out('')
        _out('Mode simulation (ajouter --confirm pour restaurer). Aucune ecriture.')
        return 0

    restored = history.rollback(db, args.cis)
    _out('')
    _out('  %d chemin(s) restaure(s).' % (restored or 0))
    return 0


def cmd_propagate(args):
    """Propage les publications vers les index derives."""
    from . import propagation

    db = jobs.connect()
    query = {'_sync': {'$exists': True}} if args.only_new else None
    scope = 'fiches publiees par le socle' if args.only_new else 'toutes les fiches'

    if not (args.qdrant_rebuild or args.qdrant or args.neo4j or args.enrichment):
        _out('Preciser au moins une cible : --qdrant-rebuild, --qdrant, --neo4j ou --enrichment.')
        return 1

    if args.qdrant_rebuild:
        _out('=== QDRANT : RECONSTRUCTION ===')
        outcome = propagation.rebuild_qdrant(db)
        _out('  %s' % ('bascule effectuee' if outcome['ok'] else 'ECHEC, rien bascule'))
        if not outcome['ok']:
            return 1

    if args.qdrant:
        _out('=== QDRANT : INDEXATION INCREMENTALE (%s) ===' % scope)
        outcome = propagation.propagate_qdrant(db, query)
        _out('  indexees : %s | points %s -> %s'
             % (f"{outcome['indexees']:,}", f"{outcome['points_avant']:,}",
                f"{outcome['points_apres']:,}"))

    if args.enrichment:
        _out('=== DRUGBANK : APPARIEMENT DES FICHES NON ENRICHIES ===')
        outcome = propagation.propagate_enrichment(db)
        _out('  traitees : %s | appariees : %s | sans correspondance : %s'
             % (f"{outcome['traitees']:,}", f"{outcome['appariees']:,}",
                f"{outcome['sans_correspondance']:,}"))

    if args.neo4j:
        _out('=== NEO4J : FUSION (%s) ===' % scope)
        before = propagation.neo4j_counts()
        outcome = propagation.propagate_neo4j(db, query)
        if not outcome.get('ok'):
            _out('  %s' % outcome.get('motif'))
            return 1
        after = propagation.neo4j_counts()
        _out('  fusionnees : %s | echecs : %d'
             % (f"{outcome['fusionnees']:,}", outcome['echecs']))
        for label in sorted(after or {}):
            _out('  %-18s %s -> %s' % (label, f"{(before or {}).get(label, 0):,}",
                                       f"{after[label]:,}"))
    return 0


NIVEAU_MARQUE = {'critique': '!!', 'alerte': ' !', 'information': ' i'}


def cmd_cycle(args):
    """Execute un cycle complet, sans surveillance."""
    from . import cycle

    db = jobs.connect()

    if args.daily:
        args.reconcile, args.publish, args.propagate = True, args.publish or 500, True
    if args.weekly:
        args.reconcile, args.probe = True, True
        args.publish, args.propagate = args.publish or 1000, True

    _out('=== CYCLE DE SYNCHRONISATION ===')
    report = cycle.run(db,
                       do_reconcile=args.reconcile,
                       do_probe=args.probe,
                       publish_limit=args.publish,
                       do_propagate=args.propagate,
                       probe_sample=args.probe_sample,
                       emit=_out)

    _out('')
    _out('  statut : %s | duree : %.0f s' % (report['statut'], report.get('duree_s', 0)))
    if report.get('motif'):
        _out('  motif  : %s' % report['motif'])

    for name, entry in report['stages'].items():
        _out('')
        _out('  [%s] %s (%.0f s)' % (entry.get('statut'), name, entry.get('duree_s', 0)))
        for key, value in sorted(entry.items()):
            if key in ('statut', 'duree_s') or isinstance(value, (dict, list)):
                continue
            _out('      %-28s %s' % (key, f'{value:,}' if isinstance(value, int) else value))

    _out('')
    if report['alertes']:
        _out('=== ALERTES ===')
        for alert in report['alertes']:
            _out('  %s [%s] %s' % (NIVEAU_MARQUE.get(alert['niveau'], '  '),
                                   alert['code'], alert['message']))
    else:
        _out('=== AUCUNE ALERTE ===')

    critical = any(a['niveau'] == 'critique' for a in report['alertes'])
    return 2 if critical else (0 if report['statut'] in ('termine', 'suspendu') else 1)


def cmd_report(args):
    """Affiche l'historique des cycles."""
    from . import cycle

    db = jobs.connect()
    runs = cycle.history(db, args.limit)
    if not runs:
        _out('Aucun cycle enregistre.')
        return 0

    _out('=== DERNIERS CYCLES ===')
    for run in runs:
        started = run['demarre_le']
        _out('  %s  %-10s %6.0f s  etapes: %-42s alertes: %d'
             % (started.strftime('%Y-%m-%d %H:%M'), run.get('statut'),
                run.get('duree_s', 0),
                ', '.join('%s=%s' % (k, v.get('statut'))
                          for k, v in (run.get('stages') or {}).items())[:42],
                len(run.get('alertes') or [])))
        for alert in run.get('alertes') or []:
            _out('        %s [%s] %s' % (NIVEAU_MARQUE.get(alert['niveau'], '  '),
                                         alert['code'], alert['message'][:70]))
    return 0


def cmd_status(args):
    db = jobs.connect()
    table = jobs.stats(db)
    _out('=== FILE DE TRAVAUX ===')
    if not table:
        _out('  (vide)')
    else:
        states = ('pending', 'reserved', 'done', 'failed', 'cancelled')
        _out('  %-26s %s' % ('type', ''.join('%12s' % s for s in states)))
        for job_type in sorted(table):
            row = table[job_type]
            _out('  %-26s %s' % (job_type,
                                 ''.join('%12s' % f"{row.get(s, 0):,}" for s in states)))
    _out('')
    _out('  baux expires recuperables : %s' % f'{jobs.reclaimable(db):,}')
    _out('  pause active              : %s' % locks.paused(db))
    for name in (config.LOCK_RECONCILIATION, config.LOCK_FULL_PROBE):
        _out('  verrou %-18s %s' % (name, locks.holder_of(db, name) or 'libre'))
    return 0


def cmd_pause(args):
    db = jobs.connect()
    locks.set_pause(db, not args.off, args.reason)
    _out('Pause %s.' % ('levee' if args.off else 'posee'))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog='sync', description='Socle de synchronisation MedicSearch')
    sub = parser.add_subparsers(dest='command', required=True)

    p = sub.add_parser('reconcile', help='differentiel catalogue officiel / base')
    p.add_argument('--dry-run', action='store_true', help='ne cree aucune tache')
    p.set_defaults(func=cmd_reconcile)

    p = sub.add_parser('probe', help='sonde de revision des notices')
    p.add_argument('--limit', type=int, help='limiter aux N premieres fiches')
    p.add_argument('--sample', type=int, help='echantillon aleatoire de N fiches')
    p.add_argument('--cross-check', action='store_true',
                   help='croiser avec le catalogue pour distinguer retrait et anomalie')
    p.add_argument('--dry-run', action='store_true', help='ne cree aucune tache')
    p.set_defaults(func=cmd_probe)

    p = sub.add_parser('simulate', help='calcule ce qu une publication ferait, sans ecrire')
    p.add_argument('--type', choices=config.JOB_TYPES, help='restreindre a un type de tache')
    p.add_argument('--limit', type=int, default=20, help='nombre de taches (defaut 20)')
    p.add_argument('--show', type=int, default=0, help='detailler les N premiers plans')
    p.set_defaults(func=cmd_simulate)

    p = sub.add_parser('publish', help='publie dans medicines (exige --confirm)')
    p.add_argument('--type', choices=config.JOB_TYPES, help='restreindre a un type de tache')
    p.add_argument('--limit', type=int, default=10, help='nombre de taches (defaut 10)')
    p.add_argument('--confirm', action='store_true',
                   help='ecrire reellement ; sans ce drapeau, simulation')
    p.add_argument('--progress', type=int, default=0,
                   help='afficher l avancement toutes les N taches')
    p.set_defaults(func=cmd_publish)

    p = sub.add_parser('rollback', help='retablit la version anterieure d une fiche')
    p.add_argument('cis', help='code CIS de la fiche')
    p.add_argument('--confirm', action='store_true', help='restaurer reellement')
    p.set_defaults(func=cmd_rollback)

    p = sub.add_parser('propagate', help='propage vers Qdrant et Neo4j')
    p.add_argument('--qdrant-rebuild', action='store_true',
                   help='reconstruit l index vectoriel dans une collection neuve puis bascule')
    p.add_argument('--qdrant', action='store_true', help='indexation incrementale Qdrant')
    p.add_argument('--neo4j', action='store_true', help='fusion des fiches dans le graphe')
    p.add_argument('--enrichment', action='store_true',
                   help='apparie a DrugBank les fiches non encore enrichies')
    p.add_argument('--only-new', action='store_true',
                   help='restreindre aux fiches publiees par le socle')
    p.set_defaults(func=cmd_propagate)

    p = sub.add_parser('cycle', help='cycle complet sans surveillance')
    p.add_argument('--daily', action='store_true',
                   help='preset quotidien : reconciliation, publication, propagation')
    p.add_argument('--weekly', action='store_true',
                   help='preset hebdomadaire : ajoute la sonde de revision')
    p.add_argument('--reconcile', action='store_true')
    p.add_argument('--probe', action='store_true')
    p.add_argument('--probe-sample', type=int,
                   help='limiter la sonde a un echantillon')
    p.add_argument('--publish', type=int, default=0,
                   help='nombre de taches hors reseau a publier')
    p.add_argument('--propagate', action='store_true')
    p.set_defaults(func=cmd_cycle)

    p = sub.add_parser('report', help='historique des cycles')
    p.add_argument('--limit', type=int, default=10)
    p.set_defaults(func=cmd_report)

    p = sub.add_parser('status', help='etat de la file et des verrous')
    p.set_defaults(func=cmd_status)

    p = sub.add_parser('pause', help='poser ou lever la pause des workers')
    p.add_argument('--off', action='store_true', help='lever la pause')
    p.add_argument('--reason', default='', help='motif consigne')
    p.set_defaults(func=cmd_pause)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == '__main__':
    sys.exit(main())
