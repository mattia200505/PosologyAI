"""
Script pour traduire TOUS les médicaments de la collection 'medicines' (FR)
vers la collection 'medicines_en' (EN) via Mistral AI.

VERSION OPTIMISÉE — BATCH :
  Au lieu d'un appel API par cellule/texte (~500/médicament), on regroupe
  les textes en paquets de ~30 et on les traduit en un seul appel.
  → ~15-25 appels API par médicament au lieu de 500
  → Temps estimé : ~3-4 jours au lieu de 60+

- Vérifie les doublons (original_id / original_name / original_denomination)
- Traduit tout : titres, sections, tableaux, sous-sections, résumés IA
- Rate-limiting intégré + retry exponentiel sur erreurs 429
- Reprend automatiquement là où il s'est arrêté (skip des déjà traduits)
"""
import os
import sys
import time
import re
import json
import copy
from typing import Dict, List, Any, Optional, Tuple
from pymongo import MongoClient
from bson.objectid import ObjectId
from mistralai.client import Mistral
from dotenv import load_dotenv

load_dotenv()

# ─── Configuration ──────────────────────────────────────────────────────
MONGO_URI = os.getenv('MONGO_URI', 'mongodb://localhost:27017')
MISTRAL_API_KEY = os.getenv('MISTRAL_API_KEY')
DB_NAME = 'medicsearch'
SOURCE_COLLECTION = 'medicines'
TARGET_COLLECTION = 'medicines_en'

# Batch : nombre max de textes par appel API
BATCH_SIZE = 30          # Nombre de textes regroupés en 1 appel

# Délais (secondes)
DELAY_BETWEEN_API_CALLS = 0.5     # Entre chaque appel batch
DELAY_BETWEEN_MEDICINES = 1       # Entre chaque médicament
MAX_RETRIES = 5                   # Nombre de retries sur erreur 429
# ────────────────────────────────────────────────────────────────────────

SEPARATOR = "|||"  # Séparateur interne entre textes dans un batch


class BatchTranslator:
    """Traduit en masse tous les médicaments FR → EN avec appels API groupés."""

    def __init__(self):
        self.mongo = MongoClient(MONGO_URI)
        self.db = self.mongo[DB_NAME]
        self.medicines_fr = self.db[SOURCE_COLLECTION]
        self.medicines_en = self.db[TARGET_COLLECTION]

        if not MISTRAL_API_KEY:
            raise ValueError("MISTRAL_API_KEY non définie dans le .env")

        self.mistral = Mistral(api_key=MISTRAL_API_KEY)
        self.model = "mistral-small-latest"
        self.api_calls = 0
        self.current_med_calls = 0

    # ── vérification doublon ─────────────────────────────────────────────

    def _already_translated(self, medicine: Dict) -> bool:
        med_id = medicine.get('_id')
        med_title = medicine.get('title', '')

        if med_id and self.medicines_en.find_one({'original_id': med_id}):
            return True
        if med_id and self.medicines_en.find_one({'original_id': str(med_id)}):
            return True
        if med_title and self.medicines_en.find_one({'original_name': med_title}):
            return True
        if med_title and self.medicines_en.find_one({'original_denomination': med_title}):
            return True
        return False

    # ── appel API batch ──────────────────────────────────────────────────

    def _call_mistral_batch(self, texts: List[str]) -> List[str]:
        """
        Envoie un batch de textes à Mistral en un seul appel.
        Les textes sont numérotés [1], [2], … et le modèle retourne
        les traductions numérotées de la même manière.
        """
        if not texts:
            return []

        # Construire le prompt avec numérotation
        numbered_lines = []
        for i, t in enumerate(texts, 1):
            numbered_lines.append(f"[{i}] {t}")
        joined = "\n".join(numbered_lines)

        prompt = (
            f"Translate each numbered French medical text below to English.\n"
            f"RULES:\n"
            f"- Keep ALL HTML tags (<p>, <strong>, <em>, <table>, <tr>, <td>, etc.) EXACTLY as they are\n"
            f"- Keep medication names, chemical/scientific names, dosages, numbers and abbreviations UNCHANGED\n"
            f"- Translate ONLY the French descriptive text\n"
            f"- Return ONLY the numbered translations in the EXACT SAME format: [1] translation\\n[2] translation\\n…\n"
            f"- Do NOT add any explanation, comment, or extra text\n"
            f"- You MUST return exactly {len(texts)} numbered lines\n\n"
            f"{joined}"
        )

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                self.api_calls += 1
                self.current_med_calls += 1

                response = self.mistral.chat.complete(
                    model=self.model,
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "You are a medical translator. You translate French pharmaceutical "
                                "documentation to English. You preserve HTML tags, medication names, "
                                "chemical names, dosages and numbers exactly as they are. "
                                "You return ONLY numbered translations, nothing else."
                            ),
                        },
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.1,
                    max_tokens=min(len(joined) * 3, 16000),
                )

                raw = response.choices[0].message.content.strip()
                time.sleep(DELAY_BETWEEN_API_CALLS)

                # Parser les traductions numérotées
                return self._parse_numbered_response(raw, len(texts), texts)

            except Exception as e:
                err_str = str(e)
                if "429" in err_str or "rate" in err_str.lower():
                    wait = 2 ** attempt  # Backoff exponentiel : 2, 4, 8, 16, 32s
                    print(f"        [429] Rate limit, retry {attempt}/{MAX_RETRIES} dans {wait}s…")
                    time.sleep(wait)
                else:
                    print(f"        [ERREUR API] {e}")
                    time.sleep(2)
                    break

        # Fallback : retourner les originaux
        return list(texts)

    def _parse_numbered_response(self, raw: str, expected: int, originals: List[str]) -> List[str]:
        """Parse la réponse numérotée [1] … [2] … en liste ordonnée."""
        results = [None] * expected

        # Regex pour capturer [N] suivi du texte
        pattern = re.compile(r'\[(\d+)\]\s*(.*?)(?=\n\[\d+\]|\Z)', re.DOTALL)
        matches = pattern.findall(raw)

        for num_str, text in matches:
            idx = int(num_str) - 1
            if 0 <= idx < expected:
                results[idx] = text.strip()

        # Remplir les trous avec les originaux
        for i in range(expected):
            if results[i] is None or results[i] == '':
                results[i] = originals[i]

        return results

    # ── extraction de tous les textes d'un médicament ────────────────────

    def _extract_texts(self, medicine: Dict) -> Tuple[List[str], List[Tuple]]:
        """
        Parcourt la structure du médicament et extrait tous les textes
        à traduire avec leur chemin (pour les réinjecter ensuite).

        Retourne:
            texts: liste de textes bruts
            paths: liste de tuples (chemin, clé) pour savoir où réinjecter
        """
        texts = []
        paths = []

        def _add(text, path_tuple):
            if text and isinstance(text, str) and len(text.strip()) >= 2:
                # Ne pas traduire les nombres purs
                s = text.strip().replace('.', '').replace(',', '').replace(' ', '')
                if not s.isdigit():
                    texts.append(text)
                    paths.append(path_tuple)

        # Titre
        _add(medicine.get('title'), ('title',))

        # Métadonnées
        for field in ('type_medicament', 'famille_therapeutique', 'groupe_anatomique'):
            _add(medicine.get(field), (field,))

        # medicine_details.forme
        md = medicine.get('medicine_details')
        if md and isinstance(md, dict):
            _add(md.get('forme'), ('medicine_details', 'forme'))

        # Résumé IA
        _add(medicine.get('ai_summary'), ('ai_summary',))

        # Sections
        for si, section in enumerate(medicine.get('sections') or []):
            _add(section.get('title'), ('sections', si, 'title'))

            # Contenu direct de la section
            for ci, item in enumerate(section.get('content') or []):
                if isinstance(item, dict):
                    _add(item.get('text'), ('sections', si, 'content', ci, 'text'))
                    _add(item.get('html_content'), ('sections', si, 'content', ci, 'html_content'))

                    # Tableaux
                    if isinstance(item.get('table'), list):
                        for ri, row in enumerate(item['table']):
                            for ci2, cell in enumerate(row):
                                if isinstance(cell, str):
                                    _add(cell, ('sections', si, 'content', ci, 'table', ri, ci2))
                    if isinstance(item.get('headers'), list):
                        for hi, h in enumerate(item['headers']):
                            if isinstance(h, str):
                                _add(h, ('sections', si, 'content', ci, 'headers', hi))
                    _add(item.get('caption'), ('sections', si, 'content', ci, 'caption'))

                elif isinstance(item, str):
                    _add(item, ('sections', si, 'content', ci))

            # Sous-sections
            for ssi, subsec in enumerate(section.get('subsections') or []):
                _add(subsec.get('title'), ('sections', si, 'subsections', ssi, 'title'))

                for ci, item in enumerate(subsec.get('content') or []):
                    if isinstance(item, dict):
                        _add(item.get('text'), ('sections', si, 'subsections', ssi, 'content', ci, 'text'))
                        _add(item.get('html_content'), ('sections', si, 'subsections', ssi, 'content', ci, 'html_content'))

                        if isinstance(item.get('table'), list):
                            for ri, row in enumerate(item['table']):
                                for ci2, cell in enumerate(row):
                                    if isinstance(cell, str):
                                        _add(cell, ('sections', si, 'subsections', ssi, 'content', ci, 'table', ri, ci2))
                        if isinstance(item.get('headers'), list):
                            for hi, h in enumerate(item['headers']):
                                if isinstance(h, str):
                                    _add(h, ('sections', si, 'subsections', ssi, 'content', ci, 'headers', hi))
                        _add(item.get('caption'), ('sections', si, 'subsections', ssi, 'content', ci, 'caption'))

                    elif isinstance(item, str):
                        _add(item, ('sections', si, 'subsections', ssi, 'content', ci))

        return texts, paths

    def _inject_translations(self, medicine: Dict, paths: List[Tuple], translations: List[str]) -> Dict:
        """Réinjecte les traductions dans une copie profonde du médicament."""
        translated = copy.deepcopy(medicine)

        for path, text in zip(paths, translations):
            obj = translated
            for i, key in enumerate(path[:-1]):
                if isinstance(obj, dict):
                    obj = obj[key]
                elif isinstance(obj, list):
                    obj = obj[key]

            last_key = path[-1]
            if isinstance(obj, dict):
                obj[last_key] = text
            elif isinstance(obj, list):
                obj[last_key] = text

        return translated

    # ── traduction complète d'un médicament (batch) ──────────────────────

    def translate_medicine(self, medicine: Dict) -> Dict:
        """Traduit intégralement un médicament avec des appels API groupés."""
        self.current_med_calls = 0

        # 1) Extraire tous les textes + chemins
        texts, paths = self._extract_texts(medicine)
        total_texts = len(texts)

        if total_texts == 0:
            translated = copy.deepcopy(medicine)
            translated['language'] = 'en'
            translated['original_id'] = medicine['_id']
            translated['original_name'] = medicine.get('title', '')
            return translated

        # 2) Traduire par batches
        all_translations = []
        for batch_start in range(0, total_texts, BATCH_SIZE):
            batch_end = min(batch_start + BATCH_SIZE, total_texts)
            batch_texts = texts[batch_start:batch_end]
            batch_translations = self._call_mistral_batch(batch_texts)
            all_translations.extend(batch_translations)

        # 3) Réinjecter les traductions
        translated = self._inject_translations(medicine, paths, all_translations)

        # 4) Marqueurs
        translated['language'] = 'en'
        translated['original_id'] = medicine['_id']
        translated['original_name'] = medicine.get('title', '')

        print(f"    {total_texts} textes traduits en {self.current_med_calls} appels API")
        return translated

    # ── sauvegarde ───────────────────────────────────────────────────────

    def save_translated(self, translated: Dict, original_id) -> bool:
        try:
            if '_id' in translated:
                del translated['_id']

            self.medicines_en.update_one(
                {'original_id': original_id},
                {'$set': translated},
                upsert=True,
            )
            return True
        except Exception as e:
            print(f"    [ERREUR SAVE] {e}")
            return False

    # ── boucle principale ────────────────────────────────────────────────

    def run(self):
        total_fr = self.medicines_fr.count_documents({})
        already_en = self.medicines_en.count_documents({})
        print("=" * 70)
        print(f"  TRADUCTION BATCH  —  medicines → medicines_en")
        print(f"  Médicaments FR : {total_fr}")
        print(f"  Déjà traduits  : {already_en}")
        print(f"  Batch size     : {BATCH_SIZE} textes/appel")
        print("=" * 70)

        start_time = time.time()
        translated_count = 0
        skipped_count = 0
        error_count = 0

        # Charger tous les _id en mémoire pour éviter le timeout du curseur MongoDB
        print("  Chargement des IDs…")
        all_ids = [doc['_id'] for doc in self.medicines_fr.find({}, {'_id': 1})]
        print(f"  {len(all_ids)} IDs chargés.\n")

        for idx, med_id in enumerate(all_ids, start=1):
            try:
                # Charger le document complet un par un (pas de curseur longue durée)
                medicine = self.medicines_fr.find_one({'_id': med_id})
                if not medicine:
                    continue

                title = medicine.get('title', '???')
                short = title[:55] + "…" if len(title) > 55 else title

                # ── vérification doublon ─────────────────────────
                if self._already_translated(medicine):
                    skipped_count += 1
                    if skipped_count % 100 == 0:
                        print(f"  [{idx}/{total_fr}] ⏭️  {skipped_count} déjà traduits ignorés")
                    continue

                print(f"\n  [{idx}/{total_fr}] {short}")

                translated = self.translate_medicine(medicine)
                if self.save_translated(translated, medicine['_id']):
                    translated_count += 1
                    print(f"    ✅ OK")
                else:
                    error_count += 1

            except KeyboardInterrupt:
                print("\n\n  ⛔ Interruption manuelle (Ctrl+C)")
                break
            except Exception as e:
                error_count += 1
                print(f"    ❌ [{type(e).__name__}] {e}")
                # Attendre un peu et continuer au suivant — ne JAMAIS crash
                time.sleep(5)
                # Reconnecter Mongo au cas où la connexion est morte
                try:
                    self.mongo.admin.command('ping')
                except Exception:
                    print("    🔄 Reconnexion MongoDB…")
                    try:
                        self.mongo = MongoClient(MONGO_URI)
                        self.db = self.mongo[DB_NAME]
                        self.medicines_fr = self.db[SOURCE_COLLECTION]
                        self.medicines_en = self.db[TARGET_COLLECTION]
                        print("    ✅ Reconnecté")
                    except Exception as re_err:
                        print(f"    ❌ Reconnexion échouée: {re_err}, pause 30s…")
                        time.sleep(30)
                continue

            time.sleep(DELAY_BETWEEN_MEDICINES)

            # Résumé toutes les 50 traductions
            if translated_count > 0 and translated_count % 50 == 0:
                elapsed = time.time() - start_time
                rate = translated_count / (elapsed / 3600)
                remaining = (total_fr - idx) / rate if rate > 0 else 0
                print(f"\n  ── {translated_count} traduits | {skipped_count} ignorés | "
                      f"{error_count} err | {self.api_calls} appels API | "
                      f"~{rate:.0f}/h | reste ~{remaining:.1f}h ──\n")

        # ── résumé final ─────────────────────────────────────
        elapsed = time.time() - start_time
        hours = elapsed / 3600
        print("\n" + "=" * 70)
        print(f"  TERMINÉ en {hours:.1f}h")
        print(f"  Traduits   : {translated_count}")
        print(f"  Ignorés    : {skipped_count}")
        print(f"  Erreurs    : {error_count}")
        print(f"  Appels API : {self.api_calls}")
        print(f"  Total EN   : {self.medicines_en.count_documents({})}")
        print("=" * 70)


if __name__ == "__main__":
    translator = BatchTranslator()
    translator.run()
