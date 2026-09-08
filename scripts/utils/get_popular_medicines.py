from pymongo import MongoClient
import os
from dotenv import load_dotenv

load_dotenv()
client = MongoClient(os.getenv('MONGO_URI', 'mongodb://localhost:27017/'))
db = client['medicsearch']

# Récupérer les types de médicaments distincts avec leur fréquence
types = list(db.medicines.aggregate([
    {'$match': {'type_medicament': {'$exists': True, '$ne': None}}},
    {'$group': {'_id': '$type_medicament', 'count': {'$sum': 1}}},
    {'$sort': {'count': -1}},
    {'$limit': 10}
]))

print('📊 Top 10 types de médicaments les plus fréquents:')
print('=' * 60)
for i, t in enumerate(types, 1):
    print(f"{i}. {t['_id']}: {t['count']} médicaments")

print('\n💊 5 MÉDICAMENTS POPULAIRES DE TYPES DIFFÉRENTS:')
print('=' * 60)

used_types = set()
medicines = []

for type_info in types:
    type_name = type_info['_id']
    if type_name not in used_types:
        # Trouver un médicament populaire de ce type avec une dénomination
        med = db.medicines.find_one({
            'type_medicament': type_name,
            'denomination': {'$exists': True, '$ne': None, '$ne': 'N/A'}
        })
        if med:
            medicines.append(med)
            used_types.add(type_name)
            
            print(f"\n{len(medicines)}. 💊 {med.get('denomination', 'N/A')}")
            print(f"   📌 Type: {med.get('type_medicament', 'N/A')}")
            print(f"   🏥 Famille ATC: {med.get('groupe_anatomique', 'N/A')}")
            print(f"   💉 Forme: {med.get('forme_pharmaceutique', 'N/A')}")
            if med.get('substance_active'):
                print(f"   🧪 Substance: {med.get('substance_active')}")
            
    if len(medicines) >= 5:
        break

print('\n' + '=' * 60)
print(f"✅ {len(medicines)} médicaments trouvés de types différents")
