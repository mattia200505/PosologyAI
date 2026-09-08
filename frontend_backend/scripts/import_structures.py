# -*- coding: utf-8 -*-
"""
Import des structures moléculaires depuis le dump DrugBank.

Le §12 du plan P9 constatait l'absence totale de donnée de structure : ni
SMILES, ni InChI, ni formule brute, ni dans `medicine_enrichment`, ni dans la
collection `DRUGBANKS`. Il en concluait qu'il faudrait réimporter le dump de
1,8 Go ou interroger PubChem.

Vérification faite, le dump est présent en local et **contient tout** :
`SMILES`, `InChI`, `InChIKey`, `Molecular Formula`, `Molecular Weight`, sous
`<calculated-properties>`. C'est l'import initial qui ne les avait pas
retenues. Aucun téléchargement n'est donc nécessaire — comme pour les listes
d'interactions, la donnée dormait déjà sur le disque.

## La décision de conception

Le §12 la pose, et elle est appliquée telle quelle : **rattacher la structure
à la substance, jamais à la spécialité.** Il y a 13 594 spécialités pour
1 544 substances au catalogue ; les cinq dosages d'ACTISKENAN afficheraient
sinon cinq fois la même molécule de morphine.

Les propriétés sont donc écrites sur les nœuds `DrugbankSubstance`, que la
reconstruction P9-3 a introduits et auxquels chaque spécialité est déjà
rattachée par `HAS_DRUGBANK_SUBSTANCE`.

## Portée

Les molécules biologiques — protéines, anticorps monoclonaux, vaccins — n'ont
pas de structure calculée dans DrugBank, et n'en auront pas : une formule
topologique n'a pas de sens pour un anticorps. Leur absence est donc normale
et doit se lire comme telle, non comme une lacune du catalogue.

## Invocation

    python -m scripts.import_structures              # simulation
    python -m scripts.import_structures --appliquer  # écriture

Le dump fait 1,8 Go ; la lecture est un balayage en flux, à mémoire bornée.
"""
import os
import sys
import time
import xml.etree.ElementTree as ET

from dotenv import load_dotenv
from neo4j import GraphDatabase

DUMP = os.path.join(os.path.dirname(__file__), '..', '..',
                    'drugbank_all_full_database.xml', 'full database.xml')
NS = '{http://www.drugbank.ca}'

# Les seules propriétés utiles à l'affichage d'une structure.
INTERESSANTES = {
    'SMILES': 'smiles',
    'InChI': 'inchi',
    'InChIKey': 'inchikey',
    'Molecular Formula': 'formule',
    'Molecular Weight': 'masse',
}

load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'), override=True)


def substances_du_catalogue(driver):
    """Identifiants DrugBank effectivement portés par le catalogue."""
    with driver.session(database='medicament') as s:
        return {r['i'] for r in s.run(
            "MATCH (x:DrugbankSubstance) RETURN x.drugbank_id AS i")}


def lire_structures(cibles, chemin=None):
    """Balaie le dump et rend {drugbank_id: {smiles, inchi, ...}}.

    Balayage en flux : chaque `<drug>` est libéré dès qu'il est traité, la
    mémoire ne croît donc pas avec la taille du fichier.
    """
    trouve = {}
    t0 = time.time()
    contexte = ET.iterparse(chemin or DUMP, events=('end',))
    for _, elem in contexte:
        if elem.tag != NS + 'drug':
            continue
        # Le premier <drugbank-id> porteur de primary="true" est l'identifiant.
        dbid = None
        for ident in elem.findall(NS + 'drugbank-id'):
            if ident.get('primary') == 'true':
                dbid = (ident.text or '').strip()
                break
        if dbid and dbid in cibles:
            props = {}
            for prop in elem.iter(NS + 'property'):
                kind = prop.findtext(NS + 'kind')
                if kind in INTERESSANTES:
                    valeur = (prop.findtext(NS + 'value') or '').strip()
                    if valeur:
                        props[INTERESSANTES[kind]] = valeur
            if props:
                trouve[dbid] = props
        elem.clear()
    print(f"   balayage du dump : {time.time() - t0:.0f} s")
    return trouve


def run(appliquer=False):
    driver = GraphDatabase.driver(
        os.getenv('NEO4J_URI'), auth=(os.getenv('NEO4J_USER'), os.getenv('NEO4J_PASSWORD')))
    cibles = substances_du_catalogue(driver)
    print(f"Substances au catalogue : {len(cibles)}")

    structures = lire_structures(cibles)
    avec_smiles = sum(1 for p in structures.values() if p.get('smiles'))
    avec_formule = sum(1 for p in structures.values() if p.get('formule'))
    print(f"   structures trouvees   : {len(structures)} "
          f"({100 * len(structures) / max(len(cibles), 1):.1f} %)")
    print(f"   dont SMILES           : {avec_smiles}")
    print(f"   dont formule brute    : {avec_formule}")
    print(f"   sans structure        : {len(cibles) - len(structures)} "
          f"(biologiques, vaccins, anticorps — normal)")

    exemples = list(structures.items())[:5]
    print()
    for dbid, p in exemples:
        print(f"   {dbid}  {p.get('formule', '?'):<18} {p.get('masse', '?'):<12} "
              f"{(p.get('smiles') or '')[:46]}")

    if not appliquer:
        print("\nSimulation : aucune écriture. Relancer avec --appliquer.")
        driver.close()
        return 0

    lignes = [{'id': k, **v} for k, v in structures.items()]
    with driver.session(database='medicament') as s:
        for i in range(0, len(lignes), 500):
            s.run("""
                UNWIND $rows AS row
                MATCH (x:DrugbankSubstance {drugbank_id: row.id})
                SET x.smiles = row.smiles, x.inchi = row.inchi,
                    x.inchikey = row.inchikey, x.formule = row.formule,
                    x.masse = row.masse
            """, rows=lignes[i:i + 500])
        n = s.run("MATCH (x:DrugbankSubstance) WHERE x.smiles IS NOT NULL "
                  "RETURN count(x) AS n").single()['n']
    print(f"\n{len(lignes)} substances enrichies. Portant un SMILES : {n}.")
    driver.close()
    return len(lignes)


if __name__ == '__main__':
    if not os.path.exists(DUMP):
        sys.exit(f"Dump introuvable : {DUMP}")
    appliquer = '--appliquer' in sys.argv
    if not appliquer:
        print("MODE SIMULATION — aucune écriture en base\n")
    run(appliquer=appliquer)
