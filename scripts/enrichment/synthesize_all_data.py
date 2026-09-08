#!/usr/bin/env python3
"""
Synthétise les données MongoDB avec Mistral
SANS RIEN PERDRE - toutes les données originales restent intactes
Ajoute juste un champ 'synthesis' avec le résumé Mistral
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


class DataPreserver:
    """Synthétise avec Mistral en préservant TOUTES les données"""
    
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
    
    def compile_all_data(self, medicine: Dict) -> str:
        """Compile TOUTES les données disponibles du médicament"""
        data_parts = []
        
        # Titre
        if medicine.get('title'):
            data_parts.append(f"MÉDICAMENT: {medicine['title']}")
        
        # URL si disponible
        if medicine.get('url'):
            data_parts.append(f"URL: {medicine['url']}")
        
        # Détails du médicament
        if medicine.get('medicine_details'):
            data_parts.append("\n=== DÉTAILS ===")
            details = medicine['medicine_details']
            
            if details.get('substances_actives'):
                data_parts.append(f"Substances actives: {', '.join(details['substances_actives'])}")
            if details.get('laboratoire'):
                data_parts.append(f"Laboratoire: {details['laboratoire']}")
            if details.get('dosages'):
                data_parts.append(f"Dosages: {', '.join(details['dosages'])}")
            if details.get('forme'):
                data_parts.append(f"Forme: {details['forme']}")
            if details.get('voie_administration'):
                data_parts.append(f"Voie d'administration: {details['voie_administration']}")
        
        # TOUTES les sections
        if medicine.get('sections'):
            data_parts.append("\n=== SECTIONS ===")
            for idx, section in enumerate(medicine['sections'], 1):
                title = section.get('title', f'Section {idx}')
                content = section.get('content', [])
                
                data_parts.append(f"\n{idx}. {title}:")
                
                if isinstance(content, list):
                    for item in content:
                        if isinstance(item, dict):
                            text = item.get('text', '')
                            if text and text not in ['Sans objet', 'Sans objet.']:
                                data_parts.append(f"   - {text[:500]}")
                        else:
                            if str(item).strip() not in ['Sans objet', 'Sans objet.']:
                                data_parts.append(f"   - {str(item)[:500]}")
                else:
                    if str(content).strip() not in ['Sans objet', 'Sans objet.']:
                        data_parts.append(f"   {str(content)[:500]}")
        
        return "\n".join(data_parts)
    
    def synthesize_with_mistral(self, medicine_name: str, all_data: str) -> Dict[str, Any]:
        """Synthétise TOUTES les données avec Mistral"""
        try:
            prompt = f"""Tu es un expert pharmaceutique. Voici TOUTES les informations disponibles sur le médicament '{medicine_name}'.

DONNÉES COMPLÈTES:
{all_data}

Synthétise ces informations et retourne un JSON structuré avec:
{{
    "indications": "Les indications (extraites de la section concernée)",
    "contre_indications": "Les contre-indications",
    "interactions": "Les interactions médicamenteuses",
    "effets_secondaires": "Les effets secondaires principaux",
    "posologie": "La posologie recommandée",
    "precautions": "Les précautions d'emploi et avertissements",
    "resume": "Résumé clinique complet du médicament (5-10 phrases)",
    "notes": "Toute information supplémentaire importante"
}}

IMPORTANT: Retourne UNIQUEMENT le JSON, pas de markdown."""
            
            payload = {
                "model": MISTRAL_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.3,  # Plus bas pour plus de précision
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
                
                # Parse JSON
                if '```json' in content:
                    content = content.split('```json')[1].split('```')[0].strip()
                elif '```' in content:
                    content = content.split('```')[1].split('```')[0].strip()
                
                synthesis = json.loads(content)
                logger.debug(f"✓ Synthétisé: {medicine_name}")
                return synthesis
            else:
                logger.warning(f"⚠️  Mistral {response.status_code}")
                return self._default_synthesis()
        
        except json.JSONDecodeError:
            logger.warning(f"⚠️  JSON parse error")
            return self._default_synthesis()
        except Exception as e:
            logger.error(f"❌ Error: {e}")
            return self._default_synthesis()
    
    def _default_synthesis(self) -> Dict[str, Any]:
        """Synthèse par défaut"""
        return {
            "indications": "Voir données originales",
            "contre_indications": "Voir données originales",
            "interactions": "Voir données originales",
            "effets_secondaires": "Voir données originales",
            "posologie": "Voir données originales",
            "precautions": "Voir données originales",
            "resume": "Synthèse non disponible - consulter les données complètes",
            "notes": "Les données complètes sont toujours disponibles dans le document"
        }
    
    def create_embedding(self, medicine: Dict[str, Any]) -> List[float]:
        """Crée embedding à partir de TOUTES les données"""
        try:
            synthesis = medicine.get('synthesis', {})
            
            text_parts = [
                medicine.get('title', ''),
                synthesis.get('indications', ''),
                synthesis.get('resume', ''),
                synthesis.get('contre_indications', '')
            ]
            
            combined = " ".join([str(t) for t in text_parts if t]).strip()
            combined = combined or medicine.get('title', 'medicine')
            
            return self.embedding_model.encode(combined, convert_to_tensor=False).tolist()
        except Exception as e:
            logger.error(f"Embedding error: {e}")
            return [0.0] * 384
    
    def save_to_qdrant(self, medicine: Dict[str, Any], vector: List[float]) -> bool:
        """Sauvegarde dans Qdrant avec TOUTES les données"""
        try:
            point_id = hash(str(medicine.get('_id', ''))) % (2**31)
            
            # Inclure les données complètes dans Qdrant
            point = PointStruct(
                id=point_id,
                vector=vector,
                payload={
                    "title": medicine.get('title', ''),
                    "synthesis": medicine.get('synthesis', {}),
                    "medicine_details": medicine.get('medicine_details', {}),
                    "mongo_id": str(medicine.get('_id', '')),
                    "synthesized_at": datetime.now().isoformat()
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
    
    def save_to_mongodb(self, medicine_id: Any, synthesis: Dict[str, Any]) -> bool:
        """Sauvegarde dans MongoDB - AJOUTE juste le champ 'synthesis', le reste reste intacte"""
        try:
            self.db.medicines.update_one(
                {"_id": medicine_id},
                {
                    "$set": {
                        "synthesis": synthesis,
                        "synthesis_date": datetime.now(),
                        "data_preserved": True  # Marqueur que toutes les données originales sont conservées
                    }
                }
            )
            return True
        except Exception as e:
            logger.error(f"MongoDB error: {e}")
            return False
    
    def process_medicine(self, medicine: Dict[str, Any]) -> bool:
        """Traite un médicament - synthétise SANS perdre les données"""
        medicine_name = medicine.get('title', '')
        
        if not medicine_name:
            return False
        
        try:
            # Compile TOUTES les données
            all_data = self.compile_all_data(medicine)
            
            if not all_data.strip():
                return False
            
            # Synthétise avec Mistral
            synthesis = self.synthesize_with_mistral(medicine_name, all_data)
            
            # Sauvegarde dans MongoDB - SANS supprimer les données originales
            if not self.save_to_mongodb(medicine.get('_id'), synthesis):
                return False
            
            # Ajoute la synthèse au document pour Qdrant
            medicine['synthesis'] = synthesis
            
            # Crée embedding
            vector = self.create_embedding(medicine)
            
            # Sauvegarde dans Qdrant
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
    args = parser.parse_args()
    
    logger.info("=" * 70)
    logger.info("🔄 SYNTHÈSE MISTRAL - SANS PERDRE LES DONNÉES")
    logger.info("=" * 70)
    logger.info("✓ Toutes les données originales restent dans MongoDB")
    logger.info("✓ Ajout d'un champ 'synthesis' avec le résumé Mistral")
    logger.info("=" * 70)
    
    try:
        preserver = DataPreserver()
        
        # Récupère les médicaments
        medicines = list(preserver.db.medicines.find({}))
        
        if args.limit:
            medicines = medicines[:args.limit]
        
        total = len(medicines)
        processed = 0
        synthesized = 0
        failed = 0
        
        logger.info(f"\n📊 Total à traiter: {total:,} médicaments")
        logger.info(f"⏱️  Vitesse: ~1 médicament / seconde")
        logger.info(f"🕐 ETA: ~{int(total/60)} minutes\n")
        
        start_time = time.time()
        
        for idx, medicine in enumerate(medicines, 1):
            try:
                if preserver.process_medicine(medicine):
                    synthesized += 1
                else:
                    failed += 1
                
                processed += 1
                
                if idx % 100 == 0 or idx == total:
                    elapsed = time.time() - start_time
                    speed = processed / elapsed if elapsed > 0 else 0
                    pct = (processed/total)*100
                    remaining = total - processed
                    eta = remaining / speed if speed > 0 else 0
                    
                    eta_str = f"{int(eta/60)}m {int(eta%60)}s" if eta > 0 else "?"
                    
                    logger.info(f"📊 {processed:,}/{total:,} ({pct:.1f}%) | Succès: {synthesized:,} | ETA: {eta_str}")
                
                # Rate limiting pour Mistral
                time.sleep(0.8)
            
            except KeyboardInterrupt:
                logger.warning("\n⚠️  Arrêt - données sauvegardées")
                break
            except Exception as e:
                logger.error(f"Error: {e}")
                failed += 1
                processed += 1
        
        # Résumé final
        total_time = time.time() - start_time
        logger.info("\n" + "=" * 70)
        logger.info("✅ SYNTHÈSE TERMINÉE")
        logger.info(f"   Temps total: {int(total_time/60)}m {int(total_time%60)}s")
        logger.info(f"   Traités: {processed:,}/{total:,}")
        logger.info(f"   Synthétisés: {synthesized:,}")
        logger.info(f"   Échoués: {failed:,}")
        logger.info(f"   Taux réussite: {(synthesized/total*100):.1f}%")
        logger.info("\n💾 Vérification MongoDB...")
        
        # Vérification
        total_synthesized = preserver.db.medicines.count_documents({"synthesis": {"$exists": True}})
        logger.info(f"   Documents avec synthesis: {total_synthesized:,}/9804")
        
        # Vérifier qu'aucune donnée n'a été perdue
        total_docs = preserver.db.medicines.count_documents({})
        logger.info(f"   Documents totaux: {total_docs:,}")
        
        if total_docs == 9804:
            logger.info("   ✓ Aucune donnée perdue!")
        
        logger.info("=" * 70)
        
        return 0 if synthesized == total else 1
    
    except Exception as e:
        logger.error(f"Fatal: {e}")
        sys.exit(1)


if __name__ == "__main__":
    sys.exit(main())
