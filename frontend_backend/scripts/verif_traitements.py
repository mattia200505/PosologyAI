"""Banc du découpage et de la reconnaissance des traitements en cours.

Ce que ce banc garde
--------------------
Le médecin écrit ses traitements en clair, et il n'écrit pas une liste : il
écrit des phrases.

    Ventoline en inhalation si besoin. Cétirizine 10 mg pendant les
    périodes allergiques.

Aucun des deux n'était reconnu, pour deux raisons superposées :

1. **Le découpage ne connaissait que la virgule.** La saisie entière devenait
   un seul traitement, et ce traitement-là ne ressemblait à rien.
2. **La prose n'était pas retirée.** `_POSOLOGIE` est une liste fermée de mots
   — soir, matin, comprimé, inhalation. Elle retire « inhalation » et laisse
   « en si besoin ». Une liste blanche ne peut pas couvrir de la prose libre.

Le nom du médicament est en tête de la saisie : le reste décrit la prise. Les
formes candidates partent donc des **préfixes de mots**, du plus long au plus
court.

Le piège à ne pas rouvrir
-------------------------
Rendre le rapprochement plus permissif rouvre le défaut du § 2.4 du rapport,
où le repli attribuait à un médicament les interactions d'une autre molécule.
Mesuré pendant l'enquête, avec `CONTAINS` :

    « cetirizine »        -> LEVOCETIRIZINE EG      -> Levocetirizine
    « insuline glargine » -> INSULIN LISPRO         -> Insulin lispro

Deux molécules différentes de celles saisies. D'où deux règles, que ce banc
tient :

- le catalogue français se cherche par **début de titre**, pas par sous-chaîne ;
- les règles de suffixe qui anglicisent un nom ne servent qu'à la substance
  DrugBank, jamais au titre français.

Emploi
------
    python scripts/verif_traitements.py

Sans base : les fonctions éprouvées ici sont pures. La résolution contre le
graphe est couverte par `verif_affichage.js` sur la capture.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from prescription_helper import (  # noqa: E402
    decouper_traitements,
    formes_candidates,
    formes_specialite,
)

_reussis = 0
_echecs = []


def verifier(intitule: str, obtenu, attendu=None) -> None:
    global _reussis
    ok = (obtenu == attendu) if attendu is not None else bool(obtenu)
    if ok:
        _reussis += 1
    else:
        _echecs.append("%s\n      obtenu : %r\n      attendu: %r"
                       % (intitule, obtenu, attendu))


# ── 1. Le découpage ──────────────────────────────────────────────────────

verifier("la virgule sépare, comme avant",
         decouper_traitements("Ramipril 10 mg, Metformine 850 mg"),
         ['Ramipril 10 mg', 'Metformine 850 mg'])

# Le cas signalé : deux phrases, aucune virgule entre elles.
verifier("le point sépare deux phrases",
         decouper_traitements("Ventoline en inhalation si besoin. "
                              "Cétirizine 10 mg pendant les périodes allergiques."),
         ['Ventoline en inhalation si besoin',
          'Cétirizine 10 mg pendant les périodes allergiques'])

verifier("le point-virgule sépare",
         decouper_traitements("Ramipril 10 mg ; Metformine 850 mg"),
         ['Ramipril 10 mg', 'Metformine 850 mg'])

verifier("le retour à la ligne sépare",
         decouper_traitements("Ramipril 10 mg\nMetformine 850 mg"),
         ['Ramipril 10 mg', 'Metformine 850 mg'])

# La virgule décimale française : « 0,5 mg » n'est pas deux traitements.
verifier("la virgule décimale ne sépare pas",
         decouper_traitements("Ventoline 0,5 mg"),
         ['Ventoline 0,5 mg'])

verifier("le point décimal ne sépare pas",
         decouper_traitements("Digoxine 0.25 mg"),
         ['Digoxine 0.25 mg'])

verifier("une saisie vide rend une liste vide", decouper_traitements(''), [])
verifier("None rend une liste vide", decouper_traitements(None), [])
verifier("les séparateurs seuls ne fabriquent pas de traitement",
         decouper_traitements(" , . ; "), [])

verifier("la liste est bornée",
         len(decouper_traitements(', '.join('Med%d 1 mg' % i for i in range(40)))),
         20)


# ── 2. Les formes cherchées côté substance DrugBank ──────────────────────

def anglaises(saisie):
    return formes_candidates(saisie)


# Non-régression : ce qui marchait doit continuer de marcher.
verifier("« Warfarine 5 mg » propose warfarin",
         'warfarin' in anglaises('Warfarine 5 mg'), True)
verifier("« Metformine 850 mg » propose metformin",
         'metformin' in anglaises('Metformine 850 mg'), True)
verifier("« Amoxicilline 500 mg » propose amoxicillin",
         'amoxicillin' in anglaises('Amoxicilline 500 mg'), True)

# Le cas signalé : la prose ne doit plus empêcher la reconnaissance.
verifier("la prose n'empêche plus de proposer cetirizine",
         'cetirizine' in anglaises('Cétirizine 10 mg pendant les périodes allergiques'),
         True)
verifier("« si besoin » n'empêche plus de proposer ventoline",
         'ventoline' in anglaises('Ventoline en inhalation si besoin'), True)
verifier("la posologie en fin de phrase ne gêne pas",
         'amoxicillin' in anglaises('Amoxicilline 500 mg 3 fois par jour'), True)

verifier("les formes vont du plus long au plus court",
         anglaises('Doliprane 1000 mg si douleur')[0].count(' ')
         >= anglaises('Doliprane 1000 mg si douleur')[-1].count(' '), True)

verifier("une saisie trop courte ne propose rien", anglaises('ok'), [])
verifier("une saisie vide ne propose rien", anglaises(''), [])


# ── 3. Les formes cherchées côté titre du catalogue ──────────────────────

verifier("le titre se cherche sur la forme française",
         'ventoline' in formes_specialite('Ventoline en inhalation si besoin'), True)

# Les règles de suffixe anglicisent : elles n'ont rien à faire sur un titre
# français. « insuline » y devenait « insulin », qui se trouve à l'intérieur
# de INSULIN LISPRO.
verifier("aucune forme anglicisée ne part vers le catalogue français",
         'insulin' in formes_specialite('insuline glargine 20 UI le soir'), False)
verifier("aucune forme anglicisée, même sur un nom courant",
         'warfarin' in formes_specialite('Warfarine 5 mg'), False)

verifier("le catalogue reçoit bien la forme entière et ses préfixes",
         formes_specialite('insuline glargine 20 UI le soir')[0], 'insuline glargine')

# Un préfixe trop court rencontrerait trop de titres.
for forme in formes_specialite('Kardegic 75 mg le matin'):
    verifier("la forme « %s » est assez longue pour un titre" % forme,
             len(forme) >= 4, True)

verifier("les préfixes du catalogue vont du plus long au plus court",
         formes_specialite('Doliprane 1000 mg si douleur'),
         sorted(formes_specialite('Doliprane 1000 mg si douleur'),
                key=len, reverse=True))


# ── 4. La route emploie bien le nouveau découpage ────────────────────────

source = (Path(__file__).resolve().parent.parent / 'prescription_helper.py').read_text(
    encoding='utf-8')
verifier("la route appelle decouper_traitements",
         'decouper_traitements(' in source, True)
verifier("la route ne découpe plus à la virgule seule",
         ".split(',') if data.get('medicaments_actuels')" in source, False)
verifier("le catalogue se cherche par début de titre",
         'STARTS WITH' in source, True)
verifier("le catalogue ne se cherche plus par sous-chaîne",
         'CONTAINS f' in source, False)


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
