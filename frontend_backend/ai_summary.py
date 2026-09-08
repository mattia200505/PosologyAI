import os
import re
from dotenv import load_dotenv
import time
import logging
from mistralai import Mistral

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables from .env file
load_dotenv(override=True)

# Get API key from environment variables
MISTRAL_API_KEY = os.getenv('MISTRAL_API_KEY')
if MISTRAL_API_KEY:
    # Ne jamais journaliser de fragment de la clé : les journaux sont partagés,
    # archivés et parfois joints à un rapport. Sa présence suffit à diagnostiquer.
    logger.info("MISTRAL_API_KEY chargée")
else:
    logger.warning("MISTRAL_API_KEY non trouvée dans .env")

# Les résumés ne sont plus périmés par le temps mais par le contenu :
# ils sont régénérés uniquement lorsque l'empreinte de la notice change.
# Voir summary_is_fresh() et get_or_generate_summary().

# ──────────────────────────────────────────────────────────────
# Cache mémoire des appels IA (reformulations et synthèses).
#
# Une même question repostée — changement de langue, retour arrière,
# partage d'URL entre collègues — relançait deux appels Mistral et un
# parcours complet Qdrant + MongoDB. Un cache borné (TTL + taille)
# suffit : les réponses ne dépendent que de la question, de la langue
# et du lot de documents trouvés.
# ──────────────────────────────────────────────────────────────
_CACHE_TTL_SECONDES = 3600
_CACHE_TAILLE_MAX = 128
_cache_ia = {}


def _cache_get(cle):
    entree = _cache_ia.get(cle)
    if not entree:
        return None
    horodatage, valeur = entree
    if time.time() - horodatage > _CACHE_TTL_SECONDES:
        _cache_ia.pop(cle, None)
        return None
    return valeur


def _cache_set(cle, valeur):
    if len(_cache_ia) >= _CACHE_TAILLE_MAX:
        plus_ancien = min(_cache_ia, key=lambda k: _cache_ia[k][0])
        _cache_ia.pop(plus_ancien, None)
    _cache_ia[cle] = (time.time(), valeur)


def _appel_mistral(messages, temperature=0.4, max_tokens=400, tentatives=2):
    """Appel Mistral avec reprise sur erreur transitoire.

    L'API renvoie parfois 503 / unreachable_backend pendant quelques
    secondes ; une seule tentative faisait alors échouer toute la
    recherche alors qu'un second essai immédiat suffit presque toujours.
    """
    derniere_erreur = None
    for tentative in range(tentatives):
        try:
            client = Mistral(api_key=MISTRAL_API_KEY)
            reponse = client.chat.complete(
                model="mistral-small-2503",
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens
            )
            return (reponse.choices[0].message.content or "").strip()
        except Exception as e:
            derniere_erreur = e
            message = str(e)
            transitoire = ("503" in message or "429" in message
                           or "unreachable" in message.lower()
                           or "rate limit" in message.lower())
            if transitoire and tentative < tentatives - 1:
                time.sleep(1.5 * (tentative + 1))
                continue
            raise
    raise derniere_erreur


def call_mistral_reformulate(user_query):
    """
    Transforme une question en langage naturel en requête de recherche efficace.

    La reformulation extrait les mots-clés médicaux ET les complète par
    leurs équivalents usuels (« mal de gorge » -> « mal de gorge pharyngite
    angine antalgique »). Le modèle d'embedding travaille mieux sur des
    mots-clés que sur une phrase interrogative, et les synonymes élargissent
    le rappel vers les notices qui emploient le vocabulaire des RCP.

    Args:
        user_query (str): Question utilisateur en langage naturel
    Returns:
        str: Requête optimisée (mots-clés + synonymes utiles)
    """
    question_normee = ' '.join(user_query.split()).lower()
    cle_cache = ('reformulation', question_normee)
    en_cache = _cache_get(cle_cache)
    if en_cache is not None:
        return en_cache

    if not MISTRAL_API_KEY:
        return user_query  # fallback: retourne la question d'origine

    prompt = f"""Tu prépares une recherche dans une base de notices de médicaments (RCP françaises).
Transforme la question ci-dessous en UNE SEULE ligne de mots-clés :
- garde les termes médicaux essentiels (symptôme, maladie, substance, forme galénique)
- ajoute 2 à 4 synonymes ou termes apparentés utiles (nom de DCI, classe thérapeutique, terme de RCP)
- supprime les mots vides (que, quel, pour, comment, est-ce...)
- pas de phrase, pas d'explication, pas de ponctuation finale, pas de guillemets

Exemples :
Question : Quels médicaments pour le mal de gorge chez l'adulte ?
Réponse : mal de gorge pharyngite angine antiseptique local collyre
Question : Quel truc existe contre la tension ?
Réponse : hypertension artérielle antihypertenseur inhibiteur calcique diurétique

Question : {user_query}
Réponse :"""
    try:
        reformule = _appel_mistral(
            [{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=64
        )
        # Nettoyage : guillemets, préfixes parasites, lignes multiples.
        reformule = reformule.replace('"', '').replace("'", " ")
        lignes = [l.strip() for l in reformule.splitlines() if l.strip()]
        for ligne in lignes:
            basse = ligne.lower()
            if basse.startswith(('réponse', 'reponse', 'question')):
                continue
            reformule = ligne.rstrip(' .;:')
            break
        else:
            reformule = ' '.join(lignes).rstrip(' .;:') if lignes else user_query

        # Garde-fou : si le modèle a répondu autre chose qu'une requête courte,
        # on retombe sur la question brute plutôt que d'empoisonner la recherche.
        if not reformule or len(reformule) > 300:
            reformule = user_query

        _cache_set(cle_cache, reformule)
        return reformule
    except Exception as e:
        logger.error(f"Erreur lors de la reformulation Mistral : {e}")
        return user_query


def _extraits_pertinents(doc, question, nb_extraits=2, longueur=340):
    """
    Sélectionne dans une notice les passages les plus proches de la question.

    L'ancienne synthèse n'injectait que le premier paragraphe de la première
    section — souvent la présentation galénique — quelle que soit la question :
    demander « posologie du X » donnait à lire au modèle sa composition. Le
    choix se fait ici par recouvrement lexical entre la question et chaque
    section/sous-section, ce qui remonte les rubriques vraiment utiles
    (indications, posologie, contre-indications…).

    Args:
        doc (dict): résultat de recherche (peut porter `sections` directement
                    ou via `full_medicine`)
        question (str): question originale de l'utilisateur
        nb_extraits (int): nombre maximum d'extraits retenus
        longueur (int): longueur maximale de chaque extrait

    Returns:
        list[tuple]: couples (titre_section, extrait)
    """
    sections = doc.get('sections')
    if not sections and isinstance(doc.get('full_medicine'), dict):
        sections = doc['full_medicine'].get('sections')
    if not sections:
        return []

    mots_question = set(re.findall(r"[a-zà-ÿ0-9]{4,}", question.lower()))
    candidats = []

    def noter(titre_section, contenu_items):
        texte = ' '.join(
            item.get('text', '') for item in (contenu_items or [])
            if isinstance(item, dict) and item.get('text')
        ).strip()
        if len(texte) < 60:
            return
        texte_bas = texte.lower()
        recouvrement = sum(1 for mot in mots_question if mot in texte_bas)
        candidats.append((recouvrement, titre_section, texte))

    for section in sections:
        titre = section.get('title', '') or ''
        noter(titre, section.get('content'))
        for sous_section in (section.get('subsections') or []):
            sous_titre = sous_section.get('title', '') or ''
            noter(f"{titre} – {sous_titre}".strip(' –'),
                  sous_section.get('content'))

    candidats.sort(key=lambda c: c[0], reverse=True)

    extraits = []
    for recouvrement, titre, texte in candidats[:nb_extraits]:
        if recouvrement == 0 and extraits:
            break  # au-delà, on ne sert que des passages sans lien avec la question
        extrait = texte[:longueur].strip()
        if len(texte) > longueur:
            extrait += '…'
        extraits.append((titre, extrait))
    return extraits


def call_mistral_summarize(user_query, docs, language='fr'):
    """
    Génère la réponse synthétique (RAG) à partir des documents trouvés.

    Améliorations par rapport à la première version :
    - contexte enrichi : substances, forme, laboratoire ET extraits des
      rubriques réellement proches de la question (voir `_extraits_pertinents`) ;
    - prompt système distinct, réponse structurée citant les médicaments ;
    - reprise automatique sur erreur transitoire de l'API ;
    - cache mémoire : une même recherche rejouée ne rappelle pas l'API.
    """
    if not MISTRAL_API_KEY:
        error_msg = "Error: Missing Mistral API key." if language == 'en' else "Erreur : Clé API Mistral manquante."
        return f"<p>{error_msg}</p>"

    ids_docs = tuple(sorted(str(d.get('mongo_id') or d.get('_id') or '')
                            for d in docs))[:12]
    cle_cache = ('synthese', ' '.join(user_query.split()).lower(), language, ids_docs)
    en_cache = _cache_get(cle_cache)
    if en_cache is not None:
        return en_cache

    consigne_langue = ('Answer in English.' if language == 'en'
                       else 'Réponds en français.')
    systeme = f"""Tu es l'assistant médical de PosologyAI, une plateforme de recherche de médicaments.
Tu réponds aux questions en t'appuyant en priorité sur les notices fournies ci-dessous.
{consigne_langue}
FORMAT DE SORTIE — impératif :
- HTML simple uniquement : <p>, <strong>, <em>, <ul>, <li>. Jamais de Markdown, jamais de balises <code>.
- Maximum 180 mots, direct et concret, sans formule d'introduction (« Voici... », « D'après les documents... »).
- Mets en gras le nom commercial des médicaments pertinents et les termes médicaux clés.
- Si les notices suffisent, cite-les. Sinon complète avec des connaissances médicales fiables et générales.
- Termine par une phrase brève invitant à consulter un professionnel de santé."""

    contexte = ""
    for i, doc in enumerate(docs[:6], 1):
        details = doc.get('medicine_details') or (
            doc.get('full_medicine') or {}).get('medicine_details') or {}
        title = doc.get('title', f'Document {i}')
        laboratoire = details.get('laboratoire', '')
        substances = details.get('substances_actives') or doc.get('substances') or []
        forme = details.get('forme', '')

        if language == 'en':
            ligne = (f"\n[{i}] {title}"
                     + (f" — Laboratory: {laboratoire}" if laboratoire else "")
                     + (f" — Form: {forme}" if forme else "")
                     + (f" — Active substances: {', '.join(substances)}" if substances else ""))
        else:
            ligne = (f"\n[{i}] {title}"
                     + (f" — Laboratoire : {laboratoire}" if laboratoire else "")
                     + (f" — Forme : {forme}" if forme else "")
                     + (f" — Substances : {', '.join(substances)}" if substances else ""))

        for titre_section, extrait in _extraits_pertinents(doc, user_query):
            ligne += f"\n   ({titre_section}) {extrait}"
        contexte += ligne

    if language == 'en':
        question_libelle = "User question"
        notices_libelle = "Leaflets found in the database:"
    else:
        question_libelle = "Question utilisateur"
        notices_libelle = "Notices trouvées dans la base PosologyAI :"

    prompt_utilisateur = f"{question_libelle} : {user_query}\n{notices_libelle}{contexte}"

    try:
        reponse = _appel_mistral(
            [
                {"role": "system", "content": systeme},
                {"role": "user", "content": prompt_utilisateur},
            ],
            temperature=0.4,
            max_tokens=450
        )
        reponse = clean_summary_format(reponse)
        if not reponse.strip().startswith('<p>'):
            reponse = "<p>" + reponse.replace("\n\n", "</p><p>") + "</p>"
            reponse = reponse.replace("<p></p>", "")
        _cache_set(cle_cache, reponse)
        return reponse
    except Exception as e:
        logger.error(f"Erreur lors de la génération de réponse Mistral : {e}")
        error_msg = ("<p>The AI answer is temporarily unavailable. The results "
                     "below remain available.</p>" if language == 'en'
                     else "<p>La réponse IA est momentanément indisponible. Les documents "
                          "retrouvés ci-dessous restent consultables.</p>")
        return error_msg

def generate_generic_summary(medicine):
    """Generate a generic summary from medicine data when API is not available"""
    title = medicine.get('title', 'Médicament inconnu')
    substances = medicine.get('medicine_details', {}).get('substances_actives', [])
    forme = medicine.get('medicine_details', {}).get('forme', 'Non spécifié')
    laboratoire = medicine.get('medicine_details', {}).get('laboratoire', 'Non spécifié')
    
    substances_str = ', '.join(substances) if substances else 'Non spécifiée'
    
    return f"""
    <p><strong>{title}</strong> est un médicament contenant {substances_str}. 
    Il se présente sous la forme de <strong>{forme}</strong> et est distribué par le laboratoire <strong>{laboratoire}</strong>.</p>
    
    <p>Pour obtenir des informations complètes et à jour sur ce médicament, notamment sur ses indications, 
    posologie, contre-indications et effets secondaires, consultez le dossier complet du médicament dans les sections ci-dessous.</p>
    
    <p><em>Note: La génération automatique de résumés par IA nécessite une clé API Mistral. 
    Vous pouvez l'obtenir gratuitement sur <a href="https://console.mistral.ai/" target="_blank">console.mistral.ai</a> 
    et l'ajouter à votre fichier .env.</em></p>
    """

def generate_medicine_summary(medicine):
    """
    Generate an AI summary of the medicine using Mistral AI
    
    Args:
        medicine (dict): Medicine data
        
    Returns:
        str: AI-generated summary of the medicine
    """
    # Check if API key is available
    if not MISTRAL_API_KEY:
        return generate_generic_summary(medicine)
    
    # Extract basic information for the summary
    title = medicine.get('title', 'Médicament inconnu')
    substances = medicine.get('medicine_details', {}).get('substances_actives', [])
    forme = medicine.get('medicine_details', {}).get('forme', 'Non spécifié')
    laboratoire = medicine.get('medicine_details', {}).get('laboratoire', 'Non spécifié')
    dosages = medicine.get('medicine_details', {}).get('dosages', [])
    
    # Extract ALL content from sections
    all_sections_text = ""
    
    if 'sections' in medicine:
        for section in medicine['sections']:
            section_title = section.get('title', '')
            all_sections_text += f"\n### {section_title}\n"
            
            # Get content from this section
            if 'content' in section and section['content']:
                for content_item in section['content']:
                    if 'text' in content_item:
                        all_sections_text += content_item['text'] + "\n"
            
            # Get content from subsections
            if 'subsections' in section:
                for subsection in section['subsections']:
                    subsection_title = subsection.get('title', '')
                    all_sections_text += f"\n#### {subsection_title}\n"
                    
                    if 'content' in subsection and subsection['content']:
                        for content_item in subsection['content']:
                            if 'text' in content_item:
                                all_sections_text += content_item['text'] + "\n"
    
    # Limit the total content length to avoid exceeding API limits
    if len(all_sections_text) > 5000:
        all_sections_text = all_sections_text[:5000] + "...[contenu tronqué]"
    
    # Create a prompt for the API
    prompt = f"""
    Génère un résumé concis en français pour le médicament suivant:
    
    Nom: {title}
    Substances actives: {', '.join(substances) if substances else 'Non spécifié'}
    Forme pharmaceutique: {forme}
    Laboratoire: {laboratoire}
    Dosages: {', '.join(str(d) for d in dosages) if dosages else 'Non spécifié'}
    
    Informations détaillées sur le médicament:
    {all_sections_text}
    
    Le résumé doit inclure:
    1. Les utilisations principales de ce médicament
    2. Comment il fonctionne en termes simples
    3. Mention brève des effets secondaires courants le cas échéant
    4. Précautions d'emploi importantes
    
    INSTRUCTIONS DE FORMATAGE IMPORTANTES:
    - Utilise UNIQUEMENT du HTML simple (pas de Markdown)
    - Format: paragraphes avec balises <p> </p>
    - Pour le texte en gras, utilise <strong> </strong>
    - Pour l'italique, utilise <em> </em>
    - Mets en gras (<strong>) les noms de maladies, symptômes et termes médicaux importants
    - Mets également en gras les précautions d'emploi cruciales
    - Maximum 3-4 paragraphes
    - Ton: Informatif et accessible, adapté à un large public
    - N'UTILISE PAS de balises de code comme ```html au début ou à la fin
    """
    
    try:
        # Initialize Mistral client
        client = Mistral(api_key=MISTRAL_API_KEY)
        
        # Make the API request using the Mistral client - using the exact format as our successful test
        chat_response = client.chat.complete(
            model="mistral-small-2503",
            messages=[
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            temperature=0.7,
            max_tokens=500
        )
        
        # Extract the generated summary
        summary = chat_response.choices[0].message.content
        
        # Clean up the formatting
        summary = clean_summary_format(summary)
        
        # Ensure the summary has proper HTML formatting
        if not summary.strip().startswith('<p>'):
            summary = "<p>" + summary.replace("\n\n", "</p><p>") + "</p>"
            summary = summary.replace("<p></p>", "")
        
        return summary
        
    except Exception as e:
        logger.error(f"Erreur lors de la génération du résumé IA: {e}")
        return f"<p>Impossible de générer un résumé pour le moment. Veuillez réessayer plus tard. Erreur: {str(e)}</p>"

def clean_summary_format(summary):
    """Clean up any markdown or code block formatting from the summary"""
    # Remove code block markers with language specifiers (like ```html, ```markdown, etc.)
    summary = re.sub(r'```[a-zA-Z]*', '', summary)
    
    # Remove closing code block markers
    summary = re.sub(r'```', '', summary)
    
    # Remove inline code markers
    summary = re.sub(r'`', '', summary)
    
    # Convert Markdown bold (**text**) to HTML bold (<strong>text</strong>)
    summary = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', summary)
    
    # Convert Markdown italic (*text*) to HTML italic (<em>text</em>)
    summary = re.sub(r'\*([^\*]+)\*', r'<em>\1</em>', summary)
    
    return summary.strip()

def summary_is_fresh(doc, content_hash):
    """
    Indique si le résumé d'un document est encore aligné sur sa notice.

    Le résumé n'est invalidé que lorsque le changement de contenu est certain :
    - pas d'empreinte enregistrée -> résumé antérieur au suivi, à régénérer
    - empreinte courante inconnue -> on conserve le résumé plutôt que de
      déclencher une régénération à chaque consultation

    Args:
        doc (dict): document contenant summary_content_hash
        content_hash (str): empreinte actuelle de la notice

    Returns:
        bool: True si le résumé peut être servi tel quel
    """
    stored = doc.get('summary_content_hash')
    if not stored:
        return False
    if not content_hash:
        return True
    return stored == content_hash


def get_or_generate_summary(medicine, db=None):
    """
    Get cached summary from database or generate a new one

    Le résumé est invalidé par le content_hash de la notice : il n'est
    régénéré que si le contenu du médicament a changé depuis sa rédaction.

    Args:
        medicine (dict): Medicine data
        db (pymongo.database.Database, optional): MongoDB database connection

    Returns:
        str: AI-generated or cached summary
    """
    medicine_id = medicine.get('_id')
    current_time = int(time.time())
    content_hash = medicine.get('content_hash')

    # Résumé déjà porté par l'objet et toujours aligné sur le contenu
    if medicine.get('ai_summary') and summary_is_fresh(medicine, content_hash):
        return medicine['ai_summary']

    # Sinon, vérifier en base
    if db is not None:
        try:
            stored_medicine = db.medicines.find_one(
                {"_id": medicine_id},
                {"ai_summary": 1, "summary_content_hash": 1, "content_hash": 1}
            )

            if stored_medicine and stored_medicine.get('ai_summary'):
                reference = content_hash or stored_medicine.get('content_hash')
                if summary_is_fresh(stored_medicine, reference):
                    return stored_medicine['ai_summary']

        except Exception as e:
            logger.error(f"Error checking for cached summary: {e}")

    summary = generate_medicine_summary(medicine)

    # Enregistrer le résumé avec l'empreinte du contenu dont il est issu
    if db is not None:
        try:
            db.medicines.update_one(
                {"_id": medicine_id},
                {"$set": {
                    "ai_summary": summary,
                    "summary_timestamp": current_time,
                    "summary_content_hash": content_hash
                }}
            )
        except Exception as e:
            logger.error(f"Error saving summary to database: {e}")
    return summary
