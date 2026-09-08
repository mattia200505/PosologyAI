"""
Configuration des catégories et types de médicaments
Organisation hiérarchique avec emojis pour l'interface utilisateur
"""

# Structure hiérarchique des catégories de médicaments
MEDICINE_CATEGORIES = {
    "🩹 Douleur / fièvre": {
        "emoji": "🩹",
        "name": "Douleur / fièvre",
        "types": [
            "Analgésiques (douleur)",
            "Antipyrétiques (fièvre)",
            "Anti-inflammatoires non stéroïdiens (AINS)",
            "Corticoïdes"
        ]
    },
    "🦠 Infections": {
        "emoji": "🦠",
        "name": "Infections",
        "types": [
            "Antibiotiques",
            "Antiviraux",
            "Antifongiques",
            "Antiparasitaires",
            "Antituberculeux"
        ]
    },
    "🧠 Système nerveux / Psychiatrie": {
        "emoji": "🧠",
        "name": "Système nerveux / Psychiatrie",
        "types": [
            "Anxiolytiques",
            "Hypnotiques (somnifères)",
            "Antidépresseurs",
            "Antipsychotiques (neuroleptiques)",
            "Antiépileptiques",
            "Psychostimulants",
            "Antiparkinsoniens",
            "Myorelaxants",
            "Anesthésiques"
        ]
    },
    "❤️ Cœur / circulation": {
        "emoji": "❤️",
        "name": "Cœur / circulation",
        "types": [
            "Antihypertenseurs",
            "Antiangineux",
            "Antiarythmiques",
            "Anticoagulants",
            "Antiagrégants plaquettaires",
            "Hypolipidémiants",
            "Vasodilatateurs",
            "Diurétiques"
        ]
    },
    "🌬️ Respiration": {
        "emoji": "🌬️",
        "name": "Respiration",
        "types": [
            "Bronchodilatateurs",
            "Corticoïdes inhalés",
            "Antitussifs",
            "Mucolytiques / expectorants",
            "Antihistaminiques"
        ]
    },
    "🍽️ Digestion / métabolisme": {
        "emoji": "🍽️",
        "name": "Digestion / métabolisme",
        "types": [
            "Anti-ulcéreux (IPP, anti-H2)",
            "Antiacides",
            "Antispasmodiques",
            "Antiémétiques",
            "Laxatifs",
            "Antidiarrhéiques",
            "Antidiabétiques",
            "Hypoglycémiants",
            "Enzymes digestives"
        ]
    },
    "🧬 Hormones / endocrinologie": {
        "emoji": "🧬",
        "name": "Hormones / endocrinologie",
        "types": [
            "Hormones thyroïdiennes",
            "Hormones sexuelles",
            "Contraceptifs",
            "Insulines",
            "Corticostéroïdes systémiques",
            "Hormones de croissance",
            "Antithyroïdiens"
        ]
    },
    "🩸 Sang / immunité": {
        "emoji": "🩸",
        "name": "Sang / immunité",
        "types": [
            "Antianémiques",
            "Facteurs de coagulation",
            "Immunosuppresseurs",
            "Immunostimulants",
            "Vaccins",
            "Anticorps monoclonaux"
        ]
    },
    "🧴 Peau": {
        "emoji": "🧴",
        "name": "Peau",
        "types": [
            "Dermocorticoïdes",
            "Antiseptiques",
            "Antifongiques cutanés",
            "Antibiotiques locaux",
            "Antiacnéiques"
        ]
    },
    "🧠 Cancérologie": {
        "emoji": "💊",
        "name": "Cancérologie",
        "types": [
            "Anticancéreux (chimiothérapie)",
            "Thérapies ciblées",
            "Hormonothérapies",
            "Immunothérapies"
        ]
    },
    "👁️ ORL / yeux": {
        "emoji": "👁️",
        "name": "ORL / yeux",
        "types": [
            "Collyres",
            "Antiglaucomateux",
            "Décongestionnants",
            "Gouttes auriculaires"
        ]
    }
}

# Liste plate de tous les types pour validation
ALL_MEDICINE_TYPES = []
for category in MEDICINE_CATEGORIES.values():
    ALL_MEDICINE_TYPES.extend(category["types"])

# Mapping inverse: type -> catégorie
TYPE_TO_CATEGORY = {}
for category_key, category_data in MEDICINE_CATEGORIES.items():
    for med_type in category_data["types"]:
        TYPE_TO_CATEGORY[med_type] = {
            "category_key": category_key,
            "category_name": category_data["name"],
            "emoji": category_data["emoji"]
        }

def get_category_for_type(medicine_type):
    """
    Retourne la catégorie d'un type de médicament
    
    Args:
        medicine_type (str): Le type de médicament
        
    Returns:
        dict: Informations sur la catégorie (nom, emoji) ou None
    """
    return TYPE_TO_CATEGORY.get(medicine_type)

def get_all_types():
    """
    Retourne la liste de tous les types de médicaments
    
    Returns:
        list: Liste de tous les types
    """
    return ALL_MEDICINE_TYPES

def get_categories_with_types():
    """
    Retourne la structure complète des catégories avec leurs types
    
    Returns:
        dict: Structure hiérarchique complète
    """
    return MEDICINE_CATEGORIES

def get_types_by_category(category_name):
    """
    Retourne les types pour une catégorie donnée
    
    Args:
        category_name (str): Nom de la catégorie (avec ou sans emoji)
        
    Returns:
        list: Liste des types de cette catégorie
    """
    for category_key, category_data in MEDICINE_CATEGORIES.items():
        if category_data["name"] == category_name or category_key == category_name:
            return category_data["types"]
    return []
