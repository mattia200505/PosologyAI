from neo4j import GraphDatabase
import os
from dotenv import load_dotenv
load_dotenv()
driver = GraphDatabase.driver(os.getenv('NEO4J_URI','neo4j://127.0.0.1:7687'), auth=(os.getenv('NEO4J_USER','neo4j'), os.getenv('NEO4J_PASSWORD','12345678')))
with driver.session() as s:
    r = s.run("""
        MATCH (m:Medicine)-[:CONTAINS_SUBSTANCE]->(s:Substance)
        WHERE toLower(s.name) CONTAINS 'paracetamol'
        RETURN m.title AS med, s.name AS sub
        LIMIT 5
    """)
    for rec in r:
        print(f"  {rec['med']} -> {rec['sub']}")
    print("---")
    # Full graph for one medicine
    r = s.run("""
        MATCH (m:Medicine {url: 'http://www.theriaque.org/apps/monographie/medicaments/DOLIPRANE-500-mg-gelule-1'})
        OPTIONAL MATCH (m)-[:CONTAINS_SUBSTANCE]->(s:Substance)
        OPTIONAL MATCH (m)-[:MANUFACTURED_BY]->(l:Laboratory)
        OPTIONAL MATCH (m)-[:IS_TYPE]->(t:MedicineType)
        OPTIONAL MATCH (m)-[:BELONGS_TO_FAMILY]->(f:TherapeuticFamily)
        OPTIONAL MATCH (m)-[:BELONGS_TO_GROUP]->(g:AnatomicalGroup)
        OPTIONAL MATCH (m)-[:HAS_ATC_CODE]->(a:AtcCode)
        OPTIONAL MATCH (m)-[r:INTERACTS_WITH]-(other:Medicine)
        RETURN m.title AS med,
               collect(DISTINCT s.name) AS substances,
               collect(DISTINCT l.name) AS labo,
               collect(DISTINCT t.name) AS type,
               collect(DISTINCT f.name) AS famille,
               collect(DISTINCT g.name) AS groupe,
               collect(DISTINCT a.code) AS atc,
               count(DISTINCT other) AS interactions,
               collect(DISTINCT other.title)[0..5] AS exemples_interactions
    """)
    for rec in r:
        print(f"  Médicament: {rec['med']}")
        print(f"  Substances: {', '.join(rec['substances'])}")
        print(f"  Labo:       {', '.join(rec['labo'])}")
        print(f"  Type:       {', '.join(rec['type'])}")
        print(f"  Famille:    {', '.join(rec['famille'])}")
        print(f"  Groupe:     {', '.join(rec['groupe'])}")
        print(f"  ATC:        {', '.join(rec['atc'])}")
        print(f"  Interactions: {rec['interactions']}")
        print(f"  Ex: {', '.join(rec['exemples_interactions'][:5])}")
driver.close()
