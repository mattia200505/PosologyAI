#!/usr/bin/env python3
"""
Générateur d'interactions entre médicaments
Détecte les interactions possibles basées sur:
1. Substances actives communes ou proches
2. Patterns d'interaction connus
"""

from pymongo import MongoClient
import itertools
from datetime import datetime
import json

# Interactions connues dangereuses (substance1 + substance2)
KNOWN_INTERACTIONS = {
    ('Warfarine', 'Aspirine'): {'severity': 'high', 'description': 'Risque accru de saignement'},
    ('Methotrexate', 'Sulfasalazine'): {'severity': 'high', 'description': 'Toxicité accrue'},
    ('Digoxine', 'Vérapamil'): {'severity': 'high', 'description': 'Augmentation des niveaux de digoxine'},
    ('Lithium', 'Diurétiques'): {'severity': 'high', 'description': 'Toxicité du lithium augmentée'},
    ('ACE inhibiteurs', 'Potassium'): {'severity': 'medium', 'description': 'Hyperkaliémie possible'},
    ('Anti-inflammatoires', 'Anticoagulants'): {'severity': 'medium', 'description': 'Risque de saignement'},
    ('Fluconazole', 'Terfénadine'): {'severity': 'high', 'description': 'Arythmies cardiaques possibles'},
    ('Metformine', 'Produits de contraste'): {'severity': 'medium', 'description': 'Acidose lactique'},
    ('Vitamine K', 'Warfarine'): {'severity': 'high', 'description': 'Antagonisme direct'},
}

def connect_db():
    """Connexion à MongoDB"""
    # Essayer d'abord localhost (pour exécution locale), sinon le service Docker
    try:
        client = MongoClient("mongodb://mongo:27017/", serverSelectionTimeoutMS=5000)
        client.admin.command('ping')
        return client["medicsearch"]
    except:
        client = MongoClient("mongodb://localhost:27017/")
        return client["medicsearch"]

def get_all_medicines(db):
    """Récupère tous les médicaments avec leurs substances"""
    medicines = []
    for med in db.medicines.find({}, {
        '_id': 1, 'title': 1, 'medicine_details.substances_actives': 1
    }):
        substances = med.get('medicine_details', {}).get('substances_actives', [])
        if substances:
            medicines.append({
                'id': str(med['_id']),
                'title': med.get('title', 'Sans titre'),
                'substances': [s.lower() for s in substances if s]
            })
    return medicines

def check_substance_interaction(subst1, subst2):
    """Vérifie s'il y a une interaction connue entre deux substances"""
    # Normaliser
    s1, s2 = subst1.lower(), subst2.lower()
    
    # Vérifier les paires connues
    for (known_s1, known_s2), interaction in KNOWN_INTERACTIONS.items():
        known_s1, known_s2 = known_s1.lower(), known_s2.lower()
        
        # Vérification exacte et partielle
        if (known_s1 in s1 or s1 in known_s1) and (known_s2 in s2 or s2 in known_s2):
            return interaction
        if (known_s1 in s1 or s1 in known_s1) or (known_s2 in s2 or s2 in known_s2):
            # Similarité partielle = interaction modérée
            if not ((known_s1 in s1 or s1 in known_s1) and (known_s2 in s2 or s2 in known_s2)):
                return {'severity': 'low', 'description': 'Interaction potentielle à vérifier'}
    
    return None

def generate_interactions(db, limit=None):
    """
    Génère les interactions entre médicaments
    
    Args:
        db: Connexion MongoDB
        limit: Nombre limite d'interactions à générer (None = toutes)
    """
    print("=" * 80)
    print("GÉNÉRATEUR D'INTERACTIONS ENTRE MÉDICAMENTS")
    print("=" * 80)
    
    print("\n[1/4] Chargement des médicaments...")
    medicines = get_all_medicines(db)
    print(f"✓ {len(medicines)} médicaments chargés avec substances")
    
    # Récupérer les interactions existantes
    existing = set(db.interactions.distinct('medicine_pair'))
    print(f"✓ {len(existing)} interactions déjà en base")
    
    print("\n[2/4] Détection des interactions...")
    interactions_to_add = []
    
    # Comparaison par paires
    for med1, med2 in itertools.combinations(medicines, 2):
        pair_key = f"{med1['id']}-{med2['id']}"
        
        if pair_key in existing:
            continue
        
        # Chercher les interactions entre substances
        for subst1, subst2 in itertools.product(med1['substances'], med2['substances']):
            interaction = check_substance_interaction(subst1, subst2)
            
            if interaction:
                interactions_to_add.append({
                    'medicine1_id': med1['id'],
                    'medicine1_title': med1['title'],
                    'medicine2_id': med2['id'],
                    'medicine2_title': med2['title'],
                    'medicine_pair': pair_key,
                    'substance1': subst1,
                    'substance2': subst2,
                    'severity': interaction['severity'],
                    'description': interaction['description'],
                    'created_at': datetime.now(),
                    'verified': False
                })
                break  # Une interaction par paire suffit
        
        if limit and len(interactions_to_add) >= limit:
            break
    
    print(f"✓ {len(interactions_to_add)} interactions détectées")
    
    if not interactions_to_add:
        print("\n⚠️  Aucune interaction trouvée!")
        return
    
    print("\n[3/4] Insertion en base de données...")
    try:
        result = db.interactions.insert_many(interactions_to_add)
        print(f"✓ {len(result.inserted_ids)} interactions ajoutées")
    except Exception as e:
        print(f"✗ Erreur: {str(e)}")
        return
    
    print("\n[4/4] Statistiques...")
    
    # Compter par sévérité
    by_severity = db.interactions.aggregate([
        {'$group': {'_id': '$severity', 'count': {'$sum': 1}}}
    ])
    
    print("\nInteractions par sévérité:")
    for item in by_severity:
        print(f"  • {item['_id'].upper()}: {item['count']}")
    
    # Top interactions
    print("\nTop 5 médicaments impliqués dans les interactions:")
    pipeline = [
        {'$group': {
            '_id': '$medicine1_title',
            'count': {'$sum': 1}
        }},
        {'$sort': {'count': -1}},
        {'$limit': 5}
    ]
    for item in db.interactions.aggregate(pipeline):
        print(f"  • {item['_id']}: {item['count']} interactions")
    
    print("\n" + "=" * 80)
    print(f"✅ {len(interactions_to_add)} interactions générées avec succès!")
    print("=" * 80)

def display_interactions(db, medicine_id=None, min_severity=None):
    """
    Affiche les interactions pour un médicament ou toutes
    
    Args:
        db: Connexion MongoDB
        medicine_id: ID du médicament (optionnel)
        min_severity: Sévérité minimale ('high', 'medium', 'low')
    """
    print("\n" + "=" * 80)
    print("INTERACTIONS DÉTECTÉES")
    print("=" * 80)
    
    # Requête
    query = {}
    if medicine_id:
        query = {'$or': [
            {'medicine1_id': medicine_id},
            {'medicine2_id': medicine_id}
        ]}
    
    if min_severity:
        severity_order = {'high': 3, 'medium': 2, 'low': 1}
        min_level = severity_order.get(min_severity, 0)
        # Approximation - mieux faire avec agrégation
    
    # Récupérer
    interactions = list(db.interactions.find(query).limit(20))
    
    if not interactions:
        print("\n⚠️  Aucune interaction trouvée")
        return
    
    print(f"\n{len(interactions)} interactions trouvées:\n")
    
    for i, inter in enumerate(interactions, 1):
        severity_emoji = {
            'high': '🔴',
            'medium': '🟡',
            'low': '🟢'
        }.get(inter['severity'], '⚪')
        
        print(f"{i}. {severity_emoji} {inter['severity'].upper()}")
        print(f"   {inter['medicine1_title']} + {inter['medicine2_title']}")
        print(f"   Substances: {inter['substance1']} ↔ {inter['substance2']}")
        print(f"   ⚠️  {inter['description']}")
        print()
    
    print("=" * 80)

if __name__ == "__main__":
    import sys
    
    db = connect_db()
    
    if len(sys.argv) > 1:
        command = sys.argv[1]
        
        if command == "generate":
            limit = int(sys.argv[2]) if len(sys.argv) > 2 else None
            generate_interactions(db, limit=limit)
        
        elif command == "display":
            medicine_id = sys.argv[2] if len(sys.argv) > 2 else None
            display_interactions(db, medicine_id=medicine_id)
        
        else:
            print("Usage:")
            print("  python interactions.py generate [limit]  - Générer les interactions")
            print("  python interactions.py display [med_id]  - Afficher les interactions")
    else:
        # Par défaut: générer
        generate_interactions(db)
        
        # Afficher un aperçu
        print("\n\nAperçu des interactions:")
        display_interactions(db)
