"""
Construction de la base de connaissances Neo4j pour MedicSearch

Importe depuis MongoDB vers Neo4j :
  - 9 800+ Medicaments (nœuds Medicine)
  - 1 600+ Substances actives (nœuds Substance)
  - 800+ Laboratoires (nœuds Laboratory)
  - 4 400+ Familles thérapeutiques (nœuds TherapeuticFamily)
  - 56 Types de médicaments (nœuds MedicineType)
  - 14 Groupes anatomiques (nœuds AnatomicalGroup)
  - 1 200+ Codes ATC (nœuds AtcCode)
  - Interactions, CI, EI stockées comme propriétés textuelles

Usage :
    cd scripts/neo4j
    python build_knowledge_graph.py
"""

import os
import sys
import re
import time
from dotenv import load_dotenv

load_dotenv()

from pymongo import MongoClient
from neo4j import GraphDatabase

# ── Configuration ───────────────────────────────────────────
MONGO_URI = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
MONGO_DB = 'medicsearch'

NEO4J_URI = os.getenv('NEO4J_URI', 'neo4j://127.0.0.1:7687')
NEO4J_USER = os.getenv('NEO4J_USER', 'neo4j')
NEO4J_PASSWORD = os.getenv('NEO4J_PASSWORD', '12345678')
NEO4J_DATABASE = os.getenv('NEO4J_DATABASE', 'neo4j')

BATCH_SIZE = 200


# ── Extraction de texte depuis les sections ─────────────────
def extract_section_text(medicine, keywords):
    """Extrait le texte d'une section par mot-clé dans le titre"""
    texts = []
    for s in medicine.get('sections', []):
        title = s.get('title', '')
        if any(k.lower() in title.lower() for k in keywords):
            for c in s.get('content', []):
                if isinstance(c, dict) and 'text' in c:
                    texts.append(c['text'])
        for ss in s.get('subsections', []):
            sstitle = ss.get('title', '')
            if any(k.lower() in sstitle.lower() for k in keywords):
                for c in ss.get('content', []):
                    if isinstance(c, dict) and 'text' in c:
                        texts.append(c['text'])
            for sss in ss.get('subsections', []):
                ssstitle = sss.get('title', '')
                if any(k.lower() in ssstitle.lower() for k in keywords):
                    for c in sss.get('content', []):
                        if isinstance(c, dict) and 'text' in c:
                            texts.append(c['text'])
    return '\n'.join(texts)


# ── Synchroniseur ───────────────────────────────────────────
class KnowledgeGraphBuilder:
    def __init__(self):
        self.mongo = MongoClient(MONGO_URI)
        self.db = self.mongo[MONGO_DB]
        print(f"MongoDB connecté: {MONGO_URI}")

        try:
            self.driver = GraphDatabase.driver(
                NEO4J_URI,
                auth=(NEO4J_USER, NEO4J_PASSWORD),
                database=NEO4J_DATABASE
            )
            self.driver.verify_connectivity()
            print(f"Neo4j connecté: {NEO4J_URI}")
        except Exception as e:
            print(f"Neo4j erreur: {e}")
            self.driver = None

    def close(self):
        self.mongo.close()
        if self.driver:
            self.driver.close()

    # ── Contraintes ─────────────────────────────────────────
    def create_constraints(self):
        if not self.driver:
            return
        with self.driver.session() as session:
            constraints = [
                "CREATE CONSTRAINT medicine_url IF NOT EXISTS FOR (m:Medicine) REQUIRE m.url IS UNIQUE",
                "CREATE CONSTRAINT substance_name IF NOT EXISTS FOR (s:Substance) REQUIRE s.name IS UNIQUE",
                "CREATE CONSTRAINT lab_name IF NOT EXISTS FOR (l:Laboratory) REQUIRE l.name IS UNIQUE",
                "CREATE CONSTRAINT family_name IF NOT EXISTS FOR (f:TherapeuticFamily) REQUIRE f.name IS UNIQUE",
                "CREATE CONSTRAINT type_name IF NOT EXISTS FOR (t:MedicineType) REQUIRE t.name IS UNIQUE",
                "CREATE CONSTRAINT group_name IF NOT EXISTS FOR (g:AnatomicalGroup) REQUIRE g.name IS UNIQUE",
                "CREATE CONSTRAINT atc_code IF NOT EXISTS FOR (a:AtcCode) REQUIRE a.code IS UNIQUE",
            ]
            for c in constraints:
                try:
                    session.run(c)
                except Exception as e:
                    print(f"  Contrainte: {e}")
        print("Contraintes créées")

    # ── Nettoyage ───────────────────────────────────────────
    def clear_graph(self):
        if not self.driver:
            return
        with self.driver.session() as session:
            session.run("MATCH (n) DETACH DELETE n")
        print("Graphe vidé")

    # ── Import des nœuds ────────────────────────────────────
    def import_medicines(self):
        """Importe tous les médicaments comme nœuds Medicine"""
        if not self.driver:
            return

        total = self.db.medicines.count_documents({})
        print(f"\nImport de {total} médicaments...")

        cursor = self.db.medicines.find({}, {
            'url': 1, 'title': 1, 'update_date': 1,
            'medicine_details.forme': 1,
            'medicine_details.laboratoire': 1,
            'medicine_details.substances_actives': 1,
            'medicine_details.dosages': 1,
            'medicine_details.description_courte': 1,
            'type_medicament': 1,
            'groupe_anatomique': 1,
            'famille_therapeutique': 1,
            'code_atc': 1,
            'sections': 1,
        })

        batch = []
        processed = 0

        with self.driver.session() as session:
            for doc in cursor:
                url = doc.get('url', '')
                if not url:
                    continue

                details = doc.get('medicine_details', {})
                ei_text = extract_section_text(doc, ['Effets ind', 'effets indésirables'])
                ci_text = extract_section_text(doc, ['Contre-indications', 'contre-indication'])
                ind_text = extract_section_text(doc, ['Indications th', 'indications thérapeutiques'])
                inter_text = extract_section_text(doc, ['Interactions avec', 'interactions avec'])

                batch.append({
                    'url': url,
                    'title': doc.get('title', ''),
                    'forme': details.get('forme', ''),
                    'update_date': doc.get('update_date', ''),
                    'type_medicament': doc.get('type_medicament', ''),
                    'groupe_anatomique': doc.get('groupe_anatomique', ''),
                    'famille_therapeutique': doc.get('famille_therapeutique', ''),
                    'code_atc': doc.get('code_atc', ''),
                    'dosages': details.get('dosages', []),
                    'description_courte': details.get('description_courte', ''),
                    'ei_text': ei_text[:5000] if ei_text else '',
                    'ci_text': ci_text[:5000] if ci_text else '',
                    'ind_text': ind_text[:5000] if ind_text else '',
                    'inter_text': inter_text[:5000] if inter_text else '',
                    'substances': [s for s in details.get('substances_actives', []) if s],
                    'laboratoire': details.get('laboratoire', ''),
                })

                if len(batch) >= BATCH_SIZE:
                    self._batch_medicines(session, batch)
                    processed += len(batch)
                    print(f"  {processed}/{total}", end='\r')
                    batch = []

            if batch:
                self._batch_medicines(session, batch)
                processed += len(batch)
                print(f"  {processed}/{total}")

        print(f"Médicaments importés: {processed}")

    def _batch_medicines(self, session, batch):
        """Insère un lot de médicaments et leurs relations"""
        session.run("""
            UNWIND $batch AS doc
            MERGE (m:Medicine {url: doc.url})
            SET m.title = doc.title,
                m.forme = doc.forme,
                m.update_date = doc.update_date,
                m.type_medicament = doc.type_medicament,
                m.groupe_anatomique = doc.groupe_anatomique,
                m.famille_therapeutique = doc.famille_therapeutique,
                m.code_atc = doc.code_atc,
                m.dosages = doc.dosages,
                m.description_courte = doc.description_courte,
                m.ei_text = doc.ei_text,
                m.ci_text = doc.ci_text,
                m.ind_text = doc.ind_text,
                m.inter_text = doc.inter_text
        """, batch=batch)

    # ── Relations ───────────────────────────────────────────
    def create_relationships(self):
        """Crée toutes les relations : Substance, Labo, Famille, Type, Groupe, ATC"""
        if not self.driver:
            return

        total = self.db.medicines.count_documents({})
        print(f"\nCréation des relations...")

        # ─ Substances ──────────────────────────────────────
        print("  Substances...")
        cursor = self.db.medicines.find(
            {"medicine_details.substances_actives": {"$ne": [], "$exists": True}},
            {"url": 1, "medicine_details.substances_actives": 1}
        )
        batch = []
        for doc in cursor:
            url = doc.get('url', '')
            substances = doc.get('medicine_details', {}).get('substances_actives', [])
            for s in substances:
                if s and s.strip():
                    batch.append({'url': url, 'substance': s.strip()})
            if len(batch) >= BATCH_SIZE:
                self._batch_substance_rels(session := self.driver.session(), batch)
                batch = []
        if batch:
            self._batch_substance_rels(session := self.driver.session(), batch)

        # ─ Laboratoires ────────────────────────────────────
        print("  Laboratoires...")
        cursor = self.db.medicines.find(
            {"medicine_details.laboratoire": {"$ne": "", "$exists": True}},
            {"url": 1, "medicine_details.laboratoire": 1}
        )
        batch = []
        for doc in cursor:
            lab = doc.get('medicine_details', {}).get('laboratoire', '')
            if lab and lab.strip():
                batch.append({'url': doc['url'], 'lab': lab.strip()})
            if len(batch) >= BATCH_SIZE:
                self._batch_lab_rels(session := self.driver.session(), batch)
                batch = []
        if batch:
            self._batch_lab_rels(session := self.driver.session(), batch)

        # ─ Familles, Types, Groupes, ATC ───────────────────
        print("  Familles thérapeutiques...")
        self._batch_simple_rel(
            "famille_therapeutique",
            "BELONGS_TO_FAMILY",
            "TherapeuticFamily",
            "name"
        )

        print("  Types de médicaments...")
        self._batch_simple_rel(
            "type_medicament",
            "IS_TYPE",
            "MedicineType",
            "name"
        )

        print("  Groupes anatomiques...")
        self._batch_simple_rel(
            "groupe_anatomique",
            "BELONGS_TO_GROUP",
            "AnatomicalGroup",
            "name"
        )

        print("  Codes ATC...")
        self._batch_simple_rel(
            "code_atc",
            "HAS_ATC_CODE",
            "AtcCode",
            "code"
        )

        print("Relations créées")

    def _batch_substance_rels(self, session, batch):
        session.run("""
            UNWIND $batch AS row
            MERGE (s:Substance {name: row.substance})
            WITH s, row
            MATCH (m:Medicine {url: row.url})
            MERGE (m)-[:CONTAINS_SUBSTANCE]->(s)
        """, batch=batch)
        session.close()

    def _batch_lab_rels(self, session, batch):
        session.run("""
            UNWIND $batch AS row
            MERGE (l:Laboratory {name: row.lab})
            WITH l, row
            MATCH (m:Medicine {url: row.url})
            MERGE (m)-[:MANUFACTURED_BY]->(l)
        """, batch=batch)
        session.close()

    def _batch_simple_rel(self, field, rel_type, node_label, node_prop):
        """Crée une relation simple Medicine → Node"""
        cursor = self.db.medicines.find(
            {field: {"$ne": "", "$exists": True}},
            {"url": 1, field: 1}
        )
        with self.driver.session() as session:
            batch = []
            for doc in cursor:
                val = doc.get(field, '')
                if val and str(val).strip():
                    batch.append({'url': doc['url'], 'val': str(val).strip()})
                if len(batch) >= BATCH_SIZE:
                    session.run(f"""
                        UNWIND $batch AS row
                        MERGE (n:{node_label} {{{node_prop}: row.val}})
                        WITH n, row
                        MATCH (m:Medicine {{url: row.url}})
                        MERGE (m)-[:{rel_type}]->(n)
                    """, batch=batch)
                    batch = []
            if batch:
                session.run(f"""
                    UNWIND $batch AS row
                    MERGE (n:{node_label} {{{node_prop}: row.val}})
                    WITH n, row
                    MATCH (m:Medicine {{url: row.url}})
                    MERGE (m)-[:{rel_type}]->(n)
                """, batch=batch)

    # ── Statistiques ────────────────────────────────────────
    # ── Interactions ────────────────────────────────────────
    def extract_interactions(self):
        """Extrait les relations INTERACTS_WITH du texte d'interactions"""
        if not self.driver:
            return

        import unicodedata

        def strip_accents(s):
            return ''.join(c for c in unicodedata.normalize('NFD', s)
                           if unicodedata.category(c) != 'Mn')

        print("\nExtraction des interactions depuis inter_text...")

        # 1. Récupérer toutes les substances et leurs noms normalisés
        with self.driver.session() as session:
            result = session.run("MATCH (s:Substance) RETURN s.name AS name")
            all_substances = {strip_accents(r['name']).lower(): r['name']
                              for r in result if r['name']}

            # 2. Récupérer pour chaque médicament : url, titres, substances, inter_text
            result = session.run("""
                MATCH (m:Medicine)
                OPTIONAL MATCH (m)-[:CONTAINS_SUBSTANCE]->(s:Substance)
                RETURN m.url AS url, m.title AS title, m.inter_text AS inter_text,
                       collect(s.name) AS substances
            """)
            medicines = []
            for r in result:
                if r['inter_text'] and r['inter_text'] not in ('Sans objet.', ''):
                    medicines.append({
                        'url': r['url'],
                        'title': r['title'],
                        'substances': set(r['substances']),
                        'inter_text': r['inter_text']
                    })

        print(f"  Médicaments avec texte d'interactions: {len(medicines)}")

        # 3. Pour chaque médicament, chercher les substances mentionnées
        rel_batch = []
        total_rels = 0
        sub_names_lower = {strip_accents(n).lower(): n for n in all_substances.values()}

        for med in medicines:
            text_lower = strip_accents(med['inter_text']).lower()
            mentioned = set()

            for norm_name, orig_name in sub_names_lower.items():
                if norm_name in text_lower:
                    # Vérifier que ce n'est pas une substance que ce médicament contient déjà
                    if orig_name not in med['substances']:
                        mentioned.add(orig_name)

            if not mentioned:
                continue

            # 4. Pour chaque substance mentionnée, trouver les médicaments qui la contiennent
            with self.driver.session() as session:
                for sub in mentioned:
                    result = session.run("""
                        MATCH (m:Medicine)-[:CONTAINS_SUBSTANCE]->(s:Substance {name: $sub})
                        RETURN m.url AS other_url
                    """, sub=sub)

                    for r in result:
                        if r['other_url'] != med['url']:
                            rel_batch.append({
                                'url1': med['url'],
                                'url2': r['other_url'],
                                'substance': sub
                            })
                            total_rels += 1

                            if len(rel_batch) >= BATCH_SIZE:
                                self._batch_interactions(rel_batch)
                                print(f"  Relations INTERACTS_WITH: {total_rels}", end='\r')
                                rel_batch = []

        if rel_batch:
            self._batch_interactions(rel_batch)

        print(f"  Relations INTERACTS_WITH créées: {total_rels}")

    def _batch_interactions(self, batch):
        with self.driver.session() as session:
            session.run("""
                UNWIND $batch AS row
                MATCH (m1:Medicine {url: row.url1})
                MATCH (m2:Medicine {url: row.url2})
                MERGE (m1)-[r:INTERACTS_WITH]-(m2)
                SET r.substance = row.substance,
                    r.source = 'section_4.5'
            """, batch=batch)

    def get_stats(self):
        if not self.driver:
            return
        with self.driver.session() as session:
            result = session.run("""
                MATCH (n)
                RETURN labels(n) AS type, count(*) AS total
                ORDER BY type
            """)
            print("\n=== STATISTIQUES NEO4J ===")
            for record in result:
                print(f"  {str(record['type'][0]):20s}: {record['total']}")

            result = session.run("""
                MATCH ()-[r]->()
                RETURN type(r) AS relation, count(*) AS total
                ORDER BY relation
            """)
            for record in result:
                print(f"  {record['relation']:25s}: {record['total']}")


# ── Main ────────────────────────────────────────────────────
def main():
    print("=" * 60)
    print("  CONSTRUCTION DE LA BASE DE CONNAISSANCES NEO4J")
    print("=" * 60)

    builder = KnowledgeGraphBuilder()
    if not builder.driver:
        print("Neo4j non disponible")
        builder.close()
        return

    try:
        action = input("\nAction (sync/interactions/clear/stats) [sync]: ").strip() or 'sync'

        if action == 'clear':
            builder.clear_graph()
        elif action == 'stats':
            builder.get_stats()
        elif action == 'interactions':
            builder.extract_interactions()
            builder.get_stats()
        else:
            t0 = time.time()
            builder.clear_graph()
            builder.create_constraints()
            builder.import_medicines()
            builder.create_relationships()
            builder.extract_interactions()
            builder.get_stats()
            elapsed = time.time() - t0
            print(f"\nDurée: {elapsed:.1f}s")

    finally:
        builder.close()

    print("\n" + "=" * 60)
    print("  TERMINÉ")
    print("=" * 60)


if __name__ == '__main__':
    main()
