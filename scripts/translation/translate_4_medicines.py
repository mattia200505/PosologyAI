"""
Script pour traduire 4 médicaments spécifiques en anglais
Avec délais pour éviter le rate limiting de l'API Mistral
"""
import os
import time
import re
from typing import Dict, List, Any
from pymongo import MongoClient
from bson.objectid import ObjectId
from mistralai.client import Mistral
from dotenv import load_dotenv

load_dotenv()

# Configuration
MONGO_URI = os.getenv('MONGO_URI', 'mongodb://localhost:27017')
MISTRAL_API_KEY = os.getenv('MISTRAL_API_KEY')

# Les 4 médicaments à traduire
MEDICINES_TO_TRANSLATE = [
    "Ibuprofen",
    "Paracetamol", 
    "Amoxicillin",
    "Omeprazole"
]


class MedicineTranslator:
    def __init__(self):
        self.mongo_client = MongoClient(MONGO_URI)
        self.db = self.mongo_client['medicsearch']
        self.medicines_fr = self.db['medicines']
        self.medicines_en = self.db['medicines_en']
        
        if not MISTRAL_API_KEY:
            raise ValueError("MISTRAL_API_KEY non définie")
        
        self.mistral = Mistral(api_key=MISTRAL_API_KEY)
        self.model = "mistral-small-latest"
        self.translation_count = 0
    
    def translate_text(self, text: str) -> str:
        """Traduit un texte avec gestion du rate limiting"""
        if not text or not isinstance(text, str):
            return text
        
        text_stripped = text.strip()
        if len(text_stripped) < 2:
            return text
        
        # Ne pas traduire les nombres
        if text_stripped.replace('.', '').replace(',', '').replace(' ', '').isdigit():
            return text
        
        max_retries = 3
        for attempt in range(max_retries):
            try:
                self.translation_count += 1
                if self.translation_count % 10 == 0:
                    print(f"      [{self.translation_count} traductions...]")
                
                response = self.mistral.chat.complete(
                    model=self.model,
                    messages=[
                        {
                            "role": "system",
                            "content": """You are a medical translator. Translate from French to English.
Rules:
- Keep medication names unchanged
- Keep chemical/scientific names unchanged
- Keep ALL HTML tags exactly as they are
- Keep dosages and numbers unchanged
- Translate only the French descriptive text
- Return ONLY the translation"""
                        },
                        {
                            "role": "user",
                            "content": text
                        }
                    ],
                    temperature=0.1,
                    max_tokens=2000
                )
                
                translated = response.choices[0].message.content.strip()
                
                # Délai pour éviter rate limiting
                time.sleep(0.8)
                return translated
                
            except Exception as e:
                error_str = str(e)
                if "429" in error_str or "rate" in error_str.lower():
                    wait_time = (attempt + 1) * 3
                    print(f"        [RATE LIMIT] Pause {wait_time}s... (tentative {attempt + 1}/{max_retries})")
                    time.sleep(wait_time)
                    if attempt == max_retries - 1:
                        print(f"        [ERROR] Échec après {max_retries} tentatives: {e}")
                        return text
                else:
                    print(f"        [ERROR] Erreur traduction: {e}")
                    return text
        
        return text
    
    def translate_content_item(self, item: Dict) -> Dict:
        """Traduit un élément de contenu"""
        if not isinstance(item, dict):
            return item
        
        result = dict(item)
        
        # Texte simple
        if 'text' in item and item['text']:
            result['text'] = self.translate_text(item['text'])
        
        if 'html_content' in item and item['html_content']:
            result['html_content'] = self.translate_text(item['html_content'])
        
        # Tableaux
        if 'table' in item and isinstance(item['table'], list):
            result['table'] = []
            for row in item['table']:
                if isinstance(row, list):
                    translated_row = []
                    for cell in row:
                        if isinstance(cell, str):
                            translated_row.append(self.translate_text(cell))
                        else:
                            translated_row.append(cell)
                    result['table'].append(translated_row)
                else:
                    result['table'].append(row)
        
        # Headers
        if 'headers' in item and isinstance(item['headers'], list):
            result['headers'] = []
            for header in item['headers']:
                if isinstance(header, str):
                    result['headers'].append(self.translate_text(header))
                else:
                    result['headers'].append(header)
        
        # Caption
        if 'caption' in item and item['caption']:
            result['caption'] = self.translate_text(item['caption'])
        
        return result
    
    def translate_subsection(self, subsection: Dict) -> Dict:
        """Traduit une sous-section"""
        if not isinstance(subsection, dict):
            return subsection
        
        result = dict(subsection)
        
        # Titre
        if 'title' in subsection and subsection['title']:
            result['title'] = self.translate_text(subsection['title'])
        
        # Contenu
        if 'content' in subsection and isinstance(subsection['content'], list):
            result['content'] = []
            for item in subsection['content']:
                if isinstance(item, dict):
                    result['content'].append(self.translate_content_item(item))
                elif isinstance(item, str):
                    result['content'].append(self.translate_text(item))
                else:
                    result['content'].append(item)
        
        return result
    
    def translate_section(self, section: Dict) -> Dict:
        """Traduit une section complète"""
        if not isinstance(section, dict):
            return section
        
        result = dict(section)
        
        # Titre
        if 'title' in section and section['title']:
            result['title'] = self.translate_text(section['title'])
        
        # Contenu direct
        if 'content' in section and isinstance(section['content'], list):
            result['content'] = []
            for item in section['content']:
                if isinstance(item, dict):
                    result['content'].append(self.translate_content_item(item))
                elif isinstance(item, str):
                    result['content'].append(self.translate_text(item))
                else:
                    result['content'].append(item)
        
        # Sous-sections
        if 'subsections' in section and isinstance(section['subsections'], list):
            result['subsections'] = []
            for subsection in section['subsections']:
                result['subsections'].append(self.translate_subsection(subsection))
        
        return result
    
    def translate_medicine_complete(self, medicine: Dict) -> Dict:
        """Traduit COMPLÈTEMENT un médicament"""
        print(f"\n{'='*70}")
        print(f"TRADUCTION: {medicine.get('title', 'Unknown')}")
        print(f"{'='*70}")
        
        translated = dict(medicine)
        self.translation_count = 0
        
        # 1. Titre
        print("\n  [1/6] Titre...")
        if 'title' in translated and translated['title']:
            translated['title'] = self.translate_text(translated['title'])
            print(f"    ✓ {medicine['title']} → {translated['title']}")
        
        # 2. Métadonnées
        print("\n  [2/6] Métadonnées...")
        meta_fields = ['type_medicament', 'famille_therapeutique', 'groupe_anatomique']
        for field in meta_fields:
            if field in translated and translated[field]:
                original = translated[field]
                translated[field] = self.translate_text(original)
                print(f"    ✓ {field}")
        
        # 3. Détails
        print("\n  [3/6] Détails du médicament...")
        if 'medicine_details' in translated:
            if 'forme' in translated['medicine_details'] and translated['medicine_details']['forme']:
                original = translated['medicine_details']['forme']
                translated['medicine_details']['forme'] = self.translate_text(original)
                print(f"    ✓ forme: {original} → {translated['medicine_details']['forme']}")
        
        # 4. Résumé IA
        print("\n  [4/6] Résumé IA...")
        if 'ai_summary' in translated and translated['ai_summary']:
            translated['ai_summary'] = self.translate_text(translated['ai_summary'])
            print(f"    ✓ Résumé traduit")
        
        # 5. Sections (le plus important)
        print("\n  [5/6] Sections complètes (avec tableaux)...")
        if 'sections' in translated and isinstance(translated['sections'], list):
            total_sections = len(medicine['sections'])
            translated['sections'] = []
            
            for idx, section in enumerate(medicine['sections'], 1):
                print(f"\n    Section {idx}/{total_sections}: {section.get('title', 'Sans titre')[:60]}")
                translated_section = self.translate_section(section)
                translated['sections'].append(translated_section)
                print(f"    ✓ Section {idx} terminée")
        
        # 6. Marquer comme traduit
        print("\n  [6/6] Finalisation...")
        translated['language'] = 'en'
        translated['original_id'] = medicine.get('_id')
        translated['original_name'] = medicine.get('title')
        
        print(f"\n  ✅ TRADUCTION TERMINÉE")
        print(f"  Total de traductions: {self.translation_count}")
        print(f"{'='*70}\n")
        
        return translated
    
    def find_medicine(self, search_term: str) -> Dict:
        """Trouve un médicament par nom"""
        # Recherche exacte
        medicine = self.medicines_fr.find_one({
            "title": {"$regex": f"^{re.escape(search_term)}", "$options": "i"}
        })
        
        if medicine:
            return medicine
        
        # Recherche partielle
        medicine = self.medicines_fr.find_one({
            "title": {"$regex": re.escape(search_term), "$options": "i"}
        })
        
        return medicine
    
    def translate_and_save(self, search_term: str):
        """Trouve, traduit et sauvegarde un médicament"""
        print(f"\n{'#'*70}")
        print(f"# Recherche: {search_term}")
        print(f"{'#'*70}")
        
        # Trouver le médicament
        medicine = self.find_medicine(search_term)
        
        if not medicine:
            print(f"❌ Médicament non trouvé: {search_term}")
            return False
        
        print(f"✓ Trouvé: {medicine['title']}")
        print(f"  ID: {medicine['_id']}")
        
        # Traduire complètement
        translated = self.translate_medicine_complete(medicine)
        
        # Supprimer l'ancien _id
        if '_id' in translated:
            del translated['_id']
        
        # Sauvegarder
        print(f"\nSauvegarde dans 'medicines_en'...")
        
        # Supprimer l'ancienne version
        self.medicines_en.delete_one({'original_id': medicine['_id']})
        
        # Insérer la nouvelle
        result = self.medicines_en.insert_one(translated)
        print(f"✅ Sauvegardé avec l'ID: {result.inserted_id}")
        
        return True
    
    def run(self):
        """Lance la traduction des 4 médicaments"""
        print("\n" + "="*70)
        print(" TRADUCTION DE 4 MÉDICAMENTS")
        print(" (Ibuprofen, Paracetamol, Amoxicillin, Omeprazole)")
        print("="*70)
        
        success_count = 0
        
        for med_name in MEDICINES_TO_TRANSLATE:
            try:
                if self.translate_and_save(med_name):
                    success_count += 1
                    print(f"\n✅ {med_name} traduit avec succès!")
                else:
                    print(f"\n❌ Échec pour {med_name}")
                
                # Pause entre les médicaments
                print("\nPause de 5 secondes avant le suivant...")
                time.sleep(5)
                
            except Exception as e:
                print(f"\n❌ ERREUR pour {med_name}: {e}")
        
        print(f"\n{'='*70}")
        print(f" RÉSUMÉ: {success_count}/{len(MEDICINES_TO_TRANSLATE)} médicaments traduits")
        print(f"{'='*70}\n")


if __name__ == "__main__":
    translator = MedicineTranslator()
    translator.run()
