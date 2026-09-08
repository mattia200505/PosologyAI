"""Banc de la génération par classe ATC — phase P3b de la roadmap.

Ce que ce banc garde
--------------------
P3a avait retourné la chaîne : la règle constitue le vivier avant que le modèle
ne choisisse. Mais elle n'avait pas pu clore son critère de sortie, pour une
raison qui tient en une phrase :

> **Un filtre retire, il n'ajoute jamais.**

Mesuré sur « pneumonie communautaire », le vivier retenu comptait 19 candidats
et **zéro antibiotique** — C09, C10, N01, R03, R06, R05, N02, L01, et neuf sans
classe. Aucun filtrage ne pouvait faire apparaître un J01 qui n'était pas là.

L'étage 1 de l'architecture prévoyait « **ATC attendus pour le diagnostic** +
recherche vectorielle bornée ». C'est la première moitié qui manquait.

Ce que P3b ajoute
-----------------
`candidats_par_classe()` interroge le graphe : quelles spécialités portent une
substance dont le code ATC relève des classes qu'appelle le diagnostic. Ces
candidats rejoignent ceux de la recherche vectorielle.

Le quota par groupe est la parade au risque de la phase : sans lui, J01
noierait N02 sous des centaines d'antibiotiques et la fièvre ne serait plus
traitée.

Emploi
------
    python scripts/verif_generation_atc.py

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


# Le contexte de requête est nécessaire : la lecture du graphe passe par
# `current_app.neo4j`, comme partout ailleurs dans le module.
from app import app  # noqa: E402
import users  # noqa: E402
users.init_users(app)

import prescription_helper as P  # noqa: E402

with app.test_request_context():

    # ── 1. La génération rend des candidats de la bonne classe ───────────

    antibiotiques = P.candidats_par_classe({'J01'})
    verifier("la génération rend des candidats pour J01",
             len(antibiotiques) > 0, True)
    verifier("tous relèvent de la classe demandée",
             all('J01' in (m.get('groupes_atc') or []) for m in antibiotiques),
             True)
    verifier("chacun porte un titre", all(m.get('title') for m in antibiotiques),
             True)
    verifier("chacun porte un identifiant de fiche",
             all(m.get('id') for m in antibiotiques), True)
    verifier("chacun dit d'où il vient",
             all(m.get('origine') == 'classe_atc' for m in antibiotiques), True)

    # Le filtre d'éligibilité de P1 s'applique aussi à ces candidats : il
    # serait absurde de générer un produit non commercialisé.
    verifier("aucun candidat non commercialisé n'est généré",
             all(m.get('commercialisation') == 'Commercialisée'
                 for m in antibiotiques if m.get('commercialisation')), True)

    # ── 2. Le quota par groupe ───────────────────────────────────────────

    # Sans quota, J01 noierait N02 : une pneumonie n'aurait plus d'antalgique.
    melange = P.candidats_par_classe({'J01', 'N02'})
    par_groupe = {}
    for m in melange:
        for g in set(m.get('groupes_atc') or []) & {'J01', 'N02'}:
            par_groupe[g] = par_groupe.get(g, 0) + 1
    verifier("les deux classes demandées sont représentées",
             sorted(par_groupe), ['J01', 'N02'])
    # Le quota du **vivier**, élargi : la génération laisse entrer, elle ne
    # choisit pas. Le tri d'entrée du graphe reste typographique — il n'a
    # aucune information clinique à ce stade — et un vivier serré coupait donc
    # sur la longueur du nom : « DAFALGAN 500 mg, gélule » n'entrait pas dans
    # les six places de N02, prises par LAMALINE et PRONTALGINE.
    verifier("aucune classe ne dépasse le quota du vivier",
             all(n <= P.CANDIDATS_PAR_CLASSE * P.ELARGISSEMENT_VIVIER
                 for n in par_groupe.values()), True)

    # Le quota final, lui, s'applique après notation — c'est `reduire_par_classe`
    # qui le tient, sur la pertinence clinique et non sur le nom.
    reduits = P.reduire_par_classe(melange, P.CANDIDATS_PAR_CLASSE)
    apres = {}
    for m in reduits:
        for g in set(m.get('groupes_atc') or []) & {'J01', 'N02'}:
            apres[g] = apres.get(g, 0) + 1
    verifier("la réduction ramène chaque classe à son quota",
             all(n <= P.CANDIDATS_PAR_CLASSE for n in apres.values()), True)
    verifier("et les deux classes restent représentées",
             sorted(apres), ['J01', 'N02'])

    verifier("aucune classe attendue ne rend aucun candidat",
             P.candidats_par_classe(set()), [])
    verifier("None ne casse pas", P.candidats_par_classe(None), [])

    # ── 3. Critère de sortie de P3b, sur le cas réel ─────────────────────

    from app import search_medications_for_diagnostic, extract_medical_keywords

    DIAG = "Pneumonie communautaire du lobe inferieur droit, forme non severe."
    attendues = P.classes_atc_attendues(DIAG)
    verifier("le diagnostic appelle les antibactériens", 'J01' in attendues, True)

    # Depuis P7, la génération rend aussi ses écartés : ils étaient jetés, et
    # le médecin voyait une liste courte sans savoir ce qui l'avait raccourcie.
    vivier, ecartes_generation = search_medications_for_diagnostic(
        DIAG, extract_medical_keywords(DIAG))
    verifier("la génération rend aussi ses écartés",
             isinstance(ecartes_generation, list), True)
    noms = ' | '.join((m.get('title') or '') for m in vivier).upper()

    verifier("CRITÈRE DE SORTIE — au moins un antibiotique est présent",
             any('J01' in (m.get('groupes_atc') or []) for m in vivier), True)
    verifier("CRITÈRE DE SORTIE — ADRENALINE est absente", 'ADRENALINE' in noms,
             False)
    verifier("HELIKIT reste absent (acquis de P3a)", 'HELIKIT' in noms, False)

    # Ce que le filtre par classe attendue doit écarter, et pas davantage.
    hors = [m for m in vivier
            if (m.get('groupes_atc') or [])
            and not (set(m.get('groupes_atc') or []) & attendues)]
    verifier("aucun candidat retenu n'est hors des classes attendues\n"
             "      (hors : %s)" % [m.get('title', '')[:24] for m in hors[:4]],
             hors, [])

    # Un produit sans classe reste retenu : l'absence déclasse, elle n'exclut
    # pas. 148 substances du graphe n'ont aucun code ATC.
    verifier("des candidats sans classe peuvent subsister",
             all(m.get('sans_classe') for m in vivier
                 if not (m.get('groupes_atc') or [])), True)

    # ── 4. Le branchement ────────────────────────────────────────────────

    app_source = (Path(__file__).resolve().parent.parent
                  / 'app.py').read_text(encoding='utf-8')
    verifier("la chaîne par diagnostic calcule les classes attendues",
             'classes_atc_attendues(' in app_source, True)
    verifier("elle les passe au filtre",
             'attendues=' in app_source, True)
    verifier("elle génère aussi par classe",
             'candidats_par_classe(' in app_source, True)

    print()
    print("  Diagnostic éprouvé : pneumonie communautaire")
    print("  Classes attendues  : %s" % sorted(attendues))
    print("  Vivier             : %d candidats" % len(vivier))
    groupes = {}
    for m in vivier:
        for g in (m.get('groupes_atc') or ['(aucun)']):
            groupes[g] = groupes.get(g, 0) + 1
    print("  Groupes présents   : %s"
          % dict(sorted(groupes.items(), key=lambda x: -x[1])))
    print("  Premiers retenus   :")
    for m in vivier[:6]:
        print("     %-48s %s" % ((m.get('title') or '')[:48],
                                 sorted(m.get('groupes_atc') or []) or '(sans classe)'))

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
