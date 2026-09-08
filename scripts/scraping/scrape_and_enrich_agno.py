#!/usr/bin/env python3
"""
Scrape des sources médicales (ANSM, HAS, Thériaque, DrugBank) via Agno
Enrichissement avec Mistral
Enregistrement dans MongoDB et Qdrant
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
from concurrent.futures import ThreadPoolExecutor, as_completed

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
AGNO_API_KEY = os.getenv('AGNO_API_KEY', '')


class AgnoScraper:
    """Scrape les données médicales via Agno"""
    
    def __init__(self):
        self.agno_base_url = "https://api.agno.ai/v1"
        self.headers = {
            "Authorization": f"Bearer {AGNO_API_KEY}",
            "Content-Type": "application/json"
        }
    
    def scrape_ansm(self, medicine_name: str) -> Dict[str, Any]:
        """Scrape la base ANSM (Agence Nationale de Sécurité du Médicament)"""
        try:
            payload = {
                "query": f"Information ANSM sur {medicine_name}",
                "source": "https://ansm.sante.fr/",
                "max_results": 3,
                "language": "fr"
            }
            response = requests.post(
                f"{self.agno_base_url}/search",
                json=payload,
                headers=self.headers,
                timeout=10
            )
            if response.status_code == 200:
                return response.json()
        except Exception as e:
            logger.warning(f"ANSM scrape failed for {medicine_name}: {e}")
        return {}
    
    def scrape_has(self, medicine_name: str) -> Dict[str, Any]:
        """Scrape la base HAS (Haute Autorité de Santé)"""
        try:
            payload = {
                "query": f"Recommandations HAS {medicine_name}",
                "source": "https://has-sante.fr/",
                "max_results": 3,
                "language": "fr"
            }
            response = requests.post(
                f"{self.agno_base_url}/search",
                json=payload,
                headers=self.headers,
                timeout=10
            )
            if response.status_code == 200:
                return response.json()
        except Exception as e:
            logger.warning(f"HAS scrape failed for {medicine_name}: {e}")
        return {}
    
    def scrape_theriaque(self, medicine_name: str) -> Dict[str, Any]:
        """Scrape Thériaque"""
        try:
            payload = {
                "query": f"Fiche Thériaque {medicine_name}",
                "source": "https://theriaque.org/",
                "max_results": 3,
                "language": "fr"
            }
            response = requests.post(
                f"{self.agno_base_url}/search",
                json=payload,
                headers=self.headers,
                timeout=10
            )
            if response.status_code == 200:
                return response.json()
        except Exception as e:
            logger.warning(f"Thériaque scrape failed for {medicine_name}: {e}")
        return {}
    
    def scrape_drugbank(self, medicine_name: str) -> Dict[str, Any]:
        """Scrape DrugBank"""
        try:
            payload = {
                "query": f"DrugBank information {medicine_name}",
                "source": "https://www.drugbank.ca/",
                "max_results": 3,
                "language": "en"
            }
            response = requests.post(
                f"{self.agno_base_url}/search",
                json=payload,
                headers=self.headers,
                timeout=10
            )
            if response.status_code == 200:
                return response.json()
        except Exception as e:
            logger.warning(f"DrugBank scrape failed for {medicine_name}: {e}")
        return {}
    
    def scrape_all_sources(self, medicine_name: str) -> Dict[str, Any]:
        """Scrape toutes les sources pour un médicament"""
        logger.info(f"🔍 Scraping {medicine_name} from all sources...")
        
        scraped_data = {
            "ansm": self.scrape_ansm(medicine_name),
            "has": self.scrape_has(medicine_name),
            "theriaque": self.scrape_theriaque(medicine_name),
            "drugbank": self.scrape_drugbank(medicine_name)
        }
        
        return scraped_data


class MistralEnricher:
    """Enrichit les données scrapées avec Mistral"""
    
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
    
    def enrich_with_mistral(self, medicine_name: str, scraped_data: Dict[str, Any]) -> Dict[str, Any]:
        """Envoie les données scrapées à Mistral pour enrichissement"""
        try:
            # Préparer le contexte avec les données scrapées
            context = self._prepare_context(medicine_name, scraped_data)
            
            prompt = f"""Basé sur les informations scrapées ci-dessous sur le médicament '{medicine_name}', 
            extrais et synthetise les informations médicales essentielles.
            
            Données scrapées:
            {context}
            
            Retourne un JSON structuré avec les champs suivants:
            {{
                "indications": "Les indications principales du médicament",
                "contre_indications": "Les contre-indications essentielles",
                "interactions": "Les interactions médicamenteuses principales",
                "effets_secondaires": "Les effets secondaires les plus courants",
                "posologie": "La posologie recommandée",
                "precautions": "Les précautions d'emploi",
                "sources": {{"ansm": bool, "has": bool, "theriaque": bool, "drugbank": bool}},
                "resume": "Un résumé clinique du médicament"
            }}
            
            Retourne UNIQUEMENT le JSON, sans markdown ni explication."""
            
            payload = {
                "model": MISTRAL_MODEL,
                "messages": [
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                "temperature": 0.5,
                "max_tokens": 2000
            }
            
            response = requests.post(
                self.mistral_api_url,
                json=payload,
                headers=self.mistral_headers,
                timeout=30
            )
            
            if response.status_code == 200:
                result = response.json()
                content = result['choices'][0]['message']['content']
                
                # Parse JSON - handle markdown code blocks
                if '```json' in content:
                    content = content.split('```json')[1].split('```')[0].strip()
                elif '```' in content:
                    content = content.split('```')[1].split('```')[0].strip()
                
                enrichment = json.loads(content)
                logger.info(f"✅ Enriched {medicine_name} with Mistral")
                return enrichment
            else:
                logger.warning(f"Mistral API error: {response.status_code}")
                return self._default_enrichment()
        
        except json.JSONDecodeError as e:
            logger.warning(f"JSON parsing error for {medicine_name}: {e}")
            return self._default_enrichment()
        except Exception as e:
            logger.error(f"Enrichment failed for {medicine_name}: {e}")
            return self._default_enrichment()
    
    def _prepare_context(self, medicine_name: str, scraped_data: Dict[str, Any]) -> str:
        """Prépare le contexte pour Mistral"""
        context_parts = []
        
        for source, data in scraped_data.items():
            if data:
                context_parts.append(f"\n{source.upper()}:")
                if isinstance(data, dict):
                    context_parts.append(json.dumps(data, ensure_ascii=False, indent=2)[:1000])
                else:
                    context_parts.append(str(data)[:1000])
        
        return "\n".join(context_parts) if context_parts else "Aucune donnée disponible"
    
    def _default_enrichment(self) -> Dict[str, Any]:
        """Retourne un enrichissement par défaut en cas d'erreur"""
        return {
            "indications": "Information non disponible",
            "contre_indications": "Information non disponible",
            "interactions": "Information non disponible",
            "effets_secondaires": "Information non disponible",
            "posologie": "Information non disponible",
            "precautions": "Information non disponible",
            "sources": {"ansm": False, "has": False, "theriaque": False, "drugbank": False},
            "resume": "Enrichissement échoué"
        }
    
    def create_embedding(self, medicine_data: Dict[str, Any]) -> List[float]:
        """Crée le vecteur d'embedding"""
        text_parts = [
            medicine_data.get('title', ''),
            medicine_data.get('enrichment', {}).get('indications', ''),
            medicine_data.get('enrichment', {}).get('resume', '')
        ]
        
        combined_text = " ".join([str(t) for t in text_parts if t])
        
        if not combined_text.strip():
            combined_text = medicine_data.get('title', 'medicine')
        
        embedding = self.embedding_model.encode(combined_text, convert_to_tensor=False)
        return embedding.tolist()
    
    def save_to_qdrant(self, medicine_data: Dict[str, Any], vector: List[float]) -> bool:
        """Sauvegarde le médicament enrichi dans Qdrant"""
        try:
            point_id = hash(medicine_data.get('_id', '')) % (2**31)
            
            point = PointStruct(
                id=point_id,
                vector=vector,
                payload={
                    "title": medicine_data.get('title', ''),
                    "enrichment": medicine_data.get('enrichment', {}),
                    "mongo_id": str(medicine_data.get('_id', '')),
                    "timestamp": datetime.utcnow().isoformat()
                }
            )
            
            self.qdrant_client.upsert(
                collection_name="medicaments",
                points=[point]
            )
            
            return True
        except Exception as e:
            logger.error(f"Qdrant save failed: {e}")
            return False
    
    def save_to_mongodb(self, medicine_id: Any, enrichment: Dict[str, Any]) -> bool:
        """Sauvegarde l'enrichissement dans MongoDB"""
        try:
            self.db.medicines.update_one(
                {"_id": medicine_id},
                {
                    "$set": {
                        "enrichment": enrichment,
                        "enrichment_timestamp": datetime.utcnow()
                    }
                }
            )
            return True
        except Exception as e:
            logger.error(f"MongoDB save failed: {e}")
            return False
    
    def process_medicine(self, medicine: Dict[str, Any], scraper: AgnoScraper) -> bool:
        """Traite un médicament: scrape + enrichit + sauvegarde"""
        try:
            medicine_id = medicine.get('_id')
            medicine_name = medicine.get('title', '')
            
            if not medicine_name:
                return False
            
            # Scraper les données
            scraped_data = scraper.scrape_all_sources(medicine_name)
            
            # Enrichir avec Mistral
            enrichment = self.enrich_with_mistral(medicine_name, scraped_data)
            
            # Ajouter l'enrichissement au document
            medicine['enrichment'] = enrichment
            
            # Sauvegarder dans MongoDB
            if not self.save_to_mongodb(medicine_id, enrichment):
                logger.warning(f"Failed to save {medicine_name} to MongoDB")
                return False
            
            # Créer l'embedding
            vector = self.create_embedding(medicine)
            
            # Sauvegarder dans Qdrant
            if not self.save_to_qdrant(medicine, vector):
                logger.warning(f"Failed to save {medicine_name} to Qdrant")
                return False
            
            logger.info(f"✨ Processed {medicine_name} successfully")
            return True
        
        except Exception as e:
            logger.error(f"Error processing medicine: {e}")
            return False


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='Scrape et enrichit les médicaments')
    parser.add_argument('--limit', type=int, default=None, help='Limite de médicaments à traiter')
    args = parser.parse_args()
    
    logger.info("=" * 70)
    logger.info("🚀 SCRAPE & ENRICH WITH AGNO + MISTRAL")
    logger.info("=" * 70)
    
    try:
        # Initialiser les services
        scraper = AgnoScraper()
        enricher = MistralEnricher()
        
        # Récupérer les médicaments
        medicines = list(enricher.db.medicines.find({}))
        
        if args.limit:
            medicines = medicines[:args.limit]
        
        total = len(medicines)
        processed = 0
        enriched = 0
        failed = 0
        
        logger.info(f"📋 Found {total} medicines to process")
        logger.info("=" * 70)
        
        # Traiter chaque médicament
        for idx, medicine in enumerate(medicines, 1):
            try:
                if enricher.process_medicine(medicine, scraper):
                    enriched += 1
                    processed += 1
                else:
                    failed += 1
                    processed += 1
                
                # Afficher la progression tous les 10 médicaments
                if idx % 10 == 0 or idx == total:
                    logger.info(f"Progress: {processed}/{total} medicines ({(processed/total)*100:.1f}%)")
                
                # Rate limiting pour éviter le throttling
                time.sleep(1)
            
            except Exception as e:
                logger.error(f"Error processing medicine {idx}: {e}")
                failed += 1
                processed += 1
        
        # Résumé final
        logger.info("=" * 70)
        logger.info("✅ PROCESSING COMPLETE")
        logger.info(f"   Total processed: {processed}/{total}")
        logger.info(f"   Successfully enriched: {enriched}/{total}")
        logger.info(f"   Failed: {failed}/{total}")
        logger.info(f"   Success rate: {(enriched/total)*100:.1f}%")
        logger.info("=" * 70)
    
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
