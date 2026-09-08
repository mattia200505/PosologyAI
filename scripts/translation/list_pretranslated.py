"""
Liste les médicaments pré-traduits
"""
from pymongo import MongoClient
from config import Config

client = MongoClient(Config.MONGO_URI)
db = client['medicsearch']

docs = list(db.medicines_en.find({}, {'_id': 1, 'original_id': 1, 'title': 1}).limit(10))

print('Médicaments pré-traduits dans medicines_en:')
print('='*80)
for doc in docs:
    title = doc.get('title', 'N/A')[:80]
    print(f"\n📋 {title}")
    print(f"   ID anglais (medicines_en): {doc['_id']}")
    print(f"   ID français (medicines): {doc.get('original_id')}")
    print(f"   URL: http://127.0.0.1:5000/medicine/{doc['_id']}?lang=en")
