# -*- coding: utf-8 -*-
"""
Import des médicaments autorisés par procédure centralisée (EMA).

Le catalogue ne couvrait que la procédure nationale : vérifié, aucune des
12 046 fiches ne portait de numéro d'autorisation européen, et XARELTO,
ELIQUIS, PRADAXA, KEYTRUDA, OZEMPIC, HUMIRA, JARDIANCE, FORXIGA, TRULICITY,
LUCENTIS, ENTRESTO et IMBRUVICA étaient tous absents. Ce sont, pour les trois
premiers, les anticoagulants oraux directs qui ont largement remplacé la
warfarine en pratique : l'application savait répondre sur COUMADINE et ignorait
ceux qu'on prescrit aujourd'hui à sa place.

## La source

Tableur public « Medicines output — European public assessment reports »,
téléchargeable sur `ema.europa.eu/en/medicines/download-medicine-data` et
déposé dans `MEDICSEARCH/data/`. En-tête en ligne 9, données à partir de la 10.

Composition mesurée : 2 730 lignes, dont 2 337 humaines — l'estimation de
`ROADMAP_P4` (~2 338) tombe juste. Mais **1 563 seulement sont autorisées** :
le reste est retiré, refusé, périmé, ou n'a jamais dépassé l'avis. Le plan P9
visait 3 917 médicaments ; le nombre réellement importable est 1 548.

## Ce que l'import retient

Seules les lignes `Category = Human` **et** `Medicine status = Authorised`
portant une substance active. Importer un médicament retiré du marché
reviendrait à répondre sur un produit qu'on ne peut plus prescrire.

Les champs se rangent dans le schéma existant plutôt que dans un schéma
parallèle : `surveillance_renforcee` reçoit « Additional monitoring », que
`regulatory.safety_flags()` lit déjà pour afficher le bandeau réglementaire —
396 de ces médicaments en relèvent.

## Ce que ces fiches n'auront pas

Aucune section de RCP : l'EMA publie les siens en PDF, hors de ce tableur. Une
fiche importée affiche donc ses interactions, sa substance, son laboratoire et
son statut, mais aucune monographie. L'interface doit le dire — c'est le même
principe que la distinction « aucune interaction connue » / « données
indisponibles » introduite au titre du §11.5.

## Invocation

    python -m scripts.import_ema              # simulation
    python -m scripts.import_ema --appliquer  # écriture

Idempotent : la clé d'unicité est l'URL EMA du médicament.
"""
import os
import sys
from datetime import datetime

import openpyxl
from pymongo import MongoClient, UpdateOne

FICHIER = os.path.join(os.path.dirname(__file__), '..', '..', 'data',
                       'medicines-output-medicines-report_en.xlsx')
LIGNE_ENTETE = 9

db = MongoClient("mongodb://localhost:27017/", serverSelectionTimeoutMS=8000)['medicsearch']


def _date(valeur):
    """Rend une date au format du catalogue, ou une chaîne vide."""
    if isinstance(valeur, datetime):
        return valeur.strftime('%d/%m/%Y')
    return str(valeur).strip() if valeur else ''


def lire(chemin=None):
    """Rend les lignes humaines autorisées, en dictionnaires."""
    wb = openpyxl.load_workbook(chemin or FICHIER, read_only=True, data_only=True)
    ws = wb['Medicine']
    it = ws.iter_rows(min_row=LIGNE_ENTETE, values_only=True)
    entete = [c for c in next(it) if c is not None]
    idx = {c: i for i, c in enumerate(entete)}

    def col(ligne, nom):
        i = idx.get(nom)
        v = ligne[i] if i is not None and i < len(ligne) else None
        return v

    retenues = []
    for ligne in it:
        if not ligne or not ligne[0]:
            continue
        if col(ligne, 'Category') != 'Human':
            continue
        if col(ligne, 'Medicine status') != 'Authorised':
            continue
        substances = [s.strip() for s in
                      str(col(ligne, 'Active substance') or '').split(';') if s.strip()]
        if not substances:
            continue
        retenues.append({
            'nom': str(col(ligne, 'Name of medicine') or '').strip(),
            'url': str(col(ligne, 'Medicine URL') or '').strip(),
            'numero_ema': str(col(ligne, 'EMA product number') or '').strip(),
            'substances': substances,
            'dci': str(col(ligne, 'International non-proprietary name (INN) / common name') or '').strip(),
            'atc': str(col(ligne, 'ATC code (human)') or '').strip(),
            'titulaire': str(col(ligne, 'Marketing authorisation developer / applicant / holder') or '').strip(),
            'indication': str(col(ligne, 'Therapeutic indication') or '').strip(),
            'surveillance': col(ligne, 'Additional monitoring') == 'Yes',
            'date_amm': _date(col(ligne, 'Marketing authorisation date')),
            'maj': _date(col(ligne, 'Last updated date')),
        })
    return retenues


def document(ligne):
    """Traduit une ligne du tableur dans le schéma du catalogue."""
    return {
        'title': ligne['nom'],
        'url': ligne['url'],
        'medicine_details': {
            'substances_actives': ligne['substances'],
            'laboratoire': ligne['titulaire'],
            'forme': '',
            'dosages': [],
        },
        # Champs réglementaires, lus tels quels par `regulatory.py`.
        'procedure_amm': 'Centralisée',
        'autorisation_europeenne': ligne['numero_ema'],
        'statut_amm': 'Autorisé',
        'surveillance_renforcee': 'Oui' if ligne['surveillance'] else 'Non',
        'titulaire_amm': ligne['titulaire'],
        'date_amm': ligne['date_amm'],
        'atc_code': ligne['atc'],
        'indication_ema': ligne['indication'],
        'update_date': ligne['maj'],
        # Provenance : ces fiches n'ont pas de RCP ANSM, et l'affichage doit
        # pouvoir le dire plutôt que de presenter une monographie vide.
        'source': 'EMA',
        'document_type': 'EPAR',
        'sections': [],
    }


def run(appliquer=False, chemin=None):
    lignes = lire(chemin)
    print(f"Médicaments EMA humains et autorisés, avec substance : {len(lignes)}")
    print(f"   dont sous surveillance renforcée : "
          f"{sum(1 for l in lignes if l['surveillance'])}")

    deja = {m['url'] for m in db.medicines.find({'source': 'EMA'}, {'url': 1})}
    nouveaux = [l for l in lignes if l['url'] not in deja]
    print(f"   déjà importés : {len(deja)}   à insérer ou mettre à jour : {len(lignes)}")

    collisions = db.medicines.count_documents({
        'title': {'$in': [l['nom'] for l in lignes]}, 'source': {'$ne': 'EMA'}})
    print(f"   titres déjà présents côté catalogue français : {collisions}")

    print()
    print("Échantillon :")
    for l in lignes[:8]:
        print(f"   {l['nom'][:24]:<24} « {l['substances'][0][:30]:<30} » {l['atc']:<9} {l['titulaire'][:24]}")

    if not appliquer:
        print("\nSimulation : aucune écriture. Relancer avec --appliquer.")
        return 0

    ops = [UpdateOne({'url': l['url']}, {'$set': document(l)}, upsert=True) for l in lignes]
    for i in range(0, len(ops), 500):
        db.medicines.bulk_write(ops[i:i + 500])
    total = db.medicines.count_documents({})
    print(f"\n{len(ops)} fiches importées ou mises à jour. Catalogue : {total} médicaments.")
    print("Enchaîner avec l'appariement DrugBank, puis la reconstruction de la "
          "couche substance (cf. rapport P9-3).")
    return len(ops)


if __name__ == '__main__':
    if not os.path.exists(FICHIER):
        sys.exit(f"Fichier introuvable : {FICHIER}\n"
                 "Le télécharger sur ema.europa.eu/en/medicines/download-medicine-data")
    appliquer = '--appliquer' in sys.argv
    if not appliquer:
        print("MODE SIMULATION — aucune écriture en base\n")
    run(appliquer=appliquer)
