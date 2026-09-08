"""Banc des contraintes d'antécédents.

Ce que ce banc garde
--------------------
Les antécédents n'étaient qu'un texte libre transmis au modèle : « insuffisance
rénale » figurait dans une phrase de l'invite et n'interdisait rien. Une table
de règles curatée les rend contraignants, et ce banc tient les deux bouts :

- la règle **écarte** ce qu'elle vise, sinon elle ne sert à rien ;
- la règle n'écarte **que** ce qu'elle vise, sinon elle est pire que rien.

Le second point est celui qui a déjà coûté cher au projet. « insuffisance »
seule rencontrait « insuffisance hépatique sévère » chez une patiente dont
l'insuffisance est rénale, et « anti » attrapait « ORGARAN 750 U.I. anti-Xa ».
Un rapprochement trop large ne se voit pas : il écarte en silence.

Emploi
------
    python scripts/verif_contraintes.py

Aucune base n'est nécessaire : les fonctions éprouvées ici sont pures.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from prescription_helper import (  # noqa: E402
    CONTRAINTES_ANTECEDENTS,
    appliquer_contraintes,
    contraintes_actives,
    compute_clinical_relevance,
)

_reussis = 0
_echecs = []


def verifier(intitule: str, condition, attendu=None) -> None:
    global _reussis
    ok = (condition == attendu) if attendu is not None else bool(condition)
    if ok:
        _reussis += 1
    else:
        _echecs.append("%s\n      obtenu : %r\n      attendu: %r"
                       % (intitule, condition, attendu))


def med(titre: str, substances=None, score: int = 80) -> dict:
    """Un médicament sous la forme que `normaliser_medicament()` produit."""
    return {
        'id': titre.lower().replace(' ', '-'),
        'title': titre,
        'substances': substances or [],
        'forme': '',
        'relevance_score': score,
    }


def noms(medicaments) -> list:
    return sorted(m['title'] for m in medicaments)


# ── 1. La table elle-même ────────────────────────────────────────────────

verifier("la table n'est pas vide", len(CONTRAINTES_ANTECEDENTS) > 0)

for regle in CONTRAINTES_ANTECEDENTS:
    nom = regle.get('libelle', '?')
    verifier("« %s » porte des expressions de reconnaissance" % nom,
             bool(regle.get('antecedent')))
    verifier("« %s » porte des cibles" % nom, bool(regle.get('cibles')))
    verifier("« %s » porte un motif écrit" % nom,
             bool((regle.get('motif') or '').strip()))
    # Une cible courte rencontre trop de mots par hasard : « ains » se trouve
    # dans « certains », « anti » dans « anti-Xa ». Le projet s'est déjà fait
    # prendre deux fois.
    for cible in regle['cibles']:
        verifier("cible « %s » assez longue pour ne pas rencontrer un mot au hasard"
                 % cible, len(cible) >= 6)


# ── 2. Reconnaissance de l'antécédent ────────────────────────────────────

def libelles(saisie: str) -> list:
    return sorted(r['libelle'] for r in contraintes_actives(saisie))


verifier("une saisie vide ne déclenche rien", libelles(''), [])
verifier("None ne déclenche rien et ne casse pas", libelles(None), [])

verifier("« insuffisance rénale légère » déclenche la règle rénale",
         'insuffisance rénale' in libelles('Insuffisance rénale légère'), True)

verifier("l'accent n'est pas requis",
         'insuffisance rénale' in libelles('insuffisance renale'), True)

# Le piège du § 2.8, transposé aux règles.
verifier("« insuffisance hépatique sévère » ne déclenche PAS la règle rénale",
         'insuffisance rénale' in libelles('Insuffisance hépatique sévère'), False)

verifier("« insuffisance rénale » ne déclenche pas la règle hépatique",
         'insuffisance hépatique' in libelles('Insuffisance rénale légère'), False)

# Les mots d'une expression doivent tenir dans le MÊME segment : deux
# antécédents distincts ne se recombinent pas en un troisième.
verifier("« insuffisance cardiaque, atteinte rénale » ne fabrique pas la règle rénale",
         'insuffisance rénale' in libelles('Insuffisance cardiaque, atteinte rénale'),
         False)

verifier("plusieurs antécédents déclenchent plusieurs règles",
         len(contraintes_actives('Asthme, ulcère gastroduodénal')) >= 2, True)

verifier("un antécédent sans règle ne déclenche rien",
         libelles('Appendicectomie en 2019'), [])


# ── 3. Application aux médicaments ───────────────────────────────────────

liste = [
    med('IBUPROFENE ZYDUS 200 mg, comprimé', ['Ibuprofène'], 95),
    med('DOLIPRANE 1000 mg, comprimé', ['Paracétamol'], 90),
    med('AMOXICILLINE ARROW 500 mg', ['Amoxicilline'], 85),
]

retenus, ecartes = appliquer_contraintes(liste, 'Insuffisance rénale légère')
verifier("l'ibuprofène est écarté chez l'insuffisant rénal",
         noms(ecartes), ['IBUPROFENE ZYDUS 200 mg, comprimé'])
verifier("le paracétamol et l'amoxicilline sont retenus",
         noms(retenus),
         ['AMOXICILLINE ARROW 500 mg', 'DOLIPRANE 1000 mg, comprimé'])

verifier("l'écarté porte la règle qui l'a écarté",
         bool(ecartes[0].get('ecarte_par')), True)
verifier("l'écarté nomme l'antécédent en cause",
         ecartes[0]['ecarte_par']['antecedent'], 'insuffisance rénale')
verifier("l'écarté porte un motif lisible",
         len(ecartes[0]['ecarte_par']['motif']) > 10, True)

# Le rapprochement porte sur la substance, pas seulement sur le titre : c'est
# la leçon du § 2.3, où « Warfarine » ne correspondait à aucun titre.
par_substance, _ = appliquer_contraintes(
    [med('ADVIL 200 mg', ['Ibuprofène'])], 'Insuffisance rénale')
verifier("un titre de marque est écarté par sa substance", par_substance, [])

# Précision : un antécédent non déclenché ne doit rien écarter.
retenus2, ecartes2 = appliquer_contraintes(liste, 'Appendicectomie en 2019')
verifier("un antécédent sans règle laisse la liste entière",
         len(retenus2), 3)
verifier("un antécédent sans règle n'écarte rien", ecartes2, [])

retenus3, ecartes3 = appliquer_contraintes(liste, '')
verifier("sans antécédent, rien n'est écarté", len(retenus3), 3)

verifier("une liste vide ne casse pas",
         appliquer_contraintes([], 'Insuffisance rénale'), ([], []))

# Le cas où tout part : l'écran ne doit pas se retrouver muet sans le savoir.
tout, rien = appliquer_contraintes(
    [med('IBUPROFENE ZYDUS 200 mg', ['Ibuprofène'])], 'Insuffisance rénale')
verifier("quand tout est écarté, la liste retenue est vide", tout, [])
verifier("quand tout est écarté, les écartés sont tous là", len(rien), 1)

# L'allergie aux pénicillines, sur le même jeu.
_, ecartes4 = appliquer_contraintes(liste, 'Allergie à la pénicilline')
verifier("l'amoxicilline est écartée en cas d'allergie aux pénicillines",
         noms(ecartes4), ['AMOXICILLINE ARROW 500 mg'])

# Deux antécédents qui écartent deux médicaments distincts.
retenus5, ecartes5 = appliquer_contraintes(
    liste, 'Insuffisance rénale, allergie à la pénicilline')
verifier("deux antécédents écartent deux médicaments",
         noms(ecartes5),
         ['AMOXICILLINE ARROW 500 mg', 'IBUPROFENE ZYDUS 200 mg, comprimé'])
verifier("le paracétamol survit aux deux", noms(retenus5),
         ['DOLIPRANE 1000 mg, comprimé'])

# Non-régression sur le faux positif de vocabulaire : aucune cible ne doit
# être trouvée dans un mot qui la contient par hasard.
_, pieges = appliquer_contraintes(
    [med('ORGARAN 750 U.I. anti-Xa'), med('CERTAINS PRODUITS')],
    'Insuffisance rénale, asthme, ulcère gastroduodénal')
verifier("aucun médicament n'est écarté par un fragment de mot", pieges, [])

# L'ordre d'entrée est préservé, dans les deux listes. La route trie par score
# à l'étape 5 bis, juste avant d'appeler : retrier ici serait redondant, mais
# défaire cet ordre ramènerait la suite inexplicable que le § 2.8 avait déjà
# vue à l'écran — 95, 90, 80, 75, 95, 80.
entree = [med('A', ['Paracétamol'], 95), med('B', ['Ibuprofène'], 90),
          med('C', ['Paracétamol'], 85), med('D', ['Ibuprofène'], 70)]
gardes, sortis = appliquer_contraintes(entree, 'Insuffisance rénale')
verifier("l'ordre d'entrée est préservé chez les retenus",
         [m['relevance_score'] for m in gardes], [95, 85])
verifier("l'ordre d'entrée est préservé chez les écartés",
         [m['relevance_score'] for m in sortis], [90, 70])


# ── 4. Le paramètre mort a bien disparu ──────────────────────────────────

import inspect  # noqa: E402

parametres = list(inspect.signature(compute_clinical_relevance).parameters)
verifier("compute_clinical_relevance ne prend plus d'antécédents",
         'antecedents' in parametres, False)

source = (Path(__file__).resolve().parent.parent / 'prescription_helper.py').read_text(
    encoding='utf-8')
verifier("la route appelle appliquer_contraintes",
         'appliquer_contraintes(' in source, True)


# ── Relevé ───────────────────────────────────────────────────────────────

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
