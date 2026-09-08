"""
Scraper OpenFDA avec traductions automatiques en français
Récupère des médicaments depuis OpenFDA (base US) et les traduit
"""

import requests
from pymongo import MongoClient
import json
from datetime import datetime
import logging
import time

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Dictionnaire de traductions médical français-anglais
MEDICAL_TRANSLATIONS = {
    # Usages
    "pain": "douleur",
    "fever": "fièvre",
    "inflammation": "inflammation",
    "hypertension": "hypertension",
    "cholesterol": "cholestérol",
    "diabetes": "diabète",
    "infection": "infection",
    "anxiety": "anxiété",
    "depression": "dépression",
    "cough": "toux",
    "constipation": "constipation",
    "diarrhea": "diarrhée",
    "nausea": "nausée",
    "insomnia": "insomnie",
    "arthritis": "arthrite",
    "asthma": "asthme",
    "migraine": "migraine",
    
    # Formes
    "tablet": "comprimé",
    "capsule": "gélule",
    "liquid": "liquide",
    "injection": "injection",
    "powder": "poudre",
    "cream": "crème",
    "ointment": "pommade",
    "patch": "patch",
    "spray": "spray",
    
    # Précautions
    "pregnancy": "grossesse",
    "liver disease": "maladie du foie",
    "kidney disease": "maladie des reins",
    "heart disease": "maladie cardiaque",
    "allergy": "allergie",
    "hypersensitivity": "hypersensibilité",
    "contraindication": "contre-indication",
    "side effects": "effets secondaires",
}

def connect_db():
    """Connexion à MongoDB"""
    try:
        client = MongoClient("mongodb://mongo:27017/", serverSelectionTimeoutMS=5000)
        client.admin.command('ping')
        return client["medicsearch"]
    except:
        client = MongoClient("mongodb://localhost:27017/")
        return client["medicsearch"]

def translate_medical_text(text):
    """Traduction simple basée sur dictionnaire"""
    if not text:
        return text
    
    text_lower = text.lower()
    for en, fr in MEDICAL_TRANSLATIONS.items():
        if en in text_lower:
            text_lower = text_lower.replace(en, fr)
    
    return text_lower.capitalize()

def scrape_openfda_medicines(brand_names=None, limit=50):
    """
    Scrape medicines from OpenFDA API
    https://open.fda.gov/apis/drug/drugsfda/
    """
    if brand_names is None:
        brand_names = [
            "Aspirin", "Ibuprofen", "Acetaminophen", "Metformin", "Atorvastatin",
            "Lisinopril", "Metoprolol", "Warfarin", "Amoxicillin", "Azithromycin",
            "Omeprazole", "Sertraline", "Fluoxetine", "Citalopram", "Losartan",
            "Amitriptyline", "Lithium", "Prednisolone", "Ciprofloxacin", "Vancomycin"
        ]
    
    db = connect_db()
    medicines = []
    
    print("=" * 80)
    print("🌐 SCRAPER OPENFDA - AVEC TRADUCTIONS")
    print("=" * 80)
    
    print(f"\n[1/3] Recherche sur OpenFDA API...")
    print(f"✓ {len(brand_names)} médicaments à chercher")
    
    base_url = "https://api.fda.gov/drug/drugsfda.json"
    
    for brand in brand_names[:limit]:
        try:
            # Chercher le médicament sur OpenFDA
            params = {
                "search": f'brand_name:"{brand}"',
                "limit": 1
            }
            
            response = requests.get(base_url, params=params, timeout=5)
            
            if response.status_code == 200:
                data = response.json()
                
                if 'results' in data and len(data['results']) > 0:
                    drug = data['results'][0]
                    
                    # Extraire les informations
                    medicine_data = {
                        'title': drug.get('brand_name', brand),
                        'medicine_details': {
                            'substances_actives': [
                                substance.get('active_ingredient', 'Unknown')
                                for substance in drug.get('active_ingredients', [{}])
                            ],
                            'forme': drug.get('dosage_form', [None])[0] if drug.get('dosage_form') else 'Comprimé',
                            'laboratoire': drug.get('openfda', {}).get('manufacturer_name', ['Laboratoire inconnu'])[0],
                            'dosages': drug.get('strength', []),
                            'route': drug.get('route', ['Voie non spécifiée'])[0] if drug.get('route') else 'Voie orale'
                        },
                        'source': 'OpenFDA',
                        'translations': {
                            'en': drug.get('brand_name', brand),
                            'fr': f"{brand} (traduit)"
                        },
                        'approvals': {
                            'us_approved': True,
                            'approval_date': drug.get('approval_date', 'Unknown')
                        },
                        'created_at': datetime.now(),
                        'updated_at': datetime.now()
                    }
                    
                    medicines.append(medicine_data)
                    print(f"  ✓ {brand}: trouvé")
            
            time.sleep(0.1)  # Rate limiting
            
        except Exception as e:
            logger.error(f"Erreur pour {brand}: {e}")
    
    print(f"\n✓ {len(medicines)} médicaments récupérés d'OpenFDA")
    return medicines

def enrich_medicines_with_openfda_data(db):
    """
    Enrichit les médicaments existants avec les données OpenFDA traduites
    """
    print("\n[2/3] Enrichissement des médicaments existants...")
    
    # Récupérer les nouveaux médicaments OpenFDA
    openfda_medicines = scrape_openfda_medicines(limit=20)
    
    inserted = 0
    updated = 0
    
    for med in openfda_medicines:
        try:
            # Chercher si existe
            existing = db.medicines.find_one({'title': med['title']})
            
            if not existing:
                # Insérer nouveau
                db.medicines.insert_one(med)
                inserted += 1
            else:
                # Mettre à jour avec traductions
                db.medicines.update_one(
                    {'_id': existing['_id']},
                    {
                        '$set': {
                            'translations': med.get('translations', {}),
                            'approvals': med.get('approvals', {})
                        }
                    }
                )
                updated += 1
        except Exception as e:
            logger.error(f"Erreur pour {med.get('title')}: {e}")
    
    print(f"✓ {inserted} médicaments insérés")
    print(f"✓ {updated} médicaments enrichis")
    
    return inserted, updated

def add_french_descriptions(db):
    """
    Ajoute des descriptions en français basées sur les indications
    """
    print("\n[3/3] Ajout de descriptions en français...")
    
    french_descriptions = {
        "paracétamol": "Médicament analgésique et antipyrétique. Utilisé pour soulager la douleur et réduire la fièvre.",
        "ibuprofène": "Anti-inflammatoire non stéroïdien (AINS). Utilisé pour traiter la douleur, l'inflammation et la fièvre.",
        "aspirine": "Anticoagulant et antalgique. Utilisé en prévention cardiovasculaire et pour soulager la douleur.",
        "metformine": "Antidiabétique oral. Première ligne de traitement du diabète de type 2.",
        "atorvastatine": "Statine. Utilisée pour réduire le cholestérol LDL et prévenir les maladies cardiovasculaires.",
        "lisinopril": "Inhibiteur de l'enzyme de conversion (IEC). Utilisé dans le traitement de l'hypertension et l'insuffisance cardiaque.",
        "oméprazole": "Inhibiteur de la pompe à protons (IPP). Utilisé pour traiter le reflux gastro-œsophagien (RGO) et les ulcères.",
        "sertraline": "Inhibiteur sélectif de la recapture de la sérotonine (ISRS). Utilisé dans le traitement de la dépression et de l'anxiété.",
    }
    
    updated = 0
    for medicine_name, description in french_descriptions.items():
        try:
            result = db.medicines.update_many(
                {'title': {'$regex': medicine_name, '$options': 'i'}},
                {'$set': {'description_fr': description}}
            )
            updated += result.modified_count
        except Exception as e:
            logger.error(f"Erreur pour {medicine_name}: {e}")
    
    print(f"✓ {updated} descriptions en français ajoutées")
    return updated

def run_openfda_scraper_with_translations():
    """
    Lance le scraper OpenFDA complet avec traductions
    """
    print("\n" + "=" * 80)
    print("🌍 SCRAPER OPENFDA + TRADUCTIONS")
    print("=" * 80)
    
    db = connect_db()
    
    # 1. Enrichir avec données OpenFDA
    inserted, updated = enrich_medicines_with_openfda_data(db)
    
    # 2. Ajouter descriptions en français
    descriptions_added = add_french_descriptions(db)
    
    # Statistiques finales
    print("\n" + "=" * 80)
    print("📊 RÉSUMÉ FINAL")
    print("=" * 80)
    print(f"✓ Nouveaux médicaments insérés: {inserted}")
    print(f"✓ Médicaments enrichis: {updated}")
    print(f"✓ Descriptions françaises ajoutées: {descriptions_added}")
    print(f"✓ Total base de données: {db.medicines.count_documents({})}")
    print("=" * 80)
    
    return {
        'inserted': inserted,
        'enriched': updated,
        'descriptions_added': descriptions_added,
        'total_medicines': db.medicines.count_documents({})
    }

if __name__ == "__main__":
    result = run_openfda_scraper_with_translations()
    print(f"\n🎉 Scraping terminé: {result}")
