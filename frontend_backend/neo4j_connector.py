"""
Module de connexion et synchronisation MongoDB vers Neo4j

Mainient la rétrocompatibilité avec l'ancien schéma (Medicine/Substance/Laboratory)
tout en offrant le nouveau Knowledge Graph professionnel (Drug/ActiveIngredient/...).
"""
from neo4j import GraphDatabase
from pymongo import MongoClient
import logging
import os
import sys

logger = logging.getLogger(__name__)

# Import du nouveau Knowledge Graph (chemin relatif)
try:
    _kg_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'neo4j_kg')
    if _kg_path not in sys.path:
        sys.path.insert(0, _kg_path)
    from python.knowledge_graph import MedicalKnowledgeGraph
    HAS_NEW_KG = True
except ImportError:
    MedicalKnowledgeGraph = None
    HAS_NEW_KG = False
    logger.warning("MedicalKnowledgeGraph non disponible — utiliser l'ancien schéma")


class Neo4jConnector:
    """
    Gestionnaire de connexion Neo4j pour les données médicales.
    Pont entre l'ancien schéma (Medicine/Substance/Laboratory) et
    le nouveau Knowledge Graph (Drug/ActiveIngredient/Disease/...).
    """

    def __init__(self, uri, user, password, database="neo4j"):
        self.uri = uri
        self.user = user
        self.password = password
        self.database = database
        self.driver = None
        self.kg = None  # Nouveau Knowledge Graph (optionnel)

        # Initialiser le nouveau KG si disponible
        if HAS_NEW_KG:
            self.kg = MedicalKnowledgeGraph(
                uri=uri, user=user, password=password, database=database
            )

    def connect(self):
        """Établit la connexion au serveur Neo4j"""
        try:
            self.driver = GraphDatabase.driver(
                self.uri,
                auth=(self.user, self.password),
                connection_timeout=5.0,
                max_connection_lifetime=3600,
                max_connection_pool_size=50,
                connection_acquisition_timeout=30.0,
            )
            self.driver.verify_connectivity()
            logger.info(f"Connexion Neo4j établie: {self.uri} (db: {self.database})")

            # Connecter le nouveau KG si disponible
            if self.kg:
                self.kg.connect()

            return True
        except Exception as e:
            logger.error(f"Erreur de connexion Neo4j: {e}")
            if self.driver:
                try:
                    self.driver.close()
                except:
                    pass
            self.driver = None
            return False

    def close(self):
        """Ferme la connexion Neo4j"""
        if self.kg:
            self.kg.close()
        if self.driver:
            self.driver.close()
            logger.info("Connexion Neo4j fermée")

    # Les contraintes et index portant sur l'etiquette `Drug` ont ete retires
    # avec elle : ils declaraient une unicite et des index sur des noeuds qui
    # n'existent plus, et les recreer ferait croire que l'etiquette est encore
    # en service.

    def create_constraints(self):
        """
        Crée les contraintes et index pour les DEUX schémas.
        Ancien : Medicine/Substance/Laboratory
        Nouveau : Drug/ActiveIngredient/Disease/Effect/Contraindication/DrugClass
        """
        with self.driver.session(database=self.database) as session:
            # ── Ancien schéma (rétrocompatibilité) ──
            session.run("CREATE CONSTRAINT medicine_url IF NOT EXISTS FOR (m:Medicine) REQUIRE m.url IS UNIQUE")
            session.run("CREATE INDEX substance_name IF NOT EXISTS FOR (s:Substance) ON (s.name)")
            session.run("CREATE INDEX laboratory_name IF NOT EXISTS FOR (l:Laboratory) ON (l.name)")
            session.run("CREATE INDEX med_title_index IF NOT EXISTS FOR (m:Medicine) ON (m.title)")

            # ── Nouveau schéma (Knowledge Graph avancé) ──
            session.run("CREATE CONSTRAINT ingredient_name IF NOT EXISTS FOR (i:ActiveIngredient) REQUIRE i.name IS UNIQUE")
            session.run("CREATE CONSTRAINT disease_name IF NOT EXISTS FOR (d:Disease) REQUIRE d.name IS UNIQUE")
            session.run("CREATE CONSTRAINT effect_id IF NOT EXISTS FOR (e:Effect) REQUIRE e.id IS UNIQUE")
            session.run("CREATE CONSTRAINT contra_id IF NOT EXISTS FOR (c:Contraindication) REQUIRE c.id IS UNIQUE")
            session.run("CREATE CONSTRAINT class_name IF NOT EXISTS FOR (c:DrugClass) REQUIRE c.name IS UNIQUE")
            session.run("CREATE INDEX interaction_severity IF NOT EXISTS FOR ()-[r:INTERACTS_WITH]-() ON (r.severity)")

            logger.info("Contraintes et index créés (ancien + nouveau schéma)")

    # ── Anciennes méthodes (rétrocompatibilité) ─────────────────────────────

    def sync_medicine_from_mongo(self, medicine_doc):
        """
        Synchronise un médicament MongoDB vers Neo4j.
        Version améliorée : crée à la fois l'ancien (Medicine) et le nouveau (Drug).
        """
        medicine_url = medicine_doc.get('url')
        if not medicine_url:
            return

        title = medicine_doc.get('title', '')
        details = medicine_doc.get('medicine_details', {}) or {}
        substances = details.get('substances_actives', []) or []
        laboratory = details.get('laboratoire', '') or ''
        forme = details.get('forme', '') or ''
        dosages = details.get('dosages', []) or []

        with self.driver.session(database=self.database) as session:
            # ── Ancien nœud Medicine (rétrocompatibilité) ──
            session.run("""
                MERGE (m:Medicine {url: $url})
                SET m.title = $title,
                    m.forme = $forme,
                    m.update_date = $update_date,
                    m.last_scraped = $last_scraped,
                    m.document_type = $document_type
            """, {
                'url': medicine_url,
                'title': title,
                'forme': forme,
                'update_date': medicine_doc.get('update_date'),
                'last_scraped': str(medicine_doc.get('last_scraped', '')),
                'document_type': medicine_doc.get('document_type', 'HTML'),
            })

            for substance in substances:
                if substance:
                    session.run("""
                        MERGE (s:Substance {name: $substance})
                        WITH s
                        MATCH (m:Medicine {url: $url})
                        MERGE (m)-[:CONTAINS_SUBSTANCE]->(s)
                    """, {'substance': substance, 'url': medicine_url})

            if laboratory:
                session.run("""
                    MERGE (l:Laboratory {name: $laboratory})
                    WITH l
                    MATCH (m:Medicine {url: $url})
                    MERGE (m)-[:MANUFACTURED_BY]->(l)
                """, {'laboratory': laboratory, 'url': medicine_url})

            if dosages:
                session.run("""
                    MATCH (m:Medicine {url: $url})
                    SET m.dosages = $dosages
                """, {'url': medicine_url, 'dosages': dosages})

            # ── Principes actifs, rattachés au nœud Medicine ──
            #
            # Cette section créait auparavant un second nœud `Drug` par
            # médicament, doublon de `Medicine` sous une autre étiquette. Il
            # n'a jamais porté d'interaction, et depuis P9-4 plus aucune
            # requête d'affichage ne le lit — les onze sites concernés ont été
            # basculés sur `Medicine`, qui porte désormais laboratoire,
            # substances, principes actifs et interactions.
            #
            # La création est retirée : elle repeuplait l'étiquette à chaque
            # consultation de fiche, ce qui rendait impossible de la retirer
            # de la base.
            for substance in substances:
                if substance:
                    session.run("""
                        MATCH (m:Medicine {url: $url})
                        MERGE (i:ActiveIngredient {name: $substance})
                        MERGE (m)-[:CONTAINS {dosage: '', is_active: true}]->(i)
                    """, {'url': medicine_url, 'substance': substance})

    def create_interaction_relationship(self, medicine_url1, medicine_url2, interaction_data):
        """Crée une relation d'interaction entre deux médicaments (ancien + nouveau)"""
        with self.driver.session(database=self.database) as session:
            # Ancien schéma
            session.run("""
                MATCH (m1:Medicine {url: $url1})
                MATCH (m2:Medicine {url: $url2})
                MERGE (m1)-[r:INTERACTS_WITH]-(m2)
                SET r.severity = $severity,
                    r.description = $description,
                    r.recommendation = $recommendation
            """, {
                'url1': medicine_url1,
                'url2': medicine_url2,
                'severity': interaction_data.get('severity', ''),
                'description': interaction_data.get('description', ''),
                'recommendation': interaction_data.get('recommendation', ''),
            })

    def sync_all_medicines(self, mongo_db):
        """Synchronise tous les médicaments de MongoDB vers Neo4j"""
        medicines_collection = mongo_db['medicines']
        total = medicines_collection.count_documents({})
        logger.info(f"Synchronisation de {total} médicaments vers Neo4j...")

        count = 0
        for medicine in medicines_collection.find():
            try:
                self.sync_medicine_from_mongo(medicine)
                count += 1
                if count % 100 == 0:
                    logger.info(f"Progression: {count}/{total} médicaments")
            except Exception as e:
                logger.error(f"Erreur pour {medicine.get('url')}: {e}")

        logger.info(f"Synchronisation terminée: {count}/{total} médicaments")
        return count

    def sync_interactions(self, mongo_db):
        """Synchronise les interactions médicamenteuses de MongoDB vers Neo4j.

        Lit les interactions depuis `medicine_enrichment.enriched.interactions`
        puis `DRUGBANKS.interactions` (fallback), et crée les relations
        INTERACTS_WITH entre nœuds Medicine puis Drug (par lots).
        """
        medicines_coll = mongo_db['medicines']

        # 1. Build medicine_id → url + name → url lookup
        all_meds = list(medicines_coll.find({}, {'_id': 1, 'url': 1, 'title': 1}))
        id_to_url = {}
        name_to_url = {}
        for m in all_meds:
            mid = m.get('_id')
            url = m.get('url', '')
            t = (m.get('title') or '').strip().lower()
            if mid and url:
                id_to_url[mid] = url
            if t and url:
                name_to_url[t] = url

        # 2. Collecter toutes les paires uniques
        pairs = {}  # (url1, url2) → {severity, description, recommendation}
        dbid_to_urls = {}

        # 2a. Depuis medicine_enrichment
        try:
            enrich_coll = mongo_db['medicine_enrichment']
            enrich_docs = list(enrich_coll.find(
                {'enriched.interactions': {'$exists': True, '$ne': []}},
                {'medicine_id': 1, 'drugbank_ids': 1, 'enriched.interactions': 1}
            ))
            logger.info(f"Sync interactions: {len(enrich_docs)} enriched drugs")
            for ed in enrich_docs:
                mid = ed.get('medicine_id')
                url = id_to_url.get(mid)
                if not url:
                    continue
                for dbid in (ed.get('drugbank_ids') or []):
                    dbid_to_urls.setdefault(dbid, set()).add(url)
            for ed in enrich_docs:
                mid = ed.get('medicine_id')
                url1 = id_to_url.get(mid)
                if not url1:
                    continue
                for inter in (ed.get('enriched', {}) or {}).get('interactions', []) or []:
                    for url2 in dbid_to_urls.get(inter.get('drugbank_id', ''), set()):
                        if url2 == url1:
                            continue
                        key = tuple(sorted([url1, url2]))
                        if key not in pairs:
                            pairs[key] = {
                                'severity': inter.get('severity', 'moderate'),
                                'description': inter.get('description', '') or '',
                                'recommendation': inter.get('recommendation', '') or ''
                            }
        except Exception as e:
            logger.warning(f"medicine_enrichment indisponible: {e}")

        # 2b. Fallback DRUGBANKS
        try:
            drugbanks_coll = mongo_db['DRUGBANKS']
            db_docs = list(drugbanks_coll.find(
                {'interactions': {'$exists': True, '$ne': []}},
                {'name': 1, 'interactions': 1}
            ))
            logger.info(f"Sync interactions DRUGBANKS fallback: {len(db_docs)} drugs")
            seen_pairs = set(pairs.keys())
            for dd in db_docs:
                src = (dd.get('name') or '').strip().lower()
                url1 = name_to_url.get(src)
                if not url1:
                    for t, u in name_to_url.items():
                        if src in t or t in src:
                            url1 = u
                            break
                if not url1:
                    continue
                for inter in (dd.get('interactions') or []):
                    tgt = (inter.get('name') or '').strip().lower()
                    if not tgt:
                        continue
                    url2 = name_to_url.get(tgt)
                    if not url2:
                        for t, u in name_to_url.items():
                            if tgt in t or t in tgt:
                                url2 = u
                                break
                    if not url2 or url2 == url1:
                        continue
                    key = tuple(sorted([url1, url2]))
                    if key in seen_pairs:
                        continue
                    seen_pairs.add(key)
                    pairs[key] = {
                        'severity': 'moderate',
                        'description': inter.get('description', '') or '',
                        'recommendation': ''
                    }
        except Exception as e:
            logger.warning(f"DRUGBANKS indisponible: {e}")

        total = len(pairs)
        logger.info(f"Total paires uniques à créer: {total}")

        # 3. Insertion par lots dans Neo4j
        with self.driver.session(database=self.database) as session:
            # 3a. Créer les relations Medicine→Medicine par lots de 5000
            batch_size = 5000
            items = list(pairs.items())
            created = 0
            for i in range(0, len(items), batch_size):
                batch = items[i:i+batch_size]
                rows = [{
                    'url1': k[0], 'url2': k[1],
                    'severity': v['severity'],
                    'description': v['description'],
                    'recommendation': v['recommendation']
                } for k, v in batch]
                session.run("""
                    UNWIND $rows AS row
                    MATCH (m1:Medicine {url: row.url1})
                    MATCH (m2:Medicine {url: row.url2})
                    MERGE (m1)-[r:INTERACTS_WITH]-(m2)
                    SET r.severity = row.severity,
                        r.description = row.description,
                        r.recommendation = row.recommendation
                """, rows=rows)
                created += len(batch)
                logger.info(f"Progression: {created}/{total} relations Medicine->Medicine")

            # L'étape 3b recopiait ces relations vers des nœuds `Drug`. Elle est
            # retirée avec l'étiquette : plus rien ne la lit, et la remettre
            # repeuplerait une duplication que P9-4 a supprimée.

        logger.info(f"Sync interactions terminée: {created} relations INTERACTS_WITH")
        return created

    # `create_interaction_relationships_drug_nodes()` recopiait les relations
    # vers des nœuds `Drug`. Retirée avec l'étiquette : aucun appelant, et son
    # seul effet serait de recréer la duplication supprimée en P9-4.

    def get_medicine_by_substance(self, substance_name):
        """Récupère les médicaments par substance active"""
        with self.driver.session(database=self.database) as session:
            result = session.run("""
                MATCH (s:Substance {name: $substance})<-[:CONTAINS_SUBSTANCE]-(m:Medicine)
                RETURN m.title as title, m.url as url, m.forme as forme
            """, {'substance': substance_name})
            return [dict(record) for record in result]

    def get_medicine_interactions(self, medicine_url):
        """Récupère les interactions d'un médicament"""
        with self.driver.session(database=self.database) as session:
            result = session.run("""
                MATCH (m1:Medicine {url: $url})-[r:INTERACTS_WITH]-(m2:Medicine)
                RETURN m2.title as medicine,
                       r.severity as severity,
                       r.description as description,
                       r.recommendation as recommendation
            """, {'url': medicine_url})
            return [dict(record) for record in result]

    def get_statistics(self):
        """Récupère les statistiques du graphe"""
        with self.driver.session(database=self.database) as session:
            # Comptages indépendants plutôt qu'une chaîne de MATCH.
            #
            # L'ancienne forme enchaînait les motifs : une étiquette vide
            # suffisait à ne rendre aucune ligne, et `result.single()` levait.
            # C'est ce qui serait arrivé au retrait des nœuds `Drug`, qu'elle
            # comptait. Chaque valeur est désormais calculée séparément.
            result = session.run("""
                RETURN COUNT { MATCH (m:Medicine) RETURN m } AS medicines,
                       COUNT { MATCH (s:Substance) RETURN s } AS substances,
                       COUNT { MATCH (l:Laboratory) RETURN l } AS laboratories,
                       COUNT { MATCH (:DrugbankSubstance)-[r:INTERACTS_WITH]-(:DrugbankSubstance)
                               RETURN r } / 2 AS interactions,
                       COUNT { MATCH (x:DrugbankSubstance) RETURN x } AS new_drugs,
                       COUNT { MATCH (i:ActiveIngredient) RETURN i } AS new_ingredients,
                       COUNT { MATCH ()-[rel]->() RETURN rel } AS total_relations
            """)
            return dict(result.single())

    # ── Nouvelles méthodes (délégation au Knowledge Graph) ─────────────────

    def search_drugs(self, query_text, limit=20):
        """Recherche fulltext de médicaments (nouveau schéma)"""
        if self.kg:
            return self.kg.search_drugs(query_text, limit)
        return []

    def find_dangerous_interactions(self, drug_id):
        """Interactions dangereuses d'un médicament"""
        if self.kg:
            return self.kg.find_dangerous_interactions(drug_id)
        return []

    def analyze_prescription(self, drug_ids):
        """Analyse les interactions dans une prescription"""
        if self.kg:
            return self.kg.analyze_prescription(drug_ids)
        return []

    def recommend_for_patient(self, pathologies):
        """Recommande des médicaments selon un profil patient"""
        if self.kg:
            return self.kg.recommend_for_patient(pathologies)
        return []

    def get_drug_detail(self, drug_id):
        """Fiche complète d'un médicament (nouveau schéma)"""
        if self.kg:
            return self.kg.get_drug(drug_id)
        return None


def init_neo4j(app):
    """
    Initialise la connexion Neo4j avec l'application Flask.
    Compatible avec le nouveau Knowledge Graph.
    """
    neo4j_connector = Neo4jConnector(
        uri=app.config.get('NEO4J_URI'),
        user=app.config.get('NEO4J_USER'),
        password=app.config.get('NEO4J_PASSWORD'),
        database=app.config.get('NEO4J_DATABASE', 'neo4j'),
    )

    if neo4j_connector.connect():
        neo4j_connector.create_constraints()
        app.neo4j = neo4j_connector
        return neo4j_connector
    else:
        logger.warning("Neo4j non disponible — fonctionnalités de graphe désactivées")
        return None
