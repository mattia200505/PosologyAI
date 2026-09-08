# -*- coding: utf-8 -*-
"""Reglage des collections Qdrant, et verification qu'il tient.

Pourquoi ce fichier existe
--------------------------
Aucun code du depot ne creait les collections Qdrant. Leur configuration
n'existait que dans l'instance qui tourne : invisible en revue, absente
d'une reinstallation, et impossible a comparer d'une machine a l'autre.
`create_indexes.py` fait ce travail pour MongoDB ; il manquait son
equivalent ici.

Le defaut mesure
----------------
`medicines_v2` portait 12 046 points et **zero vecteur indexe**.

    seuil d'indexation : 10 000 vecteurs par segment
    segments           : 6
    soit environ       : 2 007 vecteurs par segment

Chaque segment restait sous le seuil, aucun index HNSW ne se construisait,
et toute recherche parcourait les 12 046 vecteurs un par un.

Ce que la correction rapporte, honnetement
------------------------------------------
Peu, a cette taille. Mesure sur 40 requetes, vecteurs pseudo-aleatoires
normalises, graine fixe :

    avant  mediane 3,6 ms   p95 20,5 ms   0 vecteur indexe
    apres  mediane 3,4 ms   p95 21,6 ms   12 046 vecteurs indexes

Le gain est dans le bruit : douze mille vecteurs de 384 dimensions se
parcourent vite. L'interet n'est pas la vitesse d'aujourd'hui, c'est que
le cout cesse de croitre lineairement avec le catalogue. A cinquante mille
fiches, le parcours integral se verrait.

Ou passe reellement le temps d'une recherche vectorielle
--------------------------------------------------------
    encodage de la requete par le modele   11,8 ms
    recherche Qdrant                        3,4 ms
    lecture des 20 fiches dans MongoDB     27,9 ms

Qdrant est le moins cher des trois. Optimiser plus loin de ce cote
n'ameliorerait pas ce que le lecteur ressent.

La collection `interactions`
----------------------------
566 693 points, recherche a 51 ms : dix fois plus lente que `medicines_v2`.
Elle est pourtant laissee telle quelle, parce qu'**aucun code de
l'application ne l'interroge**. Seul `blueprints/database_viewer.py` y
accede, avec le nom passe dans l'URL, pour la parcourir page par page.
L'optimiser n'accelererait aucun ecran.

Emploi
------
    python scripts/regler_qdrant.py            verifie et corrige
    python scripts/regler_qdrant.py --verifier verifie seulement

Sans Qdrant joignable, le script le dit et sort en erreur plutot que de
laisser croire que tout va bien.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request

BASE = 'http://127.0.0.1:6333'

#: Le seuil doit rester **sous** le nombre de vecteurs par segment, sans
#: quoi aucun index ne se construit. Qdrant repartit 12 046 points sur
#: cinq a six segments, soit environ deux mille chacun ; mille laisse de
#: la marge si le catalogue se decoupe autrement.
SEUIL_INDEXATION = 1000

#: Les collections que ce projet sert, et ce qu'on attend d'elles.
ATTENDU = {
    'medicines_v2': {'indexing_threshold': SEUIL_INDEXATION},
}


def _appel(chemin, methode='GET', corps=None):
    donnees = json.dumps(corps).encode() if corps is not None else None
    requete = urllib.request.Request(
        BASE + chemin, data=donnees, method=methode,
        headers={'Content-Type': 'application/json'})
    return json.loads(urllib.request.urlopen(requete, timeout=60).read())


def etat(collection):
    d = _appel('/collections/' + collection)['result']
    return {
        'points': d['points_count'],
        'indexes': d['indexed_vectors_count'],
        'segments': d['segments_count'],
        'optimiseur': d['optimizer_status'],
        'seuil': d['config']['optimizer_config']['indexing_threshold'],
    }


def attendre_indexation(collection, secondes=120):
    """Rend l'etat une fois l'optimiseur au repos, ou apres le delai."""
    for _ in range(secondes // 2):
        e = etat(collection)
        if e['indexes'] >= e['points'] and e['optimiseur'] == 'ok':
            return e
        time.sleep(2)
    return etat(collection)


def main():
    verifier_seulement = '--verifier' in sys.argv

    try:
        _appel('/collections')
    except Exception as err:
        print("  Qdrant injoignable sur %s : %s" % (BASE, err))
        print("  Rien n'a ete verifie.")
        return 1

    defauts = []
    for collection, attentes in ATTENDU.items():
        try:
            avant = etat(collection)
        except urllib.error.HTTPError as err:
            defauts.append('%s : absente (%s)' % (collection, err.code))
            continue

        besoin = avant['seuil'] != attentes['indexing_threshold']
        if besoin and not verifier_seulement:
            _appel('/collections/' + collection, 'PATCH',
                   {'optimizers_config': attentes})
            apres = attendre_indexation(collection)
        else:
            apres = avant

        print('  %s' % collection)
        print('    points %d | indexes %d | segments %d | seuil %d'
              % (apres['points'], apres['indexes'], apres['segments'],
                 apres['seuil']))

        if apres['seuil'] != attentes['indexing_threshold']:
            defauts.append('%s : seuil %d au lieu de %d'
                           % (collection, apres['seuil'],
                              attentes['indexing_threshold']))
        if apres['points'] and apres['indexes'] < apres['points']:
            defauts.append('%s : %d vecteur(s) non indexe(s) sur %d'
                           % (collection, apres['points'] - apres['indexes'],
                              apres['points']))

    print()
    if defauts:
        print('  %d defaut(s) :' % len(defauts))
        for d in defauts:
            print('    - %s' % d)
        return 1

    print('  Les collections sont indexees comme attendu.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
