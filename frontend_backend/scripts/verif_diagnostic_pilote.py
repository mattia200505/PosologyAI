"""Banc : le diagnostic pilote la sélection, et la sécurité pèse sur la note.

Ce que ce banc garde
--------------------

**Le diagnostic arrivait en dernier.** Sur l'assistant, l'ordre réel était :

    search_medications_by_symptoms(symptomes)   ligne  96
    compute_clinical_relevance(symptomes, med)  ligne 108
    get_clinical_fallback(symptomes)            ligne 136
    appliquer_controles(...)  sans contexte     ligne 152
    generate_diagnostic(symptomes, ...)         ligne 159

Tout était choisi quand le diagnostic naissait. Il ne pouvait pas informer la
sélection — il s'affichait à côté d'elle.

Mesuré sur un cas réel : symptômes d'insuffisance cardiaque décompensée —
dyspnée, œdèmes, prise de poids, oligurie. Le modèle posait le bon diagnostic,
« Insuffisance cardiaque aiguë décompensée, confiance 85 % », et l'écran
proposait **salbutamol et budésonide**, « retenu pour : Asthme ». Le mot
*dyspnée* avait déclenché la conduite « asthme » du repli, et le moteur n'avait
jamais vu le diagnostic.

**Et la sécurité ne pesait pas.** Salbutamol gardait 95 sur 100 avec une
contre-indication relevée. Le score et la sécurité étaient deux axes
indépendants : un médicament contre-indiqué se lisait comme un bon choix.

Emploi
------
    python scripts/verif_diagnostic_pilote.py

Aucune base n'est nécessaire.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from prescription_helper import (  # noqa: E402
    PENALITE_CONTRE_INDICATION,
    PENALITE_INTERACTION,
    nom_du_diagnostic,
    peser_la_securite,
    tableau_clinique,
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


# ── 1. Extraire le diagnostic du compte rendu ────────────────────────────

COMPTE_RENDU = """**Diagnostic principal probable:**
Insuffisance cardiaque aiguë décompensée — Confiance : 85%
Décompensation sur insuffisance cardiaque chronique à fraction d'éjection
réduite, avec syndrome cardio-rénal.

**Diagnostics différentiels:**
[Embolie pulmonaire — Probabilité : 10% — Dyspnée aiguë]

**Conclusion et conduite à tenir:**
Hospitalisation, diurétiques intraveineux."""

verifier("le nom du diagnostic est extrait du compte rendu",
         nom_du_diagnostic(COMPTE_RENDU),
         "Insuffisance cardiaque aiguë décompensée")

verifier("les marqueurs de gras sont retirés",
         nom_du_diagnostic("**Diagnostic principal probable:**\n"
                           "**Pneumonie communautaire** — Confiance : 70%"),
         "Pneumonie communautaire")

verifier("la forme anglaise est lue",
         nom_du_diagnostic("**Probable primary diagnosis:**\n"
                           "Acute heart failure - Confidence: 85%"),
         "Acute heart failure")

# Mieux vaut rien qu'un faux diagnostic : une phrase entière promue en nom
# ferait chercher des médicaments sur de la prose.
verifier("une prose longue n'est pas prise pour un diagnostic",
         nom_du_diagnostic("**Diagnostic principal probable:**\nLe tableau "
                           "clinique évoque une atteinte dont la nature reste "
                           "à préciser par des examens complémentaires."), '')
verifier("un compte rendu vide ne rend rien", nom_du_diagnostic(''), '')
verifier("None ne casse pas", nom_du_diagnostic(None), '')


# ── 2. Le tableau clinique, ce sur quoi la sélection se fait ─────────────

SYMPTOMES = ("Dyspnee de plus en plus marquee. Oedemes bilateraux des jambes. "
             "Prise de poids de 5 kg en 3 semaines.")

tableau = tableau_clinique(SYMPTOMES, COMPTE_RENDU)
verifier("le tableau porte le diagnostic",
         'Insuffisance cardiaque' in tableau, True)
verifier("il garde aussi les symptômes", 'Oedemes' in tableau, True)

# Le diagnostic passe **devant** : c'est lui qui doit primer quand les deux
# se contredisent, comme « dyspnée » contre « insuffisance cardiaque ».
verifier("le diagnostic ouvre le tableau",
         tableau.index('Insuffisance cardiaque') < tableau.index('Dyspnee'), True)

verifier("sans diagnostic, les symptômes seuls font le tableau",
         tableau_clinique(SYMPTOMES, ''), SYMPTOMES)
verifier("sans rien, le tableau est vide", tableau_clinique('', ''), '')


# ── 3. Le tableau change ce que le moteur cherche ────────────────────────

from prescription_helper import classes_atc_attendues  # noqa: E402

sur_symptomes = classes_atc_attendues(SYMPTOMES)
sur_tableau = classes_atc_attendues(tableau)

verifier("sur les symptômes seuls, aucun diurétique n'est attendu",
         'C03' in sur_symptomes, False)
verifier("avec le diagnostic, le diurétique l'est",
         'C03' in sur_tableau, True)


# ── 4. La sécurité pèse sur la note ──────────────────────────────────────

verifier("la pénalité de contre-indication est réelle",
         PENALITE_CONTRE_INDICATION >= 20, True)
verifier("celle d'interaction aussi", PENALITE_INTERACTION >= 10, True)

def med(titre, pertinence, ci=0, inter=0):
    return {'title': titre, 'pertinence': pertinence,
            'contre_indications': [{'terme': 'x', 'phrase': 'y'}] * ci}

lot = [med('SALBUTAMOL', 95, ci=1), med('PARACETAMOL', 95),
       med('BUDESONIDE', 80)]
interactions = [{'medicine1': 'Bisoprolol (x)', 'medicine2': 'BUDESONIDE (y)',
                 'description': 'z'}]
peser_la_securite(lot, interactions)

par_nom = {m['title']: m for m in lot}
verifier("un médicament contre-indiqué perd des points",
         par_nom['SALBUTAMOL']['pertinence'] < 95, True)
verifier("il descend sous celui qui ne l'est pas",
         par_nom['SALBUTAMOL']['pertinence'] < par_nom['PARACETAMOL']['pertinence'],
         True)
verifier("un médicament en interaction en perd aussi",
         par_nom['BUDESONIDE']['pertinence'] < 80, True)
verifier("celui qui n'a rien garde sa note",
         par_nom['PARACETAMOL']['pertinence'], 95)

# La pénalité se dit : une note qui baisse sans raison affichée est pire
# qu'une note haute et fausse.
verifier("la pénalité est nommée",
         bool(par_nom['SALBUTAMOL'].get('penalites')), True)
verifier("elle dit ce qui l'a causée",
         'contre-indication' in ' '.join(par_nom['SALBUTAMOL']['penalites']).lower(),
         True)

# Elle abaisse, elle n'annule pas : un rapprochement de texte n'est pas une
# décision clinique, et le médecin doit garder la main (§ 2.8).
verifier("la note ne tombe jamais sous zéro",
         min(m['pertinence'] for m in lot) >= 0, True)
verifier("une contre-indication n'annule pas la proposition",
         par_nom['SALBUTAMOL']['pertinence'] > 0, True)

verifier("une liste vide ne casse pas", peser_la_securite([], []), [])
verifier("None ne casse pas", peser_la_securite(None, None), [])


# ── 5. Le branchement ────────────────────────────────────────────────────

source = (Path(__file__).resolve().parent.parent
          / 'prescription_helper.py').read_text(encoding='utf-8')

# L'ordre est le fond du sujet : le diagnostic doit précéder la sélection.
corps = source[source.index('def analyze_patient'):]
corps = corps[:corps.index('\ndef ', 10)]

#: Le même corps, sans les commentaires. Les contrôles de la section 6
#: cherchent l'absence d'un motif de code ; or ce motif est cité, exprès, dans
#: le commentaire qui explique son retrait. Un banc qui lit la prose comme du
#: code se déclare en échec sur sa propre explication.
code = '\n'.join(l for l in corps.split('\n') if not l.lstrip().startswith('#'))
verifier("le diagnostic est produit AVANT le contrôle des médicaments",
         corps.index('generate_diagnostic(') < corps.index('appliquer_controles('),
         True)
verifier("la sélection se fait sur le tableau clinique",
         'tableau_clinique(' in corps, True)
verifier("le contexte est transmis au tuyau",
         'contexte=tableau' in corps, True)
verifier("la sécurité est pesée", 'peser_la_securite(' in source, True)


# ── 6. Un seul seuil, et il laisse une trace ─────────────────────────────
#
# Un filtre antérieur au recrutement par classe coupait à 70 :
#
#     high_conf = [m for m in scored_medications if m['relevance_score'] >= 70]
#     if high_conf: filtered = high_conf
#
# `compute_clinical_relevance` plafonne à 60 un candidat retenu pour sa
# classe ATC. Il suffisait donc qu'une remontée vectorielle atteigne 70 pour
# que tout le recrutement piloté par le diagnostic soit jeté, sans trace.
#
# Mesuré sur une lombalgie chez une insuffisante rénale : six AINS appelés
# par le diagnostic supprimés ici ; l'écran ne montrait que des antalgiques
# de similarité, et la contrainte rénale n'avait rien eu à écarter.

verifier("le pré-filtre à 70 ne revient pas", ">= 70" not in code, True)
verifier("son repli à 50 non plus", ">= 50" not in code, True)
verifier("le vivier n'est plus coupé avant les contrôles",
         'high_conf' not in code, True)

# Ce qui disparaît doit être nommé : c'est le seuil d'`appliquer_controles`
# qui tranche désormais, et lui range ce qu'il retire.
verifier("le seuil qui reste range les écartés",
         'medicaments_ecartes' in source, True)


# ── Relevé ───────────────────────────────────────────────────────────────

print()
print("  Diagnostic extrait : %s" % nom_du_diagnostic(COMPTE_RENDU))
print("  Classes attendues  : symptômes seuls %s" % sorted(sur_symptomes))
print("                       avec diagnostic %s" % sorted(sur_tableau))
print("  Notes après pesée  : %s"
      % {m['title']: m['pertinence'] for m in lot})

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
