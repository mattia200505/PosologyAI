#!/usr/bin/env python3
"""
Scraper RAPIDE et CIBLÉ pour ANSM - scrape seulement les nouveaux médicaments
sans refaire les anciens. Utilise le multithreading pour la vitesse.
"""

import requests
from bs4 import BeautifulSoup
from pymongo import MongoClient
import pandas as pd
import re
import datetime
import hashlib
import threading
import queue
import time
from bson.objectid import ObjectId
from concurrent.futures import ThreadPoolExecutor, as_completed

# Configuration
EXCEL_FILE = "medicaments_ansm.xlsx"
MAX_WORKERS = 8  # Nombre de threads parallèles
BATCH_SIZE = 100  # Nombre de médicaments à scraper en une seule exécution
TIMEOUT = 10

def get_existing_urls(db_connection):
    """Récupère les URLs déjà scrapées pour éviter les doublons"""
    collection = db_connection['medicines']
    existing_urls = set(collection.distinct('url'))
    return existing_urls

def get_urls_to_scrape(max_urls=None):
    """Charge les URLs depuis le fichier Excel"""
    try:
        df = pd.read_excel(EXCEL_FILE)
        if 'URL' in df.columns:
            urls = df['URL'].dropna().tolist()
        else:
            print(f"❌ Colonne 'URL' non trouvée dans {EXCEL_FILE}")
            return []
        
        if max_urls:
            urls = urls[:max_urls]
        
        return urls
    except FileNotFoundError:
        print(f"❌ Fichier {EXCEL_FILE} non trouvé")
        return []

def scrape_medicine(url, timeout=TIMEOUT):
    """Scrape un seul médicament (thread-safe)"""
    try:
        response = requests.get(url, timeout=timeout, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        response.raise_for_status()
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Import des fonctions d'extraction depuis scraper.py
        from scraper import (
            extract_medicine_title, extract_laboratory, 
            extract_substances_and_dosages, extract_pharmaceutical_form,
            extract_sections, extract_update_date
        )
        
        # Extraction rapide
        medicine_data = {
            'url': url,
            'title': extract_medicine_title(soup),
            'laboratory': extract_laboratory(soup),
            'update_date': extract_update_date(soup),
            'medicine_details': {
                'substances_actives': extract_substances_and_dosages(soup)[0],
                'dosages': extract_substances_and_dosages(soup)[1],
                'forme': extract_pharmaceutical_form(soup),
                'laboratoire': extract_laboratory(soup),
            },
            'sections': extract_sections(soup),
            'last_scraped': datetime.datetime.now(),
            'content_hash': hashlib.md5(
                (extract_medicine_title(soup) + str(extract_sections(soup))).encode()
            ).hexdigest()
        }
        
        return {'success': True, 'data': medicine_data, 'url': url}
        
    except Exception as e:
        return {'success': False, 'error': str(e), 'url': url}

def run_fast_scraper(db_connection=None, max_urls=None):
    """
    Scraper rapide - scrape seulement les nouveaux médicaments en parallèle
    
    Args:
        db_connection: Connexion MongoDB (optionnel)
        max_urls: Nombre max de URLs à scraper (défaut: BATCH_SIZE=100)
    """
    if max_urls is None:
        max_urls = BATCH_SIZE
    
    start_time = time.time()
    
    print("=" * 80)
    print("SCRAPER RAPIDE ANSM - Mode optimisé")
    print("=" * 80)
    
    # Connexion MongoDB
    if db_connection is None:
        client = MongoClient("mongodb://localhost:27017/")
        db = client["medicsearch"]
    else:
        db = db_connection
    
    collection = db['medicines']
    
    # Récupérer les URLs déjà scrapées
    print("\n[1/5] Chargement des URLs existantes...")
    existing_urls = get_existing_urls(db)
    print(f"✓ {len(existing_urls)} médicaments déjà en base")
    
    # Charger les URLs à scraper
    print("\n[2/5] Chargement de la liste ANSM...")
    all_urls = get_urls_to_scrape()
    print(f"✓ {len(all_urls)} URLs disponibles dans {EXCEL_FILE}")
    
    # Filtrer les URLs déjà scrapées
    print("\n[3/5] Filtrage des URLs...")
    new_urls = [url for url in all_urls if url not in existing_urls]
    new_urls = new_urls[:max_urls]
    print(f"✓ {len(new_urls)} nouveaux médicaments à scraper")
    
    if not new_urls:
        print("\n⚠️  Aucun nouveau médicament à scraper!")
        return {
            'total_processed': 0,
            'new_added': 0,
            'errors': 0,
            'duration': time.time() - start_time
        }
    
    # Scraper en parallèle
    print(f"\n[4/5] Scraping parallèle ({MAX_WORKERS} threads)...")
    stats = {
        'new_added': 0,
        'errors': 0,
        'processed': 0
    }
    
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(scrape_medicine, url): url for url in new_urls}
        
        completed = 0
        for future in as_completed(futures):
            completed += 1
            result = future.result()
            
            if result['success']:
                try:
                    collection.insert_one(result['data'])
                    stats['new_added'] += 1
                    print(f"✓ [{completed}/{len(new_urls)}] {result['data']['title'][:50]}")
                except Exception as e:
                    print(f"✗ [{completed}/{len(new_urls)}] Erreur BD: {str(e)[:50]}")
                    stats['errors'] += 1
            else:
                print(f"✗ [{completed}/{len(new_urls)}] Erreur: {result['error'][:50]}")
                stats['errors'] += 1
            
            stats['processed'] += 1
    
    # Résultats
    duration = time.time() - start_time
    print("\n[5/5] Finalisation...")
    print("\n" + "=" * 80)
    print("RÉSULTATS:")
    print(f"  ✓ Nouveaux ajoutés: {stats['new_added']}")
    print(f"  ✗ Erreurs: {stats['errors']}")
    print(f"  ⏱️  Durée: {duration:.1f}s ({len(new_urls)/duration:.1f} meds/sec)")
    print("=" * 80)
    
    return {
        'total_processed': stats['processed'],
        'new_added': stats['new_added'],
        'errors': stats['errors'],
        'duration': duration
    }

if __name__ == "__main__":
    import sys
    
    max_urls = int(sys.argv[1]) if len(sys.argv) > 1 else BATCH_SIZE
    
    result = run_fast_scraper(max_urls=max_urls)
    print(f"\n✅ Scraping terminé!")
