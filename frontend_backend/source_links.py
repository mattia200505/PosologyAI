"""
Mapping des sources vers leurs URLs
"""

SOURCE_URLS = {
    "ANSM": {
        "url": "https://base-donnees-publique.medicaments.gouv.fr",
        "name": "ANSM",
        "name_en": "French National Agency for Medicines Safety",
        "icon": "🏥"
    },
    "Thériaque": {
        "url": "https://www.therique.org",
        "name": "Thériaque",
        "name_en": "Theriaque Database",
        "icon": "📚"
    },
    "HAS": {
        "url": "https://www.has-sante.fr",
        "name": "HAS",
        "name_en": "French Authority for Health",
        "icon": "✓"
    },
    "AFMPS": {
        "url": "https://www.afmps.be",
        "name": "AFMPS",
        "name_en": "Belgian Medicines Authority",
        "icon": "🏥"
    },
    "EMA": {
        "url": "https://www.ema.europa.eu",
        "name": "EMA",
        "name_en": "European Medicines Agency",
        "icon": "🌍"
    },
    "FDA": {
        "url": "https://www.fda.gov",
        "name": "FDA",
        "name_en": "US Food and Drug Administration",
        "icon": "🇺🇸"
    }
}

def get_source_info(source_name):
    """Retourner les infos (URL, nom) pour une source"""
    if source_name in SOURCE_URLS:
        return SOURCE_URLS[source_name]
    # Par défaut ANSM
    return SOURCE_URLS.get("ANSM", {})
