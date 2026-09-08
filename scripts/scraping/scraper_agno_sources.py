#!/usr/bin/env python3
"""
Scraper Agno pour collecter données médicales de sources françaises
- ANSM (Agence Nationale de Sécurité du Médicament)
- Thériaque
- HAS (Haute Autorité de Santé)
- UpToDate (version française)
- Vidal
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
    """Scraper pour données médicales françaises utilisant Agno"""
    
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
            self.db.medicines.create_index([('name', ASCENDING)])
            self.db.medicines.create_index([('composition.molecules', ASCENDING)])
            self.db.medicines.create_index([('sources.type', ASCENDING)])
            logger.info("✅ MongoDB indexes created")
        except Exception as e:
            logger.warning(f"Indexes might already exist: {e}")
    
    def scrape_ansm_data(self, medicine_name: str) -> Dict[str, Any]:
        """
        Scrape ANSM database
        ANSM = Agence Nationale de Sécurité du Médicament et des produits de santé
        
        Sources:
        - https://base-donnees-publique.medicaments.gouv.fr
        - https://ansm.sante.fr/
        """
        try:
            logger.info(f"🔍 Scraping ANSM for: {medicine_name}")
            
            # ANSM Public Database API endpoint
            ansm_api = "https://base-donnees-publique.medicaments.gouv.fr/api/medicament"
            
            params = {
                'denomination': medicine_name,
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
                            'procedures': med.get('procedures', []),
                            'indications': med.get('indications'),
                            'contre_indications': med.get('contre_indications'),
                            'effets_secondaires': med.get('effets_secondaires'),
                            'interactions': med.get('interactions')
                        }
                    }
        except Exception as e:
            logger.error(f"❌ ANSM Error: {e}")
        
        return None
    
    def scrape_therique_data(self, medicine_name: str) -> Dict[str, Any]:
        """
        Scrape Thériaque database
        Thériaque = Base de données complète sur les médicaments français
        
        Source: https://www.therique.org
        """
        try:
            logger.info(f"🔍 Scraping Thériaque for: {medicine_name}")
            
            # Thériaque search endpoint
            therique_api = "https://www.therique.org/API"
            
            params = {
                'action': 'search',
                'q': medicine_name,
                'type': 'medicament'
            }
            
            response = requests.get(therique_api, params=params, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                if data and isinstance(data, dict) and 'results' in data:
                    if len(data['results']) > 0:
                        med = data['results'][0]
                        
                        return {
                            'source': 'Thériaque',
                            'url': f"https://www.therique.org/substances.php?id={med.get('id')}",
                            'data': {
                                'id': med.get('id'),
                                'nom': med.get('nom'),
                                'principe_actif': med.get('principe_actif'),
                                'presentation': med.get('presentation'),
                                'laboratoire': med.get('laboratoire'),
                                'indications': med.get('indications'),
                                'contre_indications': med.get('contre_indications'),
                                'precautions_emploi': med.get('precautions_emploi'),
                                'interactions': med.get('interactions'),
                                'effets_indesirables': med.get('effets_indesirables'),
                                'posologie': med.get('posologie'),
                                'grossesse_allaitement': med.get('grossesse_allaitement')
                            }
                        }
        except Exception as e:
            logger.error(f"❌ Thériaque Error: {e}")
        
        return None
    
    def scrape_has_data(self, medicine_name: str) -> Dict[str, Any]:
        """
        Scrape HAS (Haute Autorité de Santé) data
        HAS = Organisme qui évalue les médicaments
        
        Source: https://www.has-sante.fr
        """
        try:
            logger.info(f"🔍 Scraping HAS for: {medicine_name}")
            
            # HAS database endpoint
            has_api = "https://www.has-sante.fr/api/medicament"
            
            params = {
                'search': medicine_name,
                'limit': 1
            }
            
            response = requests.get(has_api, params=params, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                if data and isinstance(data, list) and len(data) > 0:
                    med = data[0]
                    
                    return {
                        'source': 'HAS',
                        'url': f"https://www.has-sante.fr/medicament/{med.get('id')}",
                        'data': {
                            'id': med.get('id'),
                            'denomination': med.get('denomination'),
                            'asmr_status': med.get('asmr_status'),
                            'clinical_benefit': med.get('clinical_benefit'),
                            'recommendations': med.get('recommendations'),
                            'risk_analysis': med.get('risk_analysis'),
                            'disease_area': med.get('disease_area')
                        }
                    }
        except Exception as e:
            logger.error(f"❌ HAS Error: {e}")
        
        return None
    
    def merge_sources(self, medicine_name: str, sources_data: List[Dict]) -> Dict[str, Any]:
        """Merge data from multiple sources into a single comprehensive description"""
        
        merged = {
            'name': medicine_name,
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
            if 'interactions' in data and data['interactions']:
                if isinstance(data['interactions'], list):
                    merged['interactions'].extend(data['interactions'])
                else:
                    merged['interactions'].append(data['interactions'])
            
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
    
    def save_to_mongodb(self, medicine_data: Dict) -> bool:
        """Save enriched medicine data to MongoDB"""
        try:
            result = self.db.medicines.update_one(
                {'name': medicine_data['name']},
                {'$set': {
                    'enrichment': medicine_data,
                    'last_updated': datetime.now().isoformat()
                }},
                upsert=True
            )
            return True
        except Exception as e:
            logger.error(f"❌ MongoDB save error: {e}")
            return False
    
    def save_to_qdrant(self, medicine_id: str, medicine_data: Dict) -> bool:
        """Save medicine embedding to Qdrant"""
        try:
            # Create embedding from description
            text_to_embed = f"{medicine_data['name']} {medicine_data['description']}"
            embedding = self.embedding_model.encode(text_to_embed).tolist()
            
            # Ensure collection exists
            try:
                self.qdrant_client.get_collection('medicaments')
            except:
                self.qdrant_client.create_collection(
                    collection_name='medicaments',
                    vectors_config={'size': 384, 'distance': 'Cosine'}
                )
            
            # Upsert point
            from qdrant_client.models import PointStruct
            
            point = PointStruct(
                id=hash(medicine_data['name']) % (10 ** 8),
                vector=embedding,
                payload={
                    'name': medicine_data['name'],
                    'description': medicine_data['description'],
                    'sources': medicine_data['sources'],
                    'indications': medicine_data['indications'][:5],
                    'mongo_id': str(medicine_id)
                }
            )
            
            self.qdrant_client.upsert(
                collection_name='medicaments',
                points=[point]
            )
            return True
        except Exception as e:
            logger.error(f"❌ Qdrant save error: {e}")
            return False
    
    def process_medicine(self, medicine_name: str) -> bool:
        """Process a single medicine from all sources"""
        logger.info(f"\n{'='*60}")
        logger.info(f"Processing: {medicine_name}")
        logger.info(f"{'='*60}")
        
        # Scrape from multiple sources
        sources = [
            self.scrape_ansm_data(medicine_name),
            self.scrape_therique_data(medicine_name),
            self.scrape_has_data(medicine_name)
        ]
        
        # Filter out None values
        sources = [s for s in sources if s is not None]
        
        if not sources:
            logger.warning(f"⚠️  No data found for {medicine_name}")
            return False
        
        # Merge all sources
        merged_data = self.merge_sources(medicine_name, sources)
        
        # Save to MongoDB
        if self.save_to_mongodb(merged_data):
            logger.info(f"✅ Saved to MongoDB")
        
        # Save to Qdrant
        medicine = self.db.medicines.find_one({'name': medicine_name})
        if medicine and self.save_to_qdrant(medicine['_id'], merged_data):
            logger.info(f"✅ Saved to Qdrant")
        
        return True
    
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
                medicine_name = medicine.get('name') or medicine.get('title')
                
                if self.process_medicine(medicine_name):
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
        logger.info(f"Qdrant collection: medicaments")
        logger.info(f"{'='*60}\n")


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='Scrape medical data from French sources')
    parser.add_argument('--limit', type=int, default=None, help='Limit number of medicines to process')
    parser.add_argument('--medicine', type=str, default=None, help='Process a specific medicine')
    
    args = parser.parse_args()
    
    scraper = MedicalDataScraper()
    
    if args.medicine:
        scraper.process_medicine(args.medicine)
    else:
        scraper.process_all_medicines(limit=args.limit)
