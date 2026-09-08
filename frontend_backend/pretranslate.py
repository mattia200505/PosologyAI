"""
Pré-traduction par lots vers `medicines_<langue>`.

L'affichage traduit déjà à la demande et conserve son résultat : le premier
visiteur d'une fiche dans une langue donnée attend quelques secondes, les
suivants non. Cet outil déplace cette attente hors ligne, sur les fiches
choisies.

La langue cible est un paramètre — `--lang ar` pour l'arabe. Chaque langue a
sa collection et son propre décompte : les fiches déjà traduites en anglais ne
comptent pas comme traduites en arabe.

**Il n'a pas vocation à parcourir la base entière.** Traduire les 12 046 fiches
représente environ 23 heures et 313 000 appels au point d'entrée public et
gratuit de Google Translate. Le service n'est pas contractuel : une cadence
soutenue expose au blocage, et la charge n'est pas anodine pour un tiers qui
n'a rien demandé. D'où le plafond obligatoire et la temporisation.

Reprenable : une fiche déjà traduite et alignée sur sa notice est ignorée. Une
exécution interrompue peut donc être relancée telle quelle.

    python pretranslate.py --limit 100
    python pretranslate.py --limit 500 --commercialisees --pause 0.5
    python pretranslate.py --etat
"""

import argparse
import sys
import time

from pymongo import MongoClient

import live_translator_google as translator_module
from live_translator_google import (GoogleLiveTranslator, collection_traduite, ensure_indexes,
                                    stored_translation, store_translation)

MONGO_URI = 'mongodb://localhost:27017/'
DB_NAME = 'medicsearch'

# Plafond de sécurité : au-delà, l'outil refuse et renvoie à une décision
# explicite plutôt que de lancer une campagne de plusieurs heures par accident.
LIMITE_MAX = 2000


def connect():
    return MongoClient(MONGO_URI, tz_aware=True)[DB_NAME]


def etat(db, lang):
    """Compte ce qui est traduit, périmé ou absent. Aucun accès réseau."""
    total = db.medicines.count_documents({})
    hashes = {d['_id']: d.get('content_hash')
              for d in db.medicines.find({}, {'content_hash': 1})}
    a_jour = perimees = 0
    for entry in db[collection_traduite(lang)].find({}, {'original_id': 1, 'content_hash': 1}):
        source = hashes.get(entry.get('original_id'))
        if entry.get('original_id') not in hashes:
            continue
        if not source or entry.get('content_hash') == source:
            a_jour += 1
        else:
            perimees += 1
    return {'total': total, 'a_jour': a_jour, 'perimees': perimees,
            'absentes': total - a_jour - perimees}


def a_traduire(db, limite, commercialisees_seulement, lang):
    """
    Fiches sans traduction utilisable, les plus utiles d'abord.

    Une fiche non commercialisée intéresse moins un lecteur anglophone qu'un
    médicament qu'il peut réellement se voir prescrire : le tri le reflète.
    """
    connues = {}
    for entry in db[collection_traduite(lang)].find({}, {'original_id': 1, 'content_hash': 1}):
        connues[entry.get('original_id')] = entry.get('content_hash')

    requete = {}
    if commercialisees_seulement:
        requete['commercialisation'] = 'Commercialisée'

    choisies = []
    for document in db.medicines.find(requete, {'content_hash': 1,
                                                'commercialisation': 1}):
        if document['_id'] in connues:
            connu = connues[document['_id']]
            courant = document.get('content_hash')
            if not courant or connu == courant:
                continue                     # traduction utilisable, on passe
        choisies.append((0 if document.get('commercialisation') == 'Commercialisée' else 1,
                         document['_id']))
        if len(choisies) >= limite * 3:
            break

    choisies.sort(key=lambda item: item[0])
    return [identifiant for _, identifiant in choisies[:limite]]


def run(limite, commercialisees_seulement, pause, lang, taille_groupe=10):
    db = connect()
    ensure_indexes(db)

    depart = etat(db, lang)
    print('=== ETAT INITIAL ===')
    print('  fiches            : %d' % depart['total'])
    print('  traduites a jour  : %d' % depart['a_jour'])
    print('  traductions perimees : %d' % depart['perimees'])
    print('  jamais traduites  : %d' % depart['absentes'])
    print()

    identifiants = a_traduire(db, limite, commercialisees_seulement, lang)
    if not identifiants:
        print('Rien a traduire.')
        return 0

    print('=== TRADUCTION DE %d FICHE(S) ===' % len(identifiants))
    traducteur = GoogleLiveTranslator(lang, db=db)
    faites = ignorees = echecs = 0
    commence = time.time()

    # Les fiches sont traduites par groupes.
    #
    # Traitées une par une, elles n'apportent qu'une centaine de chaînes
    # nouvelles chacune, soit quelques lots : le parallélisme restait plafonné
    # par la taille du travail, et augmenter le nombre de fils ne changeait
    # rien. En relevant les chaînes de tout un groupe avant de traduire, un
    # seul appel porte assez de lots pour occuper tous les fils.
    #
    # Le groupe partage aussi son vocabulaire : deux fiches d'un même
    # laboratoire répètent largement les mêmes formulations, qui ne partent
    # alors qu'une fois sur le réseau.
    rang = 0
    for depart_groupe in range(0, len(identifiants), taille_groupe):
        lot_ids = identifiants[depart_groupe:depart_groupe + taille_groupe]

        documents = []
        for identifiant in lot_ids:
            rang += 1
            document = db.medicines.find_one({'_id': identifiant})
            if not document:
                continue
            # Contrôle repris juste avant l'appel : une autre exécution a pu la faire.
            if stored_translation(db, document, lang):
                ignorees += 1
                continue
            documents.append(document)

        if documents:
            try:
                chaines = set()
                for document in documents:
                    translator_module.relever(document, chaines)
                table = traducteur.translate_many(chaines)

                for document in documents:
                    traduite = traducteur.reconstruire(document, table)
                    if store_translation(db, document, traduite, lang):
                        faites += 1
                    else:
                        echecs += 1
            except Exception as error:                      # noqa: BLE001
                # Un échec sur le groupe ne perd que ce groupe : les
                # précédents sont déjà conservés, et l'outil est reprenable.
                echecs += len(documents)
                print('  echec sur un groupe de %d : %s'
                      % (len(documents), type(error).__name__))

        ecoule = time.time() - commence
        print('  %4d/%d | %d traduites, %d ignorees, %d echecs | %.0f s '
              '(%.1f s/fiche)'
              % (rang, len(identifiants), faites, ignorees, echecs,
                 ecoule, ecoule / max(rang, 1)))
        if pause:
            time.sleep(pause)

    arrivee = etat(db, lang)
    print()
    print('=== ETAT FINAL ===')
    print('  traduites a jour  : %d  (+%d)'
          % (arrivee['a_jour'], arrivee['a_jour'] - depart['a_jour']))
    print('  jamais traduites  : %d' % arrivee['absentes'])
    print('  duree             : %.0f s' % (time.time() - commence))
    return 0 if not echecs else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--limit', type=int, default=50,
                        help='nombre de fiches a traduire (defaut 50, plafond %d)'
                             % LIMITE_MAX)
    parser.add_argument('--commercialisees', action='store_true',
                        help='se limiter aux medicaments commercialises')
    parser.add_argument('--pause', type=float, default=0.3,
                        help='temporisation entre deux fiches, en secondes (defaut 0,3)')
    parser.add_argument('--etat', action='store_true',
                        help='afficher l etat sans rien traduire')
    parser.add_argument('--lang', default='en',
                        help='langue cible : en, ar... (defaut en). Chaque langue '
                             'a sa collection medicines_<lang> et son propre etat.')
    parser.add_argument('--groupe', type=int, default=10,
                        help='fiches traduites en un seul appel groupe (defaut 10). '
                             'Un groupe plus large occupe mieux les fils paralleles '
                             'et partage davantage de vocabulaire, au prix de la '
                             'memoire et d une perte plus large si le groupe echoue.')
    args = parser.parse_args(argv)

    if args.lang == 'fr':
        print("Refus : le francais est la langue source, il n y a rien a traduire.")
        return 2

    if args.etat:
        for cle, valeur in etat(connect(), args.lang).items():
            print('  %-20s %d' % (cle, valeur))
        return 0

    if args.limit > LIMITE_MAX:
        print('Refus : %d depasse le plafond de %d fiches par execution.'
              % (args.limit, LIMITE_MAX))
        print('Traduire la base entiere represente environ 23 h et 313 000 appels')
        print('au service public de Google Translate. Relancer l outil autant de')
        print('fois que necessaire est deliberement plus visible qu un seul appel.')
        return 2

    return run(args.limit, args.commercialisees, args.pause, args.lang, args.groupe)


if __name__ == '__main__':
    sys.exit(main())
