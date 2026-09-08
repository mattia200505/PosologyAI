"""
Import PharmGKB via données TSV publiques
Alternative plus fiable que l'API
"""
import pandas as pd
import requests
from pymongo import MongoClient
from datetime import datetime, timezone
from tqdm import tqdm
import io

# ================= CONFIG =================

MONGO_URI = "mongodb://localhost:27017"
DB_NAME = "medicsearch"

# URLs des fichiers TSV publics PharmGKB
# Documentation: https://www.pharmgkb.org/downloads
PHARMGKB_DATA_URLS = {
    "drugs": "https://s3.pgkb.org/data/drugs.zip",
    "genes": "https://s3.pgkb.org/data/genes.zip",
    "variants": "https://s3.pgkb.org/data/variants.zip",
    "clinical_annotations": "https://s3.pgkb.org/data/clinicalAnnotations.zip",
    "drug_labels": "https://s3.pgkb.org/data/drugLabels.zip",
    "relationships": "https://s3.pgkb.org/data/relationships.zip"
}

def now_utc():
    return datetime.now(timezone.utc)

def download_and_parse_tsv(url, resource_name):
    """Télécharge et parse un fichier TSV PharmGKB"""
    
    print(f"\n📥 Téléchargement: {resource_name}")
    print(f"   URL: {url}")
    
    try:
        response = requests.get(url, stream=True, timeout=60)
        response.raise_for_status()
        
        # Lire le contenu
        content = response.content
        
        # Si c'est un ZIP, extraire
        if url.endswith('.zip'):
            import zipfile
            with zipfile.ZipFile(io.BytesIO(content)) as z:
                # Trouver le fichier TSV dans le ZIP
                tsv_files = [f for f in z.namelist() if f.endswith('.tsv')]
                if not tsv_files:
                    print(f"⚠️  Pas de fichier TSV dans {url}")
                    return None
                
                # Lire le premier fichier TSV
                with z.open(tsv_files[0]) as f:
                    df = pd.read_csv(f, sep='\t', low_memory=False)
        else:
            # Fichier TSV direct
            df = pd.read_csv(io.BytesIO(content), sep='\t', low_memory=False)
        
        print(f"✅ {len(df)} lignes chargées")
        return df
        
    except Exception as e:
        print(f"❌ Erreur: {e}")
        return None

def import_to_mongodb(df, collection, resource_type):
    """Importe un DataFrame dans MongoDB"""
    
    if df is None or len(df) == 0:
        return 0
    
    print(f"\n💾 Import dans MongoDB: {collection.name}")
    
    # Convertir DataFrame en documents
    records = df.to_dict('records')
    
    count = 0
    for record in tqdm(records, desc=f"Import {resource_type}"):
        # Nettoyer les valeurs NaN
        clean_record = {k: v for k, v in record.items() if pd.notna(v)}
        
        # Ajouter métadonnées
        clean_record["source"] = "PharmGKB"
        clean_record["resource_type"] = resource_type
        clean_record["imported_at"] = now_utc()
        
        # Identifier le champ ID principal
        id_field = clean_record.get("PharmGKB Accession Id") or clean_record.get("Variant") or clean_record.get("Name")
        
        if id_field:
            collection.update_one(
                {"id_field": id_field},
                {"$set": clean_record},
                upsert=True
            )
            count += 1
    
    print(f"✅ {count} documents importés")
    return count

def main():
    """Pipeline principal d'import PharmGKB"""
    
    print("\n" + "="*60)
    print("🧬 IMPORT PHARMGKB - DONNÉES TSV PUBLIQUES")
    print("="*60)
    print("📊 Source: PharmGKB Downloads (TSV/ZIP)")
    print("🎯 Alternative fiable à l'API")
    print("="*60 + "\n")
    
    client = MongoClient(MONGO_URI)
    db = client[DB_NAME]
    
    totals = {}
    
    for resource_name, url in PHARMGKB_DATA_URLS.items():
        print(f"\n{'='*60}")
        print(f"📦 Traitement: {resource_name.upper()}")
        print(f"{'='*60}")
        
        # Télécharger et parser
        df = download_and_parse_tsv(url, resource_name)
        
        if df is not None:
            # Importer dans MongoDB
            collection_name = f"PHARMGKB_{resource_name.upper()}"
            collection = db[collection_name]
            
            count = import_to_mongodb(df, collection, resource_name)
            totals[resource_name] = count
        else:
            totals[resource_name] = 0
    
    # Résumé final
    print("\n" + "="*60)
    print("🎯 IMPORT PHARMGKB TERMINÉ")
    print("="*60)
    print("\n📊 Résumé des données importées:")
    
    for resource, count in totals.items():
        print(f"   ✓ {resource}: {count:,} entrées")
    
    total_all = sum(totals.values())
    print(f"\n🎉 TOTAL: {total_all:,} entrées importées")
    
    print("\n💡 Collections MongoDB créées:")
    for resource in PHARMGKB_DATA_URLS.keys():
        print(f"   - PHARMGKB_{resource.upper()}")
    
    client.close()

if __name__ == "__main__":
    print("🚀 Démarrage de l'import PharmGKB...")
    print("⏱️  Durée estimée: 5-10 minutes\n")
    print("📦 Fichiers à télécharger:")
    for name, url in PHARMGKB_DATA_URLS.items():
        print(f"   - {name}: {url}")
    print()
    
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️  Import interrompu par l'utilisateur")
    except Exception as e:
        print(f"\n\n❌ Erreur fatale: {e}")
        import traceback
        traceback.print_exc()
