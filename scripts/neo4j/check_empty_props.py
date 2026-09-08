from neo4j import GraphDatabase
import os
from dotenv import load_dotenv
load_dotenv()
driver = GraphDatabase.driver(os.getenv('NEO4J_URI','neo4j://127.0.0.1:7687'), auth=(os.getenv('NEO4J_USER','neo4j'), os.getenv('NEO4J_PASSWORD','12345678')))
with driver.session() as s:
    r = s.run("""
        MATCH ()-[r:INTERACTS_WITH]-()
        RETURN
            count(r) AS total,
            sum(CASE WHEN r.mechanism IS NULL OR r.mechanism = '' THEN 1 ELSE 0 END) AS empty_mechanism,
            sum(CASE WHEN r.recommendation IS NULL OR r.recommendation = '' THEN 1 ELSE 0 END) AS empty_recommendation,
            sum(CASE WHEN r.effect IS NULL OR r.effect = '' THEN 1 ELSE 0 END) AS empty_effect
    """)
    for rec in r:
        print(f"Total: {rec['total']}")
        print(f"Empty mechanism: {rec['empty_mechanism']}")
        print(f"Empty recommendation: {rec['empty_recommendation']}")
        print(f"Empty effect: {rec['empty_effect']}")
    
    print("\n--- Sample empty mechanism ---")
    r = s.run("""
        MATCH (m1:Medicine)-[r:INTERACTS_WITH]-(m2:Medicine)
        WHERE r.mechanism IS NULL OR r.mechanism = ''
        RETURN m1.title, m2.title, r.severity, r.effect LIMIT 5
    """)
    for rec in r:
        print(f"{rec['m1.title'][:40]:40s} <-> {rec['m2.title'][:40]:40s} | sev={rec['r.severity']} | eff={rec['r.effect']}")

    print("\n--- Sample with mechanism filled ---")
    r = s.run("""
        MATCH (m1:Medicine)-[r:INTERACTS_WITH]-(m2:Medicine)
        WHERE r.mechanism IS NOT NULL AND r.mechanism <> ''
        RETURN m1.title, m2.title, r.mechanism LIMIT 3
    """)
    for rec in r:
        print(f"{rec['m1.title'][:40]:40s} <-> {rec['m2.title'][:40]:40s} | mech={rec['r.mechanism']}")
driver.close()
