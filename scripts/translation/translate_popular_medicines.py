from pymongo import MongoClient
import os
from dotenv import load_dotenv
from medicine_translator import MedicineTranslator

load_dotenv()
client = MongoClient(os.getenv('MONGO_URI', 'mongodb://localhost:27017/'))
db = client['medicsearch']

# Initialiser le traducteur
translator = MedicineTranslator()

# Liste des médicaments à traduire avec leurs types
medicines_to_translate = [
    {
        'search_term': 'PARACETAMOL',
        'type': 'Analgésique',
        'emoji': '🩹',
        'note': 'Médicament le plus consommé en France'
    },
    {
        'search_term': 'IBUPROFENE',
        'type': 'Anti-inflammatoire (AINS)',
        'emoji': '🔥',
        'note': ''
    },
    {
        'search_term': 'AMOXICILLINE',
        'type': 'Antibiotique',
        'emoji': '🦠',
        'note': ''
    },
    {
        'search_term': 'OMEPRAZOLE',
        'type': 'Anti-ulcéreux / protecteur gastrique',
        'emoji': '🍽️',
        'note': ''
    },
    {
        'search_term': 'SALBUTAMOL',
        'type': 'Bronchodilatateur',
        'emoji': '🌬️',
        'note': 'Aussi connu sous le nom Ventoline'
    }
]

print('=' * 80)
print('🌍 TRADUCTION DES MÉDICAMENTS POPULAIRES EN ANGLAIS')
print('=' * 80)

results = []

for med_info in medicines_to_translate:
    search_term = med_info['search_term']
    
    # Rechercher le médicament dans la base de données par title
    medicine = db.medicines.find_one({
        'title': {'$regex': search_term, '$options': 'i'}
    })
    
    if medicine:
        print(f"\n{med_info['emoji']} {search_term}")
        print(f"{'─' * 60}")
        print(f"📌 Type: {med_info['type']}")
        if med_info['note']:
            print(f"ℹ️  Note: {med_info['note']}")
        
        # Afficher les informations françaises
        print(f"\n🇫🇷 VERSION FRANÇAISE:")
        print(f"   Titre: {medicine.get('title', 'N/A')}")
        
        medicine_details = medicine.get('medicine_details', {})
        if medicine_details:
            print(f"   Substances actives: {', '.join(medicine_details.get('substances_actives', ['N/A']))}")
            print(f"   Laboratoire: {medicine_details.get('laboratoire', 'N/A')}")
            print(f"   Forme: {medicine_details.get('forme_galenique', 'N/A')}")
        
        print(f"   Famille ATC: {medicine.get('groupe_anatomique', 'N/A')}")
        print(f"   Type: {medicine.get('type_medicament', 'N/A')}")
        
        # Traduire en anglais
        print(f"\n🇬🇧 TRADUCTION EN COURS...")
        
        translated = translator.translate_medicine_data(medicine)
        
        if translated:
            print(f"   Title: {translated.get('title', 'N/A')}")
            
            medicine_details_en = translated.get('medicine_details', {})
            if medicine_details_en:
                print(f"   Active substances: {', '.join(medicine_details_en.get('substances_actives', ['N/A']))}")
                print(f"   Laboratory: {medicine_details_en.get('laboratoire', 'N/A')}")
                print(f"   Pharmaceutical form: {medicine_details_en.get('forme', 'N/A')}")
            
            print(f"   ATC family: {translated.get('groupe_anatomique', 'N/A')}")
            print(f"   Type: {translated.get('type_medicament', 'N/A')}")
            
            # Mettre à jour dans la base de données
            update_result = db.medicines.update_one(
                {'_id': medicine['_id']},
                {'$set': {
                    'title_en': translated.get('title'),
                    'medicine_details_en': translated.get('medicine_details'),
                    'sections_en': translated.get('sections'),
                    'groupe_anatomique_en': translated.get('groupe_anatomique'),
                    'type_medicament_en': translated.get('type_medicament'),
                    'famille_therapeutique_en': translated.get('famille_therapeutique')
                }}
            )
            
            if update_result.modified_count > 0:
                print(f"   ✅ Traduction enregistrée dans MongoDB")
            else:
                print(f"   ℹ️  Traduction déjà existante")
                
            results.append({
                'name': search_term,
                'found': True,
                'translated': True
            })
        else:
            print(f"   ❌ Échec de la traduction")
            results.append({
                'name': search_term,
                'found': True,
                'translated': False
            })
    else:
        print(f"\n{med_info['emoji']} {search_term}")
        print(f"{'─' * 60}")
        print(f"❌ Médicament non trouvé dans la base de données")
        results.append({
            'name': search_term,
            'found': False,
            'translated': False
        })

# Résumé
print('\n' + '=' * 80)
print('📊 RÉSUMÉ')
print('=' * 80)
found_count = sum(1 for r in results if r['found'])
translated_count = sum(1 for r in results if r['translated'])

print(f"Médicaments recherchés: {len(medicines_to_translate)}")
print(f"Médicaments trouvés: {found_count}/{len(medicines_to_translate)}")
print(f"Médicaments traduits: {translated_count}/{len(medicines_to_translate)}")

if translated_count == len(medicines_to_translate):
    print("\n✅ Tous les médicaments ont été traduits avec succès!")
else:
    print(f"\n⚠️  {len(medicines_to_translate) - translated_count} médicament(s) n'ont pas pu être traduits")

print('=' * 80)
