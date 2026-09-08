#!/usr/bin/env python3
"""
Simple interaction generator - uses substance classification rules
to create realistic interactions without overloading memory
"""

import json
import time
from pymongo import MongoClient
from typing import Dict, List, Set
import argparse

class SimpleInteractionGenerator:
    def __init__(self):
        try:
            self.client = MongoClient('mongodb://localhost:27017/', serverSelectionTimeoutMS=5000, 
                                     socketTimeoutMS=30000, connectTimeoutMS=30000)
            self.client.server_info()
            print('✅ Connecté à MongoDB (port 27017)')
        except Exception as e:
            print(f'❌ Erreur connexion: {e}')
            exit(1)
        
        self.db = self.client['medicsearch']
        self.medicines_col = self.db['medicines']
        self.interactions_col = self.db['interactions']
        
        # Simple incompatibility matrix
        self.incompatibilities = {
            'opioide': ['benzodiazepine', 'barbiturate', 'alcohol', 'cns_depressant'],
            'nsaid': ['ace_inhibitor', 'anticoagulant', 'diuretic'],
            'ace_inhibitor': ['diuretic', 'nsaid'],
            'anticoagulant': ['aspirin', 'nsaid'],
            'benzodiazepine': ['opioide', 'alcohol', 'barbiturate'],
            'ssri': ['maoi', 'tramadol'],
            'corticoid': ['nsaid', 'anticoagulant'],
        }
    
    def classify_substance(self, substance_name: str) -> List[str]:
        """Simple substance classification"""
        s_lower = substance_name.lower()
        classes = []
        
        if any(x in s_lower for x in ['morphine', 'codeine', 'tramadol', 'fentanyl', 'oxycodone']):
            classes.append('opioide')
        if any(x in s_lower for x in ['ibuprofen', 'naproxen', 'aspirin', 'diclofenac']):
            classes.append('nsaid')
        if any(x in s_lower for x in ['lisinopril', 'enalapril', 'ramipril']):
            classes.append('ace_inhibitor')
        if any(x in s_lower for x in ['warfarine', 'dabigatran', 'rivaroxaban']):
            classes.append('anticoagulant')
        if any(x in s_lower for x in ['benzodiazep', 'diazepam', 'alprazolam']):
            classes.append('benzodiazepine')
        if any(x in s_lower for x in ['furosemide', 'hydrochlorothiazide']):
            classes.append('diuretic')
        if any(x in s_lower for x in ['sertraline', 'fluoxetine', 'paroxetine']):
            classes.append('ssri')
        if any(x in s_lower for x in ['prednisone', 'dexamethasone']):
            classes.append('corticoid')
        if 'alcohol' in s_lower or 'ethanol' in s_lower:
            classes.append('alcohol')
        if 'cns' in s_lower or 'depressant' in s_lower:
            classes.append('cns_depressant')
        if 'phenelzine' in s_lower or 'tranylcypromine' in s_lower:
            classes.append('maoi')
        if 'barbitu' in s_lower:
            classes.append('barbiturate')
        
        return classes
    
    def generate_simple(self, max_interactions: int = 5000):
        """Generate interactions in batches"""
        
        print(f"\n🔄 Génération simple d'interactions")
        print(f"   Cible: {max_interactions} interactions")
        
        # Get existing interactions count
        existing_count = self.interactions_col.count_documents({})
        print(f"   Interactions existantes: {existing_count}")
        
        # Get all medicines (with smaller batch to avoid timeout)
        batch_size = 500
        skip = 0
        medicines = []
        
        print(f"   Chargement des médicaments...")
        while True:
            batch = list(self.medicines_col.find({
                'medicine_details.substances_actives': {'$exists': True, '$ne': []}
            }).skip(skip).limit(batch_size))
            
            if not batch:
                break
            
            medicines.extend(batch)
            skip += batch_size
            print(f"   Chargés: {len(medicines)} médicaments...")
            
            if len(medicines) >= 5000:  # Limit to 5000 to avoid memory issues
                break
        
        print(f"   Total: {len(medicines)} médicaments avec substances")
        
        # Classify all medicines
        print(f"   Classification...")
        med_classes = {}
        for med in medicines:
            med_id = str(med['_id'])
            subst = med.get('medicine_details', {}).get('substances_actives', [''])[0]
            classes = self.classify_substance(subst)
            med_classes[med_id] = {
                'classes': classes,
                'substance': subst,
                'name': med.get('name', 'Unknown')
            }
        
        # Load existing pairs
        print(f"   Chargement des interactions existantes...")
        existing_pairs = set()
        for doc in self.interactions_col.find({}, {'medicine_pair': 1}):
            existing_pairs.add(doc.get('medicine_pair', ''))
        
        # Generate interactions
        print(f"   Génération des paires...")
        interactions_to_add = []
        generated = 0
        
        med_ids = list(med_classes.keys())
        for i, med1_id in enumerate(med_ids):
            if i % 500 == 0:
                print(f"   Progrès: {i}/{len(med_ids)} | Générées: {generated}/{max_interactions}")
            
            classes1 = med_classes[med1_id]['classes']
            name1 = med_classes[med1_id]['name']
            subst1 = med_classes[med1_id]['substance']
            
            if not classes1:
                continue
            
            # Check against other medicines
            for j, med2_id in enumerate(med_ids):
                if i >= j:  # Avoid duplicates
                    continue
                
                if generated >= max_interactions:
                    break
                
                # Check if pair already exists
                pair_key = f"{med1_id}-{med2_id}"
                if pair_key in existing_pairs:
                    continue
                
                classes2 = med_classes[med2_id]['classes']
                name2 = med_classes[med2_id]['name']
                subst2 = med_classes[med2_id]['substance']
                
                if not classes2:
                    continue
                
                # Check for incompatibility
                found_incomp = False
                for c1 in classes1:
                    if c1 in self.incompatibilities:
                        for c2 in classes2:
                            if c2 in self.incompatibilities[c1]:
                                found_incomp = True
                                break
                    if found_incomp:
                        break
                
                if found_incomp:
                    # Determine severity
                    severity = 'moderate'
                    high_risk = {'opioide', 'anticoagulant', 'benzodiazepine'}
                    if any(c in classes1 + classes2 for c in high_risk):
                        severity = 'high'
                    
                    interaction = {
                        'medicine1_id': med1_id,
                        'medicine1_title': name1,
                        'medicine2_id': med2_id,
                        'medicine2_title': name2,
                        'medicine_pair': pair_key,
                        'substance1': subst1,
                        'substance2': subst2,
                        'severity': severity,
                        'description': f'Interaction potentielle entre {subst1} et {subst2}',
                        'created_at': time.time(),
                        'verified': False,
                        'generated': True
                    }
                    
                    interactions_to_add.append(interaction)
                    generated += 1
                    
                    # Batch insert
                    if len(interactions_to_add) >= 100:
                        self.interactions_col.insert_many(interactions_to_add, ordered=False)
                        interactions_to_add = []
            
            if generated >= max_interactions:
                break
        
        # Insert remaining
        if interactions_to_add:
            self.interactions_col.insert_many(interactions_to_add, ordered=False)
        
        new_total = self.interactions_col.count_documents({})
        print(f"\n✅ Génération complétée:")
        print(f"   Interactions générées: {generated}")
        print(f"   Total en base avant: {existing_count}")
        print(f"   Total en base après: {new_total}")

def main():
    parser = argparse.ArgumentParser(description='Generate simple drug interactions')
    parser.add_argument('--limit', type=int, default=5000, help='Max interactions to generate')
    args = parser.parse_args()
    
    gen = SimpleInteractionGenerator()
    gen.generate_simple(args.limit)

if __name__ == '__main__':
    main()
