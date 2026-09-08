#!/usr/bin/env python3
"""
Script pour scrapper le code ATC et les familles thérapeutiques des médicaments
depuis la base de données publique de l'ANSM
"""

import requests
from bs4 import BeautifulSoup
import time
import re
from pymongo import MongoClient
from typing import Dict, Optional, List
import logging
from urllib.parse import urljoin, quote
import sys

# Configuration du logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class ATCFamilyScraper:
    """Scraper pour extraire le code ATC et la famille thérapeutique"""
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        self.base_url = "https://base-donnees-publique.medicaments.gouv.fr"
        
        # MongoDB
        self.client = MongoClient('mongodb://localhost:27017/')
        self.db = self.client['medicsearch']
        self.collection = self.db['medicines']
        
        # Statistiques
        self.stats = {
            'total': 0,
            'success': 0,
            'failed': 0,
            'already_has_atc': 0,
            'skipped': 0
        }
    
    def extract_atc_from_url(self, url: str) -> Optional[Dict[str, any]]:
        """
        Extrait le code ATC et la famille thérapeutique depuis l'URL du médicament
        
        Args:
            url: URL de la page du médicament sur base-donnees-publique.medicaments.gouv.fr
            
        Returns:
            Dict contenant {code_atc, famille_therapeutique, libelle_atc} ou None
        """
        try:
            response = self.session.get(url, timeout=10)
            response.raise_for_status()
            soup = BeautifulSoup(response.content, 'html.parser')
            
            atc_data = {
                'code_atc': None,
                'famille_therapeutique': None,
                'libelle_atc': None
            }
            
            # Chercher dans les sections de la page
            # Le code ATC est généralement dans une section spécifique
            
            # Méthode 1: Chercher "Classe ATC" ou "Code ATC"
            for text_element in soup.find_all(['p', 'div', 'span', 'td', 'th']):
                text = text_element.get_text(strip=True)
                
                # Pattern pour code ATC (ex: N02BA01, J01CA04)
                if re.search(r'\b[A-Z]\d{2}[A-Z]{2}\d{2}\b', text):
                    match = re.search(r'\b([A-Z]\d{2}[A-Z]{2}\d{2})\b', text)
                    if match:
                        atc_data['code_atc'] = match.group(1)
                        
                        # Essayer d'extraire le libellé qui suit souvent le code
                        full_text = text_element.get_text()
                        after_code = full_text.split(match.group(1), 1)
                        if len(after_code) > 1:
                            libelle = after_code[1].strip(' :-').split('\n')[0].strip()
                            if libelle and len(libelle) > 3:
                                atc_data['libelle_atc'] = libelle[:200]  # Limiter la taille
            
            # Méthode 2: Chercher dans les tableaux spécifiques
            for table in soup.find_all('table'):
                for row in table.find_all('tr'):
                    cells = row.find_all(['th', 'td'])
                    if len(cells) >= 2:
                        header = cells[0].get_text(strip=True).lower()
                        value = cells[1].get_text(strip=True)
                        
                        if 'atc' in header or 'classe' in header:
                            # Extraire code ATC
                            match = re.search(r'\b([A-Z]\d{2}[A-Z]{2}\d{2})\b', value)
                            if match:
                                atc_data['code_atc'] = match.group(1)
                                # Le reste du texte est potentiellement le libellé
                                libelle = value.replace(match.group(1), '').strip(' :-')
                                if libelle and len(libelle) > 3:
                                    atc_data['libelle_atc'] = libelle[:200]
                        
                        if 'famille' in header or 'thérapeutique' in header or 'pharmacothérapeutique' in header:
                            if value and len(value) > 3:
                                atc_data['famille_therapeutique'] = value[:200]
            
            # Méthode 3: Chercher dans les divs avec des classes spécifiques
            atc_divs = soup.find_all(['div', 'p'], class_=re.compile(r'atc|classe|therapeut', re.I))
            for div in atc_divs:
                text = div.get_text(strip=True)
                match = re.search(r'\b([A-Z]\d{2}[A-Z]{2}\d{2})\b', text)
                if match:
                    atc_data['code_atc'] = match.group(1)
                    libelle = text.replace(match.group(1), '').strip(' :-')
                    if libelle and len(libelle) > 3:
                        atc_data['libelle_atc'] = libelle[:200]
            
            # Chercher spécifiquement "Classe pharmacothérapeutique"
            for element in soup.find_all(text=re.compile(r'Classe pharmacothérapeutique', re.I)):
                parent = element.find_parent(['p', 'div', 'td'])
                if parent:
                    # Chercher le contenu dans les siblings ou enfants
                    next_elem = parent.find_next_sibling()
                    if next_elem:
                        famille = next_elem.get_text(strip=True)
                        if famille and len(famille) > 3:
                            atc_data['famille_therapeutique'] = famille[:200]
            
            # Si on a trouvé au moins le code ATC, c'est un succès
            if atc_data['code_atc']:
                return atc_data
            
            return None
            
        except Exception as e:
            logger.debug(f"Erreur lors de l'extraction ATC depuis {url}: {e}")
            return None
    
    def get_atc_info_from_code(self, atc_code: str) -> Optional[Dict[str, str]]:
        """
        Récupère les informations détaillées depuis le code ATC
        en utilisant la base de l'OMS (WHO Collaborating Centre)
        
        Args:
            atc_code: Code ATC (ex: N02BA01)
            
        Returns:
            Dict avec informations détaillées ou None
        """
        try:
            # Base de données ATC publique
            url = f"https://www.whocc.no/atc_ddd_index/?code={atc_code}"
            
            response = self.session.get(url, timeout=10)
            response.raise_for_status()
            soup = BeautifulSoup(response.content, 'html.parser')
            
            info = {}
            
            # Extraire le nom et la description
            for b_tag in soup.find_all('b'):
                text = b_tag.get_text(strip=True)
                if atc_code in text:
                    full_text = b_tag.parent.get_text(strip=True) if b_tag.parent else text
                    # Enlever le code pour garder juste le nom
                    name = full_text.replace(atc_code, '').strip(' :-')
                    if name:
                        info['libelle_atc'] = name
                        break
            
            # Structure du code ATC:
            # 1er niveau (1 lettre): Groupe anatomique principal
            # 2e niveau (2 chiffres): Groupe thérapeutique principal
            # 3e niveau (1 lettre): Sous-groupe thérapeutique/pharmacologique
            # 4e niveau (1 lettre): Sous-groupe chimique/thérapeutique/pharmacologique
            # 5e niveau (2 chiffres): Substance chimique
            
            if atc_code and len(atc_code) >= 1:
                # Décoder le premier niveau (groupe anatomique)
                anatomical_groups = {
                    'A': 'Appareil digestif et métabolisme',
                    'B': 'Sang et organes hématopoïétiques',
                    'C': 'Système cardiovasculaire',
                    'D': 'Médicaments dermatologiques',
                    'G': 'Système génito-urinaire et hormones sexuelles',
                    'H': 'Préparations systémiques hormonales',
                    'J': 'Anti-infectieux généraux à usage systémique',
                    'L': 'Antinéoplasiques et immunomodulateurs',
                    'M': 'Système musculo-squelettique',
                    'N': 'Système nerveux',
                    'P': 'Produits antiparasitaires',
                    'R': 'Système respiratoire',
                    'S': 'Organes sensoriels',
                    'V': 'Divers'
                }
                info['groupe_anatomique'] = anatomical_groups.get(atc_code[0], atc_code[0])
            
            return info if info else None
            
        except Exception as e:
            logger.debug(f"Erreur lors de la récupération des infos ATC depuis WHO: {e}")
            return None
    
    def process_medicine(self, medicine: Dict) -> bool:
        """
        Traite un médicament pour extraire son code ATC et sa famille
        
        Args:
            medicine: Document MongoDB du médicament
            
        Returns:
            True si succès, False sinon
        """
        medicine_id = medicine['_id']
        title = medicine.get('title', 'Sans titre')
        url = medicine.get('url')
        
        # Vérifier si le médicament a déjà un code ATC
        if medicine.get('code_atc') or medicine.get('atc_code'):
            logger.info(f"  ⏭️  {title} - Déjà enrichi avec ATC")
            self.stats['already_has_atc'] += 1
            return True
        
        if not url:
            logger.warning(f"  ⚠️  {title} - Pas d'URL disponible")
            self.stats['skipped'] += 1
            return False
        
        logger.info(f"  🔍 {title}")
        
        # Extraire le code ATC depuis l'URL du médicament
        atc_data = self.extract_atc_from_url(url)
        
        if not atc_data:
            logger.warning(f"    ❌ Aucun code ATC trouvé")
            self.stats['failed'] += 1
            return False
        
        # Si on a un code ATC, essayer d'obtenir plus d'infos depuis WHO
        if atc_data.get('code_atc'):
            logger.info(f"    ✅ Code ATC trouvé: {atc_data['code_atc']}")
            
            # Enrichir avec les infos WHO
            who_info = self.get_atc_info_from_code(atc_data['code_atc'])
            if who_info:
                # Ne pas écraser les données existantes
                if not atc_data.get('libelle_atc') and who_info.get('libelle_atc'):
                    atc_data['libelle_atc'] = who_info['libelle_atc']
                if who_info.get('groupe_anatomique'):
                    atc_data['groupe_anatomique'] = who_info['groupe_anatomique']
                logger.info(f"    📚 Infos WHO: {who_info.get('groupe_anatomique', 'N/A')}")
        
        # Mettre à jour MongoDB
        update_data = {}
        if atc_data.get('code_atc'):
            update_data['code_atc'] = atc_data['code_atc']
        if atc_data.get('famille_therapeutique'):
            update_data['famille_therapeutique'] = atc_data['famille_therapeutique']
            logger.info(f"    🏥 Famille: {atc_data['famille_therapeutique'][:50]}...")
        if atc_data.get('libelle_atc'):
            update_data['libelle_atc'] = atc_data['libelle_atc']
        if atc_data.get('groupe_anatomique'):
            update_data['groupe_anatomique'] = atc_data['groupe_anatomique']
        
        if update_data:
            self.collection.update_one(
                {'_id': medicine_id},
                {'$set': update_data}
            )
            self.stats['success'] += 1
            return True
        
        self.stats['failed'] += 1
        return False
    
    def run(self, limit: Optional[int] = None, skip: int = 0):
        """
        Lance le scraping pour tous les médicaments
        
        Args:
            limit: Nombre max de médicaments à traiter (None = tous)
            skip: Nombre de médicaments à sauter
        """
        logger.info("="*70)
        logger.info("🚀 Démarrage du scraping ATC et familles thérapeutiques")
        logger.info("="*70)
        
        # Compter le total
        total_count = self.collection.count_documents({})
        logger.info(f"📊 Total de médicaments dans la base: {total_count}")
        
        # Requête
        query = {}
        cursor = self.collection.find(query).skip(skip)
        
        if limit:
            cursor = cursor.limit(limit)
            logger.info(f"🎯 Traitement limité à {limit} médicaments (skip: {skip})")
        
        # Traiter chaque médicament
        for i, medicine in enumerate(cursor, 1):
            self.stats['total'] += 1
            
            if i % 10 == 0:
                logger.info(f"\n📈 Progression: {i}/{limit if limit else total_count}")
                logger.info(f"   ✅ Succès: {self.stats['success']}")
                logger.info(f"   ⏭️  Déjà enrichi: {self.stats['already_has_atc']}")
                logger.info(f"   ❌ Échecs: {self.stats['failed']}")
                logger.info(f"   ⚠️  Ignorés: {self.stats['skipped']}\n")
            
            self.process_medicine(medicine)
            
            # Pause pour ne pas surcharger les serveurs
            time.sleep(0.5)
        
        # Résumé final
        logger.info("\n" + "="*70)
        logger.info("📊 RÉSUMÉ FINAL")
        logger.info("="*70)
        logger.info(f"Total traité: {self.stats['total']}")
        logger.info(f"✅ Succès: {self.stats['success']}")
        logger.info(f"⏭️  Déjà enrichi: {self.stats['already_has_atc']}")
        logger.info(f"❌ Échecs: {self.stats['failed']}")
        logger.info(f"⚠️  Ignorés: {self.stats['skipped']}")
        
        success_rate = (self.stats['success'] / self.stats['total'] * 100) if self.stats['total'] > 0 else 0
        logger.info(f"📈 Taux de succès: {success_rate:.1f}%")
        logger.info("="*70)
    
    def close(self):
        """Ferme les connexions"""
        self.session.close()
        self.client.close()


def main():
    """Point d'entrée principal"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Scraper de codes ATC et familles thérapeutiques')
    parser.add_argument('--limit', type=int, default=None, help='Nombre max de médicaments à traiter')
    parser.add_argument('--skip', type=int, default=0, help='Nombre de médicaments à sauter')
    parser.add_argument('--test', action='store_true', help='Mode test (10 médicaments)')
    
    args = parser.parse_args()
    
    # Mode test
    if args.test:
        args.limit = 10
        args.skip = 0
    
    scraper = ATCFamilyScraper()
    
    try:
        scraper.run(limit=args.limit, skip=args.skip)
    except KeyboardInterrupt:
        logger.info("\n⚠️  Interruption par l'utilisateur")
    except Exception as e:
        logger.error(f"\n❌ Erreur fatale: {e}", exc_info=True)
    finally:
        scraper.close()
        logger.info("✅ Fermeture propre")


if __name__ == "__main__":
    main()
