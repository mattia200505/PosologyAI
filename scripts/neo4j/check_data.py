from neo4j import GraphDatabase
import os
from dotenv import load_dotenv
load_dotenv()
driver = GraphDatabase.driver(os.getenv('NEO4J_URI','neo4j://127.0.0.1:7687'), auth=(os.getenv('NEO4J_USER','neo4j'), os.getenv('NEO4J_PASSWORD','12345678')))
with driver.session() as s:
    # Check INTERACTS_WITH properties
    r = s.run("""
        MATCH ()-[r:INTERACTS_WITH]-()
        RETURN r.severity AS sev, r.effect AS eff, r.mechanism AS mech,
               r.recommendation AS reco, r.substance1 AS s1, r.substance2 AS s2,
               r.source AS src, keys(r) AS props
        LIMIT 5
    """)
    print("=== Sample INTERACTS_WITH properties ===")
    for rec in r:
        print(dict(rec))

    # Count those with missing properties
    r = s.run("""
        MATCH ()-[r:INTERACTS_WITH]-()
        RETURN
            count(r) AS total,
            sum(CASE WHEN r.severity IS NULL THEN 1 ELSE 0 END) AS no_severity,
            sum(CASE WHEN r.effect IS NULL THEN 1 ELSE 0 END) AS no_effect,
            sum(CASE WHEN r.mechanism IS NULL THEN 1 ELSE 0 END) AS no_mechanism,
            sum(CASE WHEN r.recommendation IS NULL THEN 1 ELSE 0 END) AS no_recommendation
    """)
    print("\n=== Property completeness ===")
    for rec in r:
        print(dict(rec))

    # Check for duplicate relationships (from old build + new)
    r = s.run("""
        MATCH (m1:Medicine)-[r:INTERACTS_WITH]-(m2:Medicine)
        WITH m1, m2, count(r) AS nb, collect(properties(r)) AS props
        WHERE nb > 1
        RETURN m1.title, m2.title, nb LIMIT 10
    """)
    print("\n=== Duplicate relationships ===")
    for rec in r:
        print(dict(rec))

    # Clean duplicates: keep only the one with most properties
    r = s.run("""
        MATCH (m1:Medicine)-[r:INTERACTS_WITH]-(m2:Medicine)
        WHERE m1.url < m2.url
        WITH m1, m2, count(r) AS nb
        WHERE nb > 1
        RETURN count(*) AS duplicate_pairs
    """)
    for rec in r:
        print(f"Duplicate pairs: {rec['duplicate_pairs']}")

    # Check substances connected to paracetamol and ibuprofen
    r = s.run("""
        MATCH (s:Substance)
        WHERE toLower(s.name) CONTAINS 'paracetamol'
        RETURN s.name LIMIT 5
    """)
    print("\n=== Paracetamol substances ===")
    for rec in r:
        print(rec['s.name'])

    r = s.run("""
        MATCH (s:Substance)
        WHERE toLower(s.name) CONTAINS 'ibuprofene'
        RETURN s.name LIMIT 5
    """)
    print("\n=== Ibuprofene substances ===")
    for rec in r:
        print(rec['s.name'])

    # Count total interactions
    r = s.run("MATCH ()-[r:INTERACTS_WITH]-() RETURN count(DISTINCT r) AS total")
    for rec in r:
        print(f"\nTotal INTERACTS_WITH relationships: {rec['total']}")

driver.close()
