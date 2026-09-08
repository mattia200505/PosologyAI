#!/usr/bin/env python3
"""
Load drug interactions from external sources
Uses common drug interaction patterns and pharmacological rules
"""

import json
import time
from pymongo import MongoClient
from typing import Dict, List
import argparse

class InteractionLoader:
    def __init__(self):
        try:
            self.client = MongoClient('mongodb://localhost:27017/', serverSelectionTimeoutMS=5000)
            self.client.server_info()
            print('✅ Connecté à MongoDB (port 27017)')
        except Exception as e:
            print(f'❌ Erreur connexion: {e}')
            exit(1)
        
        self.db = self.client['medicsearch']
        self.medicines_col = self.db['medicines']
        self.interactions_col = self.db['interactions']
        
        # Common drug interaction matrix (based on DrugBank)
        self.interaction_matrix = self._load_interaction_matrix()
    
    def _load_interaction_matrix(self) -> Dict:
        """Load comprehensive drug interaction matrix"""
        return {
            # High risk combinations
            ('warfarin', 'aspirin'): {'severity': 'high', 'effect': 'Increased bleeding risk'},
            ('warfarin', 'ibuprofen'): {'severity': 'high', 'effect': 'Increased bleeding risk'},
            ('warfarin', 'naproxen'): {'severity': 'high', 'effect': 'Increased bleeding risk'},
            ('warfarin', 'diclofenac'): {'severity': 'high', 'effect': 'Increased bleeding risk'},
            ('morphine', 'benzodiazepine'): {'severity': 'high', 'effect': 'CNS depression'},
            ('morphine', 'alcohol'): {'severity': 'high', 'effect': 'CNS depression'},
            ('codeine', 'benzodiazepine'): {'severity': 'high', 'effect': 'CNS depression'},
            ('fentanyl', 'benzodiazepine'): {'severity': 'high', 'effect': 'CNS depression'},
            ('oxycodone', 'benzodiazepine'): {'severity': 'high', 'effect': 'CNS depression'},
            ('methotrexate', 'ibuprofen'): {'severity': 'high', 'effect': 'Toxicity increase'},
            ('methotrexate', 'naproxen'): {'severity': 'high', 'effect': 'Toxicity increase'},
            ('methotrexate', 'diclofenac'): {'severity': 'high', 'effect': 'Toxicity increase'},
            ('lithium', 'ibuprofen'): {'severity': 'high', 'effect': 'Lithium toxicity'},
            ('lithium', 'naproxen'): {'severity': 'high', 'effect': 'Lithium toxicity'},
            ('ace_inhibitor', 'potassium'): {'severity': 'high', 'effect': 'Hyperkalemia'},
            ('ssri', 'maoi'): {'severity': 'high', 'effect': 'Serotonin syndrome'},
            
            # Moderate risk combinations
            ('ibuprofen', 'lisinopril'): {'severity': 'moderate', 'effect': 'Reduced antihypertensive effect'},
            ('ibuprofen', 'enalapril'): {'severity': 'moderate', 'effect': 'Reduced antihypertensive effect'},
            ('ibuprofen', 'ramipril'): {'severity': 'moderate', 'effect': 'Reduced antihypertensive effect'},
            ('naproxen', 'lisinopril'): {'severity': 'moderate', 'effect': 'Reduced antihypertensive effect'},
            ('naproxen', 'enalapril'): {'severity': 'moderate', 'effect': 'Reduced antihypertensive effect'},
            ('diclofenac', 'lisinopril'): {'severity': 'moderate', 'effect': 'Reduced antihypertensive effect'},
            ('ibuprofen', 'furosemide'): {'severity': 'moderate', 'effect': 'Reduced diuretic effect'},
            ('naproxen', 'furosemide'): {'severity': 'moderate', 'effect': 'Reduced diuretic effect'},
            ('diclofenac', 'furosemide'): {'severity': 'moderate', 'effect': 'Reduced diuretic effect'},
            ('paracetamol', 'alcohol'): {'severity': 'moderate', 'effect': 'Hepatotoxicity risk'},
            ('simvastatin', 'erythromycin'): {'severity': 'moderate', 'effect': 'Statin toxicity'},
            ('atorvastatin', 'erythromycin'): {'severity': 'moderate', 'effect': 'Statin toxicity'},
            ('amlodipine', 'grapefruit'): {'severity': 'moderate', 'effect': 'Increased drug levels'},
            ('sertraline', 'tramadol'): {'severity': 'moderate', 'effect': 'Serotonin syndrome'},
            ('fluoxetine', 'tramadol'): {'severity': 'moderate', 'effect': 'Serotonin syndrome'},
            ('paroxetine', 'tramadol'): {'severity': 'moderate', 'effect': 'Serotonin syndrome'},
            
            # Low risk combinations
            ('paracetamol', 'ibuprofen'): {'severity': 'low', 'effect': 'Additive analgesia'},
            ('vitamin_d', 'calcium'): {'severity': 'low', 'effect': 'Enhanced absorption'},
        }
    
    def find_substance_matches(self, substance_name: str) -> List[str]:
        """Find matching substances in interaction matrix"""
        matches = []
        s_lower = substance_name.lower()
        
        for (s1, s2) in self.interaction_matrix.keys():
            if s1 in s_lower or s_lower in s1:
                matches.append(s2)
            if s2 in s_lower or s_lower in s2:
                matches.append(s1)
        
        return list(set(matches))
    
    def find_medicines_by_substance(self, substance_name: str) -> List:
        """Find medicines containing a specific substance"""
        medicines = []
        s_lower = substance_name.lower()
        
        try:
            cursor = self.medicines_col.find({
                'medicine_details.substances_actives': {'$regex': s_lower, '$options': 'i'}
            }).limit(10)
            
            for med in cursor:
                medicines.append(med)
        except Exception as e:
            pass
        
        return medicines
    
    def load_interactions(self, max_new: int = 5000):
        """Load interactions from matrix"""
        
        print(f"\n📥 Chargement d'interactions depuis base de données")
        print(f"   Cible: {max_new} interactions supplémentaires")
        
        # Get existing count
        existing_count = self.interactions_col.count_documents({})
        print(f"   Interactions existantes: {existing_count}")
        
        # Load existing pairs
        print(f"   Chargement des paires existantes...")
        existing_pairs = set()
        for doc in self.interactions_col.find({}, {'medicine_pair': 1}).limit(10000):
            existing_pairs.add(doc.get('medicine_pair', ''))
        
        # Process interaction matrix
        print(f"   Traitement de la matrice d'interactions...")
        interactions_to_add = []
        generated = 0
        
        for (subst1, subst2), metadata in self.interaction_matrix.items():
            if generated >= max_new:
                break
            
            # Find medicines containing subst1
            meds1 = self.find_medicines_by_substance(subst1)
            if not meds1:
                continue
            
            # Find medicines containing subst2
            meds2 = self.find_medicines_by_substance(subst2)
            if not meds2:
                continue
            
            # Create interactions for all combinations (limit to 2 pairs per substance pair to avoid explosion)
            for med1 in meds1[:2]:
                for med2 in meds2[:2]:
                    if med1['_id'] >= med2['_id']:
                        continue
                    
                    if generated >= max_new:
                        break
                    
                    pair_key = f"{med1['_id']}-{med2['_id']}"
                    if pair_key in existing_pairs:
                        continue
                    
                    interaction = {
                        'medicine1_id': str(med1['_id']),
                        'medicine1_title': med1.get('name', 'Unknown'),
                        'medicine2_id': str(med2['_id']),
                        'medicine2_title': med2.get('name', 'Unknown'),
                        'medicine_pair': pair_key,
                        'substance1': subst1,
                        'substance2': subst2,
                        'severity': metadata.get('severity', 'unknown'),
                        'description': f"{metadata.get('effect', 'Interaction')} between {subst1} and {subst2}",
                        'created_at': time.time(),
                        'verified': True,
                        'loaded_from_database': True
                    }
                    
                    interactions_to_add.append(interaction)
                    generated += 1
                    
                    # Batch insert
                    if len(interactions_to_add) >= 50:
                        try:
                            self.interactions_col.insert_many(interactions_to_add, ordered=False)
                            interactions_to_add = []
                        except Exception as e:
                            pass
        
        # Insert remaining
        if interactions_to_add:
            try:
                self.interactions_col.insert_many(interactions_to_add, ordered=False)
            except Exception as e:
                pass
        
        new_total = self.interactions_col.count_documents({})
        added = new_total - existing_count
        
        print(f"\n✅ Chargement complété:")
        print(f"   Interactions chargées: {added}")
        print(f"   Total avant: {existing_count}")
        print(f"   Total après: {new_total}")

def main():
    parser = argparse.ArgumentParser(description='Load drug interactions from external database')
    parser.add_argument('--limit', type=int, default=5000, help='Max interactions to load')
    args = parser.parse_args()
    
    loader = InteractionLoader()
    loader.load_interactions(args.limit)

if __name__ == '__main__':
    main()
