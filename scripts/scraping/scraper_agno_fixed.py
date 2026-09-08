#!/usr/bin/env python3
"""
Scraper Agno pour collecter données médicales de sources françaises
FIXED VERSION - Corrected field names to match MongoDB structure
"""

import os
import sys
import requests
import json
import time
from datetime import datetime
from pymongo import MongoClient, ASCENDING
from qdrant_client import QdrantClient
from sentence_transformers import SentenceTransformer
from typing import List, Dict, Any
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Load environment variables
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '../../.env'))

class MedicalDataScraper:
    """Scraper pour données médicales françaises utilisant Agno - FIXED"""
    
    def __init__(self):
        # MongoDB connection
        mongo_host = os.getenv('MONGO_HOST', '127.0.0.1')
        mongo_port = int(os.getenv('MONGO_PORT', 27018))
        self.mongo_client = MongoClient(mongo_host, mongo_port)
        self.db = self.mongo_client['medicsearch']
        
        # Qdrant connection
        qdrant_host = os.getenv('QDRANT_HOST', '127.0.0.1')
        qdrant_port = int(os.getenv('QDRANT_PORT', 6333))
        self.qdrant_client = QdrantClient(host=qdrant_host, port=qdrant_port, timeout=30)
        
        # Embedding model
        self.embedding_model = SentenceTransformer('all-MiniLM-L6-v2')
        
        # Create indexes
        self._create_indexes()
    
    def _create_indexes(self):
        """Create MongoDB indexes for faster queries"""
        try:
            self.db.medicines.create_index([('title', ASCENDING)])
            self.db.medicines.create_index([('enrichment.sources', ASCENDING)])
            logger.info("✅ MongoDB indexes created")
        except Exception as e:
            logger.warning(f"Indexes might already exist: {e}")
    
    def scrape_ansm_data(self, medicine_title: str) -> Dict[str, Any]:
        """Scrape ANSM database"""
        try:
            logger.info(f"🔍 Scraping ANSM for: {medicine_title}")
            
            # ANSM Public Database API endpoint
            ansm_api = "https://base-donnees-publique.medicaments.gouv.fr/api/medicament"
            
            params = {
                'denomination': medicine_title,
                'limit': 1
            }
            
            response = requests.get(ansm_api, params=params, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                if data and isinstance(data, list) and len(data) > 0:
                    med = data[0]
                    
                    return {
                        'source': 'ANSM',
                        'url': f"https://base-donnees-publique.medicaments.gouv.fr/medicament/{med.get('cis', '')}",
                        'data': {
                            'cis': med.get('cis'),
                            'denomination': med.get('denomination'),
                            'forme': med.get('forme'),
                            'dosage': med.get('dosage'),
                            'voies_administration': med.get('voies_administration', []),
                            'titulaires': med.get('titulaires', []),
                            'statut': med.get('statut'),
                            'date_autorisation': med.get('date_autorisation'),
                        }
                    }
        except Exception as e:
            logger.error(f"❌ ANSM Error: {e}")
        
        return None
    
    def scrape_has_data(self, medicine_title: str) -> Dict[str, Any]:
        """Scrape HAS database (Haute Autorité de Santé)"""
        try:
            logger.info(f"🔍 Scraping HAS for: {medicine_title}")
            
            # HAS Reference Search
            has_api = "https://www.has-sante.fr/jcms/r_3202/fr/medicament"
            
            params = {'search': medicine_title}
            
            response = requests.get(has_api, params=params, timeout=10)
            
            if response.status_code == 200:
                # Check if we got any relevant data
                if medicine_title.lower() in response.text.lower():
                    return {
                        'source': 'HAS',
                        'url': f"https://www.has-sante.fr/jcms/r_3202/fr/medicament",
                        'data': {
                            'indication': 'Found in HAS database'
                        }
                    }
        except Exception as e:
            logger.error(f"❌ HAS Error: {e}")
        
        return None
    
    def merge_sources(self, medicine_title: str, sources_data: List[Dict]) -> Dict[str, Any]:
        """Merge data from multiple sources into a single comprehensive description"""
        
        merged = {
            'title': medicine_title,
            'sources': [],
            'indications': [],
            'contre_indications': [],
            'interactions': [],
            'effets_secondaires': [],
            'posologie': '',
            'precautions': [],
            'description': '',
            'last_updated': datetime.now().isoformat()
        }
        
        # Collect data from all sources
        for source in sources_data:
            if source is None:
                continue
            
            source_type = source.get('source')
            source_url = source.get('url')
            data = source.get('data', {})
            
            # Add source reference
            merged['sources'].append({
                'type': source_type,
                'url': source_url,
                'fetched_at': datetime.now().isoformat()
            })
            
            # Merge indications
            if 'indications' in data and data['indications']:
                if isinstance(data['indications'], list):
                    merged['indications'].extend(data['indications'])
                else:
                    merged['indications'].append(data['indications'])
            
            # Merge contre-indications
            for key in ['contre_indications', 'contre-indications', 'contraindications']:
                if key in data and data[key]:
                    if isinstance(data[key], list):
                        merged['contre_indications'].extend(data[key])
                    else:
                        merged['contre_indications'].append(data[key])
            
            # Merge interactions
            for key in ['interactions', 'drug_interactions']:
                if key in data and data[key]:
                    if isinstance(data[key], list):
                        merged['interactions'].extend(data[key])
                    else:
                        merged['interactions'].append(data[key])
            
            # Merge side effects
            for key in ['effets_secondaires', 'effets_indesirables', 'adverse_effects']:
                if key in data and data[key]:
                    if isinstance(data[key], list):
                        merged['effets_secondaires'].extend(data[key])
                    else:
                        merged['effets_secondaires'].append(data[key])
            
            # Store posology if available
            if not merged['posologie'] and 'posologie' in data:
                merged['posologie'] = data['posologie']
        
        # Remove duplicates
        merged['indications'] = list(set(filter(None, merged['indications'])))
        merged['contre_indications'] = list(set(filter(None, merged['contre_indications'])))
        merged['interactions'] = list(set(filter(None, merged['interactions'])))
        merged['effets_secondaires'] = list(set(filter(None, merged['effets_secondaires'])))
        
        # Create comprehensive description
        merged['description'] = self._create_description(merged)
        
        return merged
    
    def _create_description(self, merged_data: Dict) -> str:
        """Create a comprehensive description from merged data"""
        
        parts = []
        
        if merged_data['indications']:
            parts.append(f"Indications: {', '.join(merged_data['indications'][:5])}")
        
        if merged_data['posologie']:
            parts.append(f"Posologie: {merged_data['posologie']}")
        
        if merged_data['contre_indications']:
            parts.append(f"Contre-indications: {', '.join(merged_data['contre_indications'][:3])}")
        
        if merged_data['effets_secondaires']:
            parts.append(f"Effets secondaires: {', '.join(merged_data['effets_secondaires'][:3])}")
        
        if merged_data['sources']:
            sources_text = '; '.join([f"{s['type']}" for s in merged_data['sources']])
            parts.append(f"Sources: {sources_text}")
        
        return '. '.join(parts)
    
    def save_to_mongodb(self, medicine_doc_id: str, medicine_data: Dict) -> bool:
        """Save enriched medicine data to MongoDB"""
        try:
            # FIXED: Use ObjectId as filter, or use title field
            result = self.db.medicines.update_one(
                {'_id': medicine_doc_id},
                {'$set': {
                    'enrichment.sources': medicine_data['sources'],
                    'enrichment.indications': medicine_data['indications'],
                    'enrichment.contre_indications': medicine_data['contre_indications'],
                    'enrichment.interactions': medicine_data['interactions'],
                    'enrichment.effets_secondaires': medicine_data['effets_secondaires'],
                    'enrichment.description': medicine_data['description'],
                    'enrichment.last_updated': datetime.now().isoformat()
                }},
                upsert=False
            )
            if result.matched_count > 0:
                return True
            else:
                logger.warning(f"No document found for ID {medicine_doc_id}")
                return False
        except Exception as e:
            logger.error(f"❌ MongoDB save error: {e}")
            return False
    
    def process_medicine(self, medicine: Dict) -> bool:
        """Process a single medicine and fetch data from sources"""
        try:
            medicine_title = medicine.get('title')
            medicine_id = medicine.get('_id')
            
            if not medicine_title or not medicine_id:
                logger.warning(f"Skipping medicine with missing title or _id")
                return False
            
            # Scrape data from sources
            sources = []
            sources.append(self.scrape_ansm_data(medicine_title))
            sources.append(self.scrape_has_data(medicine_title))
            
            # Check if we got any data
            sources = [s for s in sources if s is not None]
            
            if not sources:
                logger.warning(f"⚠️  No data found for {medicine_title}")
                return False
            
            # Merge all sources
            merged_data = self.merge_sources(medicine_title, sources)
            
            # Save to MongoDB
            if self.save_to_mongodb(medicine_id, merged_data):
                logger.info(f"✅ Saved to MongoDB")
                return True
            else:
                return False
        
        except Exception as e:
            logger.error(f"❌ Error processing medicine: {e}")
            return False
    
    def process_all_medicines(self, limit: int = None):
        """Process all medicines from MongoDB"""
        
        query = {}
        cursor = self.db.medicines.find(query)
        
        if limit:
            cursor = cursor.limit(limit)
        
        total = self.db.medicines.count_documents(query)
        if limit:
            total = min(total, limit)
        
        processed = 0
        failed = 0
        
        logger.info(f"\n🚀 Starting processing of {total} medicines...")
        
        for medicine in cursor:
            try:
                if self.process_medicine(medicine):
                    processed += 1
                else:
                    failed += 1
                
                # Rate limiting
                time.sleep(0.5)
                
                # Progress
                if (processed + failed) % 10 == 0:
                    logger.info(f"Progress: {processed + failed}/{total}")
                
            except Exception as e:
                logger.error(f"❌ Error processing medicine: {e}")
                failed += 1
        
        logger.info(f"\n{'='*60}")
        logger.info(f"✅ Processing complete!")
        logger.info(f"Processed: {processed}/{total}")
        logger.info(f"Failed: {failed}/{total}")
        logger.info(f"Success rate: {(processed/total)*100:.1f}%")
        logger.info(f"{'='*60}\n")


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='Scrape medical data from French sources')
    parser.add_argument('--limit', type=int, default=None, help='Limit number of medicines to process')
    
    args = parser.parse_args()
    
    scraper = MedicalDataScraper()
    scraper.process_all_medicines(limit=args.limit)
