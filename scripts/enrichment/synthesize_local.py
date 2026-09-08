#!/usr/bin/env python3
"""
Synthèse locale rapide - Sans appels API
Utilise extraction locale pour créer les synthèses
"""

import os
import re
from datetime import datetime
from pymongo import MongoClient
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '../../.env'))

class LocalSynthesizer:
    def __init__(self):
        mongo_host = os.getenv('MONGO_HOST', '127.0.0.1')
        mongo_port = int(os.getenv('MONGO_PORT', 27018))
        self.mongo_client = MongoClient(mongo_host, mongo_port)
        self.db = self.mongo_client['medicsearch']
        self.medicines = self.db['medicines']
        
    def extract_indications(self, medicine):
        """Extrait les indications"""
        sections = medicine.get('sections', {})
        text = sections.get('3. Indications thérapeutiques', '')
        return text[:500] if text and text != 'Sans objet.' else 'Voir documentation originale'
    
    def extract_contre_indications(self, medicine):
        """Extrait les contre-indications"""
        sections = medicine.get('sections', {})
        text = sections.get('4. Contre-indications', '')
        return text[:500] if text and text != 'Sans objet.' else 'Voir documentation originale'
    
    def extract_interactions(self, medicine):
        """Extrait les interactions"""
        sections = medicine.get('sections', {})
        text = sections.get('6. Interactions', '')
        return text[:500] if text and text != 'Sans objet.' else 'Voir documentation originale'
    
    def extract_effets_secondaires(self, medicine):
        """Extrait les effets secondaires"""
        sections = medicine.get('sections', {})
        text = sections.get('10. Effets indésirables', '')
        return text[:500] if text and text != 'Sans objet.' else 'Voir documentation originale'
    
    def extract_posologie(self, medicine):
        """Extrait la posologie"""
        sections = medicine.get('sections', {})
        text = sections.get('8. Posologie et mode', '')
        return text[:500] if text and text != 'Sans objet.' else 'Voir documentation originale'
    
    def extract_precautions(self, medicine):
        """Extrait les précautions"""
        sections = medicine.get('sections', {})
        text = sections.get('5. Mises en garde et précautions', '')
        return text[:500] if text and text != 'Sans objet.' else 'Voir documentation originale'
    
    def create_resume(self, medicine):
        """Crée un résumé à partir des données disponibles"""
        title = medicine.get('title', 'Médicament sans titre')
        if isinstance(title, list):
            title = ' '.join(title) if title else 'Médicament sans titre'
        
        details = medicine.get('medicine_details', {})
        if not isinstance(details, dict):
            return title[:300]
        
        parts = [f"Médicament: {title}"]
        
        # Handle substances_actives (liste)
        if 'substances_actives' in details:
            subs = details['substances_actives']
            if isinstance(subs, list) and subs:
                parts.append(f"Substances: {', '.join(subs[:2])}")
        
        # Handle laboratoire
        if 'laboratoire' in details and details['laboratoire']:
            parts.append(f"Labo: {details['laboratoire']}")
        
        # Handle dosages (liste)
        if 'dosages' in details:
            dos = details['dosages']
            if isinstance(dos, list) and dos:
                parts.append(f"Dosages: {', '.join(dos[:2])}")
        
        # Handle form
        if 'forme' in details and details['forme']:
            parts.append(f"Forme: {details['forme']}")
        
        return ' | '.join(parts)[:300]
    
    def process_medicine(self, medicine):
        """Synthétise un médicament localement"""
        try:
            synthesis = {
                "indications": self.extract_indications(medicine),
                "contre_indications": self.extract_contre_indications(medicine),
                "interactions": self.extract_interactions(medicine),
                "effets_secondaires": self.extract_effets_secondaires(medicine),
                "posologie": self.extract_posologie(medicine),
                "precautions": self.extract_precautions(medicine),
                "resume": self.create_resume(medicine),
                "notes": "Synthèse extraite des sections originales"
            }
            
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
            logger.error(f"Error processing {medicine.get('title', 'unknown')}: {e}")
            return False
    
    def run(self, limit=None):
        """Lance la synthèse locale"""
        logger.info("🔄 SYNTHÈSE LOCALE - SANS PERDRE LES DONNÉES")
        
        # Compte total
        total = self.medicines.count_documents({})
        logger.info(f"📊 Médicaments totaux: {total:,}")
        
        # Filtre: médicaments sans synthesis
        query = {"synthesis": {"$exists": False}}
        to_process = self.medicines.count_documents(query)
        logger.info(f"📋 À synthétiser: {to_process:,}")
        
        start_time = __import__('time').time()
        success = 0
        failed = 0
        
        cursor = self.medicines.find(query)
        if limit:
            cursor = cursor.limit(limit)
        
        for idx, medicine in enumerate(cursor, 1):
            if self.process_medicine(medicine):
                success += 1
            else:
                failed += 1
            
            if idx % 100 == 0:
                elapsed = __import__('time').time() - start_time
                rate = idx / elapsed
                remaining = (to_process - idx) / rate if rate > 0 else 0
                logger.info(f"📊 {idx:,}/{to_process:,} ({idx/to_process*100:.1f}%) | "
                          f"Succès: {success} | ETA: {remaining/60:.0f}m")
        
        elapsed = __import__('time').time() - start_time
        logger.info(f"\n✅ SYNTHÈSE TERMINÉE")
        logger.info(f"⏱️  Temps: {elapsed/60:.1f}m")
        logger.info(f"📊 Traités: {idx:,}/{to_process:,}")
        logger.info(f"✨ Synthétisés: {success:,}")
        logger.info(f"❌ Échoués: {failed:,}")
        
        # Vérification finale
        logger.info("\n💾 Vérification MongoDB...")
        total_final = self.medicines.count_documents({})
        with_synthesis = self.medicines.count_documents({"synthesis": {"$exists": True}})
        logger.info(f"Documents totaux: {total_final:,}")
        logger.info(f"Avec synthesis: {with_synthesis:,}")
        if total_final == total:
            logger.info("✓ Aucune donnée perdue!")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--limit', type=int, default=None)
    args = parser.parse_args()
    
    synthesizer = LocalSynthesizer()
    synthesizer.run(limit=args.limit)
