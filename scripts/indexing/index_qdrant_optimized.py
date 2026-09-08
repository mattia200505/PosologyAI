#!/usr/bin/env python3
"""
Indexation vectorielle optimisée des médicaments dans Qdrant.

Utilise all-MiniLM-L6-v2 (384d, COSINE) pour la recherche sémantique.
Fusionne le titre, les substances, les formes, les dosages ET les sections
cliniques (indications, posologie, CI, effets) pour des embeddings riches.

Collection cible : "medicines" (compatible avec app.py)
"""

import os
import sys
import json
import time
import hashlib
import argparse
from datetime import datetime, timezone
from pathlib import Path

from pymongo import MongoClient
from qdrant_client import QdrantClient
from qdrant_client.models import (
    PointStruct,
    VectorParams,
    Distance,
    Filter,
    FieldCondition,
    MatchValue,
)
from sentence_transformers import SentenceTransformer
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

logger = None  # will be set after logging config

# ── helpers ──────────────────────────────────────────────────────────────

KEY_SECTIONS = {
    "indications": [
        "indications thrapeutiques",
        "indications",
        "indication",
    ],
    "posologie": [
        "posologie",
        "mode d'administration",
        "dosage",
    ],
    "contre_indications": [
        "contre-indications",
        "contre indication",
    ],
    "effets_indesirables": [
        "effets indsirables",
        "effets secondaires",
    ],
    "mises_en_garde": [
        "mises en garde",
        "prcautions d'emploi",
        "prcautions",
    ],
    "proprietes": [
        "proprits pharmacologiques",
        "proprits pharmacodynamiques",
        "proprits pharmacocintiques",
    ],
}


def extract_text_from_content(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text", "")
                if text:
                    parts.append(str(text))
            elif isinstance(item, str):
                parts.append(item)
        return " ".join(parts)
    return str(content) if content else ""


def extract_section_text(sections, keywords, max_depth=3):
    texts = []
    for section in sections:
        title = section.get("title", "")
        title_lower = title.lower()
        if any(kw in title_lower for kw in keywords):
            raw = section.get("content", "")
            extracted = extract_text_from_content(raw)
            if extracted:
                texts.append(extracted)
        if max_depth > 0:
            sub = section.get("subsections", [])
            if sub:
                sub_text = extract_section_text(sub, keywords, max_depth - 1)
                if sub_text:
                    texts.append(sub_text)
    return " ".join(texts)


def build_embedding_text(medicine):
    title = medicine.get("title") or ""
    details = medicine.get("medicine_details") or {}
    substances = details.get("substances_actives") or []
    forme = details.get("forme") or ""
    laboratoire = details.get("laboratoire") or ""
    dosages = details.get("dosages") or []
    sections = medicine.get("sections") or []

    indications = extract_section_text(sections, KEY_SECTIONS["indications"])
    posologie = extract_section_text(sections, KEY_SECTIONS["posologie"])
    ci = extract_section_text(sections, KEY_SECTIONS["contre_indications"])
    effets = extract_section_text(sections, KEY_SECTIONS["effets_indesirables"])
    warnings = extract_section_text(sections, KEY_SECTIONS["mises_en_garde"])

    subs_str = " ".join(substances) if substances else ""
    dos_str = " ".join(dosages) if dosages else ""

    parts = [
        title,
        title,
        subs_str,
        forme,
        laboratoire,
        dos_str,
        indications,
        posologie,
        ci,
        effets,
        warnings,
    ]
    text = " | ".join(p for p in parts if p)

    return text


def mongo_id_to_qdrant_id(mongo_id):
    h = hashlib.sha256(str(mongo_id).encode()).hexdigest()
    return int(h[:16], 16) % (2**63)


def extract_filter_options(collection):
    substances = set()
    formes = set()
    laboratoires = set()
    dosages = set()

    for doc in collection.find(
        {},
        {
            "medicine_details.substances_actives": 1,
            "medicine_details.forme": 1,
            "medicine_details.laboratoire": 1,
            "medicine_details.dosages": 1,
        },
    ).limit(0):
        pass

    for doc in collection.find(
        {},
        {
            "medicine_details.substances_actives": 1,
            "medicine_details.forme": 1,
            "medicine_details.laboratoire": 1,
            "medicine_details.dosages": 1,
        },
    ):
        details = doc.get("medicine_details") or {}
        for s in details.get("substances_actives") or []:
            if s:
                substances.add(s.strip())
        f = details.get("forme")
        if f:
            formes.add(f.strip())
        l = details.get("laboratoire")
        if l:
            laboratoires.add(l.strip())
        for d in details.get("dosages") or []:
            if d:
                dosages.add(d.strip())

    return {
        "substances": sorted(substances),
        "formes": sorted(formes),
        "laboratoires": sorted(laboratoires),
        "dosages": sorted(dosages),
    }


# ── Indexer ─────────────────────────────────────────────────────────────

class QdrantOptimizedIndexer:
    def __init__(
        self,
        qdrant_host="127.0.0.1",
        qdrant_port=6333,
        qdrant_path=None,
        qdrant_api_key=None,
        qdrant_https=False,
        mongo_host="127.0.0.1",
        mongo_port=27017,
        mongo_db="medicsearch",
        collection_name="medicines",
        batch_size=64,
        model_name="all-MiniLM-L6-v2",
        resume_file=None,
    ):
        self.collection_name = collection_name
        self.batch_size = batch_size
        self.model_name = model_name
        self.resume_file = resume_file

        logger.info(f"Chargement du modèle {model_name}...")
        self.model = SentenceTransformer(model_name)
        self.dim = self.model.get_embedding_dimension()
        logger.info(f"Modèle chargé (dimension: {self.dim})")

        logger.info("Connexion MongoDB...")
        self.mongo = MongoClient(mongo_host, mongo_port, serverSelectionTimeoutMS=5000)
        self.db = self.mongo[mongo_db]
        self.mongo.admin.command("ping")
        logger.info("MongoDB OK")

        if qdrant_path:
            logger.info(f"Connexion Qdrant locale: {qdrant_path}")
            self.qdrant = QdrantClient(path=qdrant_path, timeout=60)
        else:
            logger.info(f"Connexion Qdrant distante: {qdrant_host}:{qdrant_port}")
            self.qdrant = QdrantClient(
                host=qdrant_host,
                port=qdrant_port,
                api_key=qdrant_api_key,
                https=qdrant_https,
                timeout=60,
            )
        self.qdrant.get_collections()
        logger.info("Qdrant OK")

    def _load_indexed_ids(self):
        if not self.resume_file or not os.path.exists(self.resume_file):
            return set()
        with open(self.resume_file, "r") as f:
            data = json.load(f)
        s = set(data.get("indexed_ids", []))
        logger.info(f"Reprise: {len(s)} IDs déjà indexés")
        return s

    def _save_indexed_ids(self, ids):
        if not self.resume_file:
            return
        tmp = self.resume_file + ".tmp"
        with open(tmp, "w") as f:
            json.dump({"indexed_ids": list(ids), "updated_at": datetime.now(timezone.utc).isoformat()}, f)
        os.replace(tmp, self.resume_file)

    def _create_or_get_collection(self):
        try:
            col = self.qdrant.get_collection(self.collection_name)
            logger.info(f"Collection '{self.collection_name}' existe ({col.points_count} points)")
            return col
        except Exception:
            pass

        logger.info(f"Création de la collection '{self.collection_name}'...")
        self.qdrant.create_collection(
            collection_name=self.collection_name,
            vectors_config=VectorParams(size=self.dim, distance=Distance.COSINE),
        )
        logger.info("Collection créée")
        return self.qdrant.get_collection(self.collection_name)

    def index_all(self, limit=None):
        self._create_or_get_collection()

        indexed_ids = self._load_indexed_ids()
        total = self.db.medicines.count_documents({})
        if limit:
            total = min(total, limit)
        logger.info(f"Total documents MongoDB: {total}")

        cursor = self.db.medicines.find({})
        if limit:
            cursor = cursor.limit(limit)

        points = []
        processed = 0
        skipped = 0
        errors = 0
        batch_num = 0
        t0 = time.perf_counter()

        for doc in cursor:
            mongo_id = str(doc.get("_id"))

            if mongo_id in indexed_ids:
                skipped += 1
                if skipped % 1000 == 0:
                    logger.info(f"  skip {skipped} déjà indexés")
                continue

            try:
                text = build_embedding_text(doc)
                if not text.strip():
                    text = doc.get("title", "Unknown")

                embedding = self.model.encode(text, show_progress_bar=False).tolist()

                details = doc.get("medicine_details") or {}

                doc_sections = doc.get("sections") or []
                indications = doc.get("indications", "")
                if isinstance(indications, list):
                    indications = " ".join(indications)
                if not indications:
                    indications = extract_section_text(doc_sections, KEY_SECTIONS["indications"])
                ci = extract_section_text(doc_sections, KEY_SECTIONS["contre_indications"])
                effets = extract_section_text(doc_sections, KEY_SECTIONS["effets_indesirables"])

                point = PointStruct(
                    id=mongo_id_to_qdrant_id(mongo_id),
                    vector=embedding,
                    payload={
                        "mongo_id": mongo_id,
                        "title": doc.get("title", ""),
                        "substances_actives": details.get("substances_actives") or [],
                        "forme": details.get("forme") or "",
                        "laboratoire": details.get("laboratoire") or "",
                        "dosages": details.get("dosages") or [],
                        "url": doc.get("url", ""),
                        "groupe_anatomique": doc.get("groupe_anatomique") or "",
                        "type_medicament": doc.get("type_medicament") or "",
                        "indications": indications[:500] if indications else "",
                        "contre_indications": ci[:500] if ci else "",
                        "effets_indesirables": effets[:500] if effets else "",
                        "indexed_at": datetime.now(timezone.utc).isoformat(),
                    },
                )
                points.append(point)
                processed += 1

                if len(points) >= self.batch_size:
                    batch_num += 1
                    self.qdrant.upsert(
                        collection_name=self.collection_name,
                        points=points,
                        wait=True,
                    )
                    indexed_ids.update(
                        p.payload["mongo_id"] for p in points
                    )
                    logger.info(
                        f"Batch {batch_num}: {len(points)} points upserted "
                        f"(total: {processed}, skipped: {skipped}, errors: {errors}, "
                        f"time: {time.perf_counter()-t0:.1f}s)"
                    )
                    self._save_indexed_ids(indexed_ids)
                    points = []

            except Exception as e:
                errors += 1
                logger.error(f"Erreur sur {doc.get('title','?')}: {e}")
                if errors > 20:
                    logger.error("Trop d'erreurs, abandon")
                    break
                continue

        if points:
            batch_num += 1
            self.qdrant.upsert(
                collection_name=self.collection_name,
                points=points,
                wait=True,
            )
            indexed_ids.update(p.payload["mongo_id"] for p in points)
            logger.info(f"Batch final {batch_num}: {len(points)} points upserted")
            self._save_indexed_ids(indexed_ids)

        elapsed = time.perf_counter() - t0
        col = self.qdrant.get_collection(self.collection_name)

        logger.info("=" * 60)
        logger.info("INDEXATION TERMINÉE")
        logger.info("=" * 60)
        logger.info(f"  Collection:          {self.collection_name}")
        logger.info(f"  Points dans Qdrant:  {col.points_count}")
        logger.info(f"  Nouveaux indexés:    {processed}")
        logger.info(f"  Déjà indexés (skip): {skipped}")
        logger.info(f"  Erreurs:             {errors}")
        logger.info(f"  Temps total:         {elapsed:.1f}s")
        logger.info(f"  Vitesse:             {processed/max(elapsed,0.01):.1f} docs/s")
        logger.info("=" * 60)

        return processed, skipped, errors

    def verify_search(self, query="douleur", top_k=5):
        logger.info(f"\nVérification: recherche de '{query}'...")
        vec = self.model.encode(query).tolist()
        results = self.qdrant.query_points(
            collection_name=self.collection_name,
            query=vec,
            limit=top_k,
            with_payload=True,
        )
        logger.info(f"Top {top_k} résultats:")
        for i, r in enumerate(results.points):
            payload = r.payload or {}
            logger.info(
                f"  {i+1}. score={r.score:.4f} | {payload.get('title','?')} "
                f"| labo: {payload.get('laboratoire','?')}"
            )
        logger.info("")

    def export_filters(self, output_path=None):
        logger.info("Extraction des options de filtre depuis MongoDB...")
        filters = extract_filter_options(self.db.medicines)
        logger.info(
            f"  substances: {len(filters['substances'])} | "
            f"formes: {len(filters['formes'])} | "
            f"laboratoires: {len(filters['laboratoires'])} | "
            f"dosages: {len(filters['dosages'])}"
        )
        if output_path:
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(filters, f, ensure_ascii=False, indent=2)
            logger.info(f"Options exportées vers {output_path}")
        return filters


# ── CLI ─────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Indexation vectorielle optimisée des médicaments dans Qdrant"
    )

    g_conn = parser.add_argument_group("Connexion Qdrant")
    g_conn.add_argument("--host", default=None, help="Hôte Qdrant (défaut: 127.0.0.1)")
    g_conn.add_argument("--port", type=int, default=None, help="Port Qdrant (défaut: 6333)")
    g_conn.add_argument("--path", default=None, help="Chemin stockage local Qdrant (mode local, pas de serveur)")
    g_conn.add_argument("--api-key", default=None, help="Clé API Qdrant Cloud")
    g_conn.add_argument("--https", action="store_true", help="HTTPS pour Qdrant Cloud")

    g_data = parser.add_argument_group("Données")
    g_data.add_argument("--mongo-host", default=None, help="Hôte MongoDB")
    g_data.add_argument("--mongo-port", type=int, default=None, help="Port MongoDB")
    g_data.add_argument("--collection", default="medicines", help="Nom collection Qdrant")
    g_data.add_argument("--limit", type=int, default=None, help="Limiter le nombre de documents")
    g_data.add_argument("--batch-size", type=int, default=64, help="Taille des lots (défaut: 64)")

    g_other = parser.add_argument_group("Autres")
    g_other.add_argument("--resume", default=None, help="Fichier JSON pour reprise (défaut: auto)")
    g_other.add_argument("--no-resume", action="store_true", help="Ignorer la reprise, réindexer tout")
    g_other.add_argument("--verify", type=str, default=None, nargs="?", const="douleur",
                         help="Recherche de vérification après indexation")
    g_other.add_argument("--export-filters", default=None,
                         help="Exporter les options de filtre vers un fichier JSON")
    g_other.add_argument("--model", default="all-MiniLM-L6-v2",
                         help="Modèle SentenceTransformer")

    args = parser.parse_args()

    # Logging
    global logger
    import logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    logger = logging.getLogger("index_qdrant")

    host = args.host or os.getenv("QDRANT_HOST", "127.0.0.1")
    port = args.port or int(os.getenv("QDRANT_PORT", "6333"))
    path = args.path or os.getenv("QDRANT_PATH")
    api_key = args.api_key or os.getenv("QDRANT_API_KEY")
    https = args.https or os.getenv("QDRANT_HTTPS", "").lower() == "true"

    mongo_host = args.mongo_host or os.getenv("MONGO_HOST", "127.0.0.1")
    mongo_port = args.mongo_port or int(os.getenv("MONGO_PORT", "27017"))

    # Resume file
    resume_file = args.resume
    if resume_file is None and not args.no_resume:
        resume_file = str(Path(__file__).with_name(f".indexed_{args.collection}.json"))

    indexer = QdrantOptimizedIndexer(
        qdrant_host=host,
        qdrant_port=port,
        qdrant_path=path,
        qdrant_api_key=api_key,
        qdrant_https=https,
        mongo_host=mongo_host,
        mongo_port=mongo_port,
        collection_name=args.collection,
        batch_size=args.batch_size,
        model_name=args.model,
        resume_file=resume_file if not args.no_resume else None,
    )

    n, skipped, errors = indexer.index_all(limit=args.limit)

    if args.verify and n > 0:
        indexer.verify_search(args.verify)

    if args.export_filters:
        indexer.export_filters(args.export_filters)

    return 0 if errors == 0 and n > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
