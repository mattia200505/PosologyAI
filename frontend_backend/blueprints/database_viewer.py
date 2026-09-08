from flask import Blueprint, request, render_template, session, redirect, url_for, jsonify
from qdrant_client import QdrantClient
import os
from dotenv import load_dotenv
import logging

logger = logging.getLogger(__name__)
load_dotenv()

db_viewer_bp = Blueprint('database_viewer', __name__, url_prefix='/database-viewer')

PASSWORD = os.getenv('VIEWER_PASSWORD', 'admin')
QDRANT_HOST = os.getenv('QDRANT_HOST', '127.0.0.1')
QDRANT_PORT = int(os.getenv('QDRANT_PORT', 6333))
QDRANT_PATH = os.getenv('QDRANT_PATH', '')

def get_qdrant():
    if QDRANT_PATH:
        return QdrantClient(path=QDRANT_PATH, timeout=10)
    return QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT, timeout=10)

def login_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('db_viewer_authenticated'):
            return redirect(url_for('database_viewer.login'))
        return f(*args, **kwargs)
    return decorated

@db_viewer_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        if request.form.get('password') == PASSWORD:
            session['db_viewer_authenticated'] = True
            return redirect(url_for('database_viewer.index'))
        return render_template('database_viewer/login.html', error='Mot de passe incorrect')
    return render_template('database_viewer/login.html')

@db_viewer_bp.route('/logout')
def logout():
    session.pop('db_viewer_authenticated', None)
    return redirect(url_for('database_viewer.login'))

@db_viewer_bp.route('/')
@login_required
def index():
    try:
        qdrant = get_qdrant()
        collections = qdrant.get_collections().collections
        cols = []
        for col in collections:
            info = qdrant.get_collection(col.name)
            cols.append({
                'name': col.name,
                'points': info.points_count,
                'vectors': info.vectors_count if hasattr(info, 'vectors_count') else info.points_count,
                'dim': info.config.params.vectors.size if hasattr(info.config.params, 'vectors') else info.config.params.size,
                'distance': info.config.params.distance,
            })
        return render_template('database_viewer/index.html', collections=cols)
    except Exception as e:
        return render_template('database_viewer/index.html', error=str(e))

@db_viewer_bp.route('/collection/<name>')
@login_required
def view_collection(name):
    try:
        qdrant = get_qdrant()
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 20, type=int)
        search = request.args.get('search', '')

        offset = (page - 1) * per_page
        scroll = qdrant.scroll(
            collection_name=name,
            limit=per_page,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )
        points, next_offset = scroll

        total = qdrant.get_collection(name).points_count
        col_info = qdrant.get_collection(name)
        dim = col_info.config.params.vectors.size if hasattr(col_info.config.params, 'vectors') else col_info.config.params.size
        distance = col_info.config.params.distance

        return render_template(
            'database_viewer/collection.html',
            name=name,
            points=points,
            total=total,
            page=page,
            per_page=per_page,
            next_offset=next_offset,
            dim=dim,
            distance=distance,
            search=search,
        )
    except Exception as e:
        return render_template('database_viewer/collection.html', error=str(e), name=name)

@db_viewer_bp.route('/api/collection/<name>/search')
@login_required
def api_search_collection(name):
    try:
        qdrant = get_qdrant()
        q = request.args.get('q', '')
        limit = request.args.get('limit', 10, type=int)

        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer('all-MiniLM-L6-v2')
        vec = model.encode(q).tolist()

        results = qdrant.query_points(
            collection_name=name,
            query=vec,
            limit=limit,
            with_payload=True,
        )
        data = []
        for r in results.points:
            data.append({
                'id': r.id,
                'score': round(r.score, 4),
                'payload': r.payload,
            })
        return jsonify({'results': data, 'total': len(data)})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@db_viewer_bp.route('/point/<name>/<path:point_id>')
@login_required
def view_point(name, point_id):
    try:
        qdrant = get_qdrant()
        point_id = int(point_id)
        points = qdrant.retrieve(
            collection_name=name,
            ids=[point_id],
            with_payload=True,
            with_vectors=True,
        )
        if not points:
            return render_template('database_viewer/point.html', error='Point introuvable', name=name, point_id=point_id)
        point = points[0]
        vector = point.vector
        if hasattr(vector, 'tolist'):
            vector = vector.tolist()
        if vector and isinstance(vector, list) and len(vector) > 10:
            vector_display = vector[:10] + [f'... ({len(vector)-10} valeurs masquées)']
        else:
            vector_display = vector
        return render_template('database_viewer/point.html', point=point, vector_display=vector_display, name=name)
    except Exception as e:
        return render_template('database_viewer/point.html', error=str(e), name=name, point_id=point_id)
