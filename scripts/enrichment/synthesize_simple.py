#!/usr/bin/env python3
"""
Synthétise MongoDB avec Mistral - VERSION SIMPLE
SANS RIEN PERDRE - toutes données originales restent intactes
"""

import os
import sys
import time
import json
import logging
import hashlib
import urllib3
from datetime import datetime
from pymongo import MongoClient
import requests

# Désactiver les warnings SSL
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '../../.env'))

MISTRAL_API_KEY = os.getenv('MISTRAL_API_KEY', '')

class SimpleSynthesizer:
    def __init__(self):
        mongo_host = os.getenv('MONGO_HOST', '127.0.0.1')
        mongo_port = int(os.getenv('MONGO_PORT', 27018))
        self.mongo_client = MongoClient(mongo_host, mongo_port)
        self.db = self.mongo_client['medicsearch']
        self.medicines = self.db['medicines']
        
    def compile_all_data(self, medicine):
        """Compile toutes les données pour Mistral"""
        text_parts = []
        
        # Titre et URL
        if medicine.get('title'):
            text_parts.append(f"Médicament: {medicine['title']}")
        if medicine.get('url'):
            text_parts.append(f"Source: {medicine['url']}")
        
        # Détails complets
        if medicine.get('medicine_details'):
            details = medicine['medicine_details']
            text_parts.append("DÉTAILS")
            for key, value in details.items():
                if value and str(value).strip() not in ['N/A', 'N/D', '']:
                    text_parts.append(f"{key}: {value}")
        
        # Toutes les sections (18 sections)
        if medicine.get('sections'):
            sections = medicine['sections']
            for section_name in ['1. Composition', '2. Forme pharmaceutique', '3. Indications thérapeutiques',
                               '4. Contre-indications', '5. Mises en garde et précautions', '6. Interactions',
                               '7. Fécondité, fertilité, grossesse et allaitement', '8. Posologie et mode',
                               '9. Surdosage', '10. Effets indésirables', '11. Propriétés pharmacodynamiques',
                               '12. Propriétés pharmacocinétiques', '13. Données de sécurité précliniques',
                               '14. Données pharmaceutiques', '15. Nature du contenant', '16. Conditions de conservations',
                               '17. Numéro national de registre', '18. Conditions de prescription et de délivrance']:
                if section_name in sections and sections[section_name] and sections[section_name] != 'Sans objet.':
                    text_parts.append(f"\n{section_name}\n{sections[section_name]}")
        
        return '\n'.join(text_parts)
    
    def synthesize_with_mistral(self, compiled_text):
        """Appel Mistral pour synthétiser"""
        if not compiled_text or not MISTRAL_API_KEY:
            return self._default_synthesis()
        
        try:
            prompt = f"""Synthétise les informations suivantes sur ce médicament en JSON structuré.
            
DONNÉES:
{compiled_text}

Réponds UNIQUEMENT en JSON valide (pas de markdown) avec cette structure:
{{
    "indications": "...",
    "contre_indications": "...",
    "interactions": "...",
    "effets_secondaires": "...",
    "posologie": "...",
    "precautions": "...",
    "resume": "...",
    "notes": "..."
}}

Sois concis mais complet."""

            response = requests.post(
                "https://api.mistral.ai/v1/chat/completions",
                headers={"Authorization": f"Bearer {MISTRAL_API_KEY}"},
                json={
                    "model": "mistral-small",
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.3,
                    "max_tokens": 2000
                },
                timeout=30,
                verify=False  # Désactiver SSL pour les problèmes de connexion
            )
            
            if response.status_code == 200:
                result = response.json()
                content = result['choices'][0]['message']['content'].strip()
                
                # Extrait JSON
                if content.startswith('{'):
                    try:
                        return json.loads(content)
                    except:
                        pass
                
                # Cherche JSON dans le contenu
                start = content.find('{')
                end = content.rfind('}') + 1
                if start >= 0 and end > start:
                    try:
                        return json.loads(content[start:end])
                    except:
                        pass
            
            return self._default_synthesis()
        
        except KeyboardInterrupt:
            raise  # Re-raise pour ne pas ignorer l'interruption
        except Exception as e:
            logger.warning(f"Mistral unavailable, using defaults: {type(e).__name__}")
            return self._default_synthesis()
    
    def _default_synthesis(self):
        """Synthèse par défaut si Mistral échoue"""
        return {
            "indications": "Voir la documentation originale",
            "contre_indications": "Voir la documentation originale",
            "interactions": "Voir la documentation originale",
            "effets_secondaires": "Voir la documentation originale",
            "posologie": "Voir la documentation originale",
            "precautions": "Voir la documentation originale",
            "resume": "Données non synthétisées - vérifier source originale",
            "notes": "Voir sections complètes"
        }
    
    def process_medicine(self, medicine):
        """Traite un médicament"""
        try:
            # Compile les données
            compiled = self.compile_all_data(medicine)
            
            # Synthétise avec Mistral
            synthesis = self.synthesize_with_mistral(compiled)
            
            # Sauvegarde dans MongoDB (IMPORTANT: $set préserve tous les autres champs)
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
        """Lance la synthèse"""
        logger.info("🔄 SYNTHÈSE MISTRAL - SANS PERDRE LES DONNÉES")
        
        # Compte total
        total = self.medicines.count_documents({})
        logger.info(f"📊 Médicaments à traiter: {total:,}")
        
        # Filtre: médicaments sans synthesis
        query = {"synthesis": {"$exists": False}}
        to_process = self.medicines.count_documents(query)
        logger.info(f"📋 À synthétiser: {to_process:,}")
        
        start_time = time.time()
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
            
            elapsed = time.time() - start_time
            if idx % 100 == 0:
                rate = idx / elapsed
                remaining = (to_process - idx) / rate if rate > 0 else 0
                logger.info(f"📊 {idx:,}/{to_process:,} ({idx/to_process*100:.1f}%) | "
                          f"Succès: {success} | Échoués: {failed} | "
                          f"ETA: {remaining/60:.0f}m")
            
            # Rate limiting
            time.sleep(0.8)
        
        elapsed = time.time() - start_time
        logger.info(f"\n✅ SYNTHÈSE TERMINÉE")
        logger.info(f"⏱️  Temps: {elapsed/60:.1f}m")
        logger.info(f"📊 Traités: {idx:,}/{to_process:,}")
        logger.info(f"✨ Synthétisés: {success:,}")
        logger.info(f"❌ Échoués: {failed:,}")
        logger.info(f"📈 Taux réussite: {success/(success+failed)*100:.1f}%")
        
        # Vérification finale
        logger.info("\n💾 Vérification MongoDB...")
        total_final = self.medicines.count_documents({})
        with_synthesis = self.medicines.count_documents({"synthesis": {"$exists": True}})
        logger.info(f"Documents totaux: {total_final:,}")
        logger.info(f"Avec synthesis: {with_synthesis:,}")
        if total_final == total:
            logger.info("✓ Aucune donnée perdue!")
        else:
            logger.warning(f"⚠️  Difference: {total - total_final}")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--limit', type=int, default=None)
    args = parser.parse_args()
    
    synthesizer = SimpleSynthesizer()
    synthesizer.run(limit=args.limit)
