"""Banc de la notation par classe et du seuil d'exclusion — phase P4.

Ce que ce banc garde
--------------------

**Deux grandeurs partageaient un nom.** `relevance_score` portait tantôt une
similarité cosinus Qdrant sur 0,20–1,00, tantôt une note clinique sur 0–100. Un
tri ou un seuil appliqué sans savoir laquelle des deux on lit produit un
résultat qui *paraît* juste. Elles s'appellent désormais `similarite` et
`pertinence`.

**La note ignorait ce que le système savait.** Depuis P2 le graphe porte la
classification ATC, et depuis P3b la chaîne s'en sert pour *générer* — mais la
notation continuait de lire des tables textuelles qui ne connaissent ni
« BURINEX » ni « DALACINE ».

Mesuré avant cette phase, en appliquant le seuil tel quel :

    pneumonie communautaire   17 candidats sur 20 sous le seuil, 11 justes perdus
    décompensation cardiaque  19 sur 20, **la totalité des justes perdue**
    cystite aiguë             19 sur 20, 6 justes perdus

P4 aurait supprimé exactement ce que P3b venait de produire. La note tient donc
compte de la classe ATC avant que le seuil ne s'applique.

**Le seuil décide.** Un candidat sous le seuil quitte les propositions et
rejoint les écartés, avec sa note. Rien ne disparaît : tout change de panneau.

Emploi
------
    python scripts/verif_seuil.py

Aucune base n'est nécessaire.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from prescription_helper import (  # noqa: E402
    PALIERS_PERTINENCE,
    SEUIL_EXCLUSION,
    compute_clinical_relevance,
    palier_de,
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


def note(contexte, titre, groupes=None, substances=None):
    med = {'title': titre, 'substances': substances or []}
    if groupes is not None:
        med['groupes_atc'] = set(groupes)
    return compute_clinical_relevance(contexte, med)[0]


PNEUMONIE = "Pneumonie communautaire du lobe inferieur droit, forme non severe"
DECOMP = "Decompensation aigue d insuffisance cardiaque chronique"


# ── 1. La classe ATC compte désormais dans la note ───────────────────────

# Les cas mesurés : la notation textuelle leur donnait zéro.
verifier("ERY 500 mg, macrolide, est noté pour une pneumonie",
         note(PNEUMONIE, 'ERY 500 mg, comprimé', ['J01']) >= SEUIL_EXCLUSION, True)
verifier("DALACINE l'est aussi",
         note(PNEUMONIE, 'DALACINE 75 mg, gélule', ['J01']) >= SEUIL_EXCLUSION, True)
verifier("BURINEX, diurétique, est noté pour une décompensation",
         note(DECOMP, 'BURINEX 1 mg, comprimé', ['C03']) >= SEUIL_EXCLUSION, True)

# Et la précision tient : une classe hors sujet ne rapporte rien.
verifier("un antihypertenseur n'est pas noté pour une pneumonie",
         note(PNEUMONIE, 'COVERAM 10 mg, comprimé', ['C09', 'C10']), 0)
verifier("un antibiotique n'est pas noté pour une décompensation",
         note(DECOMP, 'DALACINE 75 mg, gélule', ['J01']), 0)

# Sans classe connue, la note reste celle des tables textuelles : l'absence
# d'ATC ne retire rien, elle n'ajoute simplement pas.
verifier("sans classe, un antalgique connu garde sa note textuelle",
         note("Fievre a 38,7 C", 'DOLIPRANE 1000 mg', []) > 0, True)
verifier("sans classe et sans nom connu, la note reste nulle",
         note(PNEUMONIE, 'PRODUIT INCONNU 5 mg', []), 0)

# La classe seule ne suffit pas à atteindre le palier haut : elle dit que le
# candidat est du bon rayon, pas qu'il est le bon choix.
verifier("la classe seule place au palier « retenu, déclassé »",
         palier_de(note(PNEUMONIE, 'ERY 500 mg, comprimé', ['J01'])),
         'retenu_declasse')

# Le cumul, lui, monte : classe attendue et molécule reconnue.
verifier("classe et molécule reconnues montent au palier haut",
         palier_de(note(PNEUMONIE, 'CLAMOXYL 500 mg, gélule', ['J01'],
                        ['Amoxicilline'])), 'retenu')


# ── 2. Les paliers ───────────────────────────────────────────────────────

verifier("le seuil d'exclusion vaut 40", SEUIL_EXCLUSION, 40)
verifier("quatre paliers sont définis", len(PALIERS_PERTINENCE), 4)

for valeur, attendu in [(0, 'exclu'), (1, 'exclu'), (39, 'exclu'),
                        (40, 'retenu_declasse'), (69, 'retenu_declasse'),
                        (70, 'retenu'), (100, 'retenu')]:
    verifier("une note de %d donne le palier « %s »" % (valeur, attendu),
             palier_de(valeur), attendu)

verifier("une note absente est traitée comme exclue", palier_de(None), 'exclu')


# ── 3. Les deux grandeurs ne partagent plus un nom ───────────────────────

racine = Path(__file__).resolve().parent.parent
app = (racine / 'app.py').read_text(encoding='utf-8')
helper = (racine / 'prescription_helper.py').read_text(encoding='utf-8')

verifier("la similarité cosinus a son propre champ",
         "'similarite'" in app or '"similarite"' in app, True)
verifier("la note clinique a le sien", "'pertinence'" in helper, True)
verifier("la génération ne pose plus la similarité dans relevance_score",
         "relevance_score'] = res.score" in app, False)
verifier("ni la recherche par mots-clés",
         "relevance_score'] = 0.5" in app, False)

verifier("le tuyau applique le seuil",
         'SEUIL_EXCLUSION' in helper, True)


# ── 4. Ce que le seuil ne doit pas casser ────────────────────────────────

# Le repli clinique note ses traitements de 75 à 95 : aucun ne doit tomber
# sous le seuil, sinon une fièvre n'aurait plus de paracétamol.
from prescription_helper import get_clinical_fallback  # noqa: E402

for cas in ["Fievre a 38,7 C", "Toux seche", "Nausees et vomissements"]:
    repli = get_clinical_fallback(cas)
    sous_seuil = [m['name'] for m in repli
                  if (m.get('relevance_score') or 0) < SEUIL_EXCLUSION]
    verifier("le repli clinique de « %s » survit au seuil" % cas,
             sous_seuil, [])


# ── Relevé ───────────────────────────────────────────────────────────────

print()
print("  Seuil d'exclusion : %d" % SEUIL_EXCLUSION)
print("  Notes mesurées :")
for contexte, titre, groupes in [
        (PNEUMONIE, 'CLAMOXYL 500 mg, gélule', ['J01']),
        (PNEUMONIE, 'ERY 500 mg, comprimé', ['J01']),
        (PNEUMONIE, 'COVERAM 10 mg, comprimé', ['C09', 'C10']),
        (DECOMP, 'BURINEX 1 mg, comprimé', ['C03'])]:
    n = note(contexte, titre, groupes)
    print("    %-30s %-12s %3d  %s"
          % (titre[:30], sorted(groupes), n, palier_de(n)))

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
