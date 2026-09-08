"""
Sonde de révision des notices.

Le dump officiel ne porte aucune date de révision de notice : sa seule date
est celle de l'AMM, qui ne suit pas les mises à jour du texte (vérifié en
phase P1 : concordance dans 1,1 % des cas seulement). Le seul signal
disponible est la page elle-même.

L'extraction se fait au niveau octet, sur la réponse brute. Les pages mêlent
les encodages — le « à » de « Mis à jour » est en UTF-8 alors qu'une lecture
latin-1 est nécessaire ailleurs — si bien qu'une expression régulière
appliquée au texte décodé échoue systématiquement. Appliquée aux octets, elle
atteint 100 % de réussite sur 200 fiches.
"""

import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import requests

from . import config, jobs
from .reconciliation import extract_cis

DATE_MARKER = re.compile(rb'ANSM.{0,30}?jour le\s*:?\s*(\d{2}/\d{2}/\d{4})', re.S)


class Pacer:
    """Cadence globale partagée par tous les workers."""

    def __init__(self, interval=None):
        self.interval = interval if interval is not None else config.REQUEST_INTERVAL
        self._lock = threading.Lock()
        self._last = 0.0

    def wait(self):
        with self._lock:
            elapsed = time.monotonic() - self._last
            if elapsed < self.interval:
                time.sleep(self.interval - elapsed)
            self._last = time.monotonic()


def extract_date(raw):
    """Extrait la date de révision d'une réponse brute, ou None."""
    found = DATE_MARKER.search(raw)
    return found.group(1).decode('ascii') if found else None


def probe_one(url, session, pacer):
    """
    Interroge une notice et retourne (état, date, octets).

    États possibles : ok, date_absente, http_<code>, timeout, <exception>.
    """
    pacer.wait()
    try:
        response = session.get(url, timeout=config.HTTP_TIMEOUT)
    except requests.exceptions.Timeout:
        return 'timeout', None, 0
    except Exception as error:                      # noqa: BLE001 - état remonté tel quel
        return type(error).__name__, None, 0

    if response.status_code != 200:
        return 'http_%d' % response.status_code, None, len(response.content)

    date = extract_date(response.content)
    if date is None:
        return 'date_absente', None, len(response.content)
    return 'ok', date, len(response.content)


def build_session():
    session = requests.Session()
    session.headers.update({'User-Agent': config.USER_AGENT})
    return session


def run(db, documents, workers=None, pacer=None, session=None):
    """
    Sonde une liste de fiches et retourne les résultats bruts. N'écrit rien.

    `documents` : itérable de dicts portant au moins `url` et `update_date`.
    """
    documents = list(documents)
    pacer = pacer or Pacer()
    session = session or build_session()
    limit = workers or config.WORKERS

    def handle(document):
        url = document.get('url')
        state, date, size = probe_one(url, session, pacer)
        return {
            'cis': extract_cis(url),
            'url': url,
            'state': state,
            'date_source': date,
            'date_base': (document.get('update_date') or '').strip(),
            'bytes': size,
        }

    with ThreadPoolExecutor(max_workers=limit) as pool:
        return list(pool.map(handle, documents))


def interpret(results, official_ids=None):
    """
    Classe les résultats.

    La sonde seule ne distingue pas un retrait d'une panne d'extraction : les
    deux se présentent comme une page à 200 sans marqueur de date. Croisée avec
    le catalogue officiel, la distinction devient nette — c'est la garantie
    principale contre une évolution silencieuse de la structure des pages.
    """
    changed, unchanged, withdrawn, broken, errors = [], [], [], [], []

    for item in results:
        state = item['state']
        if state == 'ok':
            (changed if item['date_source'] != item['date_base'] else unchanged).append(item)
        elif state == 'date_absente':
            known = official_ids is not None and item['cis'] in official_ids
            if known:
                broken.append(item)          # présent au catalogue mais illisible : anomalie
            else:
                withdrawn.append(item)       # absent du catalogue : retrait attendu
        else:
            errors.append(item)

    readable = len(changed) + len(unchanged)
    total = len(results)

    # Une fiche retirée du catalogue n'a légitimement pas de date : la compter
    # comme un échec déprimerait le taux sans qu'aucune anomalie n'existe.
    # Le signal d'alerte est donc le taux d'anomalie, calculé sur les seules
    # fiches encore au catalogue.
    catalogued = total - len(withdrawn)

    return {
        'changed': changed,
        'unchanged': unchanged,
        'withdrawn': withdrawn,
        'broken': broken,
        'errors': errors,
        'totals': {
            'sondees': total,
            'modifiees': len(changed),
            'inchangees': len(unchanged),
            'retirees': len(withdrawn),
            'anomalies': len(broken),
            'erreurs': len(errors),
            'taux_extraction': round(100.0 * readable / total, 2) if total else 0.0,
            'taux_anomalie': round(100.0 * len(broken) / catalogued, 2) if catalogued else 0.0,
        },
    }


def enqueue(db, verdict):
    """Crée une tâche de rafraîchissement par fiche dont la date a changé."""
    operations = [
        jobs.build('rafraichissement', item['cis'], url=item['url'], priority=3,
                   payload={'date_source': item['date_source'],
                            'date_base': item['date_base']})
        for item in verdict['changed'] if item['cis']
    ]
    created, updated = jobs.add_many(db, operations)
    return {'taches_preparees': len(operations),
            'creees': created, 'mises_a_jour': updated}
