// =============================================================================
// REQUÊTES CYPHER AVANCÉES — Knowledge Graph Médicaments
// =============================================================================

// ─── 1. TOUTES LES INTERACTIONS DANGEREUSES D'UN MÉDICAMENT ──────────────────

MATCH (d:Drug {title: 'ADVIL 400 mg'})-[r:INTERACTS_WITH]-(other:Drug)
WHERE r.severity IN ['Grave', 'Modérée']
RETURN d.title AS medicament,
       other.title AS interagit_avec,
       r.severity AS gravite,
       r.description AS description,
       r.recommendation AS recommandation,
       r.risk_score AS score_risque
ORDER BY r.risk_score DESC;

// ─── 2. INTERACTIONS DANGEREUSES ENTRE DEUX MÉDICAMENTS SPÉCIFIQUES ──────────

MATCH (d1:Drug {title: 'ADVIL 400 mg'})
MATCH (d2:Drug {title: 'ASPIRINE 100 mg'})
MATCH (d1)-[r:INTERACTS_WITH]-(d2)
RETURN d1.title AS medicament_1,
       d2.title AS medicament_2,
       r.severity AS gravite,
       r.mechanism AS mecanisme,
       r.description AS description,
       r.recommendation AS recommandation,
       r.risk_score AS score_risque;

// ─── 3. MÉDICAMENTS ALTERNATIFS SANS INTERACTION ─────────────────────────────

// Trouver des médicaments traitant la même maladie qu'un médicament donné
// mais qui n'interagissent PAS avec un autre médicament spécifique

MATCH (target:Drug {title: 'ADVIL 400 mg'})-[:TREATS]->(d:Disease)<-[:TREATS]-(alternative:Drug)
WHERE alternative.title <> 'ADVIL 400 mg'
  AND NOT EXISTS {
    MATCH (alternative)-[:INTERACTS_WITH]-(:Drug {title: 'ZOLOFT 50 mg'})
  }
RETURN alternative.title AS medicament_alternatif,
       alternative.dosage AS dosage,
       alternative.laboratory AS laboratoire,
       d.name AS maladie
ORDER BY alternative.title;

// ─── 4. MÉDICAMENTS PARTAGEANT LE MÊME PRINCIPE ACTIF ───────────────────────

MATCH (i:ActiveIngredient {name: 'Paracétamol'})<-[:CONTAINS]-(d:Drug)
RETURN i.name AS principe_actif,
       collect(d.title) AS medicaments,
       count(d) AS nombre_de_specialites
ORDER BY d.title;

// ─── 5. MÉDICAMENTS QUI TRAITENT LA MÊME MALADIE ────────────────────────────

MATCH (di:Disease)<-[:TREATS]-(d:Drug)
RETURN di.name AS maladie,
       di.icd10_code AS code_icd10,
       collect(d.title) AS medicaments,
       count(d) AS nombre_de_traitements
ORDER BY nombre_de_traitements DESC;

// ─── 6. CHEMIN DE RISQUE MAXIMAL ENTRE DEUX MÉDICAMENTS ──────────────────────

// Trouve tous les chemins d'interactions entre deux médicaments
// et calcule le score de risque cumulé

MATCH path = (d1:Drug {title: 'ADVIL 400 mg'})-[r:INTERACTS_WITH*..3]-(d2:Drug {title: 'ZOLOFT 50 mg'})
WHERE ALL(rel IN r WHERE rel.risk_score IS NOT NULL)
RETURN [n IN nodes(path) | n.title] AS chemin,
       [r IN relationships(path) | r.severity] AS gravites,
       [r IN relationships(path) | r.risk_score] AS scores_individuels,
       reduce(total = 0, rel IN r | total + rel.risk_score) AS score_risque_cumule,
       length(path) AS profondeur
ORDER BY score_risque_cumule DESC
LIMIT 10;

// ─── 7. RECOMMANDATION BASÉE SUR UN PROFIL PATIENT ───────────────────────────

// Simulation : Patient avec hypertension + diabète + hypercholestérolémie
// Quels médicaments sont sûrs ? (pas de CI + pas d'interactions graves)

WITH ['Hypertension artérielle', 'Diabète de type 2', 'Hypercholestérolémie'] AS pathologies
MATCH (d:Drug)-[:TREATS]->(di:Disease)
WHERE di.name IN pathologies

// Exclure les médicaments avec des CI absolues
OPTIONAL MATCH (d)-[ci_rel:HAS_CONTRAINDICATION]->(ci:Contraindication)
WHERE ci_rel.severity = 'Absolue'

WITH d, di, collect(DISTINCT ci.name) AS contraindications_absolues
WHERE size(contraindications_absolues) = 0

// Vérifier que les médicaments entre eux n'ont pas d'interactions graves
OPTIONAL MATCH (d)-[r:INTERACTS_WITH]-(other:Drug)-[:TREATS]->(other_di:Disease)
WHERE other_di.name IN pathologies AND r.severity = 'Grave'

WITH d, di, collect(DISTINCT other.title) AS interactions_graves
WHERE size(interactions_graves) = 0

RETURN d.title AS medicament_recommande,
       d.form AS forme,
       d.dosage AS dosage,
       d.laboratoire AS laboratoire,
       collect(DISTINCT di.name) AS pathologies_ciblees
ORDER BY d.title;

// ─── 8. ANALYSE DE COMBINAISON DE TRAITEMENTS ───────────────────────────────

// Vérifier les interactions dans une prescription donnée
WITH ['DOLIPRANE 500 mg', 'ADVIL 400 mg', 'ASPIRINE 100 mg'] AS prescription
UNWIND prescription AS drug_name
MATCH (d:Drug {title: drug_name})
WITH collect(d) AS drugs
UNWIND drugs AS d1
UNWIND drugs AS d2
WITH d1, d2 WHERE id(d1) < id(d2)
OPTIONAL MATCH (d1)-[r:INTERACTS_WITH]-(d2)
RETURN d1.title AS medicament_1,
       d2.title AS medicament_2,
       CASE
         WHEN r IS NULL THEN 'Aucune interaction connue'
         ELSE r.severity + ' — ' + r.description
       END AS analyse,
       r.recommendation AS recommandation,
       r.risk_score AS score_risque
ORDER BY r.risk_score DESC NULLS LAST;

// ─── 9. STATISTIQUES GÉNÉRALES DU GRAPHE ────────────────────────────────────

MATCH (d:Drug)
OPTIONAL MATCH (i:ActiveIngredient)
OPTIONAL MATCH (di:Disease)
OPTIONAL MATCH (e:Effect)
OPTIONAL MATCH (c:Contraindication)
OPTIONAL MATCH (dc:DrugClass)
OPTIONAL MATCH ()-[r:INTERACTS_WITH]-()
OPTIONAL MATCH ()-[rel]->()
RETURN count(DISTINCT d) AS nb_medicaments,
       count(DISTINCT i) AS nb_principes_actifs,
       count(DISTINCT di) AS nb_maladies,
       count(DISTINCT e) AS nb_effets,
       count(DISTINCT c) AS nb_contre_indications,
       count(DISTINCT dc) AS nb_classes,
       count(DISTINCT r) AS nb_interactions,
       count(DISTINCT rel) AS nb_relations_total;

// ─── 10. EFFETS INDÉSIRABLES PAR CLASSE THÉRAPEUTIQUE ───────────────────────

MATCH (dc:DrugClass)<-[:BELONGS_TO]-(d:Drug)-[:CAUSES]->(e:Effect)
RETURN dc.name AS classe_therapeutique,
       e.name AS effet_indesirable,
       e.severity AS gravite,
       e.frequency AS frequence,
       count(DISTINCT d) AS nb_medicaments_concernes
ORDER BY classe_therapeutique, e.severity DESC, nb_medicaments_concernes DESC;

// ─── 11. MÉDICAMENTS AVEC LE PLUS D'INTERACTIONS ─────────────────────────────

MATCH (d:Drug)-[r:INTERACTS_WITH]-()
RETURN d.title AS medicament,
       count(r) AS nb_interactions,
       collect(DISTINCT r.severity) AS types_interactions
ORDER BY nb_interactions DESC;

// ─── 12. RECHERCHE FULLTEXT (NLP) D'UN PRINCIPE ACTIF ───────────────────────

CALL db.index.fulltext.queryNodes('ingredient_text', 'paracetamol') YIELD node, score
MATCH (node)<-[:CONTAINS]-(d:Drug)
RETURN d.title AS medicament,
       node.name AS principe_actif,
       node.chemical_formula AS formule,
       score
ORDER BY score DESC;

// ─── 13. CHAÎNE THÉRAPEUTIQUE COMPLÈTE D'UN MÉDICAMENT ──────────────────────

MATCH path = (d:Drug {title: 'ADVIL 400 mg'})-[*1..2]-(n)
RETURN [node IN nodes(path) | 
  CASE 
    WHEN node:Drug THEN '💊 ' + node.title
    WHEN node:ActiveIngredient THEN '🧪 ' + node.name
    WHEN node:Disease THEN '🏥 ' + node.name
    WHEN node:Effect THEN '⚠️ ' + node.name
    WHEN node:DrugClass THEN '📂 ' + node.name
    WHEN node:Contraindication THEN '🚫 ' + node.name
    ELSE '❓ ' + coalesce(node.name, node.title, 'inconnu')
  END
] AS chaine,
  [rel IN relationships(path) | type(rel)] AS relations;

// ─── 14. NETTOYAGE : SUPPRIMER LES NŒUDS ORPHELINS ──────────────────────────

// Trouver les nœuds sans aucune relation
MATCH (n)
WHERE NOT EXISTS { MATCH (n)--() }
RETURN labels(n) AS type_noeud,
       coalesce(n.name, n.title, n.id, '?') AS nom,
       'Orphelin — à supprimer' AS statut;

// Pour supprimer les orphelins (décommenter si nécessaire) :
// MATCH (n) WHERE NOT EXISTS { MATCH (n)--() } DETACH DELETE n;
