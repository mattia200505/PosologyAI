"""
Import CSV et batch pour le Knowledge Graph Médicaments.
Supporte OpenFDA, DrugBank, PubChem, données ANSM.
"""
import csv
import json
import logging
import os
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone

from .knowledge_graph import MedicalKnowledgeGraph

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)


class DataImporter:
    """
    Import de données médicales vers Neo4j.
    Mapping CSV → Neo4j pour chaque source.
    """

    def __init__(self, kg: MedicalKnowledgeGraph):
        self.kg = kg

    # ── CSV helpers ────────────────────────────────────────────────────────

    def _read_csv(self, filepath: str) -> List[Dict[str, str]]:
        with open(filepath, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            return [dict(row) for row in reader]

    def _safe_int(self, val: Any, default: int = 0) -> int:
        try:
            return int(val) if val else default
        except (ValueError, TypeError):
            return default

    def _safe_float(self, val: Any, default: float = 0.0) -> float:
        try:
            return float(val) if val else default
        except (ValueError, TypeError):
            return default

    # ── Import DrugBank ────────────────────────────────────────────────────

    def import_drugbank(self, csv_path: str):
        """
        Format DrugBank attendu (drugbank_drugs.csv) :
        drugbank_id,name,generic_name,cas_number,unii,
        atc_codes,description,mechanism_of_action,pharmacodynamics,
        indication,half_life,protein_binding,toxicity,
        metabolism,classification
        """
        drugs = self._read_csv(csv_path)
        logger.info(f"Import DrugBank : {len(drugs)} médicaments")

        for row in drugs:
            drug_id = row.get('drugbank_id', '').strip()
            if not drug_id:
                continue

            self.kg.upsert_drug({
                'id': drug_id,
                'title': row.get('name', ''),
                'generic_name': row.get('generic_name', ''),
                'brand_name': row.get('name', ''),
                'atc_code': row.get('atc_codes', '')[:20],
                'therapeutic_class': row.get('classification', '')[:100],
                'source': 'DrugBank',
                'confidence_score': 95,
            })

        logger.info(f"DrugBank importé : {len(drugs)} lignes")

    # ── Import OpenFDA ─────────────────────────────────────────────────────

    def import_openfda(self, csv_path: str):
        """
        Format OpenFDA attendu (openfda_labels.csv) :
        spl_id,set_id,brand_name,generic_name,active_ingredient,
        indications_and_usage,dosage_and_administration,
        contraindications,warnings,adverse_reactions,drug_interactions
        """
        labels = self._read_csv(csv_path)
        logger.info(f"Import OpenFDA : {len(labels)} labels")

        with self.kg.session() as tx:
            for row in labels:
                spl_id = row.get('spl_id', '').strip()
                if not spl_id:
                    continue

                tx.run("""
                    MERGE (f:FdaLabel {spl_id: $spl_id})
                    SET f.set_id = $set_id,
                        f.brand_name = $brand_name,
                        f.generic_name = $generic_name,
                        f.active_ingredient = $active_ingredient,
                        f.indications_and_usage = $indications,
                        f.contraindications = $contraindications,
                        f.warnings = $warnings,
                        f.adverse_reactions = $adverse_reactions,
                        f.drug_interactions = $drug_interactions,
                        f.updated_at = datetime()
                """, {
                    'spl_id': spl_id,
                    'set_id': row.get('set_id', ''),
                    'brand_name': row.get('brand_name', ''),
                    'generic_name': row.get('generic_name', ''),
                    'active_ingredient': row.get('active_ingredient', ''),
                    'indications': row.get('indications_and_usage', ''),
                    'contraindications': row.get('contraindications', ''),
                    'warnings': row.get('warnings', ''),
                    'adverse_reactions': row.get('adverse_reactions', ''),
                    'drug_interactions': row.get('drug_interactions', ''),
                })

        logger.info(f"OpenFDA importé : {len(labels)} labels")

    def map_fda_to_drugs(self, mapping_csv: str):
        """
        Mapping OpenFDA SPL → Drug Neo4j.
        Format : spl_id,drug_id
        """
        mappings = self._read_csv(mapping_csv)
        with self.kg.session() as tx:
            for row in mappings:
                tx.run("""
                    MATCH (f:FdaLabel {spl_id: $spl_id})
                    MATCH (d:Drug {id: $drug_id})
                    MERGE (d)-[:HAS_FDA_LABEL]->(f)
                """, {
                    'spl_id': row['spl_id'],
                    'drug_id': row['drug_id'],
                })
        logger.info(f"Mapping FDA → Drug : {len(mappings)} relations")

    # ── Import PubChem ────────────────────────────────────────────────────

    def import_pubchem_compounds(self, csv_path: str):
        """
        Format PubChem attendu (pubchem_compounds.csv) :
        cid,name,molecular_formula,molecular_weight,
        canonical_smiles,inchikey,pharmacological_action,
        drug_class
        """
        compounds = self._read_csv(csv_path)
        logger.info(f"Import PubChem : {len(compounds)} composés")

        with self.kg.session() as tx:
            for row in compounds:
                tx.run("""
                    MERGE (c:Compound {cid: $cid})
                    SET c.name = $name,
                        c.molecular_formula = $formula,
                        c.molecular_weight = toFloat($weight),
                        c.canonical_smiles = $smiles,
                        c.inchikey = $inchikey,
                        c.pharmacological_action = $action,
                        c.updated_at = datetime()
                """, {
                    'cid': row['cid'],
                    'name': row.get('name', ''),
                    'formula': row.get('molecular_formula', ''),
                    'weight': self._safe_float(row.get('molecular_weight')),
                    'smiles': row.get('canonical_smiles', ''),
                    'inchikey': row.get('inchikey', ''),
                    'action': row.get('pharmacological_action', ''),
                })

        logger.info(f"PubChem importé : {len(compounds)} composés")

    # ── Import ANSM (français) ─────────────────────────────────────────────

    def import_ansm_medicines(self, csv_path: str):
        """
        Format ANSM attendu (ansm_medicines.csv) :
        cis,brand_name,generic_name,form,dosage,route,
        marketing_status,active_substances,laboratory,
        atc_code,therapeutic_class
        """
        medicines = self._read_csv(csv_path)
        logger.info(f"Import ANSM : {len(medicines)} médicaments")

        for row in medicines:
            drug_id = f"ANSM-{row.get('cis', '').strip()}"
            if not row.get('cis', '').strip():
                continue

            self.kg.upsert_drug({
                'id': drug_id,
                'title': row.get('brand_name', ''),
                'generic_name': row.get('generic_name', ''),
                'brand_name': row.get('brand_name', ''),
                'atc_code': row.get('atc_code', '')[:20],
                'therapeutic_class': row.get('therapeutic_class', '')[:100],
                'laboratory': row.get('laboratory', ''),
                'form': row.get('form', ''),
                'dosage': row.get('dosage', ''),
                'route': row.get('route', ''),
                'marketing_status': row.get('marketing_status', 'Inconnu'),
                'source': 'ANSM',
                'confidence_score': 90,
            })

            # Lier les substances actives
            substances = row.get('active_substances', '')
            if substances:
                for substance in [s.strip() for s in substances.split(';') if s.strip()]:
                    self.kg.link_drug_to_ingredient(drug_id, substance)

        logger.info(f"ANSM importé : {len(medicines)} médicaments")

    # ── Import interactions ───────────────────────────────────────────────

    def import_interactions(self, csv_path: str):
        """
        Format interactions attendu (interactions.csv) :
        drug_id_1,drug_id_2,severity,mechanism,recommendation,
        description,risk_score
        """
        interactions = self._read_csv(csv_path)
        logger.info(f"Import interactions : {len(interactions)} lignes")

        for row in interactions:
            self.kg.create_interaction(
                drug_id_1=row['drug_id_1'].strip(),
                drug_id_2=row['drug_id_2'].strip(),
                severity=row.get('severity', 'Modérée'),
                mechanism=row.get('mechanism', ''),
                recommendation=row.get('recommendation', ''),
                description=row.get('description', ''),
                risk_score=self._safe_int(row.get('risk_score'), 50),
            )

        logger.info(f"Interactions importées : {len(interactions)}")

    # ── Import JSON (DrugBank complet, etc.) ───────────────────────────────

    def import_drugbank_json(self, json_path: str):
        """
        DrugBank JSON export complet.
        [
          {
            "drugbank_id": "DB00001",
            "name": "...",
            "products": [...],
            "atc_codes": [...],
            "mechanism_of_action": "...",
            "targets": [...],
            "interactions": [...],
            ...
          }
        ]
        """
        with open(json_path, 'r', encoding='utf-8') as f:
            drugs = json.load(f)

        logger.info(f"Import DrugBank JSON : {len(drugs)} médicaments")

        for drug in drugs:
            db_id = drug.get('drugbank_id', '').strip()
            if not db_id:
                continue

            self.kg.upsert_drug({
                'id': db_id,
                'title': drug.get('name', ''),
                'generic_name': drug.get('generic_name', ''),
                'brand_name': drug.get('name', ''),
                'atc_code': ';'.join(drug.get('atc_codes', []) or [])[:20],
                'source': 'DrugBank',
                'confidence_score': 98,
            })

            # Créer les interactions DrugBank
            for interaction in (drug.get('interactions') or []):
                other_id = interaction.get('drugbank_id', '').strip()
                if other_id:
                    self.kg.create_interaction(
                        drug_id_1=db_id,
                        drug_id_2=other_id,
                        severity=interaction.get('severity', 'Non spécifié'),
                        description=interaction.get('description', ''),
                    )

        logger.info(f"DrugBank JSON importé : {len(drugs)} médicaments")

    # ── Vérification post-import ───────────────────────────────────────────

    def verify_import(self) -> Dict[str, Any]:
        stats = self.kg.get_statistics()
        logger.info(f"Vérification post-import : {stats}")
        return stats
