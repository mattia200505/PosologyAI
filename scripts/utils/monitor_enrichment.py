#!/usr/bin/env python3
"""
Monitoring en temps réel de l'enrichissement Mistral
"""

import os
import time
from datetime import datetime
from pymongo import MongoClient
from qdrant_client import QdrantClient
from dotenv import load_dotenv

# Load environment
load_dotenv(os.path.join(os.path.dirname(__file__), '../../.env'))

mongo_host = os.getenv('MONGO_HOST', '127.0.0.1')
mongo_port = int(os.getenv('MONGO_PORT', 27018))
qdrant_host = os.getenv('QDRANT_HOST', '127.0.0.1')
qdrant_port = int(os.getenv('QDRANT_PORT', 6333))

mongo_client = MongoClient(mongo_host, mongo_port)
db = mongo_client['medicsearch']
qdrant_client = QdrantClient(host=qdrant_host, port=qdrant_port)

def get_progress():
    """Récupère la progression actuelle"""
    total_medicines = db.medicines.count_documents({})
    enriched = db.medicines.count_documents({"enrichment": {"$exists": True}})
    
    try:
        qdrant_points = qdrant_client.get_collection('medicaments').points_count
    except Exception as e:
        qdrant_points = 0
    
    return total_medicines, enriched, qdrant_points

def format_time(seconds):
    """Formate le temps en format lisible"""
    if seconds < 60:
        return f"{int(seconds)}s"
    elif seconds < 3600:
        return f"{int(seconds/60)}m {int(seconds%60)}s"
    else:
        return f"{int(seconds/3600)}h {int((seconds%3600)/60)}m"

def main():
    print("\n" + "="*70)
    print("📊 MONITORING ENRICHISSEMENT MISTRAL - TEMPS RÉEL")
    print("="*70)
    
    start_time = time.time()
    last_enriched = 0
    last_check_time = start_time
    
    try:
        while True:
            total, enriched, qdrant_points = get_progress()
            
            current_time = time.time()
            elapsed = current_time - start_time
            time_since_last = current_time - last_check_time
            
            # Calculer la vitesse
            if time_since_last > 0:
                speed = (enriched - last_enriched) / time_since_last
            else:
                speed = 0
            
            last_enriched = enriched
            last_check_time = current_time
            
            # Calculer l'ETA
            if speed > 0:
                remaining = total - enriched
                eta_seconds = remaining / speed
                eta_time = format_time(eta_seconds)
            else:
                eta_time = "Calcul..."
            
            # Afficher la barre de progression
            pct = (enriched / total * 100) if total > 0 else 0
            bar_length = 50
            filled = int(bar_length * enriched / total) if total > 0 else 0
            bar = "█" * filled + "░" * (bar_length - filled)
            
            # Clear screen and display
            os.system('cls' if os.name == 'nt' else 'clear')
            
            print("\n" + "="*70)
            print("📊 MONITORING ENRICHISSEMENT MISTRAL - TEMPS RÉEL")
            print("="*70)
            print()
            print(f"⏱️  Temps écoulé: {format_time(elapsed)}")
            print(f"⚡ Vitesse: {speed:.2f} médicaments/seconde")
            print(f"🎯 ETA: {eta_time}")
            print()
            print("📈 PROGRESSION:")
            print(f"   [{bar}]")
            print(f"   {enriched:,} / {total:,} médicaments enrichis ({pct:.1f}%)")
            print()
            print("💾 BASES DE DONNÉES:")
            print(f"   MongoDB:  {enriched:,} documents avec enrichment")
            print(f"   Qdrant:   {qdrant_points:,} points indexés")
            print()
            print("📋 STATISTIQUES:")
            print(f"   Restants:     {total - enriched:,} médicaments")
            print(f"   Taux réussite: {(enriched/total*100):.1f}%")
            print()
            print("Actualisé: " + datetime.now().strftime("%H:%M:%S"))
            print("Appuyez sur Ctrl+C pour arrêter...")
            print("="*70)
            
            time.sleep(2)  # Refresh toutes les 2 secondes
    
    except KeyboardInterrupt:
        print("\n\n✋ Monitoring arrêté")
        total, enriched, qdrant_points = get_progress()
        print(f"\n📊 État final:")
        print(f"   Enrichis: {enriched:,} / {total:,} ({(enriched/total*100):.1f}%)")
        print(f"   Qdrant: {qdrant_points:,} points")
        print(f"   Temps total: {format_time(time.time() - start_time)}")

if __name__ == "__main__":
    main()
