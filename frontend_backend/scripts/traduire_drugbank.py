# -*- coding: utf-8 -*-
"""Traduit hors ligne les textes DrugBank affichés sur la fiche.

Le bloc DrugBank montrait des intitulés français au-dessus d'un contenu
anglais. Quatre champs portent de la prose utile — mécanisme d'action,
pharmacodynamie, indication, toxicité — et c'est cette prose qu'on traduit ici.

Les champs pharmacocinétiques du tableau (demi-vie, clairance, liaison
protéique, volume de distribution) restent en anglais : ce sont des valeurs
chiffrées assorties de fragments très techniques, où une traduction
automatique apporterait peu et pourrait fausser une unité.

## Pourquoi hors ligne

C'est la seule façon de répondre aux deux exigences en même temps :

- **valable pour toutes les fiches** — les textes sont portés par la substance
  et non par la spécialité : **4 590 textes distincts** couvrent les quelque
  7 000 fiches concernées. Chacun n'est traduit qu'une fois, puis recopié
  partout où il apparaît ;
- **sans ralentir le site** — la traduction est rangée à côté de l'original,
  dans le document que la fiche charge déjà. Le serveur ne traduit jamais rien
  à l'affichage : il lit un champ de plus. Aucune requête supplémentaire,
  aucun appel réseau.

Le procédé est celui des formules topologiques (§12 du plan P9) : calculer une
fois, hors du chemin de la requête, servir ensuite.

## Ce que le script garantit

**Reprise.** Chaque traduction est écrite dans `traductions_drugbank` sous
l'empreinte de son texte source, au fur et à mesure. Une interruption ne perd
que la phrase en cours ; relancer reprend où l'on s'était arrêté.

**Retenue.** L'endpoint de Google n'est pas un service contractuel. Le script
marque une pause entre deux appels, réessaie trois fois en espaçant, et
**s'arrête au bout de dix échecs consécutifs** plutôt que d'insister — la leçon
des 1 257 refus essuyés chez l'EMA par une version antérieure de l'import des
RCP, qui ne distinguait pas un refus d'une absence.

**Repli honnête.** Un texte non traduit n'est pas remplacé par une approximation
ni masqué : la fiche affiche l'anglais avec `lang="en"`, et le dit.

## Invocation

    python -m scripts.traduire_drugbank --limite 20      # simulation
    python -m scripts.traduire_drugbank --limite 20 --appliquer
    python -m scripts.traduire_drugbank --appliquer      # les 4 590

Compter environ deux heures et demie pour le lot complet.
"""
import argparse
import hashlib
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pymongo import MongoClient  # noqa: E402

MONGO_URI = "mongodb://localhost:27017/"
MONGO_DB = "medicsearch"

#: Les quatre champs de prose. Le tableau pharmacocinétique en est absent
#: volontairement, voir l'en-tête.
CHAMPS = ('mechanism_of_action', 'pharmacodynamics', 'indication', 'toxicity')

#: Au-delà, l'endpoint refuse. Huit textes sur 4 590 dépassent ce seuil ; ils
#: sont découpés aux frontières de phrase, jamais au milieu d'un mot.
LONGUEUR_MAXIMUM = 4500

#: Échecs d'affilée au-delà desquels la campagne s'arrête. Un service qui
#: refuse dix fois de suite ne dira pas oui à la onzième.
ECHECS_CONSECUTIFS_MAXIMUM = 10

ATTENTES_REPRISE = (5, 20, 60)


def empreinte(texte):
    """Clé d'un texte source. Le même paragraphe revient sur des dizaines de
    spécialités : l'empreinte évite de le retraduire à chaque fois."""
    return hashlib.sha1(texte.encode('utf-8')).hexdigest()


def _decouper(texte):
    """Découpe un texte trop long aux frontières de phrase."""
    if len(texte) <= LONGUEUR_MAXIMUM:
        return [texte]
    morceaux, courant = [], ''
    for phrase in texte.replace('\n', ' ').split('. '):
        phrase = phrase.strip()
        if not phrase:
            continue
        candidat = (courant + '. ' + phrase) if courant else phrase
        if len(candidat) > LONGUEUR_MAXIMUM and courant:
            morceaux.append(courant + '.')
            courant = phrase
        else:
            courant = candidat
    if courant:
        morceaux.append(courant)
    return morceaux


def traduire(traducteur, texte, pause):
    """Rend la traduction, ou `None`. `None` n'est pas masqué par l'appelant."""
    sorties = []
    for morceau in _decouper(texte):
        rendu = None
        for essai, attente in enumerate((0,) + ATTENTES_REPRISE):
            if attente:
                time.sleep(attente)
            try:
                rendu = traducteur.translate(morceau)
                break
            except Exception as err:
                if essai == len(ATTENTES_REPRISE):
                    print(f"      échec après {essai + 1} tentatives : "
                          f"{type(err).__name__}")
                    return None
        time.sleep(pause)
        if not rendu:
            return None
        sorties.append(rendu)
    return ' '.join(sorties)


def textes_distincts(base):
    """Tous les textes à traduire, avec le nombre de fiches qui les portent."""
    compte = {}
    for champ in CHAMPS:
        for doc in base.medicine_enrichment.find(
                {'enriched.' + champ: {'$nin': [None, '', [], {}]}},
                {'enriched.' + champ: 1}):
            valeur = doc['enriched'][champ]
            if isinstance(valeur, str) and valeur.strip():
                compte[valeur] = compte.get(valeur, 0) + 1
    return compte


def run():
    analyseur = argparse.ArgumentParser(description=__doc__)
    analyseur.add_argument('--appliquer', action='store_true',
                           help="écrire les traductions (sinon, simulation)")
    analyseur.add_argument('--limite', type=int, default=0,
                           help="ne traiter que les N premiers textes")
    analyseur.add_argument('--pause', type=float, default=0.4,
                           help="secondes entre deux appels (défaut : 0,4)")
    options = analyseur.parse_args()

    from deep_translator import GoogleTranslator

    base = MongoClient(MONGO_URI, serverSelectionTimeoutMS=8000)[MONGO_DB]
    cache = base.traductions_drugbank
    cache.create_index('empreinte', unique=True)

    compte = textes_distincts(base)
    ordonnes = sorted(compte.items(), key=lambda kv: -kv[1])
    if options.limite:
        ordonnes = ordonnes[:options.limite]

    deja = {d['empreinte'] for d in cache.find({}, {'empreinte': 1})}
    a_faire = [(t, n) for t, n in ordonnes if empreinte(t) not in deja]

    print(f"{len(compte)} textes distincts, {sum(len(t) for t in compte)} caractères")
    print(f"   déjà traduits : {len(deja)}")
    print(f"   à traduire    : {len(a_faire)}")
    print(f"   mode          : {'ÉCRITURE' if options.appliquer else 'simulation'}\n")
    if not a_faire:
        print("   Rien à faire.")
        return 0

    traducteur = GoogleTranslator(source='en', target='fr')
    echecs_consecutifs = 0
    faits = rates = 0
    debut = time.time()

    for texte, occurrences in a_faire:
        rendu = traduire(traducteur, texte, options.pause)
        if not rendu:
            rates += 1
            echecs_consecutifs += 1
            if echecs_consecutifs >= ECHECS_CONSECUTIFS_MAXIMUM:
                print(f"\n   ARRÊT : {echecs_consecutifs} échecs consécutifs. "
                      f"Le service ne répond plus ; insister n'y changerait rien.")
                print("   Relancer plus tard : les traductions déjà faites "
                      "sont conservées.")
                break
            continue
        echecs_consecutifs = 0
        faits += 1
        if options.appliquer:
            cache.update_one(
                {'empreinte': empreinte(texte)},
                {'$set': {'empreinte': empreinte(texte), 'en': texte,
                          'fr': rendu, 'occurrences': occurrences}},
                upsert=True)
        if faits % 50 == 0:
            ecoule = time.time() - debut
            reste = (len(a_faire) - faits) * ecoule / faits
            print(f"   {faits}/{len(a_faire)} traduits, {rates} échecs — "
                  f"reste ~{reste / 60:.0f} min")

    print(f"\n   traduits {faits}, échecs {rates}, "
          f"durée {time.time() - debut:.0f} s")
    if not options.appliquer:
        print("\n   Simulation : rien n'a été écrit. Ajouter --appliquer.")
        return 0

    # ── Report des traductions sur les fiches ─────────────────────────
    # Écrit `<champ>_fr` à côté de l'original, dans le document que la fiche
    # charge déjà. C'est ce report qui rend le coût nul à l'affichage.
    print("\n   report sur les fiches…")
    par_empreinte = {d['empreinte']: d['fr'] for d in cache.find({}, {'empreinte': 1, 'fr': 1})}
    ecrits = 0
    for champ in CHAMPS:
        for doc in base.medicine_enrichment.find(
                {'enriched.' + champ: {'$nin': [None, '', [], {}]}},
                {'enriched.' + champ: 1}):
            valeur = doc['enriched'][champ]
            if not isinstance(valeur, str):
                continue
            rendu = par_empreinte.get(empreinte(valeur))
            if not rendu:
                continue
            base.medicine_enrichment.update_one(
                {'_id': doc['_id']},
                {'$set': {f'enriched.{champ}_fr': rendu}})
            ecrits += 1
    print(f"   {ecrits} champs renseignés en français")
    return 0


if __name__ == '__main__':
    sys.exit(run())
