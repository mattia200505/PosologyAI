#!/usr/bin/env python3
"""
Version simplifiée: MongoDB → Mistral → MongoDB + Qdrant
Sans web scraping (plus fiable et rapide)
"""

import os
import sys
import time
import json
import logging
from datetime import datetime
from typing import Dict, Any, List
from pymongo import MongoClient
from qdrant_client import QdrantClient
from qdrant_client.models import PointStruct
from sentence_transformers import SentenceTransformer
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


class SimpleMistralEnricher:
    """Enrichit avec Mistral et sauvegarde dans MongoDB + Qdrant"""
    
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
            for section in medicine['sections'][:12]:  # Limiter aux 12 premières sections
                title = section.get('title', '')
                content = section.get('content', [])
                
                if title and content:
                    if isinstance(content, list) and len(content) > 0:
                        first_item = content[0]
                        if isinstance(first_item, dict):
                            text = first_item.get('text', '')
                        else:
                            text = str(first_item)
                    else:
                        text = str(content)
                    
                    if text and text.strip() not in ['Sans objet', 'Sans objet.']:
                        text_parts.append(f"{title}: {text[:300]}")
        
        # Détails du médicament
        if medicine.get('medicine_details'):
            details = medicine['medicine_details']
            if details.get('substances_actives'):
                text_parts.append(f"Substances actives: {', '.join(details['substances_actives'][:5])}")
            if details.get('laboratoire'):
                text_parts.append(f"Laboratoire: {details['laboratoire']}")
            if details.get('dosages'):
                text_parts.append(f"Dosages: {', '.join(details['dosages'][:3])}")
            if details.get('forme'):
                text_parts.append(f"Forme: {details['forme']}")
        
        return "\n".join(text_parts)
    
    def enrich_with_mistral(self, medicine_name: str, medicine_text: str) -> Dict[str, Any]:
        """Envoie à Mistral pour enrichissement"""
        try:
            prompt = f"""Tu es un expert pharmaceutique. Basé sur les informations suivantes sur le médicament '{medicine_name}',
            extrais et synthétise les informations médicales essentielles.
            
            INFORMATIONS DISPONIBLES:
            {medicine_text}
            
            Retourne UNIQUEMENT un JSON structuré (pas de markdown) avec ces champs:
            {{
                "indications": "Les indications principales",
                "contre_indications": "Les contre-indications essentielles",
                "interactions": "Les interactions médicamenteuses importantes",
                "effets_secondaires": "Les effets secondaires courants",
                "posologie": "La posologie recommandée",
                "precautions": "Précautions d'emploi",
                "resume_clinique": "Un résumé de 2-3 phrases"
            }}"""
            
            payload = {
                "model": MISTRAL_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.5,
                "max_tokens": 1500
            }
            
            response = requests.post(
                self.mistral_api_url,
                json=payload,
                headers=self.mistral_headers,
                timeout=30
            )
            
            if response.status_code == 200:
                result = response.json()
                content = result['choices'][0]['message']['content'].strip()
                
                # Parse JSON - handle markdown
                if '```json' in content:
                    content = content.split('```json')[1].split('```')[0].strip()
                elif '```' in content:
                    content = content.split('```')[1].split('```')[0].strip()
                
                enrichment = json.loads(content)
                return enrichment
            else:
                logger.warning(f"⚠️  Mistral error {response.status_code}")
                return self._default_enrichment()
        
        except json.JSONDecodeError as e:
            logger.warning(f"⚠️  JSON parse error: {e}")
            return self._default_enrichment()
        except Exception as e:
            logger.error(f"❌ Error: {e}")
            return self._default_enrichment()
    
    def _default_enrichment(self) -> Dict[str, Any]:
        """Enrichissement par défaut"""
        return {
            "indications": "À déterminer",
            "contre_indications": "À déterminer",
            "interactions": "À déterminer",
            "effets_secondaires": "À déterminer",
            "posologie": "À déterminer",
            "precautions": "À déterminer",
            "resume_clinique": "Données insuffisantes"
        }
    
    def create_embedding(self, medicine: Dict[str, Any]) -> List[float]:
        """Crée le vecteur d'embedding"""
        enrichment = medicine.get('enrichment', {})
        
        text_parts = [
            medicine.get('title', ''),
            enrichment.get('indications', ''),
            enrichment.get('resume_clinique', '')
        ]
        
        combined = " ".join([str(t) for t in text_parts if t]).strip()
        combined = combined or medicine.get('title', 'medicine')
        
        return self.embedding_model.encode(combined, convert_to_tensor=False).tolist()
    
    def save_to_qdrant(self, medicine: Dict[str, Any], vector: List[float]) -> bool:
        """Sauvegarde dans Qdrant"""
        try:
            point_id = hash(str(medicine.get('_id', ''))) % (2**31)
            
            point = PointStruct(
                id=point_id,
                vector=vector,
                payload={
                    "title": medicine.get('title', ''),
                    "enrichment": medicine.get('enrichment', {}),
                    "mongo_id": str(medicine.get('_id', '')),
                    "enriched_at": datetime.now().isoformat()
                }
            )
            
            self.qdrant_client.upsert(
                collection_name="medicaments",
                points=[point]
            )
            return True
        except Exception as e:
            logger.error(f"❌ Qdrant error: {e}")
            return False
    
    def save_to_mongodb(self, medicine_id: Any, enrichment: Dict[str, Any]) -> bool:
        """Sauvegarde dans MongoDB"""
        try:
            self.db.medicines.update_one(
                {"_id": medicine_id},
                {
                    "$set": {
                        "enrichment": enrichment,
                        "enrichment_date": datetime.now()
                    }
                }
            )
            return True
        except Exception as e:
            logger.error(f"❌ MongoDB error: {e}")
            return False
    
    def process_medicine(self, medicine: Dict[str, Any]) -> bool:
        """Traite un médicament"""
        medicine_name = medicine.get('title', '')
        
        if not medicine_name:
            return False
        
        try:
            # Extrait le texte
            medicine_text = self.extract_medicine_text(medicine)
            
            if not medicine_text.strip():
                return False
            
            # Enrichit avec Mistral
            enrichment = self.enrich_with_mistral(medicine_name, medicine_text)
            
            # Sauvegarde MongoDB
            if not self.save_to_mongodb(medicine.get('_id'), enrichment):
                return False
            
            # Ajoute l'enrichissement au document
            medicine['enrichment'] = enrichment
            
            # Crée embedding et sauvegarde Qdrant
            vector = self.create_embedding(medicine)
            if not self.save_to_qdrant(medicine, vector):
                return False
            
            return True
        
        except Exception as e:
            logger.error(f"❌ Error: {e}")
            return False


def main():
    import argparse
    
    parser = argparse.ArgumentParser()
    parser.add_argument('--limit', type=int, default=None)
    args = parser.parse_args()
    
    logger.info("=" * 70)
    logger.info("🚀 MISTRAL ENRICHMENT → MONGODB + QDRANT (SIMPLE VERSION)")
    logger.info("=" * 70)
    
    try:
        enricher = SimpleMistralEnricher()
        
        # Récupère les médicaments
        medicines = list(enricher.db.medicines.find({}))
        if args.limit:
            medicines = medicines[:args.limit]
        
        total = len(medicines)
        processed = 0
        enriched = 0
        
        logger.info(f"📋 Total medicines: {total}\n")
        
        for idx, medicine in enumerate(medicines, 1):
            try:
                if enricher.process_medicine(medicine):
                    enriched += 1
                
                processed += 1
                
                if idx % 10 == 0 or idx == total:
                    pct = (processed/total)*100
                    logger.info(f"📊 {processed}/{total} ({pct:.1f}%) - Success: {enriched}/{processed}")
                
                # Rate limiting pour Mistral
                time.sleep(1)
            
            except Exception as e:
                logger.error(f"Error: {e}")
                processed += 1
        
        # Résumé
        logger.info("\n" + "=" * 70)
        logger.info("✅ COMPLETE")
        logger.info(f"   Processed: {processed}/{total}")
        logger.info(f"   Enriched: {enriched}/{total}")
        logger.info(f"   Success rate: {(enriched/total)*100:.1f}%")
        logger.info("=" * 70)
    
    except Exception as e:
        logger.error(f"Fatal: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
