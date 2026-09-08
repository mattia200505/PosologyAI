import requests
from bs4 import BeautifulSoup
from pymongo import MongoClient
import pandas as pd
import re
import datetime
import hashlib
import os
import time
from bson.objectid import ObjectId

# Import des dépendances PDF
try:
    import PyPDF2
    PDF_SUPPORT = True
except ImportError:
    PDF_SUPPORT = False

try:
    import pdfplumber
    PDFPLUMBER_SUPPORT = True
except ImportError:
    PDFPLUMBER_SUPPORT = False

# Variables globales pour le suivi de l'état
is_running = False
stop_requested = False
progress = None

# Fonction principale qui peut être appelée depuis l'interface d'administration
def run_scraper(db_connection=None, source_file=None, max_urls=None):
    """
    Fonction principale de scraping qui peut être appelée depuis l'interface d'administration
    
    Args:
        db_connection: Une connexion MongoDB existante (facultatif)
        source_file: Chemin vers le fichier Excel contenant les URLs (facultatif)
        max_urls: Nombre maximum d'URLs à traiter (facultatif)
    
    Returns:
        dict: Statistiques sur les résultats du scraping
    """
    global is_running, stop_requested, progress
    
    # Prévenir l'appel récursif
    if is_running:
        print("WARNING: Une instance de scraping est déjà en cours d'exécution!")
        return {
            'total_processed': 0,
            'new_added': 0,
            'updated': 0,
            'unchanged': 0,
            'errors': 1,
            'duration': 0,
            'error': 'Scraping already running'
        }
    
    try:
        # Réinitialiser les variables de contrôle
        is_running = True
        stop_requested = False
        start_time = time.time()
        
        print("Initialisation du processus de scraping complet...")
        
        # Connexion à MongoDB - FIX: Ne pas utiliser de test booléen sur db_connection
        # Pour pymongo, db_connection ne doit pas être testé directement avec if db_connection:
        db = None
        if db_connection is not None:
            print("Utilisation de la connexion MongoDB fournie")
            db = db_connection
        else:
            print("Création d'une nouvelle connexion MongoDB")
            try:
                # En Docker, utiliser le nom du service
                client = MongoClient("mongodb://mongo:27017/", serverSelectionTimeoutMS=5000)
                client.admin.command('ping')
                print("✅ Connexion MongoDB (Docker) établie")
            except:
                # En local, utiliser localhost
                try:
                    client = MongoClient("mongodb://localhost:27017/", serverSelectionTimeoutMS=5000)
                    client.admin.command('ping')
                    print("✅ Connexion MongoDB (Local) établie")
                except:
                    print("❌ Impossible de se connecter à MongoDB")
                    raise
            
            db_name = "medicsearch"
            db = client[db_name]
        
        collection = db['medicines']
        metadata_collection = db['metadata']
        
        # Vérifier s'il existe une tâche de scraping en cours
        scraping_task = metadata_collection.find_one({"_id": "scraping_current_task"})
        if scraping_task and scraping_task.get('in_progress', False):
            # Reprendre une tâche existante
            print("Reprise d'une tâche de scraping précédente...")
            urls = scraping_task.get('remaining_urls', [])
            processed_urls = scraping_task.get('processed_urls', [])
            stats = scraping_task.get('current_stats', {
                'total_processed': len(processed_urls),
                'new_added': 0,
                'updated': 0,
                'unchanged': 0,
                'errors': 0,
                'duration': 0
            })
            
            # Si aucune URL restante, recommencer depuis le début
            if not urls:
                print("Aucune URL restante dans la tâche précédente. Recommencement depuis le début.")
                # Réinitialiser la tâche et commencer une nouvelle
                scraping_task = None
        else:
            scraping_task = None
            processed_urls = []
            stats = {
                'total_processed': 0,
                'new_added': 0,
                'updated': 0,
                'unchanged': 0,
                'errors': 0,
                'duration': 0
            }
    
        # Si aucune tâche en cours ou si on redémarre, charger les URLs depuis le fichier
        # Toujours commencer une nouvelle tâche (scraping complet)
        scraping_task = None
        processed_urls = []
        stats = {
            'total_processed': 0,
            'new_added': 0,
            'updated': 0,
            'unchanged': 0,
            'errors': 0,
            'duration': 0
        }

        # Charger les URLs depuis le fichier Excel
        if not source_file:
            # Chercher dans le répertoire du script
            script_dir = os.path.dirname(os.path.abspath(__file__))
            possible_files = [
                os.path.join(script_dir, "liens_R.xlsx"),
                os.path.join(script_dir, "..", "liens_R.xlsx"),
                os.path.join(script_dir, "..", "data", "liens_R.xlsx"),
            ]
            
            for file_path in possible_files:
                if os.path.exists(file_path):
                    source_file = file_path
                    print(f"Fichier source trouvé: {file_path}")
                    break
        
        if not source_file or not os.path.exists(source_file):
            # Si nous avons des médicaments existants, mettons-les à jour au lieu d'échouer
            existing_count = collection.count_documents({})
            if existing_count > 0:
                print(f"Aucun fichier source trouvé, mais {existing_count} médicaments existent déjà. Mise à jour des médicaments existants...")
                urls = []
                for med in collection.find({}, {"url": 1}).limit(max_urls if max_urls else 1000):
                    if "url" in med:
                        urls.append(med["url"])
                if not urls:
                    raise FileNotFoundError("Aucune URL trouvée dans la base de données existante")
            else:
                raise FileNotFoundError("Fichier Excel contenant les URLs non trouvé et aucun médicament existant")
        else:
            print(f"Chargement des URLs depuis le fichier: {source_file}")
            df = pd.read_excel(source_file)
            if 'liens' not in df.columns:
                raise ValueError("Le fichier Excel ne contient pas de colonne 'liens'.")
                
            urls = df["liens"].tolist()
            print(f"{len(urls)} URLs chargées depuis le fichier Excel")
        
        if max_urls and max_urls > 0:
            print(f"Limitation à {max_urls} URLs maximum")
            urls = urls[:max_urls]
    
        # Initialiser ou mettre à jour la tâche de scraping
        total_urls = len(urls) + len(processed_urls)
        print(f"Total URLs à traiter: {total_urls}")
        
        if total_urls == 0:
            print("Aucune URL à traiter. Arrêt du scraping.")
            is_running = False
            return {
                'total_processed': 0,
                'new_added': 0,
                'updated': 0,
                'unchanged': 0,
                'errors': 0,
                'duration': 0,
                'message': 'No URLs to process'
            }
        
        metadata_collection.update_one(
            {"_id": "scraping_current_task"},
            {
                "$set": {
                    "in_progress": True,
                    "start_time": datetime.datetime.now(),
                    "total_urls": total_urls,
                    "remaining_urls": urls,
                    "processed_urls": processed_urls,
                    "current_stats": stats
                }
            },
            upsert=True
        )
        
        # Mettre à jour la progression globale pour le suivi de l'interface
        progress = {
            "percent": int(len(processed_urls) / total_urls * 100) if total_urls > 0 else 0,
            "current": len(processed_urls),
            "total": total_urls,
            "new_added": stats.get('new_added', 0),
            "updated": stats.get('updated', 0),
            "unchanged": stats.get('unchanged', 0),
            "errors": stats.get('errors', 0)
        }
        
        # Traitement des URLs
        for url in urls[:]:
            # Vérifier si l'arrêt a été demandé
            if stop_requested:
                print("Arrêt demandé par l'utilisateur. Sauvegarde de l'état...")
                # Sauvegarder l'état actuel
                metadata_collection.update_one(
                    {"_id": "scraping_current_task"},
                    {
                        "$set": {
                            "last_updated": datetime.datetime.now(),
                            "remaining_urls": urls,
                            "processed_urls": processed_urls,
                            "current_stats": stats,
                            "stopped_by_user": True  # Marquer comme arrêté manuellement
                        }
                    }
                )
                is_running = False
                return stats
                
            stats['total_processed'] += 1
            processed_urls.append(url)
            urls.remove(url)
            
            # Mettre à jour le pourcentage
            if total_urls > 0:  # Prévenir la division par zéro
                progress["percent"] = int(len(processed_urls) / total_urls * 100)
            progress["current"] = len(processed_urls)
            progress["new_added"] = stats.get('new_added', 0)
            progress["updated"] = stats.get('updated', 0)
            progress["unchanged"] = stats.get('unchanged', 0)
            progress["errors"] = stats.get('errors', 0)
            
            print(f"Progression: {progress['percent']}% - URL {progress['current']}/{total_urls}")
            
            try:
                # timeout: 10s pour la connexion, 30s pour la lecture
                response = requests.get(url, timeout=(10, 30))
                response.raise_for_status()
                
                # Déterminer le type de contenu
                content_type = response.headers.get('content-type', '').lower()
                is_pdf = 'pdf' in content_type or url.lower().endswith('.pdf')
                
                document = None
                
                if is_pdf:
                    # Traitement PDF
                    print(f"📄 Traitement PDF: {url}")
                    pdf_data = extract_text_from_pdf(response.content)
                    
                    if pdf_data.get('success'):
                        pdf_text = pdf_data.get('text', '')
                        
                        # Extraire les informations du texte PDF
                        main_title = pdf_data.get('title', 'Document PDF')
                        
                        # Essayer d'extraire les substances du texte PDF
                        substance_match = re.search(r'(?:Substance|substance active)[:\s]*([^\n]+)', pdf_text)
                        substances = [substance_match.group(1).strip()] if substance_match else []
                        
                        dosage_match = re.search(r'(?:Dosage|dosage)[:\s]*([^\n]+)', pdf_text)
                        dosages = [dosage_match.group(1).strip()] if dosage_match else []
                        
                        laboratory_match = re.search(r'(?:Laboratoire|Fabricant)[:\s]*([^\n]+)', pdf_text)
                        laboratory = laboratory_match.group(1).strip() if laboratory_match else ''
                        
                        form_match = re.search(r'(?:Forme|Form)[:\s]*([^\n]+)', pdf_text)
                        forme = form_match.group(1).strip() if form_match else 'Forme non trouvée'
                        
                        # Créer le document
                        document = {
                            "url": url,
                            "title": main_title,
                            "medicine_details": {
                                "substances_actives": substances,
                                "laboratoire": laboratory,
                                "dosages": dosages,
                                "forme": forme
                            },
                            "update_date": datetime.datetime.now().strftime("%d/%m/%Y"),
                            "last_scraped": datetime.datetime.now(),
                            "document_type": "PDF",
                            "pdf_metadata": {
                                "page_count": pdf_data.get('page_count', 0),
                                "source": pdf_data.get('source', 'unknown')
                            }
                        }
                        
                        # Extraire les sections du texte PDF
                        try:
                            document["sections"] = extract_sections_from_pdf_text(pdf_text)
                        except Exception as e:
                            print(f"Erreur lors de l'extraction des sections PDF: {str(e)}")
                            document["sections"] = [{
                                'title': 'Contenu PDF',
                                'content': [{'text': pdf_text[:5000], 'formatting': {}}],
                                'subsections': []
                            }]
                    else:
                        print(f"Erreur extraction PDF: {pdf_data.get('error')}")
                        stats['errors'] += 1
                        continue
                
                else:
                    # Traitement HTML (existant)
                    soup = None
                    try:
                        soup = BeautifulSoup(response.content, 'html.parser')
                    except:
                        for encoding in ['utf-8', 'latin-1', 'windows-1252', 'iso-8859-1']:
                            try:
                                soup = BeautifulSoup(response.content.decode(encoding), 'html.parser')
                                break
                            except:
                                continue
                    
                    if not soup:
                        raise ValueError("Impossible de décoder le contenu de la page")
                        
                    # Extractions
                    main_title = extract_medicine_title(soup)
                    substance_dosage_data = extract_substances_and_dosages(soup)
                    update_date = extract_update_date(soup)
                    
                    # Créer le document
                    document = {
                        "url": url,
                        "title": main_title,
                        "medicine_details": {
                            "substances_actives": substance_dosage_data["substances_actives"],
                            "laboratoire": extract_laboratory(soup),
                            "dosages": substance_dosage_data["dosages"],
                            "forme": extract_pharmaceutical_form(soup)
                        },
                        "update_date": update_date,
                        "last_scraped": datetime.datetime.now(),
                        "document_type": "HTML"
                    }
                    
                    # Extraire les sections
                    try:
                        document["sections"] = extract_sections(soup)
                    except Exception as e:
                        print(f"Erreur lors de l'extraction des sections pour {url}: {str(e)}")
                        document["sections"] = []
                
                if document:
                    # Générer un hash du contenu pour vérifier si le médicament a changé
                    content_hash = generate_content_hash(document)
                    document["content_hash"] = content_hash
                    
                    # Vérifier si le médicament existe déjà
                    existing = collection.find_one({"url": url})
                    
                    if existing:
                        if "content_hash" in existing and existing["content_hash"] == content_hash:
                            # Le contenu n'a pas changé, mettre à jour uniquement la date de scraping
                            collection.update_one(
                                {"_id": existing["_id"]},
                                {"$set": {"last_scraped": datetime.datetime.now()}}
                            )
                            stats['unchanged'] += 1
                            progress['unchanged'] += 1
                            print(f"Médicament inchangé: {main_title}")
                        else:
                            # Le contenu a changé, mettre à jour
                            collection.update_one(
                                {"_id": existing["_id"]},
                                {"$set": document}
                            )
                            stats['updated'] += 1
                            progress['updated'] += 1
                            print(f"Médicament mis à jour: {main_title}")
                    else:
                        # Nouveau médicament
                        collection.insert_one(document)
                        stats['new_added'] += 1
                        progress['new_added'] += 1
                        print(f"Nouveau médicament ajouté: {main_title}")
            
            except Exception as e:
                print(f"Erreur lors du traitement de {url}: {str(e)}")
                stats['errors'] = stats.get('errors', 0) + 1
                if 'errors' in progress:
                    progress['errors'] = stats['errors']
            
            # Mettre à jour régulièrement l'état de la tâche dans la base de données
            if len(processed_urls) % 10 == 0 or len(urls) == 0:
                print(f"Sauvegarde de l'état du scraping... ({len(processed_urls)}/{total_urls})")
                metadata_collection.update_one(
                    {"_id": "scraping_current_task"},
                    {
                        "$set": {
                            "last_updated": datetime.datetime.now(),
                            "remaining_urls": urls,
                            "processed_urls": processed_urls,
                            "current_stats": stats
                        }
                    }
                )
            
            print("-" * 50)
        
        # Calculer la durée totale
        stats['duration'] = round(time.time() - start_time)
        
        # Mettre à jour les métadonnées et marquer la tâche comme terminée
        current_time = datetime.datetime.now()
        print(f"Mise à jour des métadonnées de scraping...")
        
        metadata_collection.update_one(
            {"_id": "scraping_current_task"},
            {
                "$set": {
                    "in_progress": False,
                    "completed_at": current_time,
                    "duration": stats['duration']
                }
            }
        )
        
        # Mettre à jour les métadonnées générales
        metadata_collection.update_one(
            {"_id": "scraping_metadata"},
            {
                "$set": {
                    "last_update": current_time,
                    "total_medicines": collection.count_documents({}),
                    "last_scraping_results": stats
                }
            },
            upsert=True
        )
        
        print(f"Scraping terminé!")
        print(f"Total traité: {stats['total_processed']} | Nouveaux: {stats.get('new_added', 0)} | Mis à jour: {stats.get('updated', 0)} | Inchangés: {stats.get('unchanged', 0)} | Erreurs: {stats.get('errors', 0)}")
        print(f"Durée totale: {stats['duration']} secondes")
        
        return stats
        
    except Exception as e:
        print(f"ERREUR CRITIQUE dans run_scraper: {str(e)}")
        import traceback
        traceback.print_exc()
        return {
            'total_processed': 0,
            'new_added': 0,
            'updated': 0,
            'unchanged': 0,
            'errors': 1,
            'duration': 0,
            'error_message': str(e)
        }
    finally:
        # Toujours réinitialiser les variables globales, même en cas d'erreur
        is_running = False
        progress = None

def generate_content_hash(document):
    """Génère un hash du contenu essentiel pour détecter les changements"""
    # Sélectionner les champs importants pour la comparaison
    content_string = (
        document.get('title', '') + 
        str(document.get('update_date', '')) + 
        str(document.get('medicine_details', {})) + 
        str([
            {k: v for k, v in section.items() if k != 'subsections'} 
            for section in document.get('sections', [])
        ])
    )
    return hashlib.md5(content_string.encode('utf-8')).hexdigest()

def extract_text_from_pdf(pdf_path_or_bytes):
    """
    Extrait le texte d'un PDF (fichier local ou bytes)
    Retourne: dict avec 'text', 'pages', 'title'
    """
    try:
        text_content = []
        pdf_title = "PDF Document"
        page_count = 0
        
        # Méthode 1: Utiliser pdfplumber (meilleur pour les tables et format)
        if PDFPLUMBER_SUPPORT:
            try:
                import io
                if isinstance(pdf_path_or_bytes, bytes):
                    pdf_file = io.BytesIO(pdf_path_or_bytes)
                else:
                    pdf_file = pdf_path_or_bytes
                
                with pdfplumber.open(pdf_file) as pdf:
                    page_count = len(pdf.pages)
                    
                    # Extraire le titre du PDF (première page)
                    if pdf.pages:
                        first_page_text = pdf.pages[0].extract_text()
                        lines = first_page_text.split('\n')
                        pdf_title = lines[0].strip() if lines else "PDF Document"
                    
                    # Extraire le texte de toutes les pages
                    for page_num, page in enumerate(pdf.pages, 1):
                        page_text = page.extract_text()
                        if page_text:
                            text_content.append({
                                'page': page_num,
                                'text': page_text,
                                'tables': len(page.find_table() or [])
                            })
                
                return {
                    'text': '\n\n'.join([p['text'] for p in text_content]),
                    'pages': text_content,
                    'page_count': page_count,
                    'title': pdf_title,
                    'source': 'pdfplumber',
                    'success': True
                }
            except Exception as e:
                print(f"Erreur pdfplumber: {e}, tentative PyPDF2...")
        
        # Méthode 2: PyPDF2 (fallback)
        if PDF_SUPPORT:
            try:
                import io
                if isinstance(pdf_path_or_bytes, bytes):
                    pdf_file = io.BytesIO(pdf_path_or_bytes)
                else:
                    with open(pdf_path_or_bytes, 'rb') as f:
                        pdf_file = io.BytesIO(f.read())
                
                pdf_reader = PyPDF2.PdfReader(pdf_file)
                page_count = len(pdf_reader.pages)
                
                # Extraire métadonnées pour le titre
                if pdf_reader.metadata:
                    pdf_title = pdf_reader.metadata.get('/Title', 'PDF Document')
                
                # Extraire le texte de toutes les pages
                for page_num, page in enumerate(pdf_reader.pages, 1):
                    page_text = page.extract_text()
                    if page_text:
                        text_content.append({
                            'page': page_num,
                            'text': page_text
                        })
                
                return {
                    'text': '\n\n'.join([p['text'] for p in text_content]),
                    'pages': text_content,
                    'page_count': page_count,
                    'title': pdf_title,
                    'source': 'PyPDF2',
                    'success': True
                }
            except Exception as e:
                print(f"Erreur PyPDF2: {e}")
                return {
                    'text': '',
                    'pages': [],
                    'page_count': 0,
                    'title': 'Error',
                    'error': str(e),
                    'success': False
                }
        
        return {
            'text': '',
            'pages': [],
            'page_count': 0,
            'title': 'No PDF support',
            'error': 'PyPDF2 ou pdfplumber requis',
            'success': False
        }
    
    except Exception as e:
        print(f"Erreur générale extraction PDF: {e}")
        return {
            'text': '',
            'pages': [],
            'page_count': 0,
            'title': 'Error',
            'error': str(e),
            'success': False
        }

def extract_sections_from_pdf_text(text):
    """
    Extrait des sections structurées à partir du texte PDF
    Détecte les titres et sous-titres basés sur les patterns
    """
    sections = []
    current_section = None
    lines = text.split('\n')
    
    # Patterns pour détecter les titres
    title_patterns = [
        r'^\d+\.\s+[A-Z][A-Z\s]+$',  # 1. TITRE
        r'^\d+\.\d+\s+[A-Z][A-Z\s]+$',  # 1.1 SOUS-TITRE
        r'^[A-Z][A-Z\s]{2,}:$',  # TITRE:
    ]
    
    for line in lines:
        line_stripped = line.strip()
        
        if not line_stripped:
            continue
        
        # Vérifier si c'est un titre
        is_title = any(re.match(pattern, line_stripped) for pattern in title_patterns)
        
        if is_title:
            if current_section:
                sections.append(current_section)
            current_section = {
                'title': line_stripped,
                'content': [],
                'subsections': []
            }
        elif current_section:
            current_section['content'].append({'text': line_stripped, 'formatting': {}})
    
    if current_section:
        sections.append(current_section)
    
    return sections



def extract_update_date(soup):
    """Extrait la date de mise à jour du document"""
    update_date = "Date not found"
    ansm_date_pattern = soup.find(string=lambda text: text and "ANSM - Mis à jour le :" in text)
    
    if ansm_date_pattern:
        update_date = ansm_date_pattern.split("ANSM - Mis à jour le :")[1].strip()
    else:
        update_date_element = soup.find('div', id='menuhaut')
        if update_date_element:
            update_date = update_date_element.get_text(strip=True)
            if "mise à jour" in update_date:
                update_date = update_date.split("mise à jour")[1].strip()
            elif "mise" in update_date:
                update_date = update_date.split("mise")[1].strip()
    
    return update_date.replace("le ", "").strip()

def extract_text_content(element):
    """Extrait le texte et les attributs de formatage importants"""
    text = re.sub(r'\s+', ' ', element.get_text(strip=False)).strip()
    
    formatting = {
        "bold": False, "italic": False, "underline": False,
        "list_type": None, "alignment": "left"
    }
    
    # Détection de formatage
    if element.name in ['strong', 'b'] or element.find(['strong', 'b']):
        formatting["bold"] = True
    
    if element.name in ['em', 'i'] or element.find(['em', 'i']):
        formatting["italic"] = True
    
    if 'class' in element.attrs:
        classes = ' '.join(element['class'])
        if 'gras' in classes or 'AmmCorpsTexteGras' in classes:
            formatting["bold"] = True
        if 'italique' in classes:
            formatting["italic"] = True
        if 'souligne' in classes:
            formatting["underline"] = True
        if 'AmmListePuces' in classes:
            formatting["list_type"] = "bullet"
        if 'center' in classes or 'text-align:center' in str(element):
            formatting["alignment"] = "center"
    
    if element.name == 'li' or (element.parent and element.parent.name in ['ul', 'ol']):
        formatting["list_type"] = "bullet" if element.parent and element.parent.name == 'ul' else "numbered"
    
    return {"text": text, "formatting": formatting}

def extract_sections(soup):
    """
    Construit une hiérarchie des sections à partir de <a name="RcpDenomination">.
    Si non trouvé, commence après <p class="DateNotif">.
    L'extraction capture TOUTES les sections du document (sans limite arbitraire).
    """
    root_sections = []    # Liste des sections principales
    stack = []            # Pile pour gérer la hiérarchie
    processed_elements = set()  # Pour suivre les éléments déjà traités
    
    body = soup.find('body')
    if not body:
        return root_sections

    # Trouver le point de départ
    start_found = False
    elements = body.find_all(['a', 'p', 'div', 'table'], recursive=True)
    
    for i, element in enumerate(elements):
        # Point de départ principal : RcpDenomination
        if element.name == 'a' and element.get('name') == 'RcpDenomination':
            start_found = True
            continue
        # Point de départ alternatif : après DateNotif
        elif not start_found and element.name == 'p' and element.has_attr('class') and 'DateNotif' in element['class']:
            start_found = True
            continue
        
        # Ne rien traiter avant le point de départ
        if not start_found:
            continue

        # Ne pas traiter les éléments déjà traités
        if element in processed_elements:
            continue

        # Détecter un titre de section
        if element.name == 'p' and element.has_attr('class'):
            section_class = next((cls for cls in element['class'] if cls.startswith("AmmAnnexeTitre")), None)
            if section_class:
                match = re.search(r"AmmAnnexeTitre(\d+)(Bis)?", section_class)
                if match:
                    level = int(match.group(1))
                    a_tag = element.find('a')
                    title = a_tag.get_text(strip=True) if a_tag else element.get_text(strip=True)
                    
                    # Créer la nouvelle section sans le champ "level"
                    new_section = {"title": title, "content": [], "subsections": []}
                    
                    # Gérer la hiérarchie
                    while stack and stack[-1].get("level", 0) >= level:
                        stack.pop()
                    if stack:
                        stack[-1]["subsections"].append(new_section)
                    else:
                        root_sections.append(new_section)
                    # Garder le level temporairement dans la stack pour la comparaison
                    new_section["level"] = level
                    stack.append(new_section)
                    continue

        # Traiter le contenu
        if element.name == 'table':
            # Extraction du contenu de tableau intégrée directement
            try:
                rows = element.find_all("tr")
                
                # Marquer tous les éléments du tableau comme traités
                for row in rows:
                    for cell in row.find_all(['td', 'th']):
                        processed_elements.add(cell)
                        # Marquer également tous les éléments enfants
                        for child in cell.find_all(True):
                            processed_elements.add(child)
                
                headers = []
                header_row = element.find("thead")
                if header_row and header_row.find_all("th"):
                    headers = [th.get_text(strip=True) for th in header_row.find_all("th")]
                
                table_data = []
                for row in rows:
                    cols = row.find_all(["td", "th"])
                    row_data = [col.get_text(strip=True) for col in cols]
                    if any(cell.strip() for cell in row_data):
                        table_data.append(row_data)
                
                content_data = {"table": table_data}
                
                if headers:
                    content_data["headers"] = headers
                
                caption = element.find("caption")
                if caption:
                    content_data["caption"] = caption.get_text(strip=True)
                    processed_elements.add(caption)
            except Exception as e:
                content_data = {"error": f"Erreur d'extraction de tableau: {str(e)}"}
        elif element.name in ['p', 'div']:
            if element.has_attr('class') and any(cls.startswith("AmmAnnexeTitre") for cls in element['class']):
                continue
            content_data = extract_text_content(element)
        else:
            continue
        
        # Ajouter le contenu à la dernière section
        if stack:
            stack[-1]["content"].append(content_data)
        elif root_sections:
            root_sections[-1]["content"].append(content_data)
        else:
            root_sections.append({
                "title": "Contenu non sectionné",
                "content": [content_data],
                "subsections": []
            })
    
    # Nettoyer les sections en supprimant le champ level
    def clean_sections(sections):
        for section in sections:
            if "level" in section:
                del section["level"]
            clean_sections(section["subsections"])
    
    clean_sections(root_sections)
    return root_sections

def extract_medicine_title(soup):
    """Extrait directement le titre du médicament"""
    denomination_section = soup.find('a', {'name': 'RcpDenomination'})
    if denomination_section:
        title_element = denomination_section.find_next('p', class_=lambda c: c and ('AmmCorpsTexteGras' in c or 'AmmDenomination' in c))
        if title_element:
            return re.sub(r'\s+', ' ', title_element.get_text(strip=True)).strip()
    
    # Méthodes alternatives
    title_h1 = soup.find('h1', class_='textedeno')
    if title_h1:
        title_text = title_h1.get_text(strip=True)
        if " - " in title_text:
            title_text = title_text.split(" - ")[0].strip()
        return title_text
    
    # Dernière tentative
    for class_name in ['AmmDenomination', 'AmmCorpsTexteGras']:
        title_elements = soup.find_all('p', class_=class_name, limit=3)
        for element in title_elements:
            text = element.get_text(strip=True)
            if text and len(text) > 5:
                return re.sub(r'\s+', ' ', text).strip()
    
    return "Document sans titre"

def extract_laboratory(soup):
    """Extrait directement le laboratoire"""
    titulaire_section = soup.find('a', {'name': 'RcpTitulaireAmm'})
    if titulaire_section:
        # Récupérer précisément le paragraphe qui contient le nom du laboratoire (généralement le premier ou deuxième paragraphe après l'ancre)
        paragraphs = []
        current_elem = titulaire_section.parent
        # Obtenir les 3 paragraphes après la section de titre
        for _ in range(5):  # Cherche dans les 5 éléments suivants maximum
            current_elem = current_elem.find_next(['p', 'div'])
            if not current_elem:
                break
            paragraphs.append(current_elem)
        
        # Stratégie 1: Chercher spécifiquement un élément avec span class="gras"
        for paragraph in paragraphs:
            spans = paragraph.find_all('span', class_='gras')
            for span in spans:
                text = span.get_text(strip=True)
                # Vérifier que ce n'est pas une adresse (ne contient pas de code postal)
                if text and not re.match(r'^\d{5}', text) and not re.search(r'\d{5}\s', text):
                    return text
        
        # Stratégie 2: Chercher le premier paragraphe qui contient du texte en gras
        for paragraph in paragraphs:
            # Vérifier si le paragraphe a la classe AmmCorpsTexteGras ou contient un span gras
            if (paragraph.has_attr('class') and 'AmmCorpsTexteGras' in paragraph['class']) or paragraph.find('span', class_='gras'):
                text = paragraph.get_text(strip=True)
                # Vérifier que ce n'est pas un titre, une date ou une adresse
                if not text.startswith(('7.', '8.', 'TITULAIRE', 'DATE')) and not re.match(r'^\d{5}', text):
                    return text
        
        # Stratégie 3: Prendre le premier paragraphe non vide qui n'est pas un titre
        for paragraph in paragraphs:
            text = paragraph.get_text(strip=True)
            # Exclure les titres et les adresses
            if (text and 
                not text.startswith(('7.', '8.', 'TITULAIRE', 'DATE')) and 
                not re.match(r'^\d{5}', text) and 
                not re.search(r'\b\d{5}\b', text) and  # Pas de code postal
                not any(word.lower() in text.lower() for word in ['rue', 'avenue', 'boulevard', 'cedex'])):  # Pas d'adresse
                return text.replace('LABORATOIRES', 'LABORATOIRES ').strip()  # Fix for cases where LABORATOIRES is stuck to the name
    
    return ""

# ══════════════════════════════════════════════════════════════════════
#  Composition : extraction de repli par la rubrique 2 du RCP
#
#  Le chemin historique ci-dessous lit le premier <p class="AmmComposition">
#  et exige la forme « substance......dosage ». Il fonctionne sur 9 837 fiches
#  et n'est pas touché.
#
#  Il rendait cependant une liste vide pour 2 209 autres, dont 96,2 % portent
#  pourtant une rubrique de composition. Les notices concernées écrivent la
#  composition en phrase — « Chaque comprimé contient 300 mg d'abacavir » —
#  ou n'ont aucun paragraphe AmmComposition, la donnée vivant alors sous
#  l'ancre RCP « RcpCompoQualiQuanti », présente sur toutes les notices
#  examinées.
#
#  Ce repli n'est tenté que si le chemin historique n'a rien rendu.
# ══════════════════════════════════════════════════════════════════════

_UNITE = (r'(?:mg|g|µg|mcg|microgrammes?|ml|mL|L|UI|U\.I\.|Ul|millions?|'
          r'milliards?|unit[ée]s?|%|mmol|MBq|GBq|kBq|mEq)')
_DOSE = r'\d[\d\s.,]*\s*' + _UNITE

# Au-delà, le texte relève des excipients ou de la rubrique suivante.
_ARRET = re.compile(r'excipient|liste compl[eè]te|^\s*3\s*\.\s*FORME|pour la liste', re.I)

# Amorces sans valeur informative. Volontairement minimales : une première
# version retirait aussi « Chaque comprimé ... contient », ce qui privait le
# motif principal de son point d'accroche et faisait chuter l'extraction de
# 90 % à 43 % sur le même corpus. Mesure à l'appui, on ne retire que ce qui
# ne porte aucune information.
_AMORCE = re.compile(
    r'^\s*quantit[ée]\s+correspondant\s+[àa]\s*'
    r'|^\s*(?:substances?\s+actives?|composition|principes?\s+actifs?)\s*:?\s*', re.I)

_P_POINTS = re.compile(r'^(.{3,80}?)\.{3,}')
_P_CONTIENT_DOSE = re.compile(
    r'contient\s+(?:environ\s+)?' + _DOSE +
    r'\s+(?:de\s+|d[’\']\s*|du\s+|des\s+|de\s+la\s+|de\s+l[’\']\s*)(.{3,70}?)(?=\s*[(,.;]|\s*$)', re.I)
_P_CONTIENT_NU = re.compile(
    r'contient\s+(?:du\s+|de\s+la\s+|de\s+l[’\']\s*|des\s+|de\s+)(.{3,70}?)(?=\s*[(,.;]|\s*$)', re.I)
_P_TETE = re.compile(r'^([A-Za-zÀ-ÿ][^.\d]{2,70}?)\s+' + _DOSE)

# Fragments qui ne désignent pas une substance.
_REJET = re.compile(
    r'^(?:pour|chaque|cette?|ces|un|une|le|la|les|du|des|de|d|solution|poudre|'
    r'comprim[ée]|g[ée]lule|flacon|ampoule|sachet|dose|volume|quantit[ée]|'
    r'principe actif|substances? actives?|composition|excipients?|contenu|teneur|'
    r'composants?|[ée]quivalent|apr[èe]s reconstitution|'
    r'concentration|masse|poids|contient)$', re.I)

# Grandeurs mesurées, et non substances : « activité anti-Xa » figurait comme
# principe actif sur 38 notices d'héparine. Aucun appariement erroné n'en
# découlait, mais la valeur s'affichait telle quelle sur la fiche.
_MESURE = re.compile(r'^(?:activit[ée]|titre|teneur|concentration|puissance|osmolarit[ée]|p[HhH])\b', re.I)

# Éléments seuls : ils ne désignent pas un principe actif identifiable.
# « sodium », extrait d'une solution de nutrition, s'appariait à « Potassium ».
# Un faux appariement se présente avec la même assurance qu'un appariement juste.
_MINERAL_SEUL = re.compile(
    r'^(?:sodium|potassium|calcium|magn[ée]sium|zinc|fer|lithium|aluminium|'
    r'ammonium|argent|cuivre|mangan[èe]se|s[ée]l[ée]nium|iode|phosphore|'
    r'chrome|cobalt|molybd[èe]ne|fluor|brome|chlorure|eau|glucose anhydre)$', re.I)

_AMORCE_INTERNE = re.compile(
    r'^.*?contient\s+(?:du\s+|de\s+la\s+|de\s+l\s*|des\s+|de\s+)?', re.I)
_QUEUE = re.compile(
    r'\s+(?:dans|sous\s+forme|correspondant|[ée]quivalant|soit|'
    r'par\s+(?:\d[\d\s.,]*\s*)?(?:flacon|ampoule|dose|sachet|ml|mL|L|g|mg|comprim[ée]|poche)).*$',
    re.I)


_MESURE_DE = re.compile(r'^(?:[^,;]{0,40}?)\s+(?:de\s+|d[^a-zA-Z]\s*|du\s+|en\s+)', re.I)

def _nettoyer_substance(fragment):
    """Rend un nom de substance exploitable, ou None si le fragment n'en est pas un."""
    texte = re.sub(r'\s*\([^)]*\)', ' ', fragment or '')
    texte = _AMORCE_INTERNE.sub('', texte)
    texte = _QUEUE.sub('', texte)
    texte = re.sub(r'\s+', ' ', texte).strip(' *:;,.’\'-')
    if not texte or len(texte) < 3 or len(texte) > 70:
        return None
    # Une grandeur peut introduire la vraie substance : « activite anti-Xa de
    # dalteparine sodique ». On retire l'amorce plutot que de jeter la ligne ;
    # ce qui reste sans substance nommee, lui, est bien ecarte.
    if _MESURE.match(texte):
        degage = _MESURE_DE.sub('', texte).strip(' *:;,.-')
        if degage and degage != texte and len(degage) >= 3 and not _MESURE.match(degage):
            texte = degage
        else:
            return None
    if _REJET.match(texte) or _MINERAL_SEUL.match(texte):
        return None
    if not re.search(r'[A-Za-zÀ-ÿ]{3}', texte):
        return None
    return texte


def _substances_d_une_ligne(ligne):
    """Une phrase peut porter plusieurs substances : « X et Y »."""
    for motif in (_P_POINTS, _P_CONTIENT_DOSE, _P_CONTIENT_NU, _P_TETE):
        trouve = motif.search(ligne)
        if not trouve:
            continue
        sorties = []
        for morceau in re.split(r'\s+et\s+(?=\d|[A-Za-zÀ-ÿ])', trouve.group(1)):
            morceau = re.sub(r'^' + _DOSE + r'\s+(?:de\s+|d[’\']\s*|du\s+)?', '',
                             morceau, flags=re.I)
            propre = _nettoyer_substance(morceau)
            if propre:
                sorties.append(propre)
        return sorties
    return []


def lignes_composition_rcp(soup):
    """Texte de la rubrique 2 du RCP, dans l'ordre, sans doublon."""
    ancre = soup.find('a', attrs={'name': 'RcpCompoQualiQuanti'})
    if not ancre:
        return []
    fin = soup.find('a', attrs={'name': 'RcpFormePharm'})
    vus, sortie = set(), []
    for element in ancre.find_all_next():
        if fin is not None and element is fin:
            break
        if element.name in ('p', 'div', 'td', 'li'):
            texte = element.get_text(' ', strip=True)
            if texte and texte not in vus:
                vus.add(texte)
                sortie.append(texte)
    return sortie


def extract_substances_from_rcp(soup):
    """Substances actives lues dans la rubrique 2 du RCP. Liste éventuellement vide."""
    trouvees = []
    for ligne in lignes_composition_rcp(soup):
        if _ARRET.search(ligne):
            break
        trouvees.extend(_substances_d_une_ligne(_AMORCE.sub('', ligne)))

    vus, sortie = set(), []
    for substance in trouvees:
        cle = re.sub(r'[^a-z0-9]', '', substance.lower())
        if cle and cle not in vus:
            vus.add(cle)
            sortie.append(substance)
    return sortie[:6]


def extract_substances_and_dosages(soup):
    """
    Extrait la première substance active et son dosage à partir du premier élément avec la classe 'AmmComposition'.

    À défaut, retombe sur la rubrique 2 du RCP (voir ci-dessus).
    """
    dosages = []
    substances = []

    # Récupère directement le premier paragraphe avec la classe 'AmmComposition'
    paragraph = soup.find('p', class_='AmmComposition')
    
    if paragraph:
        text = paragraph.get_text(strip=True)
        # Reduced logging to avoid console clutter
        # print(f"🔎 Paragraphe trouvé: {text}")

        # Regex pour extraire substance et dosage
        match = re.search(
            r"^(.*?)\.{3,}\s*([\d\s,]+(?:[.,]\d+)?\s*(?:mg|g|ml|µg|UI|U\.I\.|microgrammes|unités|%))\s*$",
            text, re.UNICODE | re.IGNORECASE
        )
        if match:
            substance = match.group(1).strip()
            dosage = match.group(2).strip()

            # Nettoyage du nom de la substance : supprime les contenus entre parenthèses
            substance = re.sub(r'\s*\([^)]*\)', '', substance).strip()

            # print(f"✅ Extraction réussie : Substance '{substance}' - Dosage '{dosage}'")
            substances.append(substance)
            dosages.append(dosage)
        # else:
            # print("⚠️ Aucun dosage détecté dans ce texte.")
    # else:
        # print("⚠️ Aucune balise <p class='AmmComposition'> trouvée.")

    # Repli : le chemin historique n'a rien rendu. Il n'est jamais court-circuité,
    # de sorte que les fiches déjà correctement extraites gardent leur valeur.
    if not substances:
        substances = extract_substances_from_rcp(soup)

    return {
        "substances_actives": substances,
        "dosages": dosages
    }

def extract_pharmaceutical_form(soup):
    """Extrait la forme pharmaceutique"""
    form_section = soup.find('a', {'name': 'RcpFormePharm'})
    if form_section:
        # Recherche plus générique pour trouver le premier paragraphe après la section
        form_paragraph = form_section.find_next('p')
        if form_paragraph:
            return form_paragraph.get_text(strip=True).rstrip('.')
    
    # Alternative via le titre
    title = extract_medicine_title(soup)
    if title and ',' in title:
        return title.split(',', 1)[1].strip()
    
    return ""

if __name__ == '__main__':
    print("Lancement du scraper en mode standalone...")
    run_scraper()
