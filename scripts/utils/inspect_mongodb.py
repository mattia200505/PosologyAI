from pymongo import MongoClient
import os
from dotenv import load_dotenv
import json

load_dotenv()
client = MongoClient(os.getenv('MONGO_URI', 'mongodb://localhost:27017/'))
db = client['medicsearch']

print('🔍 INSPECTION DE LA BASE MONGODB')
print('=' * 80)

# Compter le nombre total de documents
total = db.medicines.count_documents({})
print(f"Total de médicaments: {total}")

print('\n📋 PREMIER DOCUMENT COMPLET:')
print('─' * 80)
first_doc = db.medicines.find_one()
if first_doc:
    for key, value in first_doc.items():
        if key != '_id':
            # Limiter la longueur de l'affichage
            value_str = str(value)
            if len(value_str) > 100:
                value_str = value_str[:100] + '...'
            print(f"{key}: {value_str}")

print('\n📋 RECHERCHE DE DOCUMENTS AVEC SUBSTANCE ACTIVE:')
print('─' * 80)
with_substance = db.medicines.find_one({'substance_active': {'$exists': True, '$ne': None, '$ne': 'N/A'}})
if with_substance:
    print("Document trouvé avec substance_active:")
    for key, value in with_substance.items():
        if key != '_id':
            value_str = str(value)
            if len(value_str) > 100:
                value_str = value_str[:100] + '...'
            print(f"{key}: {value_str}")
else:
    print("❌ Aucun document avec substance_active valide")

print('\n📋 LISTE DES CHAMPS DISPONIBLES:')
print('─' * 80)
# Récupérer tous les champs uniques
all_keys = set()
for doc in db.medicines.find().limit(100):
    all_keys.update(doc.keys())
all_keys.discard('_id')
print(f"Champs trouvés: {sorted(all_keys)}")

print('\n' + '=' * 80)
