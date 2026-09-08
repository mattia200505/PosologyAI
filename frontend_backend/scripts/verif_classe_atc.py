"""Banc du filtre par classe ATC — phase P3 de la roadmap.

Ce que ce banc garde
--------------------
P3 retourne la chaîne. Jusqu'ici, sur la prescription par diagnostic, **le
modèle choisissait 2 à 4 médicaments parmi 20 candidats bruts, avant qu'aucune
règle ne se soit prononcée**. La note arrivait après : elle constatait, elle ne
décidait pas.

Désormais la règle constitue le vivier, et le modèle n'intervient qu'à
l'intérieur.

Deux marqueurs, indépendants du diagnostic
------------------------------------------
La projection de P2 rend interrogeables deux groupes ATC qui suffisent, à eux
seuls, à dire qu'un produit n'est pas un traitement d'indication :

    V04   agents diagnostiques      — HELIKIT, test respiratoire à l'urée
    B05   solutions de perfusion    — bicarbonate, solutés d'irrigation

Ils ne demandent aucune connaissance du diagnostic. C'est ce qui les rend sûrs
et les place ici plutôt qu'en P5.

Ce que ce banc ne peut pas encore garder
----------------------------------------
Le critère de sortie de P3 exige aussi que **l'adrénaline soit écartée pour une
pneumonie**. Ses groupes ATC — A01, B02, C01, R01, R03, S01 — sont tous
thérapeutiques et légitimes : l'écarter suppose de savoir qu'une pneumonie
appelle J01, c'est-à-dire la table diagnostic → ATC, livrable de **P5**.

**P5 dépend de P3 : la dépendance est circulaire.** Le point est signalé et
laissé ouvert ; ce banc ne prétend pas le couvrir.

Emploi
------
    python scripts/verif_classe_atc.py

Neo4j est nécessaire : les groupes ATC y sont lus.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from prescription_helper import (  # noqa: E402
    GROUPES_NON_THERAPEUTIQUES,
    filtrer_par_classe,
    groupes_atc_des,
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


# ── 1. La table des groupes non thérapeutiques ───────────────────────────

verifier("la table nomme le groupe des agents diagnostiques",
         'V04' in GROUPES_NON_THERAPEUTIQUES, True)
verifier("elle nomme le groupe des solutions de perfusion",
         'B05' in GROUPES_NON_THERAPEUTIQUES, True)
verifier("elle reste courte — deux groupes, pas une liste d'exclusion",
         len(GROUPES_NON_THERAPEUTIQUES) <= 3, True)
for groupe, motif in GROUPES_NON_THERAPEUTIQUES.items():
    verifier("le groupe %s porte un motif lisible" % groupe,
             len(motif) > 15, True)


# ── 2. Le tri, sur des groupes fournis d'avance ──────────────────────────

def med(titre, groupes):
    """Un candidat dont les groupes ATC sont déjà connus : le filtre ne relit
    alors rien, et la fonction s'éprouve sans base."""
    return {'title': titre, 'groupes_atc': set(groupes)}


lot = [
    med('HELIKIT 75 mg', ['V04']),
    med('BICARBONATE DE SODIUM 8,4%', ['B05']),
    med('AMOXICILLINE ARROW 1 g', ['A02', 'J01']),
    med('ZITHROMAX 40 mg/mL', ['J01', 'S01']),
    med('GLUCOSE 2,5 %', []),
]
retenus, ecartes = filtrer_par_classe(lot)

verifier("HELIKIT est écarté — agent diagnostique",
         'HELIKIT 75 mg' in [m['title'] for m in ecartes], True)
verifier("le bicarbonate est écarté — solution de perfusion",
         'BICARBONATE DE SODIUM 8,4%' in [m['title'] for m in ecartes], True)

verifier("les antibiotiques restent",
         sorted(m['title'] for m in retenus if 'J01' in m['groupes_atc']),
         ['AMOXICILLINE ARROW 1 g', 'ZITHROMAX 40 mg/mL'])

# L'absence d'ATC déclasse, elle n'exclut pas. C'est la parade inscrite au
# § 7.3 : 148 substances du graphe n'ont pas de code, et les écarter
# reviendrait à punir un défaut de couverture.
verifier("un produit sans ATC est retenu, pas écarté",
         'GLUCOSE 2,5 %' in [m['title'] for m in retenus], True)
verifier("mais il est marqué comme déclassé",
         next(m for m in retenus if m['title'] == 'GLUCOSE 2,5 %')
         .get('sans_classe'), True)
verifier("et il passe derrière ceux qui portent une classe",
         [m['title'] for m in retenus][-1], 'GLUCOSE 2,5 %')

verifier("chaque écarté porte son motif",
         all(m.get('hors_classe_car') for m in ecartes), True)

verifier("une liste vide ne casse pas", filtrer_par_classe([]), ([], []))
verifier("None ne casse pas", filtrer_par_classe(None), ([], []))


# ── 3. Un groupe attendu, quand l'appelant en fournit ────────────────────

# La table diagnostic → ATC est le livrable de P5. Le paramètre existe déjà et
# est éprouvé ici, mais **aucun appelant ne le renseigne** : P3 ne prétend pas
# faire P5.
retenus2, ecartes2 = filtrer_par_classe(lot, attendues={'J01'})
verifier("avec J01 attendu, seuls les antibiotiques sont retenus",
         sorted(m['title'] for m in retenus2 if not m.get('sans_classe')),
         ['AMOXICILLINE ARROW 1 g', 'ZITHROMAX 40 mg/mL'])
verifier("le produit sans ATC reste retenu même avec une attente",
         'GLUCOSE 2,5 %' in [m['title'] for m in retenus2], True)

adrenaline = med('ADRENALINE RENAUDIN', ['A01', 'B02', 'C01', 'R01', 'R03', 'S01'])
r3, e3 = filtrer_par_classe([adrenaline], attendues={'J01'})
verifier("l'adrénaline serait écartée si le diagnostic disait J01 "
         "(ce que seule P5 permettra)",
         [m['title'] for m in e3], ['ADRENALINE RENAUDIN'])
r4, e4 = filtrer_par_classe([adrenaline])
verifier("sans attente, l'adrénaline est retenue — P3 ne peut pas trancher",
         [m['title'] for m in r4], ['ADRENALINE RENAUDIN'])


# ── 4. L'inversion de l'ordre ────────────────────────────────────────────

racine = Path(__file__).resolve().parent.parent
app = (racine / 'app.py').read_text(encoding='utf-8')

verifier("la chaîne par diagnostic filtre par classe",
         'filtrer_par_classe(' in app, True)


def corps(source: str, entete: str) -> str:
    """Rend le corps d'une fonction, jusqu'à la suivante."""
    debut = source.index(entete)
    suite = source.find('\ndef ', debut + len(entete))
    return source[debut:suite if suite != -1 else len(source)]


# Le point capital de P3 : le filtre doit précéder l'appel au modèle. Placé
# après, il ne ferait que constater ce que le modèle a déjà choisi.
#
# Ce contrôle comparait des positions dans le fichier. Mauvais indicateur : il
# a échoué le jour où le filtre a déménagé dans `search_medications_for_diagnostic`
# — qui est définie plus bas dans le source, mais s'exécute plus tôt. C'est
# l'ordre d'exécution qui compte, et il se lit dans les corps de fonction.
route = corps(app, 'def analyze_diagnostic_for_prescription():')
verifier("la route constitue le vivier avant d'appeler le modèle",
         route.index('search_medications_for_diagnostic(')
         < route.index('generate_ai_prescription_suggestions('), True)

generation = corps(app, 'def search_medications_for_diagnostic(')
verifier("le vivier est filtré par classe avant d'être rendu",
         generation.index('filtrer_par_classe(')
         < generation.rindex('return relevant_meds'), True)
verifier("l'éligibilité est appliquée avant le filtre par classe",
         generation.index('filtrer_eligibilite(')
         < generation.index('filtrer_par_classe('), True)

helper = (racine / 'prescription_helper.py').read_text(encoding='utf-8')
verifier("les groupes sont relus en une seule requête",
         'UNWIND $identifiants' in helper or '$in' in helper, True)


# ── 5. Contre la base ────────────────────────────────────────────────────

try:
    reels = groupes_atc_des(['helikit', 'amoxicilline'])
    verifier("la lecture des groupes rend un dictionnaire",
             isinstance(reels, dict), True)
except Exception as err:
    _echecs.append("lecture des groupes : %s" % str(err)[:70])


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
