"""
Service d'enrichissement — ZÉRO requêtes directes sur DRUGBANKS au runtime.
Utilise uniquement :
  - medicine_enrichment  (pré-calculé par matching_drugbank.py)
  - dci_lookup           (mini collection DCI → drugbank_id)
  - Interactions déjà stockées dans medicine_enrichment
"""

import hashlib
import os
import re
from typing import Optional, List
from pymongo import MongoClient
from scripts.normalize_shared import normalize_dci


class EnrichmentService:
    """
    Enrichit les médicaments avec DrugBank sans jamais toucher DRUGBANKS.
    Sources :
      - medicine_enrichment (matching batch, 1 document par médicament)
      - dci_lookup         (mapping DCI → drugbank_id pour les non-matchés)
    """

    MIN_CONFIDENCE = 80

    def __init__(self, mongo_uri: str = None, db_name: str = None):
        mongo_uri = mongo_uri or os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
        db_name = db_name or os.getenv('MONGO_DB', 'medicsearch')
        self.client = MongoClient(mongo_uri)
        self.db = self.client[db_name]

    # ════════════════════════════════════════════
    # ENRICHISSEMENT UNITAIRE
    # ════════════════════════════════════════════

    def enrich_medicine(self, medicine: dict) -> dict:
        """
        1. Vérifie medicine_enrichment (pré-calculé)
        2. Si pas de match fiable → fallback DCI via dci_lookup
        3. ZÉRO requête sur DRUGBANKS
        """
        med_id = medicine.get('_id')
        if not med_id:
            return medicine

        # Étape 1 : medicine_enrichment (pré-calculé, O(1) index lookup)
        enrichment = self.db.medicine_enrichment.find_one(
            {'medicine_id': med_id},
        )

        if enrichment:
            conf = enrichment.get('match_confidence', 0)
            if conf >= self.MIN_CONFIDENCE:
                return self._apply_enrichment(medicine, enrichment)

        # Étape 2 : Fallback DCI (extraire la substance du titre, lookup dci_lookup)
        dci_fallback = self._try_dci_fallback(medicine)
        if dci_fallback:
            medicine['drugbank_id'] = dci_fallback['drugbank_id']
            medicine['match_confidence'] = 85
            medicine['match_type'] = 'dci_fallback'
            medicine['match_rule'] = 'dci_from_title'
            medicine['match_score'] = 85
            medicine['match_source'] = 'dci_lookup'
            medicine['matched_on'] = dci_fallback['matched_on']
            medicine['original_fr_matched'] = dci_fallback['original']

            # Enrichissement via drugbank_id lookup (indexé, O(1))
            enriched = self._fetch_enriched_by_db_id(dci_fallback['drugbank_id'])
            if enriched:
                enriched['match_summary'] = (
                    f"DrugBank — {medicine.get('match_type', 'dci_fallback')} "
                    f"(score: 85/100)"
                )
            medicine['enriched'] = enriched
            return medicine

        # Pas de match du tout
        self._clear_match(medicine)
        return medicine

    def _try_dci_fallback(self, medicine: dict) -> Optional[dict]:
        """
        Extrait la DCI du titre et cherche dans dci_lookup.
        Ex: 'ABIRATERONE SANDOZ 500 mg' → DCI 'abiraterone' → lookup
        """
        title = medicine.get('title', '')
        if not title:
            return None

        dci = normalize_dci(title)
        if len(dci) < 4:
            return None

        # Chercher dans dci_lookup (O(1), index _id)
        lookup = self.db.dci_lookup.find_one(
            {'_id': dci},
            {'drugbank_ids': 1},
        )
        if lookup and lookup.get('drugbank_ids'):
            db_id = lookup['drugbank_ids'][0]
            return {
                'drugbank_id': db_id,
                'matched_on': dci,
                'original': title,
            }

        # 2e tentative : premier mot seulement
        first_word = dci.split()[0] if ' ' in dci else dci
        if first_word != dci and len(first_word) >= 4:
            lookup = self.db.dci_lookup.find_one(
                {'_id': first_word},
                {'drugbank_ids': 1},
            )
            if lookup and lookup.get('drugbank_ids'):
                return {
                    'drugbank_id': lookup['drugbank_ids'][0],
                    'matched_on': first_word,
                    'original': title,
                }

        return None

    def _apply_enrichment(self, medicine: dict, enrichment: dict) -> dict:
        """Applique l'enrichissement depuis medicine_enrichment"""
        conf = enrichment.get('match_confidence', 0)
        medicine['drugbank_id'] = enrichment.get('drugbank_ids', [None])[0]
        medicine['match_confidence'] = conf
        medicine['match_type'] = enrichment.get('match_type')
        medicine['match_rule'] = enrichment.get('match_rule')
        medicine['match_score'] = enrichment.get('match_score', conf)
        medicine['match_source'] = enrichment.get('match_source')
        medicine['matched_on'] = enrichment.get('matched_on', '')
        medicine['original_fr_matched'] = enrichment.get('original_fr_matched', '')

        raw = (enrichment.get('enriched', {}) or {})
        if raw:
            medicine['enriched'] = self._format_enriched(raw)
            medicine['enriched']['match_summary'] = (
                f"DrugBank — {medicine.get('match_type', '?')} "
                f"(score: {conf}/100)"
            )
        else:
            medicine['enriched'] = None

        return medicine

    def _fetch_enriched_by_db_id(self, drugbank_id: str) -> Optional[dict]:
        """
        Récupère l'enrichissement via drugbank_id.
        Passe par medicine_enrichment (jamais DRUGBANKS).
        """
        doc = self.db.medicine_enrichment.find_one(
            {'drugbank_ids': drugbank_id, 'enriched': {'$ne': None}},
            {'enriched': 1},
        )
        if doc and doc.get('enriched'):
            return self._format_enriched(doc['enriched'])
        return None

    #: Champs de prose dont la traduction française est pré-calculée par
    #: `scripts/traduire_drugbank.py`. La clé de gauche est celle du
    #: dictionnaire formaté — `_format_enriched` renomme `indication` en
    #: `indication_en` —, celle de droite le nom sous lequel le gabarit
    #: cherche le français.
    CHAMPS_TRADUITS = {
        'mechanism_of_action': 'mechanism_of_action_fr',
        'pharmacodynamics': 'pharmacodynamics_fr',
        'indication_en': 'indication_fr',
        'toxicity': 'toxicity_fr',
    }

    def _joindre_traductions(self, enriched: dict) -> dict:
        """Attache la traduction française des quatre champs de prose.

        La résolution se fait ici, et non en écrivant `<champ>_fr` dans
        `medicine_enrichment`, parce que le bloc DrugBank est produit par deux
        chemins : l'enrichissement pré-calculé et le repli par DCI. Écrire dans
        la collection n'aurait couvert que le premier, et la moitié des fiches
        seraient restées en anglais sans qu'on sache pourquoi.

        Une seule requête, sur un index unique, pour les quatre champs à la
        fois : la traduction n'est jamais calculée à l'affichage, seulement
        retrouvée. Mesuré sous la milliseconde.
        """
        empreintes = {}
        for source, cible in self.CHAMPS_TRADUITS.items():
            valeur = enriched.get(source)
            if isinstance(valeur, str) and valeur.strip():
                empreintes[hashlib.sha1(valeur.encode('utf-8')).hexdigest()] = cible
        if not empreintes:
            return enriched
        try:
            for doc in self.db.traductions_drugbank.find(
                    {'empreinte': {'$in': list(empreintes)}},
                    {'empreinte': 1, 'fr': 1}):
                cible = empreintes.get(doc['empreinte'])
                if cible and doc.get('fr'):
                    enriched[cible] = doc['fr']
        except Exception:
            # Une traduction absente n'est pas une erreur : la fiche affiche
            # l'anglais, signalé comme tel.
            pass
        return enriched

    def _format_enriched(self, raw: dict) -> dict:
        """Formate les données brutes, traduction française jointe.

        Point de passage unique des deux chemins qui produisent le bloc
        DrugBank — l'enrichissement pré-calculé et le repli par DCI. C'est
        pourquoi la traduction est attachée ici : elle couvre les deux.
        """
        return self._joindre_traductions({
            'drugbank_name': raw.get('name'),
            'drugbank_description': raw.get('description'),
            'mechanism_of_action': raw.get('mechanism_of_action'),
            'pharmacodynamics': raw.get('pharmacodynamics'),
            'toxicity': raw.get('toxicity'),
            'half_life': raw.get('half_life'),
            'protein_binding': raw.get('protein_binding'),
            'metabolism': raw.get('metabolism'),
            'absorption': raw.get('absorption'),
            'route_of_elimination': raw.get('route_of_elimination'),
            'clearance': raw.get('clearance'),
            'indication_en': raw.get('indication'),
            'classification': raw.get('classification'),
            'groups': raw.get('groups', []),
            'atc_codes': raw.get('atc_codes', []),
            'synonyms_en': raw.get('synonyms', []),
            'products': raw.get('products', []),
            'external_ids': raw.get('external_identifiers', {}),
            'interactions': raw.get('interactions', []) or [],
        })

    def _clear_match(self, medicine: dict):
        medicine['drugbank_id'] = None
        medicine['match_confidence'] = 0
        medicine['match_type'] = None
        medicine['match_rule'] = None
        medicine['match_score'] = 0
        medicine['match_source'] = None
        medicine['matched_on'] = None
        medicine['original_fr_matched'] = None
        medicine['enriched'] = None

    # ════════════════════════════════════════════
    # BATCH
    # ════════════════════════════════════════════

    def enrich_many(self, medicines: List[dict]) -> List[dict]:
        return [self.enrich_medicine(m) for m in medicines]

    # ════════════════════════════════════════════
    # RECHERCHE (jamais sur DRUGBANKS)
    # ════════════════════════════════════════════

    def search(self, query: str, limit: int = 20) -> List[dict]:
        regex = re.compile(re.escape(query), re.IGNORECASE)
        results = list(self.db.medicines.find(
            {'$or': [
                {'title': regex},
                {'composition': regex},
                {'indications': regex},
            ]},
        ).limit(limit))
        return self.enrich_many(results)

    def get_enriched_by_id(self, medicine_id) -> Optional[dict]:
        med = self.db.medicines.find_one({'_id': medicine_id})
        if not med:
            return None
        return self.enrich_medicine(med)

    # ════════════════════════════════════════════
    # INTERACTIONS (pré-agrégées dans medicine_enrichment)
    # ════════════════════════════════════════════

    def get_interactions(self, medicine_id) -> List[dict]:
        """Retourne les interactions DrugBank pré-agrégées (pas de requête DRUGBANKS)"""
        enrich = self.db.medicine_enrichment.find_one(
            {'medicine_id': medicine_id},
            {'enriched.interactions': 1},
        )
        if not enrich:
            return []
        return (enrich.get('enriched', {}) or {}).get('interactions', []) or []

    def get_common_interactions(self, med_a_id, med_b_id) -> List[dict]:
        """Interactions entre 2 médicaments, via données pré-agrégées"""
        enrich_a = self.db.medicine_enrichment.find_one(
            {'medicine_id': med_a_id},
            {'enriched.interactions': 1, 'drugbank_ids': 1},
        )
        enrich_b = self.db.medicine_enrichment.find_one(
            {'medicine_id': med_b_id},
            {'drugbank_ids': 1},
        )
        if not enrich_a or not enrich_b:
            return []

        db_ids_b = set(enrich_b.get('drugbank_ids', []))
        inter_a = (enrich_a.get('enriched', {}) or {}).get('interactions', []) or []
        return [i for i in inter_a if i.get('drugbank_id') in db_ids_b]

    # ════════════════════════════════════════════
    # STATISTIQUES
    # ════════════════════════════════════════════

    def get_stats(self) -> dict:
        total = self.db.medicines.count_documents({})
        enriched = self.db.medicine_enrichment.count_documents({
            'match_confidence': {'$gte': self.MIN_CONFIDENCE},
        })
        with_dci_fallback = self.db.medicines.count_documents({
            'match_type': 'dci_fallback',
        }) if False else 0  # Serait mis à jour après enrichissement

        by_type = list(self.db.medicine_enrichment.aggregate([
            {'$match': {'match_confidence': {'$gte': self.MIN_CONFIDENCE}}},
            {'$group': {'_id': '$match_type', 'count': {'$sum': 1}}},
        ]))

        return {
            'total_medicines': total,
            'enriched': enriched + 1 if False else enriched,
            'enrichment_rate': round(enriched / total * 100, 1) if total else 0,
            'threshold': self.MIN_CONFIDENCE,
            'by_type': {t['_id']: t['count'] for t in by_type},
            'not_enriched': total - enriched,
        }

    def close(self):
        self.client.close()
