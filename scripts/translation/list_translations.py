"""
Vérifie les traductions dans la collection Medecines-EN
"""
from pymongo import MongoClient

client = MongoClient('mongodb://localhost:27017/')
db = client['medicsearch']
medicines_en = db['Medecines-EN']

# Lister tous les médicaments traduits
count = medicines_en.count_documents({})
print(f"📊 Nombre total de traductions: {count}\n")

# Afficher les 5 dernières traductions
print("=" * 80)
print("LES 5 DERNIÈRES TRADUCTIONS")
print("=" * 80)

for med in medicines_en.find().sort('_id', -1).limit(5):
    print(f"\n✅ {med.get('title', 'Sans titre')}")
    print(f"   Original: {med.get('original_denomination', 'N/A')}")
    
    if med.get('sections'):
        print(f"   Sections: {len(med['sections'])}")
        
        # Compter les sous-sections
        subsection_count = 0
        for section in med['sections']:
            subsections = section.get('subsections', [])
            subsection_count += len(subsections)
            
            # Compter les sous-sous-sections
            for sub in subsections:
                subsection_count += len(sub.get('subsections', []))
        
        print(f"   Sous-sections totales: {subsection_count}")
