"""
Scraper BIOSINO via API directe (contourne le problème JavaScript)
"""
import asyncio
import aiohttp
import json
from pymongo import MongoClient
from datetime import datetime, timezone
from tqdm import tqdm

MONGO_URI = "mongodb://localhost:27017"
DB_NAME = "medicsearch"

async def scrape_biosino_api():
    """Scrape BIOSINO en appelant directement l'API DataTables"""
    
    client = MongoClient(MONGO_URI)
    db = client[DB_NAME]
    biosino_col = db["BIOSINO"]
    
    # Types de patterns disponibles
    types = ["SideEffect", "Sensitivity", "Molecular", "Indication"]
    
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
        for pattern_type in types:
            print(f"\n🔍 Scraping BIOSINO - Type: {pattern_type}")
            
            # Paramètres pour l'API DataTables
            url = "https://www.biosino.org/cpmkg/getTableData"
            
            start = 0
            length = 100  # Nombre d'éléments par page
            total_records = None
            
            with tqdm(desc=f"BIOSINO {pattern_type}") as pbar:
                while True:
                    payload = {
                        "type": pattern_type,
                        "keyword": "",  # Vide pour tout récupérer
                        "start": start,
                        "length": length,
                        "draw": 1
                    }
                    
                    try:
                        async with session.post(url, json=payload) as resp:
                            if resp.status != 200:
                                print(f"⚠️  Erreur {resp.status} pour {pattern_type}")
                                break
                            
                            data = await resp.json()
                            
                            # Initialiser le total
                            if total_records is None:
                                total_records = data.get("recordsTotal", 0)
                                pbar.total = total_records
                            
                            records = data.get("data", [])
                            
                            if not records:
                                break
                            
                            # Sauvegarder dans MongoDB
                            for record in records:
                                biosino_col.update_one(
                                    {"id": record.get("id"), "type": pattern_type},
                                    {
                                        "$set": {
                                            **record,
                                            "type": pattern_type,
                                            "source": "BIOSINO",
                                            "scraped_at": datetime.now(timezone.utc)
                                        }
                                    },
                                    upsert=True
                                )
                            
                            pbar.update(len(records))
                            start += length
                            
                            # Si on a tout récupéré
                            if start >= total_records:
                                break
                            
                            await asyncio.sleep(0.5)  # Rate limiting
                            
                    except Exception as e:
                        print(f"❌ Erreur: {e}")
                        break
            
            print(f"✅ {pattern_type} terminé")
    
    print("\n🎯 BIOSINO scraping terminé")

if __name__ == "__main__":
    asyncio.run(scrape_biosino_api())
