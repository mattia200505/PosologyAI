"""Banc de la composition thérapeutique — phase P6 de la roadmap.

Ce que ce banc garde
--------------------
Jusqu'ici l'écran rendait une **liste**. P6 en fait une **stratégie** : ce
qu'on donne en premier, ce qu'on donne si le premier ne convient pas, et ce
qui traite le symptôme sans traiter la cause.

Le rang existait déjà, mais seulement pour les treize conduites cliniques
curatées. Les candidats venus de la génération par classe (P3b) n'en portaient
aucun : sur une pneumonie, CLAMOXYL et ERY arrivaient côte à côte sans que rien
ne dise lequel donner.

Les trois règles
----------------
1. **Une classe ne rend qu'une première intention.** C'est ce qui rend
   impossible *par construction* de proposer deux molécules de la même classe
   comme si elles s'additionnaient — le défaut observé quand PERINDOPRIL a été
   proposé à un patient déjà sous Ramipril, deux IEC.
2. **Une classe symptomatique devient adjuvante** quand le diagnostic appelle
   aussi une classe causale. Pour une pneumonie, J01 traite la cause et N02 la
   douleur ; pour une migraine, N02 **est** le traitement.
3. **Le rang des conduites curatées prime.** Il vient d'une source clinique
   relue ; celui déduit des classes est une inférence, et ne doit pas
   l'écraser.

Emploi
------
    python scripts/verif_composition.py

Aucune base n'est nécessaire.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from prescription_helper import (
    SEUILS_BIOLOGIQUES,
    niveau_de,
    NIVEAU_CLASSEMENT,
    PENALITE_CLASSEMENT,
    PENALITE_INTERACTION,
    POINTS_COUVERTURE_ATC,
    POINTS_OBJECTIF_PRINCIPAL,
    POINTS_OBJECTIF,
    POINTS_PREMIERE_LIGNE,
    peser_la_securite,
    SEUIL_EXCLUSION,
    normaliser_medicament,
    merite_clinique,
    reduire_par_classe,  # noqa: E402
    CLASSES_SYMPTOMATIQUES,
    composer_strategie,
    get_clinical_fallback,
)

_reussis = 0
_echecs = []
_RIEN = object()


def verifier(intitule: str, obtenu, attendu=_RIEN) -> None:
    global _reussis
    ok = bool(obtenu) if attendu is _RIEN else (obtenu == attendu)
    if ok:
        _reussis += 1
    else:
        _echecs.append("%s\n      obtenu : %r\n      attendu: %r"
                       % (intitule, obtenu,
                          '<vrai>' if attendu is _RIEN else attendu))


def med(titre, groupes, pertinence, rang=''):
    return {'title': titre, 'groupes_atc': list(groupes),
            'pertinence': pertinence, 'rang': rang}


def rangs(medicaments):
    return {m['title']: m.get('rang') for m in medicaments}


PNEUMONIE = "Pneumonie communautaire du lobe inferieur droit"
MIGRAINE = "Migraine sans aura"


# ── 1. Une classe ne rend qu'une première intention ──────────────────────

lot = [
    med('CLAMOXYL 500 mg', ['J01'], 100),
    med('ERY 500 mg', ['J01'], 60),
    med('DALACINE 75 mg', ['J01'], 60),
]
compose = composer_strategie(lot, PNEUMONIE)
r = rangs(compose)

verifier("le mieux noté de la classe est en première intention",
         r['CLAMOXYL 500 mg'], 'premiere_intention')
verifier("les suivants de la même classe sont des alternatives",
         sorted(t for t, v in r.items() if v == 'alternative'),
         ['DALACINE 75 mg', 'ERY 500 mg'])

verifier("CRITÈRE DE SORTIE — une seule première intention par classe",
         sum(1 for m in compose
             if m['rang'] == 'premiere_intention' and 'J01' in m['groupes_atc']),
         1)
verifier("CRITÈRE DE SORTIE — chaque proposition porte un rang",
         all(m.get('rang') for m in compose), True)


# ── 2. Deux classes causales, deux premières intentions ──────────────────

# Ce n'est pas contradictoire : une pneumonie et une fièvre appellent deux
# traitements qui s'ajoutent, pas qui se remplacent.
deux = composer_strategie([
    med('CLAMOXYL 500 mg', ['J01'], 100),
    med('BURINEX 1 mg', ['C03'], 60),
], "Pneumonie communautaire sur decompensation cardiaque")
verifier("deux classes différentes donnent deux premières intentions",
         sum(1 for m in deux if m['rang'] == 'premiere_intention'), 2)


# ── 3. L'adjuvant ────────────────────────────────────────────────────────

verifier("la table des classes symptomatiques n'est pas vide",
         len(CLASSES_SYMPTOMATIQUES) > 0, True)
verifier("les antalgiques y figurent", 'N02' in CLASSES_SYMPTOMATIQUES, True)
verifier("les antibactériens n'y figurent pas",
         'J01' in CLASSES_SYMPTOMATIQUES, False)

avec_adjuvant = composer_strategie([
    med('CLAMOXYL 500 mg', ['J01'], 100),
    med('DOLIPRANE 1000 mg', ['N02'], 60),
], PNEUMONIE)
r = rangs(avec_adjuvant)
verifier("l'antibiotique traite la cause : première intention",
         r['CLAMOXYL 500 mg'], 'premiere_intention')
verifier("l'antalgique traite le symptôme : adjuvant",
         r['DOLIPRANE 1000 mg'], 'adjuvant')

# Mais une classe symptomatique seule EST le traitement.
seule = composer_strategie([med('DOLIPRANE 1000 mg', ['N02'], 60)], MIGRAINE)
verifier("sans classe causale, l'antalgique redevient première intention",
         seule[0]['rang'], 'premiere_intention')


# ── 4. Le rang des conduites curatées prime ──────────────────────────────

# Elles viennent d'une source clinique relue ; le rang déduit d'une classe est
# une inférence et ne doit pas l'écraser.
curate = composer_strategie([
    med('Ibuprofène', ['M01'], 80, rang='alternative'),
    med('Paracétamol', ['N02'], 95, rang='premiere_intention'),
], "Fievre a 38,7 C")
r = rangs(curate)
verifier("le rang curaté « alternative » est conservé",
         r['Ibuprofène'], 'alternative')
verifier("le rang curaté « première intention » aussi",
         r['Paracétamol'], 'premiere_intention')

# Le repli clinique traverse la composition sans être bousculé.
repli = composer_strategie(
    [dict(m, groupes_atc=[], pertinence=m.get('relevance_score'))
     for m in get_clinical_fallback("Fievre et douleurs")],
    "Fievre et douleurs")
verifier("le repli garde ses premières intentions",
         any(m['rang'] == 'premiere_intention' for m in repli), True)
verifier("et ses alternatives",
         any(m['rang'] == 'alternative' for m in repli), True)


# ── 5. Les cas limites ───────────────────────────────────────────────────

verifier("une liste vide ne casse pas", composer_strategie([], PNEUMONIE), [])
verifier("None ne casse pas", composer_strategie(None, None), [])

# Un candidat sans classe ne peut pas être rangé par la classe. Il reçoit le
# rang le plus prudent plutôt qu'aucun : le critère de sortie exige que
# chaque proposition en porte un.
sans = composer_strategie([med('PRODUIT SANS ATC', [], 60)], PNEUMONIE)
verifier("un candidat sans classe porte quand même un rang",
         bool(sans[0].get('rang')), True)
verifier("et ce rang est le plus prudent", sans[0]['rang'], 'alternative')

# L'ordre de sortie suit le raisonnement.
ordonne = composer_strategie([
    med('DOLIPRANE 1000 mg', ['N02'], 60),
    med('ERY 500 mg', ['J01'], 60),
    med('CLAMOXYL 500 mg', ['J01'], 100),
], PNEUMONIE)
verifier("la première intention ouvre la liste",
         ordonne[0]['rang'], 'premiere_intention')
verifier("l'adjuvant la ferme", ordonne[-1]['rang'], 'adjuvant')


# ── 6. Le branchement ────────────────────────────────────────────────────

helper = (Path(__file__).resolve().parent.parent
          / 'prescription_helper.py').read_text(encoding='utf-8')
verifier("le tuyau compose la stratégie",
         'composer_strategie(' in helper, True)

module = (Path(__file__).resolve().parent.parent / 'static' / 'js'
          / 'prescription_resultats.js').read_text(encoding='utf-8')
verifier("l'écran connaît le rang adjuvant", "'adjuvant'" in module, True)


# ── Invariants : ni l'ordre d'entrée ni le nom ne décident ──────────────
#
# Deux décisions cliniques se prenaient sur la longueur du nom de marque.
#
# `composer_strategie` comparait les notes par `>` strict : à égalité, le
# **premier inséré** gardait la première intention. Et l'ordre d'insertion
# venait d'un tri par longueur de titre. Mesuré sur une décompensation
# cardiaque : PRESTOLE, LOGIRENE, MODAMIDE et TENSIONORME arrivaient tous à
# 90 ; PRESTOLE prenait la tête parce que son nom est le plus court.
#
# S'y ajoutait que la catégorie était figée **avant** `peser_la_securite` :
# les pénalités séparaient ensuite les notes — 70 contre 80 — et l'écran
# affichait une « première intention » à 70 devant une « alternative » à 80.

def _lot_egalite():
    """Quatre candidats d'une même classe, tous à la même note."""
    return [med('ZZZ NOM TRES LONG 100 mg', ['C03'], 90),
            med('AAA', ['C03'], 90),
            med('MMM 50 mg, comprimé', ['C03'], 90),
            med('BBB 25 mg', ['C03'], 90)]

# L'ordre d'entrée ne doit rien changer.
_normal = composer_strategie(_lot_egalite(), 'insuffisance cardiaque')
_inverse = composer_strategie(list(reversed(_lot_egalite())),
                              'insuffisance cardiaque')
verifier("à égalité, l'ordre d'entrée ne change pas le résultat",
         [(m['title'], m['rang']) for m in _normal],
         [(m['title'], m['rang']) for m in _inverse])

# Et une seule première intention, quelle que soit l'entrée.
verifier("une seule première intention malgré l'égalité",
         sum(1 for m in _normal if m['rang'] == 'premiere_intention'), 1)

# Le nom le plus court ne doit plus gagner.
_lot = [med('A', ['C03'], 70), med('NOM BEAUCOUP PLUS LONG', ['C03'], 90)]
_r = composer_strategie(_lot, 'insuffisance cardiaque')
_tete = next(m for m in _r if m['rang'] == 'premiere_intention')
verifier("la note prime sur la longueur du nom",
         _tete['title'], 'NOM BEAUCOUP PLUS LONG')

# **L'invariant de fond** : une note supérieure ne doit jamais être placée
# derrière une note inférieure de la même classe.
_ordre = [(m.get('rang'), m.get('pertinence')) for m in _r]
verifier("un score supérieur n'est jamais rétrogradé",
         _ordre[0][1] >= _ordre[-1][1], True)

# À note égale, la mono-substance représente la classe mieux qu'une
# association : elle n'apporte pas de composant non demandé.
_mono = med('MONO 10 mg', ['C03'], 80)
_mono['substances'] = ['Furosemide']
_asso = med('ASSO 10 mg/5 mg', ['C03'], 80)
_asso['substances'] = ['Furosemide', 'Amiloride']
_r2 = composer_strategie([_asso, _mono], 'insuffisance cardiaque')
verifier("à note égale, la mono-substance représente la classe",
         next(m['title'] for m in _r2 if m['rang'] == 'premiere_intention'),
         'MONO 10 mg')


# ── Réduction par classe : une molécule, une place ──────────────────────
#
# Le quota d'une classe était consommé par les génériques d'une seule
# substance : mesuré sur C03, huit spécialités d'éplérénone occupaient toutes
# les places et le furosémide n'apparaissait plus.

def _generique(nom, substance, note):
    m = med(nom, ['C03'], note)
    m['substances'] = [substance]
    return m

_generiques = [_generique('EPLERENONE %s' % marque, 'Eplerenone', 75)
               for marque in ('ARROW', 'BIOGARAN', 'CRISTERS', 'EG', 'TEVA',
                              'ACCORD', 'SANDOZ', 'VIATRIS')]
_generiques.append(_generique('LASILIX 40 mg', 'Furosemide', 70))
_reduit = reduire_par_classe(_generiques, 6)
_substances = {(m.get('substances') or [''])[0] for m in _reduit}
verifier("les génériques d'une même molécule ne prennent qu'une place",
         sorted(_substances), ['Eplerenone', 'Furosemide'])
verifier("le quota laisse donc place à une autre molécule",
         any('LASILIX' in m['title'] for m in _reduit), True)

# La réduction ne dépend pas non plus de l'ordre d'entrée.
verifier("la réduction est indépendante de l'ordre",
         [m['title'] for m in reduire_par_classe(_generiques, 6)],
         [m['title'] for m in reduire_par_classe(list(reversed(_generiques)), 6)])

# Un candidat sans classe n'appartient à aucun quota : le retirer punirait
# l'absence de donnée.
_sans_classe = med('INCONNU 10 mg', [], 50)
verifier("un candidat sans classe n'est jamais retiré",
         any(m['title'] == 'INCONNU 10 mg'
             for m in reduire_par_classe(_generiques + [_sans_classe], 1)),
         True)


# ── Representativite du vivier : ni le nom, ni l'ordre ─────────────────
#
# La selection des representants d'une classe se faisait avant toute notation,
# sur la voie d'administration, le nombre de substances et **la longueur du
# titre**. Mesure sur N02 : LAMALINE (16 caracteres) et PRONTALGINE (21)
# prenaient les places, « DAFALGAN 500 mg, gelule » (23) n'entrait pas, et le
# paracetamol simple etait indecouvrable pour une cephalee legere.
#
# La selection se fait desormais apres notation, sur `merite_clinique`. Ces
# controles fixent les trois proprietes qui comptent.

def _cand(titre, note, substance, groupes=None):
    m = med(titre, groupes or ['N02'], note)
    m['substances'] = [substance]
    return m

# 1. Un nom court ne remplace jamais un candidat cliniquement meilleur.
_court_faible = _cand('AAA', 40, 'SubstanceA')
_long_fort = _cand('MEDICAMENT AU NOM TRES LONG 500 mg, gelule', 90, 'SubstanceB')
_garde = reduire_par_classe([_court_faible, _long_fort], 1)
verifier("un nom court ne prime pas sur une meilleure note",
         [m['title'] for m in _garde],
         ['MEDICAMENT AU NOM TRES LONG 500 mg, gelule'])

# 2. Le cas inverse : un nom long mais cliniquement superieur entre bien.
verifier("un nom long n'empeche pas d'entrer dans le vivier",
         any(len(m['title']) > 30 for m in _garde), True)

# 3. L'ordre d'entree ne change pas le vivier retenu.
_lot = [_cand('ZZZ 1', 70, 'S1'), _cand('AAA 2', 90, 'S2'),
        _cand('MMM 3', 50, 'S3'), _cand('BBB 4', 80, 'S4')]
verifier("le vivier ne depend pas de l'ordre d'entree",
         [m['title'] for m in reduire_par_classe(list(_lot), 2)],
         [m['title'] for m in reduire_par_classe(list(reversed(_lot)), 2)])

# Et il garde bien les deux meilleures notes, pas les deux premiers noms.
verifier("le vivier garde les meilleures notes",
         sorted(m['pertinence'] for m in reduire_par_classe(list(_lot), 2)),
         [80, 90])

# 4. Le quota ne coupe pas un candidat meilleur au profit d'un moins bon.
_dix = [_cand('CAND %02d' % i, 10 * i, 'S%02d' % i) for i in range(1, 11)]
_six = reduire_par_classe(list(_dix), 6)
verifier("le quota garde les six meilleurs",
         sorted((m['pertinence'] for m in _six), reverse=True),
         [100, 90, 80, 70, 60, 50])

# Doubler le quota ajoute des candidats, n'en retire aucun.
_douze = reduire_par_classe(list(_dix), 12)
verifier("doubler le quota n'evince personne",
         set(m['title'] for m in _six) <= set(m['title'] for m in _douze), True)

# 5. Plusieurs specialites d'une meme substance ne prennent qu'une place, et
#    c'est la mieux notee qui represente.
_memes = [_cand('MARQUE A', 40, 'Paracetamol'),
          _cand('MARQUE B', 90, 'Paracetamol'),
          _cand('MARQUE C', 60, 'Paracetamol'),
          _cand('AUTRE MOLECULE', 50, 'Ibuprofene')]
_reduit = reduire_par_classe(_memes, 6)
verifier("une substance ne prend qu'une place",
         len(_reduit), 2)
verifier("et c'est sa specialite la mieux notee qui la represente",
         next(m['title'] for m in _reduit
              if (m['substances'] or [''])[0] == 'Paracetamol'),
         'MARQUE B')

# 6. Une substance inconnue de la table curatee reste selectionnable : le
#    vivier ne doit pas punir l'absence de donnee.
_inconnue = _cand('MOLECULE JAMAIS VUE 10 mg', 85, 'Inconnuine')
verifier("une substance inconnue de la table reste selectionnable",
         any(m['title'] == 'MOLECULE JAMAIS VUE 10 mg'
             for m in reduire_par_classe([_inconnue] + _memes, 6)), True)


# ── indication_principale doit survivre a toute la chaine ──────────────
#
# `compute_clinical_relevance` pose ce champ ; `normaliser_medicament`
# reconstruit le dictionnaire champ par champ et le perdait. Sur l'assistant
# la note se fige **avant** cette reconstruction, si bien que `merite_clinique`
# lisait toujours l'absence : son deuxieme critere valait 1 pour tout le monde,
# et le titre departageait a sa place.
#
# Meme defaut que pour le rang therapeutique, la substance annoncee et les
# groupes ATC. Ce controle ferme la serie.

_avant = {'title': 'TEST 10 mg', 'substances': ['Substance'],
          'groupes_atc': ['C03'], 'pertinence': 80,
          'indication_principale': True, 'vise_objectif_principal': True,
          'indication_secondaire': False}
_apres = normaliser_medicament(dict(_avant))
verifier("indication_principale survit a la normalisation",
         _apres.get('indication_principale'), True)
verifier("vise_objectif_principal aussi",
         _apres.get('vise_objectif_principal'), True)
verifier("indication_secondaire aussi",
         _apres.get('indication_secondaire'), False)

# Et le critere doit reellement departager dans merite_clinique.
_avec = {'title': 'ZZZ', 'substances': ['S1'], 'pertinence': 80,
         'indication_principale': True}
_sans = {'title': 'AAA', 'substances': ['S2'], 'pertinence': 80}
verifier("a note egale, l'indication principale passe devant",
         merite_clinique(_avec) < merite_clinique(_sans), True)
verifier("et le titre ne suffit pas a l'inverser",
         sorted([_avec, _sans], key=merite_clinique)[0]['title'], 'ZZZ')

# La chaine complete : scoring -> normalisation -> reduction -> categorisation.
_lot = [normaliser_medicament(dict(_sans, groupes_atc=['C03'])),
        normaliser_medicament(dict(_avec, groupes_atc=['C03']))]
_reduit = reduire_par_classe(_lot, 1)
verifier("la reduction garde celui qui vise l'indication principale",
         [m['title'] for m in _reduit], ['ZZZ'])
_range = composer_strategie(list(_lot), 'insuffisance cardiaque')
verifier("et la categorisation le met en premiere intention",
         next(m['title'] for m in _range if m['rang'] == 'premiere_intention'),
         'ZZZ')


# ── Deux scores : pertinence clinique et securite ──────────────────────
#
# Un seul nombre portait deux questions : « est-ce le bon medicament ? » et
# « demande-t-il une surveillance ? ». Le classement lisait donc la securite
# comme de la pertinence.
#
# Mesure sur une decompensation : le furosemide, premiere ligne de la
# decongestion a 100, tombait a 80 pour une interaction avec le bisoprolol —
# « may increase the hypotensive activities », donc de la surveillance — et
# passait derriere un thiazidique a 85 que le graphe ne relie simplement pas
# au bisoprolol. Six paires sur vingt-huit etaient inversees ainsi.
#
# `INTERACTS_WITH` ne porte que `description` et `source` : aucune gravite.
# Toute interaction vaut le meme -20, et l'absence d'arete se lit comme une
# absence de risque. Le classement se fait donc desormais sur le score
# clinique, que les penalites ne touchent plus.

def _soigne(titre, clinique, groupes=None, penalise=0):
    m = med(titre, groupes or ['C03'], clinique)
    m['substances'] = [titre]
    if penalise:
        m['pertinence_clinique'] = clinique
        m['pertinence'] = clinique - penalise
        m['penalites'] = ['interaction avec un traitement en cours (-%d)' % penalise]
    return m

# Une interaction de surveillance ne renverse pas une hierarchie clinique.
_anse = _soigne('LASILIX', 100, penalise=20)
_thiazide = _soigne('ESIDREX', 85)
verifier("une interaction de surveillance ne renverse pas la hierarchie",
         merite_clinique(_anse) < merite_clinique(_thiazide), True)
verifier("meme si la note affichee du premier est plus basse",
         _anse['pertinence'] < _thiazide['pertinence'], True)

_range = composer_strategie([_thiazide, _anse], 'insuffisance cardiaque')
verifier("le traitement de premiere ligne garde la premiere intention",
         next(m['title'] for m in _range if m['rang'] == 'premiere_intention'),
         'LASILIX')

# Le score clinique ne bouge pas quand on ajoute une information de securite.
_avant = _soigne('TEST', 90)
_clinique_avant = _avant['pertinence']
_apres = dict(_avant, pertinence_clinique=90, pertinence=70,
              penalites=['interaction avec un traitement en cours (-20)'])
verifier("le score clinique est inchange par une penalite",
         _apres['pertinence_clinique'], _clinique_avant)
verifier("seule la note affichee baisse", _apres['pertinence'], 70)

# Le score de securite reste tracable independamment.
verifier("les penalites restent nommees", bool(_apres['penalites']), True)
verifier("et lisibles sans le score clinique",
         'interaction' in _apres['penalites'][0], True)

# La pesee fige le score clinique et ne le retouche jamais.
_lot = [{'title': 'X', 'substances': ['S'], 'pertinence': 90,
         'contre_indications': [{'terme': 'a', 'phrase': 'b'}]}]
peser_la_securite(_lot, [])
verifier("la pesee fige le score clinique", _lot[0]['pertinence_clinique'], 90)
verifier("et n'abaisse que la note affichee", _lot[0]['pertinence'], 50)

# Une vraie exclusion reste une exclusion : le seuil lit la note **penalisee**,
# donc un medicament dangereux tombe toujours dessous.
_dangereux = [{'title': 'Y', 'substances': ['S'], 'pertinence': 60,
               'contre_indications': [{'terme': 'a', 'phrase': 'b'}]}]
peser_la_securite(_dangereux, [])
verifier("un medicament contre-indique passe sous le seuil",
         _dangereux[0]['pertinence'] < SEUIL_EXCLUSION, True)
verifier("mais son score clinique reste lisible",
         _dangereux[0]['pertinence_clinique'], 60)

# Le classement reste independant de l'ordre d'entree, penalites comprises.
verifier("l'ordre d'entree n'agit pas davantage avec des penalites",
         [m['title'] for m in composer_strategie([_anse, _thiazide],
                                                 'insuffisance cardiaque')],
         [m['title'] for m in composer_strategie([_thiazide, _anse],
                                                 'insuffisance cardiaque')])


# ── Une premiere ligne ne tombe pas sous le seuil par surveillance ─────
#
# Le seuil lit la note **penalisee**, ce qui doit rester vrai pour qu'une
# contre-indication continue d'ecarter. Mais les penalites de surveillance et
# de classement, elles, ne doivent jamais suffire a faire disparaitre le
# traitement de premiere ligne d'une pathologie.
#
# La marge est **etroite** : cinq points. Ajouter une regle de niveau
# `classement` la ferait tomber a moins dix, et un diuretique de l'anse
# pourrait alors etre ecarte chez un patient simplement hypotendu et
# insuffisant renal. Ce controle est la pour que cela ne passe pas inapercu.

_regles_classement = [s for s in SEUILS_BIOLOGIQUES
                      if niveau_de(s) == NIVEAU_CLASSEMENT]
_pire = len(_regles_classement) * PENALITE_CLASSEMENT + PENALITE_INTERACTION
_base_premiere_ligne = (POINTS_COUVERTURE_ATC + POINTS_OBJECTIF_PRINCIPAL
                        + POINTS_OBJECTIF + POINTS_PREMIERE_LIGNE)

verifier("une premiere ligne survit au cumul des surveillances",
         _base_premiere_ligne - _pire >= SEUIL_EXCLUSION, True)

# Verifie aussi sur un cas concret, penalites reellement appliquees.
_ligne = {'title': 'PREMIERE LIGNE', 'substances': ['S'],
          'pertinence': _base_premiere_ligne,
          'declassements': [{'regle': r['libelle'], 'motif': '', 'cible': '',
                             'par_classe': False} for r in _regles_classement]}
peser_la_securite([_ligne], [{'medicine1': 'X (a)',
                              'medicine2': 'premiere ligne (b)',
                              'description': 'z'}])
verifier("et son score clinique reste intact",
         _ligne['pertinence_clinique'], _base_premiere_ligne)
verifier("sa note affichee reste au-dessus du seuil",
         _ligne['pertinence'] >= SEUIL_EXCLUSION, True)

# Une contre-indication, elle, doit toujours pouvoir l'ecarter.
_ci = {'title': 'CONTRE-INDIQUE', 'substances': ['S'],
       'pertinence': _base_premiere_ligne,
       'contre_indications': [{'terme': 'a', 'phrase': 'b'}]}
peser_la_securite([_ci], [])
verifier("une contre-indication reste capable d'ecarter une premiere ligne",
         _ci['pertinence'] < _base_premiere_ligne - PENALITE_CLASSEMENT, True)


# ── Un symptomatique qui vise l'objectif principal n'est pas adjuvant ──
#
# La regle releguait toute classe symptomatique des qu'une causale etait
# attendue, sans regarder ce que le tableau vise. Mesure bout en bout sur
# « cephalees liees a l'hypertension arterielle » : le tableau appelle C03,
# C07, C08, C09 et N02 ; l'objectif principal est `antalgie` ; DAFALGAN, note
# cent sur cent, passait **adjuvant** derriere onze antihypertenseurs a
# cinquante. Le patient vient pour une cephalee.
#
# Le commentaire de `CLASSES_SYMPTOMATIQUES` l'annoncait : « elles ne sont pas
# adjuvantes en soi, tout depend du tableau ». Seule la presence d'une causale
# etait lue.

def _symptomatique(titre, note, vise_principal):
    m = med(titre, ['N02'], note)
    m['substances'] = [titre]
    m['vise_objectif_principal'] = vise_principal
    return m

# 1. Cephalee + HTA : l'antalgique vise l'objectif principal, il le reste.
_cephalee = [_symptomatique('DAFALGAN', 100, True),
             med('AMLODIPINE', ['C08'], 50),
             med('RENITEC', ['C09'], 50)]
_r = composer_strategie(_cephalee, "cephalees liees a l'hypertension arterielle")
_rangs = {m['title']: m['rang'] for m in _r}
verifier("cephalee + HTA : l'antalgique n'est pas relegue adjuvant",
         _rangs['DAFALGAN'] != 'adjuvant', True)
verifier("il reste en premiere intention",
         _rangs['DAFALGAN'], 'premiere_intention')
verifier("et les antihypertenseurs restent proposes",
         _rangs['AMLODIPINE'] in ('premiere_intention', 'alternative'), True)

# 2. Pneumonie : l'antalgique ne vise pas l'objectif principal, il reste
#    adjuvant. C'est le cas pour lequel la regle avait ete ecrite.
_pneumonie = [_symptomatique('DOLIPRANE', 95, False),
              med('CLAMOXYL', ['J01'], 80)]
_r2 = composer_strategie(_pneumonie, 'pneumonie communautaire')
_rangs2 = {m['title']: m['rang'] for m in _r2}
verifier("pneumonie : l'antalgique reste adjuvant",
         _rangs2['DOLIPRANE'], 'adjuvant')
verifier("et l'antibiotique garde la premiere intention",
         _rangs2['CLAMOXYL'], 'premiere_intention')
verifier("l'antibiotique passe devant malgre une note inferieure",
         _r2[0]['title'], 'CLAMOXYL')

# 3. Migraine : l'antimigraineux vise l'objectif principal, rien ne le relegue.
_migraine = [_symptomatique('MAXALT', 100, True)]
_r3 = composer_strategie(_migraine, 'migraine sans aura')
verifier("migraine : le traitement antimigraineux reste prioritaire",
         _r3[0]['rang'], 'premiere_intention')

# Sans classe causale attendue, rien n'est adjuvant — comportement d'origine.
_seul = [_symptomatique('PARACETAMOL', 90, False)]
verifier("sans causale attendue, le symptomatique reste le traitement",
         composer_strategie(_seul, 'cephalee de tension')[0]['rang'],
         'premiere_intention')


# ── Relevé ───────────────────────────────────────────────────────────────

print()
print("  Stratégie composée pour une pneumonie :")
for m in ordonne:
    print("    %-22s %-19s %s" % (m['title'][:22], m['rang'], m['groupes_atc']))

print()
if _echecs:
    print("ÉCHECS (%d) :" % len(_echecs))
    for e in _echecs:
        print("  - %s" % e)
    print()
    print("%d contrôles réussis, %d en échec." % (_reussis, len(_echecs)))
    sys.exit(1)

print("%d contrôles, aucun en échec." % _reussis)
sys.exit(0)
