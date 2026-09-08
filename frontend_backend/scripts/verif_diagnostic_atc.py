"""Banc de la table diagnostic → ATC — phase P5 de la roadmap.

Ce que ce banc garde
--------------------
P5 est la seule phase du projet qui porte un **jugement clinique**. Tout le
reste constate des faits : un produit est commercialisé ou non, une substance
porte un code ATC ou non, deux molécules interagissent ou non. Ici, on dit ce
qu'un tableau appelle.

Elle est nécessaire parce qu'un filtre retire et n'ajoute jamais : mesuré sur
« pneumonie communautaire », le vivier retenu comptait 19 candidats et **zéro
antibiotique**. Sans savoir qu'une pneumonie appelle J01, ni le filtrage ni la
génération ne peuvent redresser cela.

Le critère de sortie
--------------------
**≥ 80 % des diagnostics du jeu d'essai rendent au moins une classe
attendue.** Le jeu — trente diagnostics de médecine de ville, annotés en
classes attendues et inacceptables — vit dans
`donnees/jeu_essai_diagnostics.json`.

Sans lui, aucune précision ne se mesure : on ne peut que constater qu'un
résultat *paraît* meilleur.

Réserve
-------
La table n'a **pas été relue par un professionnel**. Le § 9 de l'architecture
le pose : une trame est proposable, sa validation ne l'est pas. Ce banc mesure
la cohérence entre la table et le jeu d'essai — deux écrits de la même main.
Il ne prouve pas leur justesse clinique.

Emploi
------
    python scripts/verif_diagnostic_atc.py

Aucune base n'est nécessaire.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from prescription_helper import (  # noqa: E402
    DIAGNOSTIC_ATC_MAP,
    classes_atc_attendues,
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


# ── 1. La table elle-même ────────────────────────────────────────────────

verifier("la table compte au moins 50 entrées (mesuré : %d)"
         % len(DIAGNOSTIC_ATC_MAP), len(DIAGNOSTIC_ATC_MAP) >= 50, True)

for cle, groupes in DIAGNOSTIC_ATC_MAP.items():
    verifier("« %s » appelle au moins une classe" % cle, bool(groupes), True)
    # Le nom est cherché en mot entier ; en dessous de quatre lettres, même un
    # mot entier rencontre trop de choses.
    verifier("« %s » est assez long" % cle, len(cle) >= 4, True)
    for g in groupes:
        verifier("le groupe « %s » de « %s » est un code de niveau 2"
                 % (g, cle), len(g) == 3 and g[0].isalpha() and g[1:].isdigit(),
                 True)


# ── 2. La reconnaissance ─────────────────────────────────────────────────

verifier("une pneumonie appelle les antibactériens",
         'J01' in classes_atc_attendues("Pneumonie communautaire"), True)
verifier("elle n'appelle pas les agents diagnostiques",
         'V04' in classes_atc_attendues("Pneumonie communautaire"), False)

verifier("l'accent n'est pas requis",
         'J01' in classes_atc_attendues("Pyelonephrite aigue"), True)
verifier("le pluriel est toléré",
         'J01' in classes_atc_attendues("Otites a repetition"), True)

# Le mot entier protège, comme partout ailleurs dans le projet.
verifier("« zona » n'est pas reconnue dans « zonage »",
         classes_atc_attendues("Zonage thoracique"), set())
verifier("mais « zona » l'est quand elle est citée",
         'J05' in classes_atc_attendues("Zona intercostal"), True)

verifier("un diagnostic inconnu ne rend rien",
         classes_atc_attendues("Syndrome de description inhabituelle"), set())
verifier("une saisie vide ne rend rien", classes_atc_attendues(''), set())
verifier("None ne casse pas", classes_atc_attendues(None), set())

# Un diagnostic composite cumule les classes des pathologies qu'il nomme.
composite = classes_atc_attendues(
    "Decompensation cardiaque sur fibrillation auriculaire, avec BPCO surinfectee")
for g in ['C03', 'B01', 'R03']:
    verifier("le diagnostic composite appelle %s" % g, g in composite, True)


# ── 3. Critère de sortie, contre le jeu d'essai annoté ───────────────────

chemin = Path(__file__).resolve().parent / 'donnees' / 'jeu_essai_diagnostics.json'
verifier("le jeu d'essai existe", chemin.exists(), True)

jeu = json.loads(chemin.read_text(encoding='utf-8'))
cas = jeu['cas']
verifier("le jeu compte au moins 30 cas (mesuré : %d)" % len(cas),
         len(cas) >= 30, True)

couverts, manques, faux_positifs = 0, [], []
for c in cas:
    rendues = classes_atc_attendues(c['diagnostic'])
    attendues = set(c['attendues'])
    inacceptables = set(c['inacceptables'])

    if rendues & attendues:
        couverts += 1
    else:
        manques.append((c['diagnostic'], sorted(rendues), sorted(attendues)))

    # Ce que la table appelle ne doit jamais figurer parmi les inacceptables.
    faux = rendues & inacceptables
    if faux:
        faux_positifs.append((c['diagnostic'], sorted(faux)))

couverture = 100.0 * couverts / max(len(cas), 1)
verifier("au moins 80 %% des diagnostics rendent une classe attendue "
         "(mesuré : %.1f %% — %d sur %d)" % (couverture, couverts, len(cas)),
         couverture >= 80.0, True)

verifier("aucune classe inacceptable n'est appelée", faux_positifs, [])


# ── 3 bis. Épreuve indépendante ──────────────────────────────────────────

# 100 % sur le jeu d'essai mesure la cohérence entre deux écrits de la même
# main. Ces trois diagnostics-ci ont été rédigés **avant** la table, dont un
# produit par un modèle tiers : ils ne pouvaient pas être ajustés à elle.
JEAN_MARTIN = ("Decompensation aigue d insuffisance cardiaque chronique "
               "compliquee d un syndrome cardio-renal, congestion hepatique "
               "severe et troubles hydro-electrolytiques.")
rendues = classes_atc_attendues(JEAN_MARTIN)
# Le patient est effectivement sous Furosémide (C03), Bisoprolol (C07) et
# Sacubitril/Valsartan (C09). La table retrouve ses trois classes.
for g in ['C03', 'C07', 'C09']:
    verifier("cas indépendant (rédigé par un tiers) : %s est appelé" % g,
             g in rendues, True)

CAS_BPCO = ("Decompensation cardiaque globale sur cardiopathie ischemique, avec "
            "fibrillation auriculaire rapide, insuffisance renale chronique "
            "stade 3 et bronchopneumopathie chronique obstructive surinfectee.")
rendues_bpco = classes_atc_attendues(CAS_BPCO)
for g in ['C03', 'B01', 'R03']:
    verifier("cas BPCO, antérieur à la table : %s est appelé" % g,
             g in rendues_bpco, True)

# Et elle n'invente rien sur ce qu'elle ne connaît pas.
verifier("un diagnostic hors table ne rend rien plutôt que n'importe quoi",
         classes_atc_attendues("Suspicion de maladie de Horton chez un sujet age"),
         set())


# ── 4. Le branchement, préparé pour P3b ──────────────────────────────────

# P5 livre la table ; c'est P3b qui la branchera au filtre. Le banc vérifie
# seulement que la fonction existe et que son grain correspond à celui que
# `groupes_atc_des()` relit dans le graphe.
helper = (Path(__file__).resolve().parent.parent
          / 'prescription_helper.py').read_text(encoding='utf-8')
verifier("classes_atc_attendues est exposée",
         'def classes_atc_attendues(' in helper, True)
verifier("le filtre sait recevoir des classes attendues",
         'def filtrer_par_classe(medications, attendues=None)' in helper, True)


# ── Relevé ───────────────────────────────────────────────────────────────

print()
print("  Entrées de la table   : %d" % len(DIAGNOSTIC_ATC_MAP))
print("  Cas du jeu d'essai    : %d" % len(cas))
print("  Couverture            : %.1f %% (%d sur %d)"
      % (couverture, couverts, len(cas)))
if manques:
    print()
    print("  Diagnostics non couverts :")
    for d, rendues, attendues in manques:
        print("    %-56s rendu=%s attendu=%s" % (d[:56], rendues, attendues))
if faux_positifs:
    print()
    print("  Classes inacceptables appelées :")
    for d, faux in faux_positifs:
        print("    %-56s %s" % (d[:56], faux))

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
