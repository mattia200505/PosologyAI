"""
Script de traduction en masse des médicaments
MongoDB: medicines (FR) -> Mistral AI -> MongoDB: medicines-EN (EN)
"""

import os
import sys
import time
import logging
from typing import Dict, Optional
from pymongo import MongoClient
from mistralai.client import Mistral

# Configuration du logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('translation_progress.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class MedicineBatchTranslator:
    def __init__(self):
        """Initialise les connexions MongoDB et Mistral"""
        # MongoDB
        mongo_uri = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
        self.client = MongoClient(mongo_uri)
        self.db = self.client['medicsearch']
        self.medicines_fr = self.db['medicines']
        self.medicines_en = self.db['medicines-EN']
        
        # Créer un index unique sur l'ID original
        self.medicines_en.create_index('original_id', unique=True)
        
        # Mistral AI
        self.mistral_api_key = os.getenv('MISTRAL_API_KEY')
        if not self.mistral_api_key:
            raise ValueError("MISTRAL_API_KEY non définie dans les variables d'environnement")
        
        self.mistral_client = Mistral(api_key=self.mistral_api_key)
        self.model = "mistral-large-latest"
        
        logger.info("Connexions initialisées avec succès")
        
    def translate_medicine_content(self, medicine: Dict) -> Dict:
        """
        Traduit tout le contenu d'un médicament en anglais
        
        Args:
            medicine: Document MongoDB du médicament en français
            
        Returns:
            Document traduit en anglais
        """
        # Construire le prompt structuré
        prompt_parts = []
        
        # Titre
        if medicine.get('title'):
            prompt_parts.append(f"TITLE: {medicine['title']}")
        
        # Sections et sous-sections
        if medicine.get('sections'):
            for section in medicine['sections']:
                section_name = section.get('section_name', '')
                prompt_parts.append(f"\nSECTION: {section_name}")
                
                if section.get('subsections'):
                    for subsection in section['subsections']:
                        subsection_name = subsection.get('subsection_name', '')
                        prompt_parts.append(f"\nSUBSECTION: {subsection_name}")
                        
                        if subsection.get('text'):
                            prompt_parts.append(f"TEXT: {subsection['text']}")
        
        # Créer le contenu à traduire
        content_to_translate = "\n".join(prompt_parts)
        
        # Limiter la taille (Mistral a une limite)
        if len(content_to_translate) > 30000:
            content_to_translate = content_to_translate[:30000]
            logger.warning(f"Contenu tronqué pour {medicine.get('title', 'Unknown')}")
        
        # Appel à Mistral pour traduction
        system_prompt = """You are a professional medical translator. Translate the following French medication information to English.
Maintain the exact same structure with TITLE:, SECTION:, SUBSECTION:, and TEXT: labels.
Keep medical terminology accurate and professional.
Preserve all formatting and structure."""

        try:
            response = self.mistral_client.chat.complete(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"Translate this to English:\n\n{content_to_translate}"}
                ],
                temperature=0.2,
                max_tokens=8000
            )
            
            translated_text = response.choices[0].message.content
            
            # Parser la réponse traduite
            translated_medicine = self._parse_translated_content(translated_text, medicine)
            
            return translated_medicine
            
        except Exception as e:
            logger.error(f"Erreur de traduction Mistral: {e}")
            raise
    
    def _parse_translated_content(self, translated_text: str, original_medicine: Dict) -> Dict:
        """
        Parse le texte traduit et reconstruit la structure du document
        
        Args:
            translated_text: Texte traduit par Mistral
            original_medicine: Document original pour la structure
            
        Returns:
            Document traduit structuré
        """
        lines = translated_text.split('\n')
        
        # Copier la structure de base
        translated_medicine = {
            '_id': original_medicine['_id'],
            'original_id': str(original_medicine['_id']),
            'language': 'en'
        }
        
        # Parser le contenu
        current_section = None
        current_subsection = None
        translated_sections = []
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            if line.startswith('TITLE:'):
                translated_medicine['title'] = line.replace('TITLE:', '').strip()
            
            elif line.startswith('SECTION:'):
                if current_section:
                    translated_sections.append(current_section)
                current_section = {
                    'section_name': line.replace('SECTION:', '').strip(),
                    'subsections': []
                }
                current_subsection = None
            
            elif line.startswith('SUBSECTION:'):
                if current_section:
                    if current_subsection:
                        current_section['subsections'].append(current_subsection)
                    current_subsection = {
                        'subsection_name': line.replace('SUBSECTION:', '').strip(),
                        'text': ''
                    }
            
            elif line.startswith('TEXT:'):
                if current_subsection:
                    text_content = line.replace('TEXT:', '').strip()
                    current_subsection['text'] = text_content
        
        # Ajouter la dernière section
        if current_subsection and current_section:
            current_section['subsections'].append(current_subsection)
        if current_section:
            translated_sections.append(current_section)
        
        translated_medicine['sections'] = translated_sections
        
        # Copier les autres champs non traduits
        for key in ['cis', 'forme', 'voies', 'statut', 'type', 'titulaire', 
                    'surveillance', 'date_amm', 'compositions', 'presentations']:
            if key in original_medicine:
                translated_medicine[key] = original_medicine[key]
        
        return translated_medicine
    
    def translate_all_medicines(self, batch_size: int = 10, skip_existing: bool = True):
        """
        Traduit tous les médicaments par lots
        
        Args:
            batch_size: Nombre de médicaments à traiter avant une pause
            skip_existing: Si True, skip les médicaments déjà traduits
        """
        # Compter le total
        total_medicines = self.medicines_fr.count_documents({})
        logger.info(f"Total de médicaments à traiter: {total_medicines}")
        
        if skip_existing:
            already_translated = self.medicines_en.count_documents({})
            logger.info(f"Déjà traduits: {already_translated}")
        
        # Traiter par lots
        processed = 0
        errors = 0
        skipped = 0
        
        for medicine in self.medicines_fr.find({}):
            try:
                medicine_id = str(medicine['_id'])
                medicine_title = medicine.get('title', 'Unknown')
                
                # Vérifier si déjà traduit
                if skip_existing and self.medicines_en.find_one({'original_id': medicine_id}):
                    skipped += 1
                    if skipped % 100 == 0:
                        logger.info(f"Skipped: {skipped}/{total_medicines}")
                    continue
                
                logger.info(f"Traduction de: {medicine_title} (ID: {medicine_id})")
                
                # Traduire
                translated_medicine = self.translate_medicine_content(medicine)
                
                # Sauvegarder dans medicines-EN
                self.medicines_en.replace_one(
                    {'original_id': medicine_id},
                    translated_medicine,
                    upsert=True
                )
                
                processed += 1
                logger.info(f"✓ Traduit: {medicine_title} ({processed}/{total_medicines - skipped})")
                
                # Pause tous les batch_size pour éviter rate limiting
                if processed % batch_size == 0:
                    logger.info(f"Pause après {processed} traductions...")
                    time.sleep(2)  # Pause de 2 secondes
                
            except Exception as e:
                errors += 1
                logger.error(f"✗ Erreur avec {medicine.get('title', 'Unknown')}: {e}")
                
                # Si trop d'erreurs consécutives, arrêter
                if errors > 10:
                    logger.error("Trop d'erreurs, arrêt du script")
                    break
                
                # Pause plus longue en cas d'erreur
                time.sleep(5)
        
        # Résumé final
        logger.info("=" * 60)
        logger.info(f"TRADUCTION TERMINÉE")
        logger.info(f"Total traités: {processed}")
        logger.info(f"Skipped (déjà traduits): {skipped}")
        logger.info(f"Erreurs: {errors}")
        logger.info(f"Total dans medicines-EN: {self.medicines_en.count_documents({})}")
        logger.info("=" * 60)

    def get_translation_stats(self):
        """Affiche les statistiques de traduction"""
        total_fr = self.medicines_fr.count_documents({})
        total_en = self.medicines_en.count_documents({})
        
        print("\n" + "=" * 60)
        print("STATISTIQUES DE TRADUCTION")
        print("=" * 60)
        print(f"Médicaments FR (medicines):    {total_fr}")
        print(f"Médicaments EN (medicines-EN): {total_en}")
        print(f"Progression: {(total_en/total_fr)*100:.1f}%")
        print(f"Restants: {total_fr - total_en}")
        print("=" * 60 + "\n")


def main():
    """Point d'entrée du script"""
    print("\n" + "=" * 60)
    print("TRADUCTION EN MASSE DES MÉDICAMENTS")
    print("MongoDB: medicines (FR) -> Mistral AI -> medicines-EN (EN)")
    print("=" * 60 + "\n")
    
    try:
        # Initialiser le traducteur
        translator = MedicineBatchTranslator()
        
        # Afficher les stats actuelles
        translator.get_translation_stats()
        
        # Demander confirmation
        response = input("Démarrer la traduction ? (y/n): ")
        if response.lower() != 'y':
            print("Annulé par l'utilisateur")
            return
        
        # Configuration
        batch_size = int(input("Taille du lot (défaut: 10): ") or "10")
        
        # Lancer la traduction
        start_time = time.time()
        translator.translate_all_medicines(batch_size=batch_size, skip_existing=True)
        
        elapsed_time = time.time() - start_time
        logger.info(f"Temps total: {elapsed_time/60:.1f} minutes")
        
        # Afficher les stats finales
        translator.get_translation_stats()
        
    except KeyboardInterrupt:
        logger.info("\nInterruption par l'utilisateur (Ctrl+C)")
        logger.info("Vous pouvez relancer le script, il reprendra là où il s'est arrêté")
    except Exception as e:
        logger.error(f"Erreur fatale: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
