"""
Script pour pré-traduire des médicaments complets en anglais
et les stocker dans une collection MongoDB dédiée 'medicines_en'
"""
import os
import time
import json
import re
from typing import Dict, List, Any
from pymongo import MongoClient
from mistralai.client import Mistral
from dotenv import load_dotenv

load_dotenv()

# Configuration
MONGO_URI = os.getenv('MONGO_URI', 'mongodb://localhost:27017')
MISTRAL_API_KEY = os.getenv('MISTRAL_API_KEY')

# Médicaments à traduire
MEDICINES_TO_TRANSLATE = [
    "BISACODYL BIOGARAN CONSEIL 5 mg, comprimé gastro-résistant"
]


class MedicinePreTranslator:
    def __init__(self):
        self.mongo_client = MongoClient(MONGO_URI)
        self.db = self.mongo_client['medicsearch']
        self.medicines_fr = self.db['medicines']
        self.medicines_en = self.db['medicines_en']
        
        if not MISTRAL_API_KEY:
            raise ValueError("MISTRAL_API_KEY non définie")
        
        self.mistral = Mistral(api_key=MISTRAL_API_KEY)
        self.model = "mistral-small-latest"
    
    def find_medicine(self, name: str) -> Dict:
        """Trouve un médicament par son nom (recherche partielle)"""
        # Recherche dans le titre (champ principal)
        medicine = self.medicines_fr.find_one({
            "title": {"$regex": f"^{re.escape(name)}", "$options": "i"}
        })
        
        if medicine:
            return medicine
        
        # Recherche plus large dans le titre
        medicine = self.medicines_fr.find_one({
            "title": {"$regex": re.escape(name), "$options": "i"}
        })
        
        return medicine
    
    def translate_text(self, text: str, context: str = "medical") -> str:
        """Traduit un texte du français vers l'anglais"""
        if not text or not isinstance(text, str):
            return text
        
        # Ne pas traduire les textes trop courts ou numériques
        if len(text.strip()) < 3 or text.replace('.', '').replace(',', '').isdigit():
            return text
        
        try:
            response = self.mistral.chat.complete(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": f"""You are a medical translator. Translate the following French {context} text to English.
Rules:
- Keep ALL HTML tags intact exactly as they are
- Keep medication names (like Paracétamol, Ibuprofène) unchanged  
- Keep scientific/chemical names unchanged
- Keep dosages and numbers unchanged
- Keep abbreviations unchanged
- Translate only the French descriptive text
- Return ONLY the translation, no explanations"""
                    },
                    {
                        "role": "user",
                        "content": text
                    }
                ],
                temperature=0.1,
                max_tokens=4000
            )
            
            return response.choices[0].message.content.strip()
            
        except Exception as e:
            print(f"  [ERROR] Erreur de traduction: {e}")
            return text
    
    def translate_dict_recursive(self, obj: Any, depth: int = 0, path: str = "") -> Any:
        """Traduit récursivement tous les textes d'un dictionnaire"""
        if depth > 10:  # Protection contre la récursion infinie
            return obj
        
        if isinstance(obj, str):
            # Ne pas traduire certains champs
            skip_patterns = ['_id', 'url', 'link', 'href', 'cis', 'code', 'bdpm']
            if any(p in path.lower() for p in skip_patterns):
                return obj
            
            translated = self.translate_text(obj)
            if translated != obj:
                print(f"  Traduit: {obj[:50]}... -> {translated[:50]}...")
            return translated
        
        elif isinstance(obj, dict):
            result = {}
            for key, value in obj.items():
                new_path = f"{path}.{key}" if path else key
                result[key] = self.translate_dict_recursive(value, depth + 1, new_path)
            return result
        
        elif isinstance(obj, list):
            return [self.translate_dict_recursive(item, depth + 1, path) for item in obj]
        
        else:
            return obj
    
    def translate_medicine_full(self, medicine: Dict) -> Dict:
        """Traduit un médicament complet"""
        # Créer une copie
        translated = dict(medicine)
        
        # Champs à traduire spécifiquement
        fields_to_translate = [
            'title',
            'type_medicament',
            'famille_therapeutique',
            'groupe_anatomique',
            'ai_summary'
        ]
        
        print("  Traduction des champs principaux...")
        for field in fields_to_translate:
            if field in translated and translated[field]:
                if isinstance(translated[field], str):
                    original = translated[field]
                    translated[field] = self.translate_text(original, "field")
                    print(f"    {field}: {original[:40]}... -> {translated[field][:40]}...")
                    time.sleep(0.3)  # Rate limiting
        
        # Traduire medicine_details
        if 'medicine_details' in translated:
            print("  Traduction de medicine_details...")
            md = translated['medicine_details']
            
            # Champs textuels de medicine_details
            md_fields = ['title', 'forme', 'substance_active', 'voie_administration']
            for field in md_fields:
                if field in md and md[field]:
                    original = md[field]
                    md[field] = self.translate_text(str(original), "medical term")
                    print(f"    {field}: {original[:40]}... -> {md[field][:40]}...")
                    time.sleep(0.3)
        
        # Traduire les sections (partie la plus importante)
        if 'sections' in translated:
            print("  Traduction des sections...")
            translated['sections'] = self.translate_sections(translated['sections'])
        
        # Marquer comme traduit
        translated['language'] = 'en'
        translated['original_id'] = medicine.get('_id')
        
        return translated
    
    def translate_sections(self, sections: List[Dict]) -> List[Dict]:
        """Traduit toutes les sections d'un médicament"""
        translated_sections = []
        
        for i, section in enumerate(sections):
            print(f"    Section {i+1}/{len(sections)}: {section.get('title', 'Sans titre')[:50]}")
            
            translated_section = dict(section)
            
            # Traduire le titre
            if 'title' in section:
                translated_section['title'] = self.translate_text(section['title'], "section title")
                time.sleep(0.2)
            
            # Traduire le contenu
            if 'content' in section:
                if isinstance(section['content'], str):
                    translated_section['content'] = self.translate_text(section['content'], "medical content")
                elif isinstance(section['content'], list):
                    translated_section['content'] = []
                    for item in section['content']:
                        if isinstance(item, str):
                            translated_section['content'].append(self.translate_text(item, "medical content"))
                        else:
                            translated_section['content'].append(item)
                        time.sleep(0.2)
            
            # Traduire les sous-sections
            if 'subsections' in section:
                translated_section['subsections'] = self.translate_subsections(section['subsections'])
            
            translated_sections.append(translated_section)
        
        return translated_sections
    
    def translate_subsections(self, subsections: List[Dict]) -> List[Dict]:
        """Traduit les sous-sections"""
        translated = []
        
        for sub in subsections:
            trans_sub = dict(sub)
            
            # Traduire le titre
            if 'title' in sub:
                trans_sub['title'] = self.translate_text(sub['title'], "subsection title")
                time.sleep(0.2)
            
            # Traduire le contenu
            if 'content' in sub:
                if isinstance(sub['content'], str):
                    trans_sub['content'] = self.translate_text(sub['content'], "medical content")
                elif isinstance(sub['content'], list):
                    trans_sub['content'] = []
                    for item in sub['content']:
                        if isinstance(item, str):
                            trans_sub['content'].append(self.translate_text(item, "medical content"))
                        elif isinstance(item, dict):
                            # C'est peut-être un tableau
                            trans_sub['content'].append(self.translate_table(item))
                        else:
                            trans_sub['content'].append(item)
                        time.sleep(0.2)
            
            translated.append(trans_sub)
        
        return translated
    
    def translate_table(self, table: Dict) -> Dict:
        """Traduit un tableau"""
        if not isinstance(table, dict):
            return table
        
        result = dict(table)
        
        # Traduire les headers
        if 'headers' in table and isinstance(table['headers'], list):
            result['headers'] = []
            for header in table['headers']:
                if isinstance(header, str):
                    result['headers'].append(self.translate_text(header, "table header"))
                else:
                    result['headers'].append(header)
        
        # Traduire les rows
        if 'rows' in table and isinstance(table['rows'], list):
            result['rows'] = []
            for row in table['rows']:
                if isinstance(row, list):
                    trans_row = []
                    for cell in row:
                        if isinstance(cell, str):
                            trans_row.append(self.translate_text(cell, "table cell"))
                        else:
                            trans_row.append(cell)
                    result['rows'].append(trans_row)
                else:
                    result['rows'].append(row)
        
        return result
    
    def save_translated(self, medicine: Dict):
        """Sauvegarde le médicament traduit"""
        # Utiliser le nom original comme identifiant
        original_name = medicine.get('original_name', medicine.get('nom', 'unknown'))
        
        # Mettre à jour ou insérer
        self.medicines_en.update_one(
            {'original_name': original_name},
            {'$set': medicine},
            upsert=True
        )
        
        print(f"  ✓ Sauvegardé dans medicines_en")
    
    def translate_all(self):
        """Traduit tous les médicaments de la liste"""
        print("=" * 60)
        print("PRÉ-TRADUCTION DES MÉDICAMENTS EN ANGLAIS")
        print("=" * 60)
        
        for name in MEDICINES_TO_TRANSLATE:
            print(f"\n{'='*40}")
            print(f"Recherche de: {name}")
            print("="*40)
            
            medicine = self.find_medicine(name)
            
            if not medicine:
                print(f"  ✗ Médicament '{name}' non trouvé!")
                continue
            
            print(f"  ✓ Trouvé: {medicine.get('title', 'N/A')}")
            print(f"    ID: {medicine.get('_id', 'N/A')}")
            
            # Vérifier si déjà traduit
            existing = self.medicines_en.find_one({'original_name': name})
            if existing:
                print(f"  → Déjà traduit, mise à jour...")
            
            # Traduire
            print("\n  Début de la traduction...")
            translated = self.translate_medicine_full(medicine)
            translated['original_name'] = name
            
            # Sauvegarder
            self.save_translated(translated)
            
            print(f"\n  ✓ {name} traduit avec succès!")
            
            # Pause entre les médicaments
            time.sleep(1)
        
        print("\n" + "=" * 60)
        print("TRADUCTION TERMINÉE")
        print("=" * 60)
        
        # Statistiques
        count = self.medicines_en.count_documents({})
        print(f"\nTotal de médicaments traduits en base: {count}")


def main():
    """Point d'entrée principal"""
    translator = MedicinePreTranslator()
    translator.translate_all()


if __name__ == "__main__":
    main()
