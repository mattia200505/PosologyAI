# -*- coding: utf-8 -*-
"""
Index de recherche sur le catalogue.

`/api/search-results` appliquait une expression régulière insensible à la casse
sur `title`, `substances_actives` **et le texte intégral des RCP** —
`sections.content.text` et deux niveaux de sous-sections. La collection pèse
2,55 Go pour 13 594 documents, et ne portait aucun index utile : chaque
recherche relisait 2,55 Go.

Mesuré avant : 3,9 s à 28,7 s selon le terme. Après, sur la requête seule :

    paracetamol   5,46 s -> 0,014 s
    ibuprofene    8,02 s -> 0,004 s
    warfarine     2,32 s -> 0,016 s

L'index pèse 3,3 Mo et se construit en moins d'une seconde.

## Ce n'est pas qu'une question de vitesse

L'ancienne requête cherchait dans le corps des RCP. « warfarine » y figure
partout où une notice mentionne l'interaction — 3 708 résultats annoncés, dont
**deux seulement contenaient réellement de la warfarine**. Les autres la
citaient dans leur rubrique « Interactions » ou « Mises en garde ». Chercher
une molécule renvoyait donc les médicaments qui en parlent autant que ceux qui
en contiennent.

L'index porte sur le titre et les substances actives, c'est-à-dire sur ce que
le médicament **est**, non sur ce que sa notice mentionne. La recherche plein
texte reste disponible en repli quand l'index ne rend rien.

Effet de bord bienvenu : les index de texte MongoDB ignorent les diacritiques.
« paracetamol » trouve désormais « Paracétamol » — 220 résultats contre 150 à
l'expression régulière, qui butait sur l'accent.

## Invocation

    python -m scripts.create_indexes

Idempotent : `create_index` ne recrée pas un index existant.
"""
import sys
import time

from pymongo import MongoClient, TEXT

MONGO_URI = "mongodb://localhost:27017/"
MONGO_DB = "medicsearch"

NOM_INDEX = 'idx_texte_recherche'

# Le titre pèse le double des substances : un praticien qui tape « DOLIPRANE »
# cherche la spécialité, celui qui tape « paracétamol » accepte toute
# spécialité qui en contient.
CHAMPS = [('title', TEXT), ('medicine_details.substances_actives', TEXT)]
POIDS = {'title': 10, 'medicine_details.substances_actives': 5}


def creer(db, collection):
    if collection not in db.list_collection_names():
        print(f"   {collection:<16} absente, ignorée")
        return False
    existants = [i['name'] for i in db[collection].list_indexes()]
    if NOM_INDEX in existants:
        print(f"   {collection:<16} index déjà présent")
        return False
    t0 = time.time()
    db[collection].create_index(CHAMPS, weights=POIDS, default_language='french',
                                name=NOM_INDEX)
    print(f"   {collection:<16} index créé en {time.time() - t0:.1f} s")
    return True


# Les trois axes exposés comme filtres par `/api/search-results`. Sans index,
# chacun relisait les 2,55 Go ; le trio pèse moins de 1 Mo et se construit en
# une fraction de seconde. `voies_administration` sert deux usages : le filtre
# lui-même, et l'agrégation qui peuple le menu déroulant — 147 clés d'index
# parcourues au lieu de 13 594 documents.
CHAMPS_FILTRES = ['voies_administration', 'commercialisation', 'surveillance_renforcee']


def creer_filtres(db, collection):
    if collection not in db.list_collection_names():
        return
    existants = [i['name'] for i in db[collection].list_indexes()]
    for champ in CHAMPS_FILTRES:
        if f'{champ}_1' in existants:
            print(f"   {collection:<16} {champ:<24} déjà présent")
            continue
        t0 = time.time()
        db[collection].create_index(champ)
        print(f"   {collection:<16} {champ:<24} créé en {time.time() - t0:.1f} s")


def run():
    db = MongoClient(MONGO_URI, serverSelectionTimeoutMS=8000)[MONGO_DB]
    print("Index de texte pour la recherche")
    # `medicines_en` sert les fiches traduites : sans index, la recherche
    # anglaise resterait lente là où la française est devenue immédiate.
    for c in ('medicines', 'medicines_en'):
        creer(db, c)

    print("\nIndex des filtres de la recherche avancée")
    for c in ('medicines', 'medicines_en'):
        creer_filtres(db, c)

    print()
    for c in ('medicines', 'medicines_en'):
        if c not in db.list_collection_names():
            continue
        stats = db.command('collstats', c)
        print(f"   {c:<16} {stats['size'] / 1e9:.2f} Go de données, "
              f"{stats['totalIndexSize'] / 1e6:.1f} Mo d'index")
    return 0


if __name__ == '__main__':
    sys.exit(run())
