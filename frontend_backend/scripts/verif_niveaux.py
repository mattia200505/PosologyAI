"""Banc : une règle dit son niveau, et une classe dit si elle se cumule.

Ce que ce banc garde
--------------------

**Toutes les règles excluaient.** C'était trop absolu : une valeur anormale
doit d'abord être qualifiée. Une hyponatrémie chez un patient sous furosémide
appelle une surveillance et une réévaluation — elle ne fait pas du furosémide
un mauvais traitement.

Les trois mécanismes existaient pourtant déjà, mais le niveau dépendait de
**qui** était le médicament, pas de **ce que la règle voulait dire** :

    candidat            -> appliquer_contraintes        -> écarté
    traitement en cours -> traitements_a_reconsiderer   -> signalé

La même règle, deux verdicts, deux chemins de code. `graphify path` ne
trouvait aucun chemin entre les deux fonctions : c'étaient bien deux logiques
parallèles pour une seule question.

**Et le vocabulaire des règles est une liste de noms écrite à la main.** Une
molécule absente de toutes les listes est invisible à toutes les règles.
Mesuré chez un patient à 96/58, DFG 28, natrémie 128, FEVG 30 % : huit règles
se déclenchaient et **pas une ne nommait le bendrofluméthiazide**. Il ne
restait que sa classe ATC C03 pour le noter, et il était proposé.

C'est la troisième fois que ce défaut se manifeste — les épargneurs de
potassium, puis le cardiovasculaire hors table.

**Enfin, partager une classe n'est pas toujours faire double emploi.** Deux
bêta-bloquants sont une duplication. Un second diurétique de l'anse peut être
une intensification, et c'est la conduite d'une congestion importante.

Emploi
------
    python scripts/verif_niveaux.py

Aucune base n'est nécessaire.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from prescription_helper import (  # noqa: E402
    CLASSES_THERAPEUTIQUES,
    NIVEAUX,
    NIVEAU_CLASSEMENT,
    NIVEAU_EXCLUSION,
    NIVEAU_SURVEILLANCE,
    PENALITE_CLASSEMENT,
    PENALITE_CONTRE_INDICATION,
    SEUIL_EXCLUSION,
    SEUILS_BIOLOGIQUES,
    appliquer_contraintes,
    confronter_aux_regles,
    contraintes_biologiques,
    couvert_par_le_traitement,
    niveau_de,
    peser_la_securite,
    traitements_a_reconsiderer,
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


#: Le patient signalé, tel qu'il a été saisi.
MESURES = {'dfg': 28, 'kaliemie': 5.8, 'natremie': 128, 'transaminases': 145,
           'systolique': 96, 'diastolique': 58, 'fevg': 30,
           'frequence_cardiaque': 112}
ANTECEDENTS = ("Insuffisance cardiaque chronique a fraction d ejection reduite, "
               "Maladie renale chronique stade 3b")
EN_COURS = ['Bisoprolol 5 mg', 'Sacubitril/Valsartan 49/51 mg',
            'Furosemide 80 mg', 'Spironolactone 25 mg',
            'Empagliflozine 10 mg', 'Apixaban 5 mg']


def med(titre, substance, *groupes, note=60):
    return {'title': titre, 'substances': [substance],
            'groupes_atc': list(groupes), 'pertinence': note}


def niveau_du_seuil(fragment):
    return next(niveau_de(s) for s in SEUILS_BIOLOGIQUES
                if fragment in s['libelle'])


# ── 1. Chaque règle porte son niveau ─────────────────────────────────────

verifier("les trois niveaux sont nommés", sorted(NIVEAUX),
         sorted([NIVEAU_CLASSEMENT, NIVEAU_EXCLUSION, NIVEAU_SURVEILLANCE]))

# Ce qui reste une contre-indication formelle.
verifier("un DFG sous 30 exclut toujours",
         niveau_du_seuil('30 mL/min'), NIVEAU_EXCLUSION)
verifier("une hyperkaliémie aussi",
         niveau_du_seuil('kaliémie'), NIVEAU_EXCLUSION)
verifier("une FEVG sous 40 aussi",
         niveau_du_seuil("fraction d'éjection"), NIVEAU_EXCLUSION)

# Ce qui cesse d'exclure. L'hyponatrémie est le cas qui a montré que le
# niveau unique était faux.
verifier("l'hyponatrémie passe en surveillance",
         niveau_du_seuil('natrémie'), NIVEAU_SURVEILLANCE)
verifier("la cytolyse hépatique aussi",
         niveau_du_seuil('transaminases'), NIVEAU_SURVEILLANCE)
verifier("la tachycardie est une surveillance",
         niveau_du_seuil('supérieure à 100'), NIVEAU_SURVEILLANCE)

# Ce qui ne fait plus que déclasser.
verifier("l'hypotension déclasse", niveau_du_seuil('systolique'),
         NIVEAU_CLASSEMENT)
verifier("un DFG sous 60 aussi — son motif dit « adapter les posologies »",
         niveau_du_seuil('60 mL/min'), NIVEAU_CLASSEMENT)

# PAS et PAD sont deux nombres pour un seul fait clinique — une seule règle,
# jamais deux qui se déclenchent ensemble et comptent double.
verifier("PAS et PAD sont une seule règle, pas deux",
         sum(1 for s in SEUILS_BIOLOGIQUES
             if 'systolique' in s['libelle'] or 'diastolique' in s['libelle']),
         1)
verifier("elle porte les deux conditions",
         {c['mesure'] for c in next(
             s for s in SEUILS_BIOLOGIQUES if 'systolique' in s['libelle']
         )['conditions']},
         {'systolique', 'diastolique'})

# Une règle sans niveau exclut : les huit règles d'antécédents sont toutes
# des contre-indications de manuel, et le défaut les laisse telles.
verifier("une règle sans niveau exclut", niveau_de({}), NIVEAU_EXCLUSION)
verifier("None ne casse pas", niveau_de(None), NIVEAU_EXCLUSION)

# Le déclassement pèse moins qu'une contre-indication : il dit
# l'inopportunité, pas le danger.
verifier("le déclassement pèse moins qu'une contre-indication",
         PENALITE_CLASSEMENT < PENALITE_CONTRE_INDICATION, True)


# ── 2. La tachycardie existe désormais ───────────────────────────────────

declenchees = {s['libelle'] for s in contraintes_biologiques(MESURES)}
verifier("112 battements déclenchent une règle",
         any('supérieure à 100' in d for d in declenchees), True)
verifier("et 48 continuent d'en déclencher une autre",
         any('inférieure à 50' in s['libelle']
             for s in contraintes_biologiques({'frequence_cardiaque': 48})),
         True)
verifier("une fréquence normale ne déclenche rien",
         contraintes_biologiques({'frequence_cardiaque': 72}), [])


# ── 3. Le filet ATC rend visible ce que la table ignore ──────────────────
#
# Huit règles se déclenchaient chez ce patient, aucune ne nommait le
# bendrofluméthiazide. Il ne restait que sa classe C03 pour le noter.

regles = contraintes_biologiques(MESURES)
FLUDEX = med('FLUDEX 2,5 mg', 'Bendroflumethiazide', 'C03')

verdicts = confronter_aux_regles(FLUDEX, regles)
verifier("le bendrofluméthiazide n'est plus invisible", len(verdicts) > 0, True)
verifier("tous ses verdicts viennent de la classe, pas du nom",
         all(v['par_classe'] for v in verdicts), True)

# Le filet **plafonne**, il n'exclut jamais : les codes ATC d'une substance
# DrugBank incluent ceux de toutes ses associations (§ 12.5), et une exclusion
# sur ce signal serait une décision prise sur une donnée polluée.
verifier("le filet n'exclut jamais",
         [v for v in verdicts if v['niveau'] == NIVEAU_EXCLUSION], [])

# Mais il n'amortit pas non plus : sinon la molécule absente de la table se
# classerait **mieux** que celle qui y figure, ce qui récompenserait le trou.
verifier("une règle de classement garde son niveau à travers le filet",
         any(v['niveau'] == NIVEAU_CLASSEMENT for v in verdicts), True)

verifier("le motif dit que la substance n'est pas reconnue",
         'pas reconnue' in verdicts[0]['motif'], True)
verifier("et nomme la classe employée à la place",
         'C03' in verdicts[0]['motif'], True)

# Un candidat sans groupe ATC ne déclenche pas le filet : sans donnée, on
# n'invente pas de rapprochement.
verifier("sans groupe ATC, le filet ne joue pas",
         confronter_aux_regles(
             {'title': 'INCONNU', 'substances': ['Truc']}, regles), [])

# Le nom reste la vérité : une substance reconnue n'est jamais jugée par sa
# classe, sinon le filet remplacerait la table au lieu de la compléter.
sur_furosemide = confronter_aux_regles(
    med('LASILIX 40 mg', 'Furosemide', 'C03'), regles)
verifier("une substance reconnue est jugée sur son nom",
         any(not v['par_classe'] for v in sur_furosemide), True)


# ── 4. Les trois niveaux se traduisent en trois conséquences ─────────────

lot = [FLUDEX, med('BURINEX 1 mg', 'Bumetanide', 'C03'),
       med('ISOPTINE 120 mg', 'Verapamil', 'C08'),
       med('MODAMIDE 5 mg', 'Amiloride', 'C03')]
retenus, ecartes = appliquer_contraintes(list(lot), ANTECEDENTS, MESURES)
peser_la_securite(retenus, [])
# Clé = titre entier. Découper sur la virgule cassait « FLUDEX 2,5 mg ».
par_nom = {m['title']: m for m in retenus}

# Exclusion : l'amiloride est un épargneur de potassium et la kaliémie est à
# 5,8 ; le vérapamil est un inotrope négatif et la FEVG est à 30 %. Deux
# règles d'exclusion, deux motifs distincts.
motifs = {m['title']: (m['motif_ecart'] or '').lower() for m in ecartes}
verifier("les règles d'exclusion écartent",
         sorted(motifs), ['ISOPTINE 120 mg', 'MODAMIDE 5 mg'])
verifier("l'épargneur de potassium est écarté sur la kaliémie",
         'kali' in motifs['MODAMIDE 5 mg'], True)
verifier("l'inotrope négatif l'est sur la fraction d'éjection",
         'jection' in motifs['ISOPTINE 120 mg'], True)

# Surveillance : porté par la fiche, la note ne bouge pas de ce fait.
verifier("une règle de surveillance ne retire pas le médicament",
         'BURINEX 1 mg' in par_nom, True)
verifier("elle attache une alerte",
         len(par_nom['BURINEX 1 mg'].get('alertes') or []) > 0, True)

# Classement : la note baisse, et la pénalité se nomme.
verifier("une règle de classement fait baisser la note",
         par_nom['BURINEX 1 mg']['pertinence'] < 60, True)
verifier("la pénalité est nommée",
         any('systolique' in p.lower() or 'hypotension' in p.lower()
             for p in par_nom['BURINEX 1 mg'].get('penalites') or []), True)

# Le point du signalement : PAS 96 et PAD 58 sont un seul fait, une seule
# pénalité. 60 - 15 = 45, au-dessus du seuil de 40 — le candidat reste
# visible, avec l'alerte, au lieu de disparaître par double comptage.
verifier("l'hypotension ne coûte qu'une pénalité, pas deux",
         par_nom['BURINEX 1 mg']['pertinence'], 60 - PENALITE_CLASSEMENT)
verifier("et le candidat reste au-dessus du seuil d'exclusion",
         par_nom['BURINEX 1 mg']['pertinence'] >= SEUIL_EXCLUSION, True)

# Le trou de couverture ne doit pas rapporter de points.
verifier("la molécule inconnue de la table ne se classe pas mieux",
         par_nom['FLUDEX 2,5 mg']['pertinence']
         <= par_nom['BURINEX 1 mg']['pertinence'], True)

# Tous les verdicts sont gardés, pas seulement le premier : la boucle
# s'arrêtait au premier rapprochement, ce qui suffisait tant que tout excluait.
verifier("plusieurs verdicts coexistent sur une même fiche",
         len(par_nom['BURINEX 1 mg'].get('alertes') or [])
         + len(par_nom['BURINEX 1 mg'].get('declassements') or []) > 1, True)


# ── 4 bis. Le cas signalé : plus rien ne se proposait ────────────────────
#
# La correction posée, un patient à 96/58 en décompensation cardiaque ne
# voyait plus AUCUNE proposition : douze candidats recrutés pour sa classe —
# diurétiques, bêta-bloquants, bloqueurs du SRAA, exactement ce que la
# pathologie appelle — perdaient chacun 30 points pour un seul fait clinique
# (hypotension comptée deux fois) et tombaient tous sous le seuil de 40.
#
# Reproduit ici tel que `candidats_par_classe` le note : 60 partout, aucune
# contre-indication propre — le score initial d'un candidat retenu pour sa
# seule classe ATC.
DOUZE = [med('C%02d' % i, 'Substance%d' % i, groupe, note=60)
        for i, groupe in enumerate(['C03', 'C03', 'C03', 'C07', 'C07', 'C07',
                                    'C09', 'C09', 'C08', 'C08', 'C02', 'C03'])]
retenus_douze, ecartes_douze = appliquer_contraintes(
    list(DOUZE), '', {'systolique': 96, 'diastolique': 58})
peser_la_securite(retenus_douze, [])

verifier("aucun des douze n'est écarté par la seule hypotension",
         len(ecartes_douze), 0)
verifier("aucun ne tombe sous le seuil d'exclusion",
         all(m['pertinence'] >= SEUIL_EXCLUSION for m in retenus_douze), True)
verifier("chacun ne porte qu'une seule pénalité d'hypotension",
         all(len(m.get('declassements') or []) == 1 for m in retenus_douze),
         True)


# ── 5. Duplication contre intensification ────────────────────────────────
#
# Bisoprolol -> Timolol : duplication, exclusion.
# Furosémide -> autre diurétique de l'anse : intensification possible.

CANDIDATS = [med('TIMACOR 10 mg', 'Timolol', 'C07'),
             med('BURINEX 1 mg', 'Bumetanide', 'C03'),
             med('ODRIK 2 mg', 'Trandolapril', 'C09')]
gardes, ecartes_cumul = couvert_par_le_traitement(list(CANDIDATS), EN_COURS)
noms_ecartes = {m['title'] for m in ecartes_cumul}
noms_gardes = {m['title'] for m in gardes}

verifier("deux bêta-bloquants restent une duplication",
         'TIMACOR 10 mg' in noms_ecartes, True)
verifier("l'IEC sur ARNI reste une association proscrite",
         'ODRIK 2 mg' in noms_ecartes, True)

# Le point de la demande : ne pas exclure automatiquement sur la seule
# appartenance à une classe déjà présente.
verifier("un second diurétique de l'anse n'est plus exclu",
         'BURINEX 1 mg' in noms_gardes, True)

burinex = next(m for m in gardes if m['title'] == 'BURINEX 1 mg')
alerte = ' '.join(a['motif'] for a in burinex.get('alertes') or [])
verifier("il porte l'alerte à la place", bool(alerte), True)
verifier("qui nomme le traitement en place", 'Furosemide' in alerte, True)
verifier("et pose la question de l'intensification",
         'majorer' in alerte.lower(), True)

# La table dit, classe par classe, ce qui se cumule.
verifier("le bêta-bloquant ne se cumule jamais",
         CLASSES_THERAPEUTIQUES['betabloquant']['cumul'], 'jamais')
verifier("le diurétique de l'anse peut s'intensifier",
         CLASSES_THERAPEUTIQUES['diuretique_anse']['cumul'], 'possible')
verifier("le thiazidique aussi — blocage séquentiel du néphron",
         CLASSES_THERAPEUTIQUES['thiazidique']['cumul'], 'possible')
verifier("chaque classe se prononce",
         [c for c, v in CLASSES_THERAPEUTIQUES.items()
          if v.get('cumul') not in ('jamais', 'possible')], [])


# ── 6. Une seule évaluation pour les deux côtés ──────────────────────────
#
# `traitements_a_reconsiderer` avait sa propre boucle de rapprochement :
# deux chemins de code pour une seule question, qui pouvaient diverger.

releves = traitements_a_reconsiderer(EN_COURS, ANTECEDENTS, MESURES)
verifier("les traitements en cours sont relus", len(releves) > 0, True)
verifier("chaque relevé porte son niveau",
         [r for r in releves if not r.get('niveau')], [])
verifier("et son libellé lisible",
         [r for r in releves if not r.get('niveau_libelle')], [])

niveaux_vus = {r['niveau'] for r in releves}
verifier("la spironolactone à 5,8 de kaliémie est une contre-indication",
         any(r['niveau'] == NIVEAU_EXCLUSION and 'Spironolactone' in r['traitement']
             for r in releves), True)
verifier("le furosémide à 128 de natrémie n'est qu'une surveillance",
         any(r['niveau'] == NIVEAU_SURVEILLANCE and 'Furosemide' in r['traitement']
             for r in releves), True)
verifier("les trois niveaux se rencontrent sur ce patient",
         len(niveaux_vus), 3)

# Signalés, jamais retirés : on ne retire pas un traitement en cours depuis un
# écran de suggestion, même contre-indiqué.
verifier("aucun traitement en cours n'est retiré",
         all('etage_ecart' not in r for r in releves), True)

verifier("aucun traitement saisi ne rend rien",
         traitements_a_reconsiderer([], ANTECEDENTS, MESURES), [])
verifier("aucune règle active ne rend rien",
         traitements_a_reconsiderer(EN_COURS, '', {}), [])
verifier("None ne casse pas", traitements_a_reconsiderer(None, None, None), [])


# ── 7. Le branchement ────────────────────────────────────────────────────

source = (Path(__file__).resolve().parent.parent
          / 'prescription_helper.py').read_text(encoding='utf-8')
code = '\n'.join(l for l in source.split('\n') if not l.lstrip().startswith('#'))

# L'ancienne boucle de `traitements_a_reconsiderer` doit avoir disparu au
# profit de l'évaluation commune : c'est ce qui empêche les deux chemins de
# diverger à nouveau.
corps = code[code.index('def traitements_a_reconsiderer'):]
corps = corps[:corps.index('\ndef ', 10)]
verifier("les traitements en cours passent par l'évaluation commune",
         'confronter_aux_regles(' in corps, True)

contraintes = code[code.index('def appliquer_contraintes'):]
contraintes = contraintes[:contraintes.index('\ndef ', 10)]
verifier("les candidats aussi", 'confronter_aux_regles(' in contraintes, True)

# La note ne doit baisser qu'à un seul endroit.
verifier("seule la pesée touche à la note",
         code.count("med['pertinence'] = max(0,"), 1)


# ── Relevé ───────────────────────────────────────────────────────────────

print()
print("  Niveau de chaque seuil :")
for s in SEUILS_BIOLOGIQUES:
    print("    %-56s %s" % (s['libelle'][:56], NIVEAUX[niveau_de(s)]))
print()
print("  Le bendrofluméthiazide, désormais :")
for v in verdicts:
    print("    [%s] %s" % (NIVEAUX[v['niveau']], v['regle']))
print()
print("  Traitement en cours, par niveau :")
for niveau in (NIVEAU_EXCLUSION, NIVEAU_SURVEILLANCE, NIVEAU_CLASSEMENT):
    noms = sorted({r['traitement'] for r in releves if r['niveau'] == niveau})
    print("    %-22s %s" % (NIVEAUX[niveau], ', '.join(noms) or '—'))

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
