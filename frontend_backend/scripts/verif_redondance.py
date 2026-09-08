"""Banc : le traitement en cours pèse sur la sélection.

Ce que ce banc garde
--------------------

**Le traitement en cours n'était lu que pour les interactions.** Dans
`appliquer_controles`, il servait à `check_interactions()` et à
`traitements_a_reconsiderer()`. Il n'était **jamais** comparé aux
propositions : le moteur ne pouvait pas savoir ce qu'il redisait.

Mesuré sur un patient sous bisoprolol, sacubitril/valsartan, furosémide,
spironolactone, empagliflozine et apixaban, avec une pression à 96/58 et une
fraction d'éjection à 30 %. L'écran proposait :

    Timolol        un second bêta-bloquant
    Pindolol       un troisième
    Trandolapril   un IEC, alors qu'un ARNI est en place
    Vérapamil      un inotrope négatif sur une FEVG à 30 %

Appartenir à la classe que le diagnostic appelle ne suffit pas : encore
faut-il que la place soit libre, et que l'état du patient le permette.

**Et les constantes n'existaient pas.** Le 96/58 et la FEVG à 30 % avaient bien
été saisis — dans le texte libre, qu'aucune règle ne lit. Une donnée
qu'aucune règle ne peut lire ne protège de rien.

Emploi
------
    python scripts/verif_redondance.py

Aucune base n'est nécessaire.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from prescription_helper import (  # noqa: E402
    ANTIHYPERTENSEURS,
    ASSOCIATIONS_PROSCRITES,
    CLASSES_THERAPEUTIQUES,
    MESURES_BIOLOGIQUES,
    ORDRE_ETAGES,
    classes_therapeutiques_de,
    contraintes_biologiques,
    couvert_par_le_traitement,
    substances_des_classes,
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


#: Le traitement du cas signalé, écrit comme un médecin le saisit.
EN_COURS = ['Bisoprolol 5 mg', 'Sacubitril/Valsartan 49/51 mg',
            'Furosemide 80 mg', 'Spironolactone 25 mg',
            'Empagliflozine 10 mg', 'Apixaban 5 mg']


def med(titre, *substances):
    return {'title': titre, 'substances': list(substances)}


# ── 1. Reconnaître la classe d'une saisie ────────────────────────────────

verifier("le bisoprolol est un bêta-bloquant",
         classes_therapeutiques_de('Bisoprolol 5 mg'), {'betabloquant'})

# Le sacubitril ne se prescrit qu'associé au valsartan : la saisie porte donc
# deux classes, et c'est voulu — proposer un sartan est bien une redondance.
verifier("le sacubitril/valsartan porte ses deux classes",
         classes_therapeutiques_de('Sacubitril/Valsartan 49/51 mg'),
         {'arni', 'sartan'})

verifier("le trandolapril est un IEC",
         classes_therapeutiques_de('ODRIK 2 mg'), set())
verifier("mais sa substance le dit",
         classes_therapeutiques_de('Trandolapril'), {'iec'})

# Le vérapamil et l'amlodipine sont tous deux des inhibiteurs calciques, et
# la distinction décide de tout dans l'insuffisance cardiaque : le premier
# ralentit le cœur et diminue sa force de contraction, le second non.
verifier("le vérapamil est bradycardisant",
         classes_therapeutiques_de('Verapamil'), {'calcique_bradycardisant'})
verifier("l'amlodipine ne l'est pas",
         classes_therapeutiques_de('Amlodipine'),
         {'calcique_dihydropyridine'})

# Les accents ne comptent pas — la reconnaissance passe par `_plier`.
verifier("les accents ne changent rien",
         classes_therapeutiques_de('Furosémide 80 mg'), {'diuretique_anse'})

verifier("une saisie hors du cardiovasculaire ne rend rien",
         classes_therapeutiques_de('Metformine 1000 mg'), set())
verifier("une saisie vide ne rend rien", classes_therapeutiques_de(''), set())
verifier("None ne casse pas", classes_therapeutiques_de(None), set())


# ── 2. Les quatre défauts signalés ───────────────────────────────────────

LOT = [med('TIMACOR 10 mg, comprimé', 'Timolol'),
       med('Visken 5 mg, comprimé', 'Pindolol'),
       med('ODRIK 2 mg, gélule', 'Trandolapril'),
       med('ISOPTINE 120 mg, gélule', 'Vérapamil'),
       med('AMLOR 5 mg, gélule', 'Amlodipine'),
       med('CLAMOXYL 1 g, comprimé', 'Amoxicilline')]

gardes, ecartes = couvert_par_le_traitement(LOT, EN_COURS)
par_nom = {m['title'].split(',')[0]: m for m in ecartes}
restants = {m['title'].split(',')[0] for m in gardes}

verifier("le timolol est écarté : le patient prend déjà un bêta-bloquant",
         'TIMACOR 10 mg' in par_nom, True)
verifier("le pindolol aussi", 'Visken 5 mg' in par_nom, True)
verifier("le trandolapril aussi", 'ODRIK 2 mg' in par_nom, True)
verifier("le vérapamil aussi", 'ISOPTINE 120 mg' in par_nom, True)

# Ce qui ne double rien reste proposé. Un filtre qui écarterait tout ne
# protégerait de rien : il rendrait l'écran vide, pas juste.
verifier("l'amlodipine reste : elle ne double aucune classe en cours",
         'AMLOR 5 mg' in restants, True)
verifier("l'amoxicilline aussi : la table ne connaît pas sa classe",
         'CLAMOXYL 1 g' in restants, True)


# ── 3. Redondance et association ne se confondent pas ────────────────────
#
# Un second bêta-bloquant est *inutile*. Un IEC ajouté à un ARNI est
# *dangereux*. Les deux écartent, mais l'écran ne doit pas les confondre.

verifier("le doublon de classe est une redondance",
         par_nom['TIMACOR 10 mg']['etage_ecart'], 'redondance')
verifier("l'IEC sur ARNI est une association proscrite",
         par_nom['ODRIK 2 mg']['etage_ecart'], 'association')
verifier("le vérapamil sur bêta-bloquant aussi",
         par_nom['ISOPTINE 120 mg']['etage_ecart'], 'association')

# Le motif doit nommer le traitement en cause : « écarté par redondance » sans
# dire avec quoi laisserait le médecin chercher lui-même.
verifier("la redondance nomme le traitement en cause",
         par_nom['TIMACOR 10 mg']['couvert_par']['traitement'],
         'Bisoprolol 5 mg')
verifier("elle nomme la classe partagée",
         'bêta-bloquant' in par_nom['TIMACOR 10 mg']['couvert_par']['classe'],
         True)
verifier("le motif de l'association dit le danger",
         'angio' in par_nom['ODRIK 2 mg']['motif_ecart'].lower(), True)
verifier("et cite le traitement en cours",
         'Sacubitril' in par_nom['ODRIK 2 mg']['motif_ecart'], True)


# ── 4. Sans traitement en cours, rien n'est écarté ───────────────────────

gardes_vide, ecartes_vide = couvert_par_le_traitement(LOT, [])
verifier("aucun traitement saisi : rien n'est écarté", ecartes_vide, [])
verifier("et tout est gardé", len(gardes_vide), len(LOT))
verifier("None ne casse pas", couvert_par_le_traitement(None, EN_COURS),
         ([], []))
verifier("un traitement inconnu de la table n'écarte rien",
         couvert_par_le_traitement(LOT, ['Doliprane 1000 mg'])[1], [])


# ── 5. Les constantes deviennent des règles ──────────────────────────────

for cle in ('systolique', 'diastolique', 'frequence_cardiaque', 'fevg'):
    verifier("la mesure « %s » est déclarée" % cle,
             cle in MESURES_BIOLOGIQUES, True)

CONSTANTES = {'systolique': 96, 'diastolique': 58,
              'frequence_cardiaque': 48, 'fevg': 30}
releve = contraintes_biologiques(CONSTANTES)
libelles = ' | '.join(s['libelle'] for s in releve)

verifier("96 de systolique déclenche la règle d'hypotension",
         'systolique' in libelles, True)
verifier("une FEVG à 30 déclenche la sienne", 'jection' in libelles, True)
verifier("48 battements déclenchent celle de bradycardie",
         'cardiaque' in libelles, True)

# Les valeurs normales ne déclenchent rien : une règle qui se déclencherait
# toujours ne dirait plus rien.
verifier("une pression normale ne déclenche rien",
         contraintes_biologiques({'systolique': 128, 'diastolique': 76}), [])
verifier("une FEVG conservée non plus",
         contraintes_biologiques({'fevg': 60}), [])
verifier("rien de saisi ne déclenche rien", contraintes_biologiques({}), [])
verifier("None ne casse pas", contraintes_biologiques(None), [])

# La règle d'hypotension doit viser les antihypertenseurs, tous.
cibles_pa = next(s for s in releve if 'systolique' in s['libelle'])['cibles']
for substance in ('bisoprolol', 'ramipril', 'valsartan', 'amlodipine',
                  'furosemide', 'trinitrine'):
    verifier("l'hypotension vise le %s" % substance,
             substance in cibles_pa, True)

# Et celle de la FEVG doit viser les inotropes négatifs, eux seuls.
cibles_fevg = next(s for s in releve if 'jection' in s['libelle'])['cibles']
verifier("la FEVG basse vise le vérapamil", 'verapamil' in cibles_fevg, True)
verifier("elle vise la flécaïnide", 'flecainide' in cibles_fevg, True)
verifier("elle ne vise pas l'amlodipine",
         'amlodipine' in cibles_fevg, False)
verifier("ni le bisoprolol, qui se poursuit dans l'insuffisance cardiaque",
         'bisoprolol' in cibles_fevg, False)


# ── 6. La table se tient ─────────────────────────────────────────────────

# Une substance dans deux classes serait une erreur de saisie : la table dit
# à quelle famille une molécule appartient, au singulier. Sauf le sacubitril,
# qui n'y figure qu'une fois — c'est la *saisie* qui porte deux classes.
vues = {}
for cle, classe in CLASSES_THERAPEUTIQUES.items():
    for substance in classe['substances']:
        vues.setdefault(substance, []).append(cle)
verifier("aucune substance n'est dans deux classes",
         {s: c for s, c in vues.items() if len(c) > 1}, {})

verifier("chaque classe porte un libellé lisible",
         [c for c, v in CLASSES_THERAPEUTIQUES.items()
          if not (v.get('libelle') or '').strip()], [])
verifier("aucune substance n'est écrite avec un accent",
         [s for s in vues if any(ord(c) > 127 for c in s)], [])

# Les associations proscrites ne peuvent citer que des classes existantes :
# une faute de frappe rendrait la règle silencieuse au lieu de la casser.
inconnues = [c for regle in ASSOCIATIONS_PROSCRITES for c in regle['classes']
             if c not in CLASSES_THERAPEUTIQUES]
verifier("les associations ne citent que des classes connues", inconnues, [])
verifier("chaque association porte un motif",
         [r for r in ASSOCIATIONS_PROSCRITES if not (r.get('motif') or '').strip()],
         [])

verifier("substances_des_classes met à plat",
         set(substances_des_classes('digitalique')), {'digoxine', 'digitoxine'})
verifier("elle dédoublonne",
         substances_des_classes('digitalique', 'digitalique'),
         substances_des_classes('digitalique'))
verifier("une classe inconnue ne casse pas",
         substances_des_classes('inexistante'), [])
verifier("les antihypertenseurs sont dérivés de la table, pas recopiés",
         set(ANTIHYPERTENSEURS) >= set(substances_des_classes('betabloquant')),
         True)


# ── 7. L'ordre de la chaîne ──────────────────────────────────────────────
#
# Le raisonnement demandé : diagnostic, objectif, traitement en cours,
# redondances, contre-indications, interactions, classement. Un étage qui
# remonterait jugerait sur une information que le précédent n'a pas établie.

source = (Path(__file__).resolve().parent.parent
          / 'prescription_helper.py').read_text(encoding='utf-8')
corps = source[source.index('def appliquer_controles'):]
corps = corps[:corps.index('\ndef ', 10)]

verifier("le traitement en cours est confronté AVANT les antécédents",
         corps.index('couvert_par_le_traitement(')
         < corps.index('appliquer_contraintes('), True)
verifier("et avant les interactions",
         corps.index('couvert_par_le_traitement(')
         < corps.index('check_interactions('), True)
verifier("ses écartés rejoignent le panneau",
         'deja_couverts' in corps, True)

verifier("la redondance précède l'antécédent dans le panneau",
         ORDRE_ETAGES.index('redondance') < ORDRE_ETAGES.index('antecedent'),
         True)
verifier("l'association précède la redondance",
         ORDRE_ETAGES.index('association') < ORDRE_ETAGES.index('redondance'),
         True)

# `normaliser_medicament` reconstruit champ par champ : c'est un filet à
# trous, et il a déjà laissé tomber le rang, la substance annoncée et les
# groupes ATC. `origine` doit y figurer nommément.
normalise = source[source.index('def normaliser_medicament'):]
normalise = normalise[:normalise.index('\ndef ', 10)]
verifier("la normalisation conserve l'origine du candidat",
         "'origine'" in normalise, True)


# ── Relevé ───────────────────────────────────────────────────────────────

print()
print("  Classes du traitement en cours :")
for saisie in EN_COURS:
    print("    %-32s %s" % (saisie, sorted(classes_therapeutiques_de(saisie))))
print()
print("  Écartés par le traitement en cours :")
for m in ecartes:
    print("    %-26s [%s]" % (m['title'][:26], m['etage_ecart']))
print("  Gardés : %s" % sorted(restants))
print()
print("  Constantes 96/58, FC 48, FEVG 30 :")
for s in releve:
    print("    - %s" % s['libelle'])

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
