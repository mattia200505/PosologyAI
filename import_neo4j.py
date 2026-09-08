"""Import Neo4j — Drugs, Targets, ATC, FAERS, DDInter (drug-to-drug)"""
from neo4j import GraphDatabase
import json
import os
import sys
import time

# ── Config ──────────────────────────────────────────────────────────────────
URI = "bolt://127.0.0.1:7687"
AUTH = ("neo4j", "12345678")
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_PATH = os.path.join(_SCRIPT_DIR, "data")
BATCH_SIZE = 500

driver = GraphDatabase.driver(URI, auth=AUTH)

# ── Helpers ────────────────────────────────────────────────────────────────

def load_json(name):
    path = os.path.join(DATA_PATH, name)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def load_csv(name):
    import pandas as pd
    path = os.path.join(DATA_PATH, name)
    if not os.path.exists(path):
        raise FileNotFoundError(f"Missing: {path}")
    return pd.read_csv(path).to_dict("records")

def chunks(data, size=BATCH_SIZE):
    for i in range(0, len(data), size):
        yield data[i:i+size]

def run_batch(session, func, data, name):
    total = len(data)
    done = 0
    print(f"\nSTART: {name} ({total} records)")
    for batch in chunks(data):
        try:
            session.execute_write(func, batch)
        except Exception as e:
            print(f"  ERROR [{name}]: {e}")
        done += len(batch)
        print(f"  {name}: {done}/{total}")
    print(f"DONE: {name}")

# ── Reset ──────────────────────────────────────────────────────────────────

def reset(tx):
    tx.run("MATCH (n) DETACH DELETE n")

# ── Imports ────────────────────────────────────────────────────────────────

def import_drugs(tx, batch):
    tx.run("""
    UNWIND $batch AS row
    MERGE (d:Drug {id: row.id})
    SET d.name = row.name,
        d.smiles = row.smiles,
        d.formula = row.cd_formula,
        d.weight = toFloat(coalesce(row.cd_molweight, '0'))
    """, batch=batch)

def import_targets(tx, batch):
    tx.run("""
    UNWIND $batch AS row
    MERGE (t:Target {id: row.id})
    SET t.name = row.name,
        t.gene = row.gene,
        t.accession = row.accession,
        t.swissprot = row.swissprot
    """, batch=batch)

def import_atc(tx, batch):
    tx.run("""
    UNWIND $batch AS row
    MERGE (a:ATC {code: row.code})
    SET a.name = row.name
    """, batch=batch)

def import_faers(tx, batch):
    tx.run("""
    UNWIND $batch AS row
    MATCH (d:Drug {id: row.struct_id})
    MERGE (e:AdverseEvent {name: row.meddra_name})
    MERGE (d)-[r:CAUSES]->(e)
    SET r.llr = toFloat(coalesce(row.llr, '0')),
        r.drug_ae = toInteger(coalesce(row.drug_ae, '0'))
    """, batch=batch)

def import_td2tc(tx, batch):
    tx.run("""
    UNWIND $batch AS row
    MATCH (d:Drug {id: row.component_id})
    MATCH (t:Target {id: row.target_id})
    MERGE (d)-[:AFFECTS]->(t)
    """, batch=batch)

def import_ddinter(tx, batch, source_file, category):
    tx.run("""
    UNWIND $batch AS row
    MERGE (a:Drug {id: row.DDInterID_A})
    SET a.name = coalesce(a.name, row.Drug_A)
    MERGE (b:Drug {id: row.DDInterID_B})
    SET b.name = coalesce(b.name, row.Drug_B)
    MERGE (a)-[r:INTERACTS_WITH]->(b)
    SET r.level = row.Level,
        r.source_file = $source_file,
        r.category = $category
    """, batch=batch, source_file=source_file, category=category)

# ── Main ───────────────────────────────────────────────────────────────────

DDINTER_FILES = [
    "ddinter_downloads_code_A.csv",
    "ddinter_downloads_code_B.csv",
    "ddinter_downloads_code_D.csv",
    "ddinter_downloads_code_H.csv",
    "ddinter_downloads_code_L.csv",
    "ddinter_downloads_code_P.csv",
    "ddinter_downloads_code_R.csv",
    "ddinter_downloads_code_V.csv",
]

with driver.session() as session:
    print("=" * 50)
    print("RESET DATABASE")
    print("=" * 50)
    session.execute_write(reset)

    # Créer contraintes et index
    print("\nCREATING CONSTRAINTS & INDEXES")
    try:
        session.run("CREATE CONSTRAINT drug_id IF NOT EXISTS FOR (d:Drug) REQUIRE d.id IS UNIQUE")
        session.run("CREATE INDEX drug_name IF NOT EXISTS FOR (d:Drug) ON (d.name)")
    except Exception as e:
        print(f"  Index warning: {e}")

    # 1. Drugs
    print("\n" + "=" * 50)
    drugs = load_json("structures.json")
    run_batch(session, import_drugs, drugs, "DRUGS")

    # 2. Targets
    targets = load_json("targets.json")
    if len(targets) > 0:
        run_batch(session, import_targets, targets, "TARGETS")
    else:
        print("\nSKIP TARGETS: empty file")

    # 3. ATC codes
    atc = load_json("atc.json")
    run_batch(session, import_atc, atc, "ATC")

    # 4. FAERS (adverse events)
    faers = load_json("faers.json")
    run_batch(session, import_faers, faers, "FAERS")

    # 5. Drug → Target relations
    td2tc = load_json("td2tc.json")
    run_batch(session, import_td2tc, td2tc, "DRUG-TARGET")

    # 6. DDInter (drug-to-drug interactions)
    ddinter_loaded = 0
    for file in DDINTER_FILES:
        path = os.path.join(DATA_PATH, file)
        if not os.path.exists(path):
            print(f"\nSKIP DDINTER {file}: file not found")
            continue
        print(f"\nDDINTER: {file}")
        category = file.split("_code_")[-1].replace(".csv", "")
        data = load_csv(file)
        for batch in chunks(data):
            try:
                session.execute_write(import_ddinter, batch, file, category)
            except Exception as e:
                print(f"  ERROR DDINTER: {e}")
        ddinter_loaded += len(data)
        print(f"  DDINTER {file}: {len(data)} interactions imported")

    print(f"\nTotal DDInter interactions: {ddinter_loaded}")

driver.close()

# Stats
print("\n" + "=" * 50)
print("IMPORT COMPLETE")
print("=" * 50)
print(f"  Drugs:        {len(drugs)}")
print(f"  Targets:      {len(targets)}")
print(f"  ATC:          {len(atc)}")
print(f"  FAERS:        {len(faers)}")
print(f"  Drug-Target:  {len(td2tc)}")
print(f"  DDInter:      {ddinter_loaded}")
