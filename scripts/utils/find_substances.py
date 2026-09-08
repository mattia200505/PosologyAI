from pymongo import MongoClient
from config import Config

client = MongoClient(Config.MONGO_URI)
db = client[Config.MONGO_DB]

substances = ["paracétamol", "ibuprofène", "amoxicilline", "oméprazole"]

for substance in substances:
    print(f"\n🔍 Recherche: {substance}")
    query = {
        "$or": [
            {"denomination": {"$regex": substance, "$options": "i"}},
            {"substancesActives": {"$regex": substance, "$options": "i"}},
            {"dci": {"$regex": substance, "$options": "i"}}
        ]
    }
    medicines = list(db.medicines.find(query).limit(3))
    
    if medicines:
        print(f"✅ Trouvé {len(medicines)} médicament(s):")
        for med in medicines:
            print(f"   - {med.get('denomination', 'N/A')}")
    else:
        print("❌ Aucun résultat")
