#!/usr/bin/env python3
"""
Enrichissement des médicaments avec Mistral
Récupère les données MongoDB, les envoie à Mistral pour enrichissement,
puis les indexe directement dans Qdrant
"""

import os
import sys
import time
from datetime import datetime
from pymongo import MongoClient
from qdrant_client import QdrantClient
from qdrant_client.models import PointStruct, Distance, VectorParams
from sentence_transformers import SentenceTransformer
import logging
import json
from typing import Dict, Any, List
import requests

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Load environment
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '../../.env'))

MISTRAL_API_KEY = os.getenv('MISTRAL_API_KEY', '')
MISTRAL_MODEL = "mistral-small"

class MistralEnricher:
    """Enrichit les médicaments avec Mistral et les indexe dans Qdrant"""
    
    def __init__(self):
        # MongoDB
        mongo_host = os.getenv('MONGO_HOST', '127.0.0.1')
        mongo_port = int(os.getenv('MONGO_PORT', 27018))
        self.mongo_client = MongoClient(mongo_host, mongo_port)
        self.db = self.mongo_client['medicsearch']
        
        # Qdrant
        qdrant_host = os.getenv('QDRANT_HOST', '127.0.0.1')
        qdrant_port = int(os.getenv('QDRANT_PORT', 6333))
        self.qdrant_client = QdrantClient(host=qdrant_host, port=qdrant_port)
        
        # Embedding model
        self.embedding_model = SentenceTransformer('all-MiniLM-L6-v2')
        
        # Mistral API
        self.mistral_api_url = "https://api.mistral.ai/v1/chat/completions"
        self.mistral_headers = {
            "Authorization": f"Bearer {MISTRAL_API_KEY}",
            "Content-Type": "application/json"
        }
    
    def extract_medicine_text(self, medicine: Dict) -> str:
        """Extrait le texte pertinent du document MongoDB"""
        text_parts = []
        
        # Titre
        if medicine.get('title'):
            text_parts.append(f"Médicament: {medicine['title']}")
        
        # Sections disponibles
        if medicine.get('sections'):
            for section in medicine['sections']:
                title = section.get('title', '')
                content = section.get('content', [])
                
                if title and content:
                    # Prendre le premier item si c'est une liste
                    if isinstance(content, list) and len(content) > 0:
                        first_item = content[0]
                        if isinstance(first_item, dict):
                            text = first_item.get('text', '')
                        else:
                            text = str(first_item)
                    else:
                        text = str(content)
                    
                    if text and text != 'Sans objet':
                        text_parts.append(f"{title}: {text[:500]}")
        
        # Détails du médicament
        if medicine.get('medicine_details'):
            details = medicine['medicine_details']
            if details.get('substances_actives'):
                text_parts.append(f"Substances actives: {', '.join(details['substances_actives'])}")
            if details.get('laboratoire'):
                text_parts.append(f"Laboratoire: {details['laboratoire']}")
            if details.get('dosages'):
                text_parts.append(f"Dosages: {', '.join(details['dosages'])}")
            if details.get('forme'):
                text_parts.append(f"Forme: {details['forme']}")
        
        return "\n".join(text_parts)
    
    def enrich_with_mistral(self, medicine_title: str, medicine_text: str) -> Dict[str, Any]:
        """Envoie le texte à Mistral pour enrichissement"""
        try:
            prompt = f"""Analyse ce médicament et extrait les informations clés en JSON:

Médicament: {medicine_title}

Contexte:
{medicine_text}

Retourne un JSON STRICT avec ces champs (ou vide si non applicable):
{{
    "indications": ["indication1", "indication2"],
    "contre_indications": ["contre-indication1"],
    "interactions": ["interaction1"],
    "effets_secondaires": ["effet1", "effet2"],
    "posologie": "description courte",
    "precautions": ["precaution1"],
    "resume": "Résumé clinique court en 1-2 phrases"
}}

Sois TRÈS CONCIS. Retourne UNIQUEMENT le JSON valide, rien d'autre."""

            payload = {
                "model": MISTRAL_MODEL,
                "messages": [
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                "temperature": 0.3,
                "max_tokens": 1000
            }
            
            response = requests.post(
                self.mistral_api_url,
                json=payload,
                headers=self.mistral_headers,
                timeout=30
            )
            
            if response.status_code == 200:
                result = response.json()
                content = result.get('choices', [{}])[0].get('message', {}).get('content', '{}')
                
                # Parse JSON - extract from markdown code blocks if needed
                if '```json' in content:
                    content = content.split('```json')[1].split('```')[0].strip()
                elif '```' in content:
                    content = content.split('```')[1].split('```')[0].strip()
                
                # Try to parse JSON
                try:
                    data = json.loads(content)
                    logger.info(f"✅ Mistral enriched: {medicine_title}")
                    return data
                except json.JSONDecodeError:
                    # If still fails, return empty dict (data still saved with title)
                    logger.debug(f"⚠️  Could not parse JSON for {medicine_title}: {content[:100]}")
                    return {}
            else:
                logger.error(f"❌ Mistral API error: {response.status_code}")
                return {}
        
        except Exception as e:
            logger.error(f"❌ Mistral error for {medicine_title}: {e}")
            return {}
    
    def create_embedding(self, medicine_title: str, enrichment: Dict) -> List[float]:
        """Crée l'embedding pour Qdrant"""
        
        # Combine titre + infos enrichies
        text_parts = [medicine_title]
        
        if enrichment.get('resume'):
            text_parts.append(enrichment['resume'])
        if enrichment.get('indications'):
            text_parts.append(f"Indications: {', '.join(enrichment['indications'][:3])}")
        if enrichment.get('posologie'):
            text_parts.append(f"Posologie: {enrichment['posologie']}")
        
        text = ". ".join(text_parts)
        
        # Génère embedding
        embedding = self.embedding_model.encode(text).tolist()
        return embedding
    
    def save_to_qdrant(self, medicine: Dict, enrichment: Dict) -> bool:
        """Sauvegarde dans Qdrant"""
        try:
            medicine_id = str(medicine['_id'])
            medicine_title = medicine.get('title', '')
            
            # Crée embedding
            embedding = self.create_embedding(medicine_title, enrichment)
            
            # Prépare le payload
            payload = {
                'title': medicine_title,
                'enrichment': enrichment,
                'mongo_id': medicine_id,
                'timestamp': datetime.now().isoformat()
            }
            
            # Crée le point
            point = PointStruct(
                id=hash(medicine_id) % (10 ** 9),
                vector=embedding,
                payload=payload
            )
            
            # Upsert dans Qdrant
            self.qdrant_client.upsert(
                collection_name='medicaments',
                points=[point]
            )
            
            return True
        
        except Exception as e:
            logger.error(f"❌ Qdrant save error: {e}")
            return False
    
    def process_all_medicines(self, limit: int = None):
        """Traite tous les médicaments"""
        
        # Récupère total
        total = self.db.medicines.count_documents({})
        if limit:
            total = min(total, limit)
        
        logger.info(f"\n🚀 Démarrage du traitement de {total} médicaments...")
        logger.info(f"{'='*70}")
        
        # Récupère les médicaments
        query = {}
        cursor = self.db.medicines.find(query)
        if limit:
            cursor = cursor.limit(limit)
        
        processed = 0
        enriched = 0
        failed = 0
        
        for idx, medicine in enumerate(cursor, 1):
            try:
                medicine_title = medicine.get('title')
                
                if not medicine_title:
                    logger.warning(f"[{idx}] Skipping medicine without title")
                    failed += 1
                    continue
                
                # Extrait le texte
                medicine_text = self.extract_medicine_text(medicine)
                
                # Envoie à Mistral
                enrichment = self.enrich_with_mistral(medicine_title, medicine_text)
                
                # Sauvegarde dans Qdrant
                if self.save_to_qdrant(medicine, enrichment):
                    enriched += 1
                
                processed += 1
                
                # Progress tous les 50
                if idx % 50 == 0:
                    logger.info(f"Progress: {idx}/{total} | Enriched: {enriched}")
                
                # Rate limiting
                time.sleep(0.5)
                
            except Exception as e:
                logger.error(f"❌ Error processing {medicine.get('title', 'unknown')}: {e}")
                failed += 1
        
        logger.info(f"{'='*70}")
        logger.info(f"✅ TRAITEMENT TERMINÉ")
        logger.info(f"   Traités:   {processed}/{total}")
        logger.info(f"   Enrichis:  {enriched}/{total}")
        logger.info(f"   Échoués:   {failed}/{total}")
        logger.info(f"   Taux réussite: {(enriched/total)*100:.1f}%")
        logger.info(f"{'='*70}\n")


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='Enrich medicines with Mistral and index in Qdrant')
    parser.add_argument('--limit', type=int, default=None, help='Limit number of medicines to process')
    
    args = parser.parse_args()
    
    if not MISTRAL_API_KEY:
        logger.error("❌ MISTRAL_API_KEY not found in .env")
        sys.exit(1)
    
    enricher = MistralEnricher()
    enricher.process_all_medicines(limit=args.limit)
