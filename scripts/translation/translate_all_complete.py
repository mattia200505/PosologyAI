from pymongo import MongoClient
import os
from dotenv import load_dotenv
from medicine_translator import MedicineTranslator
import time
from datetime import datetime

load_dotenv()
client = MongoClient(os.getenv('MONGO_URI', 'mongodb://localhost:27017/'))
db = client['medicsearch']

# Initialiser le traducteur
translator = MedicineTranslator()

print('=' * 80)
print('🌍 TRADUCTION COMPLÈTE DE TOUS LES MÉDICAMENTS')
print('=' * 80)

# Compter le nombre total de médicaments
total_medicines = db.medicines.count_documents({})
print(f"📊 Total de médicaments dans la base: {total_medicines}")

# Compter combien sont déjà traduits
already_translated = db.medicines.count_documents({'title_en': {'$exists': True, '$ne': None}})
print(f"✅ Déjà traduits: {already_translated}")
print(f"⏳ Restants à traduire: {total_medicines - already_translated}")

# Demander confirmation
print('\n⚠️  ATTENTION: Cette opération va traduire TOUS les médicaments.')
print('   Cela peut prendre plusieurs heures et consommer beaucoup de crédits API Mistral.')
response = input('\nVoulez-vous continuer? (oui/non): ')

if response.lower() not in ['oui', 'o', 'yes', 'y']:
    print('❌ Opération annulée')
    exit()

print('\n🚀 DÉBUT DE LA TRADUCTION')
print('=' * 80)

# Statistiques
stats = {
    'total': 0,
    'translated': 0,
    'skipped': 0,
    'errors': 0,
    'start_time': datetime.now()
}

# Batch size pour afficher la progression
batch_size = 10

# Récupérer tous les médicaments NON traduits
medicines_to_translate = db.medicines.find({
    '$or': [
        {'title_en': {'$exists': False}},
        {'title_en': None}
    ]
})

for i, medicine in enumerate(medicines_to_translate, 1):
    stats['total'] += 1
    
    try:
        # Afficher la progression
        if i % batch_size == 0 or i == 1:
            elapsed = (datetime.now() - stats['start_time']).total_seconds()
            rate = stats['translated'] / elapsed if elapsed > 0 else 0
            remaining = (total_medicines - already_translated - i)
            eta_seconds = remaining / rate if rate > 0 else 0
            eta_minutes = eta_seconds / 60
            
            print(f"\n📊 Progression: {i}/{total_medicines - already_translated}")
            print(f"   ✅ Traduits: {stats['translated']}")
            print(f"   ⏭️  Ignorés: {stats['skipped']}")
            print(f"   ❌ Erreurs: {stats['errors']}")
            print(f"   ⏱️  Vitesse: {rate:.2f} méd/sec")
            print(f"   ⏳ ETA: {eta_minutes:.1f} minutes")
        
        # Afficher le médicament en cours
        title = medicine.get('title', 'N/A')
        print(f"\n{i}. Traduction de: {title[:60]}...")
        
        # Traduire le médicament
        translated = translator.translate_medicine_data(medicine)
        
        if translated:
            # Mettre à jour dans MongoDB
            update_result = db.medicines.update_one(
                {'_id': medicine['_id']},
                {'$set': {
                    'title_en': translated.get('title_en'),
                    'medicine_details_en': translated.get('medicine_details_en'),
                    'sections_en': translated.get('sections_en'),
                    'groupe_anatomique_en': translated.get('groupe_anatomique_en'),
                    'type_medicament_en': translated.get('type_medicament_en'),
                    'famille_therapeutique_en': translated.get('famille_therapeutique_en'),
                    'translated_at': datetime.now()
                }}
            )
            
            if update_result.modified_count > 0:
                stats['translated'] += 1
                print(f"   ✅ Traduit et enregistré")
            else:
                stats['skipped'] += 1
                print(f"   ⏭️  Déjà existant")
        else:
            stats['errors'] += 1
            print(f"   ❌ Échec de la traduction")
        
        # Petit délai pour éviter de surcharger l'API
        time.sleep(0.5)
        
    except Exception as e:
        stats['errors'] += 1
        print(f"   ❌ ERREUR: {str(e)}")
        # Continuer avec le suivant
        continue

# Résumé final
print('\n' + '=' * 80)
print('📊 RÉSUMÉ FINAL')
print('=' * 80)

elapsed_total = (datetime.now() - stats['start_time']).total_seconds()
elapsed_minutes = elapsed_total / 60

print(f"Médicaments traités: {stats['total']}")
print(f"✅ Traduits avec succès: {stats['translated']}")
print(f"⏭️  Ignorés (déjà traduits): {stats['skipped']}")
print(f"❌ Erreurs: {stats['errors']}")
print(f"⏱️  Temps total: {elapsed_minutes:.1f} minutes")
print(f"⏱️  Vitesse moyenne: {stats['translated']/elapsed_total if elapsed_total > 0 else 0:.2f} méd/sec")

# Total dans la base maintenant
total_translated_now = db.medicines.count_documents({'title_en': {'$exists': True, '$ne': None}})
print(f"\n📊 Total de médicaments traduits dans la base: {total_translated_now}/{total_medicines}")
print(f"📈 Pourcentage: {(total_translated_now/total_medicines*100):.1f}%")

if stats['translated'] > 0:
    print("\n✅ Traduction terminée avec succès!")
else:
    print("\n⚠️  Aucune nouvelle traduction effectuée")

print('=' * 80)
