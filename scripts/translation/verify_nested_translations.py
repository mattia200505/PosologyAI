"""
Vérifie que TOUTES les sous-sections imbriquées sont traduites
"""
from pymongo import MongoClient

client = MongoClient('mongodb://localhost:27017/')
db = client['medicsearch']
medicines = db['medicines']

# Prendre un médicament avec structure complexe
medicine = medicines.find_one({'title': {'$regex': 'PARACETAMOL', '$options': 'i'}})

def check_nested_translation(sections, depth=0, path=""):
    """Vérifie récursivement toutes les traductions"""
    prefix = "  " * depth
    all_ok = True
    
    for i, section in enumerate(sections):
        current_path = f"{path} > Section {i+1}" if path else f"Section {i+1}"
        title = section.get('title', '')
        
        # Indicateurs français
        french_words = ['DÉNOMINATION', 'MÉDICAMENT', 'COMPOSITION', 'QUALITATIVE', 
                       'QUANTITATIVE', 'DONNÉES', 'Données', 'données']
        
        is_french = any(word in title for word in french_words)
        
        if is_french:
            print(f"{prefix}❌ {current_path}: {title[:60]}")
            all_ok = False
        else:
            print(f"{prefix}✅ {current_path}: {title[:60]}")
        
        # Vérifier le contenu
        content = section.get('content', [])
        for j, item in enumerate(content):
            if isinstance(item, dict):
                text = item.get('text', '')[:100]
                if any(word in text for word in french_words):
                    print(f"{prefix}  ❌ Contenu {j+1} en français")
                    all_ok = False
        
        # Récursion sur les sous-sections
        subsections = section.get('subsections', [])
        if subsections:
            print(f"{prefix}  📁 {len(subsections)} sous-section(s):")
            if not check_nested_translation(subsections, depth + 1, current_path):
                all_ok = False
    
    return all_ok

print("=" * 80)
print("VÉRIFICATION STRUCTURE FRANÇAISE")
print("=" * 80)
if medicine.get('sections'):
    print(f"\nMédicament: {medicine.get('title')}")
    print(f"Nombre de sections racine: {len(medicine['sections'])}\n")
    check_nested_translation(medicine['sections'])

# Maintenant vérifier la version anglaise
medicines_en = db['Medecines-EN']
medicine_en = medicines_en.find_one({'original_denomination': medicine.get('title')})

if medicine_en:
    print("\n" + "=" * 80)
    print("VÉRIFICATION STRUCTURE ANGLAISE")
    print("=" * 80)
    if medicine_en.get('sections'):
        print(f"\nMédicament: {medicine_en.get('title')}")
        print(f"Nombre de sections racine: {len(medicine_en['sections'])}\n")
        all_translated = check_nested_translation(medicine_en['sections'])
        
        if all_translated:
            print("\n🎉 TOUTES LES SECTIONS IMBRIQUÉES SONT TRADUITES !")
        else:
            print("\n⚠️ Certaines sections imbriquées restent en français")
else:
    print("\n❌ Pas de traduction trouvée")
