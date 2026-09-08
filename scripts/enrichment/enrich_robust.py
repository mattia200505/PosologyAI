#!/usr/bin/env python3
"""
Enrichissement Mistral ROBUSTE avec gestion des erreurs et reprise
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


class RobustMistralEnricher:
    """Enrichit avec Mistral - VERSION ROBUSTE avec reprise"""
    
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
            for section in medicine['sections'][:12]:
                try:
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
                except Exception as e:
                    logger.debug(f"Section error: {e}")
                    continue
        
        # Détails du médicament
        if medicine.get('medicine_details'):
            try:
                details = medicine['medicine_details']
                if details.get('substances_actives'):
                    text_parts.append(f"Substances actives: {', '.join(str(s) for s in details['substances_actives'][:5])}")
                if details.get('laboratoire'):
                    text_parts.append(f"Laboratoire: {details['laboratoire']}")
                if details.get('dosages'):
                    text_parts.append(f"Dosages: {', '.join(str(d) for d in details['dosages'][:3])}")
                if details.get('forme'):
                    text_parts.append(f"Forme: {details['forme']}")
            except Exception as e:
                logger.debug(f"Details error: {e}")
        
        return "\n".join(text_parts)
    
    def enrich_with_mistral(self, medicine_name: str, medicine_text: str) -> Dict[str, Any]:
        """Envoie à Mistral pour enrichissement avec retry"""
        max_retries = 3
        for attempt in range(max_retries):
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
                elif response.status_code == 429:
                    # Rate limit - attendre et réessayer
                    wait_time = 2 ** attempt  # Exponential backoff
                    logger.warning(f"Rate limit - attendant {wait_time}s (tentative {attempt+1}/{max_retries})")
                    time.sleep(wait_time)
                    continue
                else:
                    logger.warning(f"Mistral error {response.status_code}: {response.text[:200]}")
                    return self._default_enrichment()
            
            except json.JSONDecodeError as e:
                logger.warning(f"JSON parse error: {e}")
                return self._default_enrichment()
            except requests.exceptions.Timeout:
                if attempt < max_retries - 1:
                    logger.warning(f"Timeout - réessai {attempt+1}/{max_retries}")
                    time.sleep(2 ** attempt)
                    continue
                else:
                    return self._default_enrichment()
            except Exception as e:
                logger.error(f"Error: {e}")
                return self._default_enrichment()
        
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
        try:
            enrichment = medicine.get('enrichment', {})
            
            text_parts = [
                medicine.get('title', ''),
                enrichment.get('indications', ''),
                enrichment.get('resume_clinique', '')
            ]
            
            combined = " ".join([str(t) for t in text_parts if t]).strip()
            combined = combined or medicine.get('title', 'medicine')
            
            return self.embedding_model.encode(combined, convert_to_tensor=False).tolist()
        except Exception as e:
            logger.error(f"Embedding error: {e}")
            return [0.0] * 384  # Vecteur par défaut
    
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
            logger.error(f"Qdrant error: {e}")
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
            logger.error(f"MongoDB error: {e}")
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
            logger.error(f"Process error: {e}")
            return False


def main():
    import argparse
    
    parser = argparse.ArgumentParser()
    parser.add_argument('--limit', type=int, default=None)
    parser.add_argument('--resume', action='store_true', help='Continuer depuis où ça s\'était arrêté')
    args = parser.parse_args()
    
    logger.info("=" * 70)
    logger.info("🚀 MISTRAL ENRICHMENT ROBUSTE (AVEC REPRISE)")
    logger.info("=" * 70)
    
    try:
        enricher = RobustMistralEnricher()
        
        # Récupère les médicaments
        if args.resume:
            # Reprendre depuis les non-enrichis
            medicines = list(enricher.db.medicines.find({"enrichment": {"$exists": False}}))
            logger.info("📋 Mode REPRISE - enrichissement des médicaments manquants")
        else:
            medicines = list(enricher.db.medicines.find({}))
            logger.info("📋 Mode COMPLET - enrichissement de tous les médicaments")
        
        if args.limit:
            medicines = medicines[:args.limit]
        
        total = len(medicines)
        processed = 0
        enriched = 0
        failed = 0
        
        logger.info(f"📊 Total à traiter: {total:,} médicaments\n")
        
        start_time = time.time()
        
        for idx, medicine in enumerate(medicines, 1):
            try:
                if enricher.process_medicine(medicine):
                    enriched += 1
                else:
                    failed += 1
                
                processed += 1
                
                if idx % 50 == 0 or idx == total:
                    elapsed = time.time() - start_time
                    speed = processed / elapsed if elapsed > 0 else 0
                    pct = (processed/total)*100
                    remaining = total - processed
                    eta = remaining / speed if speed > 0 else 0
                    
                    eta_str = f"{int(eta/60)}m {int(eta%60)}s" if eta > 0 else "?"
                    
                    logger.info(f"📊 {processed:,}/{total:,} ({pct:.1f}%) - Success: {enriched:,} - ETA: {eta_str}")
                
                # Rate limiting pour Mistral (éviter throttling)
                time.sleep(0.7)
            
            except KeyboardInterrupt:
                logger.warning("\n\n⚠️  Interruption - sauvegarde en cours...")
                break
            except Exception as e:
                logger.error(f"Fatal error: {e}")
                failed += 1
                processed += 1
        
        # Résumé final
        total_time = time.time() - start_time
        logger.info("\n" + "=" * 70)
        logger.info("✅ ENRICHISSEMENT TERMINÉ")
        logger.info(f"   Temps total: {int(total_time/60)}m {int(total_time%60)}s")
        logger.info(f"   Traités: {processed:,}/{total:,}")
        logger.info(f"   Succès: {enriched:,}/{total:,}")
        logger.info(f"   Échecs: {failed:,}/{total:,}")
        logger.info(f"   Taux réussite: {(enriched/total*100):.1f}%")
        logger.info("=" * 70)
        
        # Vérification finale
        total_enriched = enricher.db.medicines.count_documents({"enrichment": {"$exists": True}})
        logger.info(f"\n📊 Vérification MongoDB: {total_enriched:,}/9804 médicaments enrichis")
        
        return 0 if enriched == total else 1
    
    except Exception as e:
        logger.error(f"Fatal: {e}")
        sys.exit(1)


if __name__ == "__main__":
    sys.exit(main())
