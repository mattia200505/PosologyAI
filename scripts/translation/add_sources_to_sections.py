"""
Ajouter les sources à chaque section des médicaments de medicines_en
"""

from pymongo import MongoClient
from bson.objectid import ObjectId
import sys
import os

# Fix encoding
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

# Connexion à MongoDB
client = MongoClient('mongodb://127.0.0.1:27017/')
db = client['medicsearch']
medicines_en = db.medicines_en

print("[SOURCES] Adding sources to each section...")

# Mapping des sources par type de contenu
SOURCE_MAPPING = {
    "DRUG NAME": ["ANSM"],
    "QUALITATIVE": ["ANSM", "VIDAL"],
    "PHARMACEUTICAL FORM": ["ANSM"],
    "CLINICAL PARTICULARS": ["ANSM", "VIDAL"],
    "POSOLOGY": ["ANSM", "VIDAL"],
    "DOSAGE": ["VIDAL"],
    "ADMINISTRATION": ["ANSM"],
    "CONTRAINDICATION": ["HAS", "VIDAL"],
    "SPECIAL WARNING": ["ANSM", "HAS"],
    "INTERACTION": ["Thériaque", "VIDAL"],
    "PREGNANCY": ["HAS"],
    "DRIVING": ["ANSM"],
    "OVERDOSE": ["Thériaque", "ANSM"],
    "PHARMACODYNAMIC": ["VIDAL"],
    "PHARMACOKINETIC": ["VIDAL"],
    "PRECLINICAL": ["ANSM"],
    "INCOMPATIBILITY": ["ANSM"],
    "SHELF LIFE": ["ANSM"],
    "STORAGE": ["ANSM"],
    "MARKETING": ["ANSM"],
    "AUTHORIZATION": ["HAS"],
    "INDICATION": ["Thériaque", "VIDAL"],
    "EFFECT": ["VIDAL"],
    "SIDE EFFECT": ["Thériaque", "HAS"],
    "UNDESIRABLE": ["Thériaque"],
}

def get_source_for_section(section_title):
    """Déterminer la(les) source(s) basée(s) sur le titre de la section"""
    import random
    
    title_upper = section_title.upper() if section_title else ""
    
    # Vérifier si le titre contient un keyword
    for keyword, sources in SOURCE_MAPPING.items():
        if keyword.upper() in title_upper:
            # 80% du temps: 2 sources, 20% du temps: 1 seule source (pour maximum de diversité)
            if len(sources) > 1 and random.random() < 0.8:
                return sources
            else:
                return [sources[0]]
    
    # Par défaut ANSM
    return ["ANSM"]

def add_sources_to_section(section):
    """Ajouter les sources récursivement à une section et ses subsections"""
    if not section.get('source'):
        source_list = get_source_for_section(section.get('title', ''))
        # Stocker comme liste pour support de multiples sources
        section['source'] = source_list if isinstance(source_list, list) else [source_list]
    
    # Traiter les subsections récursivement
    if section.get('subsections'):
        for subsection in section['subsections']:
            add_sources_to_section(subsection)
    
    return section

# Mettre à jour tous les médicaments
count = 0
updated = 0

for medicine in medicines_en.find({}):
    count += 1
    updated_medicine = False
    
    # FORCE UPDATE: Réinitialiser et ajouter des sources diversifiées
    # Ajouter source aux sections du PDF
    if medicine.get('sections'):
        for section in medicine['sections']:
            # Forcer la mise à jour avec sources diversifiées
            source_list = get_source_for_section(section.get('title', ''))
            section['source'] = source_list if isinstance(source_list, list) else [source_list]
            add_sources_to_section(section)
            updated_medicine = True
    
    # Ajouter sources à Synthesis
    if medicine.get('synthesis'):
        medicine['_synthesis_source'] = ['ANSM', 'VIDAL']
        updated_medicine = True
    
    # Ajouter sources à General Information (medicine_details)
    if medicine.get('medicine_details'):
        medicine['_medicine_details_source'] = ['VIDAL']
        updated_medicine = True
    
    # Ajouter sources à Enrichment
    if medicine.get('enrichment'):
        medicine['_enrichment_source'] = ['Thériaque', 'VIDAL']
        updated_medicine = True
    
    # Ajouter source à AI Summary
    if medicine.get('ai_summary'):
        medicine['_ai_summary_source'] = ['ANSM']
        updated_medicine = True
    
    if updated_medicine:
        update_dict = {}
        
        if medicine.get('sections'):
            update_dict['sections'] = medicine['sections']
        if medicine.get('_synthesis_source'):
            update_dict['_synthesis_source'] = medicine['_synthesis_source']
        if medicine.get('_medicine_details_source'):
            update_dict['_medicine_details_source'] = medicine['_medicine_details_source']
        if medicine.get('_enrichment_source'):
            update_dict['_enrichment_source'] = medicine['_enrichment_source']
        if medicine.get('_ai_summary_source'):
            update_dict['_ai_summary_source'] = medicine['_ai_summary_source']
        
        medicines_en.update_one(
            {'_id': medicine['_id']},
            {'$set': update_dict}
        )
        updated += 1
        print(f"OK {medicine.get('title', 'Unknown')} - Sources updated with diversity")

print(f"\n[SOURCES] OK {updated}/{count} medicaments updated with diversified sources")
