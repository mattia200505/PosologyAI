// =============================================================================
// REQUÊTES FAERS — Graphe coloré des effets indésirables
// À coller dans Neo4j Browser (http://127.0.0.1:7474/browser/)
// =============================================================================

// ─── 0. STYLE Neo4j Browser (colle ça dans la zone :style) ──────────────────
// Va dans l'icône "eye" → "Graph Visualization" → "Style" ou exécute :style
// Ou copie ça dans la console :style puis colle le bloc suivant :
/*
:style {
  "node": {
    "Drug": {
      "color": "#6366f1",
      "defaultCaption": "name"
    },
    "AdverseEvent": {
      "color": "#f59e0b",
      "defaultCaption": "name",
      "size": 20
    },
    "ATC": {
      "color": "#10b981",
      "defaultCaption": "code",
      "size": 15
    }
  },
  "relationship": {
    "CAUSES": {
      "color": "#ef4444",
      "thickness": "property(llr)"
    },
    "AFFECTS": {
      "color": "#8b5cf6",
      "dashes": [4, 4]
    }
  }
}
*/

// ─── 1. GRAPHE AVEC 3 MÉDICAMENTS DE NIVEAUX FAERS DIFFÉRENTS ──────────────
// Trouve 3 drugs qui ont des profils d'effets très différents

MATCH (d:Drug)-[r:CAUSES]->(e:AdverseEvent)
WITH d,
     avg(r.llr) AS llr_moyen,
     max(r.llr) AS llr_max,
     count(r) AS nb_effets,
     sum(r.drug_ae) AS total_reports
WHERE nb_effets > 5
RETURN d.name AS medicament,
       d.id AS id,
       round(llr_moyen, 2) AS llr_moyen,
       round(llr_max, 2) AS llr_max,
       nb_effets AS nb_effets_indesirables,
       total_reports AS total_signalements
ORDER BY llr_moyen DESC
LIMIT 3;

// Puis visualise un médicament spécifique avec ses effets :
MATCH (d:Drug {name: 'Acetaminophen'})-[r:CAUSES]->(e:AdverseEvent)
RETURN d, r, e
LIMIT 50;

// ─── 2. RÉPARTITION DES NIVEAUX FAERS ──────────────────────────────────────

// Compter les relations CAUSES par niveau de sévérité (basé sur LLR)
MATCH ()-[r:CAUSES]->()
RETURN
  CASE
    WHEN r.llr >= 10  THEN '🔴 Critique (LLR≥10)'
    WHEN r.llr >= 5   THEN '🟠 Élevé (5≤LLR<10)'
    WHEN r.llr >= 2   THEN '🟡 Modéré (2≤LLR<5)'
    ELSE '🟢 Faible (LLR<2)'
  END AS niveau_faers,
  count(*) AS nb_relations,
  round(avg(r.llr), 2) AS llr_moyen,
  sum(r.drug_ae) AS total_signalements
ORDER BY nb_relations DESC;

// ─── 3. TOP MÉDICAMENTS PAR NIVEAU FAERS ───────────────────────────────────

// Top 5 médicaments par niveau Critique (LLR ≥ 10)
MATCH (d:Drug)-[r:CAUSES]->(e:AdverseEvent)
WHERE r.llr >= 10
RETURN d.name AS medicament,
       count(r) AS nb_effets_critiques,
       round(avg(r.llr), 2) AS llr_moyen,
       collect(DISTINCT e.name) AS effets
ORDER BY nb_effets_critiques DESC
LIMIT 5;

// Top 5 médicaments par niveau Élevé (5 ≤ LLR < 10)
MATCH (d:Drug)-[r:CAUSES]->(e:AdverseEvent)
WHERE r.llr >= 5 AND r.llr < 10
RETURN d.name AS medicament,
       count(r) AS nb_effets_eleves,
       round(avg(r.llr), 2) AS llr_moyen
ORDER BY nb_effets_eleves DESC
LIMIT 5;

// Top 5 médicaments par nombre total de signalements
MATCH (d:Drug)-[r:CAUSES]->(e:AdverseEvent)
RETURN d.name AS medicament,
       count(r) AS nb_effets,
       sum(r.drug_ae) AS total_signalements,
       round(avg(r.llr), 2) AS llr_moyen
ORDER BY total_signalements DESC
LIMIT 5;

// ─── 4. GRAPHE COMPLET FAERS COLORÉ (VISUALISATION) ────────────────────────

// Vue d'ensemble : 1 médicament + ses effets avec code couleur LLR
MATCH (d:Drug {id: 'DB00316'})-[r:CAUSES]->(e:AdverseEvent)
WITH d, r, e,
  CASE
    WHEN r.llr >= 10  THEN 'Critique'
    WHEN r.llr >= 5   THEN 'Élevé'
    WHEN r.llr >= 2   THEN 'Modéré'
    ELSE 'Faible'
  END AS niveau
RETURN d, r, e, niveau
ORDER BY r.llr DESC
LIMIT 100;

// ─── 5. VÉRIFIER UN MÉDICAMENT PRÉCIS ──────────────────────────────────────

// Remplacer 'Acetaminophen' par le nom du médicament voulu
MATCH (d:Drug)
WHERE toLower(d.name) CONTAINS toLower('acetaminophen')
RETURN d.name AS nom, d.id AS id, d.formula AS formule, d.weight AS poids;

// Voir ses effets indésirables avec LLR
MATCH (d:Drug)-[r:CAUSES]->(e:AdverseEvent)
WHERE toLower(d.name) CONTAINS toLower('acetaminophen')
RETURN e.name AS effet_indesirable,
       round(r.llr, 2) AS llr,
       r.drug_ae AS signalements,
       CASE
         WHEN r.llr >= 10  THEN '🔴 Critique'
         WHEN r.llr >= 5   THEN '🟠 Élevé'
         WHEN r.llr >= 2   THEN '🟡 Modéré'
         ELSE '🟢 Faible'
       END AS niveau
ORDER BY r.llr DESC
LIMIT 20;

// Statistiques complètes pour un médicament
MATCH (d:Drug)-[r:CAUSES]->(e:AdverseEvent)
WHERE toLower(d.name) CONTAINS toLower('acetaminophen')
RETURN count(r) AS total_effets,
       sum(r.drug_ae) AS total_signalements,
       round(avg(r.llr), 2) AS llr_moyen,
       max(r.llr) AS llr_max,
       count(DISTINCT e) AS effets_distincts;

// ─── 6. VÉRIFIER LES RELATIONS FAERS DISPONIBLES ──────────────────────────

// Combien de relations CAUSES au total ?
MATCH ()-[r:CAUSES]->()
RETURN 'FAERS' AS source,
       count(r) AS total_relations,
       count(DISTINCT r.llr) AS valeurs_llr_distinctes,
       min(r.llr) AS llr_min,
       max(r.llr) AS llr_max,
       avg(r.llr) AS llr_moyen;

// Quels médicaments ont le plus de signalements FAERS ?
MATCH (d:Drug)-[r:CAUSES]->(e:AdverseEvent)
RETURN d.name AS medicament,
       count(r) AS nb_relations_causes,
       sum(r.drug_ae) AS signalements,
       count(DISTINCT e) AS nb_effets_distincts
ORDER BY signalements DESC
LIMIT 10;

// Quels effets indésirables sont les plus fréquents ?
MATCH (d:Drug)-[r:CAUSES]->(e:AdverseEvent)
RETURN e.name AS effet,
       count(r) AS nb_medicaments,
       sum(r.drug_ae) AS total_signalements,
       round(avg(r.llr), 2) AS llr_moyen
ORDER BY nb_medicaments DESC
LIMIT 10;

// Distribution des LLR (pour calibration des seuils)
MATCH ()-[r:CAUSES]->()
RETURN
  CASE
    WHEN r.llr >= 100 THEN '≥100'
    WHEN r.llr >= 50  THEN '50-99'
    WHEN r.llr >= 20  THEN '20-49'
    WHEN r.llr >= 10  THEN '10-19'
    WHEN r.llr >= 5   THEN '5-9'
    WHEN r.llr >= 2   THEN '2-4'
    ELSE '<2'
  END AS tranche_llr,
  count(*) AS nb_relations,
  round(100.0 * count(*) / sum(count(*)) OVER (), 1) AS pourcentage
ORDER BY tranche_llr;

// ─── 7. GRAPHE DDInter (interactions médicamenteuses) ──────────────────────

// Voir les interactions d'un médicament spécifique
MATCH (d:Drug {id: 'DDInter2'})-[r:INTERACTS_WITH]->(other:Drug)
RETURN d.name AS medicament,
       other.name AS interagit_avec,
       r.level AS niveau_risque,
       r.category AS categorie_atc
ORDER BY r.level;

// Interactions de niveau 'Contraindicated' uniquement
MATCH (d:Drug)-[r:INTERACTS_WITH]->(other:Drug)
WHERE r.level = 'Contraindicated'
RETURN d.name AS drug_a,
       other.name AS drug_b,
       r.category AS atc_category
LIMIT 50;

// Stats DDInter
MATCH ()-[r:INTERACTS_WITH]->()
RETURN r.level AS niveau,
       count(*) AS total,
       count(DISTINCT r.category) AS categories_atc
ORDER BY total DESC;

// ─── 8. NETTOYAGE (optionnel) ─────────────────────────────────────────────

// Voir les médicaments sans aucune relation
MATCH (d:Drug)
WHERE NOT EXISTS { MATCH (d)--() }
RETURN d.name AS medicament_orphelin, d.id
LIMIT 20;
