#!/usr/bin/env python3
"""
Scrape réel des sources médicales (ANSM, HAS, Thériaque, DrugBank)
Enrichissement avec Mistral
Enregistrement dans MongoDB et Qdrant
"""

import os
import sys
import time
import json
import logging
import requests
from datetime import datetime
from typing import Dict, Any, List
from pymongo import MongoClient
from qdrant_client import QdrantClient
from qdrant_client.models import PointStruct
from sentence_transformers import SentenceTransformer
from bs4 import BeautifulSoup
import urllib.parse

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


class MedicalSourcesScraper:
    """Scrape les données médicales depuis plusieurs sources"""
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        self.timeout = 10
    
    def scrape_ansm(self, medicine_name: str) -> Dict[str, Any]:
        """Scrape la base ANSM"""
        try:
            logger.info(f"  📍 ANSM: {medicine_name}")
            
            # Recherche ANSM
            search_url = f"https://ansm.sante.fr/recherche?query={urllib.parse.quote(medicine_name)}"
            response = self.session.get(search_url, timeout=self.timeout)
            response.encoding = 'utf-8'
            
            if response.status_code == 200:
                soup = BeautifulSoup(response.content, 'html.parser')
                
                # Essayer d'extraire les résultats
                results = []
                result_divs = soup.find_all('div', class_='search-result')
                
                for div in result_divs[:3]:
                    title = div.find('h3')
                    text = div.find('p')
                    if title and text:
                        results.append({
                            "title": title.get_text(strip=True),
                            "text": text.get_text(strip=True)[:500]
                        })
                
                return {
                    "status": "success" if results else "no_results",
                    "data": results,
                    "url": search_url
                }
        except Exception as e:
            logger.debug(f"    ANSM error: {e}")
        
        return {"status": "failed", "data": []}
    
    def scrape_has(self, medicine_name: str) -> Dict[str, Any]:
        """Scrape la base HAS"""
        try:
            logger.info(f"  📍 HAS: {medicine_name}")
            
            # Recherche HAS (recommandations)
            search_url = f"https://www.has-sante.fr/jcms/r_1568/fr/search?fulltext={urllib.parse.quote(medicine_name)}"
            response = self.session.get(search_url, timeout=self.timeout)
            response.encoding = 'utf-8'
            
            if response.status_code == 200:
                soup = BeautifulSoup(response.content, 'html.parser')
                
                results = []
                articles = soup.find_all('article', class_='result-item')
                
                for article in articles[:3]:
                    title = article.find('h3')
                    desc = article.find('p', class_='description')
                    if title and desc:
                        results.append({
                            "title": title.get_text(strip=True),
                            "text": desc.get_text(strip=True)[:500]
                        })
                
                return {
                    "status": "success" if results else "no_results",
                    "data": results,
                    "url": search_url
                }
        except Exception as e:
            logger.debug(f"    HAS error: {e}")
        
        return {"status": "failed", "data": []}
    
    def scrape_theriaque(self, medicine_name: str) -> Dict[str, Any]:
        """Scrape Thériaque"""
        try:
            logger.info(f"  📍 Thériaque: {medicine_name}")
            
            # Recherche Thériaque
            search_url = f"https://www.theriaque.org/html/recherche.php?query={urllib.parse.quote(medicine_name)}"
            response = self.session.get(search_url, timeout=self.timeout)
            response.encoding = 'utf-8'
            
            if response.status_code == 200:
                soup = BeautifulSoup(response.content, 'html.parser')
                
                results = []
                # Thériaque a une structure différente
                links = soup.find_all('a', href=True)
                
                for link in links[:3]:
                    text = link.get_text(strip=True)
                    if medicine_name.lower() in text.lower() and len(text) > 5:
                        results.append({
                            "title": text,
                            "url": link['href']
                        })
                
                return {
                    "status": "success" if results else "no_results",
                    "data": results,
                    "url": search_url
                }
        except Exception as e:
            logger.debug(f"    Thériaque error: {e}")
        
        return {"status": "failed", "data": []}
    
    def scrape_drugbank(self, medicine_name: str) -> Dict[str, Any]:
        """Scrape DrugBank via recherche libre (pas de clé API requise)"""
        try:
            logger.info(f"  📍 DrugBank: {medicine_name}")
            
            # Recherche DrugBank
            search_url = f"https://go.drugbank.com/unearth/q?query={urllib.parse.quote(medicine_name)}"
            response = self.session.get(search_url, timeout=self.timeout)
            
            if response.status_code == 200:
                soup = BeautifulSoup(response.content, 'html.parser')
                
                results = []
                drugs = soup.find_all('div', class_='drug')
                
                for drug in drugs[:3]:
                    name = drug.find('h4')
                    desc = drug.find('p')
                    if name:
                        results.append({
                            "name": name.get_text(strip=True),
                            "description": desc.get_text(strip=True)[:500] if desc else ""
                        })
                
                return {
                    "status": "success" if results else "no_results",
                    "data": results,
                    "url": search_url
                }
        except Exception as e:
            logger.debug(f"    DrugBank error: {e}")
        
        return {"status": "failed", "data": []}
    
    def scrape_all_sources(self, medicine_name: str) -> Dict[str, Any]:
        """Scrape toutes les sources"""
        logger.info(f"\n🔍 Scraping sources for: {medicine_name}")
        
        all_data = {
            "ansm": self.scrape_ansm(medicine_name),
            "has": self.scrape_has(medicine_name),
            "theriaque": self.scrape_theriaque(medicine_name),
            "drugbank": self.scrape_drugbank(medicine_name)
        }
        
        return all_data


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
    
    def enrich_with_mistral(self, medicine_name: str, scraped_data: Dict[str, Any], mongo_data: Dict[str, Any]) -> Dict[str, Any]:
        """Envoie les données scrapées à Mistral pour enrichissement"""
        try:
            # Préparer le contexte
            context = self._prepare_context(medicine_name, scraped_data, mongo_data)
            
            prompt = f"""Tu es un expert médical. Basé sur les informations suivantes sur le médicament '{medicine_name}',
            synthétise et structure les informations médicales essentielles.
            
            DONNÉES DISPONIBLES:
            {context}
            
            Retourne un JSON structuré avec ces champs:
            {{
                "indications": "Les indications principales (5-10 lignes max)",
                "contre_indications": "Les contre-indications essentielles",
                "interactions": "Les interactions médicamenteuses importantes",
                "effets_secondaires": "Les effets secondaires courants",
                "posologie": "La posologie recommandée",
                "precautions": "Précautions d'emploi et avertissements",
                "sources": {{"ansm": true/false, "has": true/false, "theriaque": true/false, "drugbank": true/false}},
                "resume_clinique": "Un résumé de 2-3 phrases sur le médicament"
            }}
            
            Retourne UNIQUEMENT le JSON valide, sans markdown."""
            
            payload = {
                "model": MISTRAL_MODEL,
                "messages": [{"role": "user", "content": prompt}],
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
                content = result['choices'][0]['message']['content'].strip()
                
                # Parse JSON - handle markdown
                if '```json' in content:
                    content = content.split('```json')[1].split('```')[0].strip()
                elif '```' in content:
                    content = content.split('```')[1].split('```')[0].strip()
                
                enrichment = json.loads(content)
                logger.info(f"  ✅ Enriched with Mistral")
                return enrichment
            else:
                logger.warning(f"  ⚠️  Mistral error: {response.status_code}")
                return self._default_enrichment()
        
        except json.JSONDecodeError as e:
            logger.warning(f"  ⚠️  JSON parse error: {e}")
            return self._default_enrichment()
        except Exception as e:
            logger.error(f"  ❌ Enrichment error: {e}")
            return self._default_enrichment()
    
    def _prepare_context(self, medicine_name: str, scraped_data: Dict[str, Any], mongo_data: Dict[str, Any]) -> str:
        """Prépare le contexte pour Mistral"""
        parts = []
        
        # Données MongoDB
        if mongo_data.get('medicine_details'):
            details = mongo_data['medicine_details']
            if details.get('substances_actives'):
                parts.append(f"Substances actives: {', '.join(details['substances_actives'])}")
            if details.get('dosages'):
                parts.append(f"Dosages: {', '.join(details['dosages'])}")
            if details.get('laboratoire'):
                parts.append(f"Labo: {details['laboratoire']}")
        
        # Données scrapées
        for source, source_data in scraped_data.items():
            if source_data.get('status') == 'success' and source_data.get('data'):
                parts.append(f"\n{source.upper()}:")
                for item in source_data['data'][:2]:
                    if isinstance(item, dict):
                        text = " ".join([str(v)[:200] for v in item.values()])
                        parts.append(f"  - {text}")
        
        return "\n".join(parts) if parts else "Données non disponibles"
    
    def _default_enrichment(self) -> Dict[str, Any]:
        """Enrichissement par défaut"""
        return {
            "indications": "À déterminer",
            "contre_indications": "À déterminer",
            "interactions": "À déterminer",
            "effets_secondaires": "À déterminer",
            "posologie": "À déterminer",
            "precautions": "À déterminer",
            "sources": {"ansm": False, "has": False, "theriaque": False, "drugbank": False},
            "resume_clinique": "Données insuffisantes pour enrichissement complet"
        }
    
    def create_embedding(self, medicine: Dict[str, Any]) -> List[float]:
        """Crée le vecteur d'embedding"""
        enrichment = medicine.get('enrichment', {})
        
        text_parts = [
            medicine.get('title', ''),
            enrichment.get('indications', ''),
            enrichment.get('resume_clinique', ''),
            enrichment.get('effets_secondaires', '')
        ]
        
        combined = " ".join([str(t) for t in text_parts if t])
        combined = combined.strip() or medicine.get('title', 'medicine')
        
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
            logger.error(f"  ❌ Qdrant save error: {e}")
            return False
    
    def save_to_mongodb(self, medicine_id: Any, enrichment: Dict[str, Any], scraped_sources: Dict[str, Any]) -> bool:
        """Sauvegarde dans MongoDB"""
        try:
            self.db.medicines.update_one(
                {"_id": medicine_id},
                {
                    "$set": {
                        "enrichment": enrichment,
                        "scraped_sources": scraped_sources,
                        "enrichment_date": datetime.now()
                    }
                }
            )
            return True
        except Exception as e:
            logger.error(f"  ❌ MongoDB save error: {e}")
            return False
    
    def process_medicine(self, medicine: Dict[str, Any], scraper: MedicalSourcesScraper) -> bool:
        """Traite un médicament complet"""
        medicine_name = medicine.get('title', '')
        
        if not medicine_name:
            return False
        
        try:
            # Scrape toutes les sources
            scraped = scraper.scrape_all_sources(medicine_name)
            
            # Enrichit avec Mistral
            enrichment = self.enrich_with_mistral(medicine_name, scraped, medicine)
            
            # Sauvegarde MongoDB
            if not self.save_to_mongodb(medicine.get('_id'), enrichment, scraped):
                return False
            
            # Crée embedding et sauvegarde Qdrant
            medicine['enrichment'] = enrichment
            vector = self.create_embedding(medicine)
            
            if not self.save_to_qdrant(medicine, vector):
                return False
            
            logger.info(f"✨ SUCCESS: {medicine_name}")
            return True
        
        except Exception as e:
            logger.error(f"❌ Error processing {medicine_name}: {e}")
            return False


def main():
    import argparse
    
    parser = argparse.ArgumentParser()
    parser.add_argument('--limit', type=int, default=None)
    args = parser.parse_args()
    
    logger.info("=" * 70)
    logger.info("🚀 REAL SOURCES SCRAPE + MISTRAL ENRICHMENT + MONGODB + QDRANT")
    logger.info("=" * 70)
    
    try:
        scraper = MedicalSourcesScraper()
        enricher = MistralEnricher()
        
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
                if enricher.process_medicine(medicine, scraper):
                    enriched += 1
                
                processed += 1
                
                if idx % 5 == 0 or idx == total:
                    pct = (processed/total)*100
                    logger.info(f"\n📊 Progress: {processed}/{total} ({pct:.1f}%) - Success: {enriched}/{processed}")
                
                # Rate limiting
                time.sleep(2)
            
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
