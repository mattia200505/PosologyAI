// =============================================================================
// SCHÉMA NEO4J — Knowledge Graph Médicaments
// Usage : CAT schema.cypher | cypher-shell -u neo4j -p 12345678
// =============================================================================

// ─── 1. CONTRAINTES D'UNICITÉ ────────────────────────────────────────────────

CREATE CONSTRAINT drug_id         IF NOT EXISTS FOR (d:Drug)                REQUIRE d.id IS UNIQUE;
CREATE CONSTRAINT drug_url        IF NOT EXISTS FOR (d:Drug)                REQUIRE d.url IS UNIQUE;
CREATE CONSTRAINT ingredient_name IF NOT EXISTS FOR (i:ActiveIngredient)    REQUIRE i.name IS UNIQUE;
CREATE CONSTRAINT disease_name    IF NOT EXISTS FOR (d:Disease)             REQUIRE d.name IS UNIQUE;
CREATE CONSTRAINT effect_id       IF NOT EXISTS FOR (e:Effect)              REQUIRE e.id IS UNIQUE;
CREATE CONSTRAINT contra_id       IF NOT EXISTS FOR (c:Contraindication)    REQUIRE c.id IS UNIQUE;
CREATE CONSTRAINT class_name      IF NOT EXISTS FOR (c:DrugClass)           REQUIRE c.name IS UNIQUE;
CREATE CONSTRAINT interaction_id  IF NOT EXISTS FOR (i:Interaction)         REQUIRE i.id IS UNIQUE;

// ─── 2. INDEX (pour les recherches textuelles et fuzzy) ──────────────────────

CREATE INDEX drug_title          IF NOT EXISTS FOR (d:Drug)                ON (d.title);
CREATE INDEX drug_generic_name   IF NOT EXISTS FOR (d:Drug)                ON (d.generic_name);
CREATE INDEX drug_atc            IF NOT EXISTS FOR (d:Drug)                ON (d.atc_code);
CREATE INDEX ingredient_formula  IF NOT EXISTS FOR (i:ActiveIngredient)    ON (i.chemical_formula);
CREATE INDEX disease_category    IF NOT EXISTS FOR (d:Disease)             ON (d.category);
CREATE INDEX effect_gravity      IF NOT EXISTS FOR (e:Effect)              ON (e.severity);
CREATE INDEX interaction_severity IF NOT EXISTS FOR ()-[r:INTERACTS_WITH]-() ON (r.severity);

// ─── 3. INDEX FULLTEXT (pour recherche textuelle) ────────────────────────────

CREATE FULLTEXT INDEX drug_text       IF NOT EXISTS FOR (d:Drug)             ON EACH [d.title, d.generic_name, d.brand_name];
CREATE FULLTEXT INDEX ingredient_text IF NOT EXISTS FOR (i:ActiveIngredient) ON EACH [i.name, i.pharmacological_class];
CREATE FULLTEXT INDEX disease_text    IF NOT EXISTS FOR (d:Disease)          ON EACH [d.name, d.symptoms, d.category];

// ─── 4. DESCRIPTION DU MODÈLE ────────────────────────────────────────────────
//
//   (:Drug)  {
//     id, title, generic_name, brand_name,
//     atc_code, therapeutic_class,
//     laboratory, form, dosage, route,
//     marketing_status, source, confidence_score,
//     updated_at, created_at
//   }
//
//   (:ActiveIngredient)  {
//     name, chemical_formula, molecular_weight,
//     pharmacological_class, mechanism_summary,
//     source, confidence_score, updated_at
//   }
//
//   (:Disease)  {
//     name, symptoms, category, icd10_code,
//     description, source, confidence_score
//   }
//
//   (:Effect)  {
//     id, name, severity, frequency,
//     description, source, confidence_score
//   }
//
//   (:Contraindication)  {
//     id, name, reason, severity,
//     category, source, confidence_score
//   }
//
//   (:DrugClass)  {
//     name, mechanism_of_action, parent_class,
//     description, source
//   }
//
//   (:Interaction)  {
//     id, severity, description,
//     mechanism, recommendation, risk_score,
//     source, confidence_score, updated_at
//   }
//
// ─── 5. RELATIONS ────────────────────────────────────────────────────────────
//
//   (d:Drug)-[:CONTAINS { dosage, is_active }]->(i:ActiveIngredient)
//   (d:Drug)-[:TREATS { rank, evidence_level }]->(di:Disease)
//   (d:Drug)-[:CAUSES { severity, frequency, risk_ratio }]->(e:Effect)
//   (d:Drug)-[:HAS_CONTRAINDICATION { reason, severity }]->(c:Contraindication)
//   (d:Drug)-[:BELONGS_TO]->(c:DrugClass)
//   (d:Drug)-[:INTERACTS_WITH { severity, mechanism, recommendation, description, risk_score }]->(d2:Drug)
//   (i:ActiveIngredient)-[:TREATS { rank, evidence_level }]->(di:Disease)
//   (i:ActiveIngredient)-[:CAUSES { severity, frequency }]->(e:Effect)
//   (c:DrugClass)-[:HAS_SUBCLASS]->(sub:DrugClass)
//   (a:ActiveIngredient)-[:HAS_MECHANISM]->(c:DrugClass)
//
// =============================================================================

RETURN '✅ Schéma créé : 7 labels, 6 contraintes, 6 index, 1 index fulltext' as status;
