# -*- coding: utf-8 -*-
"""Traduction des énoncés d'interaction DrugBank, de l'anglais vers le français.

## Pourquoi pas une traduction automatique

L'audit UX (§1.10) proposait « une traduction en lot, hors ligne, 15 731
énoncés distincts ». Deux choses clochaient dans cette formulation.

Le compte, d'abord : les 269 271 relations portent 269 271 descriptions
**toutes distinctes**. Mais elles ne sont pas rédigées une par une — DrugBank
les engendre à partir de phrases types où seuls changent les noms de
substance. En retirant ces noms (`scripts/extraire_patrons_interactions.py`),
il reste **537 patrons**, que 27 trames et deux glossaires recouvrent.

Le procédé, ensuite. Un nom de substance est un nom propre, et se tromper sur
le nom d'une molécule dans un outil de prescription est la faute qu'on ne peut
pas se permettre. Une traduction automatique de la phrase entière toucherait
aux noms ; ici ils ne sont jamais traduits, seulement replacés tels quels dans
une phrase française écrite d'avance.

Le tout est relisible : 27 phrases types et 125 termes médicaux, contre
269 271 énoncés. C'est ce qu'un pharmacien peut vérifier — et il couvre
**99,86 %** des énoncés du catalogue.

## Ce que le module ne fait pas

Il ne traduit pas ce qu'il ne reconnaît pas. Quand une trame manque, ou qu'un
terme est absent du glossaire, `traduire()` rend `None` et l'appelant garde
l'anglais avec la mention qui l'accompagne. Une phrase à moitié française
serait pire que l'anglais : elle laisserait croire à une traduction complète.

Couverture mesurée sur les 269 271 énoncés : voir `couverture()`, et le
rapport `rapport/RAPPORT_2-2_TRADUCTION_INTERACTIONS.md`.
"""
import re

def _trame(motif, francais):
    return (re.compile('^' + motif + '$'), francais)


#: Voyelles et h muet devant lesquels « de » s'élide. Le h aspiré existe
#: (« de haricot ») mais aucune substance n'en porte : la nomenclature chimique
#: n'a que des h muets — hydroxyde, héparine, halopéridol.
_VOYELLES = 'aeiouyàâäéèêëîïôöûüh'


def _elider(mot):
    """« de » ou « d' » selon l'initiale — « d'Amiodarone », « de Warfarine ».

    Les noms de substance sont substitués dans des phrases écrites d'avance ;
    sans cela toutes celles commençant par une voyelle donnaient « de
    Amiodarone ». L'élision se calcule au moment de la substitution plutôt que
    sur la phrase finie : appliquée après coup, elle toucherait aussi les
    « de » internes à un nom composé.
    """
    if mot and mot[0].lower() in _VOYELLES:
        return "d'" + mot
    return 'de ' + mot


#: Trames, de la plus fréquente à la moins fréquente. L'ordre compte : les
#: expressions sont essayées dans l'ordre et la première qui accroche gagne.
#: Les trames à emplacement de vocabulaire (`effet`, `activite`) viennent en
#: dernier, leur `.+?` étant le plus permissif.
TRAMES = [
    _trame(r'(?P<x>.+?) may decrease the excretion rate of (?P<y>.+?) '
           r'which could result in a higher serum level\.',
           "{x} peut diminuer la vitesse d'élimination {de_y}, "
           "ce qui peut en élever la concentration sérique."),

    _trame(r'(?P<x>.+?) may increase the excretion rate of (?P<y>.+?) '
           r'which could result in a lower serum level and potentially '
           r'a reduction in efficacy\.',
           "{x} peut augmenter la vitesse d'élimination {de_y}, "
           "ce qui peut en abaisser la concentration sérique et réduire son efficacité."),

    _trame(r'The metabolism of (?P<x>.+?) can be decreased when combined with (?P<y>.+?)\.',
           "Le métabolisme {de_x} peut être diminué en association avec {y}."),

    _trame(r'The metabolism of (?P<x>.+?) can be increased when combined with (?P<y>.+?)\.',
           "Le métabolisme {de_x} peut être augmenté en association avec {y}."),

    _trame(r'The serum concentration of (?P<x>.+?) can be increased when it is '
           r'combined with (?P<y>.+?)\.',
           "La concentration sérique {de_x} peut être augmentée en association avec {y}."),

    _trame(r'The serum concentration of (?P<x>.+?) can be decreased when it is '
           r'combined with (?P<y>.+?)\.',
           "La concentration sérique {de_x} peut être diminuée en association avec {y}."),

    _trame(r'The therapeutic efficacy of (?P<x>.+?) can be decreased when used in '
           r'combination with (?P<y>.+?)\.',
           "L'efficacité thérapeutique {de_x} peut être diminuée en association avec {y}."),

    _trame(r'The therapeutic efficacy of (?P<x>.+?) can be increased when used in '
           r'combination with (?P<y>.+?)\.',
           "L'efficacité thérapeutique {de_x} peut être augmentée en association avec {y}."),

    _trame(r'The excretion of (?P<x>.+?) can be decreased when combined with (?P<y>.+?)\.',
           "L'élimination {de_x} peut être diminuée en association avec {y}."),

    _trame(r'The excretion of (?P<x>.+?) can be increased when combined with (?P<y>.+?)\.',
           "L'élimination {de_x} peut être augmentée en association avec {y}."),

    _trame(r'(?P<x>.+?) can cause a decrease in the absorption of (?P<y>.+?) resulting in '
           r'a reduced serum concentration and potentially a decrease in efficacy\.',
           "{x} peut diminuer l'absorption {de_y}, d'où une concentration sérique "
           "réduite et une possible perte d'efficacité."),

    _trame(r'(?P<x>.+?) may decrease effectiveness of (?P<y>.+?) as a diagnostic agent\.',
           "{x} peut réduire l'efficacité diagnostique {de_y}."),

    _trame(r'(?P<x>.+?) can cause an increase in the absorption of (?P<y>.+?) resulting in '
           r'an increased serum concentration and potentially a worsening of adverse effects\.',
           "{x} peut augmenter l'absorption {de_y}, d'où une concentration sérique "
           "accrue et une possible aggravation des effets indésirables."),

    # La substance revient deux fois dans l'énoncé anglais — « of {a} … when {a}
    # is used ». Le second emplacement est capturé sans être nommé : le
    # réutiliser en français alourdirait la phrase pour rien.
    _trame(r'The serum concentration of the active metabolites of (?P<x>.+?) can be '
           r'increased when .+? is used in combination with (?P<y>.+?)\.',
           "La concentration sérique des métabolites actifs {de_x} peut être "
           "augmentée en association avec {y}."),

    _trame(r'The serum concentration of the active metabolites of (?P<x>.+?) can be '
           r'decreased when .+? is used in combination with (?P<y>.+?)\.',
           "La concentration sérique des métabolites actifs {de_x} peut être "
           "diminuée en association avec {y}."),

    _trame(r'The serum concentration of the active metabolites of (?P<x>.+?) can be '
           r'reduced when .+? is used in combination with (?P<y>.+?) resulting in '
           r'a loss in efficacy\.',
           "La concentration sérique des métabolites actifs {de_x} peut être "
           "réduite en association avec {y}, d'où une perte d'efficacité."),

    _trame(r'The protein binding of (?P<x>.+?) can be decreased when combined with (?P<y>.+?)\.',
           "La fixation protéique {de_x} peut être diminuée en association avec {y}."),

    _trame(r'The protein binding of (?P<x>.+?) can be increased when combined with (?P<y>.+?)\.',
           "La fixation protéique {de_x} peut être augmentée en association avec {y}."),

    _trame(r'The absorption of (?P<x>.+?) can be decreased when combined with (?P<y>.+?)\.',
           "L'absorption {de_x} peut être diminuée en association avec {y}."),

    _trame(r'The absorption of (?P<x>.+?) can be increased when combined with (?P<y>.+?)\.',
           "L'absorption {de_x} peut être augmentée en association avec {y}."),

    _trame(r'The bioavailability of (?P<x>.+?) can be decreased when combined with (?P<y>.+?)\.',
           "La biodisponibilité {de_x} peut être diminuée en association avec {y}."),

    _trame(r'The bioavailability of (?P<x>.+?) can be increased when combined with (?P<y>.+?)\.',
           "La biodisponibilité {de_x} peut être augmentée en association avec {y}."),

    _trame(r'The risk of a hypersensitivity reaction to (?P<x>.+?) is increased when it is '
           r'combined with (?P<y>.+?)\.',
           "Le risque de réaction d'hypersensibilité {de_x} est augmenté en "
           "association avec {y}."),

    # Trames à vocabulaire. `effet` et `activite` sont cherchés au glossaire ;
    # un terme absent fait échouer la traduction entière, volontairement.
    _trame(r'The risk or severity of (?P<effet>.+?) can be increased when (?P<x>.+?) '
           r'is combined with (?P<y>.+?)\.',
           "Le risque ou la gravité {effet} peut être augmenté lors de "
           "l'association {de_x} et {de_y}."),

    # La variante décroissante existe : certaines associations réduisent un
    # risque. La verser dans la trame précédente aurait inversé le sens.
    _trame(r'The risk or severity of (?P<effet>.+?) can be decreased when (?P<x>.+?) '
           r'is combined with (?P<y>.+?)\.',
           "Le risque ou la gravité {effet} peut être diminué lors de "
           "l'association {de_x} et {de_y}."),

    _trame(r'(?P<x>.+?) may increase the (?P<activite>.+?) activities of (?P<y>.+?)\.',
           "{x} peut augmenter les effets {activite} {de_y}."),

    _trame(r'(?P<x>.+?) may decrease the (?P<activite>.+?) activities of (?P<y>.+?)\.',
           "{x} peut diminuer les effets {activite} {de_y}."),
]

#: « Le risque ou la gravité **de l'hypotension** » : l'article est porté par
#: la traduction, pas par la trame, parce que le français le fait varier —
#: « des effets indésirables », « du syndrome sérotoninergique »,
#: « de l'hyperkaliémie ». Le mettre dans la trame aurait imposé un « de »
#: invariable et fauté une fois sur deux.
GLOSSAIRE_EFFETS = {
    'adverse effects': 'des effets indésirables',
    'QTc prolongation': "de l'allongement du QTc",
    'CNS depression': 'de la dépression du système nerveux central',
    'methemoglobinemia': 'de la méthémoglobinémie',
    'bleeding': 'des saignements',
    'hypertension': "de l'hypertension",
    'hypoglycemia': "de l'hypoglycémie",
    'hyperkalemia': "de l'hyperkaliémie",
    'myopathy, rhabdomyolysis, and myoglobinuria':
        'de la myopathie, de la rhabdomyolyse et de la myoglobinurie',
    'nephrotoxicity': 'de la néphrotoxicité',
    'bleeding and hemorrhage': 'des saignements et des hémorragies',
    'hyperglycemia': "de l'hyperglycémie",
    'Thrombosis': 'de la thrombose',
    'serotonin syndrome': 'du syndrome sérotoninergique',
    'Tachycardia': 'de la tachycardie',
    'gastrointestinal irritation': "de l'irritation gastro-intestinale",
    'hypotension': "de l'hypotension",
    'renal failure, hyperkalemia, and hypertension':
        "de l'insuffisance rénale, de l'hyperkaliémie et de l'hypertension",
    'gastrointestinal bleeding': 'des saignements gastro-intestinaux',
    'sedation': 'de la sédation',
    'infection': "de l'infection",
    'hypokalemia': "de l'hypokaliémie",
    'sedation, somnolence, and CNS depression':
        'de la sédation, de la somnolence et de la dépression du système nerveux central',
    'neutropenia': 'de la neutropénie',
    'myelosuppression': 'de la myélosuppression',
    'bradycardia': 'de la bradycardie',
    'angioedema': "de l'angiœdème",
    'hemorrhage': 'des hémorragies',
    'dehydration': 'de la déshydratation',
    'neuropsychiatric effects': 'des effets neuropsychiatriques',
    'nephrotoxicity and hypocalcemia': 'de la néphrotoxicité et de l’hypocalcémie',
    'immunosuppression': "de l'immunosuppression",
    'seizure': 'des convulsions',
    'sedation and CNS depression':
        'de la sédation et de la dépression du système nerveux central',
    'neuromuscular blockade': 'du blocage neuromusculaire',
    'cardiotoxicity': 'de la cardiotoxicité',
    'myopathy and weakness': 'de la myopathie et de la faiblesse musculaire',
    'renal failure, hypotension, and hyperkalemia':
        "de l'insuffisance rénale, de l'hypotension et de l'hyperkaliémie",
    'neutropenia and thrombocytopenia': 'de la neutropénie et de la thrombopénie',
    'elevated intracranial pressure': "de l'hypertension intracrânienne",
    'hypotension and orthostatic hypotension':
        "de l'hypotension et de l'hypotension orthostatique",
    'hypotension and syncope': "de l'hypotension et des syncopes",
    'orthostatic hypotension and syncope':
        "de l'hypotension orthostatique et des syncopes",
    'liver damage': "de l'atteinte hépatique",
    'tendinopathy': 'de la tendinopathie',
    'Cardiac Arrhythmia': "de l'arythmie cardiaque",
    'orthostatic hypotension and dizziness':
        "de l'hypotension orthostatique et des étourdissements",
    'renal failure': "de l'insuffisance rénale",
    'bleeding and bruising': 'des saignements et des ecchymoses',
    # Le terme français consacré depuis 2013 ; « pseudotumeur cérébrale »
    # reste employé, mais la HAS retient l'autre.
    'pseudotumor cerebri': "de l'hypertension intracrânienne idiopathique",
    'ventricular arrhythmias, bradycardia, and heart block':
        'des arythmies ventriculaires, de la bradycardie et du bloc cardiaque',
    'edema formation': "de la formation d'œdèmes",
    'hypotension and CNS depression':
        "de l'hypotension et de la dépression du système nerveux central",
    'thrombocytopenia': 'de la thrombopénie',
    'sedation and somnolence': 'de la sédation et de la somnolence',
    'renal failure and hypertension':
        "de l'insuffisance rénale et de l'hypertension",
    'jaw osteonecrosis and anti-angiogenesis':
        "de l'ostéonécrose de la mâchoire et de l'anti-angiogenèse",
    'hyponatremia': "de l'hyponatrémie",
    'electrolyte imbalance': 'du déséquilibre électrolytique',
    'respiratory depression': 'de la dépression respiratoire',
    'hyperthermia and oligohydrosis': "de l'hyperthermie et de l'oligohidrose",
    'urinary retention': 'de la rétention urinaire',
    'myopathy and rhabdomyolysis': 'de la myopathie et de la rhabdomyolyse',
    'extrapyramidal symptoms': 'des symptômes extrapyramidaux',
    'peripheral neuropathy': 'de la neuropathie périphérique',
    'gastrointestinal ulceration': "de l'ulcération gastro-intestinale",
    'thromboembolism': 'de la thromboembolie',
    'orthostatic hypotension': "de l'hypotension orthostatique",
    'reduced gastrointestinal motility': 'de la réduction de la motilité gastro-intestinale',
    'vasospastic reactions': 'des réactions vasospastiques',
    'hypertension, hyponatremia, and water intoxication':
        "de l'hypertension, de l'hyponatrémie et de l'intoxication par l'eau",
    'gastrointestinal bleeding and peptic ulcer':
        'des saignements gastro-intestinaux et de l’ulcère gastroduodénal',
    'ulceration': "de l'ulcération",
    'gastrointestinal ulceration and gastrointestinal irritation':
        "de l'ulcération et de l'irritation gastro-intestinales",
    'hypercalcemia': "de l'hypercalcémie",
    'Tachycardia and drowsiness': 'de la tachycardie et de la somnolence',
    'renal failure and hypotension': "de l'insuffisance rénale et de l'hypotension",
    'bleeding and thrombocytopenia': 'des saignements et de la thrombopénie',
    'myopathy': 'de la myopathie',
    'hypocalcemia': "de l'hypocalcémie",
}

#: « peut augmenter les effets **hypotenseurs** de » : adjectifs au masculin
#: pluriel, accordés sur « effets ». Deux entrées sortent du moule et portent
#: leur propre préposition — un adjectif n'existe pas en français pour
#: l'allongement du QTc ni pour la réduction de motilité.
GLOSSAIRE_ACTIVITES = {
    'antihypertensive': 'antihypertenseurs',
    'hypotensive': 'hypotenseurs',
    'central nervous system depressant (CNS depressant)':
        'dépresseurs du système nerveux central',
    'immunosuppressive': 'immunosuppresseurs',
    'arrhythmogenic': 'arythmogènes',
    'bradycardic': 'bradycardisants',
    'hypoglycemic': 'hypoglycémiants',
    'thrombogenic': 'thrombogènes',
    'anticoagulant': 'anticoagulants',
    'sedative': 'sédatifs',
    'QTc-prolonging': "d'allongement du QTc",
    'orthostatic hypotensive': 'hypotenseurs orthostatiques',
    'neuromuscular blocking': 'bloquants neuromusculaires',
    'hyperkalemic': 'hyperkaliémiants',
    'orthostatic hypotensive, hypotensive, and antihypertensive':
        'hypotenseurs orthostatiques, hypotenseurs et antihypertenseurs',
    'serotonergic': 'sérotoninergiques',
    'neurotoxic': 'neurotoxiques',
    'nephrotoxic': 'néphrotoxiques',
    'anticholinergic': 'anticholinergiques',
    'antiplatelet': 'antiagrégants plaquettaires',
    'hypertensive and vasoconstricting': 'hypertenseurs et vasoconstricteurs',
    'vasoconstricting': 'vasoconstricteurs',
    'neuroexcitatory': 'neuroexcitateurs',
    'myelosuppressive': 'myélosuppresseurs',
    'hypertensive': 'hypertenseurs',
    'bronchodilatory': 'bronchodilatateurs',
    'hepatotoxic': 'hépatotoxiques',
    'tachycardic': 'tachycardisants',
    'antipsychotic': 'antipsychotiques',
    'vasodilatory': 'vasodilatateurs',
    'gastrointestinal motility reducing':
        'de réduction de la motilité gastro-intestinale',
    'vasopressor': 'vasopresseurs',
    'sympathomimetic': 'sympathomimétiques',
    'cardiotoxic': 'cardiotoxiques',
    'photosensitizing': 'photosensibilisants',
    'diuretic': 'diurétiques',
    'analgesic': 'analgésiques',
    'hypokalemic': 'hypokaliémiants',
    'bronchoconstrictory': 'bronchoconstricteurs',
    # Un nom, pas un adjectif : la trame dit « les effets X de », d'où la
    # préposition portée par l'entrée elle-même.
    'Change in thyroid function': 'de modification de la fonction thyroïdienne',
    'myopathic rhabdomyolysis': 'de rhabdomyolyse myopathique',
    'opioid antagonism': "d'antagonisme opioïde",
    'cardiodepressant': 'cardiodépresseurs',
    'atrioventricular blocking (AV block)': 'de bloc auriculo-ventriculaire',
    'alpha-adrenergic': 'alpha-adrénergiques',
}


def traduire(description):
    """Rend l'énoncé en français, ou `None` si le module ne sait pas le traduire.

    `None` n'est pas un échec silencieux : c'est la réponse honnête, et
    l'appelant garde l'anglais avec la mention qui va avec.
    """
    if not description:
        return None
    texte = description.strip()
    for expression, francais in TRAMES:
        correspondance = expression.match(texte)
        if not correspondance:
            continue
        champs = correspondance.groupdict()
        for cle in ('x', 'y'):
            if cle in champs:
                champs['de_' + cle] = _elider(champs[cle])
        if 'effet' in champs:
            traduit = GLOSSAIRE_EFFETS.get(champs['effet'])
            if not traduit:
                return None
            champs['effet'] = traduit
        if 'activite' in champs:
            traduit = GLOSSAIRE_ACTIVITES.get(champs['activite'])
            if not traduit:
                return None
            champs['activite'] = traduit
        return francais.format(**champs)
    return None


def couverture(chemin_patrons=None):
    """Part des énoncés du catalogue que ce module sait traduire.

    Se mesure sur `ressources/patrons_interactions.json`, produit par
    `scripts/extraire_patrons_interactions.py` : chaque patron y porte son
    nombre d'occurrences, donc la couverture se pondère sans relire Neo4j.

        python -c "import interaction_i18n as i; print(i.couverture())"
    """
    import json
    import os

    if chemin_patrons is None:
        chemin_patrons = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                      'ressources', 'patrons_interactions.json')
    with open(chemin_patrons, encoding='utf-8') as fichier:
        patrons = json.load(fichier)

    total = traduits = 0
    patrons_couverts = 0
    for entree in patrons:
        # Deux noms quelconques suffisent : les emplacements sont substitués
        # sans être interprétés.
        exemple = entree['en'].replace('{a}', 'Warfarine').replace('{b}', 'Amiodarone')
        total += entree['occurrences']
        if traduire(exemple):
            traduits += entree['occurrences']
            patrons_couverts += 1
    return {
        'enonces': total,
        'enonces_traduits': traduits,
        'part': round(traduits / total, 5) if total else 0.0,
        'patrons': len(patrons),
        'patrons_couverts': patrons_couverts,
        'trames': len(TRAMES),
        'termes': len(GLOSSAIRE_EFFETS) + len(GLOSSAIRE_ACTIVITES),
    }
