"""
Scraper PharmGKB - API officielle
Alternative à BIOSINO pour données pharmacogénomiques
"""
import asyncio
import aiohttp
import json
from pymongo import MongoClient
from datetime import datetime, timezone
from tqdm import tqdm
import os
from dotenv import load_dotenv

load_dotenv()

# ================= CONFIG =================

MONGO_URI = "mongodb://localhost:27017"
DB_NAME = "medicsearch"

# PharmGKB API Documentation: https://api.pharmgkb.org/v1/site/
PHARMGKB_BASE_URL = "https://api.pharmgkb.org/v1/data"
REQUEST_DELAY = 0.5  # PharmGKB permet des requêtes assez rapides

USER_AGENT = "MedicSearchBot/1.0 (Academic Research)"
HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "application/json"
}

# Types de données à scraper (endpoints simplifiés)
RESOURCE_TYPES = {
    "chemical": {
        "endpoint": "/chemical",
        "description": "Médicaments et substances chimiques"
    },
    "gene": {
        "endpoint": "/gene", 
        "description": "Gènes impliqués dans pharmacogénomique"
    },
    "variant": {
        "endpoint": "/variant",
        "description": "Variants génétiques"
    },
    "clinicalAnnotation": {
        "endpoint": "/clinicalAnnotation",
        "description": "Annotations cliniques (effets, dosage, etc.)"
    }
}

# ================= UTILS =================

def now_utc():
    return datetime.now(timezone.utc)

async def fetch_pharmgkb_page(session, endpoint, params=None):
    """Fetch une page de l'API PharmGKB"""
    url = f"{PHARMGKB_BASE_URL}{endpoint}"
    
    try:
        async with session.get(url, headers=HEADERS, params=params) as resp:
            if resp.status != 200:
                return {"status": resp.status, "data": None, "error": f"HTTP {resp.status}"}
            
            data = await resp.json()
            await asyncio.sleep(REQUEST_DELAY)
            return {"status": resp.status, "data": data, "error": None}
    except Exception as e:
        return {"status": None, "data": None, "error": str(e)}

async def fetch_pharmgkb_detail(session, resource_id, resource_type):
    """Fetch les détails d'une ressource spécifique"""
    endpoint = f"{RESOURCE_TYPES[resource_type]['endpoint']}/{resource_id}"
    return await fetch_pharmgkb_page(session, endpoint)

# ================= SCRAPING FUNCTIONS =================

async def scrape_pharmgkb_resource(session, db, resource_type, resource_config):
    """Scrape un type de ressource PharmGKB"""
    
    print(f"\n🔍 Scraping PharmGKB - {resource_config['description']}")
    
    collection_name = f"PHARMGKB_{resource_type.upper()}"
    collection = db[collection_name]
    
    endpoint = resource_config['endpoint']
    
    # Essayer d'abord sans pagination pour voir si l'endpoint fonctionne
    result = await fetch_pharmgkb_page(session, endpoint)
    
    if result["error"]:
        print(f"⚠️  Endpoint {endpoint} inaccessible: {result['error']}")
        print(f"💡 PharmGKB nécessite peut-être une clé API ou l'endpoint a changé")
        return 0
    
    # Si succès, les données sont dans result["data"]
    if not result["data"]:
        print(f"⚠️  Pas de données pour {endpoint}")
        return 0
    
    # Sauvegarder les données
    data_items = result["data"]
    
    # PharmGKB peut retourner directement une liste ou {"data": [...]}
    if isinstance(data_items, dict) and "data" in data_items:
        data_items = data_items["data"]
    
    if not isinstance(data_items, list):
        data_items = [data_items]
    
    total_fetched = 0
    
    for item in tqdm(data_items, desc=f"PharmGKB {resource_type}"):
        item_id = item.get("id") or item.get("pharmgkbId") or item.get("symbol")
        
        if not item_id:
            continue
        
        collection.update_one(
            {"pharmgkbId": item_id},
            {
                "$set": {
                    **item,
                    "resource_type": resource_type,
                    "source": "PharmGKB",
                    "scraped_at": now_utc()
                }
            },
            upsert=True
        )
        total_fetched += 1
    
    print(f"✅ {resource_type}: {total_fetched} entrées récupérées")
    return total_fetched

async def scrape_clinical_annotations_detailed(session, db):
    """
    Scrape les annotations cliniques avec détails complets
    C'est l'équivalent des patterns BIOSINO
    """
    
    print("\n🧬 Scraping annotations cliniques détaillées PharmGKB")
    
    collection = db["PHARMGKB_CLINICAL_DETAILED"]
    
    # Récupérer d'abord la liste des annotations cliniques
    endpoint = "/clinicalAnnotation"
    page = 0
    page_size = 50  # Plus petit car on va fetcher les détails
    total = 0
    
    with tqdm(desc="Clinical Annotations") as pbar:
        while True:
            params = {"page": page, "size": page_size, "view": "base"}
            result = await fetch_pharmgkb_page(session, endpoint, params)
            
            if result["error"] or not result["data"]:
                break
            
            items = result["data"].get("data", [])
            if not items:
                break
            
            # Pour chaque annotation, fetcher les détails complets
            for item in items:
                ann_id = item.get("id")
                if not ann_id:
                    continue
                
                # Fetch détails complets
                detail_result = await fetch_pharmgkb_detail(session, ann_id, "clinicalAnnotation")
                
                if detail_result["data"]:
                    detail_data = detail_result["data"]["data"]
                    
                    collection.update_one(
                        {"id": ann_id},
                        {
                            "$set": {
                                **detail_data,
                                "source": "PharmGKB",
                                "resource_type": "clinicalAnnotation",
                                "scraped_at": now_utc()
                            }
                        },
                        upsert=True
                    )
                    total += 1
                    pbar.update(1)
            
            if len(items) < page_size:
                break
            
            page += 1
    
    print(f"✅ Clinical Annotations détaillées: {total} entrées")
    return total

async def scrape_drug_gene_associations(session, db):
    """
    Scrape les associations médicament-gène
    Équivalent des relations Drug-Gene de BIOSINO
    """
    
    print("\n💊 Scraping associations Drug-Gene PharmGKB")
    
    collection = db["PHARMGKB_DRUG_GENE"]
    
    # PharmGKB a un endpoint spécial pour les paires drug-gene
    endpoint = "/clinicalAnnotation"
    page = 0
    page_size = 100
    total = 0
    
    with tqdm(desc="Drug-Gene pairs") as pbar:
        while True:
            params = {
                "page": page,
                "size": page_size,
                "view": "max"
            }
            
            result = await fetch_pharmgkb_page(session, endpoint, params)
            
            if result["error"] or not result["data"]:
                break
            
            items = result["data"].get("data", [])
            if not items:
                break
            
            for item in items:
                # Extraire les associations drug-gene
                drugs = item.get("relatedChemicals", [])
                genes = item.get("relatedGenes", [])
                
                # Créer une entrée pour chaque paire drug-gene
                for drug in drugs:
                    for gene in genes:
                        association = {
                            "annotation_id": item.get("id"),
                            "drug_id": drug.get("id"),
                            "drug_name": drug.get("name"),
                            "gene_id": gene.get("id"),
                            "gene_symbol": gene.get("symbol"),
                            "phenotypes": item.get("phenotypes", []),
                            "level_of_evidence": item.get("levelOfEvidence"),
                            "guideline": item.get("guideline"),
                            "source": "PharmGKB",
                            "scraped_at": now_utc()
                        }
                        
                        collection.update_one(
                            {
                                "drug_id": drug.get("id"),
                                "gene_id": gene.get("id"),
                                "annotation_id": item.get("id")
                            },
                            {"$set": association},
                            upsert=True
                        )
                        total += 1
            
            pbar.update(len(items))
            
            if len(items) < page_size:
                break
            
            page += 1
    
    print(f"✅ Drug-Gene associations: {total} paires")
    return total

# ================= MAIN PIPELINE =================

async def run():
    """Pipeline principal de scraping PharmGKB"""
    
    client = MongoClient(MONGO_URI)
    db = client[DB_NAME]
    
    print("\n" + "="*60)
    print("🧬 SCRAPING PHARMGKB - PHARMACOGÉNOMIQUE")
    print("="*60)
    print("📊 Source: PharmGKB (API officielle)")
    print("🎯 Alternative à BIOSINO pour données pharmacogénomiques")
    print("="*60 + "\n")
    
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
        
        # PHASE 1: Ressources de base
        print("📥 PHASE 1: Ressources de base")
        print("-" * 60)
        
        totals = {}
        
        for resource_type, config in RESOURCE_TYPES.items():
            try:
                count = await scrape_pharmgkb_resource(session, db, resource_type, config)
                totals[resource_type] = count
            except Exception as e:
                print(f"❌ Erreur {resource_type}: {e}")
                totals[resource_type] = 0
        
        print("\n✅ Phase 1 terminée\n")
        
        # PHASE 2: Annotations cliniques détaillées
        print("📥 PHASE 2: Annotations cliniques détaillées")
        print("-" * 60)
        
        try:
            clinical_count = await scrape_clinical_annotations_detailed(session, db)
            totals["clinical_detailed"] = clinical_count
        except Exception as e:
            print(f"❌ Erreur annotations cliniques: {e}")
            totals["clinical_detailed"] = 0
        
        print("\n✅ Phase 2 terminée\n")
        
        # PHASE 3: Associations Drug-Gene
        print("📥 PHASE 3: Associations Drug-Gene")
        print("-" * 60)
        
        try:
            assoc_count = await scrape_drug_gene_associations(session, db)
            totals["drug_gene_associations"] = assoc_count
        except Exception as e:
            print(f"❌ Erreur associations: {e}")
            totals["drug_gene_associations"] = 0
        
        print("\n✅ Phase 3 terminée\n")
    
    # Résumé final
    print("\n" + "="*60)
    print("🎯 SCRAPING PHARMGKB TERMINÉ")
    print("="*60)
    print("\n📊 Résumé des données collectées:")
    for resource, count in totals.items():
        print(f"   ✓ {resource}: {count:,} entrées")
    
    total_all = sum(totals.values())
    print(f"\n🎉 TOTAL: {total_all:,} entrées collectées")
    print("\n💡 Collections MongoDB créées:")
    print("   - PHARMGKB_DRUG")
    print("   - PHARMGKB_GENE")
    print("   - PHARMGKB_VARIANT")
    print("   - PHARMGKB_CLINICALANNOTATION")
    print("   - PHARMGKB_GUIDELINEANNOTATION")
    print("   - PHARMGKB_DRUGLABEL")
    print("   - PHARMGKB_CLINICAL_DETAILED")
    print("   - PHARMGKB_DRUG_GENE")
    
    client.close()

# ================= EXECUTION =================

if __name__ == "__main__":
    print("🚀 Démarrage du scraper PharmGKB...")
    print("⏱️  Durée estimée: 10-30 minutes\n")
    
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        print("\n\n⚠️  Scraping interrompu par l'utilisateur")
    except Exception as e:
        print(f"\n\n❌ Erreur fatale: {e}")
