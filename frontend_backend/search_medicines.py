from pymongo import MongoClient
import os
from dotenv import load_dotenv

load_dotenv()
client = MongoClient(os.getenv('MONGO_URI', 'mongodb://localhost:27017/'))
db = client['medicsearch']

# Liste des substances à rechercher
substances = [
    'paracetamol',
    'ibuprofene',
    'amoxicilline',
    'omeprazole',
    'salbutamol'
]

# D'abord, regardons ce qu'il y a dans la base et tous les champs
print('📊 ÉCHANTILLON DE LA BASE DE DONNÉES')
print('=' * 80)
sample = list(db.medicines.find().limit(3))
for i, med in enumerate(sample, 1):
    print(f"\n{i}. Document complet:")
    for key, value in med.items():
        if key != '_id':
            print(f"   {key}: {value}")

print('\n' + '=' * 80)
print('🔍 RECHERCHE DES MÉDICAMENTS DANS LA BASE')
print('=' * 80)

for substance in substances:
    print(f"\n📋 Recherche: {substance.upper()}")
    print('─' * 60)
    
    # Recherche par substance active
    medicines = list(db.medicines.find({
        'substance_active': {'$regex': substance, '$options': 'i'}
    }).limit(3))
    
    if medicines:
        print(f"✅ {len(medicines)} médicament(s) trouvé(s):")
        for i, med in enumerate(medicines, 1):
            print(f"   {i}. Dénomination: {med.get('denomination', 'N/A')}")
            print(f"      Substance: {med.get('substance_active', 'N/A')}")
            print(f"      Forme: {med.get('forme_pharmaceutique', 'N/A')}")
            print(f"      Type: {med.get('type_medicament', 'N/A')}")
    else:
        print(f"❌ Aucun médicament trouvé")

print('\n' + '=' * 80)
