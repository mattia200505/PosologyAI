#!/usr/bin/env python3
"""
Enrich drug interactions table with detailed clinical data
Adds severity levels, symptoms, and recommendations based on substance analysis
"""

import json
import time
from pymongo import MongoClient
from typing import Optional, Dict, List
import argparse

class InteractionEnricher:
    def __init__(self):
        try:
            self.client = MongoClient('mongodb://localhost:27017/', serverSelectionTimeoutMS=5000)
            self.client.server_info()
            print('✅ Connecté à MongoDB (port 27017)')
        except Exception as e:
            print(f'❌ Erreur connexion: {e}')
            exit(1)
        
        self.db = self.client['medicsearch']
        self.interactions_col = self.db['interactions']
        self.medicines_col = self.db['medicines']
        
        # Initialize interaction knowledge base
        self.interaction_db = self._init_interaction_db()
    
    def _init_interaction_db(self) -> Dict:
        """Initialize comprehensive drug interaction database"""
        return {
            # Opioïds interactions
            ('morphine', 'cns_depressant'): {
                'severity': 'high',
                'mechanism': 'Dépression additive du système nerveux central',
                'symptoms': ['Somnolence extrême', 'Dépression respiratoire', 'Perte de conscience', 'Décès possible'],
                'recommendation': 'Éviter ou utilisateur avec prudence - surveillance étroite requise',
                'clinical_evidence': 'Grade A - Preuve solide'
            },
            ('morphine', 'alcohol'): {
                'severity': 'high',
                'mechanism': 'Potentialisation de la dépression du SNC et des effets opioïdes',
                'symptoms': ['Dépression respiratoire', 'Somnolence profonde', 'Coma', 'Mort subite'],
                'recommendation': 'CONTRAINDICATION ABSOLUE - Éviter complètement l\'alcool',
                'clinical_evidence': 'Grade A - Preuve très solide'
            },
            ('morphine', 'benzodiazepine'): {
                'severity': 'high',
                'mechanism': 'Synergie dépressive du SNC et respiratoire',
                'symptoms': ['Sédation profonde', 'Dépression respiratoire grave', 'Apnée'],
                'recommendation': 'Combinaison dangereuse - éviter ou surveillance intensive',
                'clinical_evidence': 'Grade A - Nombreux rapports'
            },
            
            # AINS interactions
            ('ibuprofen', 'ace_inhibitor'): {
                'severity': 'moderate',
                'mechanism': 'Les AINS réduisent l\'efficacité des ACE inhibiteurs',
                'symptoms': ['Augmentation de la tension artérielle', 'Baisse de l\'efficacité antihypertensive'],
                'recommendation': 'Monitorer la TA régulièrement, envisager alternative aux AINS',
                'clinical_evidence': 'Grade B - Études confirmantes'
            },
            ('ibuprofen', 'anticoagulant'): {
                'severity': 'moderate',
                'mechanism': 'Risque accru de saignement et ulcération GI',
                'symptoms': ['Hémorragie gastrique', 'Hématomes', 'Saignements anormaux'],
                'recommendation': 'Préférer le paracétamol, si AINS nécessaire = IPP + surveillance',
                'clinical_evidence': 'Grade A - Bien établi'
            },
            ('ibuprofen', 'diuretic'): {
                'severity': 'moderate',
                'mechanism': 'Réduction de l\'efficacité diurétique et insuffisance rénale possible',
                'symptoms': ['Rétention hydrique', 'Augmentation TA', 'Baisse fonction rénale'],
                'recommendation': 'Monitorer créatinine et K+, envisager alternative',
                'clinical_evidence': 'Grade B - Données cliniques'
            },
            ('ibuprofen', 'methotrexate'): {
                'severity': 'high',
                'mechanism': 'Réduction de la clairance du méthotrexate = toxicité augmentée',
                'symptoms': ['Stomatite', 'Diarrhée sévère', 'Myélosuppression', 'Néphrotoxicité'],
                'recommendation': 'Éviter les AINS avec le méthotrexate - utiliser paracétamol',
                'clinical_evidence': 'Grade A - Bien documenté'
            },
            
            # Paracétamol interactions
            ('paracetamol', 'alcohol'): {
                'severity': 'moderate',
                'mechanism': 'Augmentation du risque d\'hépatotoxicité',
                'symptoms': ['Atteinte hépatique', 'Nausées', 'Jaunisse', 'Insuffisance hépatique'],
                'recommendation': 'Limiter consommation alcool, dosage max 3-4g/jour (au lieu de 4g)',
                'clinical_evidence': 'Grade B - Rapports de cas'
            },
            ('paracetamol', 'nsaid'): {
                'severity': 'moderate',
                'mechanism': 'Association multimodale analgésique (généralement bénéfique)',
                'symptoms': ['Généralement bien tolérée', 'Attention: pas de dépassement total'],
                'recommendation': 'Combinaison acceptable si dosages respectés (max 4g paracétamol/jour)',
                'clinical_evidence': 'Grade A - Largement utilisée'
            },
            
            # Vitamines interactions
            ('vitamin_a', 'vitamin_d'): {
                'severity': 'low',
                'mechanism': 'Absorption compétitive possible mais généralement acceptable',
                'symptoms': ['Généralement bien tolérée'],
                'recommendation': 'Espacement de 2 heures peut améliorer absorption',
                'clinical_evidence': 'Grade C - Données limitées'
            },
            ('vitamin_k', 'anticoagulant'): {
                'severity': 'high',
                'mechanism': 'Antagonisme direct de l\'anticoagulant par la vitamine K',
                'symptoms': ['Réduction effet anticoagulant', 'Thrombose', 'AVC'],
                'recommendation': 'Maintenir apport K constant, NE PAS commencer/arrêter suplémentation',
                'clinical_evidence': 'Grade A - Mécanisme très bien établi'
            },
        }
    
    def identify_substance_class(self, substance_name: str) -> List[str]:
        """Identify substance classes for an interaction substance"""
        substance_lower = substance_name.lower()
        classes = []
        
        # Opioïds
        if any(x in substance_lower for x in ['morphine', 'codeine', 'tramadol', 'fentanyl', 'opium']):
            classes.append('opioide')
        
        # CNS depressants
        if any(x in substance_lower for x in ['benzodiazep', 'barbitu', 'alcool', 'éthanol']):
            classes.append('cns_depressant')
        
        # AINS
        if any(x in substance_lower for x in ['ibuprofen', 'naproxen', 'diclofenac', 'ibuprofène']):
            classes.append('nsaid')
        
        # ACE inhibitors
        if any(x in substance_lower for x in ['lisinopril', 'enalapril', 'ramipril', 'captopril']):
            classes.append('ace_inhibitor')
        
        # Anticoagulants
        if any(x in substance_lower for x in ['warfarine', 'dabigatran', 'rivaroxaban', 'apixaban', 'coumarin']):
            classes.append('anticoagulant')
        
        # Diuretics
        if any(x in substance_lower for x in ['furosemide', 'hydrochlorothiazide', 'diurétique']):
            classes.append('diuretic')
        
        # Vitamins
        if any(x in substance_lower for x in ['vitamine', 'vitamin']):
            if 'vitamine a' in substance_lower or 'vitamin a' in substance_lower:
                classes.append('vitamin_a')
            if 'vitamine d' in substance_lower or 'vitamin d' in substance_lower:
                classes.append('vitamin_d')
            if 'vitamine k' in substance_lower or 'vitamin k' in substance_lower:
                classes.append('vitamin_k')
        
        # Methotrexate
        if 'methotrexate' in substance_lower:
            classes.append('methotrexate')
        
        return classes if classes else ['unknown']
    
    def get_interaction_data(self, substance1: str, substance2: str) -> Optional[Dict]:
        """Get interaction data between two substances"""
        substance1_lower = substance1.lower()
        substance2_lower = substance2.lower()
        
        # Get classes for both substances
        classes1 = self.identify_substance_class(substance1)
        classes2 = self.identify_substance_class(substance2)
        
        # Check for known interactions
        for c1 in classes1:
            for c2 in classes2:
                # Check both directions
                if (c1, c2) in self.interaction_db:
                    return self.interaction_db[(c1, c2)]
                if (c2, c1) in self.interaction_db:
                    return self.interaction_db[(c2, c1)]
        
        # Generate generic interaction data based on severity patterns
        return self._generate_generic_interaction(substance1, substance2, classes1, classes2)
    
    def _generate_generic_interaction(self, substance1: str, substance2: str, 
                                     classes1: List[str], classes2: List[str]) -> Dict:
        """Generate generic interaction data for unknown combinations"""
        
        # Determine severity based on classes
        high_risk_classes = {'opioide', 'anticoagulant', 'methotrexate'}
        moderate_risk_classes = {'nsaid', 'ace_inhibitor', 'diuretic', 'cns_depressant'}
        
        severity = 'low'
        if any(c in high_risk_classes for c in classes1 + classes2):
            severity = 'high'
        elif any(c in moderate_risk_classes for c in classes1 + classes2):
            severity = 'moderate'
        
        return {
            'severity': severity,
            'mechanism': f'Interaction potentielle entre {substance1} et {substance2}',
            'symptoms': ['À évaluer cliniquement', 'Consultation recommandée'],
            'recommendation': 'Consulter un pharmacien ou médecin pour interaction spécifique',
            'clinical_evidence': 'Grade C - Données limitées, interaction non spécifiquement documentée'
        }
    
    def enrich_interaction(self, interaction: Dict) -> Dict:
        """Enrich an interaction record with detailed data"""
        
        substance1 = interaction.get('substance1', '')
        substance2 = interaction.get('substance2', '')
        
        # Get interaction data
        interaction_data = self.get_interaction_data(substance1, substance2)
        
        # Build enriched interaction
        enriched = interaction.copy()
        
        if interaction_data:
            enriched['enrichment'] = {
                'severity_level': interaction_data.get('severity', 'unknown'),
                'mechanism': interaction_data.get('mechanism', 'À déterminer'),
                'symptoms': interaction_data.get('symptoms', []),
                'clinical_recommendation': interaction_data.get('recommendation', 'À déterminer'),
                'evidence_grade': interaction_data.get('clinical_evidence', 'Grade C - Non documentée'),
                'risk_factors': self._get_risk_factors(substance1, substance2),
                'monitoring_parameters': self._get_monitoring_params(substance1, substance2),
                'last_updated': time.time()
            }
        else:
            enriched['enrichment'] = {
                'severity_level': 'unknown',
                'mechanism': 'À évaluer',
                'symptoms': [],
                'clinical_recommendation': 'Consultation pharmacien requise',
                'evidence_grade': 'Grade D - Non évalué',
                'last_updated': time.time()
            }
        
        return enriched
    
    def _get_risk_factors(self, substance1: str, substance2: str) -> List[str]:
        """Get risk factors for a drug interaction"""
        risk_factors = []
        
        substance1_lower = substance1.lower()
        substance2_lower = substance2.lower()
        
        # Age factors
        risk_factors.append('Patients âgés: risque augmenté')
        
        # Renal factors
        if any(x in substance1_lower + substance2_lower for x in ['méthotrexate', 'ains', 'diurétique']):
            risk_factors.append('Insuffisance rénale: surveillance requise')
        
        # Hepatic factors
        if any(x in substance1_lower + substance2_lower for x in ['paracétamol', 'opioïde', 'alcool']):
            risk_factors.append('Insuffisance hépatique: risque augmenté')
        
        # Drug metabolism
        if any(x in substance1_lower + substance2_lower for x in ['morphine', 'codeine']):
            risk_factors.append('Polymorphisme génétique CYP2D6: effet individuel variable')
        
        return risk_factors if risk_factors else ['Pas de facteurs de risque spécifiques identifiés']
    
    def _get_monitoring_params(self, substance1: str, substance2: str) -> List[str]:
        """Get monitoring parameters for a drug interaction"""
        params = []
        
        substance1_lower = substance1.lower()
        substance2_lower = substance2.lower()
        
        # Blood pressure
        if any(x in substance1_lower + substance2_lower for x in ['ains', 'ace inhibiteur', 'diurétique']):
            params.append('Tension artérielle (TA)')
        
        # Renal function
        if any(x in substance1_lower + substance2_lower for x in ['ains', 'méthotrexate', 'diurétique', 'ace inhibiteur']):
            params.append('Créatinine et clairance rénale')
            params.append('Kaliémie (K+)')
        
        # Liver function
        if any(x in substance1_lower + substance2_lower for x in ['paracétamol', 'alcool', 'opioïde']):
            params.append('Transaminases hépatiques (AST, ALT)')
        
        # Coagulation
        if 'anticoagulant' in substance1_lower or 'anticoagulant' in substance2_lower:
            params.append('INR (Temps de Quick)')
            params.append('Saignements anormaux')
        
        # Respiratory
        if any(x in substance1_lower + substance2_lower for x in ['morphine', 'opioïde', 'benzodiazépine']):
            params.append('Fonction respiratoire')
            params.append('Saturation oxygène')
        
        return params if params else ['Monitoring clinique général']
    
    def process_batch(self, batch_num: int, batch_size: int = 100):
        """Process a batch of interactions"""
        skip = batch_num * batch_size
        interactions = list(self.interactions_col.find({}).skip(skip).limit(batch_size))
        
        if not interactions:
            return 0
        
        success = 0
        for interaction in interactions:
            try:
                enriched = self.enrich_interaction(interaction)
                self.interactions_col.update_one(
                    {'_id': interaction['_id']},
                    {'$set': {'enrichment': enriched.get('enrichment', {})}}
                )
                success += 1
            except Exception as e:
                print(f"  ⚠️ Erreur enrichissement interaction: {e}")
        
        return success
    
    def enrich_all(self, limit: int = None):
        """Enrich all interactions"""
        total = self.interactions_col.count_documents({})
        limit = min(limit or total, total)
        batch_size = 100
        
        print(f"\n💊 Enrichissement des interactions entre médicaments: {limit} interactions")
        print(f"   Batch size: {batch_size}")
        
        total_processed = 0
        batch_num = 0
        
        while total_processed < limit:
            batch_processed = self.process_batch(batch_num, batch_size)
            total_processed += batch_processed
            
            progress = (total_processed / limit) * 100
            print(f"   Batch {batch_num + 1}: {batch_processed} interactions | Total: {total_processed}/{limit} ({progress:.1f}%)")
            
            if batch_processed == 0:
                break
            
            batch_num += 1
        
        print(f"\n✅ Enrichissement interactions complété: {total_processed} interactions enrichies avec données cliniques")
        return total_processed

def main():
    parser = argparse.ArgumentParser(description='Enrich drug interactions with clinical data')
    parser.add_argument('--limit', type=int, help='Number of interactions to enrich')
    args = parser.parse_args()
    
    enricher = InteractionEnricher()
    enricher.enrich_all(args.limit)

if __name__ == '__main__':
    main()
