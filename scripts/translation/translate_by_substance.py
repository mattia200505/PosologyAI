"""
Script de pré-traduction de médicaments par substance active (DCI)
Crée des versions anglaises complètes dans la collection medicines_en
"""

from pymongo import MongoClient
from mistralai.client import Mistral
import time
import os
from bson import ObjectId
from datetime import datetime
from config import Config

class MedicineTranslatorBySubstance:
    def __init__(self):
        # Configuration MongoDB
        self.mongo_uri = Config.MONGO_URI
        self.client = MongoClient(self.mongo_uri)
        self.db = self.client[Config.MONGO_DB]
        self.medicines_fr = self.db.medicines
        self.medicines_en = self.db.medicines_en
        
        # Configuration Mistral AI
        api_key = Config.MISTRAL_API_KEY
        if not api_key:
            raise ValueError("MISTRAL_API_KEY non trouvée dans config.py. Vérifiez votre fichier .env")
        self.mistral = Mistral(api_key=api_key)
        self.model = "mistral-small-latest"
        
        # Délais pour éviter rate limiting
        self.delay_between_translations = 1.0  # secondes entre traductions
        self.delay_between_medicines = 5.0     # secondes entre médicaments
        self.max_retries = 3
        
    def find_medicines_by_substance(self, substance_name):
        """
        Trouve des médicaments contenant une substance active donnée
        
        Args:
            substance_name: Nom de la substance (ex: "Paracetamol", "Ibuprofen")
        
        Returns:
            Liste de documents MongoDB
        """
        print(f"\n🔍 Recherche de médicaments contenant: {substance_name}")
        
        # Recherche dans plusieurs champs possibles
        query = {
            "$or": [
                {"title": {"$regex": substance_name, "$options": "i"}},
                {"denomination": {"$regex": substance_name, "$options": "i"}},
                {"substancesActives": {"$regex": substance_name, "$options": "i"}},
                {"dci": {"$regex": substance_name, "$options": "i"}},
                {"compositionQualitative": {"$regex": substance_name, "$options": "i"}}
            ]
        }
        
        medicines = list(self.medicines_fr.find(query).limit(5))  # Limite à 5 résultats
        
        if medicines:
            print(f"✅ Trouvé {len(medicines)} médicament(s):")
            for med in medicines:
                name = med.get('title') or med.get('denomination', 'N/A')
                print(f"   - {name} (ID: {med['_id']})")
        else:
            print(f"❌ Aucun médicament trouvé pour '{substance_name}'")
        
        return medicines
    
    def translate_text(self, text, context=""):
        """
        Traduit un texte français en anglais avec Mistral AI
        Gestion des erreurs de rate limiting
        """
        if not text or not isinstance(text, str) or text.strip() == "":
            return text
        
        for attempt in range(self.max_retries):
            try:
                time.sleep(self.delay_between_translations)
                
                messages = [
                    {
                        "role": "system",
                        "content": """Tu es un traducteur médical professionnel. 
Traduis UNIQUEMENT le texte fourni du français vers l'anglais médical précis.
Ne traduis PAS les noms de médicaments, DCI, ou noms commerciaux.
Garde les dosages, unités et valeurs numériques identiques.
Retourne SEULEMENT la traduction, sans commentaire."""
                    },
                    {
                        "role": "user",
                        "content": f"{context}\n\nTexte à traduire:\n{text}"
                    }
                ]
                
                response = self.mistral.chat.complete(
                    model=self.model,
                    messages=messages,
                    temperature=0.1
                )
                
                translation = response.choices[0].message.content.strip()
                return translation
                
            except Exception as e:
                error_msg = str(e)
                if "429" in error_msg or "rate_limit" in error_msg.lower():
                    wait_time = 3 * (attempt + 1)
                    print(f"⚠️ Rate limit atteint, attente {wait_time}s... (tentative {attempt + 1}/{self.max_retries})")
                    time.sleep(wait_time)
                    continue
                else:
                    print(f"[ERROR] Erreur de traduction: {error_msg}")
                    return text  # Retourne le texte original en cas d'erreur
        
        print(f"[ERROR] Échec de traduction après {self.max_retries} tentatives")
        return text
    
    def translate_medicine_document(self, medicine):
        """
        Traduit un document médicament complet
        
        Structure:
        - Champs à traduire: denomination, formePharmaceutique, descriptions, sections, etc.
        - Champs à conserver: _id, codeCIS, dateAMM, liens, statistiques, etc.
        """
        print(f"\n📋 Traduction de: {medicine.get('denomination', 'N/A')}")
        
        translated = medicine.copy()
        translated['original_id'] = medicine['_id']
        translated['_id'] = ObjectId()  # Nouvel ID pour la version anglaise
        translated['language'] = 'en'
        translated['translation_date'] = datetime.now()
        
        translation_count = 0
        
        # 1. MÉTADONNÉES PRINCIPALES
        print("   Métadonnées...")
        if 'denomination' in medicine:
            translated['denomination'] = self.translate_text(
                medicine['denomination'],
                "Nom de médicament (garde les noms propres)"
            )
            translation_count += 1
        
        if 'formePharmaceutique' in medicine:
            translated['formePharmaceutique'] = self.translate_text(
                medicine['formePharmaceutique'],
                "Forme pharmaceutique"
            )
            translation_count += 1
        
        # 2. RÉSUMÉ IA (si présent)
        if 'ai_summary' in medicine:
            print("   Résumé IA...")
            translated['ai_summary'] = self.translate_text(
                medicine['ai_summary'],
                "Résumé médical"
            )
            translation_count += 1
        
        # 3. SECTIONS PRINCIPALES
        if 'sections' in medicine and isinstance(medicine['sections'], list):
            print(f"   Sections ({len(medicine['sections'])})...")
            translated['sections'] = []
            
            for i, section in enumerate(medicine['sections'], 1):
                print(f"      Section {i}/{len(medicine['sections'])}...", end=" ")
                translated_section = self.translate_section(section)
                translated['sections'].append(translated_section)
                translation_count += translated_section.get('_translation_count', 0)
                print(f"✓")
        
        print(f"\n✅ Traduction terminée: {translation_count} éléments traduits")
        return translated
    
    def translate_section(self, section):
        """Traduit une section complète (titre, contenu, sous-sections, tableaux)"""
        translated_section = section.copy()
        translation_count = 0
        
        # Titre de section
        if 'title' in section:
            translated_section['title'] = self.translate_text(section['title'], "Titre de section")
            translation_count += 1
        
        # Contenu principal
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
        
        # Sous-sections
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
                    translation_count += len(row)
                else:
                    translated_table['cells'].append(row)
        
        # Légende
        if 'caption' in table_item:
            translated_table['caption'] = self.translate_text(table_item['caption'], "Légende de tableau")
            translation_count += 1
        
        translated_table['_translation_count'] = translation_count
        return translated_table
    
    def translate_and_save_medicine(self, medicine):
        """Traduit un médicament et le sauvegarde dans medicines_en"""
        # Vérifier si déjà traduit
        existing = self.medicines_en.find_one({'original_id': medicine['_id']})
        if existing:
            print(f"⚠️ Médicament déjà traduit (ID: {existing['_id']}). Ignoré.")
            return None
        
        # Traduire
        translated = self.translate_medicine_document(medicine)
        
        # Sauvegarder
        result = self.medicines_en.insert_one(translated)
        print(f"💾 Sauvegardé dans medicines_en avec ID: {result.inserted_id}")
        
        return translated
    
    def translate_medicines_by_substances(self, substances):
        """
        Traduit les médicaments pour plusieurs substances
        
        Args:
            substances: Liste de noms de substances (ex: ["Paracetamol", "Ibuprofen"])
        """
        print("="*80)
        print("🌍 TRADUCTION DE MÉDICAMENTS PAR SUBSTANCE ACTIVE")
        print("="*80)
        print(f"Substances recherchées: {', '.join(substances)}")
        print(f"Collection source: medicines")
        print(f"Collection destination: medicines_en")
        print("="*80)
        
        all_medicines = []
        
        # Récupérer tous les médicaments correspondants
        for substance in substances:
            medicines = self.find_medicines_by_substance(substance)
            all_medicines.extend(medicines)
        
        # Éliminer les doublons
        unique_medicines = {str(m['_id']): m for m in all_medicines}.values()
        
        print(f"\n📊 Total de {len(unique_medicines)} médicaments uniques à traduire")
        
        if not unique_medicines:
            print("❌ Aucun médicament à traduire. Arrêt.")
            return
        
        # Traduire chaque médicament
        for i, medicine in enumerate(unique_medicines, 1):
            print(f"\n{'='*80}")
            print(f"MÉDICAMENT {i}/{len(unique_medicines)}")
            print(f"{'='*80}")
            
            try:
                self.translate_and_save_medicine(medicine)
                
                if i < len(unique_medicines):
                    print(f"\n⏸️ Pause de {self.delay_between_medicines}s avant le prochain médicament...")
                    time.sleep(self.delay_between_medicines)
                    
            except Exception as e:
                print(f"❌ Erreur lors de la traduction: {str(e)}")
                continue
        
        print("\n" + "="*80)
        print("✅ TRADUCTION TERMINÉE")
        print("="*80)


def main():
    """Point d'entrée du script"""
    
    # Médicaments à traduire (noms commerciaux)
    SUBSTANCES_TO_TRANSLATE = [
        "ibuprofène arrow 400 mg, comprimé",
    ]
    
    print("\n🚀 Démarrage de la traduction...")
    print(f"Substances cibles: {', '.join(SUBSTANCES_TO_TRANSLATE)}\n")
    
    try:
        translator = MedicineTranslatorBySubstance()
        translator.translate_medicines_by_substances(SUBSTANCES_TO_TRANSLATE)
        
    except Exception as e:
        print(f"\n❌ ERREUR FATALE: {str(e)}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
