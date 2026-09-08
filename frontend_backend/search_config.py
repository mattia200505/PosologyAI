"""
Configuration des scores de pertinence pour la recherche
Ajustez ces valeurs pour affiner la qualité des résultats
"""

# Poids des différents facteurs dans le calcul de pertinence
SEARCH_WEIGHTS = {
    # Recherche dans le titre (très important)
    'title_exact': 100,              # Match exact du titre complet
    'title_contains': 50,            # Titre contient le terme
    'title_word_start': 40,          # Terme au début d'un mot du titre
    
    # Recherche dans les substances actives (très important)
    'substance_exact': 80,           # Match exact de la substance
    'substance_contains': 35,        # Substance contient le terme
    
    # Recherche dans la forme et dosage
    'forme_contains': 15,            # Forme pharmaceutique
    'dosage_contains': 12,           # Dosage
    
    # Recherche dans les sections
    'section_title': 10,             # Titre de section
    'section_content': 3,            # Contenu de section
    'subsection_match': 5,           # Sous-section
}

# Facteurs de boost/pénalité
BOOST_FACTORS = {
    'multiple_terms_found': 0.1,     # Bonus par terme supplémentaire trouvé (+10% par terme)
    'important_section_multiplier': 1.5,  # Multiplicateur pour sections importantes
}

# Seuils de filtrage
SEARCH_THRESHOLDS = {
    'vector_search_min_score': 0.05,      # Score minimum pour recherche vectorielle
    'vector_search_combined_min': 0.15,   # Score minimum combiné (vector + text)
    'text_search_min_score': 1,           # Score minimum pour recherche textuelle
}

# Mots-clés des sections importantes pour la pondération
IMPORTANT_SECTION_KEYWORDS = [
    'denomination',
    'composition',
    'proprietes',
    'indications',
    'posologie',
    'contre-indication',
    'effet',
    'interaction',
    'pharmacodynamique',
    'pharmacocinetique'
]

# Pondération vectoriel vs textuelle dans la recherche hybride
VECTOR_SEARCH_WEIGHTS = {
    'vector_score_weight': 0.4,      # 40% du score provient de la recherche vectorielle
    'text_score_weight': 0.6,        # 60% du score provient de la pertinence textuelle
}

# Facteurs de multiplicateur pour l'IA (amélioration future)
AI_SEARCH_WEIGHTS = {
    'semantic_relevance': 0.5,
    'text_relevance': 0.3,
    'popularity': 0.2,
}

# Options de test et debug
DEBUG = False
VERBOSE_SCORING = False  # Affiche les détails de calcul du score (lent)

if __name__ == '__main__':
    print("Configuration des scores de recherche:")
    print(f"  Poids des titres: {SEARCH_WEIGHTS['title_exact']} (exact), {SEARCH_WEIGHTS['title_contains']} (contient)")
    print(f"  Poids des substances: {SEARCH_WEIGHTS['substance_exact']} (exact), {SEARCH_WEIGHTS['substance_contains']} (contient)")
    print(f"  Seuil vectoriel: {SEARCH_THRESHOLDS['vector_search_min_score']}")
    print(f"  Seuil textuel: {SEARCH_THRESHOLDS['text_search_min_score']}")
