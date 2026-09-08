"""Vérifier la qualité des traductions"""
from pymongo import MongoClient

client = MongoClient('mongodb://localhost:27017/')
db = client['medicsearch']

# Compter les traductions
total = db['medicines-EN'].count_documents({})
print(f"\nTotal traductions: {total}")

# Vérifier les sections
for med in db['medicines-EN'].find():
    title = med.get('title', 'Unknown')
    sections_count = len(med.get('sections', []))
    subsections_total = sum(len(s.get('subsections', [])) for s in med.get('sections', []))
    
    print(f"\n{title}")
    print(f"  Sections: {sections_count}")
    print(f"  Subsections: {subsections_total}")
    
    # Afficher première section pour vérifier
    if sections_count > 0:
        first_section = med['sections'][0]
        print(f"  Première section: {first_section.get('section_name', 'N/A')}")
        if first_section.get('subsections'):
            first_sub = first_section['subsections'][0]
            text_preview = first_sub.get('text', '')[:100]
            print(f"    Texte (100 premiers chars): {text_preview}...")

client.close()
