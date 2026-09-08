"""
Script pour pré-traduire COMPLÈTEMENT les 4 médicaments en anglais
Y COMPRIS tous les tableaux, sections, sous-sections
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

# Les 4 médicaments à traduire complètement
MEDICINES_TO_TRANSLATE = [
    {"name": "EFFERALGANMED", "desc": "Paracétamol"},
    {"name": "AMOXICILLINE", "desc": "Amoxicilline"},
    {"name": "IBUPROFENE ARROW 400", "desc": "Ibuprofène"},
    {"name": "ESOMEPRAZOLE ALMUS 20", "desc": "Esoméprazole/Oméprazole"}
]


class CompleteTranslator:
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
    
    def translate_text(self, text: str, context: str = "medical") -> str:
        """Traduit un texte du français vers l'anglais avec Mistral"""
        if not text or not isinstance(text, str):
            return text
        
        # Ne pas traduire les textes trop courts
        text_stripped = text.strip()
        if len(text_stripped) < 2:
            return text
        
        # Ne pas traduire les nombres purs
        if text_stripped.replace('.', '').replace(',', '').replace(' ', '').isdigit():
            return text
        
        try:
            self.translation_count += 1
            if self.translation_count % 10 == 0:
                print(f"      [{self.translation_count} traductions effectuées]")
            
            response = self.mistral.chat.complete(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": f"""You are a medical translator. Translate from French to English.
Rules:
- Keep medication names unchanged (Paracétamol, Ibuprofène, Amoxicilline, etc.)
- Keep chemical/scientific names unchanged
- Keep ALL HTML tags (<p>, <strong>, <em>, etc.) exactly as they are
- Keep dosages and numbers unchanged (400 mg, 20 mg, etc.)
- Translate only the French descriptive text
- Return ONLY the translation, no explanations or comments"""
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
            time.sleep(0.3)  # Rate limiting pour éviter les erreurs API
            return translated
            
        except Exception as e:
            print(f"        [ERROR] Translation error: {e}")
            time.sleep(1)  # Attendre avant de réessayer
            return text
    
    def translate_content_item(self, item: Dict) -> Dict:
        """Traduit un élément de contenu (texte ou tableau)"""
        result = dict(item)
        
        # Si c'est un texte simple
        if 'text' in item:
            original = item['text']
            result['text'] = self.translate_text(original, "content text")
            
            # Si html_content existe, le traduire aussi
            if 'html_content' in item:
                result['html_content'] = self.translate_text(item['html_content'], "html content")
        
        # Si c'est un tableau
        if 'table' in item and isinstance(item['table'], list):
            result['table'] = []
            
            # Traduire chaque ligne du tableau
            for row_idx, row in enumerate(item['table']):
                translated_row = []
                for cell in row:
                    if isinstance(cell, str):
                        translated_cell = self.translate_text(cell, "table cell")
                        translated_row.append(translated_cell)
                    else:
                        translated_row.append(cell)
                result['table'].append(translated_row)
            
            # Traduire les headers si présents
            if 'headers' in item and isinstance(item['headers'], list):
                result['headers'] = []
                for header in item['headers']:
                    if isinstance(header, str):
                        result['headers'].append(self.translate_text(header, "table header"))
                    else:
                        result['headers'].append(header)
            
            # Traduire le caption si présent
            if 'caption' in item and item['caption']:
                result['caption'] = self.translate_text(item['caption'], "table caption")
        
        return result
    
    def translate_subsection(self, subsection: Dict) -> Dict:
        """Traduit une sous-section complète"""
        result = dict(subsection)
        
        # Traduire le titre
        if 'title' in subsection and subsection['title']:
            result['title'] = self.translate_text(subsection['title'], "subsection title")
        
        # Traduire le contenu
        if 'content' in subsection and isinstance(subsection['content'], list):
            result['content'] = []
            for item in subsection['content']:
                if isinstance(item, dict):
                    result['content'].append(self.translate_content_item(item))
                elif isinstance(item, str):
                    result['content'].append(self.translate_text(item, "subsection content"))
                else:
                    result['content'].append(item)
        
        return result
    
    def translate_section(self, section: Dict) -> Dict:
        """Traduit une section complète avec ses sous-sections"""
        result = dict(section)
        
        # Traduire le titre
        if 'title' in section and section['title']:
            result['title'] = self.translate_text(section['title'], "section title")
        
        # Traduire le contenu direct
        if 'content' in section and isinstance(section['content'], list):
            result['content'] = []
            for item in section['content']:
                if isinstance(item, dict):
                    result['content'].append(self.translate_content_item(item))
                elif isinstance(item, str):
                    result['content'].append(self.translate_text(item, "section content"))
                else:
                    result['content'].append(item)
        
        # Traduire les sous-sections
        if 'subsections' in section and isinstance(section['subsections'], list):
            result['subsections'] = []
            for subsection in section['subsections']:
                result['subsections'].append(self.translate_subsection(subsection))
        
        return result
    
    def translate_medicine_complete(self, medicine: Dict) -> Dict:
        """Traduit COMPLÈTEMENT un médicament"""
        print(f"\n{'='*60}")
        print(f"TRADUCTION COMPLÈTE: {medicine.get('title', 'Unknown')}")
        print(f"{'='*60}")
        
        # Créer une copie
        translated = dict(medicine)
        self.translation_count = 0
        
        # 1. Traduire le titre
        print("\n  [1/6] Titre principal...")
        if 'title' in translated:
            translated['title'] = self.translate_text(translated['title'], "medicine title")
            print(f"    ✓ {medicine['title']} → {translated['title']}")
        
        # 2. Traduire les métadonnées
        print("\n  [2/6] Métadonnées (type, famille, groupe)...")
        meta_fields = ['type_medicament', 'famille_therapeutique', 'groupe_anatomique']
        for field in meta_fields:
            if field in translated and translated[field]:
                original = translated[field]
                translated[field] = self.translate_text(original, "metadata")
                print(f"    ✓ {field}: {original} → {translated[field]}")
        
        # 3. Traduire medicine_details
        print("\n  [3/6] Détails du médicament...")
        if 'medicine_details' in translated:
            md = translated['medicine_details']
            
            # Forme
            if 'forme' in md:
                original = md['forme']
                md['forme'] = self.translate_text(original, "pharmaceutical form")
                print(f"    ✓ forme: {original} → {md['forme']}")
            
            # Laboratoire (garder tel quel généralement)
            if 'laboratoire' in md:
                print(f"    ✓ laboratoire: {md['laboratoire']} (unchanged)")
            
            # Substances actives (liste)
            if 'substances_actives' in md and isinstance(md['substances_actives'], list):
                print(f"    ✓ substances_actives: {len(md['substances_actives'])} items (chemical names unchanged)")
        
        # 4. Traduire le résumé IA
        print("\n  [4/6] Résumé IA...")
        if 'ai_summary' in translated and translated['ai_summary']:
            original_summary = translated['ai_summary']
            translated['ai_summary'] = self.translate_text(original_summary, "AI summary")
            print(f"    ✓ Résumé traduit ({len(original_summary)} → {len(translated['ai_summary'])} chars)")
        
        # 5. Traduire TOUTES les sections (c'est le plus important)
        print("\n  [5/6] Sections complètes (avec tableaux)...")
        if 'sections' in translated and isinstance(translated['sections'], list):
            translated['sections'] = []
            total_sections = len(medicine['sections'])
            
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
        print(f"{'='*60}\n")
        
        return translated
    
    def find_medicine(self, name: str) -> Dict:
        """Trouve un médicament par son nom"""
        # Recherche exacte au début
        medicine = self.medicines_fr.find_one({
            "title": {"$regex": f"^{re.escape(name)}", "$options": "i"}
        })
        
        if medicine:
            return medicine
        
        # Recherche partielle
        medicine = self.medicines_fr.find_one({
            "title": {"$regex": re.escape(name), "$options": "i"}
        })
        
        return medicine
    
    def translate_and_save(self, medicine_name: str, description: str):
        """Trouve, traduit et sauvegarde un médicament"""
        print(f"\n{'#'*70}")
        print(f"# Recherche: {description} ({medicine_name})")
        print(f"{'#'*70}")
        
        # Trouver le médicament
        medicine = self.find_medicine(medicine_name)
        
        if not medicine:
            print(f"❌ Médicament non trouvé: {medicine_name}")
            return False
        
        print(f"✓ Trouvé: {medicine['title']}")
        print(f"  ID: {medicine['_id']}")
        
        # Traduire complètement
        translated = self.translate_medicine_complete(medicine)
        
        # Supprimer l'ancien _id pour insérer un nouveau
        if '_id' in translated:
            del translated['_id']
        
        # Sauvegarder
        print(f"\nSauvegarde dans 'medicines_en'...")
        
        # Supprimer l'ancienne version si elle existe
        self.medicines_en.delete_one({
            'original_id': medicine['_id']
        })
        
        # Insérer la nouvelle version
        result = self.medicines_en.insert_one(translated)
        print(f"✅ Sauvegardé avec l'ID: {result.inserted_id}")
        
        return True
    
    def run(self):
        """Lance la traduction de tous les médicaments"""
        print("\n" + "="*70)
        print(" TRADUCTION COMPLÈTE DES 4 MÉDICAMENTS")
        print(" (Y compris tous les tableaux et sections)")
        print("="*70)
        
        success_count = 0
        
        for med in MEDICINES_TO_TRANSLATE:
            try:
                if self.translate_and_save(med['name'], med['desc']):
                    success_count += 1
                    print(f"\n✅ {med['desc']} traduit avec succès!")
                else:
                    print(f"\n❌ Échec pour {med['desc']}")
                
                # Pause entre les médicaments
                print("\nPause de 2 secondes avant le suivant...")
                time.sleep(2)
                
            except Exception as e:
                print(f"\n❌ ERREUR pour {med['desc']}: {e}")
        
        print(f"\n{'='*70}")
        print(f" RÉSUMÉ: {success_count}/{len(MEDICINES_TO_TRANSLATE)} médicaments traduits")
        print(f"{'='*70}\n")


if __name__ == "__main__":
    translator = CompleteTranslator()
    translator.run()
