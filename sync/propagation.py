"""
Propagation des publications vers les index dérivés.

Deux cibles : l'index vectoriel Qdrant et le graphe Neo4j. Chacune souffrait
d'un défaut distinct, relevé lors de l'audit P5.

**Qdrant.** Cinq stratégies d'identifiant coexistaient dans le projet, dont
deux fondées sur `hash()` de Python — aléatoire à chaque processus — et une
sur le rang dans le curseur. C'est cette dernière qui a produit la collection
en service : ses identifiants sont 0, 1, 2… et ne portent donc aucun lien
stable avec les documents. Réindexer par-dessus créerait des doublons au lieu
de mettre à jour. La seule issue propre est de reconstruire dans une
collection neuve avec un identifiant déterministe, puis de basculer l'alias.

**Neo4j.** La synchronisation de `app.py:386-402` est une amorce à usage
unique : elle ne s'exécute que si le graphe compte moins de 10 nœuds `Drug`.
Le seuil est franchi depuis longtemps, si bien qu'aucune fiche nouvelle n'y
entre plus. Le garde teste de surcroît une étiquette (`Drug`) que la fonction
de synchronisation ne produit pas — elle crée des `Medicine`.
"""

import datetime
import hashlib
import sys

from . import config

QDRANT_COLLECTION = 'medicines'
QDRANT_STAGING = 'medicines_v2'
VECTOR_SIZE = 384
EMBEDDING_MODEL = 'all-MiniLM-L6-v2'
BATCH = 256


def _out(text=''):
    encoding = sys.stdout.encoding or 'utf-8'
    sys.stdout.write(str(text).encode(encoding, 'replace').decode(encoding) + '\n')


def point_id(mongo_id):
    """
    Identifiant déterministe dérivé de l'identifiant MongoDB.

    Stable d'une exécution à l'autre, contrairement à `hash()` de Python dont
    la valeur pour une chaîne change à chaque processus, et contrairement au
    rang dans le curseur qui se décale dès qu'un document est inséré.
    """
    digest = hashlib.sha256(str(mongo_id).encode('utf-8')).hexdigest()
    return int(digest[:16], 16) % (2 ** 63)


def embedding_text(medicine):
    """Texte soumis au modèle. Reprend la composition de l'indexation en service."""
    details = medicine.get('medicine_details') or {}
    parts = [medicine.get('title') or '']
    parts.extend((details.get('substances_actives') or [])[:5])
    if details.get('forme'):
        parts.append(details['forme'])
    if details.get('laboratoire'):
        parts.append(details['laboratoire'])
    return ' '.join(p for p in parts if p)[:500]


def payload_of(medicine):
    details = medicine.get('medicine_details') or {}
    return {
        'mongo_id': str(medicine['_id']),
        'cis': medicine.get('cis'),
        'title': medicine.get('title'),
        'substances': (details.get('substances_actives') or [])[:5],
        'forme': details.get('forme'),
        'laboratoire': details.get('laboratoire'),
        'url': medicine.get('url'),
        'indexed_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }


def _add_backend_path():
    """
    Rend importable le connecteur Neo4j de l'application.

    Il vit dans `frontend_backend/` et n'est pas exposé comme paquet : les
    modules de ce répertoire s'importent à plat.
    """
    import os
    backend = os.path.join(config.BASE_DIR, 'frontend_backend')
    if backend not in sys.path:
        sys.path.insert(0, backend)


def _connector():
    """
    Instancie et ouvre le connecteur Neo4j de l'application.

    Le constructeur ne se connecte pas : `connect()` doit être appelé
    explicitement, comme le fait `app.py:163`.
    """
    import os
    _add_backend_path()
    from neo4j_connector import Neo4jConnector
    connector = Neo4jConnector(
        uri=os.getenv('NEO4J_URI', 'neo4j://127.0.0.1:7687'),
        user=os.getenv('NEO4J_USER', 'neo4j'),
        password=os.getenv('NEO4J_PASSWORD', ''),
        database=os.getenv('NEO4J_DATABASE', 'neo4j'))
    try:
        connector.connect()
    except Exception:                                       # noqa: BLE001
        return connector
    return connector


def _clients():
    from qdrant_client import QdrantClient
    from sentence_transformers import SentenceTransformer
    client = QdrantClient(host=config.QDRANT_HOST if hasattr(config, 'QDRANT_HOST') else '127.0.0.1',
                          port=6333, timeout=120)
    model = SentenceTransformer(EMBEDDING_MODEL)
    return client, model


def index_into(db, client, model, collection, query=None, progress=1000):
    """
    Indexe les fiches correspondant au filtre dans la collection indiquée.

    L'opération est idempotente : l'identifiant étant dérivé du document, une
    seconde exécution met à jour les mêmes points au lieu d'en ajouter.
    """
    from qdrant_client.models import PointStruct

    cursor = db[config.COLL_MEDICINES].find(query or {})
    points, done = [], 0

    for medicine in cursor:
        text = embedding_text(medicine)
        if not text:
            continue
        points.append(PointStruct(id=point_id(medicine['_id']),
                                  vector=model.encode(text).tolist(),
                                  payload=payload_of(medicine)))
        if len(points) >= BATCH:
            client.upsert(collection_name=collection, points=points)
            done += len(points)
            points = []
            if progress and done % progress < BATCH:
                _out('    ... %s fiches indexees' % f'{done:,}')

    if points:
        client.upsert(collection_name=collection, points=points)
        done += len(points)
    return done


def rebuild_qdrant(db, keep_old=False):
    """
    Reconstruit l'index vectoriel dans une collection neuve, puis bascule.

    La collection en service n'est jamais modifiée en place : elle reste
    interrogeable jusqu'à la validation de la nouvelle, et la bascule se fait
    par alias, ce qui laisse le nom `medicines` inchangé pour l'application.
    """
    from qdrant_client.models import Distance, VectorParams

    client, model = _clients()
    expected = db[config.COLL_MEDICINES].count_documents({})

    _out('  reconstruction dans %s (%s fiches attendues)...' % (QDRANT_STAGING, f'{expected:,}'))
    try:
        client.delete_collection(QDRANT_STAGING)
    except Exception:
        pass
    client.create_collection(
        collection_name=QDRANT_STAGING,
        vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE))

    indexed = index_into(db, client, model, QDRANT_STAGING)
    actual = client.get_collection(QDRANT_STAGING).points_count
    _out('  indexees : %s | points dans la collection : %s' % (f'{indexed:,}', f'{actual:,}'))

    if actual != expected:
        _out('  ECART entre le nombre de fiches et de points : bascule annulee.')
        return {'ok': False, 'expected': expected, 'actual': actual}

    # Bascule : l'alias porte le nom que l'application interroge.
    existing = {c.name for c in client.get_collections().collections}
    if QDRANT_COLLECTION in existing:
        if keep_old:
            client.update_collection_aliases(change_aliases_operations=[])
        else:
            client.delete_collection(QDRANT_COLLECTION)

    from qdrant_client.models import CreateAlias, CreateAliasOperation
    client.update_collection_aliases(change_aliases_operations=[
        CreateAliasOperation(create_alias=CreateAlias(
            collection_name=QDRANT_STAGING, alias_name=QDRANT_COLLECTION))])

    _out('  alias %s -> %s pose' % (QDRANT_COLLECTION, QDRANT_STAGING))
    return {'ok': True, 'expected': expected, 'actual': actual}


def propagate_qdrant(db, query=None):
    """Indexation incrémentale, sur la collection en service via son alias."""
    client, model = _clients()
    before = client.get_collection(QDRANT_COLLECTION).points_count
    done = index_into(db, client, model, QDRANT_COLLECTION, query)
    after = client.get_collection(QDRANT_COLLECTION).points_count
    return {'indexees': done, 'points_avant': before, 'points_apres': after}


# ── Neo4j ──────────────────────────────────────────────────────────────

def propagate_neo4j(db, query=None, progress=500):
    """
    Fusionne les fiches dans le graphe.

    Contourne l'amorce de `app.py`, qui ne se déclenche plus. Les requêtes du
    connecteur reposent sur `MERGE`, donc l'opération est idempotente.
    """
    connector = _connector()
    if not connector.driver:
        return {'ok': False, 'motif': 'Neo4j indisponible'}

    done, failed = 0, 0
    for medicine in db[config.COLL_MEDICINES].find(query or {}):
        try:
            connector.sync_medicine_from_mongo(medicine)
            done += 1
        except Exception:                                   # noqa: BLE001
            failed += 1
        if progress and done and done % progress == 0:
            _out('    ... %s fiches fusionnees' % f'{done:,}')

    connector.close() if hasattr(connector, 'close') else None
    return {'ok': True, 'fusionnees': done, 'echecs': failed}


# ── Enrichissement DrugBank ────────────────────────────────────────────

def propagate_enrichment(db, only_missing=True, progress=250):
    """
    Complète `medicine_enrichment` pour les fiches qui n'en ont pas encore.

    Le script `matching_drugbank.py` fonctionne en tout ou rien : il relit les
    9 804 fiches, les charge intégralement en mémoire et reconstruit
    `dci_lookup` depuis zéro. Rejouer ce traitement pour 2 242 fiches nouvelles
    serait disproportionné.

    Ses fonctions d'appariement sont en revanche réutilisables telles quelles.
    Seule la construction de l'index DrugBank est coûteuse — elle parcourt le
    million de documents de la collection — et n'est faite qu'une fois.

    `dci_lookup` n'est pas reconstruit : il indexe les molécules DrugBank, que
    l'ajout de spécialités françaises ne modifie pas.
    """
    from pymongo import UpdateOne

    _add_backend_path()
    from scripts.matching_drugbank import (build_drugbank_index,
                                           fetch_drugbank_enrichment,
                                           match_medicine_to_drugbank)

    known = set()
    if only_missing:
        known = {d['medicine_id']
                 for d in db.medicine_enrichment.find({}, {'medicine_id': 1})}

    projection = {'title': 1, 'composition': 1, 'classe_therapeutique': 1,
                  'medicine_details.substances_actives': 1}
    candidates = [m for m in db[config.COLL_MEDICINES].find({}, projection)
                  if not only_missing or m['_id'] not in known]

    if not candidates:
        return {'traitees': 0, 'appariees': 0, 'sans_correspondance': 0}

    _out('  %s fiches a apparier' % f'{len(candidates):,}')
    _out('  construction de l index DrugBank...')
    index = build_drugbank_index()

    operations, matched, unmatched = [], 0, 0
    for position, medicine in enumerate(candidates, 1):
        result = match_medicine_to_drugbank(medicine, index)
        document = {
            'medicine_id': medicine['_id'],
            'medicine_name': medicine.get('title', ''),
            'drugbank_ids': result['drugbank_ids'],
            'match_confidence': result['match_confidence'],
            'match_type': result['match_type'],
            'match_rule': result['match_rule'],
            'match_score': result['match_score'],
            'match_source': result['match_source'],
            'matched_on': result.get('matched_on', ''),
            'original_fr_matched': result.get('original_fr', ''),
            'matched_at': datetime.datetime.now(datetime.timezone.utc).timestamp(),
        }
        if result['drugbank_ids']:
            document['enriched'] = fetch_drugbank_enrichment(result['drugbank_ids'])
            matched += 1
        else:
            document['enriched'] = {}
            unmatched += 1

        operations.append(UpdateOne({'medicine_id': medicine['_id']},
                                    {'$set': document}, upsert=True))
        if len(operations) >= 200:
            db.medicine_enrichment.bulk_write(operations, ordered=False)
            operations = []
        if progress and position % progress == 0:
            _out('    ... %s / %s' % (f'{position:,}', f'{len(candidates):,}'))

    if operations:
        db.medicine_enrichment.bulk_write(operations, ordered=False)

    return {'traitees': len(candidates), 'appariees': matched,
            'sans_correspondance': unmatched}


def neo4j_counts():
    """Compteurs du graphe, pour vérifier la convergence."""
    connector = _connector()
    if not connector.driver:
        return None
    counts = {}
    with connector.driver.session(database=connector.database) as session:
        for label in ('Medicine', 'Drug', 'Substance', 'ActiveIngredient'):
            counts[label] = session.run(
                'MATCH (n:%s) RETURN count(n) AS c' % label).single()['c']
    return counts
