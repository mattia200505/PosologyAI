"""Banc : une association ne transmet pas sa classe à ses composants.

Ce que ce banc garde
--------------------

Une substance DrugBank porte les codes ATC de **toutes les associations qui la
contiennent**, et rien dans le graphe ne les distingue : la relation `HAS_ATC`
n'a aucune propriété, un nœud `AtcClass` ne porte que `code` et `niveau`.

L'amlodipine — un inhibiteur calcique, `C08CA01` — porte ainsi trente-cinq
codes, dont `C07FB13` (bisoprolol + amlodipine). Le moteur la découvrait donc
comme bêta-bloquante, et la proposait en première intention pour une
insuffisance cardiaque décompensée.

**Ce n'est pas un défaut de l'amlodipine.** Mesuré : 277 substances sur 1 485
— 19 % — portent des codes de plusieurs groupes de niveau 2. C'est la forme de
la donnée.

Deux règles structurelles corrigent la représentation, et **aucune ne nomme un
médicament** :

    suffixe ≥ 50         C08CA51 est l'amlodipine associée, C08CA01 l'amlodipine
    sous-groupe dédié    C07FB, C09BB, N02AJ, J01RA ne contiennent que des
                         associations, et leur suffixe est inférieur à 50

Ce banc éprouve la règle, pas des cas particuliers : les contrôles portent sur
la forme des codes, sur l'invariant « une association n'ajoute jamais de
groupe » et sur la non-régression du repli.

Emploi
------
    python scripts/verif_atc_association.py

Aucune base n'est nécessaire.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from prescription_helper import (  # noqa: E402
    couvert_par_le_traitement,
    SOUS_GROUPES_ASSOCIATION,
    est_code_d_association,
    groupes_propres,
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


# ── 1. La règle du suffixe ───────────────────────────────────────────────
#
# L'OMS réserve les numéros 50 et au-delà du cinquième niveau aux
# associations. C'est une propriété de la classification, vraie de toute
# substance, présente ou future.

verifier("un suffixe 01 désigne la substance seule",
         est_code_d_association('C08CA01'), False)
verifier("un suffixe 51 désigne une association",
         est_code_d_association('C08CA51'), True)
verifier("71 aussi", est_code_d_association('N02BE71'), True)
verifier("49 reste une substance seule",
         est_code_d_association('C09AA49'), False)
verifier("50 bascule", est_code_d_association('C09AA50'), True)


# ── 2. La règle du sous-groupe ───────────────────────────────────────────
#
# Certains groupes de niveau 4 ne contiennent que des associations, et leur
# suffixe est inférieur à 50 : la première règle ne les voit pas.

verifier("C07FB13 est une association malgré son suffixe bas",
         est_code_d_association('C07FB13'), True)
verifier("C09BB07 aussi", est_code_d_association('C09BB07'), True)
verifier("N02AJ01 aussi", est_code_d_association('N02AJ01'), True)
verifier("J01RA02 aussi", est_code_d_association('J01RA02'), True)

# Le sous-groupe voisin, lui, n'en est pas un : la table doit distinguer
# C07FB de C07AB, sans quoi elle écarterait les bêta-bloquants eux-mêmes.
verifier("C07AB07 n'est pas une association",
         est_code_d_association('C07AB07'), False)
verifier("C08CA01 non plus", est_code_d_association('C08CA01'), False)
verifier("C03CA01 non plus", est_code_d_association('C03CA01'), False)


# ── 3. Ce qui ne se lit pas ne s'invente pas ─────────────────────────────
#
# Dans le doute on garde : un code illisible compte comme propre, comme
# partout ailleurs dans la chaîne.

verifier("un code trop court est laissé propre",
         est_code_d_association('C08'), False)
verifier("un suffixe non numérique aussi",
         est_code_d_association('C08CAXX'), False)
verifier("une chaîne vide aussi", est_code_d_association(''), False)
verifier("None ne casse pas", est_code_d_association(None), False)


# ── 4. L'invariant : une association n'ajoute jamais de groupe ───────────
#
# C'est le contrôle qui vaut pour un médicament jamais rencontré. On ne
# nomme aucune substance : on affirme qu'ajouter un code d'association à un
# jeu de codes ne peut pas élargir les groupes propres.

CAS = [
    ['C08CA01'],
    ['C03CA01', 'C03CA02'],
    ['N02BE01'],
    ['C07AB07'],
    ['J01CA04'],
]
ASSOCIATIONS = ['C07FB13', 'C09BB07', 'N02AJ01', 'C10BX03', 'A02BD05',
                'C08CA51', 'N02BE51']

for codes in CAS:
    attendu = groupes_propres(codes)
    for ajout in ASSOCIATIONS:
        verifier("ajouter %s à %s n'élargit pas les groupes"
                 % (ajout, codes[0]),
                 groupes_propres(codes + [ajout]), attendu)


# ── 5. Le repli : ne jamais tout retirer ─────────────────────────────────
#
# Vingt-deux substances du graphe n'ont que des codes d'association. Les
# priver de tout groupe les rendrait indécouvrables, ce qui serait pire que
# le défaut corrigé.

verifier("une substance qui n'a que des associations garde ses groupes",
         groupes_propres(['C07FB13', 'C09BB07']), {'C07', 'C09'})
verifier("aucun code ne rend aucun groupe", groupes_propres([]), set())
verifier("None ne casse pas", groupes_propres(None), set())


# ── 6. Le cas qui a révélé le défaut ─────────────────────────────────────
#
# Nommé pour mémoire, mais il n'est pas ce que le banc protège : les
# contrôles ci-dessus tiennent sans lui.

AMLODIPINE = ['C07FB07', 'C07FB12', 'C07FB13', 'C08CA01', 'C08CA51',
              'C09BB01', 'C09BB02', 'C09DB01', 'C10BX03']
verifier("l'amlodipine ressort inhibiteur calcique, et rien d'autre",
         groupes_propres(AMLODIPINE), {'C08'})

BISOPROLOL = ['C07AB07', 'C07FB07', 'C09BX05']
verifier("le bisoprolol ressort bêta-bloquant",
         groupes_propres(BISOPROLOL), {'C07'})

# Une substance qui sert réellement plusieurs domaines les garde tous : le
# filtre vise les associations, pas la polyvalence.
METRONIDAZOLE = ['A01AB17', 'D06BX01', 'G01AF01', 'J01XD01', 'P01AB01']
verifier("une substance polyvalente garde ses domaines",
         groupes_propres(METRONIDAZOLE),
         {'A01', 'D06', 'G01', 'J01', 'P01'})


# ── 7. La table décrit la classification, pas des médicaments ────────────

verifier("la table ne contient que des sous-groupes de niveau 4",
         [g for g in SOUS_GROUPES_ASSOCIATION if len(g) != 5], [])
verifier("tous en majuscules",
         [g for g in SOUS_GROUPES_ASSOCIATION if g != g.upper()], [])
verifier("aucun doublon",
         len(SOUS_GROUPES_ASSOCIATION), len(set(SOUS_GROUPES_ASSOCIATION)))


# ── 8. Le branchement ────────────────────────────────────────────────────

source = (Path(__file__).resolve().parent.parent
          / 'prescription_helper.py').read_text(encoding='utf-8')
code = '\n'.join(l for l in source.split('\n')
                 if not l.lstrip().startswith('#'))

# Les deux lectures du graphe doivent filtrer. Sans cela le défaut revient
# par l'une ou par l'autre : `groupes_atc_des` note la mauvaise classe,
# `candidats_par_classe` recrute le mauvais candidat.
for fonction in ('groupes_atc_des', 'candidats_par_classe'):
    corps = code[code.index('def %s' % fonction):]
    corps = corps[:corps.index(chr(10) + 'def ', 10)]
    verifier("%s écarte les codes d'association" % fonction,
             'groupes_propres(' in corps, True)

# La remontée par `HAS_PARENT` mélangeait le code propre et ceux des
# associations : elle ne doit pas revenir dans ces deux fonctions.
corps = code[code.index('def groupes_atc_des'):]
corps = corps[:corps.index(chr(10) + 'def ', 10)]
verifier("le niveau 2 est dérivé du code, non remonté par la hiérarchie",
         'HAS_PARENT' not in corps, True)


# ── Même molécule, ou seulement même classe ? ───────────────────────────
#
# La comparaison ne portait que sur les classes. Mesuré : un FUROSEMIDE
# proposé à un patient déjà sous furosémide recevait **mot pour mot** la même
# alerte qu'un BURINEX — « même classe que … (diurétique de l'anse) ». L'un est
# le traitement en cours lui-même, l'autre une autre molécule.
#
# Proposer à nouveau ce que le patient prend déjà n'est pas un choix
# thérapeutique : c'est une question de posologie.

EN_COURS_FURO = ['Furosemide 80 mg', 'Bisoprolol 5 mg']


def _candidat(titre, substance, groupe):
    return {'title': titre, 'substances': [substance],
            'groupes_atc': [groupe], 'pertinence': 90}


def _alerte(med):
    return (med.get('alertes') or [{}])[0]


# 1. Furosémide -> furosémide : la même molécule.
_furo = _candidat('FUROSEMIDE ZYDUS 20 mg', 'Furosémide', 'C03')
_gardes, _ecartes = couvert_par_le_traitement([_furo], EN_COURS_FURO)
verifier("la même substance n'est pas écartée", _ecartes, [])
verifier("elle est conservée", [m['title'] for m in _gardes],
         ['FUROSEMIDE ZYDUS 20 mg'])
verifier("son alerte dit que la substance est déjà prescrite",
         _alerte(_furo).get('regle'), 'substance déjà prescrite')
verifier("elle nomme le traitement en cours",
         'Furosemide 80 mg' in _alerte(_furo).get('motif', ''), True)
verifier("et parle d'adaptation plutôt que d'ajout",
         'adaptation' in _alerte(_furo).get('motif', '').lower(), True)

# 2. Furosémide -> bumétanide : autre molécule, même classe cumulable.
#    Comportement d'origine conservé.
_bume = _candidat('BURINEX 1 mg', 'Bumétanide', 'C03')
_gardes2, _ecartes2 = couvert_par_le_traitement([_bume], EN_COURS_FURO)
verifier("une autre molécule de la même classe n'est pas écartée non plus",
         _ecartes2, [])
verifier("mais son alerte reste celle de la classe",
         _alerte(_bume).get('regle'), 'même classe que le traitement en cours')
verifier("les deux alertes sont bien distinctes",
         _alerte(_furo).get('regle') != _alerte(_bume).get('regle'), True)

# 3. Classe différente : rien ne se déclenche.
_iec = _candidat('RENITEC 20 mg', 'Énalapril', 'C09')
_gardes3, _ecartes3 = couvert_par_le_traitement([_iec], EN_COURS_FURO)
verifier("une classe différente ne déclenche aucune alerte",
         _iec.get('alertes'), None)
verifier("et le candidat passe", [m['title'] for m in _gardes3],
         ['RENITEC 20 mg'])

# 4. La duplication vraie continue d'écarter : le garde-fou.
_beta = _candidat('TIMACOR 10 mg', 'Timolol', 'C07')
_gardes4, _ecartes4 = couvert_par_le_traitement([_beta], EN_COURS_FURO)
verifier("un second bêta-bloquant reste écarté",
         [m['etage_ecart'] for m in _ecartes4], ['redondance'])

# 5. La reconnaissance se fait à frontière de mot et accents repliés, comme
#    partout ailleurs : « Furosémide » de la fiche contre « Furosemide » de la
#    saisie.
_accent = _candidat('LASILIX', 'Furosémide', 'C03')
couvert_par_le_traitement([_accent], ['furosemide 40 mg'])
verifier("les accents et la casse ne font pas manquer la substance",
         _alerte(_accent).get('regle'), 'substance déjà prescrite')

# Une substance qui n'est pas dans le traitement ne doit pas être reconnue
# par une sous-chaîne fortuite.
_autre = _candidat('X', 'Uree', 'C03')
couvert_par_le_traitement([_autre], EN_COURS_FURO)
verifier("aucune reconnaissance fortuite par sous-chaîne",
         _alerte(_autre).get('regle') != 'substance déjà prescrite', True)

# Le score, le rang et la sélection ne changent pas : seule l'alerte diffère.
verifier("la note du candidat est intacte", _furo.get('pertinence'), 90)
verifier("aucun rang n'a été pose", _furo.get('rang'), None)


# ── G01AE : les sulfamides ne sont pas des anti-infectieux gynéco ───────
#
# DrugBank raccroche `G01AE10` — « associations de sulfamides » — à **toute**
# molécule portant un groupement sulfonamide. Mesuré : vingt-six substances le
# portent, dont rosuvastatine, sildénafil, bosentan, célécoxib, sumatriptan,
# acétazolamide, et les diurétiques. Le furosémide ressortait
# « anti-infectieux et antiseptique gynécologique » à l'écran, et pouvait être
# recruté pour un diagnostic gynécologique.
#
# Son suffixe `10` est inférieur à 50 : la première règle ne le voyait pas.

verifier("G01AE10 est reconnu comme une association",
         est_code_d_association('G01AE10'), True)
verifier("G01AE figure dans la table", 'G01AE' in SOUS_GROUPES_ASSOCIATION,
         True)

# Le furosémide : C03 conservé, G01 disparu.
FUROSEMIDE_CODES = ['C03CA01', 'C03CB01', 'C03EB01', 'G01AE10']
verifier("le furosémide reste un diurétique",
         'C03' in groupes_propres(FUROSEMIDE_CODES), True)
verifier("et n'est plus un anti-infectieux gynécologique",
         'G01' in groupes_propres(FUROSEMIDE_CODES), False)
verifier("il ne lui reste que sa classe réelle",
         groupes_propres(FUROSEMIDE_CODES), {'C03'})

# Les autres porteurs de G01AE10 : chacun garde sa vraie classe.
for nom, codes, attendu in (
        ('bumétanide', ['C03CA02', 'G01AE10'], {'C03'}),
        ('hydrochlorothiazide', ['C03AA03', 'G01AE10'], {'C03'}),
        ('célécoxib', ['M01AH01', 'L01XX33', 'G01AE10'], {'M01', 'L01'}),
        ('acétazolamide', ['S01EC01', 'G01AE10'], {'S01'}),
        ('sumatriptan', ['N02CC01', 'G01AE10'], {'N02'})):
    verifier("%s garde sa classe et perd G01" % nom,
             groupes_propres(codes), attendu)

# **Le garde-fou** : une substance qui n'aurait que ce code garde ses groupes
# bruts. Aucune ne doit devenir indécouvrable.
verifier("une substance qui n'a que G01AE10 garde son groupe",
         groupes_propres(['G01AE10']), {'G01'})

# Un vrai anti-infectieux gynécologique n'est pas touché : c'est le
# sous-groupe des associations qui est visé, pas G01 tout entier.
verifier("un anti-infectieux gynécologique réel garde G01",
         'G01' in groupes_propres(['G01AF01']), True)
verifier("G01AF n'est pas une association",
         est_code_d_association('G01AF01'), False)


# ── Relevé ───────────────────────────────────────────────────────────────

print()
print("  %-16s %-42s %s" % ('SUBSTANCE', 'CODES', 'GROUPES PROPRES'))
for nom, codes in (('Amlodipine', AMLODIPINE), ('Bisoprolol', BISOPROLOL),
                   ('Métronidazole', METRONIDAZOLE)):
    tous = sorted({c[:3] for c in codes})
    print("  %-16s %-42s %s" % (nom, tous, sorted(groupes_propres(codes))))

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
