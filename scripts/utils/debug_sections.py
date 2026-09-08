from pymongo import MongoClient
import json

client = MongoClient('127.0.0.1', 27018)
db = client['medicsearch']

med = db.medicines.find_one({"synthesis": {"$exists": False}})

print("First section type:", type(med['sections'][0]))
print("First section:", json.dumps(med['sections'][0], indent=2)[:200])
