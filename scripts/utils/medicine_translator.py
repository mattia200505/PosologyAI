"""
Module de traduction des données médicamenteuses
Traduit les médicaments du français vers l'anglais et les stocke dans MongoDB
"""
import os
from pymongo import MongoClient
from mistralai.client import Mistral
import json
import copy
import re
import logging
from typing import Dict, Optional

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class MedicineTranslator:
    """Gère la traduction des médicaments et le cache dans MongoDB"""
    
    def __init__(self, mongo_uri: str = 'mongodb://localhost:27017/', 
                 db_name: str = 'medicsearch',
                 mistral_api_key: str = None):

        """
        Initialise le traducteur
        
        Args:
            mongo_uri: URI de connexion MongoDB
            db_name: Nom de la base de données
            mistral_api_key: Clé API Mistral
        """
        self.client = MongoClient(mongo_uri)
        self.db = self.client[db_name]
        
        # Collections
        self.medicines_fr = self.db['medicines']  # Collection originale en français
        self.medicines_en = self.db['Medecines-EN']  # Collection des traductions
        
        # Index sur denomination pour recherche rapide
        self.medicines_en.create_index('original_denomination', unique=True)
        
        # API Mistral pour la traduction
        self.mistral_api_key = mistral_api_key or os.environ.get('MISTRAL_API_KEY', '')
        if self.mistral_api_key:
            self.mistral_client = Mistral(api_key=self.mistral_api_key)
        else:
            logger.warning("MISTRAL_API_KEY non configurée, la traduction ne fonctionnera pas")
            self.mistral_client = None
    
    def get_translation(self, medicine_name: str) -> Optional[Dict]:
        """
        Récupère la traduction d'un médicament depuis le cache
        
        Args:
            medicine_name: Nom du médicament en français
            
        Returns:
            Dictionnaire du médicament traduit ou None si non trouvé
        """
        return self.medicines_en.find_one({'original_denomination': medicine_name})
    
    def translate_medicine_data(self, medicine_data: Dict) -> Dict:
        """
        Traduit TOUTES les données d'un médicament du français vers l'anglais
        
        Args:
            medicine_data: Dictionnaire contenant les données du médicament en français
            
        Returns:
            Dictionnaire avec les données traduites
        """
        if not self.mistral_client:
            logger.error("Mistral API non configurée")
            return medicine_data
        
        # Préparer le texte complet à traduire (toutes les sections)
        text_to_translate = []
        
        # Ajouter le titre
        if medicine_data.get('title'):
            text_to_translate.append(f"TITLE: {medicine_data['title']}")
        
        # Ajouter les détails médicaux
        medicine_details = medicine_data.get('medicine_details', {})
        if medicine_details:
            text_to_translate.append(f"FORM: {medicine_details.get('forme', '')}")
            text_to_translate.append(f"SUBSTANCES: {', '.join(medicine_details.get('substances_actives', []))}")
            text_to_translate.append(f"LABORATORY: {medicine_details.get('laboratoire', '')}")
        
        # Ajouter toutes les sections avec leur contenu
        sections = medicine_data.get('sections', [])
        if sections:
            for section in sections:
                section_title = section.get('title', '')
                if section_title:
                    text_to_translate.append(f"\nSECTION: {section_title}")
                
                # Contenu de la section (c'est une liste!)
                content = section.get('content', [])
                if isinstance(content, list):
                    for content_item in content:
                        if isinstance(content_item, dict) and 'text' in content_item:
                            text = content_item['text']
                            if text:
                                text_to_translate.append(f"TEXT: {text}")
                
                # Sous-sections
                subsections = section.get('subsections', [])
                for subsec in subsections:
                    subsec_title = subsec.get('title', '')
                    if subsec_title:
                        text_to_translate.append(f"SUBSECTION: {subsec_title}")
                    
                    subsec_content = subsec.get('content', [])
                    if isinstance(subsec_content, list):
                        for subsec_content_item in subsec_content:
                            if isinstance(subsec_content_item, dict) and 'text' in subsec_content_item:
                                subsec_text = subsec_content_item['text']
                                if subsec_text:
                                    text_to_translate.append(f"TEXT: {subsec_text}")
        
        # Limiter la taille du texte (max 4000 caractères pour éviter les timeouts)
        full_text = '\n'.join(text_to_translate)[:4000]
        
        # Préparer le prompt pour Mistral
        prompt = f"""Translate the following French medication information to English. Preserve the structure with labels (TITLE:, SECTION:, TEXT:, etc.).

French text:
{full_text}

Translate all content to English while keeping the same structure and labels."""

        try:
            # Appel à l'API Mistral
            response = self.mistral_client.chat.complete(
                model="mistral-large-latest",
                messages=[
                    {"role": "system", "content": "You are a medical translator specialized in pharmaceutical documentation. Translate French to English accurately, preserving medical terminology."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.2,
                max_tokens=6000
            )
            
            # Extraire la traduction
            translated_text = response.choices[0].message.content.strip()
            
            # Utiliser deepcopy pour éviter de modifier l'original en mémoire et détacher les références
            translated_medicine = copy.deepcopy(medicine_data)
            
            # Reset sections content to empty list to avoid appending to French text
            if 'sections' in translated_medicine:
                for section in translated_medicine['sections']:
                    if 'content' in section and isinstance(section['content'], list):
                        # Réinitialiser le contenu de chaque item
                        for content_item in section['content']:
                            if isinstance(content_item, dict) and 'text' in content_item:
                                content_item['text'] = ''  # On va le remplir avec la traduction
                    if 'subsections' in section:
                        for sub in section['subsections']:
                            if 'content' in sub and isinstance(sub['content'], list):
                                for content_item in sub['content']:
                                    if isinstance(content_item, dict) and 'text' in content_item:
                                        content_item['text'] = ''

            lines = translated_text.split('\n')
            
            current_section = None
            current_subsection = None
            section_index = -1
            subsection_index = -1
            text_index_in_section = 0
            text_index_in_subsection = 0
            
            for line in lines:
                # Nettoyage robuste: enlever markdown (*, **), espaces
                clean_line = line.replace('**', '').replace('*', '').strip()
                if not clean_line:
                    continue
                
                # Détection plus souple des labels
                upper_line = clean_line.upper()
                
                if 'TITLE:' in upper_line and len(clean_line) < 200: # Simple heuristic
                    # Trouver l'index de TITLE:
                    idx = upper_line.find('TITLE:')
                    content = clean_line[idx+6:].strip()
                    if content:
                        translated_medicine['title'] = content
                
                elif 'FORM:' in upper_line:
                    idx = upper_line.find('FORM:')
                    content = clean_line[idx+5:].strip()
                    if 'medicine_details' not in translated_medicine:
                        translated_medicine['medicine_details'] = {}
                    translated_medicine['medicine_details']['forme'] = content
                
                elif 'LABORATORY:' in upper_line:
                    idx = upper_line.find('LABORATORY:')
                    content = clean_line[idx+11:].strip()
                    if 'medicine_details' not in translated_medicine:
                        translated_medicine['medicine_details'] = {}
                    translated_medicine['medicine_details']['laboratoire'] = content
                
                elif 'SUBSECTION:' in upper_line: # Check SUBSECTION before SECTION
                    idx = upper_line.find('SUBSECTION:')
                    content = clean_line[idx+11:].strip()
                    subsection_index += 1
                    text_index_in_subsection = 0  # Reset text index for new subsection
                    if current_section and 'subsections' in current_section and subsection_index < len(current_section['subsections']):
                        current_section['subsections'][subsection_index]['title'] = content
                        current_subsection = current_section['subsections'][subsection_index]
                
                elif 'SECTION:' in upper_line:
                    idx = upper_line.find('SECTION:')
                    content = clean_line[idx+8:].strip()
                    section_index += 1
                    subsection_index = -1
                    text_index_in_section = 0  # Reset text index for new section
                    if 'sections' in translated_medicine and section_index < len(translated_medicine['sections']):
                        translated_medicine['sections'][section_index]['title'] = content
                        current_section = translated_medicine['sections'][section_index]
                        current_subsection = None
                
                elif 'TEXT:' in upper_line:
                    idx = upper_line.find('TEXT:')
                    text_content = clean_line[idx+5:].strip()
                    
                    # Ajouter le texte traduit à la bonne section/sous-section
                    if current_subsection:
                        if 'content' in current_subsection and isinstance(current_subsection['content'], list):
                            if text_index_in_subsection < len(current_subsection['content']):
                                if isinstance(current_subsection['content'][text_index_in_subsection], dict):
                                    current_subsection['content'][text_index_in_subsection]['text'] = text_content
                                text_index_in_subsection += 1
                    elif current_section:
                        if 'content' in current_section and isinstance(current_section['content'], list):
                            if text_index_in_section < len(current_section['content']):
                                if isinstance(current_section['content'][text_index_in_section], dict):
                                    current_section['content'][text_index_in_section]['text'] = text_content
                                text_index_in_section += 1
            
            # Marquer comme traduit
            translated_medicine['original_denomination'] = medicine_data.get('denomination', '') or medicine_data.get('title', '')
            translated_medicine['_translated'] = True
            translated_medicine['_language'] = 'en'
            
            logger.info(f"Médicament COMPLET traduit: {medicine_data.get('title', 'Unknown')}")
            return translated_medicine
            
        except Exception as e:
            logger.error(f"Erreur lors de la traduction complète: {str(e)}")
            # Retourner les données originales en cas d'erreur
            # Retourner les données originales en cas d'erreur
            return medicine_data
    
    def translate_and_cache(self, medicine_data: Dict) -> Optional[Dict]:
        """
        Traduit un médicament et le stocke dans la collection Medecines-EN
        
        Args:
            medicine_data: Dictionnaire du médicament en français (peut contenir 'title' ou 'denomination')
            
        Returns:
            Dictionnaire du médicament traduit ou None si erreur
        """
        medicine_name = medicine_data.get('title') or medicine_data.get('denomination', '')
        if not medicine_name:
            logger.warning("Médicament sans nom")
            return None
            
        # Vérifier si déjà traduit
        cached = self.get_translation(medicine_name)
        if cached:
            logger.info(f"Traduction trouvée en cache: {medicine_name}")
            return cached
        
        # Traduire directement les données fournies
        logger.info(f"Traduction en cours: {medicine_name}")
        translated = self.translate_medicine_data(medicine_data)
        
        # Stocker dans le cache
        try:
            # Retirer l'_id pour éviter les conflits
            if '_id' in translated:
                original_id = translated.pop('_id')
                translated['original_id'] = str(original_id)
            
            self.medicines_en.update_one(
                {'original_denomination': medicine_name},
                {'$set': translated},
                upsert=True
            )
            logger.info(f"Traduction mise en cache: {medicine_name}")
            return translated
            
        except Exception as e:
            logger.error(f"Erreur lors du stockage: {str(e)}")
            return translated
    
    def translate_search_results(self, results: list, lang: str = 'fr') -> list:
        """
        Traduit une liste de résultats de recherche si nécessaire
        
        Args:
            results: Liste de médicaments
            lang: Langue cible ('fr' ou 'en')
            
        Returns:
            Liste de médicaments (traduits si lang='en')
        """
        if lang == 'fr':
            return results
        
        translated_results = []
        for medicine in results:
            medicine_name = medicine.get('denomination', '')
            if not medicine_name:
                translated_results.append(medicine)
                continue
            
            # Traduire et cacher
            translated = self.translate_and_cache(medicine_name)
            if translated:
                translated_results.append(translated)
            else:
                # Fallback sur l'original
                translated_results.append(medicine)
        
        return translated_results
    
    def close(self):
        """Ferme la connexion MongoDB"""
        self.client.close()


# Instance globale (sera initialisée dans app.py)
translator = None


def init_translator(mongo_uri: str, db_name: str, mistral_api_key: str):
    """Initialise l'instance globale du traducteur"""
    global translator
    translator = MedicineTranslator(mongo_uri, db_name, mistral_api_key)
    return translator


def get_translator() -> MedicineTranslator:
    """Récupère l'instance globale du traducteur"""
    global translator
    if translator is None:
        raise RuntimeError("Translator not initialized. Call init_translator first.")
    return translator
