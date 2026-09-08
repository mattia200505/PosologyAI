#!/usr/bin/env python3
"""
Synthèse robuste - Gère les deux formats de sections (dict et list)
"""

import os
from datetime import datetime
from pymongo import MongoClient
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '../../.env'))

class RobustSynthesizer:
    def __init__(self):
        mongo_host = os.getenv('MONGO_HOST', '127.0.0.1')
        mongo_port = int(os.getenv('MONGO_PORT', 27018))
        self.mongo_client = MongoClient(mongo_host, mongo_port)
        self.db = self.mongo_client['medicsearch']
        self.medicines = self.db['medicines']
        
    def extract_section_text(self, sections, section_name):
        """Extrait le texte d'une section - gère dict ET list"""
        
        if isinstance(sections, dict):
            # Ancien format: sections[section_name] = "texte"
            text = sections.get(section_name, '')
            return text if text and text != 'Sans objet.' else ''
        
        elif isinstance(sections, list):
            # Nouveau format: [{"title": "...", "content": [...]}]
            for section in sections:
                if isinstance(section, dict) and section.get('title', '').strip() == section_name.strip():
                    content = section.get('content', [])
                    if isinstance(content, list):
                        # Combine tous les textes du contenu
                        texts = []
                        for item in content:
                            if isinstance(item, dict) and 'text' in item:
                                texts.append(item['text'])
                        result = ' '.join(texts)
                        return result if result and result != 'Sans objet.' else ''
            return ''
        
        return ''
    
    def create_synthesis(self, medicine):
        """Crée une synthèse à partir des données extraites"""
        sections = medicine.get('sections', {})
        details = medicine.get('medicine_details', {})
        
        # Extraction des sections principales
        indications = self.extract_section_text(sections, '3. INDICATIONS THERAPEUTIQUES') or \
                     self.extract_section_text(sections, '3. Indications thérapeutiques') or \
                     'Voir documentation originale'
        
        contre_indications = self.extract_section_text(sections, '4. CONTRE-INDICATIONS') or \
                            self.extract_section_text(sections, '4. Contre-indications') or \
                            'Voir documentation originale'
        
        interactions = self.extract_section_text(sections, '6. INTERACTIONS') or \
                      self.extract_section_text(sections, '6. Interactions') or \
                      'Voir documentation originale'
        
        effets_secondaires = self.extract_section_text(sections, '10. EFFETS INDESIRABLES') or \
                            self.extract_section_text(sections, '10. Effets indésirables') or \
                            'Voir documentation originale'
        
        posologie = self.extract_section_text(sections, '8. POSOLOGIE ET MODE') or \
                   self.extract_section_text(sections, '8. Posologie et mode') or \
                   'Voir documentation originale'
        
        precautions = self.extract_section_text(sections, '5. MISES EN GARDE') or \
                     self.extract_section_text(sections, '5. Mises en garde et précautions') or \
                     'Voir documentation originale'
        
        # Résumé
        title = medicine.get('title', '')
        if isinstance(title, list):
            title = ' '.join(title) if title else ''
        
        resume = f"{title}"
        if isinstance(details, dict):
            if 'dosages' in details and isinstance(details['dosages'], list) and details['dosages']:
                resume += f" | Dosages: {', '.join(details['dosages'][:2])}"
            if 'forme' in details and details['forme']:
                resume += f" | Forme: {details['forme']}"
        
        return {
            "indications": indications[:1000],
            "contre_indications": contre_indications[:1000],
            "interactions": interactions[:1000],
            "effets_secondaires": effets_secondaires[:1000],
            "posologie": posologie[:1000],
            "precautions": precautions[:1000],
            "resume": resume[:500],
            "notes": "Synthèse extraite des sections originales (gère les deux formats)"
        }
    
    def process_medicine(self, medicine):
        """Synthétise un médicament"""
        try:
            synthesis = self.create_synthesis(medicine)
            
            # Sauvegarde dans MongoDB
            self.medicines.update_one(
                {"_id": medicine["_id"]},
                {"$set": {
                    "synthesis": synthesis,
                    "synthesis_date": datetime.now(),
                    "data_preserved": True
                }}
            )
            
            return True
        except Exception as e:
            logger.error(f"Error: {medicine.get('title')}: {e}")
            return False
    
    def run(self, limit=None):
        """Lance la synthèse"""
        logger.info("🔄 SYNTHÈSE ROBUSTE (dict + list)")
        
        total = self.medicines.count_documents({})
        query = {"synthesis": {"$exists": False}}
        to_process = self.medicines.count_documents(query)
        
        logger.info(f"📊 À synthétiser: {to_process:,} / {total:,}")
        
        start_time = __import__('time').time()
        success = 0
        
        cursor = self.medicines.find(query)
        if limit:
            cursor = cursor.limit(limit)
        
        for idx, med in enumerate(cursor, 1):
            if self.process_medicine(med):
                success += 1
            
            if idx % 500 == 0:
                elapsed = __import__('time').time() - start_time
                rate = idx / elapsed
                remaining = (to_process - idx) / rate if rate > 0 else 0
                pct = (idx / to_process * 100)
                logger.info(f"📊 {idx:,}/{to_process:,} ({pct:.1f}%) | Succès: {success} | ETA: {remaining/60:.0f}m")
        
        elapsed = __import__('time').time() - start_time
        logger.info(f"✅ TERMINÉ - {success:,} synthétisés en {elapsed/60:.1f}m")
        
        # Vérification
        with_synth = self.medicines.count_documents({"synthesis": {"$exists": True}})
        logger.info(f"💾 MongoDB: {with_synth:,} avec synthesis / {total:,} total")
        
        if self.medicines.count_documents({}) == total:
            logger.info("✓ Aucune donnée perdue!")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--limit', type=int, default=None)
    args = parser.parse_args()
    
    synth = RobustSynthesizer()
    synth.run(limit=args.limit)
