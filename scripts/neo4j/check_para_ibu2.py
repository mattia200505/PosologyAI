from neo4j import GraphDatabase
import os
from dotenv import load_dotenv
load_dotenv()
driver = GraphDatabase.driver(os.getenv('NEO4J_URI','neo4j://127.0.0.1:7687'), auth=(os.getenv('NEO4J_USER','neo4j'), os.getenv('NEO4J_PASSWORD','12345678')))
with driver.session() as s:
    # Direct queries with proper accent handling
    r = s.run("MATCH (s:Substance) WHERE s.name CONTAINS 'Parac\u00e9tamol' RETURN s.name")
    print("Paracetamol substances:")
    for rec in r:
        print(f"  {repr(rec['s.name'])}")
    
    r = s.run("MATCH (s:Substance) WHERE s.name CONTAINS 'Ibuprof\u00e8ne' RETURN s.name")
    print("Ibuprofene substances:")
    for rec in r:
        print(f"  {repr(rec['s.name'])}")

    # Count all substances for paracetamol medicines
    r = s.run("""
        MATCH (m:Medicine)-[:CONTAINS_SUBSTANCE]->(s:Substance)
        WHERE s.name CONTAINS 'Parac\u00e9tamol'
        RETURN count(DISTINCT m) AS nb_meds
    """)
    for rec in r:
        print(f"Nb medicines with Paracetamol: {rec['nb_meds']}")

    # Check interactions with alcohol for paracetamol
    r = s.run("""
        MATCH (m1:Medicine)-[r:INTERACTS_WITH]-(m2:Medicine)
        WHERE m1.title CONTAINS 'DOLIPRANE'
        RETURN m1.title, m2.title, r.severity, r.effect
        LIMIT 10
    """)
    print("DOLIPRANE interactions:")
    for rec in r:
        print(f"  {rec['m1.title'][:40]:40s} <-> {rec['m2.title'][:40]:40s} | {rec['r.severity']} | {rec['r.effect']}")

driver.close()
