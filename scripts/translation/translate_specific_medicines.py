"""
Script de traduction ciblée pour des médicaments spécifiques
MongoDB: medicines (FR) -> Mistral AI -> MongoDB: medicines-EN (EN)
"""

import os
import sys
import time
import logging
from typing import Dict, List
from pymongo import MongoClient
from mistralai.client import Mistral
from dotenv import load_dotenv

# Charger les variables d'environnement
load_dotenv()

# Configuration du logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('translation_specific.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Liste des médicaments à traduire
MEDICINES_TO_TRANSLATE = [
    "Oméprazole",
    "Aspirine",
    "Atorvastatine",
    "Bétaméthasone",
    "Miconazole",
    "Lévothyroxine",
    "Amoxicilline",
    "Méthotrexate",
    "Ibuprofène",
    "Paracétamol",
    "Salbutamol",
    "Dexaméthasone",
    "Oxygène médical"
]

class SpecificMedicineTranslator:
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
        
    def find_medicine_by_name(self, name: str) -> Dict:
        """
        Recherche un médicament par son nom (insensible à la casse)
        
        Args:
            name: Nom du médicament à rechercher
            
        Returns:
            Document MongoDB du médicament ou None
        """
        # Essayer différentes variantes du nom
        patterns = [
            {"title": {"$regex": f"^{name}", "$options": "i"}},
            {"title": {"$regex": name, "$options": "i"}},
            {"denomination": {"$regex": f"^{name}", "$options": "i"}},
            {"denomination": {"$regex": name, "$options": "i"}}
        ]
        
        for pattern in patterns:
            medicine = self.medicines_fr.find_one(pattern)
            if medicine:
                return medicine
        
        return None
    
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
            logger.info(f"Appel API Mistral pour traduction...")
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
            
            # DEBUG: Sauvegarder la réponse brute pour vérification
            logger.info(f"Réponse Mistral (premiers 500 chars): {translated_text[:500]}...")
            
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
        current_text_lines = []
        
        for line in lines:
            line_stripped = line.strip()
            
            if line_stripped.startswith('TITLE:'):
                translated_medicine['title'] = line_stripped.replace('TITLE:', '').strip()
            
            elif line_stripped.startswith('SECTION:'):
                # Sauvegarder le texte accumulé de la subsection précédente
                if current_subsection and current_text_lines:
                    current_subsection['text'] = '\n'.join(current_text_lines)
                    current_text_lines = []
                
                # Sauvegarder la subsection précédente
                if current_subsection and current_section:
                    current_section['subsections'].append(current_subsection)
                    current_subsection = None
                
                # Sauvegarder la section précédente
                if current_section:
                    translated_sections.append(current_section)
                
                # Créer nouvelle section
                current_section = {
                    'section_name': line_stripped.replace('SECTION:', '').strip(),
                    'subsections': []
                }
            
            elif line_stripped.startswith('SUBSECTION:'):
                # Sauvegarder le texte accumulé de la subsection précédente
                if current_subsection and current_text_lines:
                    current_subsection['text'] = '\n'.join(current_text_lines)
                    current_text_lines = []
                
                # Sauvegarder la subsection précédente
                if current_subsection and current_section:
                    current_section['subsections'].append(current_subsection)
                
                # Créer nouvelle subsection
                current_subsection = {
                    'subsection_name': line_stripped.replace('SUBSECTION:', '').strip(),
                    'text': ''
                }
            
            elif line_stripped.startswith('TEXT:'):
                # Début du texte
                text_content = line_stripped.replace('TEXT:', '').strip()
                current_text_lines = [text_content] if text_content else []
            
            elif line_stripped and current_subsection:
                # Ligne de texte continue (sans marqueur)
                current_text_lines.append(line_stripped)
        
        # Sauvegarder le dernier texte accumulé
        if current_subsection and current_text_lines:
            current_subsection['text'] = '\n'.join(current_text_lines)
        
        # Ajouter la dernière subsection
        if current_subsection and current_section:
            current_section['subsections'].append(current_subsection)
        
        # Ajouter la dernière section
        if current_section:
            translated_sections.append(current_section)
        
        translated_medicine['sections'] = translated_sections
        
        # Copier les autres champs non traduits
        for key in ['cis', 'forme', 'voies', 'statut', 'type', 'titulaire', 
                    'surveillance', 'date_amm', 'compositions', 'presentations']:
            if key in original_medicine:
                translated_medicine[key] = original_medicine[key]
        
        return translated_medicine
    
    def translate_specific_medicines(self, medicine_names: List[str]):
        """
        Traduit une liste spécifique de médicaments
        
        Args:
            medicine_names: Liste des noms de médicaments à traduire
        """
        total = len(medicine_names)
        processed = 0
        errors = 0
        not_found = 0
        already_translated = 0
        
        logger.info(f"Début de la traduction de {total} médicaments spécifiques")
        
        for i, name in enumerate(medicine_names, 1):
            try:
                logger.info(f"\n[{i}/{total}] Recherche de: {name}")
                
                # Trouver le médicament
                medicine = self.find_medicine_by_name(name)
                
                if not medicine:
                    logger.warning(f"✗ Médicament introuvable: {name}")
                    not_found += 1
                    continue
                
                medicine_id = str(medicine['_id'])
                medicine_title = medicine.get('title', name)
                
                # Vérifier si déjà traduit
                if self.medicines_en.find_one({'original_id': medicine_id}):
                    logger.info(f"⊙ Déjà traduit: {medicine_title}")
                    already_translated += 1
                    continue
                
                logger.info(f"→ Traduction de: {medicine_title}")
                
                # Traduire
                translated_medicine = self.translate_medicine_content(medicine)
                
                # Sauvegarder dans medicines-EN
                self.medicines_en.replace_one(
                    {'original_id': medicine_id},
                    translated_medicine,
                    upsert=True
                )
                
                processed += 1
                logger.info(f"✓ Traduit avec succès: {medicine_title}")
                
                # Petite pause entre chaque traduction
                if i < total:
                    time.sleep(1)
                
            except Exception as e:
                errors += 1
                logger.error(f"✗ Erreur avec {name}: {e}")
        
        # Résumé final
        print("\n" + "=" * 60)
        print("RÉSUMÉ DE LA TRADUCTION")
        print("=" * 60)
        print(f"Total demandés:        {total}")
        print(f"✓ Traduits:            {processed}")
        print(f"⊙ Déjà traduits:       {already_translated}")
        print(f"✗ Introuvables:        {not_found}")
        print(f"✗ Erreurs:             {errors}")
        print("=" * 60)
        
        if not_found > 0:
            print("\nMédicaments introuvables:")
            for name in medicine_names:
                if not self.find_medicine_by_name(name):
                    print(f"  - {name}")


def main():
    """Point d'entrée du script"""
    print("\n" + "=" * 60)
    print("TRADUCTION DE MÉDICAMENTS SPÉCIFIQUES")
    print("MongoDB: medicines (FR) -> Mistral AI -> medicines-EN (EN)")
    print("=" * 60 + "\n")
    
    print(f"Médicaments à traduire ({len(MEDICINES_TO_TRANSLATE)}):")
    for i, name in enumerate(MEDICINES_TO_TRANSLATE, 1):
        print(f"  {i}. {name}")
    
    print("\n" + "=" * 60)
    
    try:
        # Initialiser le traducteur
        translator = SpecificMedicineTranslator()
        
        # Demander confirmation
        response = input("\nDémarrer la traduction ? (y/n): ")
        if response.lower() != 'y':
            print("Annulé par l'utilisateur")
            return
        
        # Lancer la traduction
        start_time = time.time()
        translator.translate_specific_medicines(MEDICINES_TO_TRANSLATE)
        
        elapsed_time = time.time() - start_time
        print(f"\nTemps total: {elapsed_time:.1f} secondes ({elapsed_time/60:.1f} minutes)")
        
    except KeyboardInterrupt:
        logger.info("\nInterruption par l'utilisateur (Ctrl+C)")
    except Exception as e:
        logger.error(f"Erreur fatale: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
