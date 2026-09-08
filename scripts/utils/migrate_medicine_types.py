"""
Script pour mapper les types ATC existants vers la nouvelle classification détaillée
"""

from pymongo import MongoClient
from medicine_categories import MEDICINE_CATEGORIES

# Mapping entre les types ATC et les nouveaux types
ATC_TO_NEW_TYPE_MAPPING = {
    # Système nerveux
    "Système nerveux": {
        "keywords": {
            "anxiolytique": "Anxiolytiques",
            "anxio": "Anxiolytiques",
            "hypnotique": "Hypnotiques (somnifères)",
            "somnifère": "Hypnotiques (somnifères)",
            "sommeil": "Hypnotiques (somnifères)",
            "antidépresseur": "Antidépresseurs",
            "dépression": "Antidépresseurs",
            "antipsychotique": "Antipsychotiques (neuroleptiques)",
            "neuroleptique": "Antipsychotiques (neuroleptiques)",
            "psychotique": "Antipsychotiques (neuroleptiques)",
            "antiépileptique": "Antiépileptiques",
            "épilepsie": "Antiépileptiques",
            "convulsion": "Antiépileptiques",
            "psychostimulant": "Psychostimulants",
            "adhd": "Psychostimulants",
            "parkinson": "Antiparkinsoniens",
            "myorelaxant": "Myorelaxants",
            "relaxant musculaire": "Myorelaxants",
            "anesthésie": "Anesthésiques",
            "anesthétique": "Anesthésiques",
            "analgésique": "Analgésiques (douleur)",
            "antalgique": "Analgésiques (douleur)",
            "douleur": "Analgésiques (douleur)",
            "antipyrétique": "Antipyrétiques (fièvre)",
            "fièvre": "Antipyrétiques (fièvre)",
        },
        "default": "Analgésiques (douleur)"
    },
    
    # Système cardiovasculaire
    "Système cardiovasculaire": {
        "keywords": {
            "hypertension": "Antihypertenseurs",
            "tension": "Antihypertenseurs",
            "angor": "Antiangineux",
            "angine": "Antiangineux",
            "arythmie": "Antiarythmiques",
            "rythme cardiaque": "Antiarythmiques",
            "anticoagulant": "Anticoagulants",
            "coagulation": "Anticoagulants",
            "antiagrégant": "Antiagrégants plaquettaires",
            "plaquette": "Antiagrégants plaquettaires",
            "cholestérol": "Hypolipidémiants",
            "lipide": "Hypolipidémiants",
            "statine": "Hypolipidémiants",
            "vasodilatateur": "Vasodilatateurs",
            "diurétique": "Diurétiques",
        },
        "default": "Antihypertenseurs"
    },
    
    # Système respiratoire
    "Système respiratoire": {
        "keywords": {
            "bronchodilatateur": "Bronchodilatateurs",
            "asthme": "Bronchodilatateurs",
            "bronche": "Bronchodilatateurs",
            "corticoïde": "Corticoïdes inhalés",
            "inhalé": "Corticoïdes inhalés",
            "toux": "Antitussifs",
            "antitussif": "Antitussifs",
            "mucoly": "Mucolytiques / expectorants",
            "expectorant": "Mucolytiques / expectorants",
            "antihistaminique": "Antihistaminiques",
            "allergie": "Antihistaminiques",
        },
        "default": "Bronchodilatateurs"
    },
    
    # Appareil digestif et métabolisme
    "Appareil digestif et métabolisme": {
        "keywords": {
            "ulcère": "Anti-ulcéreux (IPP, anti-H2)",
            "ipp": "Anti-ulcéreux (IPP, anti-H2)",
            "inhibiteur pompe": "Anti-ulcéreux (IPP, anti-H2)",
            "antiacide": "Antiacides",
            "acidité": "Antiacides",
            "antispasmodique": "Antispasmodiques",
            "spasme": "Antispasmodiques",
            "antiémétique": "Antiémétiques",
            "nausée": "Antiémétiques",
            "vomissement": "Antiémétiques",
            "laxatif": "Laxatifs",
            "constipation": "Laxatifs",
            "antidiarrhéique": "Antidiarrhéiques",
            "diarrhée": "Antidiarrhéiques",
            "diabète": "Antidiabétiques",
            "glycémie": "Antidiabétiques",
            "hypoglycémiant": "Hypoglycémiants",
            "enzyme": "Enzymes digestives",
            "insuline": "Insulines",
        },
        "default": "Antiacides"
    },
    
    # Anti-infectieux
    "Anti-infectieux généraux à usage systémique": {
        "keywords": {
            "antibiotique": "Antibiotiques",
            "bactérie": "Antibiotiques",
            "antiviral": "Antiviraux",
            "virus": "Antiviraux",
            "vih": "Antiviraux",
            "antifongique": "Antifongiques",
            "fongique": "Antifongiques",
            "mycose": "Antifongiques",
            "antiparasitaire": "Antiparasitaires",
            "parasite": "Antiparasitaires",
            "tuberculose": "Antituberculeux",
            "antituberculeux": "Antituberculeux",
        },
        "default": "Antibiotiques"
    },
    
    # Produits antiparasitaires
    "Produits antiparasitaires": {
        "keywords": {},
        "default": "Antiparasitaires"
    },
    
    # Système musculo-squelettique
    "Système musculo-squelettique": {
        "keywords": {
            "anti-inflammatoire": "Anti-inflammatoires non stéroïdiens (AINS)",
            "ains": "Anti-inflammatoires non stéroïdiens (AINS)",
            "inflamm": "Anti-inflammatoires non stéroïdiens (AINS)",
            "corticoïde": "Corticoïdes",
            "cortisone": "Corticoïdes",
            "myorelaxant": "Myorelaxants",
        },
        "default": "Anti-inflammatoires non stéroïdiens (AINS)"
    },
    
    # Préparations hormonales
    "Préparations systémiques hormonales": {
        "keywords": {
            "thyroïde": "Hormones thyroïdiennes",
            "hormone thyroïdienne": "Hormones thyroïdiennes",
            "testostérone": "Hormones sexuelles",
            "œstrogène": "Hormones sexuelles",
            "hormone sexuelle": "Hormones sexuelles",
            "contraceptif": "Contraceptifs",
            "contraception": "Contraceptifs",
            "pilule": "Contraceptifs",
            "insuline": "Insulines",
            "corticostéroïde": "Corticostéroïdes systémiques",
            "hormone de croissance": "Hormones de croissance",
            "antithyroïdien": "Antithyroïdiens",
        },
        "default": "Corticostéroïdes systémiques"
    },
    
    # Système génito-urinaire
    "Système génito-urinaire et hormones sexuelles": {
        "keywords": {
            "contraceptif": "Contraceptifs",
            "hormone sexuelle": "Hormones sexuelles",
            "œstrogène": "Hormones sexuelles",
            "progestérone": "Hormones sexuelles",
        },
        "default": "Hormones sexuelles"
    },
    
    # Sang et organes hématopoïétiques
    "Sang et organes hématopoïétiques": {
        "keywords": {
            "anémie": "Antianémiques",
            "fer": "Antianémiques",
            "coagulation": "Facteurs de coagulation",
            "hémophilie": "Facteurs de coagulation",
            "immunosuppresseur": "Immunosuppresseurs",
            "immunostimulant": "Immunostimulants",
            "anticoagulant": "Anticoagulants",
        },
        "default": "Antianémiques"
    },
    
    # Médicaments dermatologiques
    "Médicaments dermatologiques": {
        "keywords": {
            "dermocorticoïde": "Dermocorticoïdes",
            "corticoïde": "Dermocorticoïdes",
            "antiseptique": "Antiseptiques",
            "antifongique": "Antifongiques cutanés",
            "mycose": "Antifongiques cutanés",
            "antibiotique": "Antibiotiques locaux",
            "acné": "Antiacnéiques",
        },
        "default": "Antiseptiques"
    },
    
    # Organes sensoriels
    "Organes sensoriels": {
        "keywords": {
            "collyre": "Collyres",
            "œil": "Collyres",
            "oculaire": "Collyres",
            "glaucome": "Antiglaucomateux",
            "décongestionnant": "Décongestionnants",
            "oreille": "Gouttes auriculaires",
            "auriculaire": "Gouttes auriculaires",
        },
        "default": "Collyres"
    },
    
    # Antinéoplasiques
    "Antinéoplasiques et immunomodulateurs": {
        "keywords": {
            "chimiothérapie": "Anticancéreux (chimiothérapie)",
            "anticancéreux": "Anticancéreux (chimiothérapie)",
            "thérapie ciblée": "Thérapies ciblées",
            "hormonothérapie": "Hormonothérapies",
            "immunothérapie": "Immunothérapies",
            "anticorps": "Anticorps monoclonaux",
            "immunomodulateur": "Immunosuppresseurs",
            "immunosuppresseur": "Immunosuppresseurs",
            "vaccin": "Vaccins",
        },
        "default": "Anticancéreux (chimiothérapie)"
    },
    
    # Divers
    "Divers": {
        "keywords": {},
        "default": "Antiseptiques"
    }
}

def find_new_type(atc_type, medicine_name, famille_therapeutique):
    """
    Trouve le nouveau type basé sur le type ATC et des mots-clés
    
    Args:
        atc_type: Le type ATC actuel
        medicine_name: Le nom du médicament
        famille_therapeutique: La famille thérapeutique
        
    Returns:
        Le nouveau type ou None
    """
    if not atc_type or atc_type not in ATC_TO_NEW_TYPE_MAPPING:
        return None
    
    mapping = ATC_TO_NEW_TYPE_MAPPING[atc_type]
    
    # Combine le nom et la famille pour la recherche
    search_text = f"{medicine_name} {famille_therapeutique}".lower()
    
    # Chercher des mots-clés dans le texte
    for keyword, new_type in mapping["keywords"].items():
        if keyword.lower() in search_text:
            return new_type
    
    # Retourner le type par défaut
    return mapping["default"]

def main():
    client = MongoClient('mongodb://localhost:27017/')
    db = client['medicsearch']
    medicines = db['medicines']
    
    print('=' * 60)
    print('MIGRATION DES TYPES DE MÉDICAMENTS')
    print('=' * 60)
    
    # Récupérer tous les médicaments
    total = medicines.count_documents({})
    print(f'\nNombre total de médicaments: {total}')
    
    updated_count = 0
    no_type_count = 0
    
    # Traiter tous les médicaments par batch
    batch_size = 100
    for skip in range(0, total, batch_size):
        batch = medicines.find({}).skip(skip).limit(batch_size)
        
        for med in batch:
            atc_type = med.get('groupe_anatomique')
            name = med.get('title', '')
            famille = med.get('famille_therapeutique', '')
            
            # Trouver le nouveau type
            new_type = find_new_type(atc_type, name, famille)
            
            if new_type:
                # Conserver l'ancien type dans un nouveau champ
                medicines.update_one(
                    {'_id': med['_id']},
                    {
                        '$set': {
                            'type_medicament': new_type,
                            'groupe_anatomique_original': atc_type
                        }
                    }
                )
                updated_count += 1
            else:
                no_type_count += 1
        
        # Afficher la progression
        progress = min(skip + batch_size, total)
        print(f'Progression: {progress}/{total} ({100 * progress // total}%)', end='\r')
    
    print(f'\n\nMédicaments mis à jour: {updated_count}')
    print(f'Médicaments sans nouveau type: {no_type_count}')
    
    # Afficher quelques exemples
    print('\nExemples de médicaments avec leurs nouveaux types:')
    examples = medicines.find({'type_medicament': {'$exists': True}}).limit(10)
    for med in examples:
        print(f'\n  Nom: {med.get("title", "N/A")}')
        print(f'  Ancien type (ATC): {med.get("groupe_anatomique_original", "N/A")}')
        print(f'  Nouveau type: {med.get("type_medicament", "N/A")}')

if __name__ == '__main__':
    main()
