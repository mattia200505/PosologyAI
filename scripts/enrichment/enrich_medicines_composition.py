#!/usr/bin/env python3
"""
Script pour enrichir les médicaments avec des données de composition et génome
Sources: HAS, DrugBank, Thériaque
"""

import requests
import json
import time
from pymongo import MongoClient
from typing import Optional, Dict, List
import re

class MedicineEnricher:
    def __init__(self):
        # Connexion MongoDB
        try:
            self.client = MongoClient('mongodb://localhost:27018/', serverSelectionTimeoutMS=5000)
            self.client.server_info()
            print('✅ Connecté via Docker MongoDB (port 27018)')
        except Exception as e:
            print(f'❌ Erreur connexion MongoDB: {e}')
            exit(1)
        
        self.db = self.client['medicsearch']
        self.collection = self.db['medicines']
        self.enrichment_stats = {
            'processed': 0,
            'drugbank_found': 0,
            'therique_found': 0,
            'composition_added': 0,
            'errors': 0
        }
    
    def search_drugbank(self, medicine_name: str, active_substances: List[str]) -> Dict:
        """Cherche les informations DrugBank pour un médicament"""
        try:
            # API DrugBank gratuite (https://www.drugbank.ca/releases/latest)
            # Pour ce script, on crée une structure de données enrichie
            drugbank_data = {
                'source': 'DrugBank',
                'name': medicine_name,
                'active_substances': active_substances,
                'pharmacokinetics': {
                    'absorption': 'À rechercher sur DrugBank',
                    'distribution': 'À rechercher sur DrugBank',
                    'metabolism': 'À rechercher sur DrugBank',
                    'elimination': 'À rechercher sur DrugBank'
                },
                'interactions': [],
                'side_effects': [],
                'mechanism_of_action': 'À déterminer'
            }
            return drugbank_data
        except Exception as e:
            print(f'Erreur DrugBank pour {medicine_name}: {e}')
            return None
    
    def search_therique(self, medicine_name: str) -> Dict:
        """Cherche les informations Thériaque pour un médicament"""
        try:
            # Thériaque est une base française publique
            # Structure de données enrichie
            therique_data = {
                'source': 'Thériaque',
                'name': medicine_name,
                'french_info': True,
                'composition': {
                    'molecules': [],
                    'excipients': []
                },
                'indications': 'À rechercher sur Thériaque',
                'posology': 'À rechercher sur Thériaque',
                'contraindications': [],
                'precautions': []
            }
            return therique_data
        except Exception as e:
            print(f'Erreur Thériaque pour {medicine_name}: {e}')
            return None
    
    def search_has_database(self, medicine_name: str) -> Dict:
        """Cherche les données HAS (Haute Autorité de Santé)"""
        try:
            # HAS fournit des données sur l'efficacité et la sécurité
            has_data = {
                'source': 'HAS',
                'name': medicine_name,
                'asmr': None,  # Amélioration du Service Médical Rendu
                'smr': None,   # Service Médical Rendu
                'recommendations': [],
                'clinical_data': {
                    'efficacy': 'À valider auprès de HAS',
                    'safety_profile': 'À valider auprès de HAS',
                    'clinical_trials': []
                }
            }
            return has_data
        except Exception as e:
            print(f'Erreur HAS pour {medicine_name}: {e}')
            return None
    
    def extract_molecule_info(self, medicine: Dict) -> Dict:
        """Extrait les informations de molécule du médicament"""
        molecules_info = {
            'active_substances': [],
            'dosages': [],
            'form': None
        }
        
        # Récupérer les substances actives
        if 'medicine_details' in medicine:
            details = medicine['medicine_details']
            
            if 'substances_actives' in details:
                molecules_info['active_substances'] = details['substances_actives']
            
            if 'dosages' in details:
                molecules_info['dosages'] = details['dosages']
            
            if 'forme' in details:
                molecules_info['form'] = details['forme']
        
        return molecules_info
    
    def enrich_medicine(self, medicine: Dict) -> Dict:
        """Enrichit un médicament avec les données externes"""
        medicine_name = medicine.get('title', '')
        
        try:
            # Extraire les molécules
            molecule_info = self.extract_molecule_info(medicine)
            
            # Rechercher dans les bases de données
            drugbank_info = self.search_drugbank(medicine_name, molecule_info['active_substances'])
            therique_info = self.search_therique(medicine_name)
            has_info = self.search_has_database(medicine_name)
            
            # Créer la structure d'enrichissement
            enrichment = {
                'composition': {
                    'molecules': molecule_info['active_substances'],
                    'dosages': molecule_info['dosages'],
                    'pharmaceutical_form': molecule_info['form'],
                    'last_updated': time.time()
                },
                'external_databases': {
                    'drugbank': drugbank_info,
                    'therique': therique_info,
                    'has': has_info
                },
                'genome_related': {
                    'pharmacogenomics': 'À rechercher',
                    'genetic_variations': [],
                    'drug_interactions': []
                }
            }
            
            # Ajouter l'enrichissement au médicament
            medicine['enrichment'] = enrichment
            
            return medicine
            
        except Exception as e:
            print(f'Erreur enrichissement {medicine_name}: {e}')
            self.enrichment_stats['errors'] += 1
            return medicine
    
    def run(self, limit: Optional[int] = None, update_all: bool = False):
        """Exécute l'enrichissement des médicaments par batch"""
        print(f"\n🔍 Début de l'enrichissement des médicaments...")
        
        # Déterminer la requête
        if update_all:
            query = {}
            print("📋 Mise à jour de TOUS les médicaments")
        else:
            query = {'enrichment': {'$exists': False}}
            print("📋 Ajout d'enrichissement aux médicaments manquants")
        
        # Compter total
        total = self.collection.count_documents(query)
        print(f"📊 {total} médicaments à enrichir\n")
        
        batch_size = 100
        processed = 0
        
        # Traiter par batch pour éviter les timeouts
        for batch_num in range(0, total, batch_size):
            medicines = list(self.collection.find(query).skip(batch_num).limit(batch_size))
            
            for idx, medicine in enumerate(medicines, 1):
                medicine_name = medicine.get('title', 'Sans nom')
                
                # Enrichir
                enriched = self.enrich_medicine(medicine)
                
                # Mettre à jour dans MongoDB
                try:
                    self.collection.update_one(
                        {'_id': medicine['_id']},
                        {'$set': {'enrichment': enriched.get('enrichment')}}
                    )
                    self.enrichment_stats['processed'] += 1
                    self.enrichment_stats['composition_added'] += 1
                except Exception as e:
                    print(f"❌ Erreur mise à jour {medicine_name}: {e}")
                    self.enrichment_stats['errors'] += 1
            
            processed += len(medicines)
            # Afficher la progression
            print(f"⏳ Batch {batch_num//batch_size + 1}: {processed}/{total} ({processed/total*100:.1f}%)")
        
        self.print_stats()
    
    def print_stats(self):
        """Affiche les statistiques"""
        print("\n" + "="*50)
        print("📊 STATISTIQUES D'ENRICHISSEMENT")
        print("="*50)
        print(f"✅ Médicaments traités: {self.enrichment_stats['processed']}")
        print(f"🔗 Composition ajoutée: {self.enrichment_stats['composition_added']}")
        print(f"❌ Erreurs: {self.enrichment_stats['errors']}")
        print("="*50 + "\n")

if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='Enrichir les médicaments avec données externes')
    parser.add_argument('--limit', type=int, help='Limiter le nombre de médicaments')
    parser.add_argument('--all', action='store_true', help='Mettre à jour tous les médicaments')
    
    args = parser.parse_args()
    
    enricher = MedicineEnricher()
    enricher.run(limit=args.limit, update_all=args.all)
