"""Banc : l'ATC découvre, l'indication décide.

Ce que ce banc garde
--------------------

**Une classe ATC suffisait à recommander un médicament.** Le bonus de classe
valait 60 pour un `SEUIL_EXCLUSION` de 40 : une correspondance de classe
suffisait donc, à elle seule et avec 50 % de marge.

Mesuré sur « céphalées légères, suspicion d'HTA récente » — qui appelle
`{C03, C07, C08, C09, N02}` :

    CELEBREX  (célécoxib)   60  « Pertinent pour: classe C08 »
    LASILIX   (furosémide) 100  « Pertinent pour: classe C03, diurétique »
    OXYNORM   (oxycodone)   60  « Pertinent pour: classe N02 »
    TIMACOR   (timolol)     60  « Pertinent pour: classe C07 »

Le moteur n'affirmait pas que le célécoxib traite l'hypertension : il disait
qu'il porte un code. La confusion était entre « cette classe a un rapport avec
le domaine » et « ce médicament convient à ce patient ».

La donnée qui tranche était déjà là — `DrugbankSubstance.indication`, portée
par 1 486 substances sur 1 633 — mais lue **après** la notation, comme simple
légende d'écran.

Emploi
------
    python scripts/verif_indication.py

Aucune base n'est nécessaire.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from prescription_helper import (
    classes_atc_attendues,
    CLASSES_PAR_OBJECTIF,  # noqa: E402
    DIAGNOSTIC_ATC_MAP,
    INDICATEURS_OBJECTIF,
    OBJECTIFS_THERAPEUTIQUES,
    _plier,
    PENALITE_PALIER,
    POINTS_COUVERTURE_ATC,
    POINTS_INDICATION_INCONNUE,
    POINTS_INDICATION_PRINCIPALE,
    POINTS_INDICATION_SECONDAIRE,
    SEUIL_EXCLUSION,
    compute_clinical_relevance,
    indication_repond_au_tableau,
    intensite_douleur,
    objectifs_de_l_indication,
    objectifs_du_tableau,
    objectifs_ordonnes_du_tableau,
    repond_en_premiere_ligne,
    rang_de_premiere_ligne,
    DECROISSANCE_LIGNE,
    POINTS_OBJECTIF,
    POINTS_OBJECTIF_PRINCIPAL,
    POINTS_OBJECTIF_SECONDAIRE,
    POINTS_PREMIERE_LIGNE,
    OBJECTIFS_COMPTES,
    objectif_principal_de_l_indication,
    palier_antalgique,
    palier_par_atc,
    palier_par_composition,
    tableau_clinique,
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


#: Le tableau signalé.
TABLEAU = tableau_clinique(
    'Cephalees legeres depuis quelques jours. Pas de fievre.',
    '**Diagnostic principal probable:**\n'
    'Cephalees liees a l hypertension arterielle recente - Confiance : 70%')

#: Indications réelles, figées depuis le graphe.
#:
#: **Elles étaient recopiées à la main dans ce fichier, et c'était faux.** Les
#: extraits saisis tenaient en une ligne là où DrugBank en écrit huit cents
#: caractères, et la troncature changeait le verdict : le furosémide, réduit à
#: « edema associated with congestive heart failure », était déclaré hors sujet
#: pour une hypertension — alors que son indication réelle dit, plus loin,
#: « and in the treatment of hypertension ». Le banc validait une fiction et
#: annonçait un tri que le moteur ne faisait pas.
#:
#: La fixture se refait avec `scripts/capturer_indications.py`. Comme les
#: captures de `verif_affichage`, elle permet au banc de tourner sans Neo4j
#: tout en éprouvant les textes que le moteur lit vraiment.
INDICATIONS = json.loads(
    (Path(__file__).resolve().parent / 'donnees'
     / 'indications_drugbank.json').read_text(encoding='utf-8'))
INDICATIONS['Paracetamol'] = INDICATIONS.get('Acetaminophen', '')

ATC = {'Celecoxib': 'C08', 'Furosemide': 'C03', 'Bumetanide': 'C03',
       'Amiloride': 'C03', 'Triamterene': 'C03', 'Timolol': 'C07',
       'Pindolol': 'C07', 'Verapamil': 'C08', 'Diltiazem': 'C08',
       'Oxycodone': 'N02', 'Nefopam': 'N02', 'Codeine': 'N02',
       'Paracetamol': 'N02', 'Ramipril': 'C09', 'Enalapril': 'C09',
       'Bendroflumethiazide': 'C03', 'Acetaminophen': 'N02',
       'Ibuprofen': 'M01'}


def noter(nom, tableau=TABLEAU, indication=None, atc=None):
    med = {'title': nom, 'substances': [nom],
           'groupes_atc': [atc or ATC.get(nom, 'C09')],
           'indication_source': (INDICATIONS.get(nom, '')
                                 if indication is None else indication)}
    note, justification = compute_clinical_relevance(tableau, med)
    return note, justification, med


# ── 1. Ce que le tableau vise, ce que l'indication soutient ──────────────

verifier("le tableau vise l'antalgie et l'antihypertension",
         objectifs_du_tableau(TABLEAU), {'antalgie', 'antihypertension'})

# Le tableau dit « Pas de fievre ». Un compte rendu dit autant ce qu'il écarte
# que ce qu'il constate, et « fièvre » cherché en sous-chaîne se trouvait dans
# « pas de fièvre » : le moteur visait l'antipyrexie chez un apyrétique.
verifier("un terme nié ne compte pas",
         'antipyrexie' in objectifs_du_tableau(TABLEAU), False)
verifier("mais le même terme affirmé compte",
         'antipyrexie' in objectifs_du_tableau('Cephalees et fievre a 39'),
         True)
verifier("la négation ne déborde pas sur la proposition suivante",
         'antalgie' in objectifs_du_tableau('Pas de fievre, cephalees'), True)

verifier("l'indication du ramipril soutient l'antihypertension",
         'antihypertension' in objectifs_de_l_indication(
             INDICATIONS['Ramipril']), True)
verifier("celle du célécoxib soutient l'anti-inflammation, pas l'HTA",
         objectifs_de_l_indication(INDICATIONS['Celecoxib']),
         {'antalgie', 'anti_inflammation'})

# Le bumétanide ne décongestionne que : c'est le seul diurétique du lot dont
# l'indication ne mentionne pas l'hypertension, et le seul que le tri retire.
verifier("celle du bumétanide ne soutient que la décongestion",
         objectifs_de_l_indication(INDICATIONS['Bumetanide']),
         {'decongestion'})

# Le furosémide, lui, **est** indiqué dans l'hypertension : son texte le dit
# après 400 caractères sur l'œdème. C'est ce que la version tronquée écrite à
# la main faisait manquer, et ce qui rendait le banc menteur.
verifier("celle du furosémide mentionne aussi l'hypertension",
         'antihypertension' in objectifs_de_l_indication(
             INDICATIONS['Furosemide']), True)

verifier("un tableau vide ne vise rien", objectifs_du_tableau(''), set())
verifier("None ne casse pas", objectifs_du_tableau(None), set())
verifier("une indication vide ne soutient rien",
         objectifs_de_l_indication(''), set())
verifier("None non plus", objectifs_de_l_indication(None), set())


# ── 2. Les trois verdicts, et pourquoi « inconnu » n'est pas « non » ─────

verifier("le ramipril répond au tableau",
         indication_repond_au_tableau(INDICATIONS['Ramipril'], TABLEAU)[0],
         'oui')
# Le célécoxib répond au tableau — mais par l'antalgie, pas par
# l'antihypertension. C'est un anti-inflammatoire, et une céphalée est une
# douleur : le proposer n'est plus absurde, et surtout ce n'est plus « classe
# C08 » qui le justifie.
verdict_cele, communs_cele = indication_repond_au_tableau(
    INDICATIONS['Celecoxib'], TABLEAU)
verifier("le célécoxib répond par l'antalgie", communs_cele, {'antalgie'})
verifier("et non par l'antihypertension",
         'antihypertension' in communs_cele, False)

verifier("le bumétanide ne répond pas au tableau",
         indication_repond_au_tableau(INDICATIONS['Bumetanide'], TABLEAU)[0],
         'non')

# Une indication absente — 147 substances du graphe n'en portent pas — ou un
# graphe injoignable ne prouvent rien. Punir dans ce cas viderait l'écran à la
# première panne de Neo4j.
verifier("une indication absente ne prouve rien",
         indication_repond_au_tableau('', TABLEAU)[0], 'inconnu')
verifier("une indication illisible non plus",
         indication_repond_au_tableau('Lorem ipsum dolor sit', TABLEAU)[0],
         'inconnu')
verifier("un tableau sans objectif connu ne juge rien",
         indication_repond_au_tableau(INDICATIONS['Celecoxib'],
                                      'Motif de consultation non precise')[0],
         'inconnu')


# ── 3. Le cas signalé, molécule par molécule ─────────────────────────────
#
# Ce que le médecin a vu remonter pour une céphalée légère.

# Ce que le tri retire réellement, sur les textes réels : le bumétanide, dont
# l'indication ne parle que d'œdème.
#
# **Il en retire beaucoup moins que prévu, et c'est un résultat, pas un
# échec.** Furosémide, triamtérène, bendrofluméthiazide et timolol oral sont
# tous, selon DrugBank, indiqués dans l'hypertension — le bendrofluméthiazide
# ouvre même son texte par « for the treatment of high blood pressure ». Leur
# présence n'est donc pas une erreur d'indication ; le doute qu'ils inspirent
# porte sur l'opportunité (pas d'œdème, choix de première intention), que le
# texte d'indication ne tranche pas.
for nom in ('Bumetanide',):
    note, justification, _ = noter(nom)
    verifier("%s ne remonte plus" % nom, note < SEUIL_EXCLUSION, True)
    verifier("%s : le motif nomme l'indication" % nom,
             'indication' in justification.lower(), True)

# Ceux-là restent, et leur indication le justifie. Le banc le fige pour qu'on
# ne croie pas le contraire.
for nom in ('Furosemide', 'Triamterene', 'Bendroflumethiazide'):
    verifier("%s reste : son indication mentionne l'HTA" % nom,
             'antihypertension' in objectifs_de_l_indication(
                 INDICATIONS[nom]), True)

# Ce qui doit rester découvrable : les médicaments dont l'hypertension est la
# **vocation première**, celle que leur indication nomme en tête.
for nom in ('Ramipril', 'Enalapril', 'Bendroflumethiazide'):
    note, _, _ = noter(nom)
    verifier("%s reste proposable" % nom, note >= SEUIL_EXCLUSION, True)

# Le vérapamil, lui, ne l'est plus : son indication ouvre sur l'angor, et
# l'hypertension n'y est qu'un emploi second. Le TEST A demande précisément
# qu'il ne remonte pas automatiquement pour une céphalée avec HTA récente.
note_vera, _, _ = noter('Verapamil')
verifier("le vérapamil ne remonte pas automatiquement",
         note_vera < SEUIL_EXCLUSION, True)
verifier("parce que son indication ouvre sur l'angor",
         objectif_principal_de_l_indication(INDICATIONS['Verapamil']),
         'antiangineux')

# Le paracétamol reste pertinent comme traitement symptomatique.
note_para, justif_para, _ = noter('Paracetamol')
verifier("le paracétamol reste pertinent", note_para >= SEUIL_EXCLUSION, True)


# ── 4. L'intensité de la douleur ─────────────────────────────────────────

verifier("« légères » se lit comme une douleur de niveau 1",
         intensite_douleur(TABLEAU), 1)
verifier("« severe » se lit comme un niveau 3",
         intensite_douleur('Douleur severe et rebelle'), 3)
verifier("une intensité non dite ne se devine pas",
         intensite_douleur('Cephalees depuis trois jours'), 0)

verifier("l'oxycodone est un palier 3", palier_antalgique(
    {'title': 'OXYNORM', 'substances': ['Oxycodone']}), 3)
verifier("la codéine un palier 2", palier_antalgique(
    {'title': 'CODOLIPRANE', 'substances': ['Codeine']}), 2)
verifier("le paracétamol un palier 1", palier_antalgique(
    {'title': 'DOLIPRANE', 'substances': ['Paracetamol']}), 1)
verifier("un antihypertenseur n'est pas un antalgique", palier_antalgique(
    {'title': 'TRIATEC', 'substances': ['Ramipril']}), 0)


# ── 4 bis. Les associations que la substance déclarée cache ──────────────
#
# LAMALINE et PRONTALGINE étaient proposés à 100 pour une céphalée légère. Le
# catalogue ne leur déclare que « Paracétamol » : le palier ne pouvait pas voir
# l'opium de l'un ni la codéine de l'autre.
#
# Le code ATC de la **substance** DrugBank ne pouvait pas trancher non plus :
# LAMALINE, PRONTALGINE et DOLIPRANE pointent tous vers `Acetaminophen`, qui
# porte les codes de toutes les associations contenant du paracétamol —
# `N02AJ01` (paracétamol + codéine) compris. S'en servir aurait classé le
# DOLIPRANE en palier 2 et l'aurait fait disparaître.
#
# Deux sources justes s'y substituent : le `code_atc` de la **spécialité**, que
# porte le catalogue français, et la rubrique 2 du RCP.

verifier("un opioïde fort se lit sur le code de la spécialité",
         palier_par_atc('N02AA05'), 3)
verifier("le tramadol aussi", palier_par_atc('N02AX02'), 2)
verifier("la codéine antitussive aussi", palier_par_atc('R05DA04'), 2)
verifier("le paracétamol en association reste palier 1",
         palier_par_atc('N02BE51'), 1)
verifier("un antihypertenseur n'a pas de palier", palier_par_atc('C09AA05'), 0)
verifier("un code absent ne dit rien", palier_par_atc(''), 0)
verifier("None ne casse pas", palier_par_atc(None), 0)

verifier("l'opium se lit dans la composition",
         palier_par_composition("Paracétamol 300 mg, poudre d'opium 25 mg"), 3)
verifier("la codéine aussi",
         palier_par_composition('Paracétamol 400 mg, phosphate de codéine 20 mg'),
         2)
verifier("une composition sans opioïde ne dit rien",
         palier_par_composition('Paracétamol 1000 mg'), 0)
verifier("une composition vide non plus", palier_par_composition(''), 0)

# Le plus élevé des trois sources l'emporte, et **DOLIPRANE ne doit pas
# bouger** : c'est le faux positif qui coûterait le plus cher.
verifier("LAMALINE est reconnu palier 3 par sa composition",
         palier_antalgique({'title': 'LAMALINE', 'substances': ['Paracétamol'],
                            'code_atc': 'N02BE51',
                            'composition': "Paracétamol, poudre d'opium, caféine"}),
         3)
verifier("PRONTALGINE palier 2 par la sienne",
         palier_antalgique({'title': 'PRONTALGINE', 'substances': ['Paracétamol'],
                            'code_atc': 'N02BE51',
                            'composition': 'Paracétamol, phosphate de codéine'}),
         2)
verifier("DOLIPRANE reste palier 1",
         palier_antalgique({'title': 'DOLIPRANE', 'substances': ['Paracétamol'],
                            'code_atc': 'N02BE01',
                            'composition': 'Paracétamol 1000 mg'}), 1)
verifier("sans code ni composition, la table par substance suffit",
         palier_antalgique({'title': 'EFFERALGAN',
                            'substances': ['Paracétamol']}), 1)

# La pénalité doit survivre au plafonnement. Soustraite au fil de
# l'accumulation, elle disparaissait : un paracétamol cumule 50 par le
# symptôme, 60 par la classe et 55 par la marque ; 165 − 25 = 140, plafonné à
# 100. LAMALINE s'affichait à 100 sur 100 pour une céphalée légère, la
# pénalité posée et invisible.
note_lamaline, _, med_lamaline = noter(
    'LAMALINE', indication=INDICATIONS['Acetaminophen'], atc='N02')
med_lamaline.update(code_atc='N02BE51',
                    composition="Paracétamol, poudre d'opium, caféine")
note_lamaline, _ = compute_clinical_relevance(TABLEAU, med_lamaline)
verifier("un opioïde caché est bien déclassé malgré un score plafonné",
         note_lamaline <= 100 - PENALITE_PALIER, True)
verifier("et l'exigence est relevée",
         bool(med_lamaline.get('palier_excessif')), True)

# Le paracétamol seul ne doit pas bouger : c'est le faux positif qui coûterait
# le plus cher.
med_dolip = {'title': 'DOLIPRANE', 'substances': ['Paracétamol'],
             'groupes_atc': ['N02'], 'code_atc': 'N02BE01',
             'composition': 'Paracétamol 1000 mg',
             'indication_source': INDICATIONS['Acetaminophen']}
note_dolip, _ = compute_clinical_relevance(TABLEAU, med_dolip)
verifier("le paracétamol seul garde sa note", note_dolip, 100)
verifier("et n'est pas déclassé", med_dolip.get('palier_excessif'), None)

# Le palier vient de la substance, jamais de son indication. Un second signal
# lu dans le texte — « moderate to severe pain » → palier 2 — a été écrit puis
# retiré : mesuré sur les textes réels, il déclassait le paracétamol, dont
# l'indication fait 700 caractères et contient cette tournure à propos d'autre
# chose. Le banc garde la trace de l'essai pour qu'il ne soit pas refait.
verifier("le néfopam est au palier 2, faute d'indication dans le graphe",
         INDICATIONS['Nefopam'], '')
verifier("et la table le situe malgré tout", palier_antalgique(
    {'title': 'ACUPAN', 'substances': ['Nefopam']}), 2)

# La pénalité croît avec l'écart de palier, et les deux cas ne se valent pas.
# Un opioïde fort sur une douleur légère — deux crans — doit tomber sous le
# seuil ; la codéine, un cran, doit seulement passer derrière le paracétamol.
for nom in ('Oxycodone', 'Nefopam'):
    note, _, med = noter(nom)
    verifier("%s ne remonte pas pour une douleur légère" % nom,
             note < SEUIL_EXCLUSION, True)
    verifier("%s : l'exigence est relevée" % nom,
             bool(med.get('palier_excessif')), True)

note_codeine, _, med_codeine = noter('Codeine')
verifier("la codéine est déclassée", bool(med_codeine.get('palier_excessif')),
         True)
verifier("et passe derrière le paracétamol",
         note_codeine < noter('Paracetamol')[0], True)

# Sur une douleur sévère, l'opioïde redevient proposable : la règle gradue,
# elle n'interdit pas.
#
# Le tableau retenu est une **lombalgie sévère** et non une « douleur
# post-traumatique » : `douleur` vise bien un objectif mais n'appelle aucune
# classe ATC (voir le contrôle de cohérence, section 6), donc rien ne serait
# découvert et la note resterait nulle pour une raison étrangère au palier.
SEVERE = tableau_clinique(
    'Lombalgie severe et insupportable depuis trois jours.',
    '**Diagnostic principal probable:**\nLombalgie commune severe')
note_severe, _, med_severe = noter('Oxycodone', tableau=SEVERE)
verifier("sur une douleur sévère, l'oxycodone n'est plus déclassée",
         bool(med_severe.get('palier_excessif')), False)
verifier("et sa note remonte", note_severe > noter('Oxycodone')[0], True)


# ── 5. La dégradation ne vide pas l'écran ────────────────────────────────
#
# Sans indication — graphe injoignable, ou substance qui n'en porte pas — le
# comportement d'avant est conservé. Le doute laisse passer.

note_sans, _, _ = noter('Inconnue', indication='', atc='C09')
verifier("sans indication, la classe compte encore",
         note_sans, POINTS_COUVERTURE_ATC + POINTS_INDICATION_INCONNUE)
verifier("et le candidat reste proposable",
         note_sans >= SEUIL_EXCLUSION, True)


# ── 6. Les tables se tiennent ────────────────────────────────────────────

# Un objectif visé par un diagnostic doit pouvoir être reconnu dans une
# indication : sans marqueur, la règle serait muette au lieu d'être fausse.
vises = {o for objectifs in OBJECTIFS_THERAPEUTIQUES.values()
         for o in objectifs}
verifier("tout objectif visé sait se reconnaître",
         sorted(vises - set(INDICATEURS_OBJECTIF)), [])

verifier("chaque diagnostic vise au moins un objectif",
         [d for d, o in OBJECTIFS_THERAPEUTIQUES.items() if not o], [])
verifier("chaque objectif porte au moins un marqueur",
         [o for o, m in INDICATEURS_OBJECTIF.items() if not m], [])

# Les marqueurs sont en anglais : c'est la langue de la source.
verifier("les marqueurs sont écrits sans accent",
         [m for marqueurs in INDICATEURS_OBJECTIF.values() for m in marqueurs
          if any(ord(c) > 127 for c in m)], [])

verifier("la pénalité de palier est réelle", PENALITE_PALIER > 0, True)

# Cohérence entre les deux tables de diagnostics. Elles ont été écrites
# séparément et divergent : 19 entrées visent un objectif sans appeler de
# classe ATC, 25 l'inverse.
#
# Ce n'est pas un défaut du tri par indication — sans découverte ATC, aucun
# point n'est accordé, donc rien n'est à démentir — mais c'est une couverture
# incomplète, et elle doit être **mesurée** plutôt que tue. Le contrôle fige
# l'écart constaté : le faire bouger demande de l'avoir voulu.
_obj = {_plier(k) for k in OBJECTIFS_THERAPEUTIQUES}
_atc = {_plier(k) for k in DIAGNOSTIC_ATC_MAP}
verifier("l'écart entre les deux tables ne s'aggrave pas",
         len(_obj - _atc) <= 19 and len(_atc - _obj) <= 25, True)

# Les diagnostics du cas signalé, eux, doivent figurer des deux côtés :
# c'est ce qui permet la découverte **et** le démenti.
for terme in ('hypertension', 'cephalee', 'lombalgie'):
    verifier("« %s » vise un objectif" % terme,
             bool(objectifs_du_tableau(terme)), True)


# ── 6 bis. TEST B — l'insuffisance cardiaque aiguë décompensée ──────────
#
# Le cas inverse, et celui qui a montré que la seule valeur `POINTS_CLASSE_ATC`
# ne suffisait pas. La conduite a tenir prescrivait « diuretiques IV
# (furosemide) » et l'ecran ne proposait plus rien :
#
#     BURINEX   60 − 20 (interaction) − 15 (pression basse) = 25  ecarte
#     LOGIRENE  60 − 15                                     = 45  seul retenu
#
# Tout candidat juste plafonnait a 60, et deux penalites ordinaires suffisaient
# a le faire passer sous 40. Le moteur ne savait pas dire « ceci EST le
# traitement de cette pathologie ».

DECOMPENSATION = tableau_clinique(
    'Dyspnee progressive. Oedemes bilateraux. Prise de poids. Oligurie. '
    'Congestion systemique.',
    '**Diagnostic principal probable:**' + chr(10)
    + 'Insuffisance cardiaque aigue decompensee - Confiance : 85%')

verifier("la décompensation vise la décongestion",
         'decongestion' in objectifs_du_tableau(DECOMPENSATION), True)

# Le meme medicament, deux contextes, deux resultats : c'est tout l'objet de
# la separation entre couverture et pertinence.
note_furo_b = noter('Furosemide', tableau=DECOMPENSATION)[0]
note_furo_a = noter('Furosemide')[0]
verifier("le furosémide est pertinent dans la décompensation",
         note_furo_b >= SEUIL_EXCLUSION, True)
verifier("et ne l'est pas dans une hypertension simple",
         note_furo_a < SEUIL_EXCLUSION, True)
verifier("l'écart entre les deux contextes est net",
         note_furo_b - note_furo_a >= 40, True)

verifier("le bumétanide aussi est pertinent",
         noter('Bumetanide', tableau=DECOMPENSATION)[0] >= SEUIL_EXCLUSION,
         True)

# Ce qui ne traite pas la congestion ne doit pas remonter, meme en C08/N02.
for nom in ('Celecoxib', 'Diltiazem', 'Oxycodone'):
    verifier("%s ne remonte pas pour une décompensation" % nom,
             noter(nom, tableau=DECOMPENSATION)[0] < SEUIL_EXCLUSION, True)

# C'est la place du marqueur dans le texte qui separe les deux familles :
# aucun nom de molecule n'est ecrit, une substance jamais rencontree est
# situee par le meme calcul.
for nom in ('Furosemide', 'Bumetanide', 'Triamterene', 'Amiloride'):
    verifier("%s a la décongestion pour vocation" % nom,
             objectif_principal_de_l_indication(INDICATIONS[nom]),
             'decongestion')
for nom in ('Ramipril', 'Enalapril', 'Bendroflumethiazide'):
    verifier("%s a l'hypertension pour vocation" % nom,
             objectif_principal_de_l_indication(INDICATIONS[nom]),
             'antihypertension')


# ── 6 ter. La resolution du score ───────────────────────────────────────
#
# Le score n'avait pas assez de resolution : couverture 20 + indication
# principale 40 + objectifs 30 donnait **90 a tout le monde**. Mesure sur une
# decompensation cardiaque, triamterene, amiloride et enalapril arrivaient a
# 90 comme le furosemide, et le departage retombait sur le nom.
#
# Deux informations existaient deja sans etre exploitees : la vocation du
# medicament — l'objectif nomme en tete de son indication — et, du cote du
# tableau, lequel de ses objectifs est le principal. Les objectifs
# cardiovasculaires et antalgiques d'OBJECTIFS_THERAPEUTIQUES sont desormais
# des sequences ordonnees, et le premier terme reconnu dans le tableau designe
# le principal.

DECOMP = tableau_clinique(
    'Dyspnee. Oedemes bilateraux. Prise de poids. Oligurie. Congestion systemique.',
    '**Diagnostic principal probable:**' + chr(10) + 'Decompensation cardiaque aigue')
CEPHALEE = tableau_clinique(
    'Cephalees legeres. Pas de fievre. Pas d oedeme.',
    '**Diagnostic principal probable:**' + chr(10)
    + 'Cephalees liees a l hypertension arterielle recente')

# 2. objectif principal vs secondaire — le tableau doit savoir lequel prime.
verifier("une decompensation vise d'abord la decongestion",
         objectifs_ordonnes_du_tableau(DECOMP)[0], 'decongestion')

# Le diagnostic nomme son motif en premier : une cephalee liee a une HTA vise
# l'antalgie, pas le controle tensionnel. Trier par longueur de terme donnait
# l'inverse, « hypertension » etant plus long que « cephalees ».
verifier("une cephalee vise d'abord l'antalgie",
         objectifs_ordonnes_du_tableau(CEPHALEE)[0], 'antalgie')
verifier("mais l'HTA reste un objectif du tableau",
         'antihypertension' in objectifs_ordonnes_du_tableau(CEPHALEE)[1], True)

# Un tableau sans entree ordonnee n'a pas de principal : ne pas savoir lequel
# prime n'est pas savoir qu'ils se valent.
verifier("sans entree ordonnee, aucun principal",
         objectifs_ordonnes_du_tableau('Mycose cutanee')[0], '')
verifier("un tableau vide non plus", objectifs_ordonnes_du_tableau('')[0], '')
verifier("None ne casse pas", objectifs_ordonnes_du_tableau(None)[0], '')

def _note(nom, tableau, atc=None):
    return noter(nom, tableau=tableau, atc=atc or ATC.get(nom))[0]

# 1 et 3. La correspondance est graduee : traiter l'objectif principal vaut
# plus que traiter un objectif secondaire.
_furo = _note('Furosemide', DECOMP)
_enal = _note('Enalapril', DECOMP)
verifier("traiter l'objectif principal vaut plus qu'un objectif secondaire",
         _furo > _enal, True)
verifier("mais l'objectif secondaire reste proposable",
         _enal >= SEUIL_EXCLUSION, True)

# 5. Decompensation : le diuretique de l'anse passe devant l'epargneur, que
# DrugBank decrit pourtant dans les memes termes.
_bume = _note('Bumetanide', DECOMP)
_tria = _note('Triamterene', DECOMP)
_amil = _note('Amiloride', DECOMP)
verifier("le diuretique de l'anse prime sur l'epargneur de potassium",
         min(_furo, _bume) > max(_tria, _amil), True)
verifier("et l'epargneur reste au-dessus de l'antihypertenseur seul",
         min(_tria, _amil) > _enal, True)

# 6. Le celecoxib ne devient pas pertinent par un code ATC.
verifier("le celecoxib ne remonte pas pour une decompensation",
         _note('Celecoxib', DECOMP) < SEUIL_EXCLUSION, True)

# 4. Cephalee legere : paracetamol > codeine > oxycodone.
_para = _note('Acetaminophen', CEPHALEE)
_cod = _note('Codeine', CEPHALEE)
_oxy = _note('Oxycodone', CEPHALEE)
verifier("le paracetamol prime sur la codeine", _para > _cod, True)
verifier("et la codeine sur l'oxycodone", _cod > _oxy, True)
verifier("le paracetamol reste proposable", _para >= SEUIL_EXCLUSION, True)
verifier("l'oxycodone est ecartee", _oxy < SEUIL_EXCLUSION, True)

# Le meme medicament, deux contextes, deux notes : c'est tout l'objet de la
# resolution.
verifier("le furosemide vaut plus dans la congestion que dans la cephalee",
         _furo - _note('Furosemide', CEPHALEE) >= 40, True)

# 7. Deux medicaments reellement equivalents restent a egalite : la resolution
# ne doit pas inventer une difference la ou il n'y en a pas.
verifier("deux epargneurs equivalents restent a egalite", _tria, _amil)

# La premiere ligne ne s'applique qu'a l'objectif principal.
verifier("un diuretique de l'anse est de premiere ligne pour la decongestion",
         repond_en_premiere_ligne(
             {'title': 'LASILIX', 'substances': ['Furosemide']}, 'decongestion'),
         True)
# L'epargneur figure dans la conduite, mais **en dernier**. L'ordre du tuple
# est l'affirmation clinique, et le score doit le lire : il ne le lisait pas,
# la fonction rendant un booleen, et ESIDREX sortait a 100 devant BURINEX et
# le furosemide a 80 pour une decompensation aigue.
verifier("l'epargneur figure dans la conduite, mais en dernier",
         rang_de_premiere_ligne(
             {'title': 'MODAMIDE', 'substances': ['Amiloride']}, 'decongestion'),
         2)
verifier("l'anse vient en premier",
         rang_de_premiere_ligne(
             {'title': 'LASILIX', 'substances': ['Furosemide']}, 'decongestion'),
         0)
verifier("le thiazidique entre les deux",
         rang_de_premiere_ligne(
             {'title': 'ESIDREX', 'substances': ['Hydrochlorothiazide']},
             'decongestion'), 1)
verifier("une classe hors conduite n'a pas de rang",
         rang_de_premiere_ligne(
             {'title': 'RENITEC', 'substances': ['Enalapril']}, 'decongestion'),
         -1)

# Le rang doit peser plus que la largeur, sinon un thiazidique couvrant deux
# objectifs rattrape un diuretique de l'anse n'en couvrant qu'un.
verifier("un cran de rang coute plus que la prime de largeur",
         DECROISSANCE_LIGNE > POINTS_OBJECTIF * OBJECTIFS_COMPTES, True)
verifier("un objectif sans table ne rapporte rien",
         repond_en_premiere_ligne(
             {'title': 'LASILIX', 'substances': ['Furosemide']}, 'antalgie'),
         False)
verifier("une substance inconnue non plus",
         repond_en_premiere_ligne(
             {'title': 'X', 'substances': ['Inconnue']}, 'decongestion'), False)

# La premiere ligne doit peser plus que la prime de largeur, sinon un
# medicament couvrant deux objectifs secondaires passe devant celui qui traite
# le principal.
verifier("la premiere ligne pese plus que la largeur",
         POINTS_PREMIERE_LIGNE > POINTS_OBJECTIF * OBJECTIFS_COMPTES, True)
verifier("l'objectif principal pese plus que le secondaire",
         POINTS_OBJECTIF_PRINCIPAL > POINTS_OBJECTIF_SECONDAIRE, True)


# ── Repli par objectif : deux tables qui ne se parlaient pas ────────────
#
# `DIAGNOSTIC_ATC_MAP` alimente le recrutement, `OBJECTIFS_THERAPEUTIQUES` la
# notation. Un tableau reconnu par la seconde et ignore par la premiere ne
# recrutait rien.
#
# Mesure bout en bout sur « Fracture du col femoral compliquee », douleur
# decrite comme severe et resistante au paracetamol :
#
#     objectif principal : antalgie
#     classes ATC        : []
#     propose            : EFFERALGANSTIX FRAISE 250 mg, et rien d'autre
#
# Aucun antalgique de palier 2 ou 3 pour une douleur severe.

_severe = 'Fracture du col femoral compliquee. Douleur severe et insupportable.'
verifier("une douleur severe sans entree diagnostic recrute N02",
         classes_atc_attendues(_severe), {'N02'})
verifier("et son objectif principal reste l'antalgie",
         objectifs_ordonnes_du_tableau(_severe)[0], 'antalgie')

# Le repli ouvre le vivier, il ne choisit pas : la gradation d'intensite fait
# le tri, et un opioide reste declasse sur une douleur legere.
_legere = 'Cephalees legeres de tension.'
verifier("une douleur legere recrute aussi N02",
         classes_atc_attendues(_legere), {'N02'})
verifier("mais l'intensite les separe",
         (intensite_douleur(_severe), intensite_douleur(_legere)), (3, 1))

def _antalgique(nom, tableau):
    return noter(nom, tableau=tableau, atc='N02')[0]

verifier("sur douleur severe, l'opioide n'est plus declasse",
         _antalgique('Oxycodone', _severe) > _antalgique('Oxycodone', _legere),
         True)
verifier("sur douleur legere, le paracetamol reste devant l'opioide",
         _antalgique('Acetaminophen', _legere) > _antalgique('Oxycodone', _legere),
         True)

# Un diagnostic que la table reconnait garde exactement son comportement.
verifier("la migraine est inchangee",
         classes_atc_attendues('Migraine sans aura'), {'N02'})
verifier("la pneumonie garde J01 et N02",
         classes_atc_attendues('Pneumonie aigue communautaire. Fievre.'),
         {'J01', 'N02'})

# **Le garde-fou** : un tableau non douloureux ne peut pas recruter N02 par ce
# repli, puisqu'il est indexe par objectif et non par defaut.
for tableau in ('Diabete de type 2 desequilibre', 'Mycose cutanee',
                'Hypertension arterielle essentielle', 'Conjonctivite'):
    verifier("« %s » ne recrute pas N02 par le repli" % tableau[:28],
             'N02' in classes_atc_attendues(tableau), False)

# Le repli ne s'applique qu'a des objectifs dont la classe ne fait pas de
# doute : la table reste courte, et chaque entree est verifiable.
verifier("le repli ne couvre que des objectifs connus",
         sorted(CLASSES_PAR_OBJECTIF), ['antalgie', 'antimigraineux'])
verifier("et ne rend que des groupes de niveau 2",
         [g for gs in CLASSES_PAR_OBJECTIF.values() for g in gs
          if len(g) != 3], [])


# ── 7. Le branchement ────────────────────────────────────────────────────

source = (Path(__file__).resolve().parent.parent
          / 'prescription_helper.py').read_text(encoding='utf-8')
code = '\n'.join(l for l in source.split('\n')
                 if not l.lstrip().startswith('#'))

# L'indication doit être lue **avant** la notation, sans quoi elle ne peut
# pas peser. Elle l'était après, comme simple légende.
tuyau = code[code.index('def appliquer_controles'):]
tuyau = tuyau[:tuyau.index('\ndef ', 10)]
verifier("l'indication est relevée avant la notation",
         tuyau.index('attacher_indications(')
         < tuyau.index('compute_clinical_relevance('), True)

# Les deux sites de notation doivent l'appeler. Le premier branchement ne
# l'avait posée que dans `appliquer_controles` : sur l'assistant, la note est
# figée plus tôt, dans `analyze_patient`, et la boucle d'`appliquer_controles`
# saute tout médicament déjà noté. Mesuré bout en bout : 27 propositions,
# célécoxib toujours à 60, zéro écarté pour indication.
patient = code[code.index('def analyze_patient'):]
patient = patient[:patient.index(chr(10) + 'def ', 10)]
verifier("l'assistant relève l'indication avant sa propre notation",
         'attacher_indications(' in patient
         and patient.index('attacher_indications(')
         < patient.index('compute_clinical_relevance('), True)

notation = code[code.index('def compute_clinical_relevance'):]
notation = notation[:notation.index('\ndef ', 10)]
verifier("la notation consulte l'indication",
         'force_de_l_indication(' in notation, True)
verifier("les points de pertinence y sont conditionnés",
         notation.index('force_de_l_indication(')
         < notation.index('POINTS_INDICATION_PRINCIPALE'), True)

# La couverture ne doit jamais valoir autant que la pertinence : c'est toute
# la separation demandee. L'ATC garantit qu'on ne rate pas un candidat ; il ne
# prouve pas qu'il convient.
verifier("la couverture ATC pese moins que l'indication principale",
         POINTS_COUVERTURE_ATC < POINTS_INDICATION_PRINCIPALE, True)
verifier("et ne suffit pas a franchir le seuil seule",
         POINTS_COUVERTURE_ATC < SEUIL_EXCLUSION, True)
verifier("un emploi secondaire ne le franchit pas non plus",
         POINTS_COUVERTURE_ATC + POINTS_INDICATION_SECONDAIRE < SEUIL_EXCLUSION,
         True)
verifier("mais une indication inconnue reste au-dessus",
         POINTS_COUVERTURE_ATC + POINTS_INDICATION_INCONNUE >= SEUIL_EXCLUSION,
         True)
verifier("l'indication contraire prime sur toute créance de classe",
         'indication_hors_sujet' in notation, True)


# ── Relevé ───────────────────────────────────────────────────────────────

print()
print("  Tableau : céphalées légères + suspicion d'HTA récente")
print("  Objectifs visés : %s" % sorted(objectifs_du_tableau(TABLEAU)))
print()
print("  %-14s %-5s %-6s %-8s %s" % ('SUBSTANCE', 'ATC', 'NOTE', 'VERDICT',
                                     'OBJECTIFS DE SON INDICATION'))
for nom in INDICATIONS:
    note, _, _ = noter(nom)
    print("  %-14s %-5s %-6s %-8s %s"
          % (nom, ATC[nom], note,
             'RETENU' if note >= SEUIL_EXCLUSION else 'ecarte',
             sorted(objectifs_de_l_indication(INDICATIONS[nom])) or '—'))

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
