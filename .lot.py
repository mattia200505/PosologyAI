# -*- coding: utf-8 -*-
"""Traitement du catalogue par lots reprenables.

    python lot.py [taille]        defaut 200

Reprenable par construction : un medicament deja tente — present dans
`agent_results` ou `agent_reports` — est saute. Si l'execution est
interrompue, la suivante repart ou celle-ci s'est arretee, sans rien
retraiter.

`medicines` est relevee avant et apres CHAQUE medicament : compte et
empreinte des identifiants. Toute derive arrete le lot immediatement.
"""
import hashlib
import io
import json
import os
import re
import sys
import time

sys.path.insert(0, '.')
from dotenv import load_dotenv
load_dotenv('frontend_backend/.env')

from pymongo import MongoClient

import agent_collecte
import agent_lib
import agent_verif as V
from agent_superviseur import process_medicine

BASE = MongoClient('mongodb://localhost:27017', serverSelectionTimeoutMS=5000)['medicsearch']
JOURNAL = '.lots_journal.jsonl'
TAILLE = int(sys.argv[1]) if len(sys.argv) > 1 else 200

#: Les motifs que le superviseur peut rendre, pour le decompte.
MOTIFS = ('written', 'insuffisant', 'not_found', 'source_indisponible',
          'interrompu', 'failed')


def empreinte():
    ids = sorted(str(d['_id']) for d in BASE['medicines'].find({}, {'_id': 1}))
    return len(ids), hashlib.sha1(''.join(ids).encode()).hexdigest()[:16]


def racines_du_catalogue():
    """Une entree par racine de marque, dans l'ordre alphabetique."""
    vues, noms = set(), {}
    for d in BASE['medicines'].find({'title': {'$exists': True}}, {'title': 1}):
        titre = (d.get('title') or '').strip()
        m = re.match(r"^([A-ZÉÈÀÇ][A-Za-zÉÈÀÇ0-9\-'\. ]{2,28}?)\s+\d", titre)
        if not m:
            continue
        racine = m.group(1).split()[0]
        if len(racine) < 4 or racine in vues:
            continue
        vues.add(racine)
        noms[racine] = re.sub(r',.*$', '', titre).strip()
    return [noms[r] for r in sorted(noms)]


def deja_tentes():
    """Ce qui a deja ete traite, quel qu'ait ete le verdict."""
    faits = {d['task'] for d in BASE['agent_results'].find({}, {'task': 1})}
    faits |= {d['task'] for d in BASE['agent_reports'].find({}, {'task': 1})}
    return faits


def main():
    toutes = racines_du_catalogue()
    faits = deja_tentes()
    restant = [n for n in toutes if n not in faits]
    lot = restant[:TAILLE]

    n0, e0 = empreinte()
    print('CATALOGUE : %d racines | déjà tentées %d | restant %d'
          % (len(toutes), len(toutes) - len(restant), len(restant)), flush=True)
    print('LOT       : %d médicaments | medicines %d, empreinte %s'
          % (len(lot), n0, e0), flush=True)
    print('=' * 100, flush=True)

    if not lot:
        print('Rien à traiter : le catalogue est couvert.', flush=True)
        return 0

    compte = dict.fromkeys(MOTIFS, 0)
    appels_total, t_lot = 0, time.perf_counter()
    journal = io.open(JOURNAL, 'a', encoding='utf-8')

    for i, nom in enumerate(lot, 1):
        na, ea = empreinte()
        etat = {'n': 0}
        vrai = agent_lib.complete

        def espion(*a, **k):
            etat['n'] += 1
            return vrai(*a, **k)

        agent_lib.complete = agent_collecte.complete = V.complete = espion
        t = time.perf_counter()
        try:
            r = process_medicine(nom, use_llm=True, verbose=False)
        except Exception as err:
            r = {'status': 'failed', 'erreur': str(err)[:200], 'attempts': [],
                 'score': None}
        duree = time.perf_counter() - t
        agent_lib.complete = agent_collecte.complete = V.complete = vrai
        nb, eb = empreinte()

        statut = r.get('status', 'failed')
        compte[statut] = compte.get(statut, 0) + 1
        appels_total += etat['n']
        intacte = (na == nb and ea == eb)

        journal.write(json.dumps({
            'nom': nom, 'statut': statut, 'score': r.get('score'),
            'tentatives': len(r.get('attempts') or []), 'llm': etat['n'],
            'duree': round(duree, 1), 'medicines_intacte': intacte,
            'horodatage': time.strftime('%Y-%m-%d %H:%M:%S'),
        }, ensure_ascii=False) + '\n')
        journal.flush()

        print('%4d/%d  %-34s %-20s LLM %2d  tent %d  %5.1fs  %s'
              % (i, len(lot), nom[:34], statut, etat['n'],
                 len(r.get('attempts') or []), duree,
                 'ok' if intacte else '*** MEDICINES MODIFIÉE ***'), flush=True)

        if not intacte:
            print('\nARRÊT IMMÉDIAT : medicines modifiée au médicament %d.' % i,
                  flush=True)
            journal.close()
            return 2

    journal.close()
    n1, e1 = empreinte()
    ecoule = time.perf_counter() - t_lot
    print('=' * 100, flush=True)
    print('LOT TERMINÉ : %d traités en %.0f s (%.1f min), moyenne %.1f s'
          % (len(lot), ecoule, ecoule / 60, ecoule / len(lot)), flush=True)
    print('  ' + '  '.join('%s %d' % (m, compte[m]) for m in MOTIFS), flush=True)
    print('  appels Mistral : %d (%.1f par médicament)'
          % (appels_total, appels_total / len(lot)), flush=True)
    print('  medicines : %d -> %d, empreinte %s -> %s : %s'
          % (n0, n1, e0, e1,
             'INTACTE' if (n0 == n1 and e0 == e1) else '*** MODIFIÉE ***'),
          flush=True)
    print('  restant après ce lot : %d' % (len(restant) - len(lot)), flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
