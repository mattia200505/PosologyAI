from neo4j import GraphDatabase
import os
from dotenv import load_dotenv
load_dotenv()
driver = GraphDatabase.driver(os.getenv('NEO4J_URI','neo4j://127.0.0.1:7687'), auth=(os.getenv('NEO4J_USER','neo4j'), os.getenv('NEO4J_PASSWORD','12345678')))
with driver.session() as s:
    titles = s.run("MATCH (m:Medicine) WHERE toLower(m.title) CONTAINS 'doli' RETURN m.title LIMIT 10")
    for rec in titles:
        title = rec['m.title']
        print(repr(title))
    print("---")
    # Full graph query for first one
    r = s.run("""
        MATCH (m:Medicine)
        WHERE toLower(m.title) CONTAINS 'dol'
        AND toLower(m.title) CONTAINS '500'
        RETURN m.title, m.url LIMIT 3
    """)
    for rec in r:
        print(f"Title: {rec['m.title']}")
        print(f"URL:   {rec['m.url']}")
driver.close()
