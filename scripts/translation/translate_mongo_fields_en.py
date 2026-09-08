# Script pour traduire certains champs de tous les médicaments en anglais dans la base
from deep_translator import GoogleTranslator
from pymongo import MongoClient

# Connexion à MongoDB (adapter l'URI si besoin)
client = MongoClient('mongodb://localhost:27017/')
db = client['medicsearch']  # Adapter le nom de la base si besoin
collection = db['medicines_en']

translator = GoogleTranslator(source='fr', target='en')

fields_to_translate = [
    'famille_therapeutique',
    'groupe_anatomique',
    'groupe_anatomique_original',
    'type_medicament'
]

count = 0
for med in collection.find():
    update = {}
    for field in fields_to_translate:
        value = med.get(field)
        if value and not med.get(f'{field}_en'):
            try:
                translated = translator.translate(str(value))
                update[f'{field}_en'] = translated
            except Exception as e:
                print(f"Erreur traduction {field} pour {med.get('_id')}: {e}")
    if update:
        collection.update_one({'_id': med['_id']}, {'$set': update})
        count += 1
        print(f"Mise à jour {med.get('_id')}: {update}")
print(f"{count} médicaments mis à jour.")
