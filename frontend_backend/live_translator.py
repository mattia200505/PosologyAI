"""
Traducteur simple pour les médicaments
Version stable - utilise les traductions pré-stockées en base
"""
import os
import re
from typing import Dict, List
from mistralai import Mistral
from dotenv import load_dotenv

load_dotenv()

class LiveMedicineTranslator:
    def __init__(self):
        self.mistral_api_key = os.getenv('MISTRAL_API_KEY')
        if not self.mistral_api_key:
            raise ValueError("MISTRAL_API_KEY non définie")
        
        self.mistral_client = Mistral(api_key=self.mistral_api_key)
        self.model = "mistral-small-latest"
    
    def translate_medicine(self, medicine: Dict, include_summary: bool = True) -> Dict:
        """
        Version simple - retourne le médicament tel quel
        Les traductions sont gérées par les données pré-traduites en base
        """
        # Ne fait rien - les traductions doivent être pré-stockées
        return medicine
    
    def translate_summary_only(self, summary: str) -> str:
        """Traduit uniquement un résumé IA en anglais"""
        try:
            response = self.mistral_client.chat.complete(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": """You are a medical translator. Translate the medication summary from French to English.
Keep ALL HTML tags intact. Do NOT translate drug names or scientific terms."""
                    },
                    {
                        "role": "user",
                        "content": f"Translate to English:\n\n{summary}"
                    }
                ],
                temperature=0.2,
                max_tokens=1000
            )
            
            return response.choices[0].message.content.strip()
            
        except Exception as e:
            print(f"[ERROR] Erreur de traduction du résumé: {e}")
            return summary

    def translate_titles_batch(self, titles: List[str]) -> List[str]:
        """Traduit une liste de titres de médicaments en anglais"""
        if not titles:
            return titles
        
        try:
            titles_text = "\n".join([f"{i+1}. {title}" for i, title in enumerate(titles)])
            
            response = self.mistral_client.chat.complete(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": """Translate medication titles from French to English.
Keep medication names UNCHANGED. Translate only descriptive parts (comprimé, gélule, solution, etc.).
Keep dosages unchanged. Return ONLY the numbered list, one per line."""
                    },
                    {
                        "role": "user",
                        "content": f"Translate:\n\n{titles_text}"
                    }
                ],
                temperature=0.2,
                max_tokens=2000
            )
            
            result = response.choices[0].message.content.strip()
            translated = []
            
            for line in result.split('\n'):
                line = line.strip()
                if line:
                    match = re.match(r'^\d+[\.\)]\s*(.+)$', line)
                    if match:
                        translated.append(match.group(1))
            
            if len(translated) == len(titles):
                print(f"[TRANSLATION] {len(titles)} titres traduits")
                return translated
            
            return titles
                
        except Exception as e:
            print(f"[ERROR] Erreur traduction titres: {e}")
            return titles

    def translate_search_fields_batch(self, items: List[Dict]) -> List[Dict]:
        """Traduit les champs descriptifs pour les résultats de recherche"""
        if not items:
            return items
        
        texts_to_translate = set()
        
        for item in items:
            if item.get('medicine_details', {}).get('forme'):
                texts_to_translate.add(item['medicine_details']['forme'])
            if item.get('type_medicament'):
                texts_to_translate.add(item['type_medicament'])
            if item.get('groupe_anatomique'):
                texts_to_translate.add(item['groupe_anatomique'])
            if item.get('famille_therapeutique'):
                texts_to_translate.add(item['famille_therapeutique'])
        
        if not texts_to_translate:
            return items
            
        texts_list = list(texts_to_translate)[:50]
        
        try:
            texts_text = "\n".join([f"{i+1}. {text}" for i, text in enumerate(texts_list)])
            
            response = self.mistral_client.chat.complete(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": """Translate medical/pharmaceutical terms from French to English.
Keep scientific names unchanged. Return ONLY the numbered list."""
                    },
                    {
                        "role": "user",
                        "content": f"Translate:\n\n{texts_text}"
                    }
                ],
                temperature=0.2,
                max_tokens=2000
            )
            
            result = response.choices[0].message.content.strip()
            translated = []
            
            for line in result.split('\n'):
                line = line.strip()
                if line:
                    match = re.match(r'^\d+[\.\)]\s*(.+)$', line)
                    if match:
                        translated.append(match.group(1))
            
            # Créer le mapping
            translation_map = {}
            for i, original in enumerate(texts_list):
                if i < len(translated):
                    translation_map[original] = translated[i]
            
            print(f"[TRANSLATION] {len(translation_map)} termes traduits")
            
            # Appliquer
            for item in items:
                if item.get('medicine_details', {}).get('forme'):
                    orig = item['medicine_details']['forme']
                    if orig in translation_map:
                        item['medicine_details']['forme'] = translation_map[orig]
                
                if item.get('type_medicament'):
                    orig = item['type_medicament']
                    if orig in translation_map:
                        item['type_medicament'] = translation_map[orig]
                
                if item.get('groupe_anatomique'):
                    orig = item['groupe_anatomique']
                    if orig in translation_map:
                        item['groupe_anatomique'] = translation_map[orig]
                
                if item.get('famille_therapeutique'):
                    orig = item['famille_therapeutique']
                    if orig in translation_map:
                        item['famille_therapeutique'] = translation_map[orig]
            
            return items
            
        except Exception as e:
            print(f"[ERROR] Erreur traduction champs: {e}")
            return items
    
    def translate_text(self, text: str, context: str = "medical") -> str:
        """Traduit un texte simple du français vers l'anglais"""
        if not text or not isinstance(text, str) or len(text.strip()) < 2:
            return text
        
        # Ne pas traduire les nombres purs
        if text.strip().replace('.', '').replace(',', '').replace(' ', '').isdigit():
            return text
        
        try:
            response = self.mistral_client.chat.complete(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": """You are a medical translator. Translate from French to English.
Keep medication names, chemical names unchanged. Keep HTML tags intact. Return ONLY the translation."""
                    },
                    {
                        "role": "user",
                        "content": text
                    }
                ],
                temperature=0.1,
                max_tokens=2000
            )
            
            # Délai plus long pour éviter le rate limiting
            import time
            time.sleep(0.5)
            
            return response.choices[0].message.content.strip()
            
        except Exception as e:
            error_str = str(e)
            # Si erreur de rate limit, attendre plus longtemps et réessayer une fois
            if "429" in error_str or "rate" in error_str.lower():
                print(f"[TRANSLATION] ⏳ Rate limit, pause 3s...")
                import time
                time.sleep(3)
                try:
                    response = self.mistral_client.chat.complete(
                        model=self.model,
                        messages=[
                            {
                                "role": "system",
                                "content": """You are a medical translator. Translate from French to English.
Keep medication names, chemical names unchanged. Keep HTML tags intact. Return ONLY the translation."""
                            },
                            {
                                "role": "user",
                                "content": text
                            }
                        ],
                        temperature=0.1,
                        max_tokens=2000
                    )
                    time.sleep(0.5)
                    return response.choices[0].message.content.strip()
                except:
                    print(f"[ERROR] Translation failed after retry: {e}")
                    return text
            else:
                print(f"[ERROR] Translation error: {e}")
                return text
    
    def translate_content_item(self, item: Dict) -> Dict:
        """Traduit un élément de contenu (texte ou tableau)"""
        if not isinstance(item, dict):
            return item
        
        result = dict(item)
        
        # Traduire texte simple
        if 'text' in result and result['text']:
            result['text'] = self.translate_text(result['text'])
        
        if 'html_content' in result and result['html_content']:
            result['html_content'] = self.translate_text(result['html_content'])
        
        # Traduire tableau
        if 'table' in result and isinstance(result['table'], list):
            translated_table = []
            for row in result['table']:
                if isinstance(row, list):
                    translated_row = [self.translate_text(str(cell)) if isinstance(cell, str) else cell for cell in row]
                    translated_table.append(translated_row)
                else:
                    translated_table.append(row)
            result['table'] = translated_table
        
        # Traduire headers
        if 'headers' in result and isinstance(result['headers'], list):
            result['headers'] = [self.translate_text(h) if isinstance(h, str) else h for h in result['headers']]
        
        # Traduire caption
        if 'caption' in result and result['caption']:
            result['caption'] = self.translate_text(result['caption'])
        
        return result
    
    def translate_subsection(self, subsection: Dict) -> Dict:
        """Traduit une sous-section complète"""
        if not isinstance(subsection, dict):
            return subsection
        
        result = dict(subsection)
        
        # Traduire titre
        if 'title' in result and result['title']:
            result['title'] = self.translate_text(result['title'])
        
        # Traduire contenu
        if 'content' in result and isinstance(result['content'], list):
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
        """Traduit une section complète avec sous-sections"""
        if not isinstance(section, dict):
            return section
        
        result = dict(section)
        
        # Traduire titre
        if 'title' in result and result['title']:
            result['title'] = self.translate_text(result['title'])
        
        # Traduire contenu direct
        if 'content' in result and isinstance(result['content'], list):
            result['content'] = []
            for item in section['content']:
                if isinstance(item, dict):
                    result['content'].append(self.translate_content_item(item))
                elif isinstance(item, str):
                    result['content'].append(self.translate_text(item))
                else:
                    result['content'].append(item)
        
        # Traduire sous-sections
        if 'subsections' in result and isinstance(result['subsections'], list):
            result['subsections'] = [self.translate_subsection(sub) for sub in result['subsections']]
        
        return result
    
    def translate_medicine_full(self, medicine: Dict) -> Dict:
        """Traduit COMPLÈTEMENT un médicament (sections, tableaux, tout)"""
        print(f"[TRANSLATION] Traduction complète de: {medicine.get('title', 'Unknown')}")
        
        result = dict(medicine)
        translation_count = 0
        
        # 1. Titre
        if 'title' in result and result['title']:
            result['title'] = self.translate_text(result['title'])
            translation_count += 1
        
        # 2. Métadonnées
        meta_fields = ['type_medicament', 'famille_therapeutique', 'groupe_anatomique']
        for field in meta_fields:
            if field in result and result[field]:
                result[field] = self.translate_text(result[field])
                translation_count += 1
        
        # 3. Détails du médicament
        if 'medicine_details' in result:
            if 'forme' in result['medicine_details'] and result['medicine_details']['forme']:
                result['medicine_details']['forme'] = self.translate_text(result['medicine_details']['forme'])
                translation_count += 1
        
        # 4. Résumé IA
        if 'ai_summary' in result and result['ai_summary']:
            result['ai_summary'] = self.translate_summary_only(result['ai_summary'])
            translation_count += 1
        
        # 5. TOUTES les sections (le plus important)
        if 'sections' in result and isinstance(result['sections'], list):
            print(f"[TRANSLATION] Traduction de {len(result['sections'])} sections...")
            result['sections'] = []
            for i, section in enumerate(medicine['sections'], 1):
                if i % 5 == 0:
                    print(f"  Section {i}/{len(medicine['sections'])}...")
                result['sections'].append(self.translate_section(section))
                translation_count += 10  # Approximation
        
        print(f"[TRANSLATION] ✅ Traduction complète terminée (~{translation_count} éléments)")
        return result


# Instance globale
_translator = None

def get_live_translator():
    global _translator
    if _translator is None:
        try:
            _translator = LiveMedicineTranslator()
        except ValueError as e:
            print(f"[WARNING] LiveTranslator non disponible: {e}")
            return None
    return _translator
