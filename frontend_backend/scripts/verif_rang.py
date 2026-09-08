"""Banc du rang thérapeutique et de la notation par pathologie.

Ce que ce banc garde
--------------------

**Le rang.** `get_clinical_fallback` range ses treize entrées en `first_line`
et `alternatives` — première intention d'un côté, solution de repli de
l'autre, avec posologie, durée et justification. Cette distinction était
**jetée** à l'assemblage : tout retombait dans une liste plate, et l'écran
présentait un antalgique de première intention et son alternative comme deux
propositions équivalentes. Le raisonnement clinique était dans les données ; il
n'arrivait pas à l'écran.

**La notation par pathologie.** `classes_attendues()` ne lisait que
`SYMPTOM_CLASS_MAP`, indexée par symptômes. La prescription par diagnostic
reçoit une *pathologie* : « pneumonie communautaire » n'y trouvait rien, aucun
candidat n'était noté, et le durcissement du § 7.8 ne pouvait pas l'aider.

Elle consulte désormais trois sources, de la plus sûre à la plus large :
les symptômes, les treize guidelines cliniques — qui nomment déjà des
pathologies et leurs traitements —, puis une table courte pour les diagnostics
courants qui manquaient.

Emploi
------
    python scripts/verif_rang.py

Aucune base n'est nécessaire.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from prescription_helper import (  # noqa: E402
    PATHOLOGIE_CLASS_MAP,
    classes_attendues,
    compute_clinical_relevance,
    get_clinical_fallback,
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


def note(contexte: str, titre: str) -> int:
    return compute_clinical_relevance(contexte, {'title': titre})[0]


# ── 1. Le rang survit à l'assemblage ─────────────────────────────────────

repli = get_clinical_fallback("Fièvre à 38,7 °C avec douleurs diffuses")

verifier("le repli rend des médicaments", len(repli) > 0, True)
verifier("chaque médicament porte un rang",
         all(m.get('rang') for m in repli), True)
verifier("les rangs employés sont ceux du barème",
         sorted({m['rang'] for m in repli}),
         ['alternative', 'premiere_intention'])
verifier("chaque médicament dit quelle condition l'a fait retenir",
         all(m.get('condition') for m in repli), True)

premieres = [m for m in repli if m['rang'] == 'premiere_intention']
alternatives = [m for m in repli if m['rang'] == 'alternative']
verifier("une fièvre appelle au moins une première intention",
         len(premieres) > 0, True)
verifier("elle appelle aussi au moins une alternative",
         len(alternatives) > 0, True)

verifier("le paracétamol est en première intention sur une fièvre",
         any('paracétamol' in m['name'].lower() for m in premieres), True)
verifier("l'ibuprofène y est une alternative, pas une première intention",
         any('ibuprofène' in m['name'].lower() for m in alternatives), True)

# Les premières intentions passent devant : l'ordre à l'écran est celui du
# raisonnement, pas celui du hasard d'assemblage.
rangs = [m['rang'] for m in repli]
verifier("toutes les premières intentions précèdent les alternatives",
         rangs, sorted(rangs, key=lambda r: r != 'premiere_intention'))

# Non-régression : la forme rendue reste celle que normaliser_medicament sait
# lire, sinon l'écran réafficherait « undefined ».
for champ in ('name', 'substance', 'posology', 'duration', 'explanation',
              'relevance_score'):
    verifier("le repli porte toujours le champ %s" % champ,
             all(champ in m for m in repli), True)

# Le repli universel, quand aucune condition ne correspond, porte un rang lui
# aussi : sans quoi l'écran aurait un groupe sans titre.
universel = get_clinical_fallback("Situation clinique non décrite ici")
verifier("le repli universel porte aussi des rangs",
         all(m.get('rang') for m in universel), True)
verifier("le repli universel nomme sa condition",
         all(m.get('condition') for m in universel), True)


# ── 2. La notation reconnaît une pathologie ──────────────────────────────

verifier("une pneumonie appelle un antibiotique",
         'antibiotique' in classes_attendues("Pneumonie communautaire du lobe "
                                             "inférieur droit"), True)
verifier("une pneumonie n'appelle pas un laxatif",
         'laxatif' in classes_attendues("Pneumonie communautaire"), False)

verifier("une angine appelle un antibiotique, via les guidelines",
         'antibiotique' in classes_attendues("Angine bactérienne"), True)
verifier("une cystite appelle un antibiotique, via les guidelines",
         'antibiotique' in classes_attendues("Cystite aiguë simple"), True)

verifier("un diagnostic inconnu n'appelle rien",
         classes_attendues("Syndrome de description inhabituelle"), set())

# Le symptôme continue de fonctionner : la nouvelle source s'ajoute, elle ne
# remplace pas.
verifier("une toux appelle toujours un bronchodilatateur",
         'bronchodilatateur' in classes_attendues("Toux sèche et gêne "
                                                  "respiratoire"), True)
verifier("une toux n'appelle toujours pas d'antispasmodique",
         'antispasmodique' in classes_attendues("Toux sèche"), False)


# ── 3. Ce que la notation donne sur un diagnostic ────────────────────────

PNEUMONIE = "Pneumonie communautaire du lobe inférieur droit, forme non sévère"

verifier("un antibiotique est pertinent pour une pneumonie",
         note(PNEUMONIE, 'AMOXICILLINE ARROW 500 mg, gélule') > 0, True)
verifier("un macrolide aussi, par sa substance",
         compute_clinical_relevance(
             PNEUMONIE, {'title': 'HELIKIT 75 mg, poudre',
                         'substances': ['Azithromycine']})[0] > 0, True)
verifier("un antihypertenseur ne l'est pas",
         note(PNEUMONIE, 'PERINDOPRIL EG 2 mg, comprimé'), 0)
verifier("un laxatif ne l'est pas",
         note(PNEUMONIE, 'FORLAX 10 g, poudre'), 0)

# Le diagnostic nomme parfois une comorbidité : elle ne doit pas ouvrir la
# porte à son propre traitement quand ce n'est pas le motif.
verifier("un antalgique reste pertinent pour une lombalgie",
         note("Lombalgie commune aiguë", 'DOLIPRANE 1000 mg') > 0, True)
verifier("un antiviral est pertinent pour un zona",
         note("Zona intercostal", 'ACICLOVIR EG 200 mg') > 0, True)


# ── 3 bis. Le patient complexe ───────────────────────────────────────────

# Un diagnostic réel n'est pas un mot : c'est une phrase qui empile les
# comorbidités, souvent saisie **sans accents**. Ce cas ne rendait que
# « ibuprofène » et « paracétamol », tirés du seul mot « fébrile » : les
# bronchodilatateurs, les diurétiques et les antibiotiques obtenaient tous
# zéro.
COMPLEXE = ("Decompensation cardiaque globale sur cardiopathie ischemique, avec "
            "fibrillation auriculaire rapide, insuffisance renale chronique "
            "stade 3 et bronchopneumopathie chronique obstructive surinfectee. "
            "Etat febrile a 38,4 C.")

attendues_complexe = classes_attendues(COMPLEXE)

verifier("une bronchopneumopathie appelle un bronchodilatateur",
         'bronchodilatateur' in attendues_complexe, True)
verifier("une décompensation cardiaque appelle un diurétique",
         'diurétique' in attendues_complexe, True)
verifier("une fibrillation auriculaire appelle un anticoagulant",
         'anticoagulant' in attendues_complexe, True)
verifier("une surinfection appelle un antibiotique",
         'antibiotique' in attendues_complexe, True)

verifier("un bronchodilatateur est noté sur ce diagnostic",
         compute_clinical_relevance(
             COMPLEXE, {'title': 'BRONCHODUAL 50 microgrammes',
                        'substances': ['Fénotérol']})[0] > 0, True)
verifier("un diurétique aussi",
         note(COMPLEXE, 'LASILIX 40 mg, comprimé') > 0, True)

# Et la précision tient : ce qui n'a rien à y faire reste à zéro.
verifier("un laxatif reste hors sujet", note(COMPLEXE, 'FORLAX 10 g'), 0)
verifier("un antihistaminique reste hors sujet",
         note(COMPLEXE, 'ZYRTEC 10 mg, comprimé'), 0)

# L'accent n'est pas requis : un diagnostic se saisit rarement accentué.
verifier("« bronchopneumopathie » est reconnue sans accent",
         'bronchodilatateur' in classes_attendues('Bronchopneumopathie obstructive'),
         True)
verifier("« pyelonephrite » sans accent est reconnue",
         'antibiotique' in classes_attendues('Pyelonephrite aigue'), True)
verifier("« pyélonéphrite » avec accent l'est toujours",
         'antibiotique' in classes_attendues('Pyélonéphrite aiguë'), True)
verifier("« ulcere gastroduodenal » sans accent est reconnu",
         'antiacide' in classes_attendues('Ulcere gastroduodenal'), True)

# « bronchopneumopathie » contient « pneumopathie » : la borne de mot
# l'empêchait d'être reconnue, et c'est bien une entrée à part.
verifier("« bronchopneumopathie » n'est pas prise pour une pneumopathie seule",
         'macrolide' in classes_attendues('Bronchopneumopathie obstructive'), False)


# ── 4. La table des pathologies, isolément ───────────────────────────────

verifier("la table des pathologies n'est pas vide",
         len(PATHOLOGIE_CLASS_MAP) > 0, True)
for pathologie, classes in PATHOLOGIE_CLASS_MAP.items():
    verifier("« %s » porte des classes" % pathologie, bool(classes), True)
    # Le nom est cherché en mot entier, ce qui protège les noms courts comme
    # « zona ». En dessous de quatre lettres, même un mot entier rencontre
    # trop de choses.
    verifier("« %s » est assez long" % pathologie, len(pathologie) >= 4, True)
    for classe in classes:
        verifier("la classe « %s » est assez longue" % classe,
                 len(classe) >= 5, True)

# Le mot entier protège vraiment : une pathologie ne doit pas être reconnue
# à l'intérieur d'un mot plus long.
verifier("« otite » n'est pas reconnue dans « parotidite »",
         'amoxicilline' in classes_attendues('Parotidite virale'), False)
verifier("« zona » n'est pas reconnue dans « zonage »",
         'aciclovir' in classes_attendues('Zonage thoracique imaginaire'), False)
verifier("mais « zona » est bien reconnue quand elle est citée",
         'aciclovir' in classes_attendues('Zona intercostal'), True)
verifier("le pluriel reste reconnu",
         'amoxicilline' in classes_attendues('Otites moyennes à répétition'), True)

verifier("un antibiotique est attendu pour une cystite",
         'antibiotique' in classes_attendues('Cystite aiguë simple'), True)


# ── 5. Les sources sont bien branchées ───────────────────────────────────

source = (Path(__file__).resolve().parent.parent / 'prescription_helper.py').read_text(
    encoding='utf-8')
verifier("classes_attendues consulte la table des pathologies",
         'PATHOLOGIE_CLASS_MAP' in source, True)
verifier("le rang n'est plus jeté à l'assemblage",
         "'rang'" in source, True)

app = (Path(__file__).resolve().parent.parent / 'app.py').read_text(encoding='utf-8')
# La notation a déménagé dans `appliquer_controles`, déclenchée par `contexte` :
# elle doit venir après la confrontation des substances, que seule la
# normalisation rend possible. La route se contente de fournir le texte.
verifier("la route diagnostic fournit le contexte qui déclenche la notation",
         'contexte=diagnostic' in app, True)
verifier("le tuyau note quand un contexte lui est donné",
         'compute_clinical_relevance(contexte, med)' in source, True)


# ── Relevé ───────────────────────────────────────────────────────────────

print()
print("  Repli sur « fièvre avec douleurs » :")
for m in repli:
    print("    %-16s %-18s %s" % (m['rang'], m['condition'], m['name']))

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
