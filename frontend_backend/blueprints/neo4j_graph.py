from flask import Blueprint, jsonify, request, current_app
import logging

logger = logging.getLogger(__name__)

neo4j_graph_bp = Blueprint('neo4j_graph', __name__, url_prefix='/api/neo4j')

def get_connector():
    try:
        return current_app.neo4j
    except Exception:
        return None

@neo4j_graph_bp.route('/stats')
def stats():
    connector = get_connector()
    if not connector or not connector.driver:
        return jsonify({'error': 'Neo4j indisponible'}), 500
    try:
        db = connector.database
        with connector.driver.session(database=db) as s:
            nodes = s.run("MATCH (n) RETURN labels(n) AS type, count(*) AS total ORDER BY total DESC").data()
            rels = s.run("MATCH ()-[r]->() RETURN type(r) AS type, count(*) AS total ORDER BY total DESC").data()
            # Plus de repartition par gravite : la source n'en porte aucune
            # (cf. rapport P9-1). Renvoyer une cle vide vaut mieux qu'un
            # histogramme a une seule barre intitulee « null ».
            severities = []
            total_nodes = s.run("MATCH (n) RETURN count(n) AS total").single()['total']
            total_rels = s.run("MATCH ()-[r]->() RETURN count(r) AS total").single()['total']
            meds_with_ints = s.run("""
                MATCH (m:Medicine)-[:HAS_DRUGBANK_SUBSTANCE]->()-[:INTERACTS_WITH]-(:DrugbankSubstance)
                RETURN count(DISTINCT m) AS total
            """).single()['total']
            # Les tetes de liste sont des substances, non des specialites : dix
            # presentations d'une meme molecule occupaient les cinq places.
            top_meds = s.run("""
                MATCH (x:DrugbankSubstance)-[r:INTERACTS_WITH]-(:DrugbankSubstance)
                RETURN x.name AS title, count(r) AS interactions
                ORDER BY interactions DESC LIMIT 5
            """).data()
        return jsonify({
            'nodes': nodes,
            'relationships': rels,
            'severities': severities,
            'total_nodes': total_nodes,
            'total_rels': total_rels,
            'meds_with_interactions': meds_with_ints,
            'top_meds': top_meds
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@neo4j_graph_bp.route('/search')
def search():
    q = request.args.get('q', '').strip()
    if not q:
        return jsonify({'error': 'Parametre q requis'}), 400
    connector = get_connector()
    if not connector or not connector.driver:
        return jsonify({'error': 'Neo4j indisponible'}), 500
    try:
        db = connector.database
        with connector.driver.session(database=db) as s:
            meds = s.run("""
                MATCH (m:Medicine)
                WHERE toLower(coalesce(m.title, '')) CONTAINS toLower($q)
                RETURN m.title AS title, m.url AS id
                LIMIT 20
            """, q=q).data()
        return jsonify({'medicines': meds})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@neo4j_graph_bp.route('/medicine-graph')
def medicine_graph():
    title = request.args.get('title', '').strip()
    if not title:
        return jsonify({'error': 'Parametre title requis'}), 400
    connector = get_connector()
    if not connector or not connector.driver:
        return jsonify({'error': 'Neo4j indisponible'}), 500
    try:
        db = connector.database
        with connector.driver.session(database=db) as s:
            result = s.run("""
                MATCH (d:Medicine)
                WHERE toLower(coalesce(d.title, '')) CONTAINS toLower($title)
                OPTIONAL MATCH (d)-[r]-(n)
                RETURN d, collect(DISTINCT {rel: type(r), node: n}) AS neighbors
                LIMIT 1
            """, title=title).data()
            if not result:
                return jsonify({'error': 'Medicament non trouve'}), 404
            nodes = {}
            edges = []
            def add_node(entity, group):
                uid = entity.element_id if hasattr(entity, 'element_id') else str(id(entity))
                name = coalesce(entity, 'title', entity.get('name', ''))
                if uid not in nodes:
                    label = name[:30]
                    nodes[uid] = {'id': uid, 'label': label, 'group': group, 'title': name}
            def coalesce(entity, *keys):
                for k in keys:
                    v = entity.get(k)
                    if v:
                        return v
                return str(uid) if 'uid' in dir() else ''
            row = result[0]
            d = row['d']
            did = d.element_id if hasattr(d, 'element_id') else str(id(d))
            add_node(d, 'drug')
            for nb in row['neighbors']:
                n = nb['node']
                if n:
                    nid = n.element_id if hasattr(n, 'element_id') else str(id(n))
                    labels = list(n.labels) if hasattr(n, 'labels') else ['Unknown']
                    group = labels[0].lower() if labels else 'unknown'
                    if group == 'activesubstance': group = 'ingredient'
                    add_node(n, group)
                    edges.append({'from': did, 'to': nid, 'label': nb['rel']})
            # L'interaction relie deux substances, non deux specialites.
            interactions = s.run("""
                MATCH (d:Medicine)-[:HAS_DRUGBANK_SUBSTANCE]->()-[r:INTERACTS_WITH]-(other:DrugbankSubstance)
                WHERE toLower(coalesce(d.title, '')) CONTAINS toLower($title)
                RETURN other, null AS sev, coalesce(r.description, '') AS eff
                LIMIT 15
            """, title=title).data()
            for it in interactions:
                other = it['other']
                oid = other.element_id if hasattr(other, 'element_id') else str(id(other))
                add_node(other, 'drug_interact')
                sev = (it.get('sev') or '').lower()
                color_map = {'grave': '#e11d48', 'high': '#e11d48',
                             'moderee': '#d97706', 'moderate': '#d97706',
                             'mineure': '#22c55e', 'low': '#22c55e'}
                color = color_map.get(sev, '#6b7280')
                edges.append({
                    'from': did, 'to': oid,
                    'label': sev[:8] if sev else 'interacts',
                    'title': it.get('eff', ''),
                    'color': color
                })
        return jsonify({'nodes': list(nodes.values()), 'edges': edges})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@neo4j_graph_bp.route('/medicine-interactions-detail')
def medicine_interactions_detail():
    title = request.args.get('title', '').strip()
    if not title:
        return jsonify({'error': 'Parametre title requis'}), 400
    connector = get_connector()
    if not connector or not connector.driver:
        return jsonify({'error': 'Neo4j indisponible'}), 500
    try:
        db = connector.database
        with connector.driver.session(database=db) as s:
            result = s.run("""
                MATCH (d:Medicine)-[:HAS_DRUGBANK_SUBSTANCE]->()-[r:INTERACTS_WITH]-(other:DrugbankSubstance)
                WHERE toLower(coalesce(d.title, '')) CONTAINS toLower($title)
                RETURN other.name AS medicine,
                       r.severity AS severity, r.description AS effect,
                       r.mechanism AS mechanism, r.recommendation AS recommendation
                ORDER BY r.severity DESC
                LIMIT 30
            """, title=title).data()
        return jsonify({'interactions': result})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@neo4j_graph_bp.route('/medicine-substances')
def medicine_substances():
    title = request.args.get('title', '').strip()
    if not title:
        return jsonify({'error': 'Parametre title requis'}), 400
    connector = get_connector()
    if not connector or not connector.driver:
        return jsonify({'error': 'Neo4j indisponible'}), 500
    try:
        db = connector.database
        with connector.driver.session(database=db) as s:
            result = s.run("""
                MATCH (d:Medicine)-[:CONTAINS]->(i:ActiveIngredient)
                WHERE toLower(coalesce(d.title, '')) CONTAINS toLower($title)
                OPTIONAL MATCH (d)-[:HAS_DRUGBANK_SUBSTANCE]->()-[:INTERACTS_WITH]-(x:DrugbankSubstance)
                RETURN i.name AS substance,
                       collect(DISTINCT x.name)[..20] AS related_medicines,
                       [] AS severities
                ORDER BY i.name
            """, title=title).data()
        return jsonify({'substances': result})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@neo4j_graph_bp.route('/substance-network')
def substance_network():
    limit = int(request.args.get('limit', 30))
    connector = get_connector()
    if not connector or not connector.driver:
        return jsonify({'error': 'Neo4j indisponible'}), 500
    try:
        db = connector.database
        with connector.driver.session(database=db) as s:
            result = s.run("""
                MATCH (s1:DrugbankSubstance)-[r:INTERACTS_WITH]-(s2:DrugbankSubstance)
                WHERE s1.drugbank_id < s2.drugbank_id
                OPTIONAL MATCH (m:Medicine)-[:HAS_DRUGBANK_SUBSTANCE]->(s1)
                WITH s1, s2, count(DISTINCT m) AS pairs
                RETURN s1.name AS s1, s2.name AS s2, null AS sev, pairs
                ORDER BY pairs DESC LIMIT $limit
            """, limit=limit).data()
            nodes = {}
            edges = []
            for row in result:
                for sname in [row['s1'], row['s2']]:
                    if sname not in nodes:
                        nodes[sname] = {'id': sname, 'label': sname, 'group': 'substance', 'title': sname}
                sev = row.get('sev', 'moderate') or 'moderate'
                color_map = {'grave': '#e11d48', 'high': '#e11d48',
                             'moderee': '#d97706', 'moderate': '#d97706',
                             'mineure': '#22c55e', 'low': '#22c55e'}
                color = color_map.get(sev.lower(), '#6b7280')
                edges.append({
                    'from': row['s1'], 'to': row['s2'],
                    'label': sev,
                    'color': color,
                    'width': min(row['pairs'] / 2, 5)
                })
        return jsonify({'nodes': list(nodes.values()), 'edges': edges})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@neo4j_graph_bp.route('/sync-interactions', methods=['POST'])
def sync_interactions():
    connector = get_connector()
    if not connector or not connector.driver:
        return jsonify({'error': 'Neo4j indisponible'}), 500
    # `connector.sync_interactions()` construit le modèle spécialité–spécialité
    # que P9-3 remplace : un seul appel recréerait 2,4 millions de relations
    # redondantes entre nœuds `Medicine`, que plus aucune requête ne lit, et
    # ferait réapparaître la gravité 'moderate' inventée par défaut.
    # La route est neutralisée plutôt que supprimée, pour que l'appel échoue
    # avec une explication au lieu de dégrader le graphe en silence.
    return jsonify({
        'error': 'Route hors service depuis la reconstruction P9-3.',
        'detail': "Les interactions se construisent desormais entre substances "
                  "(:DrugbankSubstance)-[:INTERACTS_WITH]-(:DrugbankSubstance). "
                  "Voir rapport/RAPPORT_P9-3_RECONSTRUCTION.md.",
    }), 410

@neo4j_graph_bp.route('/full-graph')
def full_graph():
    limit = int(request.args.get('limit', 50))
    connector = get_connector()
    if not connector or not connector.driver:
        return jsonify({'error': 'Neo4j indisponible'}), 500
    try:
        db = connector.database
        with connector.driver.session(database=db) as s:
            result = s.run("""
                MATCH (d:DrugbankSubstance)-[r:INTERACTS_WITH]-(other:DrugbankSubstance)
                RETURN d, other, null AS sev, coalesce(r.description, '') AS eff
                LIMIT $limit
            """, limit=limit).data()
            nodes = {}
            edges = []
            def add_node(entity, group):
                uid = entity.element_id if hasattr(entity, 'element_id') else str(id(entity))
                name = entity.get('title') or entity.get('name') or str(uid)
                label = name[:25] + '...' if len(name) > 25 else name
                if uid not in nodes:
                    nodes[uid] = {'id': uid, 'label': label, 'group': group, 'title': name}
            for row in result:
                add_node(row['d'], 'drug')
                add_node(row['other'], 'drug_interact')
                did = row['d'].element_id if hasattr(row['d'], 'element_id') else str(id(row['d']))
                oid = row['other'].element_id if hasattr(row['other'], 'element_id') else str(id(row['other']))
                sev = (row.get('sev') or '').lower()
                color_map = {'grave': '#e11d48', 'high': '#e11d48',
                             'moderee': '#d97706', 'moderate': '#d97706',
                             'mineure': '#22c55e', 'low': '#22c55e'}
                color = color_map.get(sev, '#6b7280')
                edges.append({
                    'from': did, 'to': oid,
                    'label': sev[:8] if sev else '',
                    'title': row.get('eff', ''),
                    'color': color
                })
        return jsonify({'nodes': list(nodes.values()), 'edges': edges})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
