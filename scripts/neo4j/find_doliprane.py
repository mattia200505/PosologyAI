from neo4j import GraphDatabase
import os
from dotenv import load_dotenv
load_dotenv()
driver = GraphDatabase.driver(os.getenv('NEO4J_URI','neo4j://127.0.0.1:7687'), auth=(os.getenv('NEO4J_USER','neo4j'), os.getenv('NEO4J_PASSWORD','12345678')))
with driver.session() as s:
    r = s.run("MATCH (m:Medicine) WHERE toLower(m.title) CONTAINS 'doliprane' RETURN m.title LIMIT 5")
    for rec in r:
        print(rec['m.title'])
    print("---")
    r = s.run("MATCH (m:Medicine) WHERE toLower(m.title) CONTAINS 'ibuprofene' RETURN m.title LIMIT 5")
    for rec in r:
        print(rec['m.title'])
driver.close()
