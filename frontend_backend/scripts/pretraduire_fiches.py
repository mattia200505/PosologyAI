# -*- coding: utf-8 -*-
"""Pré-traduit des fiches en anglais, hors du chemin de la requête.

La première visite d'une fiche en anglais déclenche sa traduction intégrale :
mesuré entre **3,3 et 8,7 secondes**. Les visites suivantes retombent à 0,13 à
0,34 s, la traduction étant conservée dans `medicines_en`. Le coût est donc
réel mais payé une seule fois — par le premier lecteur, qui n'a rien demandé.

Ce script paie ce coût à l'avance, pour un périmètre choisi.

## Pourquoi pas le catalogue entier

Le procédé est celui de `traduire_drugbank.py`, mais le rapport de forces est
inversé et cela décide de tout.

Pour DrugBank, 4 589 textes couvraient 7 000 fiches : les paragraphes sont
portés par la substance, d'où un effet de levier de ×1 500. Ici, la prose des
RCP est presque unique par fiche — **1 710 346 textes distincts pour 13 594
fiches, soit ×1,5**. Il n'y a quasiment rien à mutualiser.

Le catalogue entier représente **853 millions de caractères**, soit, à la
vitesse mesurée sur le lot DrugBank (450 caractères par seconde), **environ
526 heures**. Contre un service qui limite déjà le débit, ce n'est pas une
campagne, c'est un déménagement.

D'où le choix d'un périmètre :

    --perimetre ema             1 548 fiches
    --perimetre surveillance      491 fiches
    --perimetre ema+surveillance 1 649 fiches, ~2 h   (défaut)
    --perimetre tout            13 594 fiches

Le périmètre par défaut compte 1 649 fiches et non 2 039 : 390 spécialités
sont à la fois d'origine EMA et sous surveillance renforcée, et le `$or` les
compte une seule fois — ce qu'une addition des deux populations manquait.

Mesuré : 1 649 fiches en 7 498 s, aucun échec. Une fiche du périmètre s'ouvre
en anglais en **0,95 s de médiane**, contre **6,07 s** pour une fiche hors
périmètre à sa première visite.

Les deux populations retenues par défaut sont celles où un lecteur anglophone
est le plus plausible : médicaments autorisés par la procédure européenne, et
spécialités sous surveillance renforcée. Le reste garde le chargement paresseux,
qui fonctionne.

## Ce que le script garantit

**Reprise.** Une fiche déjà présente dans `medicines_en` avec la bonne
empreinte de contenu est ignorée. Interrompre et relancer ne recommence rien.

**Aucune interférence.** Le script emprunte exactement le chemin du serveur —
`translate_medicines_live_google`, puis `store_translation`. Il n'écrit pas un
format parallèle qui divergerait : ce qu'il produit est ce que la fiche aurait
produit à la première visite.

**Retenue.** Une pause entre deux fiches, et **arrêt au bout de cinq échecs
consécutifs** plutôt que d'insister — la leçon des 1 257 refus essuyés chez
l'EMA par une version antérieure de l'import des RCP, qui ne distinguait pas
un refus d'une absence.

## Invocation

    python -m scripts.pretraduire_fiches --limite 5
    python -m scripts.pretraduire_fiches --limite 5 --appliquer
    python -m scripts.pretraduire_fiches --appliquer
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pymongo import MongoClient  # noqa: E402

MONGO_URI = "mongodb://localhost:27017/"
MONGO_DB = "medicsearch"

ECHECS_CONSECUTIFS_MAXIMUM = 5

#: Écritures refusées d'affilée au-delà desquelles la campagne s'arrête.
#: Plus bas que le seuil des échecs de traduction : une base qui refuse
#: trois écritures de suite est arrêtée, pas encombrée.
ECHECS_ECRITURE_MAXIMUM = 3

PERIMETRES = {
    'ema': {'source': 'EMA'},
    'surveillance': {'surveillance_renforcee': 'Oui'},
    'ema+surveillance': {'$or': [{'source': 'EMA'},
                                 {'surveillance_renforcee': 'Oui'}]},
    'tout': {},
}


def run():
    analyseur = argparse.ArgumentParser(description=__doc__)
    analyseur.add_argument('--appliquer', action='store_true',
                           help="écrire les traductions (sinon, simulation)")
    analyseur.add_argument('--perimetre', default='ema+surveillance',
                           choices=sorted(PERIMETRES),
                           help="population à traiter (défaut : ema+surveillance)")
    analyseur.add_argument('--limite', type=int, default=0,
                           help="ne traiter que les N premières fiches")
    analyseur.add_argument('--pause', type=float, default=1.0,
                           help="secondes entre deux fiches (défaut : 1)")
    options = analyseur.parse_args()

    import live_translator_google as traducteur

    base = MongoClient(MONGO_URI, serverSelectionTimeoutMS=8000)[MONGO_DB]
    traducteur.ensure_indexes(base)
    deja = base[traducteur.collection_traduite('en')]

    curseur = base.medicines.find(PERIMETRES[options.perimetre])
    if options.limite:
        curseur = curseur.limit(options.limite)
    fiches = list(curseur)

    # Une fiche déjà traduite et alignée sur son contenu courant est ignorée.
    # L'empreinte est celle que `stored_translation` vérifie à l'affichage :
    # s'en écarter ferait retraduire à chaque visite ce que ce script vient
    # d'écrire.
    a_faire = []
    for fiche in fiches:
        connue = deja.find_one({'original_id': fiche['_id']},
                               {'content_hash': 1})
        if connue and (not fiche.get('content_hash')
                       or connue.get('content_hash') == fiche.get('content_hash')):
            continue
        a_faire.append(fiche)

    print(f"périmètre « {options.perimetre} » : {len(fiches)} fiches")
    print(f"   déjà traduites : {len(fiches) - len(a_faire)}")
    print(f"   à traduire     : {len(a_faire)}")
    print(f"   mode           : {'ÉCRITURE' if options.appliquer else 'simulation'}\n")
    if not a_faire:
        print("   Rien à faire.")
        return 0

    faites = rates = 0
    echecs_consecutifs = echecs_ecriture = 0
    debut = time.time()

    for fiche in a_faire:
        try:
            # Une fiche à la fois : le relevé mutualise déjà les chaînes à
            # l'intérieur d'un document, et traiter par lots ferait tout perdre
            # en cas d'interruption au milieu du lot.
            traduites = traducteur.translate_medicines_live_google(
                [dict(fiche)], lang='en', db=base)
            if not traduites:
                raise RuntimeError('aucune fiche rendue')
            if options.appliquer:
                # L'écriture est surveillée à part de la traduction. Une
                # campagne précédente a continué d'appeler le service de
                # traduction pendant que MongoDB était arrêté : treize fiches
                # traduites pour rien, et rien pour le signaler. Traduire sans
                # pouvoir conserver n'a aucun intérêt, autant s'arrêter.
                try:
                    conserve = traducteur.store_translation(
                        base, fiche, traduites[0], lang='en')
                except Exception as err_ecriture:
                    conserve = False
                    print(f"      écriture impossible : {type(err_ecriture).__name__}")
                if conserve is False:
                    echecs_ecriture += 1
                    if echecs_ecriture >= ECHECS_ECRITURE_MAXIMUM:
                        print(f"\n   ARRÊT : {echecs_ecriture} écritures refusées "
                              f"d'affilée. La base ne répond plus ; traduire sans "
                              f"pouvoir conserver ne sert à rien.")
                        print("   Vérifier que MongoDB tourne, puis relancer : "
                              "ce qui est conservé est ignoré.")
                        break
                    continue
                echecs_ecriture = 0
        except Exception as err:
            rates += 1
            echecs_consecutifs += 1
            print(f"   {fiche.get('title', '')[:34]:<34} échec : "
                  f"{type(err).__name__}")
            if echecs_consecutifs >= ECHECS_CONSECUTIFS_MAXIMUM:
                print(f"\n   ARRÊT : {echecs_consecutifs} échecs consécutifs. "
                      f"Le service ne répond plus ; insister n'y changerait rien.")
                print("   Relancer plus tard : ce qui est traduit est conservé.")
                break
            continue

        echecs_consecutifs = 0
        faites += 1
        time.sleep(options.pause)
        if faites % 25 == 0:
            ecoule = time.time() - debut
            reste = (len(a_faire) - faites) * ecoule / faites
            print(f"   {faites}/{len(a_faire)} fiches — reste ~{reste / 3600:.1f} h")

    print(f"\n   traduites {faites}, échecs {rates}, "
          f"durée {time.time() - debut:.0f} s")
    if not options.appliquer:
        print("\n   Simulation : rien n'a été écrit. Ajouter --appliquer.")
    return 0


if __name__ == '__main__':
    sys.exit(run())
