// =============================================================================
// IMPORT CSV — Knowledge Graph Médicaments
// Usage (déposer les CSV dans /var/lib/neo4j/import/) :
//   docker cp csv/*.csv medicsearch-neo4j:/imports/
//   cat import_csv.cypher | cypher-shell
// =============================================================================

// ─── 1. DRUGS ────────────────────────────────────────────────────────────────
// Format attendu : drugs.csv
// id,title,generic_name,brand_name,atc_code,therapeutic_class,
// laboratory,form,dosage,route,marketing_status,source

LOAD CSV WITH HEADERS FROM 'file:///imports/drugs.csv' AS row
MERGE (d:Drug {id: row.id})
SET d.title = row.title,
    d.generic_name = row.generic_name,
    d.brand_name = row.brand_name,
    d.atc_code = row.atc_code,
    d.therapeutic_class = row.therapeutic_class,
    d.laboratory = row.laboratory,
    d.form = row.form,
    d.dosage = row.dosage,
    d.route = row.route,
    d.marketing_status = row.marketing_status,
    d.source = coalesce(row.source, 'import'),
    d.confidence_score = toInteger(coalesce(row.confidence_score, '80')),
    d.updated_at = datetime();

// ─── 2. ACTIVE INGREDIENTS ───────────────────────────────────────────────────
// Format attendu : ingredients.csv
// name,chemical_formula,molecular_weight,pharmacological_class,
// mechanism_summary,source,confidence_score

LOAD CSV WITH HEADERS FROM 'file:///imports/ingredients.csv' AS row
MERGE (i:ActiveIngredient {name: row.name})
SET i.chemical_formula = row.chemical_formula,
    i.molecular_weight = toFloat(coalesce(row.molecular_weight, '0')),
    i.pharmacological_class = row.pharmacological_class,
    i.mechanism_summary = row.mechanism_summary,
    i.source = coalesce(row.source, 'import'),
    i.confidence_score = toInteger(coalesce(row.confidence_score, '80')),
    i.updated_at = datetime();

// ─── 3. DISEASES ─────────────────────────────────────────────────────────────
// Format attendu : diseases.csv
// name,symptoms,category,icd10_code,description,source,confidence_score

LOAD CSV WITH HEADERS FROM 'file:///imports/diseases.csv' AS row
MERGE (d:Disease {name: row.name})
SET d.symptoms = row.symptoms,
    d.category = row.category,
    d.icd10_code = row.icd10_code,
    d.description = row.description,
    d.source = coalesce(row.source, 'import'),
    d.confidence_score = toInteger(coalesce(row.confidence_score, '80'));

// ─── 4. EFFECTS ──────────────────────────────────────────────────────────────
// Format attendu : effects.csv
// id,name,severity,frequency,description,source,confidence_score

LOAD CSV WITH HEADERS FROM 'file:///imports/effects.csv' AS row
MERGE (e:Effect {id: row.id})
SET e.name = row.name,
    e.severity = row.severity,
    e.frequency = row.frequency,
    e.description = row.description,
    e.source = coalesce(row.source, 'import'),
    e.confidence_score = toInteger(coalesce(row.confidence_score, '80'));

// ─── 5. CONTRAINDICATIONS ────────────────────────────────────────────────────
// Format attendu : contraindications.csv
// id,name,reason,severity,category,source,confidence_score

LOAD CSV WITH HEADERS FROM 'file:///imports/contraindications.csv' AS row
MERGE (c:Contraindication {id: row.id})
SET c.name = row.name,
    c.reason = row.reason,
    c.severity = row.severity,
    c.category = row.category,
    c.source = coalesce(row.source, 'import'),
    c.confidence_score = toInteger(coalesce(row.confidence_score, '80'));

// ─── 6. DRUG CLASSES ─────────────────────────────────────────────────────────
// Format attendu : drug_classes.csv
// name,mechanism_of_action,parent_class,description

LOAD CSV WITH HEADERS FROM 'file:///imports/drug_classes.csv' AS row
MERGE (c:DrugClass {name: row.name})
SET c.mechanism_of_action = row.mechanism_of_action,
    c.parent_class = row.parent_class,
    c.description = row.description;

// ─── 7. RELATION DRUG → ACTIVE_INGREDIENT ────────────────────────────────────
// Format attendu : drug_ingredient.csv
// drug_id,ingredient_name,dosage,is_active

LOAD CSV WITH HEADERS FROM 'file:///imports/drug_ingredient.csv' AS row
MATCH (d:Drug {id: row.drug_id})
MATCH (i:ActiveIngredient {name: row.ingredient_name})
MERGE (d)-[:CONTAINS {dosage: row.dosage, is_active: toBoolean(coalesce(row.is_active, 'true'))}]->(i);

// ─── 8. RELATION DRUG → DISEASE ──────────────────────────────────────────────
// Format attendu : drug_disease.csv
// drug_id,disease_name,rank,evidence_level

LOAD CSV WITH HEADERS FROM 'file:///imports/drug_disease.csv' AS row
MATCH (d:Drug {id: row.drug_id})
MATCH (di:Disease {name: row.disease_name})
MERGE (d)-[:TREATS {rank: toInteger(coalesce(row.rank, '1')), evidence_level: coalesce(row.evidence_level, 'Modéré')}]->(di);

// ─── 9. RELATION DRUG → EFFECT ───────────────────────────────────────────────
// Format attendu : drug_effect.csv
// drug_id,effect_id,severity,frequency

LOAD CSV WITH HEADERS FROM 'file:///imports/drug_effect.csv' AS row
MATCH (d:Drug {id: row.drug_id})
MATCH (e:Effect {id: row.effect_id})
MERGE (d)-[:CAUSES {severity: coalesce(row.severity, 'Modéré'), frequency: coalesce(row.frequency, 'Non connu')}]->(e);

// ─── 10. RELATION DRUG → CONTRAINDICATION ────────────────────────────────────
// Format attendu : drug_contraindication.csv
// drug_id,contraindication_id,reason,severity

LOAD CSV WITH HEADERS FROM 'file:///imports/drug_contraindication.csv' AS row
MATCH (d:Drug {id: row.drug_id})
MATCH (c:Contraindication {id: row.contraindication_id})
MERGE (d)-[:HAS_CONTRAINDICATION {reason: row.reason, severity: coalesce(row.severity, 'Absolue')}]->(c);

// ─── 11. RELATION DRUG → DRUG (INTERACTIONS) ─────────────────────────────────
// Format attendu : drug_interactions.csv
// drug_id_1,drug_id_2,severity,mechanism,recommendation,description,risk_score

LOAD CSV WITH HEADERS FROM 'file:///imports/drug_interactions.csv' AS row
MATCH (d1:Drug {id: row.drug_id_1})
MATCH (d2:Drug {id: row.drug_id_2})
MERGE (d1)-[r:INTERACTS_WITH {severity: row.severity, mechanism: row.mechanism, recommendation: row.recommendation, description: row.description, risk_score: toInteger(coalesce(row.risk_score, '0'))}]-(d2);

// ─── 12. MAPPING OPENFDA → DRUG ──────────────────────────────────────────────
// Format attendu : openfda_mapping.csv
// spl_id,product_ndc,brand_name,generic_name,active_ingredient,drug_id
//
// Usage : associer un identifiant OpenFDA au Drug.id correspondant
// Permet ensuite les requêtes : MATCH (d)-[:HAS_FDA_LABEL]->(fda)

// Supprimer les relations existantes (pour réimport)
// MATCH ()-[r:HAS_FDA_LABEL]->() DELETE r;

CREATE INDEX fda_spl_id IF NOT EXISTS FOR (f:FdaLabel) ON (f.spl_id);

LOAD CSV WITH HEADERS FROM 'file:///imports/fda_labels.csv' AS row
MERGE (f:FdaLabel {
  spl_id: row.spl_id,
  set_id: row.set_id,
  product_ndc: row.product_ndc
})
SET f.brand_name = row.brand_name,
    f.generic_name = row.generic_name,
    f.active_ingredient = row.active_ingredient,
    f.indications_and_usage = row.indications_and_usage,
    f.dosage_and_administration = row.dosage_and_administration,
    f.contraindications = row.contraindications,
    f.warnings = row.warnings,
    f.adverse_reactions = row.adverse_reactions,
    f.drug_interactions = row.drug_interactions,
    f.updated_at = datetime();

// ─── VÉRIFICATION FINALE ─────────────────────────────────────────────────────

RETURN '✅ Import CSV terminé' AS status;

// Vérifications post-import :
// MATCH (d:Drug) RETURN count(d) AS drugs;
// MATCH (:Drug)-[:CONTAINS]->(:ActiveIngredient) RETURN count(*) AS relations_ingredient;
// MATCH ()-[r:INTERACTS_WITH]-() RETURN count(DISTINCT r) AS interactions;
