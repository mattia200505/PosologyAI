import xml.etree.ElementTree as ET
from pymongo import MongoClient
from datetime import datetime, timezone
from tqdm import tqdm
import os

# ================= CONFIG =================

MONGO_URI = "mongodb://localhost:27017"
DB_NAME = "medicsearch"

# Chemin du fichier XML DrugBank (cherche dans plusieurs emplacements)
POSSIBLE_PATHS = [
    r"c:\Users\Mattia\OneDrive - UPEC\Documents\BUT 3\MEDICSEARCH (3)\MEDICSEARCH\drugbank_all_full_database.xml\full database.xml",
    r"c:\Users\Mattia\OneDrive - UPEC\Documents\BUT 3\MEDICSEARCH (3)\MEDICSEARCH\drugbank_all_full_database.xml",
    r"c:\Users\Mattia\OneDrive - UPEC\Documents\BUT 3\MEDICSEARCH (3)\MEDICSEARCH\frontend_backend\scripts\full database.xml",
    r"c:\Users\Mattia\Downloads\full database.xml",
]

XML_FILE_PATH = None
for path in POSSIBLE_PATHS:
    if os.path.exists(path):
        try:
            # Test si le fichier est accessible en lecture
            with open(path, 'rb') as f:
                f.read(1)
            XML_FILE_PATH = path
            break
        except:
            continue

if not XML_FILE_PATH:
    XML_FILE_PATH = POSSIBLE_PATHS[0]  # Fallback

# Namespace DrugBank
NS = {'db': 'http://www.drugbank.ca'}

# ================= UTILS =================

def now_utc():
    return datetime.now(timezone.utc)

def get_text(element, path, default=None):
    """Extrait le texte d'un élément XML avec namespace"""
    if element is None:
        return default
    found = element.find(path, NS)
    return found.text if found is not None and found.text else default

def get_all_texts(element, path):
    """Extrait tous les textes d'éléments multiples"""
    if element is None:
        return []
    return [el.text for el in element.findall(path, NS) if el.text]

def parse_drug(drug_elem):
    """Parse un élément <drug> complet"""
    
    # Identifiants
    drugbank_id = get_text(drug_elem, 'db:drugbank-id[@primary="true"]')
    if not drugbank_id:
        drugbank_id = get_text(drug_elem, 'db:drugbank-id')
    
    secondary_ids = get_all_texts(drug_elem, 'db:drugbank-id')
    
    # Informations de base
    name = get_text(drug_elem, 'db:name')
    description = get_text(drug_elem, 'db:description')
    cas_number = get_text(drug_elem, 'db:cas-number')
    unii = get_text(drug_elem, 'db:unii')
    
    # Type et groupes
    drug_type = drug_elem.get('type', 'small molecule')
    groups = get_all_texts(drug_elem, 'db:groups/db:group')
    
    # Informations cliniques
    indication = get_text(drug_elem, 'db:indication')
    pharmacodynamics = get_text(drug_elem, 'db:pharmacodynamics')
    mechanism_of_action = get_text(drug_elem, 'db:mechanism-of-action')
    toxicity = get_text(drug_elem, 'db:toxicity')
    metabolism = get_text(drug_elem, 'db:metabolism')
    absorption = get_text(drug_elem, 'db:absorption')
    half_life = get_text(drug_elem, 'db:half-life')
    protein_binding = get_text(drug_elem, 'db:protein-binding')
    route_of_elimination = get_text(drug_elem, 'db:route-of-elimination')
    volume_of_distribution = get_text(drug_elem, 'db:volume-of-distribution')
    clearance = get_text(drug_elem, 'db:clearance')
    
    # Classification
    classification = {}
    class_elem = drug_elem.find('db:classification', NS)
    if class_elem is not None:
        classification = {
            'description': get_text(class_elem, 'db:description'),
            'direct_parent': get_text(class_elem, 'db:direct-parent'),
            'kingdom': get_text(class_elem, 'db:kingdom'),
            'superclass': get_text(class_elem, 'db:superclass'),
            'class': get_text(class_elem, 'db:class'),
            'subclass': get_text(class_elem, 'db:subclass'),
        }
    
    # Synonymes
    synonyms = []
    syn_elem = drug_elem.find('db:synonyms', NS)
    if syn_elem is not None:
        synonyms = [s.text for s in syn_elem.findall('db:synonym', NS) if s.text]
    
    # Produits (formulations commerciales)
    products = []
    prod_elem = drug_elem.find('db:products', NS)
    if prod_elem is not None:
        for product in prod_elem.findall('db:product', NS):
            products.append({
                'name': get_text(product, 'db:name'),
                'labeller': get_text(product, 'db:labeller'),
                'ndc_id': get_text(product, 'db:ndc-id'),
                'ndc_product_code': get_text(product, 'db:ndc-product-code'),
                'dpd_id': get_text(product, 'db:dpd-id'),
                'ema_product_code': get_text(product, 'db:ema-product-code'),
                'ema_ma_number': get_text(product, 'db:ema-ma-number'),
                'started_marketing_on': get_text(product, 'db:started-marketing-on'),
                'ended_marketing_on': get_text(product, 'db:ended-marketing-on'),
                'dosage_form': get_text(product, 'db:dosage-form'),
                'strength': get_text(product, 'db:strength'),
                'route': get_text(product, 'db:route'),
                'fda_application_number': get_text(product, 'db:fda-application-number'),
                'generic': get_text(product, 'db:generic') == 'true',
                'over_the_counter': get_text(product, 'db:over-the-counter') == 'true',
                'approved': get_text(product, 'db:approved') == 'true',
                'country': get_text(product, 'db:country'),
                'source': get_text(product, 'db:source'),
            })
    
    # Interactions médicamenteuses
    interactions = []
    inter_elem = drug_elem.find('db:drug-interactions', NS)
    if inter_elem is not None:
        for interaction in inter_elem.findall('db:drug-interaction', NS):
            interactions.append({
                'drugbank_id': get_text(interaction, 'db:drugbank-id'),
                'name': get_text(interaction, 'db:name'),
                'description': get_text(interaction, 'db:description'),
            })
    
    # Catégories ATC
    atc_codes = []
    atc_elem = drug_elem.find('db:atc-codes', NS)
    if atc_elem is not None:
        for atc in atc_elem.findall('db:atc-code', NS):
            atc_codes.append({
                'code': atc.get('code'),
                'level': get_text(atc, 'db:level'),
            })
    
    # Cibles (targets)
    targets = []
    targets_elem = drug_elem.find('db:targets', NS)
    if targets_elem is not None:
        for target in targets_elem.findall('db:target', NS):
            targets.append({
                'id': target.get('id'),
                'name': get_text(target, 'db:name'),
                'organism': get_text(target, 'db:organism'),
                'actions': get_all_texts(target, 'db:actions/db:action'),
                'known_action': get_text(target, 'db:known-action'),
            })
    
    # Enzymes
    enzymes = []
    enzymes_elem = drug_elem.find('db:enzymes', NS)
    if enzymes_elem is not None:
        for enzyme in enzymes_elem.findall('db:enzyme', NS):
            enzymes.append({
                'id': enzyme.get('id'),
                'name': get_text(enzyme, 'db:name'),
                'organism': get_text(enzyme, 'db:organism'),
                'actions': get_all_texts(enzyme, 'db:actions/db:action'),
            })
    
    # Transporteurs
    transporters = []
    trans_elem = drug_elem.find('db:transporters', NS)
    if trans_elem is not None:
        for transporter in trans_elem.findall('db:transporter', NS):
            transporters.append({
                'id': transporter.get('id'),
                'name': get_text(transporter, 'db:name'),
                'organism': get_text(transporter, 'db:organism'),
                'actions': get_all_texts(transporter, 'db:actions/db:action'),
            })
    
    # Propriétés calculées
    calculated_properties = {}
    calc_elem = drug_elem.find('db:calculated-properties', NS)
    if calc_elem is not None:
        for prop in calc_elem.findall('db:property', NS):
            kind = get_text(prop, 'db:kind')
            value = get_text(prop, 'db:value')
            if kind and value:
                calculated_properties[kind] = value
    
    # Propriétés expérimentales
    experimental_properties = {}
    exp_elem = drug_elem.find('db:experimental-properties', NS)
    if exp_elem is not None:
        for prop in exp_elem.findall('db:property', NS):
            kind = get_text(prop, 'db:kind')
            value = get_text(prop, 'db:value')
            if kind and value:
                experimental_properties[kind] = value
    
    # Liens externes
    external_identifiers = {}
    ext_elem = drug_elem.find('db:external-identifiers', NS)
    if ext_elem is not None:
        for ext_id in ext_elem.findall('db:external-identifier', NS):
            resource = get_text(ext_id, 'db:resource')
            identifier = get_text(ext_id, 'db:identifier')
            if resource and identifier:
                external_identifiers[resource] = identifier
    
    # Pathways
    pathways = []
    path_elem = drug_elem.find('db:pathways', NS)
    if path_elem is not None:
        for pathway in path_elem.findall('db:pathway', NS):
            pathways.append({
                'smpdb_id': get_text(pathway, 'db:smpdb-id'),
                'name': get_text(pathway, 'db:name'),
                'category': get_text(pathway, 'db:category'),
            })
    
    return {
        'source': 'DRUGBANKS',
        'drugbank_id': drugbank_id,
        'secondary_ids': secondary_ids,
        'name': name,
        'description': description,
        'cas_number': cas_number,
        'unii': unii,
        'type': drug_type,
        'groups': groups,
        'indication': indication,
        'pharmacodynamics': pharmacodynamics,
        'mechanism_of_action': mechanism_of_action,
        'toxicity': toxicity,
        'metabolism': metabolism,
        'absorption': absorption,
        'half_life': half_life,
        'protein_binding': protein_binding,
        'route_of_elimination': route_of_elimination,
        'volume_of_distribution': volume_of_distribution,
        'clearance': clearance,
        'classification': classification,
        'synonyms': synonyms,
        'products': products,
        'interactions': interactions,
        'atc_codes': atc_codes,
        'targets': targets,
        'enzymes': enzymes,
        'transporters': transporters,
        'calculated_properties': calculated_properties,
        'experimental_properties': experimental_properties,
        'external_identifiers': external_identifiers,
        'pathways': pathways,
        'imported_at': now_utc(),
    }

# ================= MAIN =================

def main():
    print("="*60)
    print("🚀 IMPORT DRUGBANK XML - FULL DATABASE")
    print("="*60)
    
    # Vérification du fichier
    if not os.path.exists(XML_FILE_PATH):
        print(f"❌ Fichier introuvable: {XML_FILE_PATH}")
        print("\n💡 Placez le fichier drugbank_all_full_database.xml dans:")
        print(f"   {os.path.dirname(XML_FILE_PATH)}")
        return
    
    file_size_mb = os.path.getsize(XML_FILE_PATH) / (1024 * 1024)
    print(f"📁 Fichier trouvé: {os.path.basename(XML_FILE_PATH)}")
    print(f"📊 Taille: {file_size_mb:.2f} MB")
    print()
    
    # Connexion MongoDB
    client = MongoClient(MONGO_URI)
    db = client[DB_NAME]
    collection = db["DRUGBANKS"]
    
    # Nettoyage collection
    count = collection.count_documents({})
    if count > 0:
        print(f"🧹 Suppression de {count} documents existants...")
        collection.delete_many({})
    
    print("⚙️  Parsing du fichier XML (cela peut prendre quelques minutes)...\n")
    
    # Parse XML avec ElementTree (streaming pour économiser la mémoire)
    try:
        # Ouverture avec permissions de lecture explicites
        with open(XML_FILE_PATH, 'rb') as xml_file:
            context = ET.iterparse(xml_file, events=('start', 'end'))
            context = iter(context)
            event, root = next(context)
            
            drugs_imported = 0
            drugs_batch = []
            batch_size = 100
            
            for event, elem in tqdm(context, desc="Import DrugBank", unit=" drugs"):
                if event == 'end' and elem.tag == '{http://www.drugbank.ca}drug':
                    try:
                        drug_data = parse_drug(elem)
                        if drug_data['drugbank_id']:
                            drugs_batch.append(drug_data)
                            
                            if len(drugs_batch) >= batch_size:
                                collection.insert_many(drugs_batch)
                                drugs_imported += len(drugs_batch)
                                drugs_batch = []
                        
                    except Exception as e:
                        print(f"\n⚠️  Erreur parsing drug: {e}")
                    
                    # Libération mémoire
                    elem.clear()
                    root.clear()
            
            # Insert dernier batch
            if drugs_batch:
                collection.insert_many(drugs_batch)
                drugs_imported += len(drugs_batch)
        
        print("\n" + "="*60)
        print("✅ IMPORT TERMINÉ AVEC SUCCÈS")
        print("="*60)
        print(f"📦 {drugs_imported} médicaments importés")
        print(f"💾 Collection: {DB_NAME}.DRUGBANKS")
        
        # Statistiques
        print("\n📊 Statistiques:")
        print(f"   - Approved: {collection.count_documents({'groups': 'approved'})}")
        print(f"   - Experimental: {collection.count_documents({'groups': 'experimental'})}")
        print(f"   - Investigational: {collection.count_documents({'groups': 'investigational'})}")
        print(f"   - Withdrawn: {collection.count_documents({'groups': 'withdrawn'})}")
        print(f"   - Avec interactions: {collection.count_documents({'interactions': {'$ne': []}})}")
        print(f"   - Avec ATC codes: {collection.count_documents({'atc_codes': {'$ne': []}})}")
        
    except ET.ParseError as e:
        print(f"\n❌ Erreur parsing XML: {e}")
    except Exception as e:
        print(f"\n❌ Erreur: {e}")

if __name__ == "__main__":
    main()
