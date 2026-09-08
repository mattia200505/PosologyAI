from neo4j import GraphDatabase
import os, unicodedata
from dotenv import load_dotenv
load_dotenv()
driver = GraphDatabase.driver(os.getenv('NEO4J_URI','neo4j://127.0.0.1:7687'), auth=(os.getenv('NEO4J_USER','neo4j'), os.getenv('NEO4J_PASSWORD','12345678')))

def strip_accents(s):
    return ''.join(c for c in unicodedata.normalize('NFD', s) if unicodedata.category(c) != 'Mn')

with driver.session() as s:
    # Find paracetamol-like substances
    all_subs = s.run("MATCH (s:Substance) RETURN s.name AS name ORDER BY s.name")
    for rec in all_subs:
        name = rec['name']
        key = strip_accents(name).lower()
        if 'paracetamol' in key or 'doliprane' in key:
            print(f"FOUND: {repr(name)}")
        if 'ibuprofene' in key or 'ibuprof' in key:
            print(f"FOUND: {repr(name)}")
driver.close()
