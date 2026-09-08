from neo4j import GraphDatabase
from typing import Optional, List, Dict, Any
import logging
from datetime import datetime, timezone

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)


class MedicalKnowledgeGraph:
    """
    Knowledge Graph médicaments — version professionnelle.
    Zéro duplication, index optimisés, prêt pour millions de nœuds.
    """

    NODE_LABELS = frozenset({
        'Drug', 'ActiveIngredient', 'Disease',
        'Effect', 'Contraindication', 'DrugClass',
    })

    REL_TYPES = frozenset({
        'CONTAINS', 'TREATS', 'CAUSES',
        'HAS_CONTRAINDICATION', 'BELONGS_TO',
        'INTERACTS_WITH', 'HAS_SUBCLASS', 'HAS_MECHANISM',
    })

    def __init__(
        self,
        uri: str = "neo4j://127.0.0.1:7687",
        user: str = "neo4j",
        password: str = "12345678",
        database: str = "medicament",
    ):
        self.uri = uri
        self.user = user
        self.password = password
        self.database = database
        self.driver: Optional[GraphDatabase.driver] = None

    # ── Connexion ──────────────────────────────────────────────────────────

    def connect(self) -> bool:
        try:
            self.driver = GraphDatabase.driver(
                self.uri,
                auth=(self.user, self.password),
                connection_timeout=10.0,
                max_connection_lifetime=3600,
                max_connection_pool_size=50,
                connection_acquisition_timeout=30.0,
            )
            self.driver.verify_connectivity()
            logger.info(f"Connecté à {self.uri} (db: {self.database})")
            return True
        except Exception as e:
            logger.error(f"Échec connexion Neo4j : {e}")
            self.driver = None
            return False

    def close(self):
        if self.driver:
            self.driver.close()
            self.driver = None

    def session(self):
        return self.driver.session(database=self.database)

    # ── Schéma ─────────────────────────────────────────────────────────────

    def create_schema(self):
        with self.session() as tx:
            constraints = [
                "CREATE CONSTRAINT drug_id IF NOT EXISTS FOR (d:Drug) REQUIRE d.id IS UNIQUE",
                "CREATE CONSTRAINT ingredient_name IF NOT EXISTS FOR (i:ActiveIngredient) REQUIRE i.name IS UNIQUE",
                "CREATE CONSTRAINT disease_name IF NOT EXISTS FOR (d:Disease) REQUIRE d.name IS UNIQUE",
                "CREATE CONSTRAINT effect_id IF NOT EXISTS FOR (e:Effect) REQUIRE e.id IS UNIQUE",
                "CREATE CONSTRAINT contra_id IF NOT EXISTS FOR (c:Contraindication) REQUIRE c.id IS UNIQUE",
                "CREATE CONSTRAINT class_name IF NOT EXISTS FOR (c:DrugClass) REQUIRE c.name IS UNIQUE",
            ]
            indexes = [
                "CREATE INDEX drug_title IF NOT EXISTS FOR (d:Drug) ON (d.title)",
                "CREATE INDEX drug_generic_name IF NOT EXISTS FOR (d:Drug) ON (d.generic_name)",
                "CREATE INDEX drug_atc IF NOT EXISTS FOR (d:Drug) ON (d.atc_code)",
                "CREATE INDEX effect_gravity IF NOT EXISTS FOR (e:Effect) ON (e.severity)",
                "CREATE INDEX interaction_severity IF NOT EXISTS FOR ()-[r:INTERACTS_WITH]-() ON (r.severity)",
            ]
            for c in constraints:
                tx.run(c)
            for idx in indexes:
                tx.run(idx)
            try:
                tx.run("CREATE FULLTEXT INDEX drug_text IF NOT EXISTS FOR (d:Drug) ON EACH [d.title, d.generic_name, d.brand_name]")
            except Exception:
                pass
            logger.info("Schéma créé : 6 contraintes, 5 index, 1 fulltext")

    # ── CRUD Drug ──────────────────────────────────────────────────────────

    def upsert_drug(self, data: Dict[str, Any]) -> Dict[str, Any]:
        query = """
        MERGE (d:Drug {id: $id})
        SET d.title = $title,
            d.generic_name = $generic_name,
            d.brand_name = $brand_name,
            d.atc_code = $atc_code,
            d.therapeutic_class = $therapeutic_class,
            d.laboratory = $laboratory,
            d.form = $form,
            d.dosage = $dosage,
            d.route = $route,
            d.marketing_status = $marketing_status,
            d.source = $source,
            d.confidence_score = $confidence_score,
            d.updated_at = datetime()
        RETURN d.id AS id, d.title AS title, d.updated_at AS updated_at
        """
        params = {
            'id': data['id'],
            'title': data.get('title', ''),
            'generic_name': data.get('generic_name', ''),
            'brand_name': data.get('brand_name', ''),
            'atc_code': data.get('atc_code', ''),
            'therapeutic_class': data.get('therapeutic_class', ''),
            'laboratory': data.get('laboratory', ''),
            'form': data.get('form', ''),
            'dosage': data.get('dosage', ''),
            'route': data.get('route', ''),
            'marketing_status': data.get('marketing_status', 'Autorisé'),
            'source': data.get('source', 'import'),
            'confidence_score': data.get('confidence_score', 80),
        }
        with self.session() as tx:
            result = tx.run(query, params)
            return dict(result.single())

    def get_drug(self, identifier: str) -> Optional[Dict[str, Any]]:
        query = """
        MATCH (d:Drug {id: $id})
        OPTIONAL MATCH (d)-[:CONTAINS]->(i:ActiveIngredient)
        OPTIONAL MATCH (d)-[:BELONGS_TO]->(c:DrugClass)
        OPTIONAL MATCH (d)-[:TREATS]->(di:Disease)
        OPTIONAL MATCH (d)-[:CAUSES]->(e:Effect)
        OPTIONAL MATCH (d)-[:HAS_CONTRAINDICATION]->(ci:Contraindication)
        OPTIONAL MATCH (d)-[r:INTERACTS_WITH]-(other:Drug)
        RETURN d{.*,
          ingredients: collect(DISTINCT i{.*}),
          classes: collect(DISTINCT c{.*}),
          treats: collect(DISTINCT di{.*}),
          effects: collect(DISTINCT e{.*}),
          contraindications: collect(DISTINCT ci{.*}),
          interactions: collect(DISTINCT {
            drug: other.title,
            severity: r.severity,
            risk_score: r.risk_score,
            recommendation: r.recommendation
          })
        }
        """
        with self.session() as tx:
            result = tx.run(query, {'id': identifier})
            record = result.single()
            return dict(record) if record else None

    def search_drugs(self, query_text: str, limit: int = 20) -> List[Dict[str, Any]]:
        try:
            query = """
            CALL db.index.fulltext.queryNodes('drug_text', $query) 
            YIELD node, score
            RETURN node.id AS id, node.title AS title,
                   node.generic_name AS generic_name,
                   node.dosage AS dosage,
                   node.form AS form,
                   node.laboratory AS laboratory,
                   score
            ORDER BY score DESC
            LIMIT $limit
            """
            with self.session() as tx:
                result = tx.run(query, {'query': query_text, 'limit': limit})
                return [dict(r) for r in result]
        except Exception:
            # Fallback: fulltext index manquant → CONTAINS
            try:
                with self.session() as tx:
                    result = tx.run("""
                        MATCH (d:Drug)
                        WHERE toLower(coalesce(d.title, d.name, '')) CONTAINS toLower($query)
                        RETURN d.id AS id, d.title AS title,
                               d.generic_name AS generic_name,
                               d.dosage AS dosage,
                               d.form AS form,
                               d.laboratory AS laboratory
                        ORDER BY d.title
                        LIMIT $limit
                    """, {'query': query_text, 'limit': limit})
                    return [dict(r) for r in result]
            except Exception:
                return []

    # ── Relations ──────────────────────────────────────────────────────────

    def link_drug_to_ingredient(self, drug_id: str, ingredient_name: str,
                                 dosage: str = '', is_active: bool = True):
        query = """
        MATCH (d:Drug {id: $drug_id})
        MERGE (i:ActiveIngredient {name: $name})
        MERGE (d)-[:CONTAINS {dosage: $dosage, is_active: $is_active}]->(i)
        """
        with self.session() as tx:
            tx.run(query, {
                'drug_id': drug_id,
                'name': ingredient_name,
                'dosage': dosage,
                'is_active': is_active,
            })

    def link_drug_to_disease(self, drug_id: str, disease_name: str,
                              rank: int = 1, evidence: str = 'Modéré'):
        query = """
        MATCH (d:Drug {id: $drug_id})
        MERGE (di:Disease {name: $name})
        MERGE (d)-[:TREATS {rank: $rank, evidence_level: $evidence}]->(di)
        """
        with self.session() as tx:
            tx.run(query, {
                'drug_id': drug_id,
                'name': disease_name,
                'rank': rank,
                'evidence': evidence,
            })

    def create_interaction(self, drug_id_1: str, drug_id_2: str,
                            severity: str = 'Modérée',
                            mechanism: str = '',
                            recommendation: str = '',
                            description: str = '',
                            risk_score: int = 50):
        query = """
        MATCH (d1:Drug {id: $id1})
        MATCH (d2:Drug {id: $id2})
        MERGE (d1)-[r:INTERACTS_WITH]-(d2)
        SET r.severity = $severity,
            r.mechanism = $mechanism,
            r.recommendation = $recommendation,
            r.description = $description,
            r.risk_score = $risk_score
        """
        with self.session() as tx:
            tx.run(query, {
                'id1': drug_id_1,
                'id2': drug_id_2,
                'severity': severity,
                'mechanism': mechanism,
                'recommendation': recommendation,
                'description': description,
                'risk_score': risk_score,
            })

    # ── Requêtes avancées ──────────────────────────────────────────────────

    def find_dangerous_interactions(self, drug_id: str) -> List[Dict[str, Any]]:
        query = """
        MATCH (d:Drug {id: $id})-[r:INTERACTS_WITH]-(other:Drug)
        WHERE r.severity IN ['Grave', 'Modérée']
        RETURN other.title AS medicament,
               r.severity AS gravite,
               r.description AS description,
               r.recommendation AS recommandation,
               r.risk_score AS score_risque
        ORDER BY r.risk_score DESC
        """
        with self.session() as tx:
            result = tx.run(query, {'id': drug_id})
            return [dict(r) for r in result]

    def find_alternatives_without_interaction(self, drug_id: str, target_drug_id: str) -> List[Dict[str, Any]]:
        query = """
        MATCH (target:Drug {id: $target_id})-[:TREATS]->(d:Disease)<-[:TREATS]-(alternative:Drug)
        WHERE alternative.id <> $target_id
          AND NOT EXISTS {
            MATCH (alternative)-[:INTERACTS_WITH]-(:Drug {id: $drug_id})
          }
        RETURN alternative.title AS medicament_alternatif,
               alternative.dosage AS dosage,
               alternative.laboratory AS laboratoire,
               d.name AS maladie
        ORDER BY alternative.title
        """
        with self.session() as tx:
            result = tx.run(query, {
                'target_id': drug_id,
                'drug_id': target_drug_id,
            })
            return [dict(r) for r in result]

    def find_drugs_by_ingredient(self, ingredient_name: str) -> List[Dict[str, Any]]:
        query = """
        MATCH (i:ActiveIngredient {name: $name})<-[:CONTAINS]-(d:Drug)
        RETURN i.name AS principe_actif,
               d.title AS medicament,
               d.dosage AS dosage,
               d.form AS forme,
               d.laboratory AS laboratoire
        ORDER BY d.title
        """
        with self.session() as tx:
            result = tx.run(query, {'name': ingredient_name})
            return [dict(r) for r in result]

    def find_drugs_by_disease(self, disease_name: str) -> List[Dict[str, Any]]:
        query = """
        MATCH (d:Drug)-[:TREATS]->(di:Disease {name: $name})
        RETURN d.id AS id, d.title AS medicament,
               d.dosage AS dosage, d.form AS forme,
               d.laboratory AS laboratoire,
               di.name AS maladie
        ORDER BY d.title
        """
        with self.session() as tx:
            result = tx.run(query, {'name': disease_name})
            return [dict(r) for r in result]

    def analyze_prescription(self, drug_ids: List[str]) -> List[Dict[str, Any]]:
        query = """
        UNWIND $ids AS id1
        UNWIND $ids AS id2
        WITH id1, id2 WHERE id1 < id2
        MATCH (d1:Drug {id: id1})
        MATCH (d2:Drug {id: id2})
        OPTIONAL MATCH (d1)-[r:INTERACTS_WITH]-(d2)
        RETURN d1.title AS medicament_1,
               d2.title AS medicament_2,
               CASE
                 WHEN r IS NULL THEN 'Aucune interaction connue'
                 ELSE r.severity + ' — ' + coalesce(r.description, '')
               END AS analyse,
               r.recommendation AS recommandation,
               r.risk_score AS score_risque
        ORDER BY r.risk_score DESC NULLS LAST
        """
        with self.session() as tx:
            result = tx.run(query, {'ids': drug_ids})
            return [dict(r) for r in result]

    def find_risk_path(self, drug_id_1: str, drug_id_2: str, max_depth: int = 3) -> List[Dict[str, Any]]:
        query = """
        MATCH path = (d1:Drug {id: $id1})-[r:INTERACTS_WITH*..$depth]-(d2:Drug {id: $id2})
        WHERE ALL(rel IN r WHERE rel.risk_score IS NOT NULL)
        RETURN [n IN nodes(path) | n.title] AS chemin,
               [r IN relationships(path) | r.severity] AS gravites,
               reduce(total = 0, rel IN r | total + coalesce(rel.risk_score, 0)) AS score_risque_cumule,
               length(path) AS profondeur
        ORDER BY score_risque_cumule DESC
        LIMIT 5
        """
        with self.session() as tx:
            result = tx.run(query, {
                'id1': drug_id_1,
                'id2': drug_id_2,
                'depth': max_depth,
            })
            return [dict(r) for r in result]

    def recommend_for_patient(self, pathologies: List[str]) -> List[Dict[str, Any]]:
        query = """
        MATCH (d:Drug)-[:TREATS]->(di:Disease)
        WHERE di.name IN $pathologies

        OPTIONAL MATCH (d)-[ci_rel:HAS_CONTRAINDICATION]->(ci:Contraindication)
        WHERE ci_rel.severity = 'Absolue'

        WITH d, di, collect(DISTINCT ci.name) AS contraindications_absolues
        WHERE size(contraindications_absolues) = 0

        OPTIONAL MATCH (d)-[r:INTERACTS_WITH]-(other:Drug)-[:TREATS]->(other_di:Disease)
        WHERE other_di.name IN $pathologies AND r.severity = 'Grave'

        WITH d, di, collect(DISTINCT other.title) AS interactions_graves
        WHERE size(interactions_graves) = 0

        RETURN d.id AS id, d.title AS medicament,
               d.form AS forme, d.dosage AS dosage,
               d.laboratory AS laboratoire,
               collect(DISTINCT di.name) AS pathologies_ciblees
        ORDER BY d.title
        """
        with self.session() as tx:
            result = tx.run(query, {'pathologies': pathologies})
            return [dict(r) for r in result]

    # ── Statistiques ───────────────────────────────────────────────────────

    def get_statistics(self) -> Dict[str, int]:
        query = """
        MATCH (d:Drug) WITH count(d) AS drugs
        MATCH (i:ActiveIngredient) WITH drugs, count(i) AS ingredients
        MATCH (di:Disease) WITH drugs, ingredients, count(di) AS diseases
        MATCH (e:Effect) WITH drugs, ingredients, diseases, count(e) AS effects
        MATCH (c:Contraindication) WITH drugs, ingredients, diseases, effects, count(c) AS contraindications
        MATCH (dc:DrugClass) WITH drugs, ingredients, diseases, effects, contraindications, count(dc) AS classes
        MATCH ()-[r:INTERACTS_WITH]-() WITH drugs, ingredients, diseases, effects, contraindications, classes, count(r) AS interactions
        MATCH ()-[rel]->() RETURN drugs, ingredients, diseases, effects, contraindications, classes, interactions, count(rel) AS total_relations
        """
        with self.session() as tx:
            result = tx.run(query)
            return dict(result.single())

    # ── Batch ──────────────────────────────────────────────────────────────

    def batch_import_drugs(self, drugs: List[Dict[str, Any]], batch_size: int = 100):
        for i in range(0, len(drugs), batch_size):
            batch = drugs[i:i + batch_size]
            with self.session() as tx:
                for drug in batch:
                    self._upsert_drug_in_tx(tx, drug)
            logger.info(f"Batch drugs {i}/{len(drugs)}")

    def _upsert_drug_in_tx(self, tx, data: Dict[str, Any]):
        query = """
        MERGE (d:Drug {id: $id})
        SET d.title = $title, d.generic_name = $generic_name,
            d.brand_name = $brand_name, d.atc_code = $atc_code,
            d.therapeutic_class = $therapeutic_class,
            d.laboratory = $laboratory, d.form = $form,
            d.dosage = $dosage, d.route = $route,
            d.marketing_status = $marketing_status,
            d.source = $source,
            d.confidence_score = $confidence_score,
            d.updated_at = datetime()
        """
        tx.run(query, {
            'id': data['id'],
            'title': data.get('title', ''),
            'generic_name': data.get('generic_name', ''),
            'brand_name': data.get('brand_name', ''),
            'atc_code': data.get('atc_code', ''),
            'therapeutic_class': data.get('therapeutic_class', ''),
            'laboratory': data.get('laboratory', ''),
            'form': data.get('form', ''),
            'dosage': data.get('dosage', ''),
            'route': data.get('route', ''),
            'marketing_status': data.get('marketing_status', 'Autorisé'),
            'source': data.get('source', 'import'),
            'confidence_score': data.get('confidence_score', 80),
        })

    # ── Nettoyage ──────────────────────────────────────────────────────────

    def get_orphan_nodes(self):
        with self.session() as tx:
            result = tx.run("""
                MATCH (n)
                WHERE NOT EXISTS { MATCH (n)--() }
                RETURN labels(n) AS type, coalesce(n.name, n.title, n.id) AS nom
            """)
            return [dict(r) for r in result]

    def clean_orphan_nodes(self):
        with self.session() as tx:
            result = tx.run("""
                MATCH (n)
                WHERE NOT EXISTS { MATCH (n)--() }
                DETACH DELETE n
                RETURN count(n) AS deleted
            """)
            return result.single()['deleted']
