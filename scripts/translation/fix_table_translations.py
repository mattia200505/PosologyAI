"""
Script pour corriger les traductions des tableaux dans medicines_en
"""

from pymongo import MongoClient
from deep_translator import GoogleTranslator
import time

def translate_text(translator, text, cache):
    """Traduit un texte avec cache"""
    if not text or not isinstance(text, str):
        return text
    
    text = text.strip()
    if not text:
        return text
    
    # Vérifier le cache
    if text in cache:
        return cache[text]
    
    try:
        # Google Translate limite à 5000 caractères
        if len(text) > 4900:
            chunks = [text[i:i+4900] for i in range(0, len(text), 4900)]
            translated_chunks = []
            for chunk in chunks:
                if chunk in cache:
                    translated_chunks.append(cache[chunk])
                else:
                    result = translator.translate(chunk)
                    cache[chunk] = result
                    translated_chunks.append(result)
                    time.sleep(0.1)  # Éviter le rate limiting
            result = ' '.join(translated_chunks)
        else:
            result = translator.translate(text)
            time.sleep(0.1)
        
        cache[text] = result
        return result
    except Exception as e:
        print(f"  ⚠️ Erreur traduction: {e}")
        return text

def translate_table_content(table, translator, cache):
    """Traduit le contenu d'un tableau"""
    if not table or not isinstance(table, list):
        return table
    
    translated_table = []
    for row in table:
        if isinstance(row, list):
            translated_row = []
            for cell in row:
                if isinstance(cell, str):
                    translated_cell = translate_text(translator, cell, cache)
                    translated_row.append(translated_cell)
                else:
                    translated_row.append(cell)
            translated_table.append(translated_row)
        else:
            translated_table.append(row)
    
    return translated_table

def translate_headers(headers, translator, cache):
    """Traduit les headers d'un tableau"""
    if not headers or not isinstance(headers, list):
        return headers
    
    return [translate_text(translator, h, cache) if isinstance(h, str) else h for h in headers]

def translate_caption(caption, translator, cache):
    """Traduit le caption d'un tableau"""
    if not caption or not isinstance(caption, str):
        return caption
    return translate_text(translator, caption, cache)

def fix_medicine_tables(medicine, translator, cache):
    """Corrige les tableaux non traduits dans un médicament"""
    if not medicine.get('sections'):
        return medicine, 0
    
    tables_fixed = 0
    
    for section in medicine['sections']:
        # Traiter le contenu principal
        for content_item in section.get('content', []):
            if content_item.get('table'):
                # Traduire le tableau
                content_item['table'] = translate_table_content(content_item['table'], translator, cache)
                tables_fixed += 1
                
                # Traduire les headers si présents
                if content_item.get('headers'):
                    content_item['headers'] = translate_headers(content_item['headers'], translator, cache)
                
                # Traduire le caption si présent
                if content_item.get('caption'):
                    content_item['caption'] = translate_caption(content_item['caption'], translator, cache)
        
        # Traiter les sous-sections
        for subsection in section.get('subsections', []):
            for content_item in subsection.get('content', []):
                if content_item.get('table'):
                    # Traduire le tableau
                    content_item['table'] = translate_table_content(content_item['table'], translator, cache)
                    tables_fixed += 1
                    
                    # Traduire les headers si présents
                    if content_item.get('headers'):
                        content_item['headers'] = translate_headers(content_item['headers'], translator, cache)
                    
                    # Traduire le caption si présent
                    if content_item.get('caption'):
                        content_item['caption'] = translate_caption(content_item['caption'], translator, cache)
    
    return medicine, tables_fixed

def main():
    print("=" * 60)
    print("🔧 Correction des traductions de tableaux dans medicines_en")
    print("=" * 60)
    
    # Connexion MongoDB
    client = MongoClient('mongodb://localhost:27017/')
    db = client['medicsearch']
    
    # Initialiser le traducteur
    translator = GoogleTranslator(source='fr', target='en')
    cache = {}
    
    # Récupérer tous les médicaments de medicines_en
    medicines = list(db.medicines_en.find({}))
    print(f"\n📋 {len(medicines)} médicaments dans medicines_en")
    
    total_tables_fixed = 0
    
    for i, med in enumerate(medicines):
        title = med.get('title', 'Unknown')
        print(f"\n[{i+1}/{len(medicines)}] 📦 {title[:50]}")
        
        # Corriger les tableaux
        updated_med, tables_fixed = fix_medicine_tables(med, translator, cache)
        
        if tables_fixed > 0:
            # Mettre à jour dans MongoDB
            db.medicines_en.update_one(
                {'_id': med['_id']},
                {'$set': {'sections': updated_med['sections']}}
            )
            print(f"  ✅ {tables_fixed} tableau(x) traduit(s)")
            total_tables_fixed += tables_fixed
        else:
            print(f"  ℹ️ Pas de tableaux à traduire")
    
    print("\n" + "=" * 60)
    print(f"✅ TERMINÉ - {total_tables_fixed} tableaux corrigés au total")
    print("=" * 60)

if __name__ == '__main__':
    main()
