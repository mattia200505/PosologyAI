# -*- coding: utf-8 -*-
"""
Pré-calcul des formules topologiques, en SVG, une fois pour toutes.

Le §12 du plan P9 prévoyait « un moteur de dessin chimique côté navigateur,
donc une dépendance supplémentaire, à déclarer dans les `requirements` ».
Ce script prend l'autre voie, pour une raison propre à ce catalogue :

    1 267 substances portent un SMILES, et alimentent 11 255 fiches.

L'ensemble est fini et ne bouge qu'au rythme des imports DrugBank. Dessiner
côté navigateur referait les mêmes 1 267 tracés à chaque visite. On les calcule
donc une fois, on les range à côté du SMILES, et la fiche sert du SVG inline.

Conséquence sur les dépendances : **RDKit ne tourne jamais dans le processus
web**. Il relève des dépendances de développement, pas de celles du serveur.
Un déploiement n'a rien de plus à installer.

## Pourquoi RDKit plutôt qu'une bibliothèque JavaScript

Poids côté visiteur nul, tracé de référence pour la stéréochimie et les cycles
fusionnés, et du SVG inline se met à l'échelle, s'imprime et porte un `<title>`
que les lecteurs d'écran annoncent. SmilesDrawer (~100 Ko, embarqué) reste le
repli si l'on veut se passer de RDKit ; RDKit.js le serait au prix de 7 Mo de
WebAssembly par visiteur, pour une image qui ne change jamais.

## Garde-fou

Le SVG est inséré en HTML sans échappement — c'est ce que veut dire « inline ».
Le contenu vient de RDKit, appliqué à nos propres SMILES, mais le script
refuse d'enregistrer tout ce qui ne commence pas par `<svg` ou qui contiendrait
une balise de script. Ce n'est pas une défiance envers RDKit : c'est que la
seule barrière entre la base et le navigateur, ici, est ce contrôle.

## Invocation

    python -m scripts.render_structures              # simulation
    python -m scripts.render_structures --appliquer  # écriture
    python -m scripts.render_structures --appliquer --refaire   # tout recalculer

Sans `--refaire`, les substances déjà dessinées sont ignorées : le script
reprend là où il s'est arrêté.
"""
import os
import re
import sys
import time

from dotenv import load_dotenv
from neo4j import GraphDatabase

from rdkit import Chem, RDLogger
from rdkit.Chem.Draw import rdMolDraw2D

# RDKit signale sur stderr chaque valence douteuse ; le compte des échecs
# suffit, et le détail noierait la sortie.
RDLogger.DisableLog('rdApp.*')

load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'), override=True)

LARGEUR, HAUTEUR = 340, 260

# Au-delà de cette taille, on ne dessine pas.
#
# La décision est de lisibilité avant d'être de poids : une chaîne de plusieurs
# centaines d'atomes tassée dans 340 × 260 pixels donne un enchevêtrement dont
# un prescripteur ne tire rien. Mesuré sur le catalogue — médiane 25 atomes
# lourds, 90ᵉ centile 42 — le seuil n'écarte que 19 substances sur 1 267
# (1,5 %), toutes peptides ou oligonucléotides : Imetelstat en compte 295, et
# son tracé pesait 235 Ko pour une image indéchiffrable.
MAX_ATOMES = 100

_RE_DECLARATION = re.compile(r"^<\?xml[^>]*\?>\s*", re.I)
_RE_DOCTYPE = re.compile(r"^<!DOCTYPE[^>]*>\s*", re.I)


def dessiner(smiles, nom):
    """Rend le SVG d'une molécule, ou None si elle n'est pas dessinable."""
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        return None
    if mol.GetNumHeavyAtoms() > MAX_ATOMES:
        return None

    dessin = rdMolDraw2D.MolDraw2DSVG(LARGEUR, HAUTEUR)
    options = dessin.drawOptions()
    # Fond transparent : la carte de la fiche porte déjà sa couleur, et le
    # dessin doit suivre le thème plutôt que d'imposer un rectangle blanc.
    options.clearBackground = False
    options.addStereoAnnotation = True
    options.bondLineWidth = 2
    rdMolDraw2D.PrepareAndDrawMolecule(dessin, mol)
    dessin.FinishDrawing()

    svg = dessin.GetDrawingText()
    # La déclaration XML et le DOCTYPE n'ont pas leur place dans du HTML.
    svg = _RE_DOCTYPE.sub('', _RE_DECLARATION.sub('', svg)).strip()

    if not svg.startswith('<svg') or '<script' in svg.lower():
        return None

    # Le titre est ce qu'annonce un lecteur d'écran.
    titre = (nom or 'molécule').replace('<', '').replace('>', '')
    return svg.replace('<svg', '<svg role="img"', 1).replace(
        '>', f'><title>Structure développée : {titre}</title>', 1)


def run(appliquer=False, refaire=False):
    driver = GraphDatabase.driver(
        os.getenv('NEO4J_URI'),
        auth=(os.getenv('NEO4J_USER'), os.getenv('NEO4J_PASSWORD')))

    filtre = '' if refaire else 'AND x.svg IS NULL'
    with driver.session(database='medicament') as s:
        cibles = [dict(r) for r in s.run(f"""
            MATCH (x:DrugbankSubstance)
            WHERE x.smiles IS NOT NULL {filtre}
            RETURN x.drugbank_id AS id, x.name AS nom, x.smiles AS smiles
            ORDER BY x.name
        """)]
    print(f"Substances à dessiner : {len(cibles)}")
    if not cibles:
        print("Rien à faire. Utiliser --refaire pour tout recalculer.")
        driver.close()
        return 0

    t0 = time.time()
    rendus, echecs = [], []
    for c in cibles:
        svg = dessiner(c['smiles'], c['nom'])
        if svg:
            rendus.append({'id': c['id'], 'svg': svg})
        else:
            echecs.append(c['nom'])

    poids = sum(len(r['svg']) for r in rendus)
    print(f"   dessinées : {len(rendus)} en {time.time() - t0:.0f} s")
    print(f"   échecs    : {len(echecs)} (SMILES non interprétable)")
    print(f"   poids     : {poids / 1024 / 1024:.1f} Mo, "
          f"{poids // max(len(rendus), 1)} octets en moyenne")
    if echecs:
        print(f"   exemples d'échec : {', '.join(str(e)[:24] for e in echecs[:5])}")

    if not appliquer:
        print("\nSimulation : aucune écriture. Relancer avec --appliquer.")
        driver.close()
        return 0

    with driver.session(database='medicament') as s:
        for i in range(0, len(rendus), 200):
            s.run("""
                UNWIND $rows AS row
                MATCH (x:DrugbankSubstance {drugbank_id: row.id})
                SET x.svg = row.svg
            """, rows=rendus[i:i + 200])
        total = s.run("MATCH (x:DrugbankSubstance) WHERE x.svg IS NOT NULL "
                      "RETURN count(x) AS n").single()['n']
    print(f"\n{len(rendus)} structures enregistrées. Total en base : {total}.")
    driver.close()
    return len(rendus)


if __name__ == '__main__':
    appliquer = '--appliquer' in sys.argv
    if not appliquer:
        print("MODE SIMULATION — aucune écriture en base\n")
    run(appliquer=appliquer, refaire='--refaire' in sys.argv)
