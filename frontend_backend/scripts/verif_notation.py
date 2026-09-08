"""Banc de la notation de pertinence clinique.

Ce que ce banc garde
--------------------
`compute_clinical_relevance` accordait **+55 à toute marque reconnue dans le
titre**, sans jamais vérifier que sa catégorie avait le moindre rapport avec
les symptômes saisis. Mesuré sur « toux sèche, gêne respiratoire,
éternuements » :

    VENTOLINE   55   Pertinent pour: bronchodilatateur
    DEBRIDAT    55   Pertinent pour: antispasmodique
    FORLAX      55   Pertinent pour: laxatif

Un laxatif valait un bronchodilatateur pour une toux, et l'écran écrivait
« Pertinent pour: laxatif » sans que rien ne signale l'absurdité. C'est ce qui
faisait proposer DEBRIDAT — un antispasmodique intestinal — à un asthmatique
qui tousse.

La correction : le bonus de marque n'est accordé que si sa catégorie figure
parmi les classes que `SYMPTOM_CLASS_MAP` associe aux symptômes présents.

Le rapprochement se fait par **inclusion dans un sens ou dans l'autre** :
`BRAND_MAP` dit « anti-inflammatoire » là où `SYMPTOM_CLASS_MAP` dit
« anti-inflammatoire non stéroïdien ». Exiger l'égalité écarterait l'ibuprofène
d'une fièvre, ce qui serait pire que le défaut corrigé.

Emploi
------
    python scripts/verif_notation.py

Aucune base n'est nécessaire.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from prescription_helper import (  # noqa: E402
    BRAND_MAP,
    CATEGORIES_NON_SYMPTOMATIQUES,
    SYMPTOM_CLASS_MAP,
    classes_attendues,
    compute_clinical_relevance,
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


def note(symptomes: str, titre: str) -> int:
    return compute_clinical_relevance(symptomes, {'title': titre})[0]


def justification(symptomes: str, titre: str) -> str:
    return compute_clinical_relevance(symptomes, {'title': titre})[1]


TOUX = "Toux seche depuis 3 jours, gene respiratoire a l'effort, eternuements"
DOULEUR = "Douleur lombaire intense depuis 2 jours"
FIEVRE = "Fievre a 38,7 C depuis 48 heures"
NAUSEE = "Nausees et vomissements depuis ce matin"
CONSTIPATION = "Constipation depuis 5 jours"


# ── 1. Le cas signalé ────────────────────────────────────────────────────

verifier("un bronchodilatateur reste pertinent pour une toux",
         note(TOUX, 'VENTOLINE 100 microgrammes/dose') > 0, True)

# Les deux médicaments qui n'avaient rien à faire là.
verifier("un antispasmodique intestinal n'est plus pertinent pour une toux",
         note(TOUX, 'DEBRIDAT, granules pour suspension buvable'), 0)
verifier("un laxatif n'est plus pertinent pour une toux",
         note(TOUX, 'FORLAX 10 g, poudre'), 0)

verifier("et l'écran ne dit plus « Pertinent pour: laxatif » à propos d'une toux",
         'laxatif' in justification(TOUX, 'FORLAX 10 g, poudre'), False)


# ── 2. Non-régression : ce qui est pertinent doit le rester ──────────────

verifier("un antalgique reste pertinent pour une douleur",
         note(DOULEUR, 'DOLIPRANE 1000 mg, comprime') > 0, True)
verifier("un laxatif redevient pertinent pour une constipation",
         note(CONSTIPATION, 'FORLAX 10 g, poudre') > 0, True)
verifier("un antiémétique reste pertinent pour des nausées",
         note(NAUSEE, 'MOTILIUM 10 mg, comprime') > 0, True)

# BRAND_MAP dit « anti-inflammatoire », SYMPTOM_CLASS_MAP dit
# « anti-inflammatoire non stéroïdien ». Exiger l'égalité écarterait
# l'ibuprofène d'une fièvre.
verifier("un anti-inflammatoire reste pertinent pour une fièvre",
         note(FIEVRE, 'ADVIL 200 mg, comprime enrobe') > 0, True)
verifier("un antalgique reste pertinent pour une fièvre",
         note(FIEVRE, 'DOLIPRANE 1000 mg, comprime') > 0, True)


# ── 3. Les classes attendues, isolément ─────────────────────────────────

verifier("une toux appelle un bronchodilatateur",
         'bronchodilatateur' in classes_attendues(TOUX), True)
verifier("une toux n'appelle pas d'antispasmodique",
         'antispasmodique' in classes_attendues(TOUX), False)
verifier("une constipation appelle un laxatif",
         'laxatif' in classes_attendues(CONSTIPATION), True)
verifier("des symptômes vides n'appellent aucune classe",
         classes_attendues(''), set())
verifier("None ne casse pas", classes_attendues(None), set())

verifier("un symptôme inconnu n'appelle aucune classe",
         classes_attendues('Sensation etrange non decrite'), set())


# ── 4. Toute catégorie symptomatique reste atteignable ──────────────────

# Une catégorie qu'aucun symptôme n'appelle est morte : la marque ne peut plus
# jamais marquer de point. Le durcissement de la notation en a rendu cinq
# inatteignables d'un coup — SPASFON, STREPSILS et DAFLON étaient devenus
# improposables. Trois ont reçu leurs symptômes ; les deux autres ne répondent
# à aucun symptôme et sont nommées dans CATEGORIES_NON_SYMPTOMATIQUES.
symptomes_connus = ' '.join(SYMPTOM_CLASS_MAP.keys())
atteignables = classes_attendues(symptomes_connus)
inatteignables = {c for c in BRAND_MAP.values()
                  if not any(c in a or a in c for a in atteignables)}

verifier("les seules catégories inatteignables sont celles qu'on a décidé de "
         "ne pas déduire d'un symptôme",
         sorted(inatteignables), sorted(CATEGORIES_NON_SYMPTOMATIQUES))

verifier("un antispasmodique est proposable pour une colique",
         note("Coliques abdominales depuis hier", 'SPASFON, comprime') > 0, True)
verifier("un antiseptique est proposable pour un mal de gorge",
         note("Mal de gorge et fievre", 'STREPSILS, pastille') > 0, True)
verifier("un veinotonique est proposable pour des jambes lourdes",
         note("Jambes lourdes en fin de journee", 'DAFLON 500 mg') > 0, True)

# Et le cas signalé reste corrigé : DEBRIDAT est un antispasmodique, il
# redevient pertinent pour une colique, jamais pour une toux.
verifier("DEBRIDAT redevient pertinent pour une colique",
         note("Coliques abdominales depuis hier",
              'DEBRIDAT, granules pour suspension buvable') > 0, True)
verifier("DEBRIDAT reste écarté pour une toux",
         note(TOUX, 'DEBRIDAT, granules pour suspension buvable'), 0)


# ── 5. Le paramètre et la forme de retour n'ont pas bougé ───────────────

verifier("la note reste bornée à 100",
         note(FIEVRE, 'DOLIPRANE 1000 mg') <= 100, True)
verifier("un titre vide ne casse pas", note(FIEVRE, ''), 0)
verifier("une justification est toujours rendue",
         isinstance(justification(TOUX, 'VENTOLINE 100 microgrammes'), str), True)


# ── Relevé ───────────────────────────────────────────────────────────────

print()
print("  Notation sur « %s » :" % TOUX[:46])
for titre in ['VENTOLINE 100 microgrammes/dose',
              'DEBRIDAT, granules pour suspension buvable',
              'FORLAX 10 g, poudre']:
    n, j = compute_clinical_relevance(TOUX, {'title': titre})
    print("    %-44s %3d  %s" % (titre[:44], n, j))

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
