from neo4j import GraphDatabase
import os
from dotenv import load_dotenv
load_dotenv()
driver = GraphDatabase.driver(os.getenv('NEO4J_URI','neo4j://127.0.0.1:7687'), auth=(os.getenv('NEO4J_USER','neo4j'), os.getenv('NEO4J_PASSWORD','12345678')))
with driver.session() as s:
    r = s.run("""
        MATCH (m1:Medicine)-[:CONTAINS_SUBSTANCE]->(s1:Substance)
        WHERE toLower(s1.name) CONTAINS 'paracetamol'
        WITH DISTINCT m1
        MATCH (m2:Medicine)-[:CONTAINS_SUBSTANCE]->(s2:Substance)
        WHERE toLower(s2.name) CONTAINS 'ibuprofene'
        WITH m1, m2
        OPTIONAL MATCH (m1)-[r:INTERACTS_WITH]-(m2)
        RETURN m1.title AS med1, m2.title AS med2,
               r.severity AS sev, r.effect AS eff
        LIMIT 20
    """)
    found = False
    for rec in r:
        found = True
        print(f"{rec['med1'][:40]:40s} <-> {rec['med2'][:40]:40s} | sev={rec['sev']} | eff={rec['eff']}")
    if not found:
        print("Aucun résultat - vérifions les substances...")
        r2 = s.run("MATCH (s:Substance) WHERE toLower(s.name) CONTAINS 'paracetamol' RETURN s.name")
        for rec in r2:
            print(f"Substance paracetamol: {repr(rec['s.name'])}")
        r3 = s.run("MATCH (s:Substance) WHERE toLower(s.name) CONTAINS 'ibuprofene' RETURN s.name")
        for rec in r3:
            print(f"Substance ibuprofene: {repr(rec['s.name'])}")
driver.close()
