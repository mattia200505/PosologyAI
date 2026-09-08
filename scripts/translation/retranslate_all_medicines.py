"""
Re-traduire tous les médicaments déjà présents dans medicines_en
avec le code corrigé qui traduit TOUS les contenus
"""

from pymongo import MongoClient
from config import Config
from bson import ObjectId
from mistralai.client import Mistral
import time

class MedicineRetranslator:
    def __init__(self):
        self.client = MongoClient(Config.MONGO_URI)
        self.db = self.client['medicsearch']
        self.medicines_fr = self.db['medicines']
        self.medicines_en = self.db['medicines_en']
        self.mistral_client = Mistral(api_key=Config.MISTRAL_API_KEY)
        self.model = "mistral-small-latest"
        
    def translate_text(self, text, context="Texte médical"):
        """Traduit un texte en anglais avec Mistral"""
        if not text or not isinstance(text, str) or len(text.strip()) == 0:
            return text
            
        try:
            prompt = f"""Translate the following French medical text to English. 
Keep all medical terms accurate and professional. 
Return ONLY the English translation, nothing else.

French text: {text}"""

            response = self.mistral_client.chat.complete(
                model=self.model,
                messages=[{"role": "user", "content": prompt}]
            )
            
            translation = response.choices[0].message.content.strip()
            time.sleep(1.0)  # Rate limiting
            return translation
            
        except Exception as e:
            if "429" in str(e):
                print(f"   ⏳ Rate limit, attente 5s...")
                time.sleep(5.0)
                return self.translate_text(text, context)
            print(f"   ⚠️ Erreur traduction: {e}")
            return text
    
    def translate_section(self, section):
        """Traduit une section complète (titre, contenu, sous-sections, tableaux)"""
        translated_section = section.copy()
        translation_count = 0
        
        # Titre de section
        if 'title' in section:
            translated_section['title'] = self.translate_text(section['title'], "Titre de section")
            translation_count += 1
        
        # Contenu principal - CORRECTION: traduire tous les items avec 'text'
        if 'content' in section and isinstance(section['content'], list):
            translated_section['content'] = []
            for item in section['content']:
                if isinstance(item, dict):
                    # Si l'item a du texte (avec ou sans type='text')
                    if 'text' in item and isinstance(item['text'], str):
                        translated_item = item.copy()
                        translated_item['text'] = self.translate_text(item['text'], "Contenu médical")
                        translated_section['content'].append(translated_item)
                        translation_count += 1
                    elif item.get('type') == 'table':
                        translated_item = self.translate_table(item)
                        translated_section['content'].append(translated_item)
                        translation_count += translated_item.get('_translation_count', 0)
                    else:
                        translated_section['content'].append(item)
                else:
                    translated_section['content'].append(item)
        
        # Sous-sections (récursif)
        if 'subsections' in section and isinstance(section['subsections'], list):
            translated_section['subsections'] = []
            for subsection in section['subsections']:
                translated_subsection = self.translate_section(subsection)
                translated_section['subsections'].append(translated_subsection)
                translation_count += translated_subsection.get('_translation_count', 0)
        
        translated_section['_translation_count'] = translation_count
        return translated_section
    
    def translate_table(self, table_item):
        """Traduit un tableau (headers, cells, caption)"""
        translated_table = table_item.copy()
        translation_count = 0
        
        # En-têtes
        if 'headers' in table_item and isinstance(table_item['headers'], list):
            translated_table['headers'] = [
                self.translate_text(h, "En-tête de tableau") if isinstance(h, str) else h
                for h in table_item['headers']
            ]
            translation_count += len(table_item['headers'])
        
        # Cellules
        if 'cells' in table_item and isinstance(table_item['cells'], list):
            translated_table['cells'] = []
            for row in table_item['cells']:
                if isinstance(row, list):
                    translated_row = [
                        self.translate_text(cell, "Cellule de tableau") if isinstance(cell, str) else cell
                        for cell in row
                    ]
                    translated_table['cells'].append(translated_row)
                    translation_count += len([c for c in row if isinstance(c, str)])
        
        # Caption
        if 'caption' in table_item and isinstance(table_item['caption'], str):
            translated_table['caption'] = self.translate_text(table_item['caption'], "Légende de tableau")
            translation_count += 1
        
        translated_table['_translation_count'] = translation_count
        return translated_table
    
    def translate_medicine(self, medicine_fr):
        """Traduit un médicament complet"""
        translated = medicine_fr.copy()
        translation_count = 0
        
        # Métadonnées
        fields_to_translate = ['title', 'denomination', 'formePharmaceutique', 'voiesAdministration']
        for field in fields_to_translate:
            if field in medicine_fr and isinstance(medicine_fr[field], str):
                translated[field] = self.translate_text(medicine_fr[field], f"Métadonnée {field}")
                translation_count += 1
        
        # Résumé IA
        if 'ai_summary' in medicine_fr and isinstance(medicine_fr['ai_summary'], str):
            translated['ai_summary'] = self.translate_text(medicine_fr['ai_summary'], "Résumé IA")
            translation_count += 1
        
        # Sections
        if 'sections' in medicine_fr and isinstance(medicine_fr['sections'], list):
            translated['sections'] = []
            total_sections = len(medicine_fr['sections'])
            for i, section in enumerate(medicine_fr['sections'], 1):
                translated_section = self.translate_section(section)
                translated['sections'].append(translated_section)
                translation_count += translated_section.get('_translation_count', 0)
                print(f"      Section {i}/{total_sections}... ✓")
        
        return translated, translation_count
    
    def retranslate_all(self):
        """Re-traduit tous les médicaments de medicines_en"""
        print("\n" + "="*80)
        print("🔄 RE-TRADUCTION DE TOUS LES MÉDICAMENTS")
        print("="*80)
        
        # 1. Récupérer tous les médicaments actuels dans medicines_en
        existing_docs = list(self.medicines_en.find({}, {'_id': 1, 'original_id': 1, 'title': 1, 'denomination': 1}))
        
        if not existing_docs:
            print("❌ Aucun médicament trouvé dans medicines_en")
            return
        
        print(f"\n📊 Trouvé {len(existing_docs)} médicament(s) à re-traduire:")
        for doc in existing_docs:
            title = doc.get('title') or doc.get('denomination', 'N/A')
            print(f"   - {title} (ID: {doc.get('original_id')})")
        
        # 2. Pour chaque médicament, récupérer l'original français
        medicines_to_translate = []
        for doc in existing_docs:
            original_id = doc.get('original_id')
            if original_id:
                medicine_fr = self.medicines_fr.find_one({'_id': original_id})
                if medicine_fr:
                    medicines_to_translate.append({
                        'fr': medicine_fr,
                        'old_en_id': doc['_id']
                    })
        
        print(f"\n📋 {len(medicines_to_translate)} médicament(s) prêts pour re-traduction")
        
        # 3. Supprimer les anciennes traductions
        print("\n🗑️  Suppression des anciennes traductions...")
        result = self.medicines_en.delete_many({})
        print(f"   ✓ {result.deleted_count} document(s) supprimé(s)")
        
        # 4. Re-traduire chaque médicament
        print("\n" + "="*80)
        print("🌍 DÉBUT DE LA RE-TRADUCTION")
        print("="*80)
        
        for i, med_data in enumerate(medicines_to_translate, 1):
            medicine_fr = med_data['fr']
            title = medicine_fr.get('title') or medicine_fr.get('denomination', 'N/A')
            
            print(f"\n📋 Médicament {i}/{len(medicines_to_translate)}: {title}")
            print(f"   ID original: {medicine_fr['_id']}")
            
            try:
                # Traduire
                print("   Traduction en cours...")
                print("      Métadonnées... ✓")
                print("      Résumé IA... ✓")
                print(f"      Sections ({len(medicine_fr.get('sections', []))})...")
                
                translated_medicine, count = self.translate_medicine(medicine_fr)
                
                # Ajouter l'ID original
                translated_medicine['original_id'] = medicine_fr['_id']
                
                # Sauvegarder
                del translated_medicine['_id']
                result = self.medicines_en.insert_one(translated_medicine)
                
                print(f"\n   ✅ Traduction terminée: {count} éléments traduits")
                print(f"   💾 Sauvegardé avec ID: {result.inserted_id}")
                
                # Pause entre médicaments
                if i < len(medicines_to_translate):
                    print("   ⏳ Pause 5s avant le prochain...")
                    time.sleep(5.0)
                    
            except Exception as e:
                print(f"   ❌ ERREUR: {e}")
                continue
        
        print("\n" + "="*80)
        print("✅ RE-TRADUCTION TERMINÉE")
        print("="*80)
        
        # Statistiques finales
        final_count = self.medicines_en.count_documents({})
        print(f"\n📊 Total de médicaments traduits: {final_count}")


def main():
    translator = MedicineRetranslator()
    # Chercher le médicament en anglais
    med_en = translator.medicines_en.find_one({"title": {"$regex": "BISACODYL BIOGARAN CONSEIL 5 mg, comprimé gastro-résistant", "$options": "i"}})
    if med_en:
        print("Le médicament BISACODYL BIOGARAN CONSEIL 5 mg, comprimé gastro-résistant est déjà présent dans medicines_en. Aucune traduction nécessaire.")
        return
    # Chercher le médicament en français
    med_fr = translator.medicines_fr.find_one({"title": {"$regex": "BISACODYL BIOGARAN CONSEIL 5 mg, comprimé gastro-résistant", "$options": "i"}})
    if not med_fr:
        print("Médicament non trouvé dans la base française.")
        return
    print("Traduction du médicament BISACODYL BIOGARAN CONSEIL 5 mg, comprimé gastro-résistant...")
    translated_medicine, count = translator.translate_medicine(med_fr)
    translated_medicine['original_id'] = med_fr['_id']
    if '_id' in translated_medicine:
        del translated_medicine['_id']
    result = translator.medicines_en.insert_one(translated_medicine)
    print(f"✅ Traduction terminée ({count} éléments traduits), sauvegardé avec ID: {result.inserted_id}")


if __name__ == "__main__":
    main()
