# -*- coding: utf-8 -*-
"""Réduit les 269 271 énoncés d'interaction à leurs patrons.

L'audit UX (§1.10) demandait de traduire hors ligne « 15 731 énoncés
distincts ». Le compte est faux : les 269 271 relations portent 269 271
descriptions **toutes distinctes**. Mais elles ne sont pas écrites à la main —
DrugBank les engendre à partir d'un petit nombre de phrases types où seuls
changent les noms de substance :

    The metabolism of Warfarin can be decreased when combined with Amiodarone.
    The metabolism of Codeine can be decreased when combined with Quinidine.

En remplaçant les noms par des jetons, il reste **537 patrons**, dont 22
couvrent 80 % des énoncés, 41 en couvrent 90 % et 192 en couvrent 99 %.

Les noms sont pris aux extrémités de la relation, non devinés sur la casse :
une première version masquait tout mot capitalisé et laissait fuir les parties
minuscules des noms composés — « … combined with {b} acid » — d'où 2 839
patrons au lieu de 537, cinq fois trop.

## Pourquoi les noms sont substitués et non traduits

Un nom de substance est un nom propre. « Warfarin » ne devient pas « Warfarine »
par une traduction automatique fiable, et se tromper sur le nom d'une molécule
dans un outil de prescription est la faute qu'on ne peut pas se permettre. Les
noms sont donc retirés avant traduction et réinsérés tels quels après.

## Ce que produit ce script

`ressources/patrons_interactions.json` : les patrons anglais, triés par
fréquence, avec leur nombre d'occurrences et la couverture cumulée. C'est le
fichier sur lequel `interaction_i18n.couverture()` se mesure, et qu'un
pharmacien peut relire — 537 phrases, pas 269 271.

## Invocation

    python -m scripts.extraire_patrons_interactions

Lecture seule : rien n'est écrit dans Neo4j.
"""
import io
import json
import os
import re
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import get_config                     # noqa: E402
from neo4j_connector import Neo4jConnector        # noqa: E402

# `ressources/` et non `data/` : ce dernier est le répertoire de données de
# MongoDB — y écrire un fichier de référence le mêlerait aux fichiers
# WiredTiger, et il est d'ailleurs gitignoré.
SORTIE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      'ressources', 'patrons_interactions.json')

#: Jetons de substitution. Deux suffisent : un énoncé met en jeu deux
#: substances, celle de la fiche et celle d'en face. Quelques patrons citent la
#: seconde deux fois — le même jeton y revient, ce qui est correct.
JETON_A = '{a}'
JETON_B = '{b}'


def masquer(description, nom_a, nom_b):
    """Remplace les deux noms de substance par leurs jetons.

    Le nom le plus long passe en premier : « Insulin glargine » contient
    « Insulin », et masquer le court d'abord laisserait « {a} glargine ».
    La comparaison ignore la casse — DrugBank écrit tantôt « Vitamin E »,
    tantôt « vitamin E » selon la position dans la phrase.
    """
    paires = sorted([(nom_a, JETON_A), (nom_b, JETON_B)],
                    key=lambda p: len(p[0] or ''), reverse=True)
    resultat = description
    for nom, jeton in paires:
        if not nom:
            continue
        resultat = re.sub(re.escape(nom), jeton, resultat, flags=re.IGNORECASE)
    return resultat


def run():
    cfg = get_config()
    connecteur = Neo4jConnector(cfg.NEO4J_URI, cfg.NEO4J_USER,
                                cfg.NEO4J_PASSWORD, cfg.NEO4J_DATABASE)
    if not connecteur.connect():
        print("Neo4j indisponible")
        return 1

    patrons = Counter()
    non_masques = 0
    total = 0
    with connecteur.driver.session(database=connecteur.database) as session:
        lignes = session.run("""
            MATCH (a:DrugbankSubstance)-[r:INTERACTS_WITH]->(b:DrugbankSubstance)
            WHERE r.description IS NOT NULL
            RETURN a.name AS a, b.name AS b, r.description AS d
        """)
        for ligne in lignes:
            total += 1
            patron = masquer(ligne['d'], ligne['a'], ligne['b'])
            # Un patron où aucun jeton n'apparaît signale un énoncé dont les
            # noms ne correspondent pas aux extrémités : il ne sera pas
            # traduisible par substitution, on le compte pour le savoir.
            if JETON_A not in patron and JETON_B not in patron:
                non_masques += 1
            patrons[patron] += 1
    connecteur.close()

    classement = patrons.most_common()
    cumul = 0
    entrees = []
    for rang, (patron, nombre) in enumerate(classement, 1):
        cumul += nombre
        entrees.append({'rang': rang, 'occurrences': nombre,
                        'couverture': round(cumul / total, 5), 'en': patron})

    os.makedirs(os.path.dirname(SORTIE), exist_ok=True)
    io.open(SORTIE, 'w', encoding='utf-8').write(
        json.dumps(entrees, ensure_ascii=False, indent=1))

    print(f"{total} énoncés, {len(classement)} patrons")
    print(f"   {non_masques} énoncés dont aucun nom d'extrémité n'apparaît "
          f"({100 * non_masques / max(total, 1):.2f} %)")
    for seuil in (0.5, 0.8, 0.9, 0.95, 0.99):
        rang = next(e['rang'] for e in entrees if e['couverture'] >= seuil)
        print(f"   {rang:>5} patrons couvrent {100 * seuil:.0f} %")
    print(f"   écrit dans {SORTIE}")
    return 0


if __name__ == '__main__':
    sys.exit(run())
