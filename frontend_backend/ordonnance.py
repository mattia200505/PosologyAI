# -*- coding: utf-8 -*-
"""Vérification d'une ordonnance — action 3.1 de l'audit UX.

L'audit la décrivait ainsi : « à partir d'une liste de médicaments, ce que le
praticien doit voir en premier — contre-indications croisées, interactions
entre les lignes de l'ordonnance, alertes de surveillance. La donnée existe
déjà ; c'est l'écran qui manque. »

## Ce que cet écran n'est pas

L'application possédait déjà un assistant de prescription : on lui donne des
symptômes, il propose des médicaments. Il va du symptôme vers le traitement,
et s'appuie sur un modèle de langage.

Celui-ci va dans l'autre sens et ne s'appuie sur aucun modèle. On lui donne
une ordonnance déjà écrite, il dit ce que les données recensent à son sujet.
**Aucun appel à un LLM, aucune suggestion, aucun score inventé** : rien qu'un
rapprochement de faits, que le lecteur peut vérifier ligne à ligne dans le
RCP. Sur un écran qui touche à la prescription, une réponse invérifiable vaut
moins que pas de réponse.

## Les quatre contrôles, dans l'ordre où ils comptent

1. **Doublon de substance active.** Deux lignes qui portent la même molécule
   sous deux noms commerciaux — DOLIPRANE et DAFALGAN sont tous deux du
   paracétamol. C'est l'erreur de prescription la plus silencieuse : chaque
   ligne est correcte, seule leur somme ne l'est pas. Ce contrôle ne figurait
   pas dans l'audit ; il est ajouté ici parce que la donnée le permet sans
   effort et que le risque est réel.

2. **Interactions entre les lignes.** Croisement deux à deux au niveau de la
   substance, jamais du nom commercial. Sans niveau de gravité : la source
   n'en porte pas (cf. rapport P9-1), et une gradation inventée à cet endroit
   orienterait une décision de prescription.

3. **Contre-indications.** La rubrique 4.3 de chaque ligne, remontée telle
   quelle. 99 % des fiches en portent une.

4. **Surveillance renforcée.** Les 491 spécialités sous triangle noir.

## Ce que l'écran dit quand il ne sait pas

Un médicament non apparié à DrugBank ne peut pas être croisé. L'écran le
nomme au lieu de le passer sous silence : « aucune interaction trouvée » et
« ce médicament n'a pas pu être analysé » ne disent pas la même chose à un
prescripteur, et c'est la distinction que toute cette application s'efforce
de tenir depuis P9.
"""
import logging
import os

from bson.errors import InvalidId
from bson.objectid import ObjectId
from flask import Blueprint, current_app, jsonify, render_template, request
from pymongo import MongoClient

import interaction_i18n

logger = logging.getLogger(__name__)

MONGO_URI = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
MONGO_DB = os.getenv('MONGO_DB', 'medicsearch')

# Client propre au module, comme `prescription_helper` : la connexion Mongo
# n'est pas portée par `app` dans ce projet, et un blueprint qui irait la
# chercher dans `current_app` dépendrait d'un attribut qui n'existe pas.
db = MongoClient(MONGO_URI)[MONGO_DB]

ordonnance_bp = Blueprint('ordonnance', __name__)

#: Au-delà, l'écran cesse d'être lisible et le croisement deux à deux devient
#: coûteux : vingt lignes font déjà cent quatre-vingt-dix paires.
LIGNES_MAXIMUM = 20


@ordonnance_bp.route('/ordonnance')
def page_ordonnance():
    lang = request.args.get('lang', 'fr')
    return render_template('ordonnance.html', lang=lang)


def _lire_lignes(identifiants):
    """Charge les fiches demandées. Les identifiants inconnus sont signalés.

    Un identifiant absent n'interrompt pas l'analyse : l'ordonnance est
    vérifiée sur les lignes trouvées, et les autres sont nommées dans la
    réponse. Échouer en bloc parce qu'une ligne sur six est introuvable
    priverait le prescripteur des cinq autres.
    """
    lignes, introuvables = [], []
    for identifiant in identifiants[:LIGNES_MAXIMUM]:
        try:
            objet = ObjectId(identifiant)
        except (InvalidId, TypeError):
            introuvables.append(identifiant)
            continue
        fiche = db.medicines.find_one(
            {'_id': objet},
            {'title': 1, 'url': 1, 'surveillance_renforcee': 1,
             'medicine_details.substances_actives': 1,
             'medicine_details.forme': 1, 'sections': 1})
        if not fiche:
            introuvables.append(identifiant)
            continue
        lignes.append(fiche)
    return lignes, introuvables


def _substances_par_ligne(lignes):
    """Substances DrugBank de chaque ligne, par l'URL de la fiche.

    L'appariement passe par le graphe et non par les substances déclarées dans
    MongoDB : c'est la couche DrugBank qui porte les interactions, et elle est
    normalisée là où les libellés du RCP ne le sont pas (« paracétamol »,
    « Paracetamol », « paracétamol monohydraté »).
    """
    connecteur = getattr(current_app, 'neo4j', None)
    if not connecteur or not getattr(connecteur, 'driver', None):
        return {}

    urls = [ligne['url'] for ligne in lignes if ligne.get('url')]
    if not urls:
        return {}

    par_url = {}
    try:
        with connecteur.driver.session(database=connecteur.database) as session:
            for row in session.run("""
                UNWIND $urls AS url
                MATCH (m:Medicine {url: url})-[:HAS_DRUGBANK_SUBSTANCE]->(s:DrugbankSubstance)
                RETURN url, collect(DISTINCT s.name) AS substances
            """, urls=urls):
                par_url[row['url']] = sorted(row['substances'])
    except Exception as err:
        logger.error(f"Substances de l'ordonnance : {err}")
    return par_url


def _doublons(lignes, substances_par_url):
    """Substances portées par plus d'une ligne."""
    porteuses = {}
    for ligne in lignes:
        for substance in substances_par_url.get(ligne.get('url'), []):
            porteuses.setdefault(substance, []).append({
                'id': str(ligne['_id']),
                'titre': ligne.get('title', ''),
            })
    return [{'substance': substance, 'lignes': portees}
            for substance, portees in sorted(porteuses.items())
            if len(portees) > 1]


def _interactions_croisees(lignes, substances_par_url, lang):
    """Interactions entre substances de deux lignes distinctes.

    La requête écarte `s1 = s2` : une substance n'interagit pas avec
    elle-même, et un doublon relève du contrôle précédent, où il est mieux
    nommé.
    """
    connecteur = getattr(current_app, 'neo4j', None)
    if not connecteur or not getattr(connecteur, 'driver', None):
        return [], 'not_loaded'

    couples = []
    for i, ligne_a in enumerate(lignes):
        for ligne_b in lignes[i + 1:]:
            for substance_a in substances_par_url.get(ligne_a.get('url'), []):
                for substance_b in substances_par_url.get(ligne_b.get('url'), []):
                    if substance_a != substance_b:
                        couples.append({
                            'a': substance_a, 'b': substance_b,
                            'ligne_a': str(ligne_a['_id']),
                            'ligne_b': str(ligne_b['_id']),
                            'titre_a': ligne_a.get('title', ''),
                            'titre_b': ligne_b.get('title', ''),
                        })
    if not couples:
        return [], 'ok'

    trouvees = []
    try:
        with connecteur.driver.session(database=connecteur.database) as session:
            for row in session.run("""
                UNWIND $couples AS couple
                MATCH (s1:DrugbankSubstance {name: couple.a})
                      -[r:INTERACTS_WITH]-(s2:DrugbankSubstance {name: couple.b})
                RETURN DISTINCT couple, r.description AS description
            """, couples=couples):
                couple = row['couple']
                anglais = row['description'] or ''
                francais = interaction_i18n.traduire(anglais)
                trouvees.append({
                    'ligne_a': couple['ligne_a'], 'ligne_b': couple['ligne_b'],
                    'titre_a': couple['titre_a'], 'titre_b': couple['titre_b'],
                    'substance_a': couple['a'], 'substance_b': couple['b'],
                    'description': anglais,
                    'description_fr': francais,
                })
    except Exception as err:
        logger.error(f"Interactions de l'ordonnance : {err}")
        return [], 'not_loaded'

    # Tri par paire de lignes, pour que l'écran regroupe ce qui concerne les
    # mêmes deux médicaments. L'ordre n'exprime aucune gravité.
    trouvees.sort(key=lambda x: (x['titre_a'], x['titre_b'], x['substance_b']))
    return trouvees, 'ok'


def rang_section_contre_indications(fiche):
    """Rang (1-indexé) de la section qui abrite la rubrique 4.3, ou `None`.

    Sert à renvoyer le lecteur vers la rubrique d'origine. Le rang est
    cherché plutôt que supposé : « 4. DONNEES CLINIQUES » est la quatrième
    section d'un RCP ANSM standard, mais les fiches EMA et les notices
    autonomes ne suivent pas ce plan, et un lien codé en dur y pointerait
    vers autre chose.
    """
    for rang, section in enumerate(fiche.get('sections') or [], 1):
        for sous_section in (section.get('subsections') or []):
            titre = (sous_section.get('title') or '').lower()
            if 'contre-indication' in titre or 'contre indication' in titre:
                return rang
    return None


def contre_indications_de(fiche):
    """Rubrique 4.3 de la fiche, remontée telle quelle.

    Publique parce que la fiche médicament s'en sert aussi : les
    contre-indications y sont désormais présentées avant la monographie, et
    non plus seulement enfouies en 4.3. Une seconde implémentation aurait
    divergé — celle-ci retire les puces du collecteur et la virgule finale,
    deux détails qu'on n'écrit pas deux fois de la même façon.
    """
    enonces = []
    for section in (fiche.get('sections') or []):
        for sous_section in (section.get('subsections') or []):
            titre = (sous_section.get('title') or '').lower()
            if 'contre-indication' not in titre and 'contre indication' not in titre:
                continue
            for item in (sous_section.get('content') or []):
                texte = (item.get('text') or '').strip()
                # Le collecteur préfixe les puces d'un point médian.
                texte = texte.lstrip('·•').strip().rstrip(',')
                if texte:
                    enonces.append(texte)
    return enonces


@ordonnance_bp.route('/api/ordonnance/analyse', methods=['POST'])
def analyser():
    donnees = request.get_json(silent=True) or {}
    identifiants = donnees.get('medicaments') or []
    lang = donnees.get('lang', 'fr')

    if not isinstance(identifiants, list) or not identifiants:
        return jsonify({'success': False,
                        'error': 'aucun médicament fourni'}), 400

    lignes, introuvables = _lire_lignes(identifiants)
    if not lignes:
        return jsonify({'success': False, 'error': 'aucune fiche trouvée',
                        'introuvables': introuvables}), 404

    substances_par_url = _substances_par_ligne(lignes)

    # Une ligne sans substance appariée ne peut être croisée avec rien. La
    # nommer vaut mieux que de laisser croire que l'ordonnance est indemne.
    non_appariees = [{'id': str(l['_id']), 'titre': l.get('title', '')}
                     for l in lignes if not substances_par_url.get(l.get('url'))]

    interactions, etat = _interactions_croisees(lignes, substances_par_url, lang)

    detail = []
    for ligne in lignes:
        detail.append({
            'id': str(ligne['_id']),
            'titre': ligne.get('title', ''),
            'forme': (ligne.get('medicine_details') or {}).get('forme', ''),
            'substances': substances_par_url.get(ligne.get('url'), []),
            'contre_indications': contre_indications_de(ligne),
            'surveillance_renforcee': ligne.get('surveillance_renforcee') == 'Oui',
        })

    return jsonify({
        'success': True,
        'etat_interactions': etat,
        'lignes': detail,
        'doublons': _doublons(lignes, substances_par_url),
        'interactions': interactions,
        'non_appariees': non_appariees,
        'introuvables': introuvables,
        'tronquee': len(identifiants) > LIGNES_MAXIMUM,
        'limite': LIGNES_MAXIMUM,
    })
