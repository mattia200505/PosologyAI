#!/usr/bin/env python3
"""
Generate more drug interactions based on pharmacological incompatibilities
Analyze substance combinations and create new interactions
"""

import json
import time
from pymongo import MongoClient
from typing import Optional, Dict, List, Set
import argparse
from itertools import combinations

class InteractionGenerator:
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
        
        # Initialize incompatibility rules
        self.incompatibility_rules = self._init_rules()
    
    def _init_rules(self) -> Dict:
        """Initialize pharmacological incompatibility rules"""
        return {
            # CNS Depressants interactions
            'cns_depressant': ['opioide', 'benzodiazepine', 'barbiturate', 'alcohol', 'antihistamine'],
            
            # Opioïds interactions
            'opioide': ['cns_depressant', 'benzodiazepine', 'barbiturate', 'alcohol', 'maoi'],
            
            # AINS interactions
            'nsaid': ['ace_inhibitor', 'anticoagulant', 'diuretic', 'corticoid', 'methotrexate', 'ssri'],
            
            # ACE Inhibitors interactions
            'ace_inhibitor': ['nsaid', 'diuretic', 'potassium_sparing', 'potassium'],
            
            # Anticoagulants interactions
            'anticoagulant': ['nsaid', 'aspirin', 'ssri', 'vitamin_k', 'alcohol', 'corticoid'],
            
            # Diuretics interactions
            'diuretic': ['nsaid', 'ace_inhibitor', 'potassium_sparing', 'lithium', 'ototoxic'],
            
            # Benzodiazepines interactions
            'benzodiazepine': ['cns_depressant', 'opioide', 'alcohol', 'antihistamine', 'barbiturate'],
            
            # SSRI interactions
            'ssri': ['maoi', 'tramadol', 'nsaid', 'warfarin', 'lithium'],
            
            # Corticoids interactions
            'corticoid': ['nsaid', 'anticoagulant', 'diuretic', 'potassium_sparing'],
            
            # Benzodiazepine interactions
            'barbiturate': ['cns_depressant', 'benzodiazepine', 'alcohol', 'corticoid'],
            
            # Vitamin K interactions
            'vitamin_k': ['anticoagulant', 'antibiotics'],
            
            # Methotrexate interactions
            'methotrexate': ['nsaid', 'trimethoprim', 'fluorouracil'],
            
            # Lithium interactions
            'lithium': ['diuretic', 'nsaid', 'ace_inhibitor', 'sodium'],
            
            # MAOI interactions
            'maoi': ['ssri', 'opioide', 'sympathomimetic', 'tricyclic'],
            
            # Potassium interactions
            'potassium': ['ace_inhibitor', 'potassium_sparing', 'diuretic'],
            
            # Aspirin interactions
            'aspirin': ['anticoagulant', 'nsaid', 'methotrexate', 'corticoid'],
        }
    
    def classify_substance(self, substance_name: str) -> Set[str]:
        """Classify a substance into pharmacological categories"""
        substance_lower = substance_name.lower()
        classes = set()
        
        # CNS Depressants
        if any(x in substance_lower for x in ['benzodiazep', 'diazepam', 'alprazolam', 'lorazepam']):
            classes.add('benzodiazepine')
        if any(x in substance_lower for x in ['barbitu', 'phenobarbital', 'pentobarbital']):
            classes.add('barbiturate')
        if any(x in substance_lower for x in ['alcool', 'éthanol']):
            classes.add('alcohol')
        if any(x in substance_lower for x in ['antihistamine', 'diphenhydramine', 'promethazine']):
            classes.add('antihistamine')
        
        # Opioïds
        if any(x in substance_lower for x in ['morphine', 'codeine', 'tramadol', 'fentanyl', 'oxycodone']):
            classes.add('opioide')
            classes.add('cns_depressant')
        
        # AINS
        if any(x in substance_lower for x in ['ibuprofen', 'naproxen', 'diclofenac', 'ketoprofen', 'aspirin', 'indomethacin']):
            classes.add('nsaid')
        if 'aspirin' in substance_lower or 'acide acetylsalicylique' in substance_lower:
            classes.add('aspirin')
        
        # ACE Inhibitors
        if any(x in substance_lower for x in ['lisinopril', 'enalapril', 'ramipril', 'captopril', 'perindopril']):
            classes.add('ace_inhibitor')
        
        # Anticoagulants
        if any(x in substance_lower for x in ['warfarine', 'dabigatran', 'rivaroxaban', 'apixaban', 'coumarin']):
            classes.add('anticoagulant')
        
        # Diuretics
        if any(x in substance_lower for x in ['furosemide', 'hydrochlorothiazide', 'spironolactone', 'amiloride']):
            classes.add('diuretic')
        if 'spironolactone' in substance_lower or 'amiloride' in substance_lower:
            classes.add('potassium_sparing')
        
        # SSRI
        if any(x in substance_lower for x in ['sertraline', 'fluoxetine', 'paroxetine', 'escitalopram', 'citalopram']):
            classes.add('ssri')
        
        # Tricyclic
        if any(x in substance_lower for x in ['amitriptyline', 'nortriptyline', 'imipramine']):
            classes.add('tricyclic')
        
        # Corticoids
        if any(x in substance_lower for x in ['prednisone', 'prednisolone', 'dexamethasone', 'methylprednisolone']):
            classes.add('corticoid')
        
        # Vitamins
        if any(x in substance_lower for x in ['vitamine k', 'vitamin k', 'phylloquinone']):
            classes.add('vitamin_k')
        
        # Methotrexate
        if 'methotrexate' in substance_lower:
            classes.add('methotrexate')
        
        # Lithium
        if 'lithium' in substance_lower:
            classes.add('lithium')
        
        # MAOI
        if any(x in substance_lower for x in ['phenelzine', 'tranylcypromine', 'isocarboxazid', 'moclobemide']):
            classes.add('maoi')
        
        # Potassium supplements
        if any(x in substance_lower for x in ['chlorure de potassium', 'potassium chloride']):
            classes.add('potassium')
            classes.add('potassium_sparing')
        
        # Antibiotics (for Vitamin K interactions)
        if any(x in substance_lower for x in ['tetracycline', 'penicillin', 'cephalosporin', 'fluoroquinolone']):
            classes.add('antibiotics')
        
        # Sympathomimetics
        if any(x in substance_lower for x in ['ephedrine', 'pseudoephedrine', 'phenylephrine']):
            classes.add('sympathomimetic')
        
        return classes if classes else set()
    
    def check_existing_interaction(self, medicine1_id: str, medicine2_id: str) -> bool:
        """Check if interaction already exists"""
        interaction = self.interactions_col.find_one({
            'medicine_pair': f"{medicine1_id}-{medicine2_id}"
        }) or self.interactions_col.find_one({
            'medicine_pair': f"{medicine2_id}-{medicine1_id}"
        })
        return interaction is not None
    
    def create_interaction(self, med1: Dict, med2: Dict, classes1: Set[str], classes2: Set[str]) -> Dict:
        """Create interaction document"""
        
        # Determine severity from class incompatibilities
        severity = 'low'
        for c1 in classes1:
            for c2 in classes2:
                if c1 in self.incompatibility_rules and c2 in self.incompatibility_rules[c1]:
                    # High risk combinations
                    if any(x in c1 + c2 for x in ['opioide', 'anticoagulant', 'methotrexate']) and \
                       any(x in c1 + c2 for x in ['opioide', 'anticoagulant', 'methotrexate']):
                        severity = 'high'
                    # Also high if depressant combos
                    elif (c1 in ['opioide', 'benzodiazepine', 'barbiturate'] and \
                          c2 in ['opioide', 'benzodiazepine', 'barbiturate', 'cns_depressant', 'alcohol']):
                        severity = 'high'
                    # Moderate for other combinations
                    else:
                        if severity != 'high':
                            severity = 'moderate'
        
        subst1 = med1.get('medicine_details', {}).get('substances_actives', [''])[0]
        subst2 = med2.get('medicine_details', {}).get('substances_actives', [''])[0]
        
        return {
            'medicine1_id': str(med1['_id']),
            'medicine1_title': med1.get('name', 'Unknown'),
            'medicine2_id': str(med2['_id']),
            'medicine2_title': med2.get('name', 'Unknown'),
            'medicine_pair': f"{med1['_id']}-{med2['_id']}",
            'substance1': subst1,
            'substance2': subst2,
            'substance_classes1': list(classes1),
            'substance_classes2': list(classes2),
            'severity': severity,
            'description': f'Interaction potentielle entre {subst1} et {subst2}',
            'created_at': time.time(),
            'verified': False,
            'generated': True
        }
    
    def generate_interactions(self, limit: int = None):
        """Generate interactions based on substance incompatibilities"""
        
        # Get all medicines with substances
        medicines = list(self.medicines_col.find({
            'medicine_details.substances_actives': {'$exists': True, '$ne': []}
        }))
        
        print(f"\n🔄 Génération d'interactions pharmacologiques")
        print(f"   Médicaments avec substances: {len(medicines)}")
        
        total_medicines = len(medicines)
        generated = 0
        skipped = 0
        
        # Classify all medicines once
        print(f"   Classification des substances...")
        medicine_classes = {}
        medicine_by_id = {}
        for med in medicines:
            med_id = str(med['_id'])
            subst = med.get('medicine_details', {}).get('substances_actives', [''])[0]
            classes = self.classify_substance(subst)
            medicine_classes[med_id] = classes
            medicine_by_id[med_id] = med
        
        # Load existing interactions into memory (faster than querying each time)
        print(f"   Chargement des interactions existantes...")
        existing_pairs = set()
        for existing in self.interactions_col.find({}, {'medicine_pair': 1}):
            existing_pairs.add(existing.get('medicine_pair', ''))
        
        # Generate interactions
        print(f"   Génération des paires d'interactions...")
        interaction_batch = []
        
        for i, med1_id in enumerate(list(medicine_classes.keys())):
            if i % 500 == 0:
                print(f"   Traitement: {i}/{total_medicines} médics (générées: {generated})...")
            
            classes1 = medicine_classes[med1_id]
            med1 = medicine_by_id[med1_id]
            
            if not classes1:
                continue
            
            # Check against other medicines
            for med2_id in list(medicine_classes.keys()):
                if med1_id >= med2_id:  # Avoid duplicates
                    continue
                
                # Check if interaction already exists (fast in-memory check)
                pair_key = f"{med1_id}-{med2_id}"
                if pair_key in existing_pairs:
                    skipped += 1
                    continue
                
                classes2 = medicine_classes[med2_id]
                med2 = medicine_by_id[med2_id]
                
                if not classes2:
                    continue
                
                # Check if any class combination matches incompatibility rules
                has_incompatibility = False
                for c1 in classes1:
                    if c1 in self.incompatibility_rules:
                        for c2 in classes2:
                            if c2 in self.incompatibility_rules[c1]:
                                has_incompatibility = True
                                break
                    if has_incompatibility:
                        break
                
                # Create interaction if incompatibility found
                if has_incompatibility:
                    interaction = self.create_interaction(med1, med2, classes1, classes2)
                    interaction_batch.append(interaction)
                    generated += 1
                    
                    # Batch insert for efficiency
                    if len(interaction_batch) >= 100:
                        try:
                            self.interactions_col.insert_many(interaction_batch)
                            interaction_batch = []
                        except Exception as e:
                            print(f"  ⚠️ Erreur insertion batch: {e}")
            
            # Apply limit if specified
            if limit and generated >= limit:
                break
        
        # Insert remaining interactions
        if interaction_batch:
            try:
                self.interactions_col.insert_many(interaction_batch)
            except Exception as e:
                print(f"  ⚠️ Erreur insertion finale: {e}")
        
        print(f"\n✅ Génération complétée:")
        print(f"   Interactions générées: {generated}")
        print(f"   Interactions existantes (non dupliquées): {skipped}")
        print(f"   Total interactions en base: {self.interactions_col.count_documents({})}")
        
        return generated

def main():
    parser = argparse.ArgumentParser(description='Generate drug interactions from pharmacological incompatibilities')
    parser.add_argument('--limit', type=int, help='Maximum number of interactions to generate')
    args = parser.parse_args()
    
    generator = InteractionGenerator()
    generator.generate_interactions(args.limit)

if __name__ == '__main__':
    main()
