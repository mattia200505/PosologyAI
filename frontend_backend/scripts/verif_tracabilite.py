"""Banc de la traçabilité — phase P7 de la roadmap, la dernière.

Ce que ce banc garde
--------------------
Six phases ont appris au système à écarter. P7 lui apprend à **dire pourquoi**.

Quatre étages écartent désormais, et trois d'entre eux le faisaient en
silence :

    P1  éligibilité      non commercialisé, produit de procédure
    P3  classe ATC       hors des classes que le tableau appelle
    P4  seuil            note sous 40
    —   antécédents      contrainte ou seuil biologique

Seul le dernier arrivait à l'écran. Les trois autres se produisaient dans
`search_medications_for_diagnostic`, dont les écartés étaient **jetés** : le
médecin voyait une liste courte sans savoir ce qui l'avait raccourcie.

C'est exactement ce que le § 2.8 reproche depuis le début — un médicament
écarté en silence emporte avec lui la raison de son retrait.

Ce que P7 ajoute aux propositions
---------------------------------
Le § 4.3 de l'architecture en demande quatre : la règle qui l'a retenue, la
classe ATC **et son libellé**, l'indication DrugBank citée, et ce qui a été
écarté à sa place. Les deux premières existaient ; les deux autres arrivent ici.

Emploi
------
    python scripts/verif_tracabilite.py

Neo4j et MongoDB sont nécessaires.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

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


from app import app, search_medications_for_diagnostic, extract_medical_keywords  # noqa: E402
import users  # noqa: E402
users.init_users(app)
import prescription_helper as P  # noqa: E402

DIAG = "Pneumonie communautaire du lobe inferieur droit, forme non severe."

with app.test_request_context():

    # ── 1. La génération rend ses écartés ────────────────────────────────

    retenus, ecartes = search_medications_for_diagnostic(
        DIAG, extract_medical_keywords(DIAG))

    verifier("la génération rend deux listes", isinstance(retenus, list), True)
    verifier("elle rend ses écartés", isinstance(ecartes, list), True)
    verifier("des candidats ont bien été écartés", len(ecartes) > 0, True)

    # CRITÈRE DE SORTIE : un motif lisible et sa source.
    verifier("CRITÈRE DE SORTIE — chaque écarté porte un motif",
             all(m.get('motif_ecart') for m in ecartes), True)
    verifier("CRITÈRE DE SORTIE — chaque écarté nomme l'étage qui l'a retiré",
             all(m.get('etage_ecart') for m in ecartes), True)
    verifier("le motif est lisible, pas un code",
             all(len(m.get('motif_ecart', '')) > 15 for m in ecartes), True)

    etages = {m['etage_ecart'] for m in ecartes}
    verifier("les étages nommés sont ceux de l'architecture",
             etages <= {'eligibilite', 'classe'}, True)
    verifier("l'étage d'éligibilité a écarté", 'eligibilite' in etages, True)

    # ── 2. HELIKIT, le cas d'école, est écarté et le dit ─────────────────

    helikit = [m for m in ecartes
               if (m.get('title') or '').upper().startswith('HELIKIT')]
    if helikit:
        verifier("HELIKIT dit pourquoi il est écarté",
                 'diagnostique' in helikit[0]['motif_ecart'].lower(), True)
        verifier("et par quel étage", helikit[0]['etage_ecart'], 'classe')

    # ── 3. Les propositions portent leur explication ─────────────────────

    controles = P.appliquer_controles(retenus[:6], contexte=DIAG)
    propositions = controles['medications']
    verifier("des propositions subsistent", len(propositions) > 0, True)

    verifier("chacune porte un rang thérapeutique",
             all(m.get('rang') for m in propositions), True)
    verifier("chacune porte une note",
             all(isinstance(m.get('pertinence'), (int, float))
                 for m in propositions), True)

    # Le § 4.3 demande la classe ATC **et son libellé**.
    avec_classe = [m for m in propositions if m.get('groupes_atc')]
    if avec_classe:
        verifier("la classe ATC est nommée, pas seulement codée",
                 all(m.get('classes_libelles') for m in avec_classe), True)
        verifier("le libellé est un texte",
                 all(isinstance(v, str) and v
                     for m in avec_classe
                     for v in (m.get('classes_libelles') or {}).values()), True)

    # Et l'indication DrugBank, citée.
    verifier("au moins une proposition porte son indication",
             any(m.get('indication') for m in propositions), True)

    # ── 4. Les écartés de la génération rejoignent la réponse ────────────

    controles2 = P.appliquer_controles(retenus[:6], contexte=DIAG,
                                       ecartes_generation=ecartes)
    tous_ecartes = controles2['medicaments_ecartes']
    verifier("les écartés de la génération figurent dans la réponse",
             len(tous_ecartes) >= len(ecartes), True)
    verifier("tous portent un motif",
             all(m.get('motif_ecart') or m.get('ecarte_par')
                 or m.get('sous_le_seuil') for m in tous_ecartes), True)

    # ── 5. Le branchement ────────────────────────────────────────────────

    racine = Path(__file__).resolve().parent.parent
    app_source = (racine / 'app.py').read_text(encoding='utf-8')
    verifier("la route transmet les écartés de la génération",
             'ecartes_generation=' in app_source, True)

    module = (racine / 'static' / 'js'
              / 'prescription_resultats.js').read_text(encoding='utf-8')
    verifier("l'écran sait afficher un motif de génération",
             'motif_ecart' in module, True)
    verifier("l'écran sait afficher l'indication", 'indication' in module, True)

    print()
    print("  Vivier : %d retenus, %d écartés" % (len(retenus), len(ecartes)))
    par_etage = {}
    for m in ecartes:
        par_etage[m['etage_ecart']] = par_etage.get(m['etage_ecart'], 0) + 1
    print("  Écartés par étage : %s" % par_etage)
    print()
    print("  Trois écartés, avec leur motif :")
    for m in ecartes[:3]:
        print("    %-38s [%s] %s"
              % ((m.get('title') or '')[:38], m['etage_ecart'],
                 m['motif_ecart'][:44]))
    print()
    print("  Propositions, avec leur explication :")
    for m in propositions[:3]:
        print("    %-30s %-19s %s"
              % ((m.get('title') or '')[:30], m.get('rang'),
                 list((m.get('classes_libelles') or {}).values())[:1]))

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
