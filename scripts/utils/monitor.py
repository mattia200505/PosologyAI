from pymongo import MongoClient
import time

client = MongoClient('127.0.0.1', 27018)
db = client['medicsearch']

for i in range(30):
    synth = db.medicines.count_documents({'synthesis': {'$exists': True}})
    total = db.medicines.count_documents({})
    pct = synth / total * 100 if total > 0 else 0
    print(f'Synthesis: {synth:,} / {total:,} ({pct:.1f}%)')
    if i < 29:
        time.sleep(3)
