"""
Module d'aide à la prescription
Analyse les symptômes, suggère des médicaments et vérifie les interactions
"""

from flask import Blueprint, request, jsonify, render_template, current_app
from pymongo import MongoClient
from qdrant_client import QdrantClient
from sentence_transformers import SentenceTransformer
from mistralai import Mistral
import os
import re
import unicodedata
# Traduction des énoncés d'interaction, par trames françaises écrites d'avance
# plutôt que par traduction automatique : les noms de substance n'y sont jamais
# touchés.
import interaction_i18n
from urllib.parse import quote
from bson import ObjectId
from dotenv import load_dotenv
import logging

logger = logging.getLogger(__name__)
load_dotenv(override=True)

# Configuration Mistral AI
MISTRAL_API_KEY = os.getenv('MISTRAL_API_KEY')
if MISTRAL_API_KEY:
    logger.info(f"MISTRAL_API_KEY chargée ({MISTRAL_API_KEY[:4]}...{MISTRAL_API_KEY[-4:]})")
else:
    logger.warning("MISTRAL_API_KEY non trouvée dans .env")

# Configuration
MONGO_URI = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
MONGO_DB = os.getenv('MONGO_DB', 'medicsearch')
QDRANT_HOST = os.getenv('QDRANT_HOST', '127.0.0.1')
QDRANT_PORT = int(os.getenv('QDRANT_PORT', 6333))

# Clients
mongo_client = MongoClient(MONGO_URI)
db = mongo_client[MONGO_DB]
qdrant_client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT, timeout=5)
# embedding_model = SentenceTransformer('all-MiniLM-L6-v2')  # Commenté - utilise celui de app.py
embedding_model = None  # Sera importé de app.py

#: Modele employe pour l'hypothese clinique. Nomme ici plutot qu'enfoui dans
#: l'appel : l'ecran l'affiche, et un lecteur doit pouvoir savoir ce qui a
#: ecrit le texte qu'il lit.
MODELE_DIAGNOSTIC = 'mistral-small-2503'

#: Les mesures que les deux formulaires proposent, toutes facultatives.
#: Nommées ici pour que les routes et les gabarits emploient les mêmes clés :
#: c'est la liste qui fait foi.
#:
#: Les quatre dernières sont des constantes, non des résultats de laboratoire.
#: Elles ont été ajoutées après un essai où le moteur proposait des
#: antihypertenseurs à un patient dont la pression était à 96/58, et du
#: vérapamil à une fraction d'éjection de 30 %. Les deux valeurs avaient bien
#: été saisies — dans le texte libre, que **aucune règle ne lit**. Une donnée
#: qu'aucune règle ne peut lire ne protège de rien.
MESURES_BIOLOGIQUES = ('dfg', 'kaliemie', 'natremie', 'transaminases',
                       'systolique', 'diastolique', 'frequence_cardiaque',
                       'fevg')

prescription_bp = Blueprint('prescription', __name__, url_prefix='/api/prescription')


@prescription_bp.route('/assistant')
def prescription_assistant():
    """Page d'interface de l'aide à la prescription"""
    return render_template('prescription_assistant.html')


@prescription_bp.route('/analyze', methods=['POST'])
def analyze_patient():
    """
    Analyse les symptômes du patient et suggère des médicaments
    avec vérification des interactions
    """
    try:
        data = request.json
        
        # Extraction des données patient
        symptomes = data.get('symptomes', '')
        # Le découpage ne connaissait que la virgule. « Ventoline en
        # inhalation si besoin. Cétirizine 10 mg pendant les périodes
        # allergiques. » devenait donc **un seul** traitement, et aucun des
        # deux n'était reconnu.
        medicaments_actuels = decouper_traitements(data.get('medicaments_actuels'))
        antecedents = data.get('antecedents', '')
        try:
            age = int(data.get('age', 0))
        except (ValueError, TypeError):
            age = 0
        language = data.get('language', 'fr')  # Langue (fr ou en)
        # Résultats biologiques, tous facultatifs. Un antécédent est un mot,
        # un résultat est un nombre : « maladie rénale chronique » ne dit pas
        # si la metformine est déconseillée ou interdite, un DFG à 28 le dit.
        # Laissés vides, ils ne déclenchent rien.
        mesures = {cle: data.get(cle) for cle in MESURES_BIOLOGIQUES}
        
        logger.info(f"Analyse pour patient: {data.get('nom')} {data.get('prenom')}, Symptômes: {symptomes}, Langue: {language}")
        
        # 1. Première passe : des candidats, pour que le modèle ait des RCP à
        #    lire. Ils ne seront pas proposés tels quels ; ils servent de
        #    contexte à l'hypothèse (§ 2.6).
        candidats_contexte = search_medications_by_symptoms(symptomes, limit=5)

        # 2. **Le diagnostic d'abord.** Il naissait en dernier, après que les
        #    médicaments avaient été cherchés, notés, filtrés et composés sur
        #    les seuls symptômes : il ne pouvait pas les informer.
        #
        #    Mesuré : sur dyspnée, œdèmes et prise de poids, le modèle posait
        #    « Insuffisance cardiaque aiguë décompensée » et l'écran proposait
        #    salbutamol et budésonide, « retenu pour : Asthme ». Le mot
        #    *dyspnée* avait déclenché la conduite « asthme » du repli.
        diagnostic = generate_diagnostic(
            symptomes, antecedents, candidats_contexte, language=language)

        # 3. Le tableau clinique : le diagnostic devant, les symptômes derrière.
        #    C'est lui, désormais, qui pilote toute la sélection.
        tableau = tableau_clinique(symptomes, diagnostic)
        logger.info("Tableau retenu pour la selection : %s", tableau[:110])

        # 4. Seconde passe, sur le tableau. Les candidats appelés par la classe
        #    du diagnostic passent devant ceux que la similarité de texte
        #    remonte — c'est ce que la chaîne par diagnostic fait depuis P3b.
        medications_suggested = search_medications_by_symptoms(tableau, limit=5)
        attendues = classes_atc_attendues(tableau)
        if attendues:
            par_classe = candidats_par_classe(attendues)
            deja = {(m.get('title') or '') for m in medications_suggested}
            medications_suggested = [m for m in par_classe
                                     if m['title'] not in deja] + medications_suggested
            logger.info("Classes attendues %s : %d candidat(s) generes",
                        sorted(attendues), len(par_classe))

        # 5. Score de pertinence clinique, sur le tableau.
        #
        # L'indication réelle est relevée juste avant : c'est elle qui décide
        # si un candidat découvert par sa classe ATC mérite ses points. Elle
        # doit donc être là **avant** cette boucle — c'est ici que la note se
        # fige pour l'assistant, `appliquer_controles` ne renotant que ce qui
        # arrive sans note.
        attacher_indications(medications_suggested)

        scored_medications = []
        for med in medications_suggested:
            try:
                score, justification = compute_clinical_relevance(tableau, med)
            except Exception as e:
                logger.warning(f"Erreur scoring pour {med.get('title', '?')}: {e}")
                score, justification = 0, "Erreur d'évaluation"
            med['relevance_score'] = score
            med['justification'] = justification
            scored_medications.append(med)
        
        # Le tri seul. Le seuil qui se trouvait ici — garder les ≥ 70, et à
        # défaut les ≥ 50 — est retiré.
        #
        # Il précédait le recrutement par classe et ne pouvait pas le voir.
        # `compute_clinical_relevance` plafonne à 60 un candidat retenu pour sa
        # classe ATC : il ne franchit jamais 70. Il suffisait donc qu'une seule
        # remontée vectorielle atteigne 70 pour que la branche `high_conf`
        # l'emporte et que **tout** le recrutement piloté par le diagnostic
        # disparaisse, en silence, avant le moindre contrôle.
        #
        # Mesuré sur une lombalgie chez une insuffisante rénale : les six AINS
        # appelés par le diagnostic étaient supprimés ici, et l'écran ne
        # proposait que les antalgiques remontés par similarité de texte. La
        # contrainte rénale n'avait jamais eu l'occasion de les écarter, ni
        # l'écran de le dire.
        #
        # Un seul seuil subsiste désormais, celui d'`appliquer_controles`, qui
        # range ce qu'il retire dans `medicaments_ecartes` avec son motif. Le
        # bruit vectoriel, noté 0, y tombe aussi — mais nommé.
        filtered = sorted(scored_medications,
                          key=lambda m: m['relevance_score'], reverse=True)
        logger.info("Vivier note : %d candidat(s), aucun retire sans motif",
                    len(filtered))
        
        # 4. Vérification des contre-indications (âge, antécédents)
        filtered_medications = filter_contraindications(
            filtered, 
            age=age, 
            antecedents=antecedents
        )
        
        # 5. Fallback médical si aucun médicament retenu
        if not filtered_medications:
            logger.info("[FALLBACK] Aucun médicament retenu, utilisation du fallback clinique")
            # Le repli lit le tableau, pas les seuls symptômes : ses treize
            # conduites reconnaissent « insuffisance cardiaque » aussi bien
            # que « dyspnée », et c'est la première qui doit l'emporter.
            fallback = get_clinical_fallback(tableau)
            # Convertir en format attendu
            for fb in fallback:
                fb['id'] = fb.get('name', '').lower().replace(' ', '-')
                if 'posologie' not in fb and 'posology' in fb:
                    fb['posologie'] = fb.get('posology', 'Selon prescription médicale')
                if 'posology' in fb:
                    fb['posologie'] = fb.pop('posology')
            # Le repli passe par le même filtre que le reste : il en sortait
            # auparavant sans aucun contrôle.
            filtered_medications = filter_contraindications(
                fallback, age=age, antecedents=antecedents)

        # 5 bis à 6. Forme unique, contraintes, contre-indications et
        # interactions — le même enchaînement que la prescription par
        # diagnostic emploie désormais.
        # Le `contexte` réveille sur cet écran tout ce que la chaîne par
        # diagnostic emploie déjà : notation par classe ATC, filtre par classe
        # attendue, seuil d'exclusion et composition en première intention,
        # alternatives et adjuvants. Il était absent, et cette machinerie
        # restait inactive sur l'assistant.
        controles = appliquer_controles(
            filtered_medications, antecedents=antecedents,
            traitements_en_cours=medicaments_actuels, age=age,
            contexte=tableau, mesures=mesures)
        filtered_medications = controles['medications']

        # 8. Recommandations
        recommendations = generate_recommendations(
            filtered_medications, controles['interactions'], language=language)

        return jsonify(dict(controles, **{
            'success': True,
            'diagnostic': diagnostic,
            'recommendations': recommendations,
            # Le champ `provenance` est retiré. Son panneau avait quitté
            # l'écran en `c737fe3` ; le champ lui a survécu dans la réponse
            # sans que personne ne le lise. Une donnée que plus aucun écran ne
            # demande finit par être crue à jour alors qu'elle ne l'est plus.
            #
            # Le recours au repli reste au journal, à l'étape 5, où il sert au
            # diagnostic d'exploitation.
        }))
        
    except Exception as e:
        logger.error(f"Erreur lors de l'analyse: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


# Mapping symptômes -> classes thérapeutiques / substances cibles
SYMPTOM_CLASS_MAP = {
    'fièvre': ['paracétamol', 'ibuprofène', 'aspirine', 'antipyrétique', 'antalgique', 'anti-inflammatoire non stéroïdien', 'ains'],
    'fievre': ['paracétamol', 'ibuprofène', 'aspirine', 'antipyrétique', 'antalgique', 'anti-inflammatoire non stéroïdien', 'ains'],
    'douleur': ['paracétamol', 'ibuprofène', 'antalgique', 'anti-inflammatoire', 'tramadol', 'codéine', 'morphine'],
    'toux': ['sirop', 'antitussif', 'expectorant', 'bronchodilatateur', 'dextrométhorphane'],
    'maux de tête': ['paracétamol', 'ibuprofène', 'antalgique', 'triptan', 'sumatriptan'],
    'céphalée': ['paracétamol', 'ibuprofène', 'antalgique', 'triptan', 'sumatriptan'],
    'céphalées': ['paracétamol', 'ibuprofène', 'antalgique', 'triptan', 'sumatriptan'],
    'migraine': ['triptan', 'sumatriptan', 'ibuprofène', 'paracétamol'],
    'nausée': ['dompéridone', 'métoclopramide', 'antiémétique', 'primperan'],
    'nausées': ['dompéridone', 'métoclopramide', 'antiémétique', 'primperan'],
    'vomissement': ['dompéridone', 'métoclopramide', 'antiémétique', 'primperan'],
    'vomissements': ['dompéridone', 'métoclopramide', 'antiémétique', 'primperan'],
    'diarrhée': ['lopéramide', 'smectite', 'racécadotril', 'antidiarrhéique'],
    'infection': ['antibiotique', 'amoxicilline', 'antiviral', 'antifongique'],
    'grippe': ['paracétamol', 'antiviral', 'oseltamivir'],
    'rhume': ['paracétamol', 'décongestionnant', 'antihistaminique'],
    'allergie': ['antihistaminique', 'cétirizine', 'loratadine', 'desloratadine'],
    'anxiété': ['anxiolytique', 'benzodiazépine', 'hydroxyzine'],
    'insomnie': ['hypnotique', 'zolpidem', 'mélatonine'],
    'hypertension': ['antihypertenseur', 'inhibiteur calcique', 'iec', 'sartan', 'diurétique'],
    'diabète': ['antidiabétique', 'metformine', 'insuline'],
    'asthme': ['bronchodilatateur', 'corticoïde inhalé', 'bêta-2 agoniste', 'salbutamol'],
    'dyspnée': ['bronchodilatateur', 'corticoïde inhalé', 'bêta-2 agoniste', 'salbutamol'],
    'essoufflement': ['bronchodilatateur', 'corticoïde inhalé', 'bêta-2 agoniste', 'salbutamol'],
    'constipation': ['laxatif', 'macrogol', 'dulcolax', 'forlax'],
    'brûlure': ['antiacide', 'inhibiteur pompe à protons', 'oméprazole', 'ésoméprazole'],
    'reflux': ['antiacide', 'inhibiteur pompe à protons', 'oméprazole', 'ésoméprazole'],
    # Ajoutés avec le durcissement de la notation. Le bonus de marque n'est
    # plus accordé qu'aux catégories que les symptômes appellent : sans ces
    # entrées, `antispasmodique`, `antiseptique` et `veinotonique` n'étaient
    # appelées par aucun symptôme, et SPASFON, STREPSILS ou DAFLON ne
    # pouvaient plus jamais être proposés. Ils l'étaient auparavant pour
    # n'importe quel symptôme, ce qui n'était pas mieux.
    'spasme': ['antispasmodique', 'phloroglucinol', 'trimébutine'],
    'colique': ['antispasmodique', 'phloroglucinol', 'trimébutine'],
    'crampe': ['antispasmodique', 'phloroglucinol'],
    'douleur abdominale': ['antispasmodique', 'phloroglucinol', 'antalgique'],
    'mal de gorge': ['antiseptique', 'antalgique', 'paracétamol'],
    'angine': ['antiseptique', 'antalgique', 'antibiotique', 'amoxicilline'],
    'jambes lourdes': ['veinotonique', 'diosmine'],
    'hémorroïde': ['veinotonique', 'diosmine'],
    'insuffisance veineuse': ['veinotonique', 'diosmine'],
}

#: Catégories de `BRAND_MAP` qu'aucun symptôme n'appelle, **délibérément**.
#:
#: Ces traitements ne répondent pas à un symptôme : un antiagrégant se prescrit
#: en prévention d'un événement cardiovasculaire, un hypocholestérolémiant
#: corrige un dosage biologique. Ni l'un ni l'autre ne se déduit de ce que le
#: patient ressent, et les proposer à partir de symptômes serait une erreur de
#: raisonnement, pas un manque de couverture.
#:
#: Nommées ici pour que leur absence soit un choix lisible plutôt qu'un oubli.
CATEGORIES_NON_SYMPTOMATIQUES = {'antiagrégant', 'hypocholestérolémiant'}

# Catégories médicamenteuses à exclure (hors contexte, compléments, homéopathie)
EXCLUDED_CATEGORIES = [
    'homéopathique', 'homeopathique', 'homéopathie', 'homeopathie',
    'complément', 'complement', 'vitamine', 'minéral', 'mineral',
    'tisane', 'infusion', 'huile essentielle', 'aromatherapie',
    'produit de beauté', 'cosmétique', 'cosmetique',
    'complément alimentaire', 'complement alimentaire',
]

# Noms de spécialités courantes → classes thérapeutiques
BRAND_MAP = {
    'doliprane': 'antalgique', 'efferalgan': 'antalgique', 'dafalgan': 'antalgique',
    'ibuprofène': 'anti-inflammatoire', 'ibuprofene': 'anti-inflammatoire', 'advil': 'anti-inflammatoire', 'nurofen': 'anti-inflammatoire',
    'spasfon': 'antispasmodique',
    'mopral': 'antiacide', 'inexium': 'antiacide', 'omeprazole': 'antiacide',
    'clamoxyl': 'antibiotique', 'amoxicilline': 'antibiotique', 'augmentin': 'antibiotique',
    'ventoline': 'bronchodilatateur', 'salbutamol': 'bronchodilatateur',
    'xanax': 'anxiolytique', 'seresta': 'anxiolytique',
    'zolpidem': 'hypnotique', 'stilnox': 'hypnotique',
    'daflon': 'veinotonique',
    'tahor': 'hypocholestérolémiant',
    'lasilix': 'diurétique', 'furosemide': 'diurétique',
    'diamicron': 'antidiabétique', 'metformine': 'antidiabétique', 'glucophage': 'antidiabétique',
    'kardegic': 'antiagrégant', 'aspirine': 'antiagrégant',
    'smecta': 'antidiarrhéique', 'lopéramide': 'antidiarrhéique', 'imodium': 'antidiarrhéique',
    'debridat': 'antispasmodique', 'trimébutine': 'antispasmodique', 'trimebutine': 'antispasmodique',
    'forlax': 'laxatif', 'transipeg': 'laxatif', 'movicol': 'laxatif',
    'primpéran': 'antiémétique', 'primperan': 'antiémétique', 'métoclopramide': 'antiémétique',
    'motilium': 'antiémétique', 'dompéridone': 'antiémétique', 'domperidone': 'antiémétique',
    'cétirizine': 'antihistaminique', 'cetirizine': 'antihistaminique', 'zyrtec': 'antihistaminique',
    'loratadine': 'antihistaminique', 'aerius': 'antihistaminique', 'desloratadine': 'antihistaminique',
    'strepsil': 'antiseptique', 'drill': 'antiseptique', 'humex': 'décongestionnant',
    'actifed': 'décongestionnant', 'rhinadvil': 'décongestionnant',
}

#: Les treize conduites cliniques du projet : pathologie ou symptome ->
#: traitement de premiere intention, et ses alternatives, avec posologie,
#: duree et justification.
#:
#: Remontee au niveau du module : elle etait locale a
#: `get_clinical_fallback`, et `classes_attendues` doit la lire pour noter
#: un diagnostic. C'est la source la mieux etablie du depot sur ce terrain,
#: puisqu'elle porte deja le rang therapeutique et la posologie.
GUIDELINES_CLINIQUES = [
    {
        'keywords': ['fièvre', 'fievre', 'hyperthermie', 'fébrile', 'febrile', 'température'],
        'first_line': {
            'name': 'Paracétamol',
            'substance': 'Paracétamol',
            'posology': '1g toutes les 6h, max 4g/jour',
            'duration': '3 à 5 jours selon évolution',
            'explanation': 'Traitement antipyrétique de première intention. Bien toléré aux doses thérapeutiques.',
            'relevance_score': 95
        },
        'alternatives': [{
            'name': 'Ibuprofène',
            'substance': 'Ibuprofène',
            'posology': '400mg toutes les 6-8h, max 1200mg/jour',
            'duration': '3 à 5 jours selon évolution',
            'explanation': 'Anti-inflammatoire non stéroïdien. Alternative si paracétamol insuffisant ou contre-indiqué.',
            'relevance_score': 80
        }]
    },
    {
        'keywords': ['douleur', 'douleurs', 'algique', 'algies', 'céphalée', 'céphalées', 'maux de tête', 'migraine'],
        'first_line': {
            'name': 'Paracétamol',
            'substance': 'Paracétamol',
            'posology': '1g toutes les 6h, max 4g/jour',
            'duration': '3 à 5 jours selon évolution',
            'explanation': 'Antalgique de première intention pour les douleurs légères à modérées.',
            'relevance_score': 95
        },
        'alternatives': [{
            'name': 'Ibuprofène',
            'substance': 'Ibuprofène',
            'posology': '400mg toutes les 6-8h, max 1200mg/jour',
            'duration': '3 à 5 jours selon évolution',
            'explanation': 'AINS efficace pour les douleurs d\'origine inflammatoire.',
            'relevance_score': 80
        }]
    },
    {
        'keywords': ['toux', 'toux sèche', 'toux grasse', 'quinte'],
        'first_line': {
            'name': 'Dextrométhorphane',
            'substance': 'Dextrométhorphane',
            'posology': '15 à 30 mg toutes les 6-8h, max 120mg/jour',
            'duration': '5 jours maximum',
            'explanation': 'Antitussif antitussif d\'action centrale pour les toux sèches gênantes.',
            'relevance_score': 90
        },
        'alternatives': [{
            'name': 'Acétylcystéine',
            'substance': 'Acétylcystéine',
            'posology': '200mg 3 fois par jour ou 600mg 1 fois par jour',
            'duration': '8 à 10 jours',
            'explanation': 'Mucolytique fluidifiant les sécrétions bronchiques pour les toux grasses.',
            'relevance_score': 75
        }]
    },
    {
        'keywords': ['infection virale', 'infection respiratoire', 'rhume', 'rhinite', 'grippe', 'état grippal', 'virose'],
        'first_line': {
            'name': 'Paracétamol',
            'substance': 'Paracétamol',
            'posology': '1g toutes les 6h, max 4g/jour',
            'duration': '3 à 5 jours selon évolution',
            'explanation': 'Traitement symptomatique de la fièvre et des courbatures liés aux infections virales.',
            'relevance_score': 95
        },
        'alternatives': [{
            'name': 'Ibuprofène',
            'substance': 'Ibuprofène',
            'posology': '400mg toutes les 6-8h, max 1200mg/jour',
            'duration': '3 à 5 jours selon évolution',
            'explanation': 'AINS pour les douleurs musculaires et articulaires associées.',
            'relevance_score': 75
        }]
    },
    {
        'keywords': ['nausée', 'nausées', 'vomissement', 'vomissements', 'nausee'],
        'first_line': {
            'name': 'Dompéridone',
            'substance': 'Dompéridone',
            'posology': '10 à 20mg 3 fois par jour avant les repas',
            'duration': '3 à 5 jours',
            'explanation': 'Antiémétique de référence pour les nausées et vomissements.',
            'relevance_score': 95
        },
        'alternatives': [{
            'name': 'Métoclopramide',
            'substance': 'Métoclopramide',
            'posology': '10mg 3 fois par jour avant les repas',
            'duration': '3 à 5 jours',
            'explanation': 'Antiémétique prokinétique. Alternative à la dompéridone.',
            'relevance_score': 80
        }]
    },
    {
        'keywords': ['diarrhée', 'diarrhées', 'diarrhee', 'gastro-entérite', 'gastroentérite'],
        'first_line': {
            'name': 'Smectite',
            'substance': 'Smectite diosmectite',
            'posology': '1 sachet 3 fois par jour après les repas',
            'duration': '5 à 7 jours',
            'explanation': 'Pansement intestinal adsorbant les toxines et protégeant la muqueuse digestive.',
            'relevance_score': 95
        },
        'alternatives': [{
            'name': 'Lopéramide',
            'substance': 'Lopéramide',
            'posology': '2 gélules d\'emblée puis 1 après chaque selle liquide, max 6/jour',
            'duration': '3 jours maximum',
            'explanation': 'Ralentisseur du transit intestinal. Ne pas utiliser en cas de diarrhée fébrile ou glairo-sanglante.',
            'relevance_score': 80
        }]
    },
    {
        'keywords': ['angine', 'pharyngite', 'amygdalite'],
        'first_line': {
            'name': 'Amoxicilline',
            'substance': 'Amoxicilline',
            'posology': '1g 2 fois par jour pendant 7 jours',
            'duration': '7 jours',
            'explanation': 'Antibiotique de première intention pour les angines bactériennes à streptocoque.',
            'relevance_score': 95
        },
        'alternatives': [{
            'name': 'Paracétamol',
            'substance': 'Paracétamol',
            'posology': '1g toutes les 6h, max 4g/jour',
            'duration': '3 à 5 jours selon évolution',
            'explanation': 'Traitement symptomatique de la douleur et de la fièvre associées.',
            'relevance_score': 85
        }]
    },
    {
        'keywords': ['bronchite', 'bronchiolite'],
        'first_line': {
            'name': 'Amoxicilline',
            'substance': 'Amoxicilline',
            'posology': '1g 2 fois par jour pendant 7 jours',
            'duration': '7 jours',
            'explanation': 'Antibiotique de première intention si bronchite bactérienne suspectée.',
            'relevance_score': 90
        },
        'alternatives': [{
            'name': 'Paracétamol',
            'substance': 'Paracétamol',
            'posology': '1g toutes les 6h, max 4g/jour',
            'duration': '3 à 5 jours selon évolution',
            'explanation': 'Traitement symptomatique de la fièvre.',
            'relevance_score': 75
        }]
    },
    {
        'keywords': ['infection urinaire', 'cystite', 'infection urinaire'],
        'first_line': {
            'name': 'Amoxicilline',
            'substance': 'Amoxicilline',
            'posology': '1g 2 fois par jour pendant 7 jours',
            'duration': '7 jours',
            'explanation': 'Antibiotique de première intention pour les infections urinaires non compliquées.',
            'relevance_score': 90
        },
        'alternatives': [{
            'name': 'Paracétamol',
            'substance': 'Paracétamol',
            'posology': '1g toutes les 6h, max 4g/jour',
            'duration': '3 jours',
            'explanation': 'Traitement symptomatique des douleurs et de la fièvre associées.',
            'relevance_score': 75
        }]
    },
    {
        'keywords': ['allergie', 'urticaire', 'rhinite allergique', 'conjonctivite allergique'],
        'first_line': {
            'name': 'Cétirizine',
            'substance': 'Cétirizine',
            'posology': '10mg 1 fois par jour le soir',
            'duration': 'Selon les symptômes, 7 à 14 jours',
            'explanation': 'Antihistaminique H1 de deuxième génération efficace pour les manifestations allergiques.',
            'relevance_score': 95
        },
        'alternatives': [{
            'name': 'Loratadine',
            'substance': 'Loratadine',
            'posology': '10mg 1 fois par jour',
            'duration': 'Selon les symptômes, 7 à 14 jours',
            'explanation': 'Antihistaminique H1 non sédatif pour le traitement symptomatique des allergies.',
            'relevance_score': 85
        }]
    },
    {
        'keywords': ['constipation', 'transit', 'irrégulier'],
        'first_line': {
            'name': 'Macrogol',
            'substance': 'Macrogol 4000',
            'posology': '1 à 2 sachets par jour à diluer dans un verre d\'eau',
            'duration': '5 à 10 jours',
            'explanation': 'Laxatif osmotique bien toléré pour les constipations passagères.',
            'relevance_score': 90
        },
        'alternatives': [{
            'name': 'Bisacodyl',
            'substance': 'Bisacodyl',
            'posology': '1 à 2 comprimés le soir au coucher',
            'duration': '3 à 5 jours',
            'explanation': 'Laxatif stimulant. Utilisation en deuxième intention, ponctuelle.',
            'relevance_score': 75
        }]
    },
    {
        'keywords': ['reflux', 'brûlure', 'brûlures', 'pyrosis', 'remontées acides'],
        'first_line': {
            'name': 'Oméprazole',
            'substance': 'Oméprazole',
            'posology': '20mg 1 fois par jour le matin à jeun',
            'duration': '7 à 14 jours',
            'explanation': 'Inhibiteur de la pompe à protons réduisant la sécrétion acide gastrique.',
            'relevance_score': 95
        },
        'alternatives': [{
            'name': 'Hydroxyde d\'aluminium',
            'substance': 'Hydroxyde d\'aluminium - Magnésium',
            'posology': '1 sachet 3 fois par jour après les repas',
            'duration': '5 à 7 jours',
            'explanation': 'Antiacide d\'action rapide neutralisant l\'acidité gastrique.',
            'relevance_score': 75
        }]
    },
    {
        'keywords': ['asthme', 'dyspnée', 'dyspnee', 'sifflement', 'essoufflement'],
        'first_line': {
            'name': 'Salbutamol',
            'substance': 'Salbutamol',
            'posology': '1 à 2 bouffées à la demande, max 8/jour',
            'duration': 'Traitement à la demande',
            'explanation': 'Bronchodilatateur bêta-2 agoniste d\'action rapide pour la crise d\'asthme.',
            'relevance_score': 95
        },
        'alternatives': [{
            'name': 'Budésonide',
            'substance': 'Budésonide',
            'posology': '200 à 400µg 2 fois par jour',
            'duration': 'Traitement de fond continu',
            'explanation': 'Corticoïde inhalé anti-inflammatoire pour le contrôle de l\'asthme persistant.',
            'relevance_score': 80
        }]
    },
]


def get_clinical_fallback(diagnostic_text: str) -> list:
    """
    Fallback médical basé sur les connaissances cliniques validées.
    Garantit qu'une réponse utile est toujours fournie, même sans base de données.
    
    Retourne une liste de médicaments avec score de pertinence:
        90-100: traitement de première intention
        70-89: traitement possible
        <70: non affiché (pas inclus)
    """
    text = diagnostic_text.lower()
    results = []
    seen_treatments = set()

    # Carte des pathologies/symptômes -> traitements standard
    # Les conduites vivent au niveau du module : voir
    # GUIDELINES_CLINIQUES.
    guidelines = GUIDELINES_CLINIQUES

    # Chercher les mots-clés dans le texte du diagnostic
    matched_conditions = []
    for condition in guidelines:
        matched = False
        for keyword in condition['keywords']:
            if keyword in text:
                matched_conditions.append(condition)
                matched = True
                break
        if matched:
            continue

    # Toujours ajouter les traitements symptomatiques universels si des symptômes sont présents
    if any(kw in text for kw in ['fièvre', 'fievre', 'douleur', 'infection']):
        # Ces traitements sont déjà gérés par les conditions ci-dessus
        pass

    # Construire la liste finale avec déduplication.
    #
    # Le rang survit désormais à l'assemblage. Cette table range ses entrées en
    # `first_line` et `alternatives` — première intention d'un côté, solution
    # de repli de l'autre — et cette distinction était **jetée** ici : tout
    # retombait dans une liste plate, et l'écran présentait un antalgique de
    # première intention et son alternative comme deux propositions
    # équivalentes. Le raisonnement clinique était dans les données, il
    # n'arrivait pas à l'écran.
    #
    # Les premières intentions sont assemblées avant les alternatives, toutes
    # conditions confondues : l'ordre à l'écran est celui du raisonnement, et
    # non celui du hasard de parcours.
    if matched_conditions:
        for rang, cle in (('premiere_intention', 'first_line'),
                          ('alternative', 'alternatives')):
            for condition in matched_conditions:
                proposes = condition[cle]
                if isinstance(proposes, dict):
                    proposes = [proposes]
                for propose in proposes:
                    if propose['name'] in seen_treatments:
                        continue
                    seen_treatments.add(propose['name'])
                    results.append(dict(propose, rang=rang,
                                        origine='conduite_clinique',
                                        condition=_libelle_condition(condition)))

    # Si toujours rien trouvé, fournir le traitement symptomatique universel.
    # Il porte un rang lui aussi : sans quoi l'écran aurait un groupe sans
    # titre, et la seule liste qui échappe au classement serait précisément
    # celle qu'on connaît le moins bien.
    if not results:
        results = [
            {
                'name': 'Paracétamol',
                'substance': 'Paracétamol',
                'posology': '1g toutes les 6h, max 4g/jour',
                'duration': 'Selon évolution',
                'explanation': 'Traitement symptomatique de première intention (antalgique et antipyrétique).',
                'relevance_score': 95,
                'rang': 'premiere_intention',
                'origine': 'conduite_clinique',
                'condition': 'Traitement symptomatique',
            },
            {
                'name': 'Mesures symptomatiques',
                'substance': 'Repos, hydratation',
                'posology': 'Repos au lit, boire 1.5L d\'eau par jour',
                'duration': 'Jusqu\'à disparition des symptômes',
                'explanation': 'Mesures générales essentielles : repos, hydratation abondante, alimentation légère.',
                'relevance_score': 90,
                'rang': 'premiere_intention',
                'condition': 'Traitement symptomatique',
            },
            {
                'name': 'Ibuprofène',
                'substance': 'Ibuprofène',
                'posology': '400mg toutes les 6-8h, max 1200mg/jour',
                'duration': 'Selon évolution',
                'explanation': 'Anti-inflammatoire non stéroïdien si paracétamol insuffisant ou contre-indiqué.',
                'relevance_score': 80,
                'rang': 'alternative',
                'condition': 'Traitement symptomatique',
            },
        ]

    return results


def _libelle_condition(condition: dict) -> str:
    """Nomme la condition qui a fait retenir un traitement.

    Le premier mot-clé sert d'intitulé : les treize entrées le donnent déjà
    sous sa forme la plus courante, et lui ajouter un champ dédié aurait
    demandé treize modifications pour la même chaîne de caractères.
    """
    mots = condition.get('keywords') or []
    return mots[0].capitalize() if mots else 'Traitement symptomatique'


#: Diagnostics posés, et les classes qu'ils appellent.
#:
#: `SYMPTOM_CLASS_MAP` est indexée par **symptômes** : fièvre, toux, nausée.
#: La prescription par diagnostic reçoit une **pathologie** déjà nommée —
#: « pneumonie communautaire du lobe inférieur droit ». Aucun de ses mots ne
#: figurait dans la table des symptômes, aucun candidat n'était donc noté, et
#: le durcissement de la notation ne pouvait rien pour cet écran.
#:
#: Les treize entrées de `get_clinical_fallback` couvrent déjà une partie du
#: terrain — angine, bronchite, cystite, gastro-entérite, asthme — et sont
#: consultées avant celle-ci. Ne figurent ici que les diagnostics courants
#: qu'elles ne connaissent pas.
#:
#: Comme la table des contraintes, elle est **volontairement courte**. Ce qui
#: n'y figure pas n'est pas noté, et l'écran le dit plutôt que d'inventer une
#: pertinence. L'étendre demande une source.
PATHOLOGIE_CLASS_MAP = {
    # Les molécules sont nommées, pas seulement les classes : le texte d'un
    # médicament porte « clarithromycine », jamais « macrolide ». Une table
    # qui ne dirait que les classes ne rencontrerait rien.
    'pneumonie': ['antibiotique', 'amoxicilline', 'macrolide', 'azithromycine',
                  'clarithromycine', 'spiramycine', 'roxithromycine',
                  'doxycycline', 'lévofloxacine', 'levofloxacine',
                  'ceftriaxone', 'antipyrétique', 'paracétamol'],
    'pneumopathie': ['antibiotique', 'amoxicilline', 'macrolide', 'azithromycine',
                     'clarithromycine', 'spiramycine', 'doxycycline',
                     'lévofloxacine', 'levofloxacine', 'ceftriaxone',
                     'antipyrétique', 'paracétamol'],
    'otite': ['antibiotique', 'amoxicilline', 'céfpodoxime', 'cefpodoxime',
              'antalgique', 'paracétamol'],
    'sinusite': ['antibiotique', 'amoxicilline', 'céfpodoxime', 'cefpodoxime',
                 'pristinamycine', 'antalgique', 'corticoïde'],
    'pyélonéphrite': ['antibiotique', 'ceftriaxone', 'fluoroquinolone',
                      'ciprofloxacine', 'ofloxacine', 'lévofloxacine',
                      'levofloxacine'],
    'lombalgie': ['antalgique', 'paracétamol', 'anti-inflammatoire',
                  'ibuprofène', 'myorelaxant'],
    'gastrite': ['antiacide', 'inhibiteur pompe à protons', 'oméprazole',
                 'ésoméprazole'],
    'ulcère gastroduodénal': ['antiacide', 'inhibiteur pompe à protons',
                              'oméprazole', 'ésoméprazole'],
    'zona': ['antiviral', 'aciclovir', 'valaciclovir', 'antalgique'],
    'eczéma': ['corticoïde', 'dermocorticoïde', 'émollient'],
    'dermatite': ['corticoïde', 'dermocorticoïde', 'émollient'],
    'conjonctivite': ['antiseptique', 'collyre', 'antibiotique'],
    'hypertension artérielle': ['antihypertenseur', 'inhibiteur calcique',
                                'sartan', 'diurétique', 'ramipril'],
    'diabète de type 2': ['antidiabétique', 'metformine'],
    # Ces pathologies sont déjà connues des guidelines, mais celles-ci ne
    # rendent que des **substances** — « amoxicilline », jamais
    # « antibiotique ». Or `BRAND_MAP` raisonne en classes : sans l'entrée
    # ci-dessous, CLAMOXYL n'obtenait pas son bonus pour une cystite, alors
    # que la conduite clinique du dépôt y propose de l'amoxicilline.
    'cystite': ['antibiotique', 'amoxicilline', 'fosfomycine'],
    'infection urinaire': ['antibiotique', 'amoxicilline', 'fosfomycine'],
    'bronchite': ['antitussif', 'expectorant', 'bronchodilatateur',
                  'antibiotique', 'paracétamol'],
    'gastro-entérite': ['antidiarrhéique', 'lopéramide', 'racécadotril',
                        'antiémétique', 'smectite'],
    # Ajoutés après un essai sur un patient réellement complexe : le
    # diagnostic empilait décompensation cardiaque, fibrillation auriculaire,
    # insuffisance rénale et BPCO surinfectée, et la table n'en reconnaissait
    # **aucun**. Seuls « ibuprofène » et « paracétamol » ressortaient, tirés
    # du mot « fébrile » : bronchodilatateurs, diurétiques et antibiotiques
    # obtenaient tous zéro.
    #
    # « bronchopneumopathie » a son entrée propre : la borne de mot empêche
    # « pneumopathie » de s'y reconnaître, et c'est voulu — une BPCO ne se
    # traite pas comme une pneumonie.
    'bronchopneumopathie': ['bronchodilatateur', 'salbutamol', 'ipratropium',
                            'tiotropium', 'fénotérol', 'formotérol',
                            'salmétérol', 'corticoïde', 'budésonide',
                            'fluticasone', 'antibiotique', 'amoxicilline'],
    'bpco': ['bronchodilatateur', 'salbutamol', 'ipratropium', 'tiotropium',
             'fénotérol', 'formotérol', 'salmétérol', 'corticoïde',
             'budésonide', 'fluticasone'],
    'emphysème': ['bronchodilatateur', 'tiotropium', 'salbutamol'],
    'insuffisance cardiaque': ['diurétique', 'furosémide', 'spironolactone',
                               'antihypertenseur', 'ramipril', 'périndopril',
                               'bêta-bloquant', 'bisoprolol'],
    'décompensation cardiaque': ['diurétique', 'furosémide', 'spironolactone'],
    'fibrillation auriculaire': ['anticoagulant', 'apixaban', 'rivaroxaban',
                                 'warfarine', 'bêta-bloquant', 'bisoprolol',
                                 'digoxine', 'amiodarone'],
    'surinfection': ['antibiotique', 'amoxicilline', 'macrolide'],
    'surinfecté': ['antibiotique', 'amoxicilline', 'macrolide'],
}

#: Un nom de pathologie est cherché en **mot entier**. La table en porte de
#: courts — « zona », « otite » — et une sous-chaîne les rencontrerait dans un
#: mot plus long. Le projet s'est déjà fait prendre deux fois : « anti » dans
#: « ORGARAN 750 U.I. anti-Xa » au § 2.7, « cetirizine » dans
#: « LEVOCETIRIZINE » au § 7.6.
def _pathologie_citee(pathologie: str, texte: str) -> bool:
    # Borne des deux côtés, le pluriel toléré. Sans la borne de fin, « zona »
    # se retrouvait dans « zonage » ; sans le pluriel, « otites » et
    # « pneumonies » n'étaient plus reconnues.
    #
    # Accents pliés des deux côtés. La table les porte — « pyélonéphrite »,
    # « ulcère gastroduodénal » — et un diagnostic se saisit rarement accentué.
    # Sans ce pli, « pyelonephrite » ne rencontrait rien, et la table restait
    # muette sans que rien ne le signale.
    return re.search(r'\b%ss?\b' % re.escape(_plier(pathologie)),
                     _plier(texte)) is not None


# ══ Phase P4 de la roadmap · la note décide ══════════════════════════════
#
# Deux grandeurs partageaient le nom `relevance_score` : une similarité cosinus
# Qdrant sur 0,20–1,00, et une note clinique sur 0–100. Un seuil appliqué sans
# savoir laquelle on lit produit un résultat qui *paraît* juste. Elles
# s'appellent désormais `similarite` et `pertinence`.

#: En deçà, un candidat quitte les propositions et rejoint les écartés.
#:
#: **Rien ne disparaît : tout change de panneau.** C'est ce qui rend le seuil
#: compatible avec le principe du § 2.8 — un médicament écarté en silence
#: emporte avec lui la raison de son retrait.
#:
#: La valeur est un point à mesurer, pas une donnée. Le principe, lui, ne l'est
#: pas : un candidat à zéro ne doit pas figurer parmi les propositions.
SEUIL_EXCLUSION = 40

#: Les quatre paliers de l'architecture, § 5.2.
PALIERS_PERTINENCE = (
    (0, 'exclu'),
    (SEUIL_EXCLUSION, 'retenu_declasse'),
    (70, 'retenu'),
    (101, '_borne'),
)

#: Le score de pertinence, décomposé.
#:
#: Pourquoi il l'est
#: -----------------
#: Une valeur unique — `POINTS_CLASSE_ATC = 60` — servait à la fois de
#: couverture et de pertinence. Tout candidat cliniquement juste plafonnait
#: donc à 60, et deux pénalités ordinaires suffisaient à le faire passer sous
#: le seuil de 40.
#:
#: Mesuré sur une insuffisance cardiaque aiguë décompensée, alors que la
#: conduite à tenir prescrivait « diurétiques IV (furosémide) » :
#:
#:     BURINEX   60 − 20 (interaction) − 15 (pression basse) = 25  écarté
#:     LOGIRENE  60 − 15                                     = 45  seul retenu
#:
#: Les deux pénalités étaient doublement mal placées : l'interaction signalait
#: le furosémide que le patient prend **déjà** — soit l'intensification même
#: qu'on cherche — et l'hypotension est un signe de la décompensation, non une
#: raison d'écarter son traitement.
#:
#: Le moteur ne savait pas dire « ceci **est** le traitement de cette
#: pathologie » : l'affirmation valait le même nombre de points que « ceci
#: appartient à une classe plausible ». Les quatre valeurs qui suivent
#: séparent les deux.
#:
#: **L'ATC ne prouve rien.** Il garantit qu'une classe utile n'est pas manquée,
#: et vaut donc juste assez pour rester visible — la moitié du seuil. Ce qui
#: fait monter un candidat, c'est son indication réelle.
POINTS_COUVERTURE_ATC = 20

#: L'indication répond au tableau, **et c'est la vocation première** du
#: médicament — l'objectif nommé en tête de son texte d'indication.
#:
#: Cette valeur se dédouble : couvrir l'objectif **principal** du tableau ne
#: vaut pas couvrir un de ses objectifs secondaires. Sans cette distinction,
#: vingt candidats arrivaient à 90 et le départage retombait sur le nom.
POINTS_INDICATION_PRINCIPALE = 40

#: La vocation du médicament est **l'objectif principal** du tableau.
#: Décongestionner une décompensation, abaisser la pression d'une HTA.
POINTS_OBJECTIF_PRINCIPAL = 45

#: La vocation du médicament est un objectif **secondaire** du tableau. Un IEC
#: dans une décompensation congestive : utile, et ce n'est pas ce qu'on traite
#: en premier. Il reste largement au-dessus du seuil.
POINTS_OBJECTIF_SECONDAIRE = 25

#: Le médicament appartient à une classe de **première ligne** pour l'objectif
#: principal — voir `CLASSES_DE_PREMIERE_LIGNE`. C'est ce qui sépare deux
#: molécules dont les indications DrugBank sont identiques.
#:
#: Choisi **supérieur** à la prime de largeur (`POINTS_OBJECTIF` × 2) : traiter
#: ce qu'on traite en premier compte davantage que couvrir plusieurs besoins à
#: la fois. Mesuré à 10, le bumétanide — diurétique de l'anse, dont
#: l'indication ne parle que d'œdème — passait sous le triamtérène, qui
#: mentionne aussi l'hypertension et gagnait la prime de largeur. Dans une
#: congestion aiguë, c'est l'inverse qu'il faut.
POINTS_PREMIERE_LIGNE = 25

#: Ce que coûte chaque rang au-delà de la première ligne.
#:
#: Choisi pour que l'ordre de `CLASSES_DE_PREMIERE_LIGNE` se lise dans le
#: score : anse 25, thiazidique 15, épargneur 5 pour une décongestion. Sans
#: cette décroissance, les trois valaient 25 et un thiazidique passait devant
#: un diurétique de l'anse dans une décompensation aiguë.
#:
#: Porté à 15, soit **plus** que la prime de largeur maximale (2 × 5) : un
#: rang de conduite doit peser davantage que le nombre d'objectifs couverts.
#: À 10, les deux s'annulaient exactement.
DECROISSANCE_LIGNE = 15

#: L'indication répond, mais par un emploi secondaire : le furosémide dans une
#: hypertension simple, mentionné après trois cents caractères sur l'œdème.
#: Assez pour rester découvrable, pas pour franchir le seuil seul.
POINTS_INDICATION_SECONDAIRE = 10

#: Par objectif thérapeutique du tableau que l'indication couvre, dans la
#: limite de `OBJECTIFS_COMPTES`. Un médicament qui répond à deux besoins du
#: cas — décongestionner **et** abaisser la pression — vaut mieux qu'un qui
#: n'en couvre qu'un.
#:
#: Abaissé de 15 à 10 pour que la prime de largeur reste **sous** celle de
#: première ligne : couvrir deux besoins à la fois ne doit pas valoir plus que
#: traiter celui qu'on traite en premier. À 15, la hiérarchie attendue ne
#: tenait que par saturation du plafond de 100 — elle était juste par accident.
#:
#: Abaissé de 10 à 5 : la prime de largeur compensait exactement un cran de
#: rang. Un thiazidique couvrant deux objectifs (rang 1, prime 15, largeur 20)
#: atteignait la même base qu'un diurétique de l'anse n'en couvrant qu'un
#: (rang 0, prime 25, largeur 10) — cent points tous les deux, plafond compris.
#: ESIDREX sortait donc devant BURINEX pour une décompensation aiguë.
POINTS_OBJECTIF = 5
OBJECTIFS_COMPTES = 2

#: L'indication est absente ou illisible — 147 substances du graphe n'en
#: portent pas, et un graphe injoignable les rend toutes muettes.
#:
#: **Le doute ne punit pas.** Avec la seule couverture ATC, un tel candidat
#: tomberait sous le seuil : une panne de Neo4j viderait l'écran, et une
#: substance absente de DrugBank disparaîtrait sans qu'on sache pourquoi. Ces
#: points ramènent exactement au comportement d'avant la décomposition —
#: 20 + 40 = 60 — soit « la classe est jugée digne de confiance faute de mieux ».
#:
#: Moins qu'une indication principale confirmée, plus qu'un emploi secondaire
#: reconnu : ne rien savoir vaut mieux que savoir que ce n'est pas la vocation.
POINTS_INDICATION_INCONNUE = 40


def palier_de(pertinence) -> str:
    """Rend le palier d'une note. Une note absente vaut « exclu »."""
    if not isinstance(pertinence, (int, float)):
        return 'exclu'
    palier = 'exclu'
    for seuil, nom in PALIERS_PERTINENCE:
        if nom == '_borne':
            break
        if pertinence >= seuil:
            palier = nom
    return palier


# ══ Le diagnostic pilote la sélection ════════════════════════════════════
#
# Sur l'assistant, le diagnostic naissait **en dernier** : les médicaments
# étaient cherchés, notés, filtrés et composés sur les seuls symptômes, et
# l'hypothèse clinique s'affichait à côté d'eux sans les avoir informés.
#
# Mesuré sur un cas réel — dyspnée, œdèmes, prise de poids, oligurie : le
# modèle posait « Insuffisance cardiaque aiguë décompensée, confiance 85 % »,
# et l'écran proposait **salbutamol et budésonide**, « retenu pour : Asthme ».
# Le mot *dyspnée* avait déclenché la conduite « asthme » du repli clinique.

#: Longueur au-delà de laquelle une première ligne est de la prose, non un
#: nom de diagnostic. Mieux vaut rien qu'un faux : un faux nom ferait chercher
#: des médicaments sur une phrase entière.
_LONGUEUR_DIAGNOSTIC_MAXIMALE = 90

_CONFIANCE = re.compile(r'\s*[—–-]\s*(?:confiance|confidence)[\s\S]*$', re.I)


def nom_du_diagnostic(compte_rendu: str) -> str:
    """Extrait le nom de l'hypothèse principale du compte rendu du modèle.

    Le modèle écrit sa première ligne sous la forme « Insuffisance cardiaque
    aiguë décompensée — Confiance : 85% ». C'est ce nom, et lui seul, qui doit
    piloter la recherche de médicaments.

    Rend une chaîne vide quand rien de sûr ne s'en dégage. Mieux vaut pas de
    diagnostic qu'un faux : l'appelant retombe alors sur les symptômes.

    Miroir de `decouperPrincipal()` côté écran, qui fait le même découpage
    pour l'affichage.
    """
    texte = str(compte_rendu or '')
    if not texte.strip():
        return ''

    # La section principale, repérée par sa forme plutôt que par comparaison
    # littérale — le modèle varie ses intitulés.
    lignes = []
    dans_section = False
    for ligne in texte.split('\n'):
        entete = re.match(r'^\s*\*\*\s*([^*\n]+?)\s*:?\s*\*\*\s*$', ligne)
        if entete:
            titre = entete.group(1).lower()
            dans_section = ('principal' in titre or 'probable' in titre
                            or 'primary' in titre)
            continue
        if dans_section and ligne.strip():
            lignes.append(ligne.strip())

    if not lignes:
        return ''

    premiere = lignes[0].replace('*', '').replace('_', '').replace('`', '').strip()
    nom = _CONFIANCE.sub('', premiere).strip(' :,.').strip()
    if not nom or len(nom) > _LONGUEUR_DIAGNOSTIC_MAXIMALE or len(nom.split()) > 10:
        return ''
    return nom


def tableau_clinique(symptomes: str, compte_rendu: str = '') -> str:
    """Compose ce sur quoi la sélection thérapeutique doit se faire.

    Le diagnostic passe **devant** les symptômes : c'est lui qui doit primer
    quand les deux se contredisent. « Dyspnée » appelle un bronchodilatateur,
    « insuffisance cardiaque décompensée » appelle un diurétique — et c'est le
    second qui a raison.

    Les symptômes sont conservés derrière : ils portent ce que le diagnostic
    ne nomme pas, et servent aux adjuvants.
    """
    diagnostic = nom_du_diagnostic(compte_rendu)
    symptomes = (symptomes or '').strip()
    if not diagnostic:
        return symptomes
    return ('%s. %s' % (diagnostic, symptomes)).strip().strip('.')


#: Ce que coûte une contre-indication relevée dans le RCP.
#:
#: Elle **abaisse, elle n'annule pas**. Un rapprochement de texte n'est pas une
#: décision clinique (§ 2.8) et le médecin garde la main ; mais un médicament
#: contre-indiqué qui garde 95 sur 100 se lit comme un bon choix, et c'est
#: exactement ce que l'écran montrait pour le salbutamol.
PENALITE_CONTRE_INDICATION = 40

#: Ce que coûte une interaction avec un traitement en cours. Moins qu'une
#: contre-indication : une interaction se gère parfois par la surveillance,
#: une contre-indication rarement.
PENALITE_INTERACTION = 20

#: Bornes de charge du contrôle d'interactions.
#:
#: Elles ne sélectionnent rien : elles empêchent seulement une saisie aberrante
#: de lancer un produit cartésien démesuré. Placées très au-dessus de l'usage
#: réel — une consultation compte quelques traitements en cours et quelques
#: dizaines de candidats retenus — pour qu'elles ne mordent jamais en pratique.
#:
#: Elles valaient dix de chaque côté, sans être nommées ni dites. Une borne
#: qui coupe la liste sur laquelle se calcule une pénalité de sécurité est un
#: filtre clinique déguisé : elle décide, sans ordre ni critère, quelle
#: interaction sera vue. Si l'une d'elles mord malgré tout, `tronque` le dit.
LIMITE_TRAITEMENTS_INTERACTION = 40
LIMITE_CANDIDATS_INTERACTION = 120


def peser_la_securite(medications, interactions=None):
    """Fait peser les contre-indications et les interactions sur la note.

    Le score et la sécurité étaient deux axes indépendants : les
    contre-indications déclassaient dans l'ordre d'affichage sans jamais
    toucher à la note, et une interaction ne comptait pas du tout. Salbutamol
    s'affichait à 95 sur 100 avec une contre-indication relevée.

    La pénalité est **nommée** : une note qui baisse sans raison affichée est
    pire qu'une note haute et fausse.
    """
    for med in (medications or []):
        note = med.get('pertinence')
        if not isinstance(note, (int, float)):
            continue

        # Le score **clinique** est figé ici, avant toute pénalité, et n'est
        # plus jamais touché.
        #
        # Un seul nombre portait jusqu'ici deux questions distinctes : « est-ce
        # le bon médicament ? » et « demande-t-il une surveillance ? ». Le
        # classement lisait donc la sécurité comme de la pertinence.
        #
        # Mesuré sur une décompensation : le furosémide, première ligne de la
        # décongestion à 100, tombait à 80 pour une interaction avec le
        # bisoprolol — « may increase the hypotensive activities », c'est-à-dire
        # de la surveillance — et passait derrière un thiazidique à 85 que le
        # graphe ne relie simplement pas au bisoprolol. Six paires sur vingt-huit
        # étaient inversées de cette façon.
        #
        # La relation `INTERACTS_WITH` ne porte que `description` et `source` :
        # **aucune gravité**. Toute interaction vaut donc le même −20, et
        # l'absence d'arête se lit comme une absence de risque. Aucune règle de
        # score ne corrige cette lacune ; elle peut seulement cesser de la
        # récompenser.
        # `setdefault` ne suffisait pas : `normaliser_medicament` crée la clé
        # à `None` avant la pesée, et la valeur n'était donc jamais posée.
        if not isinstance(med.get('pertinence_clinique'), (int, float)):
            med['pertinence_clinique'] = note

        penalites = []
        if med.get('contre_indications'):
            note -= PENALITE_CONTRE_INDICATION
            penalites.append("contre-indication relevée au RCP (−%d)"
                             % PENALITE_CONTRE_INDICATION)

        titre = (med.get('title') or '').lower()
        if any(str(i.get('medicine2', '')).lower().startswith(titre)
               for i in (interactions or []) if titre):
            # Allégée quand l'interaction porte sur un traitement de la **même
            # classe cumulable**.
            #
            # Le bumétanide « interagit » avec le furosémide que le patient
            # prend déjà — c'est-à-dire exactement l'intensification qu'une
            # congestion importante appelle. La pleine pénalité écartait donc
            # le traitement même de la décompensation. Le signal reste — deux
            # diurétiques de l'anse exposent bien à la déshydratation et à
            # l'hypokaliémie — mais il ne doit pas peser comme une association
            # fortuite.
            #
            # `couvert_par_le_traitement` a déjà posé l'alerte qui l'explique ;
            # ceci n'en est que la traduction dans la note.
            cumulable = any(
                a.get('regle') == 'même classe que le traitement en cours'
                for a in (med.get('alertes') or []))
            penalite = (PENALITE_INTERACTION // 2 if cumulable
                        else PENALITE_INTERACTION)
            note -= penalite
            penalites.append(
                "interaction avec un traitement en cours (−%d)%s"
                % (penalite, " — même classe, intensification possible"
                   if cumulable else ""))

        # Les règles de niveau `classement`. Elles n'écartent pas et
        # n'alertent pas : elles disent « moins indiqué ici », et c'est la
        # note qui doit le porter. Une pression à 96/58 ne contre-indique pas
        # un antihypertenseur de plus, elle le déclasse.
        #
        # Chaque règle compte une fois, et se nomme. Elles pèsent moins qu'une
        # contre-indication du RCP : elles disent l'inopportunité, pas le
        # danger.
        for declassement in (med.get('declassements') or []):
            note -= PENALITE_CLASSEMENT
            penalites.append("%s (−%d)"
                             % (declassement['regle'], PENALITE_CLASSEMENT))

        if penalites:
            med['pertinence'] = max(0, note)
            med['penalites'] = penalites
        else:
            med.pop('penalites', None)
    return medications or []


def classes_attendues(symptomes: str) -> set:
    """Rend les classes thérapeutiques que la saisie clinique appelle.

    C'est la lecture des tables dans l'autre sens : au lieu de demander « ce
    médicament correspond-il à un symptôme ? », on demande d'abord
    « qu'attend-on pour ce tableau ? ». Sans cette question, une marque
    marquait des points par sa seule notoriété.

    Trois sources, de la plus sûre à la plus large :

    1. `SYMPTOM_CLASS_MAP`, indexée par symptômes ;
    2. les treize guidelines de `get_clinical_fallback`, qui nomment des
       pathologies et **leurs traitements** — c'est la source la mieux
       établie, puisqu'elle porte déjà posologie et justification ;
    3. `PATHOLOGIE_CLASS_MAP`, pour les diagnostics courants que les deux
       premières ignorent.

    Les substances des guidelines entrent telles quelles : `SYMPTOM_CLASS_MAP`
    mêle déjà classes et molécules (« antipyrétique » à côté de
    « paracétamol »), et le rapprochement se fait par inclusion.
    """
    bas = (symptomes or '').lower()
    attendues = set()

    for symptome, classes in SYMPTOM_CLASS_MAP.items():
        if symptome in bas:
            attendues.update(c.lower() for c in classes)

    for condition in GUIDELINES_CLINIQUES:
        if any(mot in bas for mot in condition.get('keywords') or []):
            proposes = [condition['first_line']] + list(condition['alternatives'])
            for propose in proposes:
                for champ in ('substance', 'name'):
                    valeur = (propose.get(champ) or '').strip().lower()
                    if valeur:
                        attendues.add(valeur)

    for pathologie, classes in PATHOLOGIE_CLASS_MAP.items():
        if _pathologie_citee(pathologie, bas):
            attendues.update(c.lower() for c in classes)

    return attendues


def _classe_attendue(categorie: str, attendues: set) -> bool:
    """Dit si une catégorie de `BRAND_MAP` répond aux symptômes.

    L'inclusion joue dans les deux sens, et c'est nécessaire : `BRAND_MAP` dit
    « anti-inflammatoire » là où `SYMPTOM_CLASS_MAP` dit « anti-inflammatoire
    non stéroïdien ». Exiger l'égalité écarterait l'ibuprofène d'une fièvre,
    ce qui serait pire que le défaut corrigé.
    """
    categorie = _plier(categorie or '')
    if not categorie:
        return False
    return any(categorie in _plier(attendue) or _plier(attendue) in categorie
               for attendue in attendues)


def compute_clinical_relevance(symptomes: str, medication: dict) -> tuple:
    """Note la pertinence d'un médicament face aux symptômes.

    Cette fonction acceptait un troisième paramètre, `antecedents`, qu'elle ne
    lisait nulle part : la signature laissait croire que les antécédents
    pesaient sur le score, et rien ne le faisait. Ils agissent maintenant
    ailleurs, dans `appliquer_contraintes()`, au moment où chaque médicament
    porte sa fiche — les y relire ici coûterait une lecture Mongo par
    candidat, pour le même résultat.
    """
    try:
        title = (medication.get('title') or '').lower()
        raw_substances = medication.get('substances') or []
        if isinstance(raw_substances, str):
            substances = [raw_substances.lower()]
        else:
            substances = [s.lower() for s in raw_substances]
        forme = (medication.get('forme') or '').lower()
        # Accents pliés. Les tables sont accentuées — « dextrométhorphane »,
        # « corticoïde » — et les titres du catalogue ne le sont presque
        # jamais : DEXTROMETHORPHANE 15 mg obtenait **zéro pour une toux**
        # alors que la table l'y attend explicitement. Le rapprochement
        # échouait en silence, comme toujours avec les accents.
        text_for_match = _plier(title + ' ' + ' '.join(substances) + ' ' + forme)
        symptomes_lower = _plier(symptomes or '')
        
        # Exclusion si catégorie exclue
        for excl in EXCLUDED_CATEGORIES:
            if excl in text_for_match:
                return 0, "Produit hors contexte thérapeutique"
        
        score = 0
        matching_elements = []
        
        # 1. Correspondance par substance active
        for symptom, drug_classes in SYMPTOM_CLASS_MAP.items():
            if _plier(symptom) in symptomes_lower:
                for drug_class in drug_classes:
                    if _plier(drug_class) in text_for_match:
                        score += 50
                        matching_elements.append(drug_class)
                        break

        attendues = classes_attendues(symptomes)
        attendues_pliees = {_plier(c) for c in attendues}

        # 1 ter. Phase P4 — la classe ATC compte dans la note.
        #
        # La notation ne lisait que des tables textuelles, qui ne connaissent
        # ni « BURINEX » ni « DALACINE ». Depuis P2 le graphe porte pourtant la
        # classification, et depuis P3b la chaîne s'en sert pour générer :
        # la note ignorait la moitié de ce que le système avait appris.
        #
        # Mesuré avant cette étape, en appliquant le seuil : 17 candidats sur
        # 20 écartés pour une pneumonie, 19 sur 20 pour une décompensation
        # cardiaque — dont **la totalité** des candidats cliniquement justes.
        # P4 aurait supprimé ce que P3b venait de produire.
        #
        # **Ces points sont désormais conditionnels.** Ils valaient 60 pour un
        # seuil à 40 : une correspondance de classe suffisait, à elle seule et
        # avec 50 % de marge, à faire recommander un médicament. Mesuré sur
        # « céphalées légères, suspicion d'HTA » — qui appelle C03, C07, C08,
        # C09 et N02 — le célécoxib obtenait 60 avec pour toute justification
        # « Pertinent pour: classe C08 ».
        #
        # L'ATC redevient un mécanisme de **découverte** : il garantit qu'une
        # classe utile n'est pas manquée. C'est l'indication réelle qui décide
        # si le candidat découvert mérite ses points.
        groupes = set(medication.get('groupes_atc') or [])
        attendues_atc = classes_atc_attendues(symptomes)
        if groupes and attendues_atc and (set(groupes) & attendues_atc):
            classe = sorted(set(groupes) & attendues_atc)[0]
            verdict, communs, principal = force_de_l_indication(
                medication.get('indication_source') or '', symptomes)

            if verdict == 'non':
                # Découvert par sa classe, démenti par son indication.
                #
                # Ce n'est pas une exclusion par règle — c'est une absence de
                # pertinence. La distinction compte : les règles d'exclusion
                # restent réservées aux contre-indications, interactions et
                # duplications.
                medication['indication_hors_sujet'] = classe
            else:
                # La couverture d'abord : la classe garantit qu'on n'a pas
                # manqué le candidat. Elle ne prouve rien de plus, et vaut donc
                # la moitié du seuil.
                score += POINTS_COUVERTURE_ATC
                matching_elements.append("classe %s" % classe)

                # Puis la pertinence, qui elle peut porter haut.
                if verdict == 'inconnu':
                    # Ni preuve ni démenti. On revient au comportement d'avant
                    # la décomposition : la classe fait foi faute de mieux.
                    score += POINTS_INDICATION_INCONNUE
                elif verdict == 'oui':
                    if principal:
                        # Gradué selon **quel** objectif du tableau la vocation
                        # du médicament couvre. Couvrir ce qu'on traite en
                        # premier ne vaut pas couvrir un objectif second : sans
                        # cette distinction, triamtérène, amiloride et
                        # énalapril arrivaient à 90 comme le furosémide.
                        vocation = objectif_principal_de_l_indication(
                            medication.get('indication_source') or '')
                        vise = objectifs_ordonnes_du_tableau(symptomes)[0]
                        touche_le_principal = bool(vise and vocation == vise)

                        score += (POINTS_OBJECTIF_PRINCIPAL
                                  if touche_le_principal else
                                  POINTS_OBJECTIF_SECONDAIRE if vise else
                                  POINTS_INDICATION_PRINCIPALE)
                        score += POINTS_OBJECTIF * min(len(communs),
                                                       OBJECTIFS_COMPTES)

                        # À indication équivalente, la classe de première ligne
                        # départage. C'est ce qui sépare un diurétique de
                        # l'anse d'un épargneur de potassium, que DrugBank
                        # décrit dans les mêmes termes.
                        rang_ligne = (rang_de_premiere_ligne(medication, vise)
                                      if touche_le_principal else -1)
                        if rang_ligne >= 0:
                            # Dégressif selon le rang : la conduite dit dans
                            # quel ordre on emploie les classes, et le score
                            # doit le refléter plutôt que de les égaliser.
                            prime = max(0, POINTS_PREMIERE_LIGNE
                                        - rang_ligne * DECROISSANCE_LIGNE)
                            score += prime
                            medication['rang_de_ligne'] = rang_ligne
                            matching_elements.append(
                                'première ligne' if rang_ligne == 0
                                else 'ligne %d' % (rang_ligne + 1))

                        medication['vise_objectif_principal'] = touche_le_principal
                        # Nommes, pas seulement constates : l'ecran doit
                        # pouvoir dire *quel* objectif le medicament sert.
                        medication['objectif_principal'] = vise or ''
                        medication['objectif_vise'] = vocation or ''
                        matching_elements.append(
                            'indication principale : '
                            + ', '.join(sorted(communs)))
                    else:
                        # Emploi secondaire. Découvrable, mais il lui faut un
                        # autre signal pour franchir le seuil.
                        score += POINTS_INDICATION_SECONDAIRE
                        matching_elements.append(
                            'indication secondaire : '
                            + ', '.join(sorted(communs)))
                        medication['indication_secondaire'] = True
                    medication['indication_principale'] = bool(principal)

        # Palier antalgique. L'indication ne suffit pas à trier les
        # antalgiques : oxycodone et paracétamol répondent tous deux à
        # « antalgie », et une céphalée légère faisait remonter un opioïde.
        # Le palier vient de la **substance**, jamais de son indication.
        #
        # J'avais ajouté un second signal, lu dans le texte d'indication
        # (« moderate to severe pain » → palier 2). Mesuré sur les textes
        # réels, il est faux : celui du paracétamol fait 700 caractères et
        # contient « moderate to severe » à propos d'autre chose, ce qui
        # déclassait le paracétamol pour une céphalée légère — l'inverse de ce
        # qu'on cherche. Une table curatée de quarante substances est plus sûre
        # qu'un rapprochement lexical sur de la prose.
        # La pénalité est **retenue** et appliquée après le plafonnement, non
        # soustraite ici.
        #
        # Soustraite au fil de l'accumulation, elle disparaissait : un
        # paracétamol cumule 50 par le symptôme, 60 par la classe et 55 par la
        # marque ; 165 − 25 = 140, plafonné à 100. LAMALINE — palier 3, opium —
        # s'affichait donc à 100 sur 100 pour une céphalée légère, la pénalité
        # posée et invisible. Mesuré bout en bout.
        intensite = intensite_douleur(symptomes)
        exigence = palier_antalgique(medication)
        if exigence and intensite and exigence > intensite:
            medication['palier_excessif'] = {
                'palier': exigence, 'intensite': intensite}

        # 1 bis. Correspondance par pathologie nommée.
        #
        # La boucle ci-dessus ne lit que `SYMPTOM_CLASS_MAP`, indexée par
        # symptômes. Un diagnostic déjà posé n'en contient aucun :
        # « pneumonie communautaire » n'y trouvait rien, et un macrolide
        # obtenait donc zéro pour une pneumonie.
        #
        # `classes_attendues()` consulte aussi les conduites cliniques et la
        # table des pathologies. Le point n'est accordé qu'une fois, et
        # seulement si rien n'a été trouvé plus haut : cette étape complète la
        # précédente, elle ne s'y ajoute pas.
        if not matching_elements:
            for classe in sorted(attendues, key=len, reverse=True):
                if _plier(classe) in text_for_match:
                    score += 50
                    matching_elements.append(classe)
                    break

        # 2. Correspondance par nom de spécialité (brand map)
        #
        # Le bonus n'est accordé que si la catégorie de la marque a un rapport
        # avec les symptômes. Il l'était auparavant à **toute** marque
        # reconnue : mesuré sur « toux sèche, gêne respiratoire », VENTOLINE,
        # DEBRIDAT et FORLAX obtenaient 55 chacun, et l'écran écrivait
        # « Pertinent pour: laxatif » à propos d'une toux. C'est ce qui faisait
        # proposer un antispasmodique intestinal à un asthmatique.
        for brand, category in BRAND_MAP.items():
            if brand not in title:
                continue
            if category.lower() in [m.lower() for m in matching_elements]:
                continue
            if not _classe_attendue(category, attendues):
                continue
            score += 55
            matching_elements.append(category)
        
        # 3. Bonus forme pharmaceutique
        if 'toux' in symptomes_lower and ('sirop' in text_for_match or 'solution' in text_for_match):
            score += 10
        
        # 4. Pénalités pour médicaments d'autres systèmes sans symptômes correspondants
        digestive_markers = ['digestif', 'gastro', 'intestinal', 'rectal', 'laxatif', 'antiacide', 'constipation', 'antispasmodique']
        skin_markers = ['dermique', 'cutané', 'cutane', 'topique', 'crème', 'creme', 'pommade', 'cortancyl']
        
        is_digestive = any(m in title for m in digestive_markers)
        is_skin = any(m in title for m in skin_markers)
        has_digestive_symptom = any(s in symptomes_lower for s in ['digestif', 'ventre', 'estomac', 'nausée', 'nausee', 'vomissement', 'diarrhée', 'diarrhee', 'constipation'])
        has_skin_symptom = any(s in symptomes_lower for s in ['peau', 'dermique', 'cutané', 'cutane', 'éruption', 'eruption'])
        
        if is_digestive and not has_digestive_symptom:
            score -= 30
        if is_skin and not has_skin_symptom:
            score -= 30
        
        # 5. Dernier recours : une molécule connue, **et attendue**.
        #
        # Cette étape accordait 60 à toute molécule de la liste, quels que
        # soient les symptômes. ZYRTEC obtenait donc 60 pour une fièvre et
        # pour une toux, DOLIPRANE 60 pour une allergie. C'est le même défaut
        # que celui corrigé à l'étape 2, sur l'autre moitié de la fonction :
        # la notoriété tenait lieu de pertinence.
        #
        # La marque est reliée à sa catégorie par `BRAND_MAP` quand elle y
        # figure ; c'est cette catégorie qui doit être attendue. Sans elle, la
        # molécule est cherchée telle quelle parmi les classes attendues.
        if score <= 0:
            all_known = ['paracétamol', 'paracetamol', 'doliprane', 'efferalgan', 'dafalgan',
                         'ibuprofène', 'ibuprofene', 'advil', 'nurofen', 'aspirine', 'kardegic',
                         'amoxicilline', 'clamoxyl', 'salbutamol', 'ventoline',
                         'cétirizine', 'cetirizine', 'zyrtec', 'loratadine', 'aerius',
                         'dompéridone', 'domperidone', 'motilium', 'primperan', 'métoclopramide',
                         'prednisone', 'prednisolone', 'solupred', 'cortancyl']
            for connue in all_known:
                if _plier(connue) not in text_for_match:
                    continue
                categorie = BRAND_MAP.get(connue, connue)
                if not _classe_attendue(categorie, attendues):
                    continue
                score = 60
                matching_elements.append('molécule à visée symptomatique')
                break
        
        # L'indication réelle prime sur toute créance de classe.
        #
        # Suspendre les seuls points ATC ne suffisait pas : le furosémide
        # gardait 55 points par `BRAND_MAP`, qui le relie à « diurétique », et
        # une hypertension attend un diurétique. Vrai au niveau de la classe,
        # faux au niveau du médicament — c'est exactement la confusion qu'on
        # corrige, réapparue un étage plus bas.
        #
        # Toutes ces voies — SYMPTOM_CLASS_MAP, classes attendues, BRAND_MAP,
        # molécules connues — raisonnent par appartenance. Quand l'indication
        # dit explicitement autre chose, aucune ne tient.
        #
        # `indication_hors_sujet` n'est posé que si l'indication est **lisible
        # et contraire** : une indication absente ou illisible laisse tout ce
        # qui précède intact.
        if medication.get('indication_hors_sujet'):
            return 0, ("Classe ATC pertinente (%s), mais l'indication réelle "
                       "est sans rapport avec le tableau clinique"
                       % medication['indication_hors_sujet'])

        # Un emploi secondaire ne peut pas être porté haut par des crédits de
        # classe.
        #
        # Toutes les voies qui précèdent — `SYMPTOM_CLASS_MAP`, les classes
        # attendues, `BRAND_MAP`, les molécules connues — raisonnent par
        # appartenance. Quand l'indication dit que ce n'est pas la vocation du
        # médicament, aucune ne tient : le furosémide, relié à « diurétique »
        # par `BRAND_MAP` et l'hypertension attendant un diurétique, remontait
        # à 85 pour une céphalée, sa vocation décongestionnante mise de côté.
        #
        # Il reste découvrable — la couverture ATC et l'emploi secondaire lui
        # sont acquis — mais il lui faut un autre signal que sa classe pour
        # franchir le seuil.
        if medication.get('indication_secondaire'):
            score = min(score, POINTS_COUVERTURE_ATC
                        + POINTS_INDICATION_SECONDAIRE)

        # Le plafond d'abord, les pénalités ensuite. Dans l'autre ordre elles
        # sont absorbées par le plafond et ne changent rien.
        final_score = min(score, 100)

        # La pénalité de palier croît avec l'écart. Un opioïde fort sur une
        # douleur légère — deux crans — doit tomber sous le seuil ; la codéine,
        # un cran, doit seulement passer derrière le paracétamol. Une pénalité
        # fixe ne distinguait pas les deux, et la marge accrue du score les
        # laissait tous deux au-dessus du seuil.
        excessif = medication.get('palier_excessif')
        if excessif:
            ecart = excessif['palier'] - excessif['intensite']
            final_score -= PENALITE_PALIER * max(1, ecart)
        final_score = max(0, final_score)
        
        if matching_elements:
            justification = f"Pertinent pour: {', '.join(set(matching_elements))}"
        elif final_score >= 70:
            justification = "Traitement cliniquement pertinent"
        elif final_score >= 50:
            justification = "Traitement symptomatique possible"
        else:
            return 0, "Aucun lien thérapeutique direct avec les symptômes"
        
        return final_score, justification
    except Exception as e:
        logger.warning(f"Erreur dans compute_clinical_relevance pour {medication.get('title', '?')}: {e}")
        return 50, "Évaluation clinique non disponible"


def _requete_de_repli(symptomes: str) -> str:
    """Compose une requête texte à partir des symptômes reconnus.

    Le projet range déjà, dans SYMPTOM_CLASS_MAP, les substances et classes
    associées à chaque symptôme. Les employer vaut mieux que de jeter la
    phrase entière dans l'index : « fièvre à 38,7 °C » y trouvait des
    dosages.

    À défaut de symptôme reconnu, les mots du texte sont repris, mais
    débarrassés des nombres et des mots trop courts pour porter du sens.
    """
    plie = _plier(symptomes or '')
    cibles = []
    for symptome, classes in SYMPTOM_CLASS_MAP.items():
        if _plier(symptome) not in plie:
            continue
        for classe in classes:
            # Un seul mot, et assez long pour être distinctif. « ains » et
            # « anti-inflammatoire non stéroïdien » se décomposent en jetons
            # courts, et « anti » rencontrait « ORGARAN 750 U.I. anti-Xa » :
            # la recherche d'un antipyrétique rendait des anticoagulants.
            if ' ' in classe or '-' in classe or len(classe) < 6:
                continue
            if classe not in cibles:
                cibles.append(classe)
    if cibles:
        # Sans guillemets, volontairement. MongoDB exige que **toutes** les
        # expressions entre guillemets soient presentes : huit classes
        # therapeutiques citees ensemble ne rendaient plus aucune fiche. Sans
        # guillemets, les termes sont alternatifs, ce qu'un repli demande.
        return ' '.join(cibles[:12])

    mots = [m for m in re.split(r'[^a-zA-Zàâäçéèêëîïôöùûüÿ]+', symptomes or '')
            if len(m) > 4]
    return ' '.join(mots[:8])


def search_medications_by_symptoms(symptomes: str, limit: int = 5):
    """
    Recherche vectorielle de médicaments pertinents basée sur les symptômes
    """
    try:
        # Générer l'embedding des symptômes
        query_vector = embedding_model.encode(symptomes).tolist()
        
        # Recherche dans Qdrant (nouvelle syntaxe)
        search_result = qdrant_client.query_points(
            collection_name='medicines',
            query=query_vector,
            limit=limit
        )
        
        medications = []
        # Adaptation selon la structure de réponse
        points = search_result.points if hasattr(search_result, 'points') else search_result
        
        for hit in points:
            payload = hit.payload
            medications.append({
                'id': payload.get('mongo_id'),
                'title': payload.get('title'),
                'substances': payload.get('substances', []),
                'forme': payload.get('forme', ''),
                'laboratoire': payload.get('laboratoire', ''),
                'score': hit.score,
                'posologie': get_default_posologie(payload.get('title')),
                # Remonté par proximité de texte, rien de plus. L'écran doit
                # pouvoir le dire : une similarité n'est pas une indication.
                'origine': 'similarite',
            })
        
        # Phase P1 : le vivier est filtré dès sa constitution. Un produit non
        # commercialisé ou de voie extracorporelle n'a pas à être noté, ni
        # confronté aux antécédents : il n'est pas prescriptible.
        medications, _ineligibles = filtrer_eligibilite(medications)
        logger.info(f"Trouvé {len(medications)} médicaments pour: {symptomes}")
        return medications

    except Exception as e:
        logger.error(f"Erreur recherche Qdrant: {e}")
        # Repli MongoDB si Qdrant échoue.
        #
        # La phrase de symptômes ne peut pas servir de requête telle quelle :
        # « fièvre à 38,7 °C » trouvait « LEVOTHYROX 38 microgrammes » et
        # « GEMCITABINE 38 mg/mL », les nombres du texte clinique rencontrant
        # les dosages. La requête part donc des classes thérapeutiques que le
        # projet associe déjà à chaque symptôme.
        try:
            requete = _requete_de_repli(symptomes)
            if not requete:
                logger.warning("Repli MongoDB : aucun terme exploitable dans « %s »",
                               symptomes[:60])
                return []
            meds_cursor = db.medicines.find(
                {'$text': {'$search': requete}},
                {'title': 1, 'medicine_details': 1}
            ).limit(limit)
            
            medications = []
            for med in meds_cursor:
                medications.append({
                    'id': str(med['_id']),
                    'title': med.get('title'),
                    'substances': med.get('medicine_details', {}).get('substances_actives', []),
                    'forme': med.get('medicine_details', {}).get('forme', ''),
                    'laboratoire': med.get('medicine_details', {}).get('laboratoire', ''),
                    'score': 0.5,
                    'posologie': get_default_posologie(med.get('title')),
                    'origine': 'similarite',
                })
            logger.info(f"Fallback MongoDB: {len(medications)} médicaments")
            return medications
        except Exception as e2:
            logger.error(f"Erreur fallback MongoDB: {e2}")
            return []


#: Spécialité retenue pour représenter une dénomination commune.
#: Le rapprochement est retenu par processus : la même DCI revient d'une
#: analyse à l'autre, et l'interroger à chaque fois ne rendrait jamais autre
#: chose.
_specialites_representatives = {}

#: Formes locales, écartées quand une forme générale existe. Une suggestion
#: d'ibuprofène par voie orale ne doit pas ouvrir la fiche d'un gel.
_FORMES_LOCALES = ('gel', 'crème', 'creme', 'pommade', 'collyre', 'suppositoire',
                   'solution pour inhalation', 'usage cutané', 'usage cutane',
                   'auriculaire', 'nasal', 'ovule', 'emplâtre', 'emplatre')


def specialite_representative(dci: str):
    """Rend une spécialité du catalogue qui contient cette substance.

    Une dénomination commune n'est le titre d'aucune fiche : « Salbutamol »
    ouvrait une page introuvable. Le catalogue contient pourtant seize
    spécialités qui en contiennent, et le clic doit mener à l'une d'elles.

    Le choix est ordonné : une spécialité à substance unique, commercialisée,
    de forme générale plutôt que locale, et au titre le plus court, ce qui
    désigne presque toujours la présentation la plus simple. La recherche passe
    par l'index texte, qui couvre le titre et les substances actives ; un
    parcours du catalogue serait ici la faute déjà commise ailleurs.

    Rend `None` si rien ne convient. L'appelant retombe alors sur la recherche.
    """
    cle = _plier(dci or '')
    if not cle:
        return None
    if cle in _specialites_representatives:
        return _specialites_representatives[cle]

    choix = None
    try:
        candidats = list(db.medicines.find(
            {'$text': {'$search': '"%s"' % dci}},
            {'title': 1, 'medicine_details.substances_actives': 1,
             'commercialisation': 1, 'score': {'$meta': 'textScore'}}
        ).sort([('score', {'$meta': 'textScore'})]).limit(40))

        def rang(doc):
            titre = (doc.get('title') or '')
            substances = doc.get('medicine_details', {}).get('substances_actives') or []
            bas = _plier(titre)
            return (
                0 if len(substances) == 1 else 1,
                0 if doc.get('commercialisation') == 'Commercialisée' else 1,
                1 if any(f in bas for f in _FORMES_LOCALES) else 0,
                len(titre),
            )

        candidats.sort(key=rang)
        if candidats:
            choix = {'_id': candidats[0]['_id'], 'title': candidats[0].get('title', '')}
    except Exception as err:
        logger.warning("Spécialité représentative pour %s : %s", dci, err)

    _specialites_representatives[cle] = choix
    return choix


def normaliser_medicament(med: dict) -> dict:
    """Ramène un médicament à une seule forme, quel que soit son chemin.

    Deux chemins alimentent la liste affichée et ils ne nommaient pas leurs
    champs pareil :

        recherche vectorielle   title, substances, forme, justification
        repli clinique          name,  substance,  explanation, duration

    Le gabarit lisait la première forme. Quand le repli servait, il affichait
    donc « undefined » à la place du nom du médicament, et laissait tomber la
    justification, la substance et la durée. Le contrôle d'interactions, qui
    lisait `title` lui aussi, sortait sans rien vérifier.

    Une seule forme en sortie règle les deux à la fois.
    """
    substances = med.get('substances')
    if not substances:
        une = med.get('substance')
        substances = [une] if une else []
    elif isinstance(substances, str):
        substances = [substances]

    titre = med.get('title') or med.get('name') or ''
    identifiant = med.get('id') or _plier(titre).replace(' ', '-')

    # Où mène la fiche. Les deux chemins ne désignent pas la même chose : la
    # recherche vectorielle rend une spécialité du catalogue, avec son
    # identifiant ; le repli clinique rend une dénomination commune, qui n'est
    # le titre d'aucune fiche.
    #
    # Une dénomination commune est donc rattachée à une spécialité qui la
    # contient, et le clic ouvre cette fiche. Faute de spécialité, il ouvre la
    # recherche, qui les liste toutes.
    fiche_id = ''
    if re.fullmatch(r'[0-9a-f]{24}', str(identifiant)):
        lien = '/medicine/%s' % identifiant
        fiche_id = str(identifiant)
    else:
        representative = specialite_representative(titre)
        if representative:
            lien = '/medicine/%s' % representative['_id']
            fiche_id = str(representative['_id'])
            med['representative'] = representative['title']
        else:
            lien = '/search?search=%s' % quote(titre)

    return {
        'id': identifiant,
        'lien': lien,
        # Fiche a consulter pour lire le RCP : la specialite elle-meme quand
        # elle vient du catalogue, sa representative quand le medicament est
        # une denomination commune. Sans elle, les contre-indications ne
        # pourraient etre relevees que sur la moitie des cas.
        'fiche_id': fiche_id,
        'title': titre,
        'substances': [s for s in substances if s],
        'forme': med.get('forme') or '',
        'posologie': med.get('posologie') or med.get('posology') or '',
        'duration': med.get('duration') or med.get('duree') or '',
        'justification': med.get('justification') or med.get('explanation') or '',
        # Phase P4 : la note clinique s'appelle `pertinence`. Elle partageait
        # `relevance_score` avec la similarité cosinus, qui a désormais son
        # propre champ. Le nom d'entrée reste `relevance_score` : c'est celui
        # que portent les conduites cliniques, qui sont des données.
        'pertinence': med.get('pertinence', med.get('relevance_score')),
        'laboratoire': med.get('laboratoire') or '',
        # Nom de la specialite ouverte par le lien, quand le medicament est
        # une denomination commune. L ecran le dit : le lecteur doit savoir
        # sur quelle fiche il atterrit, et que d autres existent.
        'representative': med.get('representative') or '',
        # Rang therapeutique, et condition qui l a fait retenir. Les conduites
        # cliniques du depot rangent leurs traitements en premiere intention
        # et alternatives ; cette distinction se perdait ici, dans un
        # dictionnaire reconstruit champ par champ. Le raisonnement etait dans
        # les donnees et n arrivait pas a l ecran.
        #
        # Vide pour les candidats venus de la recherche vectorielle ou du
        # modele : eux ne portent aucun rang, et en inventer un donnerait a
        # une note le poids d une conduite clinique.
        'rang': med.get('rang') or '',
        'condition': med.get('condition') or '',
        # Groupes ATC de niveau 2. Ils se perdaient ici : le modele fabrique
        # de nouveaux dictionnaires a partir de son JSON, et la normalisation
        # les reconstruit champ par champ. La note ne voyait donc pas la
        # classe, et ERY 500 — un macrolide — obtenait zero pour une pneumonie.
        #
        # Meme defaut que pour le rang therapeutique et la substance annoncee.
        # Ce dictionnaire explicite est un filet a trous : tout ce qui compte
        # doit y figurer nommement.
        'groupes_atc': sorted(med.get('groupes_atc') or []),
        # Substance que le modele avait annoncee, quand la fiche la contredit.
        # Vide le reste du temps. C'est le signal le plus utile de l'ecran : il
        # dit que le modele a parle de ce qu'il ne connaissait pas.
        'substance_annoncee': med.get('substance_annoncee') or '',
        # D'ou vient ce candidat. « appartenir a la classe ATC du diagnostic »
        # et « convenir a ce patient » ne sont pas la meme chose, et l'ecran
        # les affichait pareil : un medicament genere parce que sa classe
        # figurait dans la table se lisait comme une recommandation clinique.
        #
        #   classe_atc        genere depuis la classe attendue du diagnostic
        #   conduite_clinique repli du depot, range en intention
        #   similarite        remonte par la recherche vectorielle
        #   modele            propose par le modele
        #
        # Vide quand la provenance n'est pas connue : mieux vaut ne rien dire
        # que d'annoncer une origine supposee.
        'origine': med.get('origine') or '',
        # Ce que la notation a etabli sur l'indication.
        #
        # `compute_clinical_relevance` pose ces trois champs, et la
        # normalisation les perdait : sur l'assistant la note se fige dans
        # `analyze_patient`, **avant** cette reconstruction. `merite_clinique`
        # lisait donc toujours `indication_principale` absent, et son deuxieme
        # critere valait 1 pour tout le monde — un critere clinique mort, qui
        # laissait le titre departager.
        #
        # Meme defaut que pour le rang therapeutique, la substance annoncee et
        # les groupes ATC : ce dictionnaire explicite est un filet a trous, et
        # tout ce qui compte doit y figurer nommement.
        'indication_principale': bool(med.get('indication_principale')),
        'vise_objectif_principal': bool(med.get('vise_objectif_principal')),
        'indication_secondaire': bool(med.get('indication_secondaire')),
        # Le score clinique, distinct de la note affichee : celle-ci porte les
        # penalites de securite, celui-la non. C'est lui qui classe.
        'pertinence_clinique': med.get('pertinence_clinique'),
        # Ce que le medicament sert, et a quel rang de la conduite.
        #
        # L'ecran ne disposait que de booleens : il pouvait dire « indication
        # principale » sans dire laquelle. Ces trois champs le permettent, et
        # `classe_representee` sort de `condition`, ou elle etait noyee dans
        # une chaine libre.
        'objectif_principal': med.get('objectif_principal') or '',
        'objectif_vise': med.get('objectif_vise') or '',
        'rang_de_ligne': med.get('rang_de_ligne'),
        'classe_representee': med.get('classe_representee') or '',
    }


#: Unités de dosage à retirer d'un traitement saisi en clair.
_UNITES = r'(?:mg|g|µg|mcg|ug|ml|l|ui|u\.?i\.?|%|cp|gel|gtte|bouff\w*)'
_DOSAGE = re.compile(r'\b\d+[\d.,/]*\s*' + _UNITES + r'\b', re.I)
_NOMBRES = re.compile(r'\b\d+[\d.,/]*\b')
_PARENTHESES = re.compile(r'\([^)]*\)')
_APRES_BARRE = re.compile(r'/\s*\w+')
_POSOLOGIE = re.compile(
    r'\b(?:le |au |du |par |a |de )?'
    r'(?:soir|matin|midi|nuit|jour|semaine|mois|prise|fois|'
    r'comprime|comprimes|gelule|gelules|sachet|sachets|'
    r'bouffee|bouffees|goutte|gouttes|inhalation|inhalations)\b')


def _plier(texte: str) -> str:
    """Minuscule sans accent : « Ibuprofène » et « ibuprofene » se valent."""
    sans_accent = unicodedata.normalize('NFD', texte)
    return ''.join(c for c in sans_accent
                   if unicodedata.category(c) != 'Mn').lower()


#: Séparateurs d'une saisie de traitements en clair.
#:
#: Le médecin n'écrit pas une liste, il écrit des phrases : « Ventoline en
#: inhalation si besoin. Cétirizine 10 mg pendant les périodes allergiques. »
#: Le découpage ne connaissait que la virgule : la saisie entière devenait un
#: seul traitement, et aucun des deux n'était reconnu.
#:
#: La virgule et le point ne séparent que s'ils ne sont pas suivis d'un
#: chiffre : en français, « Ventoline 0,5 mg » porte une virgule décimale, et
#: la couper donnerait « Ventoline 0 » et « 5 mg ».
_SEPARATEURS = re.compile(r'[;\n]+|,(?!\s*\d)|\.(?!\s*\d)')

#: Au-delà, ce n'est plus une ordonnance mais un dossier. La borne existait
#: déjà en aval, dans `check_interactions` ; elle est ici pour que le compte
#: rendu de ce qui n'a pas été reconnu porte sur ce qui a vraiment été lu.
_TRAITEMENTS_MAXIMUM = 20

#: Nombre de mots de tête retenus comme nom possible. Trois suffit : « acide
#: acétylsalicylique » et « insuline glargine » tiennent dedans, et au-delà on
#: ramasse la phrase.
_MOTS_DE_TETE = 3

#: Longueur minimale d'une forme envoyée au catalogue français. Un préfixe
#: court rencontrerait trop de titres.
_LONGUEUR_TITRE_MINIMALE = 4


def decouper_traitements(saisie: str) -> list:
    """Découpe une saisie de traitements en clair.

    Virgule, point, point-virgule et retour à la ligne séparent — sauf quand
    la virgule ou le point sont décimaux.
    """
    morceaux = []
    for morceau in _SEPARATEURS.split(saisie or ''):
        morceau = morceau.strip(' \t.,;-')
        if morceau:
            morceaux.append(morceau)
    return morceaux[:_TRAITEMENTS_MAXIMUM]


def _nom_nettoye(saisie: str) -> str:
    """Retire de la saisie tout ce qui décrit la prise plutôt que la substance."""
    brut = _PARENTHESES.sub(' ', saisie or '')
    brut = _DOSAGE.sub(' ', brut)
    brut = _NOMBRES.sub(' ', brut)
    # « 100 µg/bouffée » laisse « /bouffée » : ce qui suit une barre oblique
    # décrit la prise, jamais la substance.
    brut = _APRES_BARRE.sub(' ', brut)
    nom = _POSOLOGIE.sub(' ', _plier(brut))
    return re.sub(r'\s{2,}', ' ', nom).strip(' .,;-')


def _prefixes(nom: str) -> list:
    """Rend les préfixes de mots, du plus long au plus court.

    `_POSOLOGIE` est une **liste fermée** de mots — soir, matin, comprimé,
    inhalation. Elle retire « inhalation » de « Ventoline en inhalation si
    besoin » et laisse « ventoline en si besoin », qui ne ressemble à rien.
    Une liste blanche ne couvrira jamais de la prose libre, et l'allonger à
    chaque tournure rencontrée est une course perdue d'avance.

    Le nom du médicament, lui, est **en tête** : ce qui suit décrit la prise.
    Partir des préfixes retourne le problème — au lieu d'énumérer ce qu'il
    faut jeter, on énumère ce qu'on garde.
    """
    mots = nom.split()
    return [' '.join(mots[:n]) for n in range(min(_MOTS_DE_TETE, len(mots)), 0, -1)]


def formes_candidates(saisie: str) -> list:
    """Rend les écritures sous lesquelles une **substance DrugBank** est connue.

    Le médecin écrit « Warfarine 5 mg ». Le graphe range ses substances sous
    leur dénomination anglaise, « Warfarin ». Entre les deux il faut retirer le
    dosage, la forme et la posologie, plier les accents, puis essayer les
    quelques règles de suffixe qui séparent les deux langues. Ce sont celles
    que la campagne d'appariement du projet employait sous le nom
    « dci_translated ».

    Aucune de ces règles n'est infaillible : « insuline glargine » ne devient
    pas « insulin glargine ». C'est la raison pour laquelle l'appelant doit
    dire ce qu'il n'a pas su reconnaître, plutôt que de se taire.
    """
    nom = _nom_nettoye(saisie)
    if len(nom) < 3:
        return []

    formes = []
    for prefixe in _prefixes(nom):
        variantes = {prefixe}
        if prefixe.endswith('ine'):        # warfarine -> warfarin
            variantes.add(prefixe[:-1])
        if prefixe.endswith('e'):          # ibuprofene -> ibuprofen
            variantes.add(prefixe[:-1])
        if prefixe.endswith('lline'):      # amoxicilline -> amoxicillin
            variantes.add(prefixe[:-1])
        # Du plus long au plus court à l'intérieur d'un même préfixe : la
        # forme entière avant sa troncature.
        for forme in sorted(variantes, key=len, reverse=True):
            if len(forme) >= 3 and forme not in formes:
                formes.append(forme)
    return formes


def formes_specialite(saisie: str) -> list:
    """Rend les écritures sous lesquelles une **spécialité française** est connue.

    Séparée de `formes_candidates()` à dessein : les règles de suffixe
    anglicisent, et un titre du catalogue est français. Les mélanger a une
    conséquence mesurée pendant l'enquête — « insuline » devenait « insulin »,
    qui se retrouve à l'intérieur de *INSULIN LISPRO*, et le repli attribuait
    à la glargine les interactions de la lispro.

    C'est le défaut du § 2.4 du rapport, sous une autre forme.
    """
    nom = _nom_nettoye(saisie)
    if len(nom) < _LONGUEUR_TITRE_MINIMALE:
        return []
    return [p for p in _prefixes(nom) if len(p) >= _LONGUEUR_TITRE_MINIMALE]


def resoudre_traitements(saisies: list, session) -> tuple:
    """Rattache chaque traitement saisi à une substance du graphe.

    Deux chemins, dans cet ordre : la dénomination commune, puis le nom
    commercial. « Warfarine » trouve la substance directement ; « DOLIPRANE »
    passe par la spécialité, qui porte la sienne.

    Rend les traitements reconnus et ceux qui ne l'ont pas été. Les seconds
    comptent autant que les premiers : sans eux, une ordonnance à moitié lue
    passerait pour une ordonnance sans interaction.
    """
    reconnus, non_reconnus = [], []
    for saisie in saisies:
        saisie = (saisie or '').strip()
        if not saisie:
            continue
        formes = formes_candidates(saisie)
        if not formes:
            non_reconnus.append(saisie)
            continue

        ligne = session.run("""
            UNWIND range(0, size($formes) - 1) AS rang
            WITH rang, $formes[rang] AS f
            MATCH (sub:DrugbankSubstance) WHERE toLower(sub.name) = f
            RETURN sub.name AS nom
            ORDER BY rang
            LIMIT 1
        """, formes=formes).single()

        if not ligne:
            titres = formes_specialite(saisie)
            # Le repli n'accepte qu'une spécialité ne portant qu'une seule
            # substance. Sans cette réserve, « paracetamol » tombait sur
            # TRAMADOL/PARACETAMOL et rendait Tramadol : l'écran attribuait
            # alors au paracétamol les interactions du tramadol, ce qui est
            # pire que de ne rien trouver. « doliprane » tombait de même sur
            # CODOLIPRANE, et « amoxicilline » sur l'association à l'acide
            # clavulanique.
            #
            # `STARTS WITH` et non `CONTAINS` : une spécialité commence par le
            # nom de ce qu'elle contient. La sous-chaîne, elle, rapprochait
            # « cetirizine » de LEVOCETIRIZINE et « insulin » d'INSULIN
            # LISPRO — deux molécules différentes de celle saisie. C'est le
            # même défaut qu'au § 2.4, et la même classe de piège que « anti »
            # dans « ORGARAN 750 U.I. anti-Xa » au § 2.7.
            #
            # Le tri par `rang` fait passer le préfixe le plus long d'abord :
            # « insuline glargine » est essayé avant « insuline ». Sans lui,
            # le tri par longueur de titre choisissait la spécialité la plus
            # courte toutes formes confondues, et la forme la plus vague
            # l'emportait sur la plus précise.
            ligne = titres and session.run("""
                UNWIND range(0, size($titres) - 1) AS rang
                WITH rang, $titres[rang] AS f
                MATCH (m:Medicine)-[:HAS_DRUGBANK_SUBSTANCE]->(sub:DrugbankSubstance)
                WHERE toLower(m.title) STARTS WITH f
                WITH rang, m, collect(DISTINCT sub) AS subs
                WHERE size(subs) = 1
                RETURN subs[0].name AS nom
                ORDER BY rang, size(m.title)
                LIMIT 1
            """, titres=titres).single()

        if ligne:
            reconnus.append({'saisie': saisie, 'substance': ligne['nom']})
        else:
            non_reconnus.append(saisie)

    return reconnus, non_reconnus


def check_interactions(current_medications: list, suggested_medications: list):
    """
    Vérifie les interactions entre les traitements en cours et les médicaments
    **effectivement proposés à l'écran**.

    Trois défauts corrigés ici, tous silencieux.

    Le premier : la fonction lisait `m.get('title')` sur les médicaments
    suggérés. Le repli clinique nomme les siens `name`, si bien que la liste
    des suggérés sortait vide et que la fonction rendait `[]` sans avoir rien
    vérifié. Un écran affichant de l'ibuprofène à une patiente sous warfarine
    ne montrait aucune alerte.

    Le deuxième : le contrôle tournait sur la liste d'avant filtrage, alors que
    l'écran affiche celle d'après. Les deux n'ont aucune raison de coïncider.

    Le troisième : le rapprochement comparait la saisie du médecin au titre
    d'une spécialité française. « Warfarine » ne correspond à aucun titre du
    catalogue, la warfarine étant vendue sous le nom de Coumadine. Le
    rapprochement passe désormais par la substance.

    Aucun niveau de gravité n'est renvoyé : la source n'en porte pas
    (cf. rapport P9-1). Une gradation inventée à cet endroit orienterait une
    décision de prescription.

    Rend un état, et pas seulement une liste : « aucune interaction trouvée »
    et « rien n'a pu être vérifié » ne doivent pas se ressembler à l'écran.
    """
    vide = {'interactions': [], 'etat': 'non_verifiable',
            'reconnus': [], 'non_reconnus': [], 'paires_verifiees': 0,
            'tronque': False}

    connector = getattr(current_app, 'neo4j', None)
    if not connector or not getattr(connector, 'driver', None):
        logger.warning("Neo4j indisponible : interactions non verifiees")
        return vide

    # Les bornes sont des garde-fous de charge, **pas** un filtre.
    #
    # Elles valaient dix de chaque côté, et la pénalité de `peser_la_securite`
    # se calcule sur ce que cette fonction rend : un candidat dont l'arête
    # DrugBank tombait au-delà de la coupure ressortait sans pénalité et sans
    # mention — c'est-à-dire comme un candidat que le graphe ne relie à rien.
    # Mesuré sur une décompensation : PRESTOLE était pénalisé chez un patient
    # sous bisoprolol seul, et ne l'était plus chez le même patient sous
    # bisoprolol **et** furosémide et ramipril ; ESIDREX faisait l'inverse.
    # Ajouter un traitement en cours faisait donc disparaître une interaction.
    courants = [m.strip() for m in current_medications if m and m.strip()]
    if not courants:
        return dict(vide, etat='aucun_traitement')
    tronque = len(courants) > LIMITE_TRAITEMENTS_INTERACTION
    courants = courants[:LIMITE_TRAITEMENTS_INTERACTION]

    suggeres = []
    for med in suggested_medications:
        nom = (med.get('title') or med.get('name') or '').strip()
        if nom:
            suggeres.append(nom)
    if not suggeres:
        return dict(vide, etat='aucune_suggestion')
    tronque = tronque or len(suggeres) > LIMITE_CANDIDATS_INTERACTION
    suggeres = suggeres[:LIMITE_CANDIDATS_INTERACTION]
    if tronque:
        # Dit, jamais silencieux : une liste coupée ne doit pas se lire comme
        # une liste complète.
        logger.warning(
            "Interactions : borne de charge atteinte (%d traitement(s), "
            "%d candidat(s)) — le controle est partiel",
            len(current_medications or []), len(suggested_medications or []))

    try:
        with connector.driver.session(database=connector.database) as session:
            reconnus, non_reconnus = resoudre_traitements(courants, session)
            suggeres_reconnus, suggeres_inconnus = resoudre_traitements(
                suggeres, session)

            if not reconnus or not suggeres_reconnus:
                return {'interactions': [], 'etat': 'non_appariees',
                        'reconnus': reconnus, 'non_reconnus': non_reconnus,
                        'paires_verifiees': 0, 'tronque': tronque}

            # Sans `LIMIT`. Le résultat est déjà borné par le `DISTINCT` sur
            # les paires `courants × suggérés`, et une coupure ici ne choisit
            # pas les paires les plus graves — la relation n'en porte pas la
            # gravité — mais celles que le graphe rend en premier. L'`ORDER BY`
            # ne sert donc pas à filtrer : il rend l'affichage reproductible,
            # Neo4j ne garantissant aucun ordre sans lui.
            rows = session.run("""
                UNWIND $courants AS c
                UNWIND $suggeres AS s
                MATCH (s1:DrugbankSubstance), (s2:DrugbankSubstance)
                WHERE s1.name = c.substance AND s2.name = s.substance
                MATCH (s1)-[r:INTERACTS_WITH]-(s2)
                RETURN DISTINCT c.saisie AS courant, s.saisie AS suggere,
                       s1.name AS substance1, s2.name AS substance2,
                       r.description AS description
                ORDER BY suggere, courant, description
            """, courants=reconnus, suggeres=suggeres_reconnus)

            # Les énoncés de DrugBank sont en anglais. `interaction_i18n` les
            # traduit par **remplacement dans des phrases françaises écrites
            # d'avance** : 27 trames et 125 termes couvrent 99,86 % du
            # catalogue, et les noms de substance ne sont jamais traduits — se
            # tromper sur le nom d'une molécule dans un outil de prescription
            # est la faute qu'on ne peut pas se permettre.
            #
            # Il rend `None` sur ce qu'il ne reconnaît pas, et l'anglais reste
            # alors tel quel : une phrase à moitié française serait pire, elle
            # laisserait croire à une traduction complète.
            #
            # Le module servait déjà à la fiche médicament et à l'ordonnance,
            # jamais à la prescription — les deux écrans qui décident.
            interactions = []
            for row in rows:
                anglais = row['description'] or ''
                francais = interaction_i18n.traduire(anglais) if anglais else ''
                interactions.append({
                    'medicine1': f"{row['courant']} ({row['substance1']})",
                    'medicine2': f"{row['suggere']} ({row['substance2']})",
                    'description': francais or anglais,
                    # L'écran doit pouvoir dire qu'un énoncé est resté en
                    # anglais faute de trame, plutôt que de le faire passer
                    # pour du français.
                    'traduit': bool(francais),
                    'symptoms': [],
                })

        paires = len(reconnus) * len(suggeres_reconnus)
        logger.info("Interactions : %d trouvee(s) sur %d paire(s) verifiee(s), "
                    "%d traitement(s) non reconnu(s)",
                    len(interactions), paires, len(non_reconnus))
        return {
            # La liste entière, et non les dix premières.
            #
            # `peser_la_securite` cherche ici l'interaction qui concerne
            # chaque candidat : ce qui manque à la liste devient une absence
            # de pénalité, donc une apparence de sûreté. Le front n'en souffre
            # pas — `interactionsDe(med.title, …)` filtre déjà par fiche, et
            # une liste complète lui rend celles qu'il perdait.
            'interactions': interactions,
            'etat': 'trouvees' if interactions else 'aucune',
            'reconnus': reconnus,
            'non_reconnus': non_reconnus,
            'paires_verifiees': paires,
            'tronque': tronque,
        }

    except Exception as e:
        logger.error(f"Erreur vérification interactions: {e}")
        return vide


#: Antécédents trop courts ou trop vagues pour être confrontés à un RCP.
#: « HTA » figure dans peu de rubriques 4.3 sous cette forme, et un terme de
#: trois lettres rencontre trop de mots par hasard.
_LONGUEUR_TERME_MINIMALE = 5

#: Mots de liaison qu'une saisie d'antécédents contient sans qu'ils désignent
#: quoi que ce soit.
_MOTS_VIDES = {'aucun', 'aucune', 'traite', 'traitee', 'ancien', 'ancienne',
               'depuis', 'annees', 'legere', 'legers', 'severe', 'moderee',
               'chronique', 'type', 'stade'}


def termes_des_antecedents(antecedents: str) -> list:
    """Découpe une saisie libre d'antécédents en groupes de mots.

    Le médecin écrit « Hypertension artérielle, diabète de type 2,
    insuffisance rénale légère ». Chaque segment donne un groupe, et c'est le
    groupe entier qui devra se retrouver dans une phrase du RCP.

    Le mot seul ne suffit pas : « insuffisance » rencontrait « insuffisance
    hépatique sévère » chez une patiente dont l'insuffisance est rénale, et
    « hypertension » puis « artérielle » signalaient deux fois la même
    phrase. Un antécédent est une expression, pas une liste de mots.
    """
    groupes = []
    for segment in re.split(r'[,;.\n]+', antecedents or ''):
        libelle = segment.strip()
        mots = [m for m in re.split(r'\s+', _plier(libelle)) if m]
        mots = [m for m in mots
                if len(m) >= _LONGUEUR_TERME_MINIMALE and m not in _MOTS_VIDES]
        if mots:
            groupes.append({'libelle': libelle, 'mots': mots})
    return groupes[:10]


#: Longueur en deçà de laquelle une correspondance par inclusion ne prouve
#: rien : « ur » se retrouve dans « urée » comme dans cent autres mots.
_LONGUEUR_SUBSTANCE_MINIMALE = 4


def ecart_de_substance(annoncee: str, reelles) -> bool:
    """Dit si la substance annoncée contredit celle de la fiche.

    La comparaison est indulgente à dessein : accents et casse pliés, et
    l'inclusion joue dans les deux sens. Une fiche nomme souvent le sel —
    « périndopril arginine » là où le modèle dit « périndopril » — et ce n'est
    pas une invention, c'est une précision.

    **Ne rien savoir n'est pas constater un écart.** Sans substance annoncée,
    ou sans substance en base, la fonction rend `False` : signaler dans le
    doute ferait perdre au signalement tout son poids, et c'est précisément ce
    signalement qui doit rester crédible.
    """
    annoncee = _plier(str(annoncee or '')).strip()
    connues = [_plier(str(s or '')).strip() for s in (reelles or [])]
    connues = [s for s in connues if s]
    if not annoncee or not connues:
        return False
    if len(annoncee) < _LONGUEUR_SUBSTANCE_MINIMALE:
        return True
    for connue in connues:
        if len(connue) < _LONGUEUR_SUBSTANCE_MINIMALE:
            continue
        if annoncee in connue or connue in annoncee:
            return False
    return True


def confronter_substances(medications: list) -> list:
    """Remplace la substance annoncée par celle de la fiche, et dit l'écart.

    Pourquoi cette fonction existe
    ------------------------------
    La prescription par diagnostic laisse un modèle de langage choisir les
    médicaments, et ce modèle annonce leur substance. Mesuré sur « pneumonie
    communautaire » : HELIKIT 75 mg annoncé comme contenant de la
    « clarithromycine », alors que la fiche porte « urée 13 C ». HELIKIT est un
    test respiratoire pour détecter *H. pylori*, il ne contient aucun
    antibiotique.

    Le pire n'était pas l'invention, c'était sa validation : la notation lisait
    la substance annoncée, trouvait « clarithromycine » dans la table des
    pathologies, et accordait 50 points à un test diagnostique. Le score, censé
    mesurer la pertinence, récompensait une hallucination — alors que la fiche
    était relue dix lignes plus loin pour les contre-indications.

    Les fiches sont relues par identifiant, en une seule requête, comme le fait
    déjà `filter_contraindications`.
    """
    if not medications:
        return medications

    par_identifiant = {}
    for med in medications:
        brut = med.get('fiche_id') or med.get('id') or med.get('_id')
        try:
            par_identifiant.setdefault(ObjectId(brut), []).append(med)
        except Exception:
            continue
    if not par_identifiant:
        return medications

    try:
        fiches = db.medicines.find(
            {'_id': {'$in': list(par_identifiant)}},
            {'title': 1, 'medicine_details.substances_actives': 1})
    except Exception as err:
        logger.warning("Confrontation des substances : %s", err)
        return medications

    ecarts = 0
    for fiche in fiches:
        reelles = (fiche.get('medicine_details') or {}).get('substances_actives') or []
        if not reelles:
            continue
        for med in par_identifiant[fiche['_id']]:
            # Selon le moment, l'annonce est dans `substance` (forme du repli
            # clinique et du modèle) ou déjà repliée dans `substances` par
            # `normaliser_medicament`. Ne lire que la première laissait passer
            # l'écart en silence, une fois la normalisation faite.
            annoncees = med.get('substances') or []
            annoncee = med.get('substance') or (annoncees[0] if annoncees else '')
            if ecart_de_substance(annoncee, reelles):
                # L'annonce est conservée, nommée pour ce qu'elle est. C'est le
                # signal le plus utile de l'écran : il dit que le modèle a
                # parlé de ce qu'il ne connaissait pas.
                med['substance_annoncee'] = annoncee
                ecarts += 1
            # La fiche fait foi, écart ou non : c'est elle qui sera notée.
            med['substance'] = ', '.join(str(s) for s in reelles)
            med['substances'] = list(reelles)

    if ecarts:
        logger.warning("Substances annoncees contredites par la fiche : %d sur %d",
                       ecarts, len(medications))
    return medications


# ══ Phase P6 de la roadmap · composition thérapeutique ═══════════════════
#
# L'écran rendait une **liste**. Il rend désormais une **stratégie** : ce qu'on
# donne en premier, ce qu'on donne si le premier ne convient pas, et ce qui
# traite le symptôme sans traiter la cause.
#
# Le rang existait, mais seulement pour les treize conduites curatées. Les
# candidats venus de la génération par classe n'en portaient aucun : sur une
# pneumonie, CLAMOXYL et ERY arrivaient côte à côte sans que rien ne dise
# lequel donner.

#: Classes ATC qui soulagent un symptôme sans traiter sa cause.
#:
#: Elles ne sont **pas** adjuvantes en soi : tout dépend du tableau. Pour une
#: pneumonie, J01 traite la cause et N02 la douleur — N02 est adjuvant. Pour
#: une migraine, N02 **est** le traitement, et rien ne le relègue.
#:
#: La règle qui en découle tient en une phrase : une classe symptomatique
#: devient adjuvante **quand le diagnostic appelle aussi une classe causale**.
CLASSES_SYMPTOMATIQUES = {
    'N02',  # analgésiques
    'R05',  # toux et rhume
    'R06',  # antihistaminiques
    'R01',  # décongestionnants nasaux
    'A03',  # antispasmodiques
    'A07',  # antidiarrhéiques
}


def merite_clinique(med: dict) -> tuple:
    """Clé de départage d'un candidat, du meilleur au moins bon.

    Pourquoi elle existe
    --------------------
    Deux décisions cliniques se prenaient sur la **longueur du nom de
    marque** : le choix des représentants d'une classe, et l'attribution du
    rang de première intention en cas d'égalité de score.

    Mesuré sur une décompensation cardiaque : PRESTOLE, LOGIRENE, MODAMIDE et
    TENSIONORME arrivaient tous à 90. `composer_strategie` comparait par `>`
    strict, donc le premier inséré gardait la place — et l'ordre d'insertion
    venait d'un tri par longueur de titre. PRESTOLE devenait première
    intention parce que son nom est le plus court ; LOGIRENE, qui finissait à
    80 contre 70 après pénalités, passait alternative.

    L'ordre des critères
    --------------------
    1. **La note finale.** C'est elle qui porte la pertinence clinique, les
       contraintes et les pénalités. Elle prime sur tout le reste.
    2. **L'indication principale.** Un médicament dont la vocation répond au
       tableau vaut mieux qu'un autre qui n'y répond que par un emploi second,
       à note égale.
    3. **La mono-substance.** À pertinence comparable, une molécule seule
       représente sa classe mieux qu'une association : elle est plus simple à
       ajuster et n'apporte pas de composant non demandé.
    4. **Le titre, alphabétique.** Départage technique et rien d'autre. Il
       n'entre en jeu que lorsque tout ce qui précède est à égalité, et il
       est là pour rendre le résultat **déterministe** — non pour trancher
       cliniquement.

    Aucun nom de médicament n'est écrit ici : une spécialité jamais rencontrée
    est départagée par les mêmes critères.
    """
    med = med or {}
    # Le score **clinique**, pas la note pénalisée : une interaction de
    # surveillance ne doit pas déclasser un traitement de première ligne. Le
    # repli sur `pertinence` sert aux candidats que la pesée n'a pas encore vus.
    note = med.get('pertinence_clinique')
    if not isinstance(note, (int, float)):
        note = med.get('pertinence')
    note = note if isinstance(note, (int, float)) else 0
    substances = [s for s in (med.get('substances') or []) if s]
    return (
        -note,
        0 if med.get('indication_principale') else 1,
        0 if len(substances) == 1 else 1,
        str(med.get('title') or ''),
    )


def reduire_par_classe(medications, par_classe: int = None) -> list:
    """Ne garde, par classe ATC, que les meilleurs — **après** notation.

    Le quota de `candidats_par_classe()` s'appliquait avant que quoi que ce
    soit ne soit noté : six représentants étaient choisis sur la voie
    d'administration, le nombre de substances et la longueur du nom, et la
    pertinence clinique ne se calculait qu'ensuite, sur des candidats déjà
    retenus. Un traitement de référence écarté là ne pouvait plus revenir.

    Mesuré sur N02 pour une céphalée légère : LAMALINE et PRONTALGINE — deux
    associations opioïdes — occupaient deux des six places, et le paracétamol
    simple n'était jamais découvert.

    Le graphe rend donc large, et la réduction se fait ici, sur `merite_clinique`.
    Un candidat sans groupe ATC n'est jamais retiré : il n'appartient à aucun
    quota, et le supprimer reviendrait à punir l'absence de donnée.
    """
    medications = list(medications or [])
    if not medications:
        return []
    par_classe = par_classe or CANDIDATS_PAR_CLASSE

    comptes = {}
    vues = set()
    gardes = []
    for med in sorted(medications, key=merite_clinique):
        groupes = [g for g in (med.get('groupes_atc') or []) if g]
        if not groupes:
            gardes.append(med)
            continue

        # Une molécule, une place.
        #
        # Le quota d'une classe était consommé par les génériques d'une seule
        # substance : mesuré sur C03, huit spécialités d'éplérénone occupaient
        # toutes les places et le furosémide n'apparaissait plus. Un médecin
        # qui lit six propositions attend six *molécules*, pas six marques du
        # même produit.
        #
        # La meilleure de chaque substance la représente — « meilleure » au
        # sens de `merite_clinique`, donc de la note finale d'abord.
        signature = tuple(sorted(_plier(str(s)) for s in
                                 (med.get('substances') or []) if s))
        if signature and signature in vues:
            continue

        # Une place suffit : un candidat est gardé dès qu'une de ses classes a
        # encore de la place. Exiger que toutes en aient écarterait un
        # médicament utile au motif qu'il appartient aussi à une classe
        # saturée.
        if any(comptes.get(g, 0) < par_classe for g in groupes):
            gardes.append(med)
            if signature:
                vues.add(signature)
            for g in groupes:
                comptes[g] = comptes.get(g, 0) + 1

    if len(gardes) < len(medications):
        logger.info("Reduction par classe : %d candidat(s) sur %d",
                    len(gardes), len(medications))
    return gardes


def composer_strategie(medications, contexte: str = ''):
    """Attribue un rang thérapeutique à chaque proposition.

    Trois règles, dans cet ordre de priorité.

    **Le rang curaté prime.** Les treize conduites cliniques du dépôt disent
    déjà ce qui se donne en première intention ; elles viennent d'une source
    relue, et le rang déduit d'une classe est une inférence qui ne doit pas
    l'écraser.

    **Une classe ne rend qu'une première intention.** Le mieux noté de chaque
    classe la représente, les suivants deviennent des alternatives. C'est ce
    qui rend impossible *par construction* de proposer deux molécules de la
    même classe comme si elles s'additionnaient — le défaut observé quand
    PERINDOPRIL a été proposé à un patient déjà sous Ramipril, deux IEC.

    **Une classe symptomatique devient adjuvante** si le tableau appelle aussi
    une classe causale.

    Un candidat sans classe ne peut pas être rangé par la classe ; il reçoit
    `alternative`, le rang le plus prudent. Le critère de sortie exige que
    chaque proposition en porte un, et « aucun rang » n'est pas un rang.
    """
    if not medications:
        return []

    attendues = classes_atc_attendues(contexte)
    # Une classe causale est attendue par le tableau sans être symptomatique.
    # S'il n'y en a aucune, rien n'est adjuvant : le symptomatique est alors
    # le traitement.
    causales_attendues = attendues - CLASSES_SYMPTOMATIQUES

    # Le meilleur de chaque classe, parmi ceux qui n'ont pas de rang curaté.
    #
    # La comparaison se faisait par `>` strict sur la note : à égalité, le
    # **premier inséré** gardait la place. Et l'ordre d'insertion venait d'un
    # tri par longueur de titre — le rang de première intention se décidait
    # donc, en cas d'égalité, sur la brièveté du nom de marque.
    #
    # Les candidats sont désormais parcourus dans l'ordre de `merite_clinique`,
    # et le premier de chaque classe la représente. Le résultat ne dépend plus
    # de l'ordre dans lequel ils arrivent.
    meilleur_par_classe = {}
    for med in sorted(medications, key=merite_clinique):
        if med.get('rang'):
            continue
        for classe in (med.get('groupes_atc') or []):
            meilleur_par_classe.setdefault(classe, med)

    for med in medications:
        if med.get('rang'):
            continue

        groupes = [g for g in (med.get('groupes_atc') or [])]
        pertinentes = [g for g in groupes if g in attendues] or groupes
        if not pertinentes:
            med['rang'] = 'alternative'
            continue

        # La classe qui vaut à ce candidat sa place : celle qu'il représente
        # le mieux, à défaut la première.
        representee = next(
            (g for g in pertinentes if meilleur_par_classe.get(g) is med), None)

        if representee is None:
            med['rang'] = 'alternative'
        elif (representee in CLASSES_SYMPTOMATIQUES and causales_attendues
              and not med.get('vise_objectif_principal')):
            # Adjuvant seulement si le medicament ne sert PAS ce que le
            # tableau vise en premier.
            #
            # La regle releguait toute classe symptomatique des qu'une classe
            # causale etait attendue, sans regarder l'objectif. Mesure sur
            # « cephalees liees a l'hypertension arterielle » : le tableau
            # appelle C03, C07, C08, C09 **et** N02, l'objectif principal est
            # `antalgie`, et DAFALGAN — cent sur cent — passait adjuvant
            # derriere onze antihypertenseurs a cinquante. Le patient vient
            # pour une cephalee, pas pour son chiffre tensionnel.
            #
            # Le commentaire de `CLASSES_SYMPTOMATIQUES` l'annoncait deja :
            # « elles ne sont pas adjuvantes en soi, tout depend du tableau ».
            # L'implementation ne lisait que la presence d'une causale.
            #
            # Sur une pneumonie, l'objectif principal est l'antibiotherapie :
            # l'antalgique ne le vise pas, et reste adjuvant comme avant.
            med['rang'] = 'adjuvant'
            med['condition'] = med.get('condition') or 'soulagement'
        else:
            med['rang'] = 'premiere_intention'
        med['classe_representee'] = representee or pertinentes[0]
        if not med.get('condition'):
            med['condition'] = 'classe %s' % med['classe_representee']

    medications.sort(key=_ordre_therapeutique)
    return medications


#: Ordre d'affichage des rangs. Une première intention passe devant une
#: alternative, et un candidat sans rang — venu de la recherche vectorielle ou
#: du modèle — se range entre les deux : il n'est pas donné pour une conduite
#: établie, mais rien ne dit non plus qu'il est un second choix.
_ORDRE_RANG = {'premiere_intention': 0, '': 1, 'alternative': 2, 'adjuvant': 3}


def _ordre_therapeutique(med: dict):
    """Rang d'abord, score ensuite.

    L'ordre à l'écran doit être celui du raisonnement clinique : ce qu'on
    donne en premier, puis ce qu'on donne si le premier ne convient pas. Le
    score départage à l'intérieur d'un même rang.
    """
    # Le titre ferme la clé, pour que l'ordre soit **total**.
    #
    # Sans lui, deux candidats de même rang et de même note gardaient l'ordre
    # d'arrivée — le tri de Python étant stable — et l'affichage dépendait donc
    # de l'ordre d'insertion. Ce n'est pas un critère clinique : c'est ce qui
    # rend le résultat reproductible. Les critères cliniques ont déjà tranché
    # au-dessus, dans `merite_clinique`.
    note = med.get('pertinence_clinique')
    if not isinstance(note, (int, float)):
        note = med.get('pertinence') or 0
    return (_ORDRE_RANG.get(med.get('rang') or '', 1),
            -note,
            str(med.get('title') or ''))


# ══ Phase P1 de la roadmap · filtre d'éligibilité ════════════════════════
#
# Le vivier de candidats n'était filtré par rien. Mesuré sur le catalogue :
# **3 547 fiches sur 13 594 ne sont pas commercialisées** — un quart — et
# restaient candidates. 116 autres sont des produits de procédure.
#
# C'est ainsi que SUBSOL SANS POTASSIUM, non commercialisé **et** de voie
# extracorporelle, a été proposé pour une décompensation cardiaque. Deux
# critères déterministes suffisaient à l'écarter ; aucun n'était lu.
#
# Ce filtre ne porte aucun jugement clinique : il constate des faits
# administratifs. C'est ce qui le rend sûr, et c'est pourquoi il vient en
# premier dans la roadmap.

#: Motifs d'inéligibilité, rédigés pour être lus par un professionnel.
MOTIFS_INELIGIBILITE = {
    'non_commercialise':
        "Produit non commercialisé : il ne peut pas être délivré.",
    'produit_de_procedure':
        "Produit de procédure, administré par voie extracorporelle "
        "(hémodialyse, hémofiltration) : ce n'est pas le traitement d'une "
        "pathologie.",
}

#: Voies qui désignent une procédure, non une administration thérapeutique.
#: Cherchées en mot entier : « dialyse » ne doit pas être reconnue dans
#: « prédialyse ». Le projet s'est déjà fait prendre trois fois — « anti »
#: dans « anti-Xa », « cetirizine » dans « LEVOCETIRIZINE », « zona » dans
#: « zonage ».
_VOIES_DE_PROCEDURE = re.compile(
    r'\b(?:hemodialyse|dialyse|hemofiltration|filtration|extracorporelle)\b')


def motif_d_ineligibilite(fiche):
    """Dit pourquoi une fiche n'est pas éligible, ou `None` si elle l'est.

    **Ne rien savoir n'est pas un motif d'exclusion.** Une commercialisation
    ou une voie absente laisse le produit éligible : 1 654 fiches du catalogue
    ne portent aucune voie, et les écarter reviendrait à punir un défaut de
    données plutôt qu'un fait.

    Le cumul rend le motif le plus sûr. Ne pas être commercialisé se constate
    sans jugement ; c'est le motif qui l'emporte.
    """
    if not fiche:
        return None

    commercialisation = (fiche.get('commercialisation') or '').strip()
    if commercialisation and commercialisation != 'Commercialisée':
        return MOTIFS_INELIGIBILITE['non_commercialise']

    voies = fiche.get('voies_administration') or ''
    if isinstance(voies, (list, tuple)):
        voies = ';'.join(str(v) for v in voies)
    if _VOIES_DE_PROCEDURE.search(_plier(str(voies))):
        return MOTIFS_INELIGIBILITE['produit_de_procedure']

    return None


def filtrer_eligibilite(medications) -> tuple:
    """Sépare les candidats éligibles de ceux qu'aucune règle n'a à examiner.

    Rend `(eligibles, écartés)`. Chaque écarté porte `inelligible_car` : rien
    n'est retiré en silence, c'est la règle du § 2.8 appliquée à cet étage.

    Les champs sont lus sur le candidat quand il les porte déjà — la chaîne
    par diagnostic relit les fiches Mongo entières — et relus en **une seule
    requête** sinon, comme le fait `filter_contraindications`.

    L'ordre d'entrée est préservé : le tri par pertinence a lieu ailleurs.
    """
    if not medications:
        return [], []

    # Ce qui manque est relu en une fois. Un candidat qui porte déjà ses
    # champs n'entraîne aucune lecture.
    manquants = {}
    for med in medications:
        if 'commercialisation' in med or 'voies_administration' in med:
            continue
        brut = med.get('fiche_id') or med.get('id') or med.get('_id')
        try:
            manquants.setdefault(ObjectId(brut), []).append(med)
        except Exception:
            continue

    if manquants:
        try:
            for fiche in db.medicines.find(
                    {'_id': {'$in': list(manquants)}},
                    {'commercialisation': 1, 'voies_administration': 1}):
                for med in manquants[fiche['_id']]:
                    med['commercialisation'] = fiche.get('commercialisation')
                    med['voies_administration'] = fiche.get('voies_administration')
        except Exception as err:
            # Une base injoignable ne doit pas vider le vivier : sans donnée,
            # tout reste éligible.
            logger.warning("Filtre d'eligibilite : %s", err)
            return list(medications), []

    eligibles, ecartes = [], []
    for med in medications:
        motif = motif_d_ineligibilite(med)
        if motif:
            med['inelligible_car'] = motif
            # Phase P7 : l'ecran doit pouvoir dire quel etage a ecarte.
            med['motif_ecart'] = motif
            med['etage_ecart'] = 'eligibilite'
            ecartes.append(med)
        else:
            med.pop('inelligible_car', None)
            eligibles.append(med)

    if ecartes:
        logger.info("Eligibilite : %d candidat(s) ecarte(s) sur %d",
                    len(ecartes), len(medications))
    return eligibles, ecartes


# ══ Phase P5 de la roadmap · diagnostic → classes ATC attendues ══════════
#
# C'est la phase que l'architecture classait « élevé — contenu clinique », et
# la seule qui porte un jugement. Tout le reste du système constate des faits :
# un produit est commercialisé ou non, une substance porte un code ATC ou non,
# deux molécules interagissent ou non. Ici, on dit ce qu'un tableau appelle.
#
# **Cette table n'a pas été relue par un professionnel.** Le § 9 de
# l'architecture le pose : une trame est proposable, sa validation ne l'est
# pas. Elle est écrite pour être relue entrée par entrée.
#
# Pourquoi elle est nécessaire
# ----------------------------
# Mesuré sur « pneumonie communautaire » : le vivier retenu comptait 19
# candidats et **zéro antibiotique**. Un filtre retire, il n'ajoute jamais.
# Sans savoir qu'une pneumonie appelle J01, ni le filtrage ni la génération ne
# peuvent redresser cela.
#
# Le grain
# --------
# Niveau 2 de la classification ATC — trois caractères, `J01`, `C09`, `R03`.
# Assez fin pour distinguer un antibiotique d'un antihypertenseur, assez large
# pour ne pas dépendre de la molécule exacte. C'est aussi le grain que
# `groupes_atc_des()` relit dans le graphe.

#: Diagnostic reconnu → groupes ATC de niveau 2 qu'il appelle.
#:
#: Les clés se cherchent en **mot entier, accents pliés, pluriel toléré** —
#: même règle que `PATHOLOGIE_CLASS_MAP`, dont cette table est le pendant en
#: codes ATC plutôt qu'en noms de classes.
#:
#: Elle est **volontairement courte**. Un diagnostic absent ne rend aucune
#: classe attendue, et l'appelant ne filtre alors pas : ne rien savoir n'est
#: pas savoir que rien ne convient.
DIAGNOSTIC_ATC_MAP = {
    # ── Infections respiratoires ──────────────────────────────────────────
    'pneumonie': {'J01', 'N02'},
    'pneumopathie': {'J01', 'N02'},
    'angine': {'J01', 'N02'},
    'pharyngite': {'J01', 'N02'},
    'otite': {'J01', 'N02'},
    'sinusite': {'J01', 'R01', 'N02'},
    'bronchite': {'R05', 'N02', 'J01'},
    'bronchiolite': {'R03', 'R05'},
    'grippe': {'N02', 'J05'},
    'rhinopharyngite': {'N02', 'R01', 'R05'},

    # ── Voies urinaires ───────────────────────────────────────────────────
    'cystite': {'J01'},
    'infection urinaire': {'J01'},
    'pyélonéphrite': {'J01'},
    'prostatite': {'J01'},

    # ── Voies respiratoires chroniques ────────────────────────────────────
    'asthme': {'R03'},
    'bronchopneumopathie': {'R03', 'H02', 'J01'},
    'bpco': {'R03', 'H02'},
    'emphysème': {'R03'},

    # ── Allergie ──────────────────────────────────────────────────────────
    'rhinite allergique': {'R06', 'R01'},
    'urticaire': {'R06', 'H02'},
    'conjonctivite allergique': {'S01', 'R06'},
    'eczéma': {'D07'},
    'dermatite': {'D07'},

    # ── Digestif ──────────────────────────────────────────────────────────
    'gastro-entérite': {'A07', 'A03'},
    'reflux': {'A02'},
    'gastrite': {'A02'},
    'ulcère gastroduodénal': {'A02', 'J01'},
    'constipation': {'A06'},
    'colique néphrétique': {'M01', 'N02', 'A03'},
    'hémorroïde': {'C05'},

    # ── Douleur et appareil locomoteur ────────────────────────────────────
    'lombalgie': {'M01', 'N02', 'M03'},
    'sciatique': {'M01', 'N02'},
    'arthrose': {'M01', 'N02'},
    'tendinite': {'M01', 'N02'},
    'goutte': {'M01', 'M04'},
    'migraine': {'N02'},
    'céphalée': {'N02'},

    # ── Cardiovasculaire et métabolique ───────────────────────────────────
    'hypertension artérielle': {'C09', 'C08', 'C03', 'C07'},
    'insuffisance cardiaque': {'C03', 'C09', 'C07'},
    'décompensation cardiaque': {'C03', 'C09'},
    'fibrillation auriculaire': {'B01', 'C01', 'C07'},
    'angor': {'C01', 'C07', 'C08'},
    'diabète': {'A10'},
    'hypercholestérolémie': {'C10'},
    'dyslipidémie': {'C10'},

    # ── Psychiatrie et neurologie ─────────────────────────────────────────
    'dépressif': {'N06'},
    'dépression': {'N06'},
    'anxieux': {'N05', 'N06'},
    'anxiété': {'N05', 'N06'},
    'insomnie': {'N05'},
    'épilepsie': {'N03'},

    # ── Divers ────────────────────────────────────────────────────────────
    'conjonctivite': {'S01'},
    'zona': {'J05', 'N02'},
    'herpès': {'J05'},
    'mycose': {'D01', 'J02'},
    'candidose': {'D01', 'J02'},
}


# ══ Ce qu'un tableau cherche à obtenir, et ce qu'un médicament sait faire ══
#
# Pourquoi ces deux tables existent
# ---------------------------------
# La classe ATC servait à la fois à **découvrir** des candidats et à les
# **noter**. Une correspondance de classe valait 60 points pour un seuil à 40 :
# elle suffisait donc, à elle seule et avec 50 % de marge, à faire recommander
# un médicament.
#
# Mesuré sur « céphalées légères, suspicion d'HTA récente » — qui appelle
# `{C03, C07, C08, C09, N02}` :
#
#     CELEBREX  (célécoxib)   60  « Pertinent pour: classe C08 »
#     LASILIX   (furosémide) 100  « Pertinent pour: classe C03, diurétique »
#     OXYNORM   (oxycodone)   60  « Pertinent pour: classe N02 »
#     TIMACOR   (timolol)     60  « Pertinent pour: classe C07 »
#
# Le moteur n'affirmait pas que le célécoxib traite l'hypertension : il disait
# qu'il porte un code. La confusion était entre « cette classe a un rapport
# avec le domaine » et « ce médicament convient à ce patient ».
#
# La donnée qui tranche existait déjà. `explication_atc_des()` lit
# `DrugbankSubstance.indication` depuis P7 — 1 486 substances sur 1 633 en
# portent une — et ne s'en servait que comme légende, **après** la notation :
#
#     Célécoxib   « symptomatic treatment of adult osteoarthritis … »
#     Furosémide  « edema associated with congestive heart failure … »
#     Ramipril    « management of mild to severe hypertension … »
#     Timolol     « increased intraocular pressure … »   (c'est un collyre)
#
# Ces quatre phrases suffisent à trier ce que la classe ATC confondait. Elles
# entrent donc maintenant dans la note, et l'ATC redevient ce qu'il aurait dû
# rester : un mécanisme de **découverte**, qui garantit qu'aucune classe utile
# n'est manquée, jamais une preuve de pertinence.
#
# Le détour par un objectif thérapeutique, plutôt qu'un rapprochement direct
# entre le diagnostic et l'indication, tient à une raison simple : les
# indications DrugBank sont **en anglais** et les tableaux cliniques en
# français. L'objectif est le pivot entre les deux vocabulaires.

#: Ce qu'un tableau clinique cherche à obtenir.
#:
#: **Cette table n'a pas été relue par un professionnel**, comme
#: `DIAGNOSTIC_ATC_MAP` (§ 9). Elle est écrite pour être relue entrée par
#: entrée. Un diagnostic absent d'ici ne déclenche aucun tri par indication :
#: ne rien savoir n'est pas savoir que rien ne convient.
OBJECTIFS_THERAPEUTIQUES = {
    # ── Cardiovasculaire ──────────────────────────────────────────────────
    # L'hypertension appelle à abaisser la pression — pas à déshydrater.
    # C'est la distinction que le seul C03 ne pouvait pas faire : le
    # furosémide et le bumétanide y figurent pour l'œdème, pas pour l'HTA.
    'hypertension': ('antihypertension',),
    'hta': ('antihypertension',),
    'poussée hypertensive': ('antihypertension',),
    # La congestion d'abord : c'est elle qu'une décompensation met en jeu.
    # Le contrôle tensionnel reste un objectif, mais second.
    'insuffisance cardiaque': ('decongestion', 'antihypertension'),
    'décompensation cardiaque': ('decongestion', 'antihypertension'),
    'oedème': ('decongestion',),
    'œdème': ('decongestion',),
    'congestion': ('decongestion',),
    'fibrillation auriculaire': {'antiarythmie', 'anticoagulation'},
    'angor': {'antiangineux', 'antihypertension'},
    'infarctus': {'antiangineux', 'anticoagulation'},
    'thrombose': {'anticoagulation'},
    'embolie pulmonaire': {'anticoagulation'},
    'hypercholestérolémie': {'hypolipemie'},
    'dyslipidémie': {'hypolipemie'},

    # ── Douleur et fièvre ─────────────────────────────────────────────────
    'céphalée': ('antalgie',),
    'céphalées': ('antalgie',),
    'migraine': ('antimigraineux', 'antalgie'),
    'lombalgie': ('antalgie', 'anti_inflammation'),
    'sciatique': {'antalgie', 'anti_inflammation'},
    'arthrose': {'antalgie', 'anti_inflammation'},
    'tendinite': {'antalgie', 'anti_inflammation'},
    'goutte': {'anti_inflammation', 'antigoutteux'},
    'fièvre': ('antipyrexie',),
    'douleur': ('antalgie',),
    'colique néphrétique': {'antalgie', 'antispasme'},

    # ── Infectieux ────────────────────────────────────────────────────────
    'pneumonie': {'antibiotherapie', 'antipyrexie'},
    'pneumopathie': {'antibiotherapie', 'antipyrexie'},
    'angine': {'antibiotherapie', 'antalgie'},
    'otite': {'antibiotherapie', 'antalgie'},
    'sinusite': {'antibiotherapie', 'antalgie'},
    'bronchite': {'antibiotherapie', 'antitussif'},
    'cystite': {'antibiotherapie'},
    'pyélonéphrite': {'antibiotherapie'},

    # ── Respiratoire ──────────────────────────────────────────────────────
    'asthme': {'bronchodilatation', 'anti_inflammation'},
    'bpco': {'bronchodilatation'},
    'toux': {'antitussif'},

    # ── Métabolique et digestif ───────────────────────────────────────────
    'diabète': {'antidiabetique'},
    'reflux': {'antiacide'},
    'ulcère': {'antiacide'},
    'gastrite': {'antiacide'},
    'constipation': {'laxatif'},
    'diarrhée': {'antidiarrheique'},
    'nausée': {'antiemetique'},
    'vomissement': {'antiemetique'},

    # ── Divers ────────────────────────────────────────────────────────────
    'allergie': {'antihistaminique'},
    'rhinite': {'antihistaminique'},
    'anxiété': {'anxiolyse'},
    'dépression': {'antidepression'},
    'insomnie': {'hypnose'},
}


#: Comment reconnaître un objectif dans le texte d'indication de DrugBank.
#:
#: Les marqueurs sont **en anglais** : c'est la langue de la source. Ils sont
#: cherchés en sous-chaîne repliée — « hypertens » attrape *hypertension* et
#: *antihypertensive*.
#:
#: Choisis larges plutôt qu'étroits. Un marqueur trop pointu ferait manquer
#: l'objectif et retirerait ses points à un médicament juste ; l'erreur
#: coûteuse est ici le faux négatif, puisqu'un faux positif laisse simplement
#: le reste de la chaîne — contraintes, interactions, redondance — faire son
#: travail.
INDICATEURS_OBJECTIF = {
    'antihypertension': ['hypertens', 'blood pressure'],
    # L'œdème et la congestion, distincts de l'hypertension : c'est ce qui
    # sépare le furosémide du ramipril quand le tableau ne dit qu'« HTA ».
    'decongestion': ['edema', 'oedema', 'heart failure', 'congestive',
                     'diuretic', 'ascites', 'fluid retention'],
    # `migraine` n'est **pas** un marqueur d'antalgie.
    #
    # Il l'etait, et il l'est aussi d'`antimigraineux` : le mot se trouvait
    # donc a la meme position pour les deux objectifs, et le depart se faisait
    # alphabetiquement — `antalgie` avant `antimigraineux`. Le rizatriptan,
    # indique « for the acute treatment of diagnosed migraine », ressortait
    # donc antalgique general, et MAXALT obtenait le bonus plein pour une
    # cephalee de tension, sur laquelle un triptan est sans effet.
    #
    # Les deux objectifs sont desormais disjoints : `antalgie` couvre la
    # douleur en general, `antimigraineux` la migraine et ses marqueurs
    # propres. Un antalgique vrai reste reconnu par `pain` ou `analgesi`, que
    # tout texte d'indication antalgique contient.
    'antalgie': ['pain', 'analgesi', 'antipyretic'],
    'antimigraineux': ['migraine', 'triptan', 'cluster headache',
                       'headache'],
    'anti_inflammation': ['inflammat', 'arthritis', 'osteoarthritis',
                          'rheumatoid', 'ankylosing'],
    'antipyrexie': ['fever', 'antipyretic', 'pyrexia'],
    'antibiotherapie': ['infection', 'bacteri', 'antibiotic', 'antibacterial'],
    'antiarythmie': ['arrhythmi', 'atrial fibrillation', 'tachycard',
                     'ventricular rate'],
    'anticoagulation': ['thromb', 'anticoagul', 'embolism', 'clot',
                        'antiplatelet', 'stroke prevention'],
    'antiangineux': ['angina', 'ischemi', 'coronary', 'myocardial infarction'],
    'hypolipemie': ['cholesterol', 'lipid', 'hyperlipid', 'dyslipid',
                    'statin', 'triglycerid'],
    'bronchodilatation': ['asthma', 'bronchospasm', 'bronchodilat', 'copd',
                          'obstructive pulmonary'],
    'antitussif': ['cough', 'antitussive', 'expectorant'],
    'antidiabetique': ['diabet', 'glycemic', 'blood glucose', 'hyperglycemi'],
    'antiacide': ['gastroesophageal', 'reflux', 'ulcer', 'gastric acid',
                  'heartburn', 'dyspepsia'],
    'laxatif': ['constipation', 'laxative', 'bowel'],
    'antidiarrheique': ['diarrhea', 'diarrhoea'],
    'antiemetique': ['nausea', 'vomiting', 'emesis', 'antiemetic'],
    'antihistaminique': ['allerg', 'rhinitis', 'urticaria', 'antihistamin'],
    'anxiolyse': ['anxiety', 'anxiolytic', 'panic'],
    'antidepression': ['depress', 'antidepress'],
    'hypnose': ['insomnia', 'sedativ', 'hypnotic', 'sleep'],
    'antigoutteux': ['gout', 'hyperuricemi', 'uric acid'],
    'antispasme': ['spasm', 'colic', 'antispasmodic'],

    # ── Domaines qu'aucun de nos diagnostics n'appelle ────────────────────
    #
    # Ils ne figurent dans aucune entrée d'`OBJECTIFS_THERAPEUTIQUES` : ils ne
    # sont donc jamais *visés*. Leur rôle est de rendre l'indication
    # **lisible**, ce qui transforme un « inconnu » en « non ».
    #
    # Sans eux, le timolol ophtalmique — « increased intraocular pressure » —
    # ne rencontrait aucun marqueur, était déclaré illisible, et gardait ses
    # points au bénéfice du doute. C'est ainsi que TIMACOR remontait pour une
    # céphalée. Élargir le vocabulaire vaut mieux qu'écarter la molécule : tout
    # collyre à venir en profite, sans qu'on ait à le nommer.
    'ophtalmologie': ['intraocular', 'ocular', 'glaucoma', 'ophthalmic',
                      'conjunctiv', 'uveitis', 'eye'],
    'dermatologie': ['dermat', 'psoriasis', 'eczema', 'acne', 'skin',
                     'topical'],
    'oncologie': ['carcinoma', 'tumor', 'tumour', 'neoplas', 'lymphoma',
                  'leukemia', 'chemotherap', 'metasta'],
    'immunosuppression': ['immunosuppress', 'transplant', 'graft rejection'],
    'hormonal': ['contracept', 'hormone replacement', 'testosterone',
                 'estrogen', 'thyroid', 'hypothyroid'],
    'osteoporose': ['osteoporosis', 'bone mineral density', 'paget'],
    'anesthesie': ['anesthes', 'anaesthes', 'muscle relaxant during',
                   'induction of'],
    'urologie': ['benign prostatic', 'urinary incontinence', 'overactive '
                 'bladder', 'erectile'],
    'neurologie': ['epilep', 'seizure', 'parkinson', 'multiple sclerosis',
                   'dementia', 'alzheimer'],
    'psychiatrie': ['schizophren', 'bipolar', 'psychosis', 'adhd'],
    'diagnostique': ['diagnostic', 'contrast agent', 'imaging',
                     'radiopharmaceutical'],
}


#: Tournures qui **nient** ce qui les suit.
#:
#: Un compte rendu dit autant ce qu'il écarte que ce qu'il constate : « pas de
#: fièvre », « absence d'œdème », « sans déficit neurologique ». Cherché en
#: simple sous-chaîne, « fièvre » se trouvait dans « pas de fièvre » et faisait
#: viser l'antipyrexie chez un patient apyrétique.
NEGATIONS = ['pas de ', 'pas d ', "pas d'", 'absence de ', 'absence d ',
             "absence d'", 'sans ', 'aucun ', 'aucune ', 'ni ',
             'negatif', 'negative']


def _est_nie(texte: str, position: int) -> bool:
    """Le terme trouvé à cette position est-il précédé d'une négation ?

    On ne remonte que de 24 caractères : au-delà, la négation appartient
    probablement à une autre proposition. « Pas de fièvre, céphalées » ne doit
    pas voir sa négation s'étendre aux céphalées.
    """
    amont = texte[max(0, position - 24):position]
    # La négation doit être dans le même segment : une virgule ou un point la
    # referme.
    dernier = max(amont.rfind(','), amont.rfind('.'), amont.rfind(';'))
    if dernier != -1:
        amont = amont[dernier + 1:]
    return any(n in amont for n in NEGATIONS)


#: Quelles classes thérapeutiques répondent en **première ligne** à un
#: objectif donné.
#:
#: Pourquoi cette table
#: --------------------
#: L'indication réelle ne suffit pas à tout trancher. Le furosémide et le
#: triamtérène disent la même chose — « edema associated with congestive heart
#: failure » — et arrivent donc à la même note, alors qu'un diurétique de
#: l'anse et un épargneur de potassium n'ont pas le même rôle dans une
#: congestion aiguë.
#:
#: DrugBank ne porte pas cette information. Elle est ici, courte et nommée,
#: pour être relue : une ligne par objectif, et **l'ordre des classes est
#: l'affirmation clinique**. Elle n'écarte rien — elle départage à indication
#: équivalente.
#:
#: **Cette table n'a pas été relue par un professionnel**, comme
#: `DIAGNOSTIC_ATC_MAP` et `OBJECTIFS_THERAPEUTIQUES` (§ 9).
CLASSES_DE_PREMIERE_LIGNE = {
    # Une congestion aiguë se traite par la diurèse de l'anse ; les
    # épargneurs de potassium y sont un traitement de fond, pas le moyen de
    # désengorger.
    'decongestion': ('diuretique_anse', 'thiazidique',
                     'epargneur_potassium'),
    # L'hypertension se traite d'abord par les bloqueurs du système
    # rénine-angiotensine, les thiazidiques et les dihydropyridines.
    'antihypertension': ('iec', 'sartan', 'arni', 'thiazidique',
                         'calcique_dihydropyridine'),
    'anticoagulation': ('anticoagulant_direct', 'antivitamine_k'),
    'hypolipemie': ('statine',),
    'antiarythmie': ('betabloquant', 'antiarythmique_iii'),
}


def rang_de_premiere_ligne(med: dict, objectif: str) -> int:
    """Rend le rang du médicament dans la conduite de cet objectif, ou -1.

    **L'ordre du tuple est l'affirmation clinique.** Il ne l'était pas : la
    fonction rendait un booléen, et un thiazidique valait autant qu'un
    diurétique de l'anse pour décongestionner. Mesuré sur une décompensation
    aiguë, ESIDREX sortait à 100 devant BURINEX et le furosémide à 80 — alors
    que c'est l'anse qui désengorge.

    Rang 0 pour la première ligne, 1 pour la suivante, et ainsi de suite.
    Rend -1 quand l'objectif n'a pas de table, quand la substance n'est pas
    reconnue, ou quand sa classe n'y figure pas : le doute ne rapporte rien,
    il ne coûte rien non plus.
    """
    lignes = CLASSES_DE_PREMIERE_LIGNE.get(objectif or '')
    if not lignes:
        return -1
    classes = classes_therapeutiques_de(_texte_du_medicament(med))
    rangs = [i for i, classe in enumerate(lignes) if classe in classes]
    return min(rangs) if rangs else -1


def repond_en_premiere_ligne(med: dict, objectif: str) -> bool:
    """Ce médicament figure-t-il dans la conduite de cet objectif ?

    Conservée pour ce qu'elle dit — l'appartenance — là où le score, lui, a
    besoin du rang.
    """
    return rang_de_premiere_ligne(med, objectif) >= 0


def objectifs_ordonnes_du_tableau(tableau: str) -> tuple:
    """Rend `(principal, tous)` — l'objectif principal du tableau, et tous.

    Pourquoi la distinction
    -----------------------
    Les objectifs étaient un ensemble **non ordonné**. Une décompensation
    cardiaque visait `{antihypertension, décongestion}` sans dire lequel
    importe, si bien qu'un médicament couvrant le contrôle tensionnel marquait
    autant qu'un médicament couvrant la congestion. Mesuré : triamtérène,
    amiloride et énalapril arrivaient tous à 90, comme le furosémide.

    Les entrées cardiovasculaires et antalgiques d'`OBJECTIFS_THERAPEUTIQUES`
    sont désormais des **séquences**, dont le premier élément est l'objectif
    principal. Les autres restent des ensembles et n'ont pas de principal :
    ne pas savoir lequel prime n'est pas savoir qu'ils se valent, mais le
    résultat est le même — aucune graduation ne s'applique.

    L'entrée la plus **spécifique** l'emporte pour désigner le principal :
    « insuffisance cardiaque » prime sur « oedème » quand les deux sont
    reconnus, parce que le terme le plus long décrit le tableau de plus près.
    """
    texte = _plier(tableau or '')
    if not texte:
        return '', set()

    tous = set()
    ordonnes = []
    for terme, vises in OBJECTIFS_THERAPEUTIQUES.items():
        terme_plie = _plier(terme)
        position = texte.find(terme_plie)
        reconnu = -1
        while position != -1:
            if not _est_nie(texte, position):
                reconnu = position
                break
            position = texte.find(terme_plie, position + 1)
        if reconnu < 0:
            continue
        tous |= set(vises)
        # Seule une séquence ordonnée désigne un principal.
        if isinstance(vises, (tuple, list)) and vises:
            ordonnes.append((reconnu, -len(terme_plie), vises[0]))

    # Le terme le plus **tôt** dans le tableau désigne l'objectif principal.
    #
    # `tableau_clinique()` place le diagnostic devant les symptômes, et un
    # compte rendu nomme d'abord ce qu'il traite : « Céphalées liées à
    # l'hypertension » dit que la céphalée est le motif, l'hypertension le
    # contexte. Trier par longueur du terme donnait l'inverse — « hypertension »
    # est plus long que « céphalées » — et faisait viser le contrôle tensionnel
    # chez un patient venu pour un mal de tête.
    #
    # À position égale, le terme le plus long l'emporte : « insuffisance
    # cardiaque » prime sur « cardiaque » seul.
    principal = min(ordonnes)[2] if ordonnes else ''
    return principal, tous


def objectifs_du_tableau(tableau: str) -> set:
    """Rend les objectifs thérapeutiques que le tableau clinique appelle.

    Vide quand rien n'est reconnu, et c'est délibéré : l'appelant ne doit
    alors pas trier par indication. Ne rien savoir n'est pas savoir que rien
    ne convient — c'est la même règle que `classes_atc_attendues()`.

    Un terme nié ne compte pas : « pas de fièvre » ne fait pas viser
    l'antipyrexie.
    """
    texte = _plier(tableau or '')
    if not texte:
        return set()
    objectifs = set()
    for terme, vises in OBJECTIFS_THERAPEUTIQUES.items():
        terme_plie = _plier(terme)
        position = texte.find(terme_plie)
        while position != -1:
            if not _est_nie(texte, position):
                objectifs |= set(vises)
                break
            position = texte.find(terme_plie, position + 1)
    return objectifs


def objectifs_de_l_indication(indication: str) -> set:
    """Rend les objectifs que le texte d'indication DrugBank soutient.

    Vide quand l'indication est absente ou qu'aucun marqueur n'est reconnu.
    L'appelant doit distinguer ces deux cas de « l'indication ne correspond
    pas » : voir `indication_repond_au_tableau()`.
    """
    texte = _plier(indication or '')
    if not texte:
        return set()
    return {objectif for objectif, marqueurs in INDICATEURS_OBJECTIF.items()
            if any(_plier(m) in texte for m in marqueurs)}


def objectif_principal_de_l_indication(indication: str) -> str:
    """Rend la vocation première du médicament, lue sur son indication.

    Pourquoi la position du marqueur
    --------------------------------
    Un texte d'indication énumère plusieurs emplois, et le premier nommé est
    celui pour lequel le médicament existe. Le furosémide est indiqué « for the
    treatment of **edema** associated with congestive heart failure » — puis,
    trois cents caractères plus loin, « and in the treatment of hypertension ».
    Les deux sont vrais ; ils ne pèsent pas pareil.

    C'est ce qui distingue les deux cas que le moteur confondait :

        décompensation cardiaque + furosémide  -> décongestion, sa vocation
        hypertension simple      + furosémide  -> emploi secondaire

    Mesuré sur les textes réels, en position du premier marqueur :

        Furosémide            décongestion  45   antihypertension  297
        Bumétanide            décongestion  21   antihypertension  absent
        Triamtérène           décongestion  46   antihypertension  338
        Bendrofluméthiazide   décongestion  59   antihypertension   26
        Ramipril              décongestion 198   antihypertension   37

    Les diurétiques de l'anse et épargneurs sortent décongestionnants, les
    thiazidiques et les IEC antihypertenseurs. Aucun nom de molécule n'est
    écrit : une substance jamais rencontrée est située par le même calcul.

    Rend une chaîne vide quand l'indication est absente ou illisible.
    """
    texte = _plier(indication or '')
    if not texte:
        return ''
    positions = {}
    for objectif, marqueurs in INDICATEURS_OBJECTIF.items():
        trouvees = [texte.find(_plier(m)) for m in marqueurs
                    if _plier(m) in texte]
        if trouvees:
            positions[objectif] = min(trouvees)
    if not positions:
        return ''
    return min(positions, key=lambda o: (positions[o], o))


def force_de_l_indication(indication: str, tableau: str) -> tuple:
    """Rend `(verdict, objectifs_communs, principal_couvert)`.

    `principal_couvert` dit si la **vocation première** du médicament figure
    parmi les objectifs du tableau. C'est ce qui sépare « ce médicament est
    fait pour ce cas » de « ce médicament peut aussi servir à cela », et le
    score s'appuie sur cette différence plutôt que sur la seule appartenance
    à une classe ATC.
    """
    verdict, communs = indication_repond_au_tableau(indication, tableau)
    if verdict != 'oui':
        return verdict, communs, False
    principal = objectif_principal_de_l_indication(indication)
    return verdict, communs, bool(principal and principal in communs)


def indication_repond_au_tableau(indication: str, tableau: str) -> tuple:
    """L'indication réelle du médicament répond-elle au tableau clinique ?

    Rend `(verdict, objectifs_communs)` où `verdict` vaut :

        'oui'      l'indication soutient au moins un objectif du tableau
        'non'      l'indication est lisible mais ne soutient aucun objectif
        'inconnu'  rien ne permet de trancher

    **`inconnu` n'est pas `non`.** Une indication absente — 147 substances du
    graphe n'en portent pas — ou un graphe injoignable ne prouvent rien. Punir
    dans ce cas viderait l'écran à la première panne de Neo4j, et ferait
    disparaître un médicament juste au motif que la base est incomplète. Le
    doute laisse passer ; c'est la règle du projet depuis `groupes_atc_des()`.
    """
    vises = objectifs_du_tableau(tableau)
    if not vises:
        return 'inconnu', set()

    soutenus = objectifs_de_l_indication(indication)
    if not soutenus:
        return 'inconnu', set()

    communs = vises & soutenus
    return ('oui', communs) if communs else ('non', set())


#: Paliers antalgiques de l'OMS, par substance.
#:
#: L'indication seule ne suffit pas à trier les antalgiques : l'oxycodone est
#: indiquée « for moderate to severe pain », le paracétamol « for mild to
#: moderate pain ». Les deux répondent donc à l'objectif `antalgie`, et une
#: céphalée légère faisait remonter un opioïde.
#:
#: Le palier est une propriété de la **substance**, pas du tableau : il se lit
#: une fois et vaut pour tous les cas. C'est ce qui évite d'écrire une règle
#: par couple douleur/molécule.
PALIER_ANTALGIQUE = {
    1: ['paracetamol', 'acetaminophen', 'ibuprofene', 'ketoprofene',
        'diclofenac', 'naproxene', 'aspirine', 'acetylsalicylique',
        'piroxicam', 'celecoxib', 'meloxicam', 'indometacine',
        'acide mefenamique', 'nefopam', 'floctafenine'],
    # Le néfopam est un antalgique central non opioïde. Il est ici et non au
    # palier 1 parce qu'il s'emploie dans les douleurs modérées à sévères, et
    # parce que le graphe ne porte **aucune** indication pour lui : rien
    # d'autre ne pouvait le situer.
    2: ['codeine', 'tramadol', 'dihydrocodeine', 'opium', 'poudre d opium',
        'nefopam'],
    3: ['morphine', 'oxycodone', 'fentanyl', 'hydromorphone', 'buprenorphine',
        'methadone', 'peth idine', 'nalbuphine', 'tapentadol',
        'sufentanil', 'alfentanil'],
}

#: Comment lire l'intensité d'une douleur dans un tableau clinique.
#:
#: Les mots sont cherchés en sous-chaîne repliée. L'ordre compte : on retient
#: l'intensité **la plus élevée** trouvée, un tableau pouvant mentionner
#: plusieurs douleurs.
INTENSITE_DOULEUR = {
    1: ['legere', 'leger', 'minime', 'faible', 'moderee', 'modere',
        'supportable'],
    2: ['intense', 'vive', 'importante', 'marquee'],
    3: ['severe', 'insupportable', 'atroce', 'refractaire', 'rebelle',
        'tres intense'],
}

#: Ce que coûte un palier antalgique supérieur à l'intensité relevée.
#:
#: Un déclassement, pas une exclusion : la décision revient au médecin, qui
#: peut connaître du tableau ce que la saisie ne dit pas.
PENALITE_PALIER = 25


#: Paliers lus sur le code ATC **de la spécialité**, par préfixe.
#:
#: Pourquoi le code de la spécialité et non celui de la substance
#: --------------------------------------------------------------
#: Les codes ATC portés par une substance DrugBank sont ceux de **toutes** les
#: associations qui la contiennent. Mesuré : LAMALINE, PRONTALGINE et
#: DOLIPRANE — qui pointent tous vers `Acetaminophen` — portent le même jeu de
#: huit codes, dont `N02AJ01` (paracétamol + codéine). S'en servir classerait
#: le DOLIPRANE en palier 2 et le ferait disparaître : l'inverse du but.
#:
#: Le catalogue français porte, lui, un `code_atc` **par spécialité** :
#: `N02AA05` pour OXYNORM, `N02AX02` pour le tramadol, `R05DA04` pour POLERY.
#: Celui-là est juste. Il ne couvre que 59 % des fiches, d'où le maintien de la
#: table par substance : les deux se complètent.
PALIER_PAR_ATC = [
    # Opioïdes forts — naturels, phénylpipéridines, oripavine, morphinanes.
    (3, ('N02AA', 'N02AB', 'N02AD', 'N02AE', 'N02AG')),
    # Opioïdes faibles et associations codéinées. `R05DA` est la codéine
    # employée comme antitussif : POLERY y figure, et c'est bien un opioïde.
    (2, ('N02AJ', 'N02AX', 'R05DA', 'N02CX')),
    # Non-opioïdes : paracétamol, salicylés, pyrazolés, autres.
    (1, ('N02BA', 'N02BB', 'N02BE', 'N02BG')),
]

#: Composants opioïdes à chercher dans la composition du RCP.
#:
#: Dernier recours, quand ni la substance déclarée ni le code ATC ne révèlent
#: l'opioïde. LAMALINE est officiellement `N02BE51` — « paracétamol en
#: association hors psycholeptiques » — et le catalogue ne lui déclare que
#: « Paracétamol » ; sa rubrique 2 dit pourtant « poudre d'opium (titrée à
#: 10 % en morphine base anhydre) ». PRONTALGINE de même, avec « phosphate de
#: codéine hémihydraté ».
COMPOSANTS_OPIOIDES = {
    3: ['morphine', 'oxycodone', 'fentanyl', 'hydromorphone', 'peth idine',
        'opium'],
    2: ['codeine', 'tramadol', 'dihydrocodeine'],
}


def palier_par_atc(code: str) -> int:
    """Rend le palier qu'annonce un code ATC de spécialité, ou 0."""
    code = str(code or '').strip().upper()
    if not code:
        return 0
    for palier, prefixes in PALIER_PAR_ATC:
        if code.startswith(prefixes):
            return palier
    return 0


def palier_par_composition(composition: str) -> int:
    """Rend le palier qu'annonce la composition du RCP, ou 0."""
    texte = _plier(composition or '')
    if not texte:
        return 0
    for palier in (3, 2):
        for composant in COMPOSANTS_OPIOIDES[palier]:
            if re.search(r'\b%s' % re.escape(composant), texte):
                return palier
    return 0


def palier_antalgique(medication: dict) -> int:
    """Rend le palier OMS d'un antalgique, ou 0 si ce n'en est pas un.

    Trois sources, du plus fin au plus large, et **le plus élevé l'emporte** :
    la composition du RCP, le code ATC de la spécialité, la table par
    substance. Aucune ne suffit seule.

    Mesuré sur le cas signalé : LAMALINE et PRONTALGINE étaient proposés à 100
    pour une céphalée légère. Le catalogue ne leur déclare que « Paracétamol »,
    leur code ATC officiel est celui d'une association banale, et seule la
    rubrique 2 du RCP dit qu'ils contiennent de l'opium et de la codéine.
    """
    texte = _texte_du_medicament(medication)
    par_substance = 0
    for palier in (3, 2, 1):
        if any(re.search(r'\b%s' % re.escape(_plier(s)), texte)
               for s in PALIER_ANTALGIQUE[palier]):
            par_substance = palier
            break

    return max(par_substance,
               palier_par_atc(medication.get('code_atc')),
               palier_par_composition(medication.get('composition')))


def intensite_douleur(tableau: str) -> int:
    """Rend l'intensité de douleur que le tableau décrit, ou 0 s'il se tait.

    Zéro veut dire « non précisé », pas « nulle » : l'appelant ne doit alors
    pas déclasser. Une douleur dont l'intensité n'est pas dite ne justifie ni
    l'opioïde ni son refus.
    """
    texte = _plier(tableau or '')
    if not texte:
        return 0
    trouvee = 0
    for niveau in (1, 2, 3):
        if any(_plier(mot) in texte for mot in INTENSITE_DOULEUR[niveau]):
            trouvee = max(trouvee, niveau)
    return trouvee


def attacher_indications(medications) -> tuple:
    """Pose `indication_source` sur chaque fiche, et rend la lecture du graphe.

    Pourquoi cette fonction existe
    ------------------------------
    L'indication réelle décide désormais si un candidat découvert par sa
    classe ATC mérite ses points. Encore faut-il qu'elle soit là **avant** la
    notation.

    Elle ne l'était pas. Posée dans `appliquer_controles`, elle n'atteignait
    rien : sur l'assistant, la notation a lieu plus tôt, dans
    `analyze_patient`, et la boucle d'`appliquer_controles` saute tout
    médicament déjà noté. Mesuré bout en bout après ce premier branchement :
    27 propositions, célécoxib toujours à 60 « Pertinent pour: classe C08 »,
    **zéro** écarté pour indication. Le tri fonctionnait en test unitaire et
    n'était alimenté nulle part en vrai.

    D'où une fonction, appelée des deux sites de notation, plutôt que le même
    bloc recopié — c'est la divergence entre deux copies qui avait déjà produit
    ce défaut.

    Rend `(titres_reels, explications)` pour que l'appelant puisse réemployer
    la lecture sans la refaire.
    """
    medications = list(medications or [])
    if not medications:
        return {}, {}

    # Par le titre réel, jamais par celui que le modèle affiche : il les
    # réécrit, et la jointure exacte échouerait sur ses propositions.
    reels = _titres_reels(medications)
    explications = explication_atc_des(
        [reels.get(id(m)) or m.get('title') for m in medications])
    for med in medications:
        cle = str(reels.get(id(med)) or med.get('title') or '')
        med['indication_source'] = (
            (explications.get(cle) or {}).get('indication') or '')

    attacher_composition(medications, reels)
    return reels, explications


def attacher_composition(medications, reels=None) -> None:
    """Pose `code_atc` et `composition` sur chaque fiche, en une requête.

    Ce que le catalogue déclare sous `substances_actives` est parfois
    incomplet : LAMALINE et PRONTALGINE n'y portent que « Paracétamol », alors
    qu'ils contiennent respectivement de la poudre d'opium et du phosphate de
    codéine. Le palier antalgique ne pouvait donc pas les voir, et l'écran les
    proposait à 100 sur 100 pour une céphalée légère.

    Les deux champs relevés ici le disent : le `code_atc` de la spécialité —
    celui du catalogue français, pas celui, pollué par les associations, que
    porte la substance DrugBank — et la rubrique 2 du RCP, qui énumère la
    composition réelle.

    Une seule requête pour tout le lot. Mongo injoignable ne casse rien : sans
    ces champs, le palier retombe sur la table par substance.
    """
    medications = list(medications or [])
    if not medications:
        return
    reels = reels or _titres_reels(medications)
    titres = [str(reels.get(id(m)) or m.get('title') or '')
              for m in medications]
    titres = [t for t in titres if t]
    if not titres:
        return

    try:
        fiches = {str(f.get('title')): f for f in db.medicines.find(
            {'title': {'$in': titres}},
            {'title': 1, 'code_atc': 1, 'sections': 1})}
    except Exception as err:
        logger.warning("Relevé de composition : %s", err)
        return

    for med in medications:
        cle = str(reels.get(id(med)) or med.get('title') or '')
        fiche = fiches.get(cle)
        if not fiche:
            continue
        med['code_atc'] = fiche.get('code_atc') or ''
        # Rubrique 2 : « Composition qualitative et quantitative ». C'est là
        # que les composants d'une association sont énumérés.
        med['composition'] = _abreger(rubrique_rcp(fiche, '2'), 600)


#: Classes ATC qu'un objectif thérapeutique appelle, faute d'entrée dans
#: `DIAGNOSTIC_ATC_MAP`.
#:
#: Pourquoi ce repli
#: -----------------
#: Deux tables décrivent les diagnostics et elles ne se parlaient pas.
#: `DIAGNOSTIC_ATC_MAP` alimente le **recrutement** ; `OBJECTIFS_THERAPEUTIQUES`
#: alimente la **notation**. Un tableau reconnu par la seconde et ignoré par la
#: première ne recrutait donc rien.
#:
#: Mesuré bout en bout sur « Fracture du col fémoral compliquée », douleur
#: décrite comme sévère et résistante au paracétamol :
#:
#:     objectif principal : antalgie
#:     classes ATC        : []            ← aucune
#:     proposé            : EFFERALGANSTIX FRAISE 250 mg, et rien d'autre
#:
#: Le vivier retombait sur la seule recherche vectorielle, et aucun antalgique
#: de palier 2 ou 3 n'était proposé.
#:
#: Le repli est **volontairement étroit** : il ne s'applique que lorsque la
#: table des diagnostics ne rend rien, et seulement aux objectifs dont la
#: classe ATC ne fait aucun doute. Il est indexé par **objectif**, si bien
#: qu'un tableau non douloureux ne peut pas recruter N02 : encore faut-il que
#: `OBJECTIFS_THERAPEUTIQUES` ait reconnu de la douleur.
#:
#: Il ne choisit rien : il ouvre le vivier. La gradation d'intensité déjà en
#: place — `intensite_douleur()` et les paliers — fait ensuite le tri, et un
#: opioïde reste déclassé sur une douleur légère.
CLASSES_PAR_OBJECTIF = {
    'antalgie': {'N02'},
    'antimigraineux': {'N02'},
}


def classes_atc_attendues(diagnostic: str) -> set:
    """Rend les groupes ATC de niveau 2 que le diagnostic appelle.

    Rend un ensemble **vide** quand rien n'est reconnu, et c'est délibéré :
    l'appelant ne doit alors pas filtrer. Ne rien savoir n'est pas savoir que
    rien ne convient — c'est la même règle qu'à chaque étage du système.

    Un repli par objectif intervient quand la table des diagnostics ne
    reconnaît rien : voir `CLASSES_PAR_OBJECTIF`.
    """
    attendues = set()
    for cle, groupes in DIAGNOSTIC_ATC_MAP.items():
        if _pathologie_citee(cle, diagnostic or ''):
            attendues |= groupes
    if attendues:
        return attendues

    # Repli : ce que les objectifs du tableau appellent. Uniquement ici, quand
    # la table des diagnostics est muette — un diagnostic qu'elle reconnaît
    # garde exactement le comportement d'avant.
    for objectif in objectifs_du_tableau(diagnostic or ''):
        attendues |= CLASSES_PAR_OBJECTIF.get(objectif, set())
    if attendues:
        logger.info("Classes deduites de l'objectif : %s", sorted(attendues))
    return attendues


# ══ Phase P3 de la roadmap · filtre par classe ATC ═══════════════════════
#
# P3 retourne la chaîne. Jusqu'ici, sur la prescription par diagnostic, le
# modèle choisissait 2 à 4 médicaments parmi 20 candidats bruts, **avant
# qu'aucune règle ne se soit prononcée**. La note arrivait ensuite : elle
# constatait, elle ne décidait pas.
#
# Désormais la règle constitue le vivier et le modèle n'intervient qu'à
# l'intérieur.

#: Groupes ATC qui suffisent, à eux seuls, à dire qu'un produit n'est pas un
#: traitement d'indication. Ils ne demandent **aucune connaissance du
#: diagnostic** : c'est ce qui les rend sûrs et les place ici.
#:
#: La table reste courte à dessein. Deux groupes constatés, pas une liste
#: d'exclusion qui grossirait au gré des cas rencontrés.
GROUPES_NON_THERAPEUTIQUES = {
    'V04': "Agent diagnostique : ce produit sert à explorer, pas à traiter.",
    'B05': "Solution de perfusion ou d'irrigation : véhicule ou correcteur, "
           "pas le traitement d'une pathologie.",
}


#: Sous-groupes ATC de niveau 4 qui désignent des **associations**.
#:
#: Pourquoi cette table
#: --------------------
#: Une substance DrugBank porte les codes ATC de toutes les associations qui la
#: contiennent, et rien dans le graphe ne les distingue : la relation `HAS_ATC`
#: n'a aucune propriété, et un nœud `AtcClass` ne porte que `code` et `niveau`.
#: L'amlodipine — un inhibiteur calcique — porte ainsi 35 codes, dont
#: `C07FB13` (bisoprolol + amlodipine), et le moteur la découvrait comme
#: bêta-bloquante.
#:
#: Mesuré : **277 substances sur 1 485 (19 %)** portent des codes de plusieurs
#: groupes de niveau 2. Ce n'est pas un défaut de l'amlodipine, c'est la forme
#: de la donnée.
#:
#: Deux règles la corrigent, toutes deux structurelles — aucune ne nomme un
#: médicament :
#:
#: 1. **Suffixe numérique ≥ 50.** L'OMS réserve les numéros 50 et au-delà du
#:    cinquième niveau aux associations : `C08CA01` est l'amlodipine seule,
#:    `C08CA51` l'amlodipine associée, `N02BE51` le paracétamol associé.
#: 2. **Sous-groupe de niveau 4 dédié aux associations.** Certains groupes
#:    entiers ne contiennent que des associations : `C07FB` (bêta-bloquants et
#:    inhibiteurs calciques), `C09BB` (IEC et inhibiteurs calciques), `N02AJ`
#:    (opioïdes et non-opioïdes), `J01RA` (antibactériens combinés). Leur
#:    numéro de cinquième niveau est inférieur à 50, la première règle ne les
#:    voit donc pas.
#:
#: Cette table décrit **la classification ATC**, pas des médicaments : un
#: produit jamais rencontré qui tomberait dans `C07FB` est traité par la même
#: règle, sans qu'on ait à l'inscrire nulle part.
#:
#: `G01AE` — « associations de sulfamides » — mérite sa mention : DrugBank y
#: raccroche **toute molécule portant un groupement sulfonamide**, et vingt-six
#: substances portent donc `G01AE10` sans avoir le moindre rapport avec la
#: gynécologie : rosuvastatine, sildénafil, bosentan, célécoxib, sumatriptan,
#: acétazolamide, et les diurétiques — furosémide, bumétanide,
#: hydrochlorothiazide, indapamide. Le furosémide ressortait ainsi
#: « anti-infectieux et antiseptique gynécologique » à l'écran, et pouvait être
#: recruté pour un diagnostic gynécologique. Son suffixe `10` est inférieur à
#: 50 : la première règle ne le voyait pas.
#:
#: Elle est volontairement incomplète — l'OMS compte des centaines de
#: sous-groupes — et se lit comme les autres tables du projet : ce qui n'y
#: figure pas continue d'être compté comme un code propre, ce qui élargit la
#: découverte au lieu de la restreindre.
SOUS_GROUPES_ASSOCIATION = frozenset("""
    A02BD A10BD
    C02LA C02LB C02LC C02LE C02LF C02LG C02LK C02LL C02LN
    C03EA C03EB
    C07BA C07BB C07CA C07CB C07DA C07DB C07FB C07FX
    C08GA
    C09BA C09BB C09BX C09DA C09DB C09DX
    C10BA C10BX
    D07CA D07CB D07CC
    G01AE
    G03AA G03AB G03FA G03FB
    J01CR J01EE J01RA
    M05BB
    N02AJ
    R03AK R03AL
    S01CA
""".split())


def est_code_d_association(code: str) -> bool:
    """Ce code ATC de niveau 5 désigne-t-il une association ?

    Voir `SOUS_GROUPES_ASSOCIATION` pour les deux règles et leur raison. Un
    code trop court ou illisible est déclaré « propre » : dans le doute on
    garde, comme partout ailleurs dans la chaîne.
    """
    code = str(code or '').strip().upper()
    if len(code) < 7:
        return False
    try:
        rang = int(code[5:7])
    except ValueError:
        return False
    return rang >= 50 or code[:5] in SOUS_GROUPES_ASSOCIATION


def groupes_propres(codes) -> set:
    """Rend les groupes ATC de niveau 2 qui appartiennent vraiment à la
    substance, associations retirées.

    **Ne rend jamais l'ensemble vide quand des codes existent.** Vingt-deux
    substances du graphe n'ont que des codes d'association ; les priver de
    tout groupe les rendrait indécouvrables, ce qui serait pire que le défaut
    corrigé. Dans ce cas les codes bruts font foi, faute de mieux.
    """
    codes = [str(c) for c in (codes or []) if c]
    if not codes:
        return set()
    propres = {c[:3] for c in codes if not est_code_d_association(c)}
    return propres or {c[:3] for c in codes}


def groupes_atc_des(titres) -> dict:
    """Rend, pour chaque titre de spécialité, ses groupes ATC de niveau 2.

    Le niveau 2 — trois caractères, `J01`, `C03`, `V04` — est le grain utile :
    assez fin pour distinguer un antibiotique d'un antihypertenseur, assez
    large pour ne pas dépendre de la molécule exacte.

    **Pourquoi le titre et non l'identifiant Mongo.** Les nœuds `Medicine` de
    Neo4j ne portent ni `mongo_id` ni `cis` : leurs seules propriétés sont
    `url`, `title`, `forme`, `update_date`, `document_type`, `last_scraped` et
    `dosages`. Le titre et l'URL sont donc les deux seules clés possibles, et
    seul le titre est présent des deux côtés — la charge Qdrant de la chaîne
    par symptômes ne porte pas d'URL. Mesuré : 400 fiches sur 400 retrouvées
    par l'un comme par l'autre, aucune URL dupliquée.

    Une seule requête pour tout le lot. Neo4j injoignable rend un dictionnaire
    vide : sans donnée, le filtre laisse tout passer plutôt que tout écarter.
    """
    titres = [str(t) for t in (titres or []) if t]
    if not titres:
        return {}

    # `current_app` lève hors d'un contexte de requête, il ne rend pas None.
    # Le filtre doit se dégrader, pas casser : sans graphe, tout passe.
    try:
        connector = getattr(current_app, 'neo4j', None)
    except Exception:
        connector = None
    if not connector or not getattr(connector, 'driver', None):
        logger.warning("Filtre par classe : Neo4j indisponible, rien n'est filtre")
        return {}

    try:
        with connector.driver.session(database=connector.database) as session:
            # Les codes de niveau 5 sont demandés, et le niveau 2 dérivé
            # ensuite par tranche de trois caractères — plutôt que remonté par
            # `HAS_PARENT`.
            #
            # C'est ce qui permet d'écarter les codes d'association avant de
            # généraliser : la remontée par la hiérarchie mélangeait le code
            # propre de la substance et ceux de toutes les associations qui la
            # contiennent, et l'amlodipine ressortait bêta-bloquante par
            # `C07FB13`. Voir `SOUS_GROUPES_ASSOCIATION`.
            lignes = session.run("""
                UNWIND $titres AS titre
                MATCH (m:Medicine {title: titre})
                      -[:HAS_DRUGBANK_SUBSTANCE]->(:DrugbankSubstance)
                      -[:HAS_ATC]->(a:AtcClass)
                WHERE a.niveau = 5
                RETURN titre, collect(DISTINCT a.code) AS codes
            """, titres=titres)
            return {l['titre']: groupes_propres(l['codes']) for l in lignes}
    except Exception as err:
        logger.warning("Filtre par classe : %s", err)
        return {}


#: Nombre de candidats générés par classe attendue.
#:
#: Le quota est la parade au risque de P3b : sans lui, J01 — qui compte des
#: centaines de spécialités — noierait N02, et une pneumonie n'aurait plus
#: d'antalgique. Chaque classe appelée par le diagnostic a droit au même
#: nombre de places.
CANDIDATS_PAR_CLASSE = 6

#: De combien le vivier est élargi avant la sélection clinique.
#:
#: Le quota de six était appliqué **avant** toute notation : les six
#: représentants d'une classe étaient choisis sur des critères administratifs —
#: voie d'administration, nombre de substances, longueur du nom — et la
#: pertinence clinique n'était calculée qu'ensuite, sur des candidats déjà
#: choisis. Un traitement de référence écarté à ce stade ne pouvait plus
#: revenir.
#:
#: Le graphe rend donc large, et `reduire_par_classe()` tranche après la
#: notation. Le coût est en mémoire, pas en requêtes : le nombre d'allers-
#: retours vers Neo4j et Mongo ne change pas.
#:
#: **Fixé à 2**, mesuré. Le tri d'entrée du graphe reste typographique — il ne
#: dispose d'aucune information clinique à ce stade — et un vivier trop serré
#: coupe donc sur la longueur du nom : à 1, le quota de six places de N02 était
#: pris par LAMALINE et PRONTALGINE, et « DAFALGAN 500 mg, gélule » n'entrait
#: pas. À 2, il entre ; au-delà, plus rien ne change.
#:
#: L'élargissement ne décide de rien : il **laisse entrer**. C'est
#: `reduire_par_classe()`, après notation, qui choisit — et depuis que le score
#: sépare réellement les candidats, ce choix est clinique.
ELARGISSEMENT_VIVIER = 2


def candidats_par_classe(attendues, par_classe: int = None) -> list:
    """Génère des candidats **à partir des classes** que le diagnostic appelle.

    Pourquoi cette fonction existe
    ------------------------------
    P3a avait retourné la chaîne, mais n'avait pas pu clore son critère de
    sortie : **un filtre retire, il n'ajoute jamais**. Mesuré sur « pneumonie
    communautaire », le vivier retenu comptait 19 candidats et **zéro
    antibiotique**. Aucun filtrage ne pouvait faire apparaître un J01 absent.

    L'étage 1 de l'architecture prévoyait « ATC attendus pour le diagnostic +
    recherche vectorielle bornée ». C'est la première moitié, qui manquait.

    Le chemin dans le graphe part de la classe et descend vers les
    spécialités :

        (:AtcClass) ←[:HAS_PARENT*0..]— (:AtcClass)
                    ←[:HAS_ATC]— (:DrugbankSubstance)
                    ←[:HAS_DRUGBANK_SUBSTANCE]— (:Medicine)

    L'ordre retenu à l'intérieur d'une classe reprend celui de
    `specialite_representative()`, déjà éprouvé : une seule substance d'abord,
    puis le titre le plus court. Une spécialité simple représente sa classe
    mieux qu'une association.
    """
    attendues = {str(a) for a in (attendues or []) if a}
    if not attendues:
        return []
    # Le vivier est élargi : la sélection clinique se fait après la notation,
    # dans `reduire_par_classe()`. Voir `ELARGISSEMENT_VIVIER`.
    par_classe = par_classe or (CANDIDATS_PAR_CLASSE * ELARGISSEMENT_VIVIER)

    try:
        connector = getattr(current_app, 'neo4j', None)
    except Exception:
        connector = None
    if not connector or not getattr(connector, 'driver', None):
        logger.warning("Generation par classe : Neo4j indisponible")
        return []

    titres_par_groupe = {}
    try:
        with connector.driver.session(database=connector.database) as session:
            for groupe in sorted(attendues):
                # Le graphe rend large ; l'ordre fin se fait ensuite, sur les
                # champs du catalogue français que Neo4j ne porte pas.
                lignes = session.run("""
                    MATCH (a:AtcClass)<-[:HAS_ATC]-(s:DrugbankSubstance)
                    WHERE a.niveau = 5 AND a.code STARTS WITH $groupe
                    WITH DISTINCT s
                    MATCH (s)-[:HAS_ATC]->(tous:AtcClass)
                    WHERE tous.niveau = 5
                    WITH s, collect(DISTINCT tous.code) AS codes
                    MATCH (s)<-[:HAS_DRUGBANK_SUBSTANCE]-(m:Medicine)
                    RETURN m.title AS titre, s.name AS substance, codes
                    LIMIT $limite
                """, groupe=groupe, limite=par_classe * 400)
                # Le tri par nombre de substances se faisait dans Cypher ; il
                # se fait ici, après avoir écarté les rattachements dus aux
                # associations. Sans ce filtre, une classe recrutait tout
                # produit qu'une association relie à elle : C07 remontait
                # l'amlodipine par `C07FB13`.
                par_titre = {}
                for l in lignes:
                    if groupe not in groupes_propres(l['codes']):
                        continue
                    par_titre.setdefault(l['titre'], set()).add(l['substance'])
                titres_par_groupe[groupe] = sorted(
                    ((t, len(s)) for t, s in par_titre.items()),
                    key=lambda p: (p[1], len(p[0])))
    except Exception as err:
        logger.warning("Generation par classe : %s", err)
        return []

    tous = [t for titres in titres_par_groupe.values() for t, _ in titres]
    if not tous:
        return []

    # Les fiches sont relues en une requête, pour porter ce dont la suite de
    # la chaîne a besoin : identifiant, substances, et les champs du filtre
    # d'éligibilité.
    try:
        fiches = {f['title']: f for f in db.medicines.find(
            {'title': {'$in': tous}},
            {'title': 1, 'medicine_details': 1, 'commercialisation': 1,
             'voies_administration': 1})}
    except Exception as err:
        logger.warning("Generation par classe : %s", err)
        return []

    def rang(paire):
        """Ordonne les candidats d'une classe, du plus prescriptible au moins.

        Le tri du graphe seul choisissait Invanz, Cubicin et Vaborem pour une
        pneumonie communautaire : des antibiotiques hospitaliers de dernier
        recours. Ils gagnaient par la brièveté de leur nom de marque, et parce
        que rien ne les pénalisait d'être des fiches d'origine EMA, dépourvues
        des champs structurés du catalogue français.

        La voie orale passe donc devant, puis les fiches qui portent une voie
        du tout. Ce n'est pas une exclusion — le critère 5 de l'architecture
        reste différé, et un injectable est parfois le traitement juste.
        """
        titre, substances = paire
        fiche = fiches.get(titre) or {}
        voies = _plier(str(fiche.get('voies_administration') or ''))
        return (
            0 if 'orale' in voies else 1,
            0 if voies else 1,
            substances,
            # La longueur du titre, faute de mieux — et c'est un défaut connu.
            #
            # Ce critère décide de la représentation d'une classe sur la
            # brièveté du nom de marque. Mesuré sur N02 : LAMALINE (16
            # caractères) et PRONTALGINE (21), deux associations opioïdes,
            # entrent dans le quota ; « DAFALGAN 1000 mg, gélule » (24) en est
            # exclu, et le paracétamol simple devient indécouvrable pour une
            # céphalée légère.
            #
            # **L'alphabétique a été essayé, et il est pire.** Mesuré sur une
            # décompensation cardiaque : il fait entrer ALDACTAZINE, ALDACTONE
            # et AMILORIDE, et sort le furosémide — le traitement même de la
            # congestion. Un critère arbitraire en remplace un autre.
            #
            # La cause est en amont : à cet endroit **rien de clinique n'est
            # disponible**. Ni les indications ni les notes ne sont calculées,
            # et tous les candidats d'une classe sont indiscernables. Le
            # départage ne peut devenir clinique que si la note sépare
            # réellement les candidats — aujourd'hui ils arrivent tous à 90.
            # C'est un défaut de **résolution du score**, consigné comme tel.
            len(titre),
        )

    candidats, vus = [], set()
    for groupe, titres in titres_par_groupe.items():
        retenus_du_groupe = 0
        for titre, _substances in sorted(titres, key=rang):
            if retenus_du_groupe >= par_classe:
                break
            fiche = fiches.get(titre)
            if not fiche or titre in vus:
                continue
            # Le filtre d'éligibilité de P1 s'applique ici aussi : générer un
            # produit non commercialisé serait absurde.
            if motif_d_ineligibilite(fiche):
                continue
            details = fiche.get('medicine_details') or {}
            vus.add(titre)
            retenus_du_groupe += 1
            candidats.append({
                'id': str(fiche['_id']),
                'title': titre,
                'substances': details.get('substances_actives') or [],
                'forme': details.get('forme', ''),
                'laboratoire': details.get('laboratoire', ''),
                'commercialisation': fiche.get('commercialisation'),
                'voies_administration': fiche.get('voies_administration'),
                'posologie': get_default_posologie(titre),
                # D'où vient ce candidat. L'écran et les bancs doivent pouvoir
                # distinguer ce que la classe a appelé de ce que la similarité
                # a remonté.
                'origine': 'classe_atc',
                'groupes_atc': [groupe],
            })

    if candidats:
        logger.info("Generation par classe : %d candidat(s) pour %s",
                    len(candidats), ', '.join(sorted(attendues)))
    return candidats


# ══ Phase P7 de la roadmap · la traçabilité ══════════════════════════════
#
# Six phases ont appris au système à écarter. P7 lui apprend à **dire
# pourquoi**.
#
# Quatre étages écartent, et trois le faisaient en silence : l'éligibilité et
# la classe se produisent dans `search_medications_for_diagnostic`, dont les
# écartés étaient jetés. Le médecin voyait une liste courte sans savoir ce qui
# l'avait raccourcie — exactement ce que le § 2.8 reproche depuis le début.

#: Nom lisible de chaque étage qui écarte. L'écran doit pouvoir dire lequel a
#: joué : « non commercialisé » et « sans lien thérapeutique » ne se
#: ressemblent pas et n'appellent pas la même relecture.
ETAGES_ECART = {
    'eligibilite': "Éligibilité",
    'classe': "Classe thérapeutique",
    'seuil': "Pertinence",
    'redondance': "Déjà couvert par le traitement en cours",
    'association': "Association proscrite",
    'antecedent': "Antécédents et biologie",
}

#: L'ordre de lecture du panneau des écartés.
#:
#: Il suit celui de la chaîne — éligibilité, classe, traitement en cours,
#: antécédents et constantes, pertinence — à une exception près :
#: l'association proscrite passe devant la redondance. La chaîne teste le
#: doublon d'abord parce que c'est le cas le plus fréquent ; le médecin, lui,
#: doit lire le danger avant l'inutile.
ORDRE_ETAGES = ('eligibilite', 'classe', 'association', 'redondance',
                'antecedent', 'seuil')


#: Libellés français des sous-groupes thérapeutiques ATC — niveau 2.
#:
#: **La source n'en fournit aucun.** Mesuré : 88 classes de niveau 2, zéro
#: libellé ; DrugBank ne donne que celui du niveau 4. L'écran affichait donc
#: le niveau 4, ce qui égarait : CLAMOXYL proposé pour une pneumonie
#: s'annonçait « Combinations for eradication of Helicobacter pylori ».
#:
#: Le niveau 2 est le bon grain — « antibactériens » plutôt que le détail de
#: l'association — et c'est aussi celui que le filtre emploie. Les 88 libellés
#: sont écrits ici : donnée de référence publique de l'OMS, comme les
#: quatorze groupes anatomiques, et de même nature — pas un jugement clinique.
LIBELLES_ATC_NIVEAU_2 = {
    'A01': "Préparations stomatologiques",
    'A02': "Antiacides et antiulcéreux",
    'A03': "Antispasmodiques et anticholinergiques digestifs",
    'A04': "Antiémétiques",
    'A05': "Thérapeutique biliaire et hépatique",
    'A06': "Laxatifs",
    'A07': "Antidiarrhéiques et anti-inflammatoires intestinaux",
    'A08': "Préparations contre l'obésité",
    'A09': "Digestifs, enzymes incluses",
    'A10': "Antidiabétiques",
    'A11': "Vitamines",
    'A12': "Suppléments minéraux",
    'A14': "Anabolisants à usage systémique",
    'A16': "Autres médicaments des voies digestives et du métabolisme",
    'B01': "Antithrombotiques",
    'B02': "Antihémorragiques",
    'B03': "Antianémiques",
    'B05': "Substituts du sang et solutions de perfusion",
    'B06': "Autres agents hématologiques",
    'C01': "Thérapeutique cardiaque",
    'C02': "Antihypertenseurs",
    'C03': "Diurétiques",
    'C04': "Vasodilatateurs périphériques",
    'C05': "Vasculoprotecteurs",
    'C07': "Bêta-bloquants",
    'C08': "Inhibiteurs calciques",
    'C09': "Médicaments du système rénine-angiotensine",
    'C10': "Hypolipémiants",
    'D01': "Antifongiques dermatologiques",
    'D02': "Émollients et protecteurs cutanés",
    'D03': "Cicatrisants",
    'D04': "Antiprurigineux",
    'D05': "Antipsoriasiques",
    'D06': "Antibiotiques et chimiothérapie dermatologiques",
    'D07': "Corticoïdes dermatologiques",
    'D08': "Antiseptiques et désinfectants",
    'D09': "Pansements médicamenteux",
    'D10': "Préparations contre l'acné",
    'D11': "Autres préparations dermatologiques",
    'G01': "Anti-infectieux et antiseptiques gynécologiques",
    'G02': "Autres médicaments gynécologiques",
    'G03': "Hormones sexuelles",
    'G04': "Médicaments urologiques",
    'H01': "Hormones hypophysaires et hypothalamiques",
    'H02': "Corticoïdes à usage systémique",
    'H03': "Thérapeutique thyroïdienne",
    'H04': "Hormones pancréatiques",
    'H05': "Régulateurs du calcium",
    'J01': "Antibactériens à usage systémique",
    'J02': "Antifongiques à usage systémique",
    'J04': "Antimycobactériens",
    'J05': "Antiviraux à usage systémique",
    'J06': "Immunsérums et immunoglobulines",
    'J07': "Vaccins",
    'L01': "Antinéoplasiques",
    'L02': "Thérapeutique endocrine",
    'L03': "Immunostimulants",
    'L04': "Immunosuppresseurs",
    'M01': "Anti-inflammatoires et antirhumatismaux",
    'M02': "Topiques pour douleurs articulaires et musculaires",
    'M03': "Myorelaxants",
    'M04': "Antigoutteux",
    'M05': "Médicaments des désordres osseux",
    'M09': "Autres médicaments de l'appareil locomoteur",
    'N01': "Anesthésiques",
    'N02': "Analgésiques",
    'N03': "Antiépileptiques",
    'N04': "Antiparkinsoniens",
    'N05': "Psycholeptiques",
    'N06': "Psychoanaleptiques",
    'N07': "Autres médicaments du système nerveux",
    'P01': "Antiprotozoaires",
    'P02': "Anthelminthiques",
    'P03': "Ectoparasiticides et insecticides",
    'R01': "Préparations nasales",
    'R02': "Préparations pour la gorge",
    'R03': "Médicaments des syndromes obstructifs des voies aériennes",
    'R05': "Médicaments du rhume et de la toux",
    'R06': "Antihistaminiques à usage systémique",
    'R07': "Autres médicaments de l'appareil respiratoire",
    'S01': "Médicaments ophtalmologiques",
    'S02': "Médicaments otologiques",
    'S03': "Médicaments ophtalmologiques et otologiques",
    'V03': "Tous autres médicaments",
    'V04': "Agents diagnostiques",
    'V08': "Produits de contraste",
    'V09': "Produits radiopharmaceutiques diagnostiques",
    'V10': "Produits radiopharmaceutiques thérapeutiques",
}


#: Indications déjà traduites, retenues par processus. Le même médicament
#: revient d'une analyse à l'autre, et retraduire coûterait un appel réseau
#: pour un texte identique.
_indications_traduites = {}


def traduire_indication(texte: str) -> tuple:
    """Traduit une indication DrugBank de l'anglais vers le français.

    Rend `(texte, traduit)`. En cas d'échec, l'anglais est rendu tel quel avec
    `traduit` à faux : l'écran doit pouvoir le dire, plutôt que de faire passer
    de l'anglais pour du français.

    **Pourquoi une traduction automatique ici, et pas pour les interactions.**
    Les énoncés d'interaction suivent 537 patrons, que 27 trames françaises
    écrites d'avance recouvrent à 99,86 % — sans jamais toucher aux noms de
    substance. Une indication est de la prose libre, sans patron : aucune
    trame ne la couvrirait.

    C'est donc un compromis assumé, et l'écran le signale : la mention vaut
    avertissement, pas décoration.
    """
    texte = (texte or '').strip()
    if not texte:
        return '', False
    if texte in _indications_traduites:
        return _indications_traduites[texte], True

    try:
        from deep_translator import GoogleTranslator
        francais = GoogleTranslator(source='en', target='fr').translate(
            texte[:4500])
        if francais and francais.strip():
            _indications_traduites[texte] = francais.strip()
            return francais.strip(), True
    except Exception as err:
        logger.warning("Traduction d'indication : %s", str(err)[:90])
    return texte, False


def explication_atc_des(titres) -> dict:
    """Rend, par titre, les libellés de classe et l'indication DrugBank.

    Le § 4.3 de l'architecture demande que chaque proposition porte quatre
    éléments : la règle qui l'a retenue, la **classe ATC et son libellé**,
    l'**indication** citée, et ce qui a été écarté à sa place. Les deux du
    milieu viennent d'ici.

    La classification et les indications ont été projetées en P2 et n'avaient
    jamais servi à autre chose qu'à filtrer. Elles servent maintenant aussi à
    expliquer.
    """
    titres = [str(t) for t in (titres or []) if t]
    if not titres:
        return {}

    try:
        connector = getattr(current_app, 'neo4j', None)
    except Exception:
        connector = None
    if not connector or not getattr(connector, 'driver', None):
        return {}

    try:
        with connector.driver.session(database=connector.database) as session:
            # Seul le niveau 2 est demandé : c'est le grain du filtre, et le
            # seul dont les libellés soient français. Le niveau 4 de DrugBank
            # est en anglais et trop fin — il annonçait CLAMOXYL comme
            # « Combinations for eradication of Helicobacter pylori » sur une
            # pneumonie.
            lignes = session.run("""
                UNWIND $titres AS titre
                MATCH (m:Medicine {title: titre})
                      -[:HAS_DRUGBANK_SUBSTANCE]->(s:DrugbankSubstance)
                OPTIONAL MATCH (s)-[:HAS_ATC]->(a:AtcClass)
                          -[:HAS_PARENT*0..]->(g:AtcClass)
                WHERE g.niveau = 2
                RETURN titre,
                       collect(DISTINCT g.code) AS classes,
                       head(collect(s.indication)) AS indication
            """, titres=titres)
            return {l['titre']: {
                'classes': {c: LIBELLES_ATC_NIVEAU_2.get(c, c)
                            for c in (l['classes'] or []) if c},
                'indication': l['indication'] or '',
            } for l in lignes}
    except Exception as err:
        logger.warning("Explication ATC : %s", err)
        return {}


def filtrer_par_classe(medications, attendues=None) -> tuple:
    """Écarte les candidats dont la classe ATC ne peut pas répondre au cas.

    Deux règles, dans cet ordre.

    **Le groupe est non thérapeutique** — `V04` ou `B05`. Aucun diagnostic
    n'est nécessaire pour le constater : un agent diagnostique n'est jamais un
    traitement.

    **Le groupe n'est pas attendu** — quand l'appelant fournit `attendues`.
    Ce paramètre est le point d'accroche de la table diagnostic → ATC, qui est
    le livrable de **P5**. Aucun appelant ne le renseigne aujourd'hui : P3 ne
    prétend pas faire P5.

    **L'absence de classe déclasse, elle n'exclut pas.** 148 substances du
    graphe n'ont aucun code ATC, et les écarter reviendrait à punir un défaut
    de couverture plutôt qu'un fait. Elles passent en fin de liste, marquées.

    Rend `(retenus, écartés)`. Chaque écarté porte son motif.
    """
    if not medications:
        return [], []

    # Les groupes sont pris sur le candidat quand il les porte déjà — le banc
    # les fournit — et relus en une fois sinon.
    inconnus = [m for m in medications if 'groupes_atc' not in m]
    if inconnus:
        releve = groupes_atc_des([m.get('title') or m.get('name')
                                  for m in inconnus])
        for med in inconnus:
            cle = str(med.get('title') or med.get('name') or '')
            # Une liste, jamais un ensemble : ces candidats partent en JSON
            # sans passer par `normaliser_medicament`, et un `set` y leve.
            med['groupes_atc'] = sorted(releve.get(cle, set()))

    retenus, ecartes, sans_classe = [], [], []
    for med in medications:
        groupes = set(med.get('groupes_atc') or [])

        if not groupes:
            med['sans_classe'] = True
            sans_classe.append(med)
            continue
        med.pop('sans_classe', None)

        non_therapeutiques = groupes & set(GROUPES_NON_THERAPEUTIQUES)
        # Un produit qui ne porte **que** des groupes non thérapeutiques est
        # écarté. En porter un parmi d'autres ne suffit pas : l'adrénaline
        # figure en B02 sans cesser d'être un traitement.
        if non_therapeutiques and not (groupes - set(GROUPES_NON_THERAPEUTIQUES)):
            med['hors_classe_car'] = GROUPES_NON_THERAPEUTIQUES[
                sorted(non_therapeutiques)[0]]
            med['motif_ecart'] = med['hors_classe_car']
            med['etage_ecart'] = 'classe'
            ecartes.append(med)
            continue

        if attendues and not (groupes & set(attendues)):
            med['hors_classe_car'] = (
                "Classe thérapeutique sans rapport avec le cas : %s, quand le "
                "tableau appelle %s."
                % (', '.join(sorted(groupes)), ', '.join(sorted(attendues))))
            med['motif_ecart'] = med['hors_classe_car']
            med['etage_ecart'] = 'classe'
            ecartes.append(med)
            continue

        med.pop('hors_classe_car', None)
        retenus.append(med)

    if ecartes:
        logger.info("Filtre par classe : %d candidat(s) ecarte(s) sur %d",
                    len(ecartes), len(medications))
    # Les sans-classe ferment la marche : retenus, mais après ceux dont la
    # classe est connue.
    return retenus + sans_classe, ecartes


def _titres_reels(medications) -> dict:
    """Rend, par médicament, le titre du catalogue plutôt que celui affiché.

    **Le modèle réécrit les noms.** Il propose « ERY 500 mg » quand le
    catalogue dit « ERY 500 mg, comprimé », et toute jointure par titre exact
    échoue sur ses propositions — la classe ATC comme l'indication.

    Le titre réel se relit par `fiche_id`, que `normaliser_medicament` a déjà
    résolu, au besoin par la spécialité représentative d'une dénomination
    commune. Une seule requête pour tout le lot.
    """
    reels, par_identifiant = {}, {}
    for med in (medications or []):
        brut = med.get('fiche_id') or med.get('id')
        try:
            par_identifiant.setdefault(ObjectId(brut), []).append(med)
        except Exception:
            continue
    if not par_identifiant:
        return reels
    try:
        for fiche in db.medicines.find(
                {'_id': {'$in': list(par_identifiant)}}, {'title': 1}):
            for med in par_identifiant[fiche['_id']]:
                reels[id(med)] = fiche.get('title')
    except Exception as err:
        logger.warning("Relecture des titres : %s", err)
    return reels


def _compter_par_etage(*lots) -> list:
    """Compte les écartés par étage, dans l'ordre où la chaîne les applique.

    Un panneau qui énumérerait trente fiches écartées serait illisible. Le
    compte par étage dit d'où vient la coupe ; le détail suit pour ceux qui
    comptent le plus — les propositions retirées par une règle clinique.
    """
    comptes = {}
    for lot in lots:
        for med in (lot or []):
            etage = med.get('etage_ecart')
            if etage:
                comptes[etage] = comptes.get(etage, 0) + 1
    return [{'etage': cle, 'libelle': ETAGES_ECART.get(cle, cle),
             'nombre': comptes[cle]}
            for cle in ORDRE_ETAGES
            if cle in comptes]


def appliquer_controles(medications: list, antecedents: str = '',
                        traitements_en_cours=None, age: int = 0,
                        contexte: str = '', mesures: dict = None,
                        ecartes_generation=None) -> dict:
    """Passe une liste de médicaments par tous les contrôles, dans l'ordre.

    Pourquoi cette fonction existe
    ------------------------------
    Deux écrans proposent des médicaments et vont en sens inverse : l'assistant
    part des symptômes pour arriver à un traitement, la prescription par
    diagnostic part d'un diagnostic déjà posé. Ils n'ont aucune raison de
    différer sur **ce qui est vérifié** une fois la liste constituée.

    Ils différaient pourtant sur tout. La prescription par diagnostic
    collectait les antécédents et les traitements en cours, les transmettait au
    modèle comme contexte libre, et ne contrôlait rien : ni contrainte, ni
    contre-indication, et un contrôle d'interactions qui comparait les
    suggestions **entre elles** au lieu de les comparer aux traitements du
    patient. Un patient sous warfarine à qui l'écran proposait de l'ibuprofène
    n'était averti de rien.

    L'ordre des étapes n'est pas indifférent
    ----------------------------------------
    La normalisation vient en premier : c'est elle qui donne aux deux chemins
    d'alimentation la même forme, et tout ce qui suit lit cette forme. Placer
    un contrôle avant elle le ferait porter sur des champs qui n'existent que
    d'un côté — c'est déjà arrivé au contrôle d'interactions.

    Les contraintes retirent, les contre-indications signalent. Les deux
    s'appliquent, y compris aux écartés : un médicament retiré pour un
    antécédent peut en heurter un second, et le médecin qui reconsidère la
    décision doit voir les deux.

    Rend tout ce dont un écran a besoin, états compris.
    """
    medications = [normaliser_medicament(m) for m in medications or []]

    # La fiche fait foi sur la substance. Ici et pas plus tôt : c'est
    # `normaliser_medicament` qui résout `fiche_id`, en passant au besoin par
    # la spécialité représentative d'une dénomination commune. Confronter
    # avant, comme je l'avais d'abord écrit, ne trouvait aucun identifiant et
    # ne faisait rien du tout — sans le dire.
    medications = confronter_substances(medications)

    #: Lecture du graphe partagée entre la notation et l'explication. La
    #: notation la fait quand un contexte clinique est fourni ; l'explication
    #: la refait sinon. `None` signifie « pas encore lue ».
    explications = None
    reels = None

    # La note vient après la confrontation, jamais avant. Le modèle annonce la
    # substance de ce qu'il propose et il se trompe : noter sur son annonce
    # revenait à récompenser l'invention. Seuls les médicaments qui arrivent
    # sans note sont notés ici — ceux de l'assistant le sont déjà, sur les
    # symptômes.
    if contexte:
        # Les groupes ATC sont relus pour ceux qui n'en portent pas. Les
        # candidats du modèle arrivent nus : il fabrique ses propositions à
        # partir de son JSON, sans rien reprendre du vivier. Sans cette
        # relecture, la note ignorerait la classe et le seuil supprimerait des
        # traitements justes — c'est exactement ce qui s'est produit.
        sans_groupes = [m for m in medications if not m.get('groupes_atc')]
        if sans_groupes:
            # Le titre du candidat ne suffit pas : **le modèle réécrit les
            # noms**. Il propose « ERY 500 mg » quand le catalogue dit « ERY
            # 500 mg, comprimé », et la jointure par titre exact échoue. ERY
            # obtenait alors zéro pour une pneumonie, et le seuil l'écartait.
            #
            # Le titre réel se relit par `fiche_id`, que la normalisation a
            # déjà résolu — au besoin par la spécialité représentative d'une
            # dénomination commune. Même détour que `confronter_substances`.
            titres_reels = _titres_reels(sans_groupes)
            demandes = [titres_reels.get(id(m)) or m.get('title')
                        for m in sans_groupes]
            releve = groupes_atc_des(demandes)
            for med in sans_groupes:
                cle = titres_reels.get(id(med)) or med.get('title') or ''
                med['groupes_atc'] = sorted(releve.get(str(cle), set()))

        # L'indication réelle, **avant** la notation. Son résultat est
        # réemployé plus bas par l'étape d'explication : une seule lecture du
        # graphe pour les deux usages.
        reels, explications = attacher_indications(medications)

        for med in medications:
            if med.get('pertinence') is not None:
                continue
            score, justification = compute_clinical_relevance(contexte, med)
            med['pertinence'] = score
            if not med.get('justification'):
                med['justification'] = justification

        # Première réduction, large.
        #
        # `candidats_par_classe()` rend désormais un vivier élargi, et il faut
        # le borner **avant** le contrôle d'interactions : celui-ci coupe à
        # vingt paires côté graphe et à dix à la sortie, si bien qu'avec
        # quarante-huit candidats les pénalités d'interaction dépendaient de
        # l'ordre d'arrivée. Défaut latent, révélé par l'élargissement.
        #
        # Le quota est ici du double du quota final : assez serré pour que les
        # bornes ne mordent pas, assez large pour que la seconde réduction —
        # celle qui voit les notes finales — ait de quoi choisir. C'est aussi
        # cette passe qui retire les génériques d'une même molécule.
        medications = reduire_par_classe(medications, CANDIDATS_PAR_CLASSE * 2)

        # La réduction finale et la composition de la stratégie ont lieu
        # **après** `peser_la_securite` : voir leurs appels plus bas. Elles se
        # faisaient ici, sur des notes d'avant pénalités toutes égales, et le
        # départage retombait sur le nom.

    # Phase P7 : chaque proposition porte son explication — la classe **et son
    # libellé**, l'indication DrugBank citée. La classification projetée en P2
    # n'avait servi qu'à filtrer ; elle sert maintenant aussi à expliquer.
    if medications:
        # Par le titre réel, jamais par celui que le modèle affiche : il les
        # réécrit, et la jointure exacte échouerait sur ses propositions.
        #
        # La requête n'est refaite que si la notation ne l'a pas déjà faite —
        # c'est-à-dire hors contexte clinique. Sinon on réemploie son résultat :
        # une seule lecture du graphe pour les deux usages.
        if explications is None:
            reels = _titres_reels(medications)
            explications = explication_atc_des(
                [reels.get(id(m)) or m.get('title') for m in medications])
        for med in medications:
            cle = str(reels.get(id(med)) or med.get('title') or '')
            explication = explications.get(cle) or {}
            med['classes_libelles'] = explication.get('classes') or {}
            # L'indication est abrégée **avant** d'être traduite : traduire
            # 4 000 caractères pour n'en montrer 320 serait payer un appel
            # réseau pour rien.
            brut = _abreger(explication.get('indication') or '', 320)
            med['indication'], med['indication_traduite'] = traduire_indication(brut)

    medications.sort(key=_ordre_therapeutique)

    # Phase P4 : le seuil décide. Un candidat sous le seuil quitte les
    # propositions et rejoint les écartés, avec sa note.
    #
    # Rien ne disparaît : tout change de panneau. C'est ce qui rend le seuil
    # compatible avec le § 2.8 — un médicament écarté en silence emporte avec
    # lui la raison de son retrait.
    #
    # Le seuil ne s'applique qu'aux candidats **notés**. Le repli clinique
    # arrive avec ses notes de 75 à 95 ; un candidat sans note du tout n'est
    # pas jugé, il est simplement laissé.
    sous_le_seuil = []

    # Ce que le patient prend déjà, **avant** les antécédents et la biologie.
    #
    # L'ordre est celui du raisonnement : on regarde d'abord si la place est
    # libre, ensuite seulement si le médicament conviendrait. Un bêta-bloquant
    # de plus chez un patient sous bisoprolol n'a pas à être jugé sur ses
    # contre-indications : la question ne se pose pas.
    #
    # C'était l'angle mort de la chaîne. Le traitement en cours ne servait qu'à
    # chercher des interactions ; il n'était jamais comparé aux propositions.
    # Mesuré chez un patient sous bisoprolol et sacubitril/valsartan : l'écran
    # proposait du timolol, du pindolol et du trandolapril.
    medications, deja_couverts = couvert_par_le_traitement(
        medications, traitements_en_cours)

    retenus, ecartes = appliquer_contraintes(medications, antecedents, mesures)
    contraintes = contraintes_actives(antecedents)
    biologiques = contraintes_biologiques(mesures)

    # Les traitements que le patient prend déjà, confrontés aux mêmes règles.
    # Signalés, jamais écartés : on ne retire pas un traitement en cours depuis
    # un écran de suggestion.
    a_reconsiderer = traitements_a_reconsiderer(
        traitements_en_cours, antecedents, mesures)

    retenus = filter_contraindications(retenus, age=age, antecedents=antecedents)
    ecartes = filter_contraindications(ecartes, age=age, antecedents=antecedents)

    controle = check_interactions(traitements_en_cours or [], retenus)

    # La sécurité pèse sur la note, et le seuil s'applique ensuite.
    #
    # Le score et la sécurité étaient deux axes indépendants : les
    # contre-indications déclassaient dans l'ordre d'affichage sans toucher à
    # la note, et une interaction ne comptait pas du tout. Le salbutamol
    # s'affichait à 95 sur 100 avec une contre-indication relevée.
    #
    # Le seuil vient **après** : appliqué avant, il n'aurait pas vu la
    # pénalité, et un médicament dangereux serait resté au-dessus.
    peser_la_securite(retenus, controle['interactions'])

    # Phase P6 : la liste devient une stratégie — **après** la pesée.
    #
    # Elle se composait avant, sur les notes brutes. Le rang était donc figé
    # sur des scores que les pénalités contredisaient ensuite : mesuré sur une
    # décompensation, PRESTOLE et LOGIRENE arrivaient tous deux à 90, PRESTOLE
    # prenait la première intention par ordre d'insertion, puis les pénalités
    # les séparaient — 70 contre 80. L'écran affichait un « première
    # intention » à 70 devant une « alternative » à 80.
    #
    # Rien entre l'ancien emplacement et celui-ci ne lisait `rang` ni
    # `condition` : le déplacement est sans autre effet.
    if contexte:
        # Le quota par classe d'abord, sur les notes finales : c'est la
        # sélection clinique des représentants, celle qui remplace le tri par
        # voie d'administration et longueur de nom de `candidats_par_classe()`.
        retenus = reduire_par_classe(retenus)
        retenus = composer_strategie(retenus, contexte)

    if contexte:
        gardes = []
        for med in retenus:
            note = med.get('pertinence')
            if isinstance(note, (int, float)) and note < SEUIL_EXCLUSION:
                med['sous_le_seuil'] = SEUIL_EXCLUSION
                med['motif_ecart'] = (
                    "Note de %d sur 100, sous le seuil de %d%s."
                    % (note, SEUIL_EXCLUSION,
                       " après pénalité de sécurité" if med.get('penalites')
                       else " : aucun lien thérapeutique établi"))
                med['etage_ecart'] = 'seuil'
                sous_le_seuil.append(med)
            else:
                med.pop('sous_le_seuil', None)
                gardes.append(med)
        retenus = gardes
        if sous_le_seuil:
            logger.info("Seuil de pertinence : %d candidat(s) ecarte(s) sur %d",
                        len(sous_le_seuil), len(sous_le_seuil) + len(retenus))
        # La pesée a pu défaire l'ordre : un contre-indiqué à 95 tombe à 55.
        retenus.sort(key=lambda m: ((1 if m.get('contre_indications') else 0,)
                                    + _ordre_therapeutique(m)))

    # L'état des contraintes, dans l'esprit d'`interactions_etat` : une liste
    # vide ne dit pas d'elle-même pourquoi elle l'est. « aucun antécédent
    # contraignant », « les règles n'ont rien trouvé » et « tout ce qui était
    # proposé a été écarté » donnent le même écran vide et ne veulent pas dire
    # la même chose.
    if not contraintes:
        contraintes_etat = 'aucune'
    elif not ecartes:
        contraintes_etat = 'sans_effet'
    elif not retenus:
        contraintes_etat = 'tout_ecarte'
    else:
        contraintes_etat = 'appliquees'

    # `penalites` et `alertes` sortaient tantot absents, tantot vides : deux
    # formes pour « rien ». `peser_la_securite` retire la cle quand aucune
    # penalite ne s'applique, et `appliquer_contraintes` rend la main avant
    # d'avoir pose `alertes` quand aucune regle n'est active.
    #
    # L'ecran devait donc distinguer `null` de `[]` sans que la difference ne
    # signifie rien. Une liste vide dit « rien a signaler » ; une absence de
    # cle dit la meme chose, mais oblige chaque lecteur a y penser.
    for med in list(retenus) + list(sous_le_seuil) + list(deja_couverts)             + list(ecartes) + list(ecartes_generation or []):
        for cle in ('penalites', 'alertes', 'declassements'):
            if not isinstance(med.get(cle), list):
                med[cle] = []

    return {
        'medications': retenus,
        # Écartés par une règle d'antécédent : ils quittent les propositions
        # mais restent à l'écran, avec la règle qui les a retirés. Un
        # médicament écarté en silence emporte avec lui la raison de son
        # retrait.
        # Les écartés par une règle d'antécédent, **et** ceux que le seuil de
        # pertinence a retirés. Les seconds portent `sous_le_seuil` : l'écran
        # doit pouvoir dire lequel des deux motifs a joué.
        # Tous les écartés, de tous les étages. Les trois premiers — éligibilité,
        # classe, seuil — se produisaient en amont et étaient **jetés** : le
        # médecin voyait une liste courte sans savoir ce qui l'avait
        # raccourcie. C'est ce que le § 2.8 reproche depuis le début.
        'medicaments_ecartes': deja_couverts + ecartes + sous_le_seuil + list(
            ecartes_generation or []),
        # Le compte par étage, pour que le panneau puisse dire d'où vient la
        # coupe sans énumérer trente fiches.
        'ecartes_par_etage': _compter_par_etage(
            deja_couverts, ecartes, sous_le_seuil, ecartes_generation),
        'contraintes_etat': contraintes_etat,
        'contraintes_appliquees': [
            {'antecedent': r['libelle'], 'motif': r['motif']}
            for r in contraintes + biologiques
        ],
        # Les traitements que le patient prend déjà et que ses antécédents ou
        # ses résultats contredisent. Signalés, jamais retirés : c'est là que
        # se trouvent les erreurs qui durent, une proposition nouvelle étant
        # relue quand un traitement ancien ne l'est plus.
        'traitements_a_reconsiderer': a_reconsiderer,
        # Ce que la biologie a relevé, avec la valeur mesurée. Vide quand rien
        # n'a été saisi : ne rien savoir n'est pas constater une anomalie.
        'biologie_relevee': [
            {'libelle': s['libelle'], 'valeur': s['mesure_relevee'],
             'motif': s['motif']}
            for s in biologiques
        ],
        'interactions': controle['interactions'],
        # L'état dit pourquoi la liste est vide quand elle l'est : « aucune
        # interaction trouvée » et « rien n'a pu être vérifié » ne se
        # ressemblent pas, et l'écran ne doit pas les confondre.
        'interactions_etat': controle['etat'],
        'traitements_reconnus': controle['reconnus'],
        'traitements_non_reconnus': controle['non_reconnus'],
        'paires_verifiees': controle['paires_verifiees'],
        # Vrai si une borne de charge a mordu : le contrôle est alors partiel,
        # et une absence de pénalité ne vaut pas absence d'interaction. Faux
        # dans tous les cas rencontrés en consultation.
        'interactions_tronquees': controle.get('tronque', False),
    }


#: Classes pharmacologiques, et les substances qui les composent.
#:
#: Pourquoi une table écrite à la main plutôt que les codes ATC
#: ------------------------------------------------------------
#: Il serait tentant de dériver ces classes du graphe : les codes ATC les
#: portent déjà. Ils ne peuvent pas servir ici.
#:
#: Une substance DrugBank porte les codes ATC de **toutes les associations qui
#: la contiennent**. `Amlodipine` — un inhibiteur calcique, `C08CA01` — porte
#: aussi `C07FB13` (bisoprolol + amlodipine), `C09DX01`, `C10BX18`. Comparer les
#: classes ATC de deux médicaments ferait donc voir de la redondance là où il
#: n'y en a pas : AMLOR passerait pour un bêta-bloquant. Le défaut est mesuré et
#: consigné au § 12.5 de l'architecture.
#:
#: Cette table dit une seule chose de chaque substance : à quelle famille elle
#: appartient réellement. Elle est écrite, donc relisible et contestable — même
#: raison que `CONTRAINTES_ANTECEDENTS`.
#:
#: **Portée : le cardiovasculaire, et lui seul.** C'est le domaine où la
#: poly-médication est la règle et où la redondance fait le plus de dégâts. Ce
#: qui n'y figure pas n'est pas détecté comme redondant — un manque, pas une
#: erreur : le médicament reste proposé et le médecin garde la main. L'étendre
#: est un acte à part, qui demande une source.
#:
#: Les substances sont écrites **sans accent** : la reconnaissance passe par
#: `_plier`, comme partout ailleurs.
CLASSES_THERAPEUTIQUES = {
    'betabloquant': {
        'cumul': 'jamais',
        'libelle': "bêta-bloquant",
        'substances': ['acebutolol', 'atenolol', 'betaxolol', 'bisoprolol',
                       'carvedilol', 'celiprolol', 'esmolol', 'labetalol',
                       'metoprolol', 'nadolol', 'nebivolol', 'oxprenolol',
                       'pindolol', 'propranolol', 'sotalol', 'tertatolol',
                       'timolol'],
    },
    'iec': {
        'cumul': 'jamais',
        'libelle': "inhibiteur de l'enzyme de conversion",
        'substances': ['benazepril', 'captopril', 'cilazapril', 'enalapril',
                       'fosinopril', 'imidapril', 'lisinopril', 'moexipril',
                       'perindopril', 'quinapril', 'ramipril', 'trandolapril',
                       'zofenopril'],
    },
    'sartan': {
        'cumul': 'jamais',
        'libelle': "antagoniste des récepteurs de l'angiotensine II",
        'substances': ['candesartan', 'eprosartan', 'irbesartan', 'losartan',
                       'olmesartan', 'telmisartan', 'valsartan'],
    },
    # Le sacubitril ne se prescrit qu'associé au valsartan. Une fiche de
    # sacubitril/valsartan appartient donc aux deux classes à la fois, et c'est
    # voulu : proposer un sartan à ce patient est bien une redondance.
    'arni': {
        'cumul': 'jamais',
        'libelle': "inhibiteur de la néprilysine et des récepteurs de "
                   "l'angiotensine",
        'substances': ['sacubitril'],
    },
    'diuretique_anse': {
        # Majorer le diurétique de l'anse est la conduite d'une congestion
        # importante : l'exclure comme doublon interdirait le traitement même
        # de la décompensation.
        'cumul': 'possible',
        'libelle': "diurétique de l'anse",
        'substances': ['bumetanide', 'furosemide', 'piretanide', 'torasemide'],
    },
    'epargneur_potassium': {
        'cumul': 'jamais',
        'libelle': "diurétique épargneur de potassium",
        'substances': ['amiloride', 'canrenoate', 'eplerenone',
                       'spironolactone', 'triamterene'],
    },
    'thiazidique': {
        # Un thiazidique ajouté à un diurétique de l'anse est le blocage
        # séquentiel du néphron, une stratégie de la congestion réfractaire.
        'cumul': 'possible',
        'libelle': "diurétique thiazidique",
        'substances': ['chlortalidone', 'cicletanine', 'hydrochlorothiazide',
                       'indapamide', 'methyclothiazide'],
    },
    # Séparés des dihydropyridines à dessein : le vérapamil et le diltiazem
    # ralentissent le cœur et diminuent sa force de contraction, l'amlodipine
    # non. La distinction décide de tout dans l'insuffisance cardiaque.
    'calcique_bradycardisant': {
        'cumul': 'jamais',
        'libelle': "inhibiteur calcique bradycardisant",
        'substances': ['diltiazem', 'verapamil'],
    },
    'calcique_dihydropyridine': {
        'cumul': 'jamais',
        'libelle': "inhibiteur calcique dihydropyridine",
        'substances': ['amlodipine', 'felodipine', 'isradipine', 'lacidipine',
                       'lercanidipine', 'manidipine', 'nicardipine',
                       'nifedipine', 'nimodipine', 'nitrendipine'],
    },
    'isglt2': {
        'cumul': 'jamais',
        'libelle': "inhibiteur du cotransporteur sodium-glucose de type 2",
        'substances': ['canagliflozine', 'dapagliflozine', 'empagliflozine',
                       'ertugliflozine'],
    },
    'anticoagulant_direct': {
        'cumul': 'jamais',
        'libelle': "anticoagulant oral direct",
        'substances': ['apixaban', 'dabigatran', 'edoxaban', 'rivaroxaban'],
    },
    'antivitamine_k': {
        'cumul': 'jamais',
        'libelle': "antivitamine K",
        'substances': ['acenocoumarol', 'fluindione', 'warfarine'],
    },
    'antiagregant': {
        # La bithérapie antiagrégante est une conduite établie après un
        # syndrome coronarien ou une pose de stent.
        'cumul': 'possible',
        'libelle': "antiagrégant plaquettaire",
        'substances': ['acetylsalicylique', 'clopidogrel', 'prasugrel',
                       'ticagrelor'],
    },
    'statine': {
        'cumul': 'jamais',
        'libelle': "statine",
        'substances': ['atorvastatine', 'fluvastatine', 'pravastatine',
                       'rosuvastatine', 'simvastatine'],
    },
    'antiarythmique_i': {
        'cumul': 'jamais',
        'libelle': "antiarythmique de classe I",
        'substances': ['cibenzoline', 'disopyramide', 'flecainide',
                       'hydroquinidine', 'propafenone'],
    },
    'antiarythmique_iii': {
        'cumul': 'jamais',
        'libelle': "antiarythmique de classe III",
        'substances': ['amiodarone', 'dronedarone'],
    },
    'digitalique': {
        'cumul': 'jamais',
        'libelle': "digitalique",
        'substances': ['digitoxine', 'digoxine'],
    },
    'derive_nitre': {
        # Un dérivé nitré d'action rapide s'ajoute à un dérivé retard.
        'cumul': 'possible',
        'libelle': "dérivé nitré",
        'substances': ['isosorbide', 'molsidomine', 'trinitrine'],
    },
}


def substances_des_classes(*cles) -> list:
    """Rend, à plat, toutes les substances des classes nommées.

    Sert à écrire une règle de seuil en désignant des familles plutôt qu'en
    recopiant cinquante molécules — et surtout à ce que l'ajout d'une substance
    à la table profite du même coup aux règles qui citent sa classe. C'est la
    table des épargneurs de potassium, incomplète pendant deux phases, qui a
    montré ce que coûte une liste recopiée.
    """
    trouvees = []
    for cle in cles:
        for substance in (CLASSES_THERAPEUTIQUES.get(cle) or {}).get(
                'substances', []):
            if substance not in trouvees:
                trouvees.append(substance)
    return trouvees


#: Ce qui, dans le cardiovasculaire, abaisse la pression artérielle. Cité par
#: la règle d'hypotension et par celle de l'insuffisance cardiaque.
ANTIHYPERTENSEURS = substances_des_classes(
    'betabloquant', 'iec', 'sartan', 'arni', 'thiazidique', 'diuretique_anse',
    'epargneur_potassium', 'calcique_bradycardisant',
    'calcique_dihydropyridine', 'derive_nitre')


#: Associations que l'on ne prescrit pas, exprimées en classes.
#:
#: À distinguer de la redondance. Proposer un second bêta-bloquant à qui en
#: prend déjà un est *inutile* ; ajouter un IEC à un patient sous
#: sacubitril/valsartan est *dangereux*. Les deux écartent, mais l'écran ne doit
#: pas les confondre, et le motif diffère.
ASSOCIATIONS_PROSCRITES = [
    {
        'classes': ('iec', 'arni'),
        'motif': "Association contre-indiquée : le risque d'angio-œdème "
                 "impose un intervalle de 36 heures entre un inhibiteur de "
                 "l'enzyme de conversion et le sacubitril/valsartan.",
    },
    {
        'classes': ('iec', 'sartan'),
        'motif': "Double blocage du système rénine-angiotensine : "
                 "hyperkaliémie, hypotension et dégradation de la fonction "
                 "rénale, sans bénéfice démontré.",
    },
    {
        'classes': ('betabloquant', 'calcique_bradycardisant'),
        'motif': "Association déconseillée : bradycardie sévère, bloc "
                 "auriculo-ventriculaire et dépression de la contractilité "
                 "par addition des effets.",
    },
    {
        'classes': ('anticoagulant_direct', 'antivitamine_k'),
        'motif': "Deux anticoagulants oraux : risque hémorragique majeur. "
                 "Le relais entre les deux se conduit, il ne se cumule pas.",
    },
    {
        'classes': ('calcique_bradycardisant', 'digitalique'),
        'motif': "Le vérapamil et le diltiazem augmentent la digoxinémie : "
                 "surdosage digitalique et troubles de conduction.",
    },
]


#: Antécédents qui interdisent, et ce qu'ils interdisent.
#:
#: Pourquoi une table plutôt qu'un rapprochement de texte
#: -----------------------------------------------------
#: `contre_indications_relevees()` cherche les antécédents dans la rubrique 4.3
#: du RCP et **signale** ce qu'elle trouve, sans rien retirer. C'est délibéré :
#: un rapprochement de texte n'est pas une décision clinique, et un médicament
#: écarté en silence emporte avec lui la raison de son retrait.
#:
#: Cette table est d'une autre nature. Chaque règle est écrite, nommée et
#: motivée : on peut la relire, la contester, la corriger. C'est ce qui lui
#: permet d'écarter là où un rapprochement de texte ne le pouvait pas. Les deux
#: mécanismes coexistent et ne se confondent pas.
#:
#: Elle est **volontairement courte**. Huit règles de manuel valent mieux que
#: cinquante approximations : ce qui n'y figure pas continue d'être signalé par
#: le RCP, et le médecin garde la main. L'étendre est un acte à part, qui
#: demande une source.
#:
#: `antecedent` : expressions de reconnaissance. Tous les mots d'une expression
#: doivent tenir dans le **même segment** de la saisie — « insuffisance » seule
#: rencontrait « insuffisance hépatique sévère » chez une patiente dont
#: l'insuffisance est rénale.
#:
#: `cibles` : ce qui est écarté, cherché en mot entier dans le titre, les
#: substances et la forme. Jamais d'abréviation courte : « ains » se trouve
#: dans « certains », et « anti » attrapait « ORGARAN 750 U.I. anti-Xa ».
CONTRAINTES_ANTECEDENTS = [
    {
        'libelle': 'insuffisance rénale',
        # « maladie rénale chronique » et « néphropathie » ajoutées après un
        # essai sur un dossier réel : il portait « Maladie rénale chronique
        # stade 3b », formulation parfaitement standard, et **aucune règle ne
        # se déclenchait**. Un patient au DFG de 28 pouvait recevoir un AINS.
        #
        # « rénale » seule reste insuffisante : elle rencontrerait « colique
        # néphrétique » et l'on retomberait dans le faux positif du § 2.8.
        'antecedent': [('insuffisance', 'renale'), ('insuffisant', 'renal'),
                       ('maladie', 'renale'), ('nephropathie',),
                       ('clairance', 'abaissee')],
        'cibles': ['ibuprofene', 'ketoprofene', 'diclofenac', 'naproxene',
                   'piroxicam', 'metformine'],
        'motif': "Néphrotoxicité des anti-inflammatoires non stéroïdiens ; "
                 "risque d'acidose lactique sous metformine.",
    },
    {
        'libelle': 'insuffisance cardiaque',
        # « décompensation cardiaque » désigne la même situation, en aigu.
        # « cardiopathie ischémique » n'y figure pas à dessein : une
        # coronaropathie n'est pas une insuffisance cardiaque, et l'y mettre
        # écarterait des AINS chez des patients qui n'en relèvent pas.
        'antecedent': [('insuffisance', 'cardiaque'), ('insuffisant', 'cardiaque'),
                       ('decompensation', 'cardiaque')],
        'cibles': ['ibuprofene', 'ketoprofene', 'diclofenac', 'naproxene',
                   'piroxicam'],
        'motif': "Rétention hydrosodée sous anti-inflammatoire non stéroïdien, "
                 "risque de décompensation.",
    },
    {
        'libelle': 'ulcère gastroduodénal',
        'antecedent': [('ulcere',), ('gastroduodenal',)],
        'cibles': ['ibuprofene', 'ketoprofene', 'diclofenac', 'naproxene',
                   'piroxicam', 'aspirine', 'acetylsalicylique'],
        'motif': "Risque hémorragique digestif sous anti-inflammatoire non "
                 "stéroïdien et sous aspirine.",
    },
    {
        'libelle': 'asthme',
        'antecedent': [('asthme',), ('asthmatique',)],
        'cibles': ['propranolol', 'atenolol', 'bisoprolol', 'metoprolol',
                   'aspirine', 'acetylsalicylique', 'ibuprofene'],
        'motif': "Bronchoconstriction sous bêta-bloquant ; asthme à l'aspirine "
                 "et aux anti-inflammatoires non stéroïdiens.",
    },
    {
        'libelle': 'allergie aux pénicillines',
        'antecedent': [('allergie', 'penicilline'), ('allergie', 'penicillines'),
                       ('allergique', 'penicilline'),
                       ('allergie', 'betalactamines')],
        'cibles': ['amoxicilline', 'penicilline', 'ampicilline',
                   'cloxacilline', 'piperacilline'],
        'motif': "Réaction croisée entre bêta-lactamines.",
    },
    {
        'libelle': 'grossesse',
        'antecedent': [('grossesse',), ('enceinte',), ('gestation',)],
        'cibles': ['ibuprofene', 'ketoprofene', 'diclofenac', 'naproxene',
                   'piroxicam', 'isotretinoine', 'methotrexate'],
        'motif': "Contre-indication formelle : fermeture du canal artériel "
                 "après 24 semaines d'aménorrhée ; tératogénicité.",
    },
    {
        'libelle': 'glaucome à angle fermé',
        'antecedent': [('glaucome',), ('angle', 'ferme')],
        'cibles': ['atropine', 'scopolamine', 'oxybutynine', 'hydroxyzine',
                   'amitriptyline'],
        'motif': "Risque de crise aiguë de glaucome par effet "
                 "anticholinergique.",
    },
    {
        'libelle': 'insuffisance hépatique',
        'antecedent': [('insuffisance', 'hepatique'), ('insuffisant', 'hepatique'),
                       ('cirrhose',)],
        'cibles': ['methotrexate', 'ibuprofene', 'ketoprofene', 'diclofenac',
                   'naproxene'],
        'motif': "Métabolisme hépatique altéré ; risque de syndrome "
                 "hépatorénal sous anti-inflammatoire non stéroïdien.",
    },
]


#: Ce qu'une règle fait quand elle se déclenche.
#:
#: Pourquoi trois niveaux et non un seul
#: -------------------------------------
#: Toutes les règles des deux tables excluaient. C'était trop absolu : *une
#: valeur anormale doit d'abord être qualifiée*. Une hyponatrémie chez un
#: patient sous furosémide appelle une surveillance et une réévaluation — elle
#: ne fait pas du furosémide un mauvais traitement.
#:
#: Les trois mécanismes existaient déjà, mais mal branchés : le niveau
#: dépendait de **qui** était le médicament, pas de **ce que la règle voulait
#: dire**. Un candidat était exclu, un traitement en cours seulement signalé —
#: par la même règle. `traitements_a_reconsiderer` était un second chemin pour
#: la même évaluation.
#:
#: Le niveau appartient désormais à la règle. Le même verdict vaut pour un
#: candidat et pour un traitement en place ; seule change la conséquence, car
#: on ne retire pas un traitement en cours depuis un écran de suggestion.
#:
#:   `exclusion`     le médicament ne doit pas être proposé
#:   `surveillance`  il peut rester pertinent, sous réévaluation ; l'alerte
#:                   est portée sur sa fiche, sa note ne bouge pas
#:   `classement`    il reste possible, mais sa note baisse
NIVEAU_EXCLUSION = 'exclusion'
NIVEAU_SURVEILLANCE = 'surveillance'
NIVEAU_CLASSEMENT = 'classement'

NIVEAUX = {
    NIVEAU_EXCLUSION: "Contre-indication",
    NIVEAU_SURVEILLANCE: "À surveiller",
    NIVEAU_CLASSEMENT: "Facteur de classement",
}

#: Ce qu'une règle de niveau `classement` retire à la note.
#:
#: Moins qu'une contre-indication relevée au RCP (40) et qu'une interaction
#: (20) : une règle de classement dit « moins indiqué ici », pas « dangereux ».
PENALITE_CLASSEMENT = 15


#: Seuils biologiques qui contraignent, et ce qu'ils visent.
#:
#: Pourquoi des nombres à côté des mots
#: ------------------------------------
#: Un antécédent est un mot, un résultat est un nombre. « Maladie rénale
#: chronique » ne dit pas si la metformine est déconseillée ou interdite ; un
#: DFG à 28 le dit. Un seuil ne dépend d'aucune tournure de phrase : il
#: s'écrit, se relit et s'éprouve.
#:
#: Le cas qui a motivé cette table : patient au DFG de 28, sous 2 g de
#: metformine par jour — contre-indication formelle sous 30 — et kaliémie à
#: 5,8 sous spironolactone **et** sacubitril/valsartan, deux traitements qui
#: l'élèvent. Rien ne le signalait.
#:
#: Les seuils sont ceux des RCP. Ils sont **volontairement peu nombreux** :
#: quatre mesures, celles qu'un dossier porte presque toujours. Chaque entrée
#: dit sa mesure, son sens, sa valeur, ce qu'elle vise, à quel niveau, et
#: pourquoi.
SEUILS_BIOLOGIQUES = [
    {
        'mesure': 'dfg',
        'libelle': 'DFG inférieur à 30 mL/min',
        'sens': '<', 'valeur': 30,
        'niveau': NIVEAU_EXCLUSION,
        'groupes': ['A10'],
        'cibles': ['metformine', 'ibuprofene', 'ketoprofene', 'diclofenac',
                   'naproxene', 'piroxicam'],
        'motif': "Metformine contre-indiquée sous 30 mL/min (risque d'acidose "
                 "lactique). Anti-inflammatoires non stéroïdiens à proscrire : "
                 "aggravation de la fonction rénale.",
    },
    {
        'mesure': 'dfg',
        'libelle': 'DFG inférieur à 60 mL/min',
        'sens': '<', 'valeur': 60,
        # Son propre motif dit « déconseillés » et « adaptation des
        # posologies » : cela ne justifie pas une exclusion.
        'niveau': NIVEAU_CLASSEMENT,
        'groupes': ['M01'],
        'cibles': ['ibuprofene', 'ketoprofene', 'diclofenac', 'naproxene',
                   'piroxicam'],
        'motif': "Anti-inflammatoires non stéroïdiens déconseillés : "
                 "néphrotoxicité. Adaptation des posologies à prévoir.",
    },
    {
        'mesure': 'kaliemie',
        'libelle': 'kaliémie supérieure à 5,5 mmol/L',
        'sens': '>', 'valeur': 5.5,
        'niveau': NIVEAU_EXCLUSION,
        # `amiloride` et `triamterene` ajoutés après P3b : le motif de la règle
        # disait déjà « diurétiques épargneurs de potassium », mais la liste ne
        # nommait que la spironolactone et l'éplérénone. Le trou est apparu
        # quand la génération par classe ATC, devenue plus juste, a proposé
        # MODAMIDE — de l'amiloride — à un patient dont la kaliémie était à 5,8.
        #
        # Une génération plus fine expose les tables incomplètes. C'est un bon
        # signe, et une raison de les relire à chaque phase.
        'cibles': ['spironolactone', 'eplerenone', 'amiloride', 'triamterene',
                   'ramipril', 'perindopril', 'enalapril', 'lisinopril',
                   'valsartan', 'losartan', 'candesartan',
                   'ibuprofene', 'ketoprofene', 'diclofenac'],
        'motif': "Hyperkaliémie : diurétiques épargneurs de potassium, "
                 "inhibiteurs de l'enzyme de conversion, sartans et "
                 "anti-inflammatoires non stéroïdiens l'aggravent.",
    },
    {
        'mesure': 'natremie',
        'libelle': 'natrémie inférieure à 130 mmol/L',
        'sens': '<', 'valeur': 130,
        # Une hyponatrémie sous furosémide appelle une réévaluation et une
        # surveillance ; elle ne fait pas du furosémide un mauvais
        # traitement. C'est la règle qui a montré que le niveau unique
        # était faux.
        'niveau': NIVEAU_SURVEILLANCE,
        'groupes': ['C03'],
        'cibles': ['hydrochlorothiazide', 'indapamide', 'furosemide',
                   'carbamazepine'],
        'motif': "Hyponatrémie : les diurétiques thiazidiques et de l'anse "
                 "l'aggravent.",
    },
    {
        'mesure': 'transaminases',
        'libelle': 'transaminases supérieures à trois fois la normale',
        'sens': '>', 'valeur': 120,
        # Le motif dit lui-même « posologie réduite » pour le paracétamol :
        # une exclusion le contredisait.
        'niveau': NIVEAU_SURVEILLANCE,
        'groupes': ['C10'],
        'cibles': ['methotrexate', 'paracetamol', 'atorvastatine',
                   'simvastatine', 'rosuvastatine', 'amiodarone'],
        'motif': "Cytolyse hépatique : méthotrexate, statines et amiodarone "
                 "sont hépatotoxiques ; le paracétamol demande une posologie "
                 "réduite.",
    },
    # ── Constantes ───────────────────────────────────────────────────────
    #
    # Les quatre règles qui suivent lisent des constantes et non des résultats
    # de laboratoire. Elles répondent à un essai précis : chez un patient à
    # 96/58 avec une fraction d'éjection à 30 %, le moteur proposait du
    # timolol, du trandolapril et du vérapamil. Les trois sont ici.
    {
        # Une seule règle pour les deux nombres de la pression : voir la note
        # de `contraintes_biologiques` sur le double compte d'un même fait
        # clinique. PAS et PAD se déclenchent presque toujours ensemble ; l'une
        # ou l'autre suffit à établir l'hypotension, et une seule pénalité
        # doit s'appliquer.
        'libelle': 'pression artérielle basse (systolique < 100 ou '
                   'diastolique < 60 mmHg)',
        'conditions': [
            {'mesure': 'systolique', 'sens': '<', 'valeur': 100},
            {'mesure': 'diastolique', 'sens': '<', 'valeur': 60},
        ],
        # Déclasse sans interdire : la décision dépend de la tolérance et de
        # l'objectif tensionnel, que le moteur ne connaît pas.
        'niveau': NIVEAU_CLASSEMENT,
        'groupes': ['C02', 'C03', 'C07', 'C08', 'C09'],
        'cibles': ANTIHYPERTENSEURS,
        'motif': "Hypotension : tout antihypertenseur supplémentaire expose "
                 "au collapsus et à la dégradation de la fonction rénale. "
                 "L'ajustement porte d'abord sur le traitement en cours.",
    },
    {
        'mesure': 'fevg',
        'libelle': "fraction d'éjection ventriculaire gauche inférieure à 40 %",
        'sens': '<', 'valeur': 40,
        'niveau': NIVEAU_EXCLUSION,
        'cibles': substances_des_classes('calcique_bradycardisant',
                                         'antiarythmique_i'),
        'motif': "Fraction d'éjection abaissée : les inhibiteurs calciques "
                 "bradycardisants et les antiarythmiques de classe I sont "
                 "contre-indiqués par leur effet inotrope négatif.",
    },
    {
        'mesure': 'frequence_cardiaque',
        'libelle': 'fréquence cardiaque inférieure à 50 battements par minute',
        'sens': '<', 'valeur': 50,
        'niveau': NIVEAU_EXCLUSION,
        'cibles': substances_des_classes('betabloquant',
                                         'calcique_bradycardisant',
                                         'antiarythmique_iii', 'digitalique')
                  + ['ivabradine'],
        'motif': "Bradycardie : bêta-bloquants, inhibiteurs calciques "
                 "bradycardisants, amiodarone, digitaliques et ivabradine "
                 "ralentissent encore la conduction.",
    },
    {
        # La tachycardie n'existait pas dans le moteur : la seule règle sur la
        # fréquence était « inférieure à 50 ». Chez un patient à 112 en
        # décompensation, elle signale la congestion et pèse sur la conduite
        # bêta-bloquante — on poursuit sans majorer en phase aiguë.
        #
        # Surveillance, jamais exclusion : une tachycardie ne contre-indique
        # pas un bêta-bloquant, elle en est plutôt une indication.
        'mesure': 'frequence_cardiaque',
        'libelle': 'fréquence cardiaque supérieure à 100 battements par minute',
        'sens': '>', 'valeur': 100,
        'niveau': NIVEAU_SURVEILLANCE,
        'groupes': ['C07'],
        'cibles': substances_des_classes('betabloquant', 'digitalique',
                                         'antiarythmique_iii'),
        'motif': "Tachycardie : en décompensation elle traduit la congestion. "
                 "Poursuivre le bêta-bloquant sans le majorer en phase aiguë ; "
                 "traiter la cause avant d'ajuster la fréquence.",
    },
]


def _nombre(valeur):
    """Rend un nombre, ou None. Ne rien savoir n'est pas un résultat."""
    if valeur is None or valeur == '':
        return None
    try:
        return float(str(valeur).replace(',', '.').strip())
    except (TypeError, ValueError):
        return None


def contraintes_biologiques(mesures: dict) -> list:
    """Rend les seuils que les résultats biologiques franchissent.

    Une mesure absente, vide ou illisible ne déclenche rien : ne rien savoir
    n'est pas la même chose que constater une anomalie, et signaler dans le
    doute ferait perdre au signalement tout son poids.

    Pourquoi une règle peut porter plusieurs conditions
    ----------------------------------------------------
    La pression artérielle systolique et la pression diastolique sont deux
    nombres pour **un seul fait clinique** : l'hypotension. Deux règles
    distinctes — l'une par mesure, comme le reste de la table — se
    déclenchaient quasi toujours ensemble, puisqu'une PAS basse s'accompagne
    presque toujours d'une PAD basse. Chaque candidat perdait la pénalité de
    classement deux fois pour la même cause.

    Mesuré sur un patient à 96/58 en insuffisance cardiaque décompensée : les
    douze candidats recrutés pour sa classe — diurétiques, bêta-bloquants,
    bloqueurs du SRAA, exactement ce que la pathologie appelle — perdaient
    chacun 30 points au lieu de 15, et passaient tous sous le seuil de
    pertinence. Le moteur, corrigé la veille contre l'excès de propositions,
    tombait dans l'excès inverse : plus rien à proposer.

    Une règle porte donc soit `mesure`/`sens`/`valeur` — le cas courant, une
    mesure — soit `conditions`, une liste de ces mêmes triplets. La première
    condition franchie suffit à déclencher la règle, **une seule fois** :
    la pénalité se compte par fait clinique, pas par nombre qui le mesure.
    """
    franchis = []
    for seuil in SEUILS_BIOLOGIQUES:
        conditions = seuil.get('conditions') or [
            {'mesure': seuil['mesure'], 'sens': seuil['sens'],
             'valeur': seuil['valeur']}]
        for condition in conditions:
            valeur = _nombre((mesures or {}).get(condition['mesure']))
            if valeur is None:
                continue
            depasse = (valeur < condition['valeur'] if condition['sens'] == '<'
                       else valeur > condition['valeur'])
            if depasse:
                franchis.append(dict(seuil, mesure=condition['mesure'],
                                     mesure_relevee=valeur))
                break
    return franchis


def traitements_a_reconsiderer(traitements, antecedents: str = '',
                               mesures: dict = None) -> list:
    """Confronte les traitements **en cours** aux contraintes du patient.

    Pourquoi cette fonction existe
    ------------------------------
    Les contraintes ne portaient que sur les médicaments *proposés*. Un patient
    prenant 2 g de metformine par jour avec un DFG de 28 — contre-indication
    formelle sous 30 — n'était averti de rien : ses traitements ne servaient
    qu'à chercher des interactions avec les suggestions.

    C'est pourtant là que se trouvent les erreurs qui durent : une nouvelle
    proposition est relue, un traitement ancien ne l'est plus.

    Ils sont **signalés, jamais écartés**. On ne retire pas le traitement d'un
    patient depuis un écran de suggestion : on le porte à la connaissance du
    médecin, avec la règle et son motif.
    """
    regles = contraintes_actives(antecedents) + contraintes_biologiques(mesures)
    if not regles:
        return []

    releves = []
    for saisie in (traitements or []):
        saisie = (saisie or '').strip()
        if not saisie:
            continue
        # La **même** évaluation que pour les candidats. Cette fonction avait
        # sa propre boucle de rapprochement : deux chemins pour une seule
        # question, qui pouvaient diverger — et divergeaient, puisque l'un
        # s'arrêtait au premier verdict et ignorait les niveaux.
        #
        # Un traitement en cours n'est pas une fiche du catalogue : il n'a
        # qu'un texte, donc pas de groupe ATC. Le filet de classe ne joue pas
        # ici, et c'est juste — on ne va pas alerter sur une saisie libre au
        # motif d'une classe qu'on n'a pas établie.
        for verdict in confronter_aux_regles({'title': saisie}, regles):
            releves.append({
                'traitement': saisie,
                'antecedent': verdict['regle'],
                'cible': verdict['cible'],
                'motif': verdict['motif'],
                # Le niveau que la règle porte. Signalés, jamais retirés : on
                # ne retire pas un traitement en cours depuis un écran de
                # suggestion. Mais le médecin doit lire la différence entre
                # « contre-indiqué » et « à surveiller ».
                'niveau': verdict['niveau'],
                'niveau_libelle': NIVEAUX.get(verdict['niveau'],
                                              verdict['niveau']),
            })

    if releves:
        logger.warning("Traitements en cours a reconsiderer : %d", len(releves))
    return releves


def classes_therapeutiques_de(texte: str) -> set:
    """Rend les classes pharmacologiques que ce texte nomme.

    Le texte peut être une saisie du médecin — « Bisoprolol 5 mg » — ou le
    titre et les substances d'une fiche. Même appariement que partout :
    accents repliés, mot entier des deux côtés.

    Une même saisie peut porter deux classes, et c'est voulu :
    « Sacubitril/Valsartan » est à la fois un ARNI et un sartan. Proposer un
    sartan à ce patient est bien une redondance.
    """
    texte = _plier(str(texte or ''))
    if not texte:
        return set()
    return {cle for cle, classe in CLASSES_THERAPEUTIQUES.items()
            if any(re.search(r'\b%s' % re.escape(s), texte)
                   for s in classe['substances'])}


def _texte_du_medicament(med: dict) -> str:
    """Le titre, les substances et la forme, repliés — de quoi apparier.

    Sorti d'`appliquer_contraintes`, où il était écrit en clair : trois
    fonctions cherchent désormais des substances dans une fiche, et elles
    doivent chercher dans le même texte. Une divergence ici ferait qu'une règle
    reconnaîtrait un médicament qu'une autre ne voit pas.
    """
    return _plier(' '.join([
        str(med.get('title') or ''),
        ' '.join(str(s) for s in (med.get('substances') or [])),
        str(med.get('forme') or ''),
    ]))


def couvert_par_le_traitement(medications: list, traitements) -> tuple:
    """Sépare ce que le traitement en cours couvre déjà, ou lui interdit.

    Pourquoi cette fonction existe
    ------------------------------
    Le traitement en cours n'était lu que pour deux choses : chercher des
    interactions, et se voir confronté aux contraintes du patient. Il n'était
    **jamais** comparé aux propositions.

    Le moteur ne pouvait donc pas savoir ce qu'il redisait. Mesuré chez un
    patient sous bisoprolol, sacubitril/valsartan, furosémide, spironolactone,
    empagliflozine et apixaban, l'écran proposait du **timolol** et du
    **pindolol** — deux bêta-bloquants de plus — et du **trandolapril**, un
    inhibiteur de l'enzyme de conversion, alors qu'un ARNI était en place.

    Appartenir à la classe que le diagnostic appelle ne suffit pas : encore
    faut-il que la place soit libre.

    Deux motifs, qu'il ne faut pas confondre
    ----------------------------------------
    `redondance` — la classe est déjà occupée. C'est *inutile*.
    `association` — les deux classes ne se prescrivent pas ensemble. C'est
    *dangereux*, et le motif le dit.

    Rend `(retenus, écartés)`. Les écartés portent leur motif et le traitement
    en cause : un médicament retiré en silence emporte avec lui la raison de
    son retrait.
    """
    medications = list(medications or [])
    saisies = [s for s in (traitements or []) if (s or '').strip()]
    if not medications or not saisies:
        return medications, []

    # La classe de chaque traitement en cours, une fois pour toutes.
    en_cours = {}
    for saisie in saisies:
        for cle in classes_therapeutiques_de(saisie):
            en_cours.setdefault(cle, saisie.strip())
    if not en_cours:
        return medications, []

    logger.info("Traitement en cours : classes %s", sorted(en_cours))

    retenus, ecartes = [], []
    for med in medications:
        classes = classes_therapeutiques_de(_texte_du_medicament(med))
        if not classes:
            # Hors du cardiovasculaire, la table ne sait rien. Elle laisse
            # passer plutôt que d'écarter sans savoir.
            retenus.append(med)
            continue

        touche = None

        # La **même molécule** d'abord.
        #
        # La comparaison ne portait que sur les classes : un FUROSEMIDE proposé
        # à un patient déjà sous furosémide recevait exactement la même alerte
        # qu'un BURINEX — « même classe que … (diurétique de l'anse) ». Mesuré :
        # les deux sortaient mot pour mot identiques, alors que l'un est le
        # traitement en cours lui-même et l'autre une autre molécule.
        #
        # Proposer à nouveau ce que le patient prend déjà n'est pas un choix
        # thérapeutique : c'est une question de posologie. L'écran doit le dire
        # autrement.
        #
        # La comparaison se fait sur le texte de la saisie, à frontière de mot
        # et accents repliés — comme partout ailleurs. Aucune table nouvelle :
        # les substances de la fiche font foi.
        deja_prescrite = None
        for substance in (med.get('substances') or []):
            plie = _plier(str(substance or '')).strip()
            if len(plie) < _LONGUEUR_SUBSTANCE_MINIMALE:
                continue
            for saisie in saisies:
                if re.search(r'\b%s' % re.escape(plie), _plier(saisie)):
                    deja_prescrite = (substance, saisie.strip())
                    break
            if deja_prescrite:
                break

        if deja_prescrite:
            substance, saisie = deja_prescrite
            # Conservé, comme l'intensification par classe : on ne retire pas
            # une molécule juste au motif qu'elle est déjà là — c'est peut-être
            # la dose qu'il faut revoir. Le score, le rang et la sélection ne
            # changent pas ; seule l'alerte diffère.
            med.setdefault('alertes', []).append({
                'regle': 'substance déjà prescrite',
                'cible': str(substance),
                'par_classe': False,
                'motif': "%s est déjà le traitement en cours (« %s »). Il ne "
                         "s'agit pas d'un ajout : envisager une adaptation de "
                         "posologie ou une intensification plutôt qu'une "
                         "nouvelle prescription."
                         % (substance, saisie),
            })
            retenus.append(med)
            continue

        # La redondance ensuite : c'est le cas le plus fréquent, et son motif
        # est le plus simple à lire.
        #
        # Mais partager une classe n'est pas toujours faire double emploi.
        # Deux bêta-bloquants sont une duplication : jamais. Un second
        # diurétique de l'anse peut être une **intensification**, et c'est la
        # conduite d'une congestion importante — l'écarter comme doublon
        # interdirait le traitement même de la décompensation. La table le dit,
        # classe par classe, par son champ `cumul`.
        commune = classes & set(en_cours)
        cumulables = {c for c in commune
                      if CLASSES_THERAPEUTIQUES[c].get('cumul') == 'possible'}
        duplications = commune - cumulables

        if duplications:
            cle = sorted(duplications)[0]
            libelle = CLASSES_THERAPEUTIQUES[cle]['libelle']
            touche = {
                'etage': 'redondance',
                'traitement': en_cours[cle],
                'classe': libelle,
                'motif': "Déjà couvert par le traitement en cours : %s est "
                         "un %s, comme « %s »."
                         % (med.get('title') or 'ce médicament', libelle,
                            en_cours[cle]),
            }
        elif cumulables:
            # Il reste proposé, avec l'alerte. Le moteur ne sait pas trancher
            # entre « majorer l'existant » et « ajouter » — il pose la question
            # au lieu de décider à la place du médecin.
            cle = sorted(cumulables)[0]
            libelle = CLASSES_THERAPEUTIQUES[cle]['libelle']
            med.setdefault('alertes', []).append({
                'regle': 'même classe que le traitement en cours',
                'cible': libelle,
                'par_classe': False,
                'motif': "Même classe que « %s » (%s). Ce n'est pas "
                         "nécessairement un doublon : une intensification de "
                         "la stratégie en place peut être indiquée. Vérifier "
                         "s'il faut majorer l'existant plutôt qu'ajouter."
                         % (en_cours[cle], libelle),
            })
            retenus.append(med)
            continue
        else:
            for regle in ASSOCIATIONS_PROSCRITES:
                a, b = regle['classes']
                paire = ((a in classes and b in en_cours)
                         or (b in classes and a in en_cours))
                if not paire:
                    continue
                # La classe du patient est celle des deux qu'il prend déjà.
                cle_patient = b if a in classes else a
                touche = {
                    'etage': 'association',
                    'traitement': en_cours[cle_patient],
                    'classe': CLASSES_THERAPEUTIQUES[cle_patient]['libelle'],
                    'motif': "%s Traitement en cours : « %s »."
                             % (regle['motif'], en_cours[cle_patient]),
                }
                break

        if touche:
            med['couvert_par'] = touche
            med['motif_ecart'] = touche['motif']
            med['etage_ecart'] = touche['etage']
            ecartes.append(med)
        else:
            retenus.append(med)

    if ecartes:
        logger.info("Traitement en cours : %d proposition(s) ecartee(s) sur %d",
                    len(ecartes), len(medications))
    return retenus, ecartes


def contraintes_actives(antecedents: str) -> list:
    """Rend les règles que la saisie d'antécédents déclenche.

    Une expression n'est reconnue que si **tous** ses mots se trouvent dans un
    **même segment** de la saisie. Deux antécédents distincts ne se
    recombinent donc pas en un troisième : « insuffisance cardiaque, atteinte
    rénale » ne déclenche pas la règle rénale, qui demande « insuffisance » et
    « rénale » côte à côte.
    """
    segments = [_plier(s) for s in re.split(r'[,;.\n]+', antecedents or '')
                if s.strip()]
    if not segments:
        return []

    actives = []
    for regle in CONTRAINTES_ANTECEDENTS:
        for expression in regle['antecedent']:
            if any(all(re.search(r'\b%s' % re.escape(mot), segment)
                       for mot in expression)
                   for segment in segments):
                actives.append(regle)
                break
    return actives


def appliquer_contraintes(medications: list, antecedents: str,
                          mesures: dict = None) -> tuple:
    """Sépare les médicaments qu'un antécédent interdit de ceux qu'il permet.

    Rend `(retenus, écartés)`. Chaque écarté porte `ecarte_par`, qui nomme
    l'antécédent, la cible reconnue et le motif : l'écran doit pouvoir dire ce
    qu'il a retiré et pourquoi. Un médicament qui disparaît sans explication
    est le défaut que le § 2.8 du rapport reprochait au filtrage silencieux.

    Les deux listes gardent l'ordre par score décroissant qu'elles avaient en
    entrant.
    """
    if not medications:
        return [], []

    # Les seuils biologiques écartent au même titre que les antécédents, et
    # avec plus de force : un DFG mesuré à 28 est une contre-indication
    # formelle, là où « maladie rénale chronique » ne dit pas jusqu'où.
    regles = contraintes_actives(antecedents) + [
        dict(s, libelle=s['libelle']) for s in contraintes_biologiques(mesures)]
    if not regles:
        return list(medications), []

    retenus, ecartes = [], []
    for med in medications:
        verdicts = confronter_aux_regles(med, regles)

        # Les deux niveaux qui n'écartent pas sont portés par la fiche.
        # `alertes` s'affiche, `declassements` sera pesé par
        # `peser_la_securite` — le seul endroit où une note baisse.
        #
        # On **ajoute** : `couvert_par_le_traitement` est passé avant et a pu
        # poser la sienne, pour une classe cumulable. Une affectation l'aurait
        # effacée sans bruit.
        #
        # Un verdict obtenu par le filet de classe s'affiche **toujours**,
        # quel que soit son niveau : il porte l'information « la substance
        # n'est pas dans la table », et c'est cela qui doit se voir. Un trou
        # qui se referme en silence est le défaut qu'on corrige ici.
        med.setdefault('alertes', []).extend(
            {'regle': v['regle'], 'motif': v['motif'], 'cible': v['cible'],
             'par_classe': v['par_classe']}
            for v in verdicts
            if v['niveau'] == NIVEAU_SURVEILLANCE or v['par_classe'])
        med['declassements'] = [
            {'regle': v['regle'], 'motif': v['motif'], 'cible': v['cible'],
             'par_classe': v['par_classe']}
            for v in verdicts if v['niveau'] == NIVEAU_CLASSEMENT]

        # Une exclusion suffit à écarter, et c'est la première rencontrée qui
        # est donnée pour motif. Les autres verdicts restent portés par la
        # fiche : le médecin qui reconsidère la décision doit voir tout ce qui
        # a joué, pas seulement ce qui a tranché.
        exclusion = next((v for v in verdicts
                          if v['niveau'] == NIVEAU_EXCLUSION), None)
        if exclusion:
            med['ecarte_par'] = {'antecedent': exclusion['regle'],
                                 'cible': exclusion['cible'],
                                 'motif': exclusion['motif']}
            med['motif_ecart'] = exclusion['motif']
            med['etage_ecart'] = 'antecedent'
            ecartes.append(med)
        else:
            med.pop('ecarte_par', None)
            retenus.append(med)

    if ecartes:
        logger.info("Contraintes d'antecedents : %d medicament(s) ecarte(s) sur %d",
                    len(ecartes), len(medications))
    return retenus, ecartes


def niveau_de(regle: dict) -> str:
    """Le niveau d'une règle. Une règle sans niveau exclut.

    Les huit règles d'antécédents n'en portent pas : elles sont toutes des
    contre-indications de manuel, et le défaut les laisse telles. Les seuils,
    eux, se qualifient un par un.
    """
    return (regle or {}).get('niveau') or NIVEAU_EXCLUSION


def confronter_aux_regles(med: dict, regles: list) -> list:
    """Confronte un médicament aux règles, et rend **tous** les verdicts.

    Pourquoi tous, et non le premier
    --------------------------------
    La boucle s'arrêtait au premier rapprochement trouvé. Tant que toute règle
    excluait, cela suffisait — un médicament écarté l'est. Depuis que les
    règles se qualifient, ce n'est plus vrai : un candidat peut relever d'une
    surveillance *et* d'un facteur de classement, et s'arrêter au premier
    perdrait le second.

    Le filet des groupes ATC
    ------------------------
    Le rapprochement se fait par nom de substance, sur des listes écrites à la
    main. **Une molécule absente de toutes les listes est invisible à toutes
    les règles.** Mesuré : chez un patient à 96/58, DFG 28, natrémie 128,
    huit règles se déclenchaient et pas une ne nommait le bendrofluméthiazide ;
    il ne restait que sa classe ATC C03 pour le noter, et il était proposé.

    C'est la troisième fois que ce défaut se manifeste — les épargneurs de
    potassium, puis le cardiovasculaire hors table.

    Quand une règle porte des groupes ATC et qu'aucune de ses cibles n'est
    reconnue, le groupe prend le relais — **au niveau surveillance, jamais
    exclusion**. Le nom reste la vérité ; le groupe empêche seulement le
    silence. Deux raisons de ne jamais exclure sur ce signal : les codes ATC
    d'une substance DrugBank incluent ceux de toutes ses associations (§ 12.5),
    et le trou doit se voir à l'écran plutôt que de se refermer sans bruit.
    """
    # Le rapprochement porte sur la substance autant que sur le titre :
    # « Warfarine » ne correspond à aucun titre du catalogue, et une
    # spécialité s'appelle ADVIL avant de s'appeler ibuprofène.
    texte = _texte_du_medicament(med)
    groupes = set(med.get('groupes_atc') or [])

    verdicts = []
    for regle in (regles or []):
        # Mot entier des deux côtés : sans la borne de fin, « aspirine » se
        # trouverait dans un mot plus long, et le projet s'est déjà fait
        # prendre par « anti » dans « anti-Xa ».
        cible = next((c for c in regle.get('cibles') or []
                      if re.search(r'\b%s\b' % re.escape(c), texte)), None)
        if cible:
            verdicts.append({
                'regle': regle['libelle'], 'cible': cible,
                'motif': regle['motif'], 'niveau': niveau_de(regle),
                'par_classe': False,
            })
            continue

        communs = groupes & set(regle.get('groupes') or [])
        if communs:
            # Le filet **plafonne**, il n'amortit pas. Une règle d'exclusion
            # retombe à la surveillance — c'est là qu'un code ATC pollué par
            # les associations pourrait faire un dégât. Une règle qui ne fait
            # que déclasser garde son niveau : sinon la molécule inconnue de
            # la table se classerait **mieux** que celle qui y figure, ce qui
            # récompenserait précisément le trou qu'on cherche à combler.
            niveau = niveau_de(regle)
            if niveau == NIVEAU_EXCLUSION:
                niveau = NIVEAU_SURVEILLANCE
            verdicts.append({
                'regle': regle['libelle'], 'cible': sorted(communs)[0],
                'motif': "%s — la substance de ce médicament n'est pas "
                         "reconnue par la règle ; le rapprochement se fait "
                         "sur sa classe ATC %s, à vérifier."
                         % (regle['motif'], sorted(communs)[0]),
                'niveau': niveau,
                'par_classe': True,
            })
    return verdicts


def contre_indications_relevees(fiche: dict, groupes: list) -> list:
    """Rapproche les antécédents du patient de la rubrique 4.3 du RCP.

    Un antécédent n'est signalé que si **tous** ses mots significatifs se
    trouvent dans une même phrase de la rubrique. La phrase est rendue avec
    le relevé : c'est elle qui permet au médecin de juger si le
    rapprochement tient.
    """
    texte = rubrique_rcp(fiche, '4.3')
    if not texte or not groupes:
        return []

    phrases = [p.strip() for p in re.split(r'(?<=[.;·])\s+', texte) if p.strip()]
    releves, vus = [], set()
    for phrase in phrases:
        plie = _plier(phrase)
        for groupe in groupes:
            libelle = groupe['libelle']
            if libelle in vus:
                continue
            if all(mot in plie for mot in groupe['mots']):
                vus.add(libelle)
                releves.append({
                    'terme': libelle,
                    'phrase': _abreger(phrase, 260),
                })
    return releves


def filter_contraindications(medications: list, age: int = 0, antecedents: str = ''):
    """Confronte chaque médicament proposé aux antécédents du patient.

    Cette fonction ne filtrait rien : elle portait un « TODO », et sa seule
    règle testait la présence du mot « enfant » dans le titre du médicament,
    ce qui ne pouvait écarter personne.

    Elle lit maintenant la rubrique 4.3 du RCP et y cherche les antécédents
    saisis. Elle **signale** au lieu de retirer, et c'est délibéré : un
    rapprochement de texte n'est pas une décision clinique, et un médicament
    écarté en silence emporte avec lui la raison de son retrait. Le médecin
    voit la phrase du RCP et tranche.

    Les médicaments signalés passent en fin de liste, sans disparaître.
    """
    termes = termes_des_antecedents(antecedents)
    if not medications:
        return medications

    for med in medications:
        med['contre_indications'] = []

    if not termes:
        return medications

    # Les fiches sont relues par identifiant, en une seule requête.
    par_identifiant = {}
    for med in medications:
        brut = med.get('fiche_id') or med.get('id')
        try:
            par_identifiant.setdefault(ObjectId(brut), []).append(med)
        except Exception:
            continue
    if not par_identifiant:
        return medications

    try:
        fiches = db.medicines.find({'_id': {'$in': list(par_identifiant)}},
                                   {'sections': 1})
        for fiche in fiches:
            releves = contre_indications_relevees(fiche, termes)
            if releves:
                for med in par_identifiant[fiche['_id']]:
                    med['contre_indications'] = releves
    except Exception as err:
        logger.warning("Contre-indications : %s", err)
        return medications

    signales = sum(1 for m in medications if m.get('contre_indications'))
    if signales:
        logger.info("Contre-indications : %d medicament(s) signale(s) sur %d",
                    signales, len(medications))
    # Signalés en fin de liste, jamais retirés, puis par rang thérapeutique et
    # par score décroissant à l'intérieur de chaque groupe. Trier sur le seul
    # signalement suffisait à défaire l'ordre par score, et l'écran retrouvait
    # la suite inexplicable qu'il présentait avant : 95, 90, 80, 75, 95, 80.
    medications.sort(key=lambda m: ((1 if m.get('contre_indications') else 0,)
                                    + _ordre_therapeutique(m)))
    return medications


#: Longueurs retenues pour chaque rubrique. Une invite qui grossit sans
#: limite coûte du temps et dilue ce qui compte : les indications disent à
#: quoi sert le médicament, les contre-indications disent à qui l'éviter.
LONGUEUR_INDICATIONS = 450
LONGUEUR_CONTRE_INDICATIONS = 450
MEDICAMENTS_EN_CONTEXTE = 3


def _texte_de(blocs) -> str:
    """Aplatit le contenu d'une rubrique, qui est une liste de blocs."""
    morceaux = []
    for bloc in blocs or []:
        if isinstance(bloc, dict):
            morceaux.append(str(bloc.get('text') or ''))
        else:
            morceaux.append(str(bloc))
    return ' '.join(m.strip() for m in morceaux if m.strip())


def rubrique_rcp(fiche: dict, prefixe: str) -> str:
    """Rend le texte d'une rubrique du RCP, repérée par son numéro.

    « 4.1 » pour les indications thérapeutiques, « 4.3 » pour les
    contre-indications — ce sont des **sous-sections** de « 4. DONNEES
    CLINIQUES ». Mais « 2. COMPOSITION QUALITATIVE ET QUANTITATIVE » est une
    section de **premier niveau**, sans sous-section : ne chercher que dans les
    sous-sections la rendait invisible, et la composition revenait vide.

    Les deux niveaux sont donc lus, les sous-sections d'abord — c'est là que se
    trouvent les rubriques les plus demandées, et « 4 » ne doit pas rendre la
    section entière quand « 4.3 » est cherché.
    """
    sections = fiche.get('sections') or []
    for section in sections:
        for sous_section in section.get('subsections') or []:
            titre = str(sous_section.get('title') or '').strip()
            if titre.startswith(prefixe):
                return _texte_de(sous_section.get('content'))
    for section in sections:
        titre = str(section.get('title') or '').strip()
        if titre.startswith(prefixe):
            return _texte_de(section.get('content'))
    return ''


def _abreger(texte: str, longueur: int) -> str:
    texte = re.sub(r'\s+', ' ', texte or '').strip()
    if len(texte) <= longueur:
        return texte
    coupe = texte[:longueur]
    dernier = coupe.rfind(' ')
    return (coupe[:dernier] if dernier > longueur * 0.6 else coupe) + '...'


def contexte_clinique(medications_suggested: list) -> str:
    """Compose le contexte transmis au modèle, à partir des RCP réels.

    Les candidats viennent de la recherche vectorielle et portent leur
    identifiant Mongo : la fiche est relue par cet identifiant, ce qui est
    une lecture par clé. La version précédente cherchait un champ
    `denomination` qui n'existe sur aucune fiche, et ne trouvait donc rien.
    """
    if not medications_suggested:
        return ''

    identifiants = []
    for med in medications_suggested[:MEDICAMENTS_EN_CONTEXTE]:
        brut = med.get('id')
        try:
            identifiants.append(ObjectId(brut))
        except Exception:
            continue
    if not identifiants:
        return ''

    try:
        fiches = {d['_id']: d for d in db.medicines.find(
            {'_id': {'$in': identifiants}},
            {'title': 1, 'sections': 1, 'medicine_details.substances_actives': 1})}
    except Exception as err:
        logger.warning("Contexte clinique : %s", err)
        return ''

    morceaux = []
    for identifiant in identifiants:
        fiche = fiches.get(identifiant)
        if not fiche:
            continue
        substances = fiche.get('medicine_details', {}).get('substances_actives') or []
        indications = _abreger(rubrique_rcp(fiche, '4.1'), LONGUEUR_INDICATIONS)
        contre = _abreger(rubrique_rcp(fiche, '4.3'), LONGUEUR_CONTRE_INDICATIONS)
        if not (indications or contre):
            continue
        bloc = ["- %s" % fiche.get('title', '')]
        if substances:
            bloc.append("  Substances : %s" % ', '.join(substances[:4]))
        if indications:
            bloc.append("  Indications (RCP 4.1) : %s" % indications)
        if contre:
            bloc.append("  Contre-indications (RCP 4.3) : %s" % contre)
        morceaux.append('\n'.join(bloc))

    if not morceaux:
        return ''
    return ("\n**Rubriques des RCP du catalogue, pour les medicaments les plus "
            "proches des symptomes :**\n" + '\n'.join(morceaux) + '\n')


def generate_diagnostic(symptomes: str, antecedents: str = '', medications_suggested: list = None, language: str = 'fr'):
    """
    Génère un diagnostic médical détaillé avec Mistral AI enrichi par les données des BDs
    """
    if not MISTRAL_API_KEY:
        # Fallback si pas de clé API
        diagnostic = f"Analyse des symptômes: {symptomes}. "
        if 'fièvre' in symptomes.lower():
            diagnostic += "Syndrome fébrile détecté. "
        if 'douleur' in symptomes.lower():
            diagnostic += "Syndrome douloureux présent. "
        if 'toux' in symptomes.lower():
            diagnostic += "Symptômes respiratoires observés. "
        diagnostic += "Consultation médicale recommandée pour diagnostic précis."
        return diagnostic
    
    # 1. Le contexte vient des rubriques reelles du RCP.
    #
    # Il etait auparavant compose de deux requetes qui n aboutissaient jamais :
    # l une cherchait un champ `denomination`, l autre des champs `indications`
    # et `classe_therapeutique`, absents des 13 594 fiches. La seconde balayait
    # le catalogue par expression reguliere pour un resultat toujours vide.
    #
    # Le modele ne recevait donc que des noms de medicaments, et l hypothese
    # reposait sur lui seul.
    medical_context = contexte_clinique(medications_suggested)

    # 3. Créer le prompt enrichi pour Mistral
    if language == 'en':
        prompt = f"""You are a diagnostic support assistant for healthcare professionals. Output must be concise, professional, and immediately actionable.

Patient symptoms: {symptomes}
{"Medical history: " + antecedents if antecedents else ""}

{medical_context if medical_context else ""}

RESPOND WITH EXACTLY 3 SECTIONS. Section titles use **Title:** format (colon BEFORE the closing **).

IMPORTANT: Do NOT use **Any label:** inside section content. NEVER put a colon before closing ** inside content. Inside sections, use plain text or `**label** : value` (colon AFTER **).

**Probable primary diagnosis:**
Diagnosis name — Confidence: XX%
Short clinical justification (2-4 sentences).

**Differential diagnoses:**
[Diagnosis 1 — Probability: XX% — 1-2 sentence justification]
[Diagnosis 2 — Probability: XX% — 1-2 sentence justification]
Max 3. One per line.

**Conclusion and management:**
2-4 sentences: synthesis, red flags, relevant workup, next steps.

RULES:
- Exactly 3 **Title:** sections only
- NEVER use **Label:** with colon inside bold inside content
- Use `**label** : value` (colon AFTER **) if needed inside a section
- No patient education, professional vocabulary only"""
    else:
        prompt = f"""Tu es un assistant d'aide au diagnostic destiné à des professionnels de santé. Réponse concise, professionnelle, immédiatement exploitable.

Symptômes rapportés : {symptomes}
{"Antécédents médicaux : " + antecedents if antecedents else ""}

{medical_context if medical_context else ""}

RÉPONDS AVEC EXACTEMENT 3 SECTIONS. Les titres de section utilisent le format **Titre:** (deux-points AVANT la fermeture **).

ATTENTION : N'utilise PAS **Label:** à l'intérieur du contenu des sections. Ne mets JAMAIS deux-points avant ** dans le contenu. Si tu dois mettre un label, utilise `**label** : valeur` (deux-points APRÈS **).

**Diagnostic principal probable:**
Nom du diagnostic — Confiance : XX%
Justification clinique courte (2 à 4 phrases).

**Diagnostics différentiels:**
[Diagnostic 1 — Probabilité : XX% — 1-2 phrases de justification]
[Diagnostic 2 — Probabilité : XX% — 1-2 phrases de justification]
Maximum 3. Un par ligne.

**Conclusion et conduite à tenir:**
2 à 4 phrases : synthèse, signes de gravité, examens pertinents, conduite à tenir.

RÈGLES :
- Exactement 3 sections **Titre:** uniquement
- JAMAIS de **Label:** dans le contenu (jamais deux-points avant **)
- Utilise `**label** : valeur` (deux-points APRÈS **) si nécessaire
- Aucune vulgarisation, vocabulaire médical uniquement"""

    try:
        client = Mistral(api_key=MISTRAL_API_KEY)
        chat_response = client.chat.complete(
            model=MODELE_DIAGNOSTIC,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,  # Faible pour maximiser la précision clinique
            max_tokens=1000  # Format structuré plus long
        )
        
        diagnostic = chat_response.choices[0].message.content.strip()
        logger.info(f"Diagnostic IA enrichi généré pour: {symptomes}")
        return diagnostic
        
    except Exception as e:
        logger.error(f"Erreur génération diagnostic Mistral: {e}")
        # Fallback 3 sections, pas d'erreur technique affichée
        diag_name = "Syndrome non spécifié"
        confiance = "Faible"
        if 'fièvre' in symptomes.lower() or 'fievre' in symptomes.lower():
            diag_name = "Syndrome fébrile"
            confiance = "Moyenne"
        if 'douleur' in symptomes.lower():
            diag_name = "Syndrome douloureux"
            confiance = "Moyenne"
        if 'toux' in symptomes.lower():
            diag_name = "Infection respiratoire aiguë"
            confiance = "Modérée"
        if 'vomissement' in symptomes.lower() or 'nausée' in symptomes.lower() or 'nausee' in symptomes.lower():
            diag_name = "Trouble gastro-intestinal aigu"
            confiance = "Modérée"
        if 'vertige' in symptomes.lower() or 'étourdissement' in symptomes.lower() or 'etourdissement' in symptomes.lower():
            diag_name = "Syndrome vertigineux"
            confiance = "Moyenne"
        diagnostic = f"**Diagnostic principal probable:**\n{diag_name} — Confiance : {confiance}\nPrésentation clinique évocatrice. L'absence de données complémentaires limite la précision diagnostique. Un avis médical est nécessaire pour confirmer.\n\n**Diagnostics différentiels:**\nÀ déterminer — Examens complémentaires requis\n\n**Conclusion et conduite à tenir:**\n{diag_name} suspecté. Bilan clinique et paraclinique recommandé pour confirmation diagnostique et adaptation thérapeutique."
        return diagnostic


def generate_recommendations(medications: list, interactions: list, language: str = 'fr'):
    """
    Génère des recommandations basées sur l'analyse
    """
    recommendations = []
    
    # Textes en français
    if language == 'en':
        high_risk_text = "⚠️ WARNING: High-risk interactions detected - Urgent consultation recommended"
        interactions_text = "Monitor identified drug interactions"
        dosage_text = "Respect indicated dosages for each medication"
        regular_text = "Take medications at regular times"
        follow_up_text = "Monitor symptom progression over 48-72 hours"
        consult_text = "Consult in case of worsening or side effects"
    else:
        high_risk_text = "⚠️ ATTENTION: Interactions à haut risque détectées - Consultation urgente recommandée"
        interactions_text = "Surveiller les interactions médicamenteuses identifiées"
        dosage_text = "Respecter les posologies indiquées pour chaque médicament"
        regular_text = "Prendre les médicaments à heures régulières"
        follow_up_text = "Suivre l'évolution des symptômes sur 48-72h"
        consult_text = "Consulter en cas d'aggravation ou d'effets indésirables"
    
    if interactions:
        # La source ne porte aucun niveau de gravite : on ne peut plus
        # distinguer un « risque eleve » d un autre, et le pretendre serait
        # une affirmation sans fondement. L avertissement est donc emis pour
        # toute interaction detectee.
        recommendations.append(interactions_text)
    
    if medications:
        recommendations.append(dosage_text)
        recommendations.append(regular_text)
    
    recommendations.append(follow_up_text)
    recommendations.append(consult_text)
    
    return recommendations


def get_default_posologie(medication_name: str):
    """
    Retourne une posologie par défaut (placeholder)
    TODO: Extraire depuis les données MongoDB ou base de connaissances
    """
    # Règles génériques basiques
    if 'paracétamol' in medication_name.lower():
        return "1g toutes les 6h, max 4g/jour"
    elif 'ibuprofène' in medication_name.lower():
        return "400mg toutes les 6-8h, max 1200mg/jour"
    elif 'amoxicilline' in medication_name.lower():
        return "1g matin et soir pendant 7 jours"
    else:
        return "Selon prescription médicale"


@prescription_bp.route('/medications/search', methods=['GET'])
def search_medications():
    """Recherche simple de médicaments par nom"""
    query = request.args.get('q', '').strip()
    limit = int(request.args.get('limit', 10))
    
    if not query:
        return jsonify({'medications': []})
    
    try:
        # Recherche MongoDB
        medications = db.medicines.find(
            {'title': {'$regex': query, '$options': 'i'}},
            {'title': 1, 'medicine_details.forme': 1, 'medicine_details.laboratoire': 1}
        ).limit(limit)
        
        results = []
        for med in medications:
            results.append({
                'id': str(med['_id']),
                'title': med.get('title'),
                'forme': med.get('medicine_details', {}).get('forme', ''),
                'laboratoire': med.get('medicine_details', {}).get('laboratoire', '')
            })
        
        return jsonify({'medications': results})
        
    except Exception as e:
        logger.error(f"Erreur recherche médicaments: {e}")
        return jsonify({'error': str(e)}), 500
