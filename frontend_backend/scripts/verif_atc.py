"""Banc de la projection ATC — phase P2 de la roadmap.

Ce que ce banc garde
--------------------
Le graphe connaissait **269 271 interactions et zéro indication**. Les nœuds
`DrugClass` (10), `Disease` (7) et `Contraindication` (7) formaient une
maquette de démonstration : trois relations `HAS_SUBCLASS` en tout. Aucune
donnée ne disait « ce médicament traite cette pathologie ».

La classification thérapeutique existait pourtant déjà dans MongoDB —
**90,9 %** des substances du graphe portent un code ATC dans `DRUGBANKS` — et
n'avait jamais été projetée.

Le piège que ce banc surveille
------------------------------
`DRUGBANKS` compte **1 014 328 documents pour ~1 633 substances utiles**. Un
même nom y apparaît des centaines de fois — *Epinephrine* 251 fois, *Urea* 537
fois — et **un seul de ces documents porte les codes ATC**.

Une jointure par `name` rend donc « aucun ATC » pour des substances qui en
ont. C'est arrivé pendant la rédaction de l'architecture. Les trois substances
témoins du critère de sortie sont précisément celles qui piègent cette
jointure.

Emploi
------
    python scripts/verif_atc.py

Neo4j est nécessaire. La projection se refait avec :
    python scripts/projeter_atc.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_reussis = 0
_echecs = []
_RIEN = object()


def verifier(intitule: str, obtenu, attendu=_RIEN) -> None:
    global _reussis
    ok = bool(obtenu) if attendu is _RIEN else (obtenu == attendu)
    if ok:
        _reussis += 1
    else:
        _echecs.append("%s\n      obtenu : %r\n      attendu: %r"
                       % (intitule, obtenu,
                          '<vrai>' if attendu is _RIEN else attendu))


def relever():
    from config import get_config
    from neo4j_connector import Neo4jConnector
    k = get_config()
    c = Neo4jConnector(uri=k.NEO4J_URI, user=k.NEO4J_USER,
                       password=k.NEO4J_PASSWORD, database=k.NEO4J_DATABASE)
    if not c.connect():
        print("Neo4j injoignable — la projection ne peut pas être éprouvée.")
        sys.exit(2)
    return c


connecteur = relever()
session = connecteur.driver.session(database=connecteur.database)


def un(cypher: str, **params):
    ligne = session.run(cypher, **params).single()
    return ligne[0] if ligne else None


# ── 1. Les nœuds existent ────────────────────────────────────────────────

substances = un("MATCH (n:DrugbankSubstance) RETURN count(n)")
classes = un("MATCH (n:AtcClass) RETURN count(n)")
verifier("des nœuds AtcClass ont été créés", classes and classes > 0, True)
verifier("le graphe garde ses 1 633 substances", substances, 1633)


# ── 2. Critère de sortie : la couverture ─────────────────────────────────

avec_atc = un("MATCH (n:DrugbankSubstance)-[:HAS_ATC]->(:AtcClass) "
              "RETURN count(DISTINCT n)")
couverture = 100.0 * (avec_atc or 0) / max(substances or 1, 1)
verifier("au moins 90 %% des substances portent un ATC "
         "(mesuré : %.1f %%)" % couverture, couverture >= 90.0, True)


# ── 3. Critère de sortie : les trois témoins ─────────────────────────────

# Ce sont les substances qui piègent une jointure par `name`. Si l'une d'elles
# manque, la projection a joint sur le mauvais champ.
#
# Le troisième témoin a changé pendant P2, et l'erreur mérite d'être gardée.
# L'architecture citait « Urea » et son code `B05BC02` : cette substance
# **n'existe pas dans le graphe**. Celle de HELIKIT est `Urea C-13`, l'isotope,
# entrée DrugBank distincte — et son code est `V04CX05`, groupe **V04, agents
# diagnostiques**. C'est une bien meilleure raison de l'écarter d'un traitement
# de pneumonie, et c'est la projection qui l'a révélée.
TEMOINS = [('Furosemide', 'C03CA01'), ('Epinephrine', 'R03AK01'),
           ('Urea C-13', 'V04CX05')]

for nom, code in TEMOINS:
    trouve = un("""
        MATCH (s:DrugbankSubstance)-[:HAS_ATC]->(a:AtcClass {code: $code})
        WHERE s.name = $nom RETURN count(*)
    """, nom=nom, code=code)
    verifier("témoin : %s porte %s "
             "(une jointure par nom l'aurait manqué)" % (nom, code),
             trouve and trouve > 0, True)


# ── 4. Critère de sortie : la hiérarchie est navigable ───────────────────

# Un code de niveau 5 doit remonter jusqu'au groupe anatomique : C03CA01 →
# C03CA → C03C → C03 → C. Quatre bonds.
chemin = un("""
    MATCH (a:AtcClass {code: 'C03CA01'})-[:HAS_PARENT*]->(racine:AtcClass)
    WHERE racine.niveau = 1
    RETURN racine.code
""")
verifier("C03CA01 remonte jusqu'au groupe anatomique C", chemin, 'C')

bonds = un("""
    MATCH p = (:AtcClass {code: 'C03CA01'})-[:HAS_PARENT*]->(r:AtcClass)
    WHERE r.niveau = 1 RETURN length(p)
""")
verifier("la remontée compte quatre bonds", bonds, 4)

for code, niveau in [('C', 1), ('C03', 2), ('C03C', 3), ('C03CA', 4),
                     ('C03CA01', 5)]:
    trouve = un("MATCH (a:AtcClass {code: $code}) RETURN a.niveau", code=code)
    verifier("le niveau de %s est %d" % (code, niveau), trouve, niveau)

verifier("aucune classe n'est orpheline de parent hors du niveau 1",
         un("MATCH (a:AtcClass) WHERE a.niveau > 1 AND "
            "NOT (a)-[:HAS_PARENT]->() RETURN count(a)"), 0)


# ── 5. Les libellés ──────────────────────────────────────────────────────

# Le niveau 4 porte le libellé fourni par DrugBank, le niveau 1 celui des
# groupes anatomiques de l'OMS. Les niveaux 2 et 3 restent codés sans
# libellé : les écrire serait une acquisition de données, hors P2.
verifier("le niveau 4 porte un libellé",
         un("MATCH (a:AtcClass {code: 'C03CA'}) RETURN a.libelle") is not None,
         True)
verifier("le groupe anatomique C est nommé",
         un("MATCH (a:AtcClass {code: 'C'}) RETURN a.libelle") is not None,
         True)
verifier("les 14 groupes anatomiques existent",
         un("MATCH (a:AtcClass) WHERE a.niveau = 1 RETURN count(a)"), 14)


# ── 6. Les indications ───────────────────────────────────────────────────

avec_indication = un("MATCH (n:DrugbankSubstance) WHERE n.indication IS NOT NULL "
                     "RETURN count(n)")
part = 100.0 * (avec_indication or 0) / max(substances or 1, 1)
verifier("au moins 90 %% des substances portent une indication "
         "(mesuré : %.1f %%)" % part, part >= 90.0, True)

verifier("l'indication est un texte non vide",
         un("MATCH (n:DrugbankSubstance) WHERE n.indication IS NOT NULL "
            "RETURN size(n.indication) > 20 LIMIT 1"), True)


# ── 6 bis. Ce que la projection rend possible pour P3 ────────────────────

# P3 filtrera par classe attendue. Deux groupes ATC marquent à eux seuls un
# produit qui n'est pas un traitement d'indication : V04 (agents
# diagnostiques) et B05 (solutions de perfusion et d'irrigation). Le premier
# écarte HELIKIT, le second les solutés.
for groupe, attendu in [('V04', True), ('B05', True)]:
    verifier("le groupe %s est projeté, P3 pourra s'en servir" % groupe,
             (un("MATCH (a:AtcClass {code: $c}) RETURN count(a)", c=groupe) or 0) > 0,
             attendu)

verifier("HELIKIT est rattaché à un agent diagnostique",
         un("""
            MATCH (m:Medicine)-[:HAS_DRUGBANK_SUBSTANCE]->(:DrugbankSubstance)
                  -[:HAS_ATC]->(:AtcClass)-[:HAS_PARENT*]->(g:AtcClass {code:'V04'})
            WHERE m.title STARTS WITH 'HELIKIT' RETURN count(DISTINCT m)
         """) or 0, 1)


# ── 7. Ce que la projection ne doit pas avoir cassé ──────────────────────

verifier("les interactions sont intactes",
         un("MATCH ()-[r:INTERACTS_WITH]->() RETURN count(r)"), 269271)
verifier("le rattachement des spécialités est intact",
         un("MATCH ()-[r:HAS_DRUGBANK_SUBSTANCE]->() RETURN count(r)"), 12135)


# ── 8. Le script joint par le bon champ ──────────────────────────────────

script = (Path(__file__).resolve().parent / 'projeter_atc.py').read_text(
    encoding='utf-8')
verifier("la projection joint par drugbank_id", "'drugbank_id'" in script, True)
verifier("la projection ne joint pas par nom",
         "{'name':" in script or '{"name":' in script, False)
verifier("la projection est rejouable (MERGE, pas CREATE)",
         'MERGE' in script and 'CREATE (' not in script, True)


# ── Relevé ───────────────────────────────────────────────────────────────

print()
print("  Substances          : %s" % substances)
print("  Classes ATC créées  : %s" % classes)
print("  Couverture ATC      : %.1f %%" % couverture)
print("  Couverture indication : %.1f %%" % part)

session.close()
connecteur.close()

print()
if _echecs:
    print("ÉCHECS (%d) :" % len(_echecs))
    for e in _echecs:
        print("  - %s" % e)
    print()
    print("%d contrôles réussis, %d en échec." % (_reussis, len(_echecs)))
    sys.exit(1)

print("%d contrôles, aucun en échec." % _reussis)
sys.exit(0)
