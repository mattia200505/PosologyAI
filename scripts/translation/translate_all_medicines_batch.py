"""
Script pour traduire TOUS les médicaments de la base de données
- Ne supprime pas les traductions existantes
- Utilise Google Translate (gratuit)
- Sauvegarde la progression pour pouvoir reprendre
"""

from pymongo import MongoClient
from deep_translator import GoogleTranslator
import time
import json
import os
from datetime import datetime

# Configuration
BATCH_SIZE = 50  # Nombre de médicaments par batch
DELAY_BETWEEN_TRANSLATIONS = 0.1  # Délai entre chaque traduction (éviter rate limiting)
PROGRESS_FILE = "translation_progress.json"

# Connexion MongoDB
client = MongoClient('mongodb://localhost:27017/')
db = client['medicsearch']

# Traducteur
translator = GoogleTranslator(source='fr', target='en')

def translate_text(text):
    """Traduit un texte du français vers l'anglais"""
    if not text or not isinstance(text, str) or len(text.strip()) == 0:
        return text
    
    try:
        # Google Translate a une limite de 5000 caractères
        if len(text) > 4500:
            # Découper en morceaux
            parts = []
            current = ""
            for sentence in text.split('. '):
                if len(current) + len(sentence) < 4500:
                    current += sentence + '. '
                else:
                    if current:
                        parts.append(current.strip())
                    current = sentence + '. '
            if current:
                parts.append(current.strip())
            
            translated_parts = []
            for part in parts:
                translated = translator.translate(part)
                translated_parts.append(translated)
                time.sleep(DELAY_BETWEEN_TRANSLATIONS)
            return ' '.join(translated_parts)
        else:
            result = translator.translate(text)
            time.sleep(DELAY_BETWEEN_TRANSLATIONS)
            return result
    except Exception as e:
        print(f"    [WARN] Erreur traduction: {e}")
        return text

def translate_table(table):
    """Traduit un tableau (liste de listes)"""
    if not table:
        return table
    
    translated_table = []
    for row in table:
        translated_row = []
        for cell in row:
            if isinstance(cell, str):
                translated_row.append(translate_text(cell))
            else:
                translated_row.append(cell)
        translated_table.append(translated_row)
    return translated_table

def translate_content(content_list):
    """Traduit une liste de contenus (texte, tableaux, listes)"""
    if not content_list:
        return content_list
    
    translated = []
    for item in content_list:
        new_item = {}
        
        if 'text' in item:
            new_item['text'] = translate_text(item['text'])
        
        if 'table' in item:
            new_item['table'] = translate_table(item['table'])
        
        if 'headers' in item:
            if isinstance(item['headers'], list):
                new_item['headers'] = [translate_text(h) if isinstance(h, str) else h for h in item['headers']]
            else:
                new_item['headers'] = item['headers']
        
        if 'list' in item:
            new_item['list'] = [translate_text(li) if isinstance(li, str) else li for li in item['list']]
        
        # Copier les autres champs
        for key in item:
            if key not in new_item:
                new_item[key] = item[key]
        
        translated.append(new_item)
    
    return translated

def translate_subsection(subsection):
    """Traduit une sous-section"""
    translated = {}
    
    if 'title' in subsection:
        translated['title'] = translate_text(subsection['title'])
    
    if 'content' in subsection:
        translated['content'] = translate_content(subsection['content'])
    
    # Copier les autres champs
    for key in subsection:
        if key not in translated:
            translated[key] = subsection[key]
    
    return translated

def translate_section(section):
    """Traduit une section complète"""
    translated = {}
    
    if 'title' in section:
        translated['title'] = translate_text(section['title'])
    
    if 'content' in section:
        translated['content'] = translate_content(section['content'])
    
    if 'subsections' in section:
        translated['subsections'] = [translate_subsection(sub) for sub in section['subsections']]
    
    # Copier les autres champs (sources, etc.)
    for key in section:
        if key not in translated:
            translated[key] = section[key]
    
    return translated

def translate_medicine(medicine):
    """Traduit un médicament complet"""
    translated = {}
    
    # ID original pour le lien
    translated['original_id'] = medicine['_id']
    
    # Titre
    if 'title' in medicine:
        translated['title'] = translate_text(medicine['title'])
    
    # Sections
    if 'sections' in medicine:
        translated['sections'] = [translate_section(s) for s in medicine['sections']]
    
    # Résumé IA
    if 'ai_summary' in medicine:
        translated['ai_summary'] = translate_text(medicine['ai_summary'])
    
    # Medicine details
    if 'medicine_details' in medicine:
        details = medicine['medicine_details'].copy()
        if 'forme' in details:
            details['forme'] = translate_text(details['forme'])
        if 'voie_administration' in details:
            details['voie_administration'] = translate_text(details['voie_administration'])
        translated['medicine_details'] = details
    
    # Copier les autres champs sans traduction
    fields_to_copy = ['substance_active', 'laboratoire', 'atc_code', 'atc_family', 
                      'dosage', 'cis_code', 'url', 'created_at', 'updated_at']
    for field in fields_to_copy:
        if field in medicine:
            translated[field] = medicine[field]
    
    translated['translated_at'] = datetime.now()
    translated['translation_source'] = 'google_translate_batch'
    
    return translated

def load_progress():
    """Charge la progression depuis le fichier"""
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE, 'r') as f:
            return json.load(f)
    return {'translated_ids': [], 'last_index': 0}

def save_progress(progress):
    """Sauvegarde la progression"""
    with open(PROGRESS_FILE, 'w') as f:
        json.dump(progress, f)


# --- Correction des tableaux non traduits dans medicines_en ---
FRENCH_TERMS = [
    'Poids', 'Clairance', 'créatinine', 'Intervalle d', 'journalière', 'heures minimum', 'comprimé',
    'Dose maximale', 'administration', 'Dose journalière', 'Enfant', 'Adulte', 'soit', 'par jour', 'minimum', 'mg', 'g', 'heures', 'tableau', 'Clairance de la créatinine'
]

def contains_french(cell):
    if not isinstance(cell, str):
        return False
    return any(term in cell for term in FRENCH_TERMS)

def table_needs_retranslation(table):
    if not table:
        return False
    for row in table:
        for cell in row:
            if contains_french(cell):
                return True
    return False

def fix_tables_in_content(content_list):
    changed = False
    for item in content_list:
        if 'table' in item and table_needs_retranslation(item['table']):
            print('  [FIX] Retraaduction d\'un tableau détecté en français...')
            item['table'] = translate_table(item['table'])
            changed = True
        # Headers éventuels
        if 'headers' in item and isinstance(item['headers'], list):
            if any(contains_french(h) for h in item['headers']):
                print('  [FIX] Retraaduction d\'un header de tableau...')
                item['headers'] = [translate_text(h) if contains_french(h) else h for h in item['headers']]
                changed = True
    return changed

def fix_tables_in_sections(sections):
    changed = False
    for section in sections:
        if 'content' in section:
            if fix_tables_in_content(section['content']):
                changed = True
        if 'subsections' in section:
            for sub in section['subsections']:
                if 'content' in sub:
                    if fix_tables_in_content(sub['content']):
                        changed = True
    return changed

def fix_french_tables_in_medicines_en():
    print("\n=== Correction des tableaux non traduits dans medicines_en ===")
    count = 0
    for med in db.medicines_en.find({}):
        if 'sections' in med:
            changed = fix_tables_in_sections(med['sections'])
            if changed:
                db.medicines_en.update_one({'_id': med['_id']}, {'$set': {'sections': med['sections'], 'corrected_tables_at': datetime.now()}})
                print(f"  [OK] Correction appliquée pour: {med.get('title', med.get('_id'))}")
                count += 1
    print(f"=== Correction terminée. {count} médicaments corrigés. ===\n")

def main():
    print("=" * 60)
    print("TRADUCTION DE TOUS LES MÉDICAMENTS")
    print("=" * 60)

    # Correction des tableaux déjà traduits mais restés en français
    fix_french_tables_in_medicines_en()

    # Compter les médicaments
    total_medicines = db.medicines.count_documents({})
    already_translated = db.medicines_en.count_documents({})

    print(f"Total médicaments français: {total_medicines}")
    print(f"Déjà traduits: {already_translated}")

    # Récupérer les IDs déjà traduits
    existing_translations = set()
    for med in db.medicines_en.find({}, {'original_id': 1}):
        if 'original_id' in med:
            existing_translations.add(str(med['original_id']))

    print(f"IDs avec traduction existante: {len(existing_translations)}")
    print("")

    # Récupérer tous les médicaments à traduire
    medicines_to_translate = []
    for med in db.medicines.find():
        if str(med['_id']) not in existing_translations:
            medicines_to_translate.append(med)

    remaining = len(medicines_to_translate)
    print(f"Médicaments restants à traduire: {remaining}")
    print("")

    if remaining == 0:
        print("✅ Tous les médicaments sont déjà traduits!")
        return

    # Estimation du temps
    estimated_minutes = (remaining * 2) / 60  # ~2 secondes par médicament en moyenne
    print(f"⏱️  Temps estimé: {estimated_minutes:.0f} minutes ({estimated_minutes/60:.1f} heures)")
    print("")
    print("Démarrage de la traduction...")
    print("-" * 60)

    translated_count = 0
    errors_count = 0
    start_time = time.time()

    for i, medicine in enumerate(medicines_to_translate):
        try:
            title = medicine.get('title', 'Sans titre')[:50]
            print(f"[{i+1}/{remaining}] Traduction: {title}...")

            # Traduire
            translated = translate_medicine(medicine)

            # Sauvegarder
            db.medicines_en.insert_one(translated)

            translated_count += 1

            # Afficher progression toutes les 10 traductions
            if (i + 1) % 10 == 0:
                elapsed = time.time() - start_time
                rate = translated_count / elapsed * 60  # par minute
                remaining_time = (remaining - i - 1) / rate if rate > 0 else 0
                print(f"    ✅ {translated_count} traduits | {rate:.1f}/min | Reste: {remaining_time:.0f} min")

        except Exception as e:
            errors_count += 1
            print(f"    ❌ ERREUR: {e}")
            # Continuer avec le suivant
            continue

    # Résumé final
    elapsed = time.time() - start_time
    print("")
    print("=" * 60)
    print("TERMINÉ!")
    print("=" * 60)
    print(f"✅ Traduits: {translated_count}")
    print(f"❌ Erreurs: {errors_count}")
    print(f"⏱️  Temps total: {elapsed/60:.1f} minutes")
    print(f"Total dans medicines_en: {db.medicines_en.count_documents({})}")

if __name__ == "__main__":
    main()
