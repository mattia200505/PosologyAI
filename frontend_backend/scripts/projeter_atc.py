"""Projette la classification ATC de MongoDB vers Neo4j — phase P2.

Pourquoi ce script existe
-------------------------
Le graphe connaissait 269 271 interactions et **zéro indication**. Aucune
donnée ne disait « ce médicament traite cette pathologie », et tout le reste de
la chaîne de recommandation — filtres, notes, classements — n'était qu'une
compensation de cette absence.

La classification existait pourtant déjà dans MongoDB : **90,9 %** des 1 633
substances du graphe portent un code ATC dans `DRUGBANKS`, et **91,4 %** une
indication rédigée. Rien n'avait jamais été projeté.

Le piège, mesuré
----------------
`DRUGBANKS` compte **1 014 328 documents pour ~1 633 substances utiles**. Un
même nom y apparaît des centaines de fois — *Epinephrine* 251 fois, *Urea* 537
fois — et **un seul de ces documents porte les codes ATC**.

Une jointure par `name` rendrait donc « aucun ATC » pour des substances qui en
ont. La jointure se fait par `drugbank_id`, seule clé fiable, et déjà indexée.

La hiérarchie
-------------
Tous les codes de la source font sept caractères — le niveau 5, la substance
chimique. La hiérarchie se dérive du code lui-même, qui est positionnel :

    C03CA01   niveau 5, substance chimique
    C03CA     niveau 4, sous-groupe chimique
    C03C      niveau 3, sous-groupe pharmacologique
    C03       niveau 2, sous-groupe thérapeutique
    C         niveau 1, groupe anatomique

Chaque entrée de la source porte **un seul libellé**, celui du niveau 4. Les
groupes anatomiques de niveau 1 sont écrits ici : ce sont les quatorze de la
classification de l'OMS, une donnée de référence publique, sans laquelle la
hiérarchie ne serait qu'une suite de codes muets. Les niveaux 2 et 3 restent
codés sans libellé — les écrire serait une acquisition de données, hors de
cette phase.

Rejouable
---------
Tout passe par `MERGE`. Relancer le script ne duplique rien.

Emploi
------
    python scripts/projeter_atc.py

MongoDB et Neo4j doivent tourner.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

#: Les quatorze groupes anatomiques de la classification ATC de l'OMS.
#: Donnée de référence publique et fixe, pas un jugement clinique.
GROUPES_ANATOMIQUES = {
    'A': "Voies digestives et métabolisme",
    'B': "Sang et organes hématopoïétiques",
    'C': "Système cardiovasculaire",
    'D': "Dermatologie",
    'G': "Système génito-urinaire et hormones sexuelles",
    'H': "Hormones systémiques, hors hormones sexuelles et insulines",
    'J': "Anti-infectieux généraux à usage systémique",
    'L': "Antinéoplasiques et immunomodulateurs",
    'M': "Système musculo-squelettique",
    'N': "Système nerveux",
    'P': "Antiparasitaires, insecticides et répulsifs",
    'R': "Système respiratoire",
    'S': "Organes sensoriels",
    'V': "Divers",
}

#: Longueur du préfixe pour chaque niveau de la classification.
NIVEAUX = ((1, 1), (3, 2), (4, 3), (5, 4), (7, 5))


def paliers(code: str):
    """Décompose un code ATC en ses cinq niveaux, du plus large au plus fin."""
    code = (code or '').strip().upper()
    if len(code) != 7:
        return []
    return [(code[:longueur], niveau) for longueur, niveau in NIVEAUX]


def main() -> int:
    from config import get_config
    from neo4j_connector import Neo4jConnector
    from pymongo import MongoClient

    k = get_config()
    connecteur = Neo4jConnector(uri=k.NEO4J_URI, user=k.NEO4J_USER,
                                password=k.NEO4J_PASSWORD,
                                database=k.NEO4J_DATABASE)
    if not connecteur.connect():
        print("Neo4j injoignable.")
        return 2

    mongo = MongoClient('mongodb://localhost:27017/')['medicsearch']

    with connecteur.driver.session(database=connecteur.database) as session:
        identifiants = [r['i'] for r in session.run(
            "MATCH (n:DrugbankSubstance) WHERE n.drugbank_id IS NOT NULL "
            "RETURN n.drugbank_id AS i")]
        print("Substances du graphe : %d" % len(identifiants))

        # Jointure par `drugbank_id`, jamais par `name` : la collection compte
        # 1 014 328 documents et un même nom y revient des centaines de fois,
        # dont un seul porte les codes ATC.
        source = {}
        for doc in mongo.DRUGBANKS.find(
                {'drugbank_id': {'$in': identifiants}},
                {'drugbank_id': 1, 'name': 1, 'atc_codes': 1, 'indication': 1}):
            precedent = source.get(doc['drugbank_id'])
            # Le même identifiant peut revenir : on retient le document le
            # plus riche, celui qui porte les codes.
            if precedent and not doc.get('atc_codes'):
                continue
            source[doc['drugbank_id']] = doc
        print("Documents source retenus : %d" % len(source))

        # Index d'unicité : la projection est rejouable, MERGE en dépend pour
        # ne pas dupliquer.
        session.run("CREATE CONSTRAINT atc_code IF NOT EXISTS "
                    "FOR (a:AtcClass) REQUIRE a.code IS UNIQUE")

        # Les quatorze groupes anatomiques, posés d'abord : ils sont la racine
        # de toute la hiérarchie.
        session.run("""
            UNWIND $groupes AS g
            MERGE (a:AtcClass {code: g.code})
            SET a.niveau = 1, a.libelle = g.libelle
        """, groupes=[{'code': c, 'libelle': l}
                      for c, l in GROUPES_ANATOMIQUES.items()])

        classes, liens, indications, sans_atc = 0, 0, 0, 0
        lot_classes, lot_liens, lot_indications = [], [], []

        for identifiant, doc in source.items():
            texte = (doc.get('indication') or '').strip()
            if texte:
                lot_indications.append({'id': identifiant, 'texte': texte})

            codes = doc.get('atc_codes') or []
            if not codes:
                sans_atc += 1
                continue

            for entree in codes:
                niveaux = paliers(entree.get('code'))
                if not niveaux:
                    continue
                for code, niveau in niveaux:
                    lot_classes.append({
                        'code': code, 'niveau': niveau,
                        # Seul le niveau 4 porte un libellé dans la source.
                        'libelle': entree.get('level') if niveau == 4 else None,
                    })
                lot_liens.append({'id': identifiant, 'code': niveaux[-1][0]})

        # Les classes et leurs parents. Le parent se déduit du code : le
        # niveau n est le préfixe du niveau n+1.
        session.run("""
            UNWIND $classes AS c
            MERGE (a:AtcClass {code: c.code})
            SET a.niveau = c.niveau,
                a.libelle = coalesce(a.libelle, c.libelle)
        """, classes=lot_classes)
        classes = len({c['code'] for c in lot_classes})

        parents = []
        for longueur, niveau in NIVEAUX[1:]:
            precedent = NIVEAUX[NIVEAUX.index((longueur, niveau)) - 1][0]
            for c in lot_classes:
                if c['niveau'] == niveau:
                    parents.append({'enfant': c['code'],
                                    'parent': c['code'][:precedent]})
        session.run("""
            UNWIND $liens AS l
            MATCH (e:AtcClass {code: l.enfant}), (p:AtcClass {code: l.parent})
            MERGE (e)-[:HAS_PARENT]->(p)
        """, liens=parents)

        r = session.run("""
            UNWIND $liens AS l
            MATCH (s:DrugbankSubstance {drugbank_id: l.id}),
                  (a:AtcClass {code: l.code})
            MERGE (s)-[:HAS_ATC]->(a)
            RETURN count(*) AS n
        """, liens=lot_liens).single()
        liens = r['n'] if r else 0

        # L'indication est posée en propriété, non en nœud. Le texte est libre
        # et en anglais : en faire 1 493 nœuds distincts fabriquerait une
        # fausse structure. La normalisation est une autre phase.
        r = session.run("""
            UNWIND $lot AS l
            MATCH (s:DrugbankSubstance {drugbank_id: l.id})
            SET s.indication = l.texte
            RETURN count(*) AS n
        """, lot=lot_indications).single()
        indications = r['n'] if r else 0

        couverts = session.run(
            "MATCH (n:DrugbankSubstance)-[:HAS_ATC]->() "
            "RETURN count(DISTINCT n) AS n").single()['n']

    connecteur.close()

    print()
    print("Classes ATC          : %d" % classes)
    print("Liens substance→ATC  : %d" % liens)
    print("Indications posées   : %d" % indications)
    print("Substances sans ATC  : %d" % sans_atc)
    print("Couverture ATC       : %d sur %d — %.1f %%"
          % (couverts, len(identifiants),
             100.0 * couverts / max(len(identifiants), 1)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
