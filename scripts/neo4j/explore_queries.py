"""
Neo4j queries for exploring MedicSearch knowledge graph
"""
from neo4j import GraphDatabase
import os
from dotenv import load_dotenv
load_dotenv()

NEO4J_URI = os.getenv('NEO4J_URI', 'neo4j://127.0.0.1:7687')
NEO4J_USER = os.getenv('NEO4J_USER', 'neo4j')
NEO4J_PASSWORD = os.getenv('NEO4J_PASSWORD', '12345678')

driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))

with driver.session() as s:
    print("=" * 70)
    print("1. MÉDICAMENTS AVEC LE PLUS DE RELATIONS")
    print("=" * 70)
    r = s.run("""
        MATCH (m:Medicine)-[r]-(n)
        RETURN m.title AS titre, m.url AS url,
               count(DISTINCT r) AS total_relations,
               count(DISTINCT n) AS voisins
        ORDER BY total_relations DESC LIMIT 8
    """)
    for rec in r:
        print(f"  {rec['titre'][:48]:48s} | {rec['total_relations']:3d} relations | {rec['voisins']:3d} voisins")

    print()
    print("=" * 70)
    print("2. RÉPARTITION PAR SÉVÉRITÉ D'INTERACTION")
    print("=" * 70)
    r = s.run("""
        MATCH ()-[r:INTERACTS_WITH]-()
        RETURN r.severity AS severite, count(*) AS total
        ORDER BY total DESC
    """)
    for rec in r:
        print(f"  {rec['severite']:15s}: {rec['total']}")

    print()
    print("=" * 70)
    print("3. TOP SUBSTANCES LES PLUS CONNECTÉES (interactions)")
    print("=" * 70)
    r = s.run("""
        MATCH (s:Substance)<-[:CONTAINS_SUBSTANCE]-()<-[:INTERACTS_WITH]-()-[:CONTAINS_SUBSTANCE]->(s2:Substance)
        RETURN s.name AS substance, count(DISTINCT s2) AS interactions_connues
        ORDER BY interactions_connues DESC LIMIT 15
    """)
    for rec in r:
        print(f"  {rec['substance'][:35]:35s}: {rec['interactions_connues']} interactions")

    print()
    print("=" * 70)
    print("4. MÉDICAMENTS PAR TYPE")
    print("=" * 70)
    r = s.run("""
        MATCH (m:Medicine)-[:IS_TYPE]->(t:MedicineType)
        RETURN t.name AS type, count(m) AS total
        ORDER BY total DESC LIMIT 10
    """)
    for rec in r:
        print(f"  {rec['type'][:30]:30s}: {rec['total']} médicaments")

    print()
    print("=" * 70)
    print("5. LABORATOIRES AVEC LE PLUS DE MÉDICAMENTS")
    print("=" * 70)
    r = s.run("""
        MATCH (l:Laboratory)<-[:MANUFACTURED_BY]-(m:Medicine)
        RETURN l.name AS laboratoire, count(m) AS medicaments
        ORDER BY medicaments DESC LIMIT 10
    """)
    for rec in r:
        print(f"  {rec['laboratoire'][:35]:35s}: {rec['medicaments']} médicaments")

    print()
    print("=" * 70)
    print("6. FAMILLES THÉRAPEUTIQUE LES PLUS REPRÉSENTÉES")
    print("=" * 70)
    r = s.run("""
        MATCH (f:TherapeuticFamily)<-[:BELONGS_TO_FAMILY]-(m:Medicine)
        RETURN f.name AS famille, count(m) AS total
        ORDER BY total DESC LIMIT 10
    """)
    for rec in r:
        print(f"  {rec['famille'][:40]:40s}: {rec['total']} médicaments")

    print()
    print("=" * 70)
    print("7. INTERACTIONS LES PLUS GRAVES (high severity examples)")
    print("=" * 70)
    r = s.run("""
        MATCH (m1:Medicine)-[r:INTERACTS_WITH]-(m2:Medicine)
        WHERE r.severity = 'high'
        RETURN m1.title AS med1, m2.title AS med2,
               r.effect AS effet, r.recommendation AS reco
        LIMIT 10
    """)
    for rec in r:
        print(f"  {rec['med1'][:35]:35s} <-> {rec['med2'][:35]:35s}")
        print(f"    Effet: {rec['effet']}")
        print(f"    Reco:  {rec['reco']}")
        print()

    print()
    print("=" * 70)
    print("8. GRAPHE COMPLET D'UN MÉDICAMENT (ex: DOLIPRANE)")
    print("=" * 70)
    r = s.run("""
        MATCH (m:Medicine {title: 'DOLIPRANE 500 mg, gélule'})
        OPTIONAL MATCH (m)-[r1:CONTAINS_SUBSTANCE]->(s:Substance)
        OPTIONAL MATCH (m)-[r2:MANUFACTURED_BY]->(l:Laboratory)
        OPTIONAL MATCH (m)-[r3:IS_TYPE]->(t:MedicineType)
        OPTIONAL MATCH (m)-[r4:BELONGS_TO_FAMILY]->(f:TherapeuticFamily)
        OPTIONAL MATCH (m)-[r5:BELONGS_TO_GROUP]->(g:AnatomicalGroup)
        OPTIONAL MATCH (m)-[r6:HAS_ATC_CODE]->(a:AtcCode)
        RETURN m.title AS medicament,
               collect(DISTINCT s.name) AS substances,
               collect(DISTINCT l.name) AS laboratoire,
               collect(DISTINCT t.name) AS type,
               collect(DISTINCT f.name) AS famille,
               collect(DISTINCT g.name) AS groupe,
               collect(DISTINCT a.code) AS atc
    """)
    for rec in r:
        print(f"\n  Médicament: {rec['medicament']}")
        print(f"  ┌─ Substances:      {', '.join(rec['substances'])}")
        print(f"  ├─ Laboratoire:     {', '.join(rec['laboratoire'])}")
        print(f"  ├─ Type:            {', '.join(rec['type'])}")
        print(f"  ├─ Famille thérap.: {', '.join(rec['famille'])}")
        print(f"  ├─ Groupe anat.:    {', '.join(rec['groupe'])}")
        print(f"  └─ Code ATC:        {', '.join(rec['atc'])}")

    print()
    print("=" * 70)
    print("9. INTERACTIONS DE DOLIPRANE AVEC D'AUTRES MÉDICAMENTS")
    print("=" * 70)
    r = s.run("""
        MATCH (m:Medicine {title: 'DOLIPRANE 500 mg, gélule'})-[r:INTERACTS_WITH]-(other:Medicine)
        RETURN other.title AS medicament,
               r.severity AS severite,
               r.effect AS effet
        ORDER BY r.severity DESC LIMIT 15
    """)
    for rec in r:
        print(f"  {rec['medicament'][:40]:40s} | {str(rec['severite']):10s} | {rec['effet']}")

    print()
    print("=" * 70)
    print("10. STATISTIQUES GÉNÉRALES DU GRAPHE")
    print("=" * 70)
    r = s.run("MATCH (n) RETURN count(n) AS total_nodes")
    nodes = r.single()['total_nodes']
    r = s.run("MATCH ()-[r]->() RETURN count(r) AS total_rels")
    rels = r.single()['total_rels']
    print(f"  Nœuds:      {nodes}")
    print(f"  Relations:  {rels}")

    r = s.run("""
        MATCH (m:Medicine)-[r:INTERACTS_WITH]-(n:Medicine)
        RETURN count(DISTINCT m) AS med_avec_interactions
    """)
    meds = r.single()['med_avec_interactions']
    print(f"  Médicaments avec interactions: {meds}")

driver.close()
