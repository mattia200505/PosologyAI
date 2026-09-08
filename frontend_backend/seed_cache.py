# -*- coding: utf-8 -*-
"""
Amorce le cache de traduction depuis les fiches déjà traduites.

Chaque fiche conservée dans `medicines_<langue>` est la copie exacte de sa
source française, structure comprise : la reconstruction ne fait que remplacer
les chaînes, sans jamais réordonner ni supprimer de nœud. Parcourir les deux
documents en parallèle rend donc, paire par paire, le travail déjà payé.

Sans cet amorçage, le cache repartirait vide alors que 702 fiches — près de
100 000 chaînes distinctes — ont déjà été traduites. La mesure qui justifie
l'opération : 68,7 % des chaînes d'une fiche neuve figurent déjà dans ce
vocabulaire.

    python seed_cache.py --lang ar
    python seed_cache.py --lang en
"""

import argparse
import sys

from pymongo import MongoClient

from live_translator_google import (COLL_CACHE, SKIP_KEYS, _cache_key,
                                    collection_traduite)

MONGO_URI = 'mongodb://localhost:27017/'
DB_NAME = 'medicsearch'


def _apparier(source, traduit, paires):
    """
    Parcourt deux documents de même forme et relève les couples de chaînes.

    Toute divergence de structure interrompt la branche : mieux vaut perdre
    quelques paires qu'associer le texte d'une rubrique à une autre.
    """
    if isinstance(source, str) and isinstance(traduit, str):
        origine = source.strip()
        cible = traduit.strip()
        if origine and cible:
            paires[origine] = cible
        return

    if isinstance(source, list) and isinstance(traduit, list):
        if len(source) != len(traduit):
            return
        for a, b in zip(source, traduit):
            _apparier(a, b, paires)
        return

    if isinstance(source, dict) and isinstance(traduit, dict):
        for cle, valeur in source.items():
            if cle in SKIP_KEYS or cle not in traduit:
                continue
            _apparier(valeur, traduit[cle], paires)


def amorcer(lang):
    db = MongoClient(MONGO_URI, tz_aware=True)[DB_NAME]
    traduites = db[collection_traduite(lang)]
    total = traduites.count_documents({})
    if not total:
        print("Aucune fiche traduite en '%s' : rien a amorcer." % lang)
        return 0

    print('=== AMORCAGE DU CACHE (%s) ===' % lang)
    print('  fiches traduites disponibles : %d' % total)

    paires = {}
    examinees = ignorees = 0
    for fiche in traduites.find():
        source = db.medicines.find_one({'_id': fiche.get('original_id')})
        if not source:
            ignorees += 1
            continue
        _apparier(source, fiche, paires)
        examinees += 1

    print('  fiches appariees             : %d  (ignorees : %d)' % (examinees, ignorees))
    print('  couples de chaines releves   : %d' % len(paires))

    if not paires:
        return 0

    from pymongo import UpdateOne
    operations = [
        UpdateOne({'_id': _cache_key(origine, lang)},
                  {'$setOnInsert': {'t': cible, 'lang': lang}}, upsert=True)
        for origine, cible in paires.items()
    ]

    inseres = 0
    for i in range(0, len(operations), 2000):
        resultat = db[COLL_CACHE].bulk_write(operations[i:i + 2000], ordered=False)
        inseres += resultat.upserted_count

    print('  entrees ajoutees au cache    : %d' % inseres)
    print('  taille totale du cache       : %d' % db[COLL_CACHE].count_documents({}))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--lang', default='ar', help='langue cible (defaut ar)')
    args = parser.parse_args(argv)
    return amorcer(args.lang)


if __name__ == '__main__':
    sys.exit(main())
