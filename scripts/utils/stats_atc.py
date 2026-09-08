#!/usr/bin/env python3
"""Afficher les statistiques sur les codes ATC et familles"""
from pymongo import MongoClient
from collections import Counter
import json

client = MongoClient('mongodb://localhost:27017/')
db = client['medicsearch']

print("="*70)
print("📊 STATISTIQUES DES CODES ATC ET FAMILLES THÉRAPEUTIQUES")
print("="*70)

# Total de médicaments
total = db['medicines'].count_documents({})
print(f"\nTotal de médicaments: {total:,}")

# Avec code ATC
with_atc = db['medicines'].count_documents({'code_atc': {'$exists': True}})
print(f"Avec code ATC: {with_atc:,} ({with_atc/total*100:.1f}%)")

# Avec famille thérapeutique
with_family = db['medicines'].count_documents({'famille_therapeutique': {'$exists': True}})
print(f"Avec famille thérapeutique: {with_family:,} ({with_family/total*100:.1f}%)")

# Avec groupe anatomique
with_group = db['medicines'].count_documents({'groupe_anatomique': {'$exists': True}})
print(f"Avec groupe anatomique: {with_group:,} ({with_group/total*100:.1f}%)")

# Top 10 groupes anatomiques les plus fréquents
print("\n" + "="*70)
print("🏥 TOP 10 GROUPES ANATOMIQUES")
print("="*70)

pipeline = [
    {'$match': {'groupe_anatomique': {'$exists': True}}},
    {'$group': {'_id': '$groupe_anatomique', 'count': {'$sum': 1}}},
    {'$sort': {'count': -1}},
    {'$limit': 10}
]

for i, group in enumerate(db['medicines'].aggregate(pipeline), 1):
    print(f"{i:2}. {group['_id']:50} ({group['count']:4} médicaments)")

# Top 10 codes ATC les plus fréquents
print("\n" + "="*70)
print("💊 TOP 10 CODES ATC")
print("="*70)

pipeline = [
    {'$match': {'code_atc': {'$exists': True}}},
    {'$group': {'_id': '$code_atc', 'count': {'$sum': 1}, 'exemple': {'$first': '$title'}}},
    {'$sort': {'count': -1}},
    {'$limit': 10}
]

for i, code in enumerate(db['medicines'].aggregate(pipeline), 1):
    print(f"{i:2}. {code['_id']:10} ({code['count']:4} médicaments) - Ex: {code['exemple'][:40]}...")

# Exemples de médicaments enrichis
print("\n" + "="*70)
print("📋 EXEMPLES DE MÉDICAMENTS ENRICHIS")
print("="*70)

examples = db['medicines'].find(
    {'code_atc': {'$exists': True}, 'famille_therapeutique': {'$exists': True}},
    limit=3
)

for i, med in enumerate(examples, 1):
    print(f"\n{i}. {med.get('title')}")
    print(f"   Code ATC: {med.get('code_atc')}")
    print(f"   Groupe: {med.get('groupe_anatomique', 'N/A')}")
    print(f"   Famille: {med.get('famille_therapeutique', 'N/A')[:80]}...")
    if med.get('libelle_atc'):
        print(f"   Libellé: {med.get('libelle_atc')[:80]}...")

print("\n" + "="*70)

client.close()
