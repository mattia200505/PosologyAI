"""Banc du filtre d'éligibilité — phase P1 de la roadmap.

Ce que ce banc garde
--------------------
Le vivier de candidats n'était filtré par rien. Mesuré sur le catalogue :
**3 547 fiches sur 13 594 ne sont pas commercialisées** — un quart du
catalogue — et restaient candidates. 116 autres sont des produits de
procédure, administrés par voie extracorporelle, hémodialyse ou
hémofiltration : ce ne sont pas des traitements d'une pathologie.

C'est ainsi que SUBSOL SANS POTASSIUM, **non commercialisé** et de **voie
extracorporelle**, a été proposé pour une décompensation cardiaque. Deux
critères déterministes suffisaient à l'écarter ; aucun des deux n'était lu.

Ce que ce banc refuse
---------------------
Un filtre qui écarte trop est pire que pas de filtre : il retire en silence
des traitements légitimes. Le critère de sortie de P1 est donc double —
**SUBSOL et ACCUSOL absents**, et **aucun médicament oral commercialisé
perdu**. Les deux sont éprouvés ici.

Rien n'est retiré en silence : chaque écarté porte son motif, et l'appelant
les reçoit.

Emploi
------
    python scripts/verif_eligibilite.py

Les critères sont purs et s'éprouvent sans base. Les deux contrôles du critère
de sortie interrogent MongoDB et sont ignorés s'il n'est pas joignable.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from prescription_helper import (  # noqa: E402
    MOTIFS_INELIGIBILITE,
    filtrer_eligibilite,
    motif_d_ineligibilite,
)

_reussis = 0
_echecs = []
_ignores = []

#: Sentinelle. Les bancs précédents employaient `attendu=None` pour dire
#: « pas d'attendu, vérifie la véracité » — ce qui rend impossible d'attendre
#: `None` lui-même. Or `motif_d_ineligibilite()` rend précisément `None` quand
#: un médicament est éligible, c'est-à-dire dans le cas le plus fréquent.
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


def fiche(**champs) -> dict:
    base = {'title': 'MEDICAMENT TEST', 'commercialisation': 'Commercialisée',
            'voies_administration': 'orale'}
    base.update(champs)
    return base


# ── 1. Critère 1 — la commercialisation ──────────────────────────────────

verifier("un médicament commercialisé est éligible",
         motif_d_ineligibilite(fiche()), None)

verifier("un médicament non commercialisé est écarté",
         motif_d_ineligibilite(fiche(commercialisation='Non commercialisée')),
         MOTIFS_INELIGIBILITE['non_commercialise'])

# Ne rien savoir n'est pas un motif d'exclusion. 1 654 fiches du catalogue ne
# portent aucune voie, et le champ peut manquer : les écarter reviendrait à
# punir un défaut de données.
verifier("une commercialisation absente n'écarte pas",
         motif_d_ineligibilite({'title': 'X'}), None)
verifier("une commercialisation vide n'écarte pas",
         motif_d_ineligibilite(fiche(commercialisation='')), None)
verifier("None n'écarte pas et ne casse pas",
         motif_d_ineligibilite(None), None)


# ── 2. Critère 2 — les produits de procédure ─────────────────────────────

for voie in ['hémodialyse', 'hémofiltration', 'voie extracorporelle autre',
             'hémodialyse;hémofiltration;voie extracorporelle autre',
             'HEMODIALYSE']:
    verifier("la voie « %s » écarte" % voie[:34],
             motif_d_ineligibilite(fiche(voies_administration=voie)),
             MOTIFS_INELIGIBILITE['produit_de_procedure'])

for voie in ['orale', 'intraveineuse', 'inhalée', 'cutanée', 'sous-cutanée',
             'ophtalmique', 'rectale', 'intraveineuse;sous-cutanée']:
    verifier("la voie « %s » n'écarte pas" % voie,
             motif_d_ineligibilite(fiche(voies_administration=voie)), None)

verifier("une voie absente n'écarte pas",
         motif_d_ineligibilite(fiche(voies_administration=None)), None)

# La borne de mot protège : « dialyse » ne doit pas être reconnue dans un mot
# plus long. Le projet s'est déjà fait prendre trois fois — « anti » dans
# « anti-Xa », « cetirizine » dans « LEVOCETIRIZINE », « zona » dans
# « zonage ».
verifier("« prédialyse » ne déclenche pas le critère de procédure",
         motif_d_ineligibilite(fiche(voies_administration='predialyse')), None)


# ── 3. Le tri, et ce qu'il rend ──────────────────────────────────────────

lot = [
    fiche(title='DOLIPRANE 1000 mg'),
    fiche(title='SUBSOL SANS POTASSIUM', commercialisation='Non commercialisée',
          voies_administration='hémodialyse;voie extracorporelle autre'),
    fiche(title='ACCUSOL 35', voies_administration='hémodialyse;hémofiltration'),
    fiche(title='VENTOLINE 100 µg', voies_administration='inhalée'),
]
eligibles, ecartes = filtrer_eligibilite(lot)

verifier("les médicaments légitimes passent",
         sorted(m['title'] for m in eligibles),
         ['DOLIPRANE 1000 mg', 'VENTOLINE 100 µg'])
verifier("SUBSOL et ACCUSOL sont écartés",
         sorted(m['title'] for m in ecartes),
         ['ACCUSOL 35', 'SUBSOL SANS POTASSIUM'])

verifier("chaque écarté porte son motif",
         all(m.get('inelligible_car') for m in ecartes), True)
verifier("le motif est lisible",
         all(len(m['inelligible_car']) > 10 for m in ecartes), True)

# Un produit cumulant les deux défauts est écarté une fois, par le motif le
# plus sûr : ne pas être commercialisé se constate sans jugement.
subsol = next(m for m in ecartes if m['title'].startswith('SUBSOL'))
verifier("le cumul rend le motif le plus sûr",
         subsol['inelligible_car'], MOTIFS_INELIGIBILITE['non_commercialise'])

verifier("une liste vide ne casse pas", filtrer_eligibilite([]), ([], []))
verifier("None ne casse pas", filtrer_eligibilite(None), ([], []))

# L'ordre d'entrée est préservé : le tri par pertinence a lieu ailleurs.
ordonne, _ = filtrer_eligibilite([fiche(title='A'), fiche(title='B'),
                                  fiche(title='C')])
verifier("l'ordre d'entrée est préservé",
         [m['title'] for m in ordonne], ['A', 'B', 'C'])


# ── 4. Le branchement sur les deux chaînes ───────────────────────────────

racine = Path(__file__).resolve().parent.parent
helper = (racine / 'prescription_helper.py').read_text(encoding='utf-8')
app = (racine / 'app.py').read_text(encoding='utf-8')

verifier("la chaîne A filtre son vivier",
         'filtrer_eligibilite(' in helper, True)
verifier("la chaîne B filtre son vivier",
         'filtrer_eligibilite(' in app, True)


# ── 5. Critère de sortie de P1, contre la base ───────────────────────────

try:
    from prescription_helper import db
    catalogue = db.medicines

    for titre in ['SUBSOL', 'ACCUSOL']:
        f = catalogue.find_one({'title': {'$regex': '^' + titre, '$options': 'i'}},
                               {'title': 1, 'commercialisation': 1,
                                'voies_administration': 1})
        verifier("%s est écarté par le filtre" % titre,
                 motif_d_ineligibilite(f) is not None, True)

    # Le second critère de sortie, et le plus important : le filtre ne doit
    # perdre aucun médicament oral commercialisé.
    oraux = catalogue.count_documents({
        'voies_administration': 'orale', 'commercialisation': 'Commercialisée'})
    perdus = 0
    for f in catalogue.find(
            {'voies_administration': 'orale',
             'commercialisation': 'Commercialisée'},
            {'title': 1, 'commercialisation': 1, 'voies_administration': 1}
    ).limit(3000):
        if motif_d_ineligibilite(f) is not None:
            perdus += 1
    verifier("aucun médicament oral commercialisé n'est perdu\n"
             "      (%d éprouvés sur %d)" % (min(3000, oraux), oraux),
             perdus, 0)

    ecartes_total = catalogue.count_documents(
        {'$or': [{'commercialisation': {'$ne': 'Commercialisée'}},
                 {'voies_administration': {
                     '$regex': 'extracorporelle|dialyse|filtration',
                     '$options': 'i'}}]})
    total = catalogue.estimated_document_count()
    print()
    print("  Écartement mesuré sur le catalogue : %d fiches sur %d (%.1f %%)"
          % (ecartes_total, total, 100.0 * ecartes_total / total))
    verifier("l'écartement reste dans la fourchette annoncée (25–40 %%)",
             25.0 <= 100.0 * ecartes_total / total <= 40.0, True)

except Exception as err:
    _ignores.append("critères de sortie non éprouvés — MongoDB : %s"
                    % str(err)[:70])


# ── Relevé ───────────────────────────────────────────────────────────────

print()
for i in _ignores:
    print("  IGNORÉ : %s" % i)
if _echecs:
    print("ÉCHECS (%d) :" % len(_echecs))
    for e in _echecs:
        print("  - %s" % e)
    print()
    print("%d contrôles réussis, %d en échec." % (_reussis, len(_echecs)))
    sys.exit(1)

print("%d contrôles, aucun en échec." % _reussis)
sys.exit(0)
