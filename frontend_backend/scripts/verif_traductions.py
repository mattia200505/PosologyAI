"""Relève les clés `data-i18n` que `translations.js` ne définit pas.

Pourquoi ce banc existe
-----------------------
`getStaticTranslation()` se termine par ``return frText || key`` : quand la
clé manque, elle rend **la clé elle-même**, et `translatePage()` l'injecte en
`innerHTML`. Une clé oubliée n'échoue donc pas, elle affiche
``disclaimer_title`` en toutes lettres au milieu de la page. Rien ne le
signale : ni erreur, ni journal.

Tous les gabarits incluent `components/header.html`, qui charge
`translations.js` : la règle vaut pour toutes les pages, y compris celles qui
portent leur propre dictionnaire en ligne. Ce dictionnaire s'applique par
`if (trans[key])` et laisse donc le texte en place quand la clé lui manque,
mais il ne protège de rien : `translatePage()` est passée avant lui.

Emploi
------
    python scripts/verif_traductions.py

Sortie non nulle si une clé manque, pour que le balayage soit rejouable après
chaque nouvelle page — ce que le rapport de l'assistant de prescription
demandait au § 7.3.
"""

from __future__ import annotations

import re
import sys
from collections import defaultdict
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
GABARITS = RACINE / 'templates'
TRADUCTIONS = RACINE / 'static' / 'js' / 'translations.js'

#: Les trois attributs que `translatePage()` lit réellement. En ajouter un ici
#: sans l'ajouter là-bas ne servirait à rien.
ATTRIBUTS = ('data-i18n', 'data-i18n-placeholder', 'data-i18n-title')

_EMPLOI = re.compile(
    r'\b(' + '|'.join(re.escape(a) for a in ATTRIBUTS) + r')\s*=\s*"([^"]+)"')

#: `fr.cle = '...'` et `fr['cle'] = '...'`, les deux formes du fichier.
_DEFINITION = re.compile(r"""\bfr(?:\.([A-Za-z0-9_]+)|\[['"]([^'"]+)['"]\])\s*=""")


def cles_definies(source: str) -> set:
    """Rend les clés que `STATIC_TRANSLATIONS.fr` possède."""
    return {point or crochet for point, crochet in _DEFINITION.findall(source)}


def cles_employees(racine: Path) -> dict:
    """Rend, par gabarit, les clés que la page demande.

    Le chemin est relatif à `templates/` pour que le relevé reste lisible
    quand les gabarits vivent dans des sous-répertoires.
    """
    par_gabarit = defaultdict(set)
    for chemin in sorted(racine.rglob('*.html')):
        texte = chemin.read_text(encoding='utf-8', errors='replace')
        for _, cle in _EMPLOI.findall(texte):
            cle = cle.strip()
            # Une valeur composée n'est pas une clé : elle vient d'un gabarit
            # Jinja qui construit l'attribut, et le balayage ne peut rien en
            # dire de sûr.
            if cle and '{' not in cle:
                par_gabarit[chemin.relative_to(racine).as_posix()].add(cle)
    return par_gabarit


def cles_orphelines(definies: set, employees: dict) -> set:
    """Rend les clés définies que plus aucun gabarit ne demande.

    Elles ne cassent rien ; elles disent seulement que le dictionnaire garde
    la trace d'un écran disparu.
    """
    demandees = set()
    for cles in employees.values():
        demandees |= cles
    return definies - demandees


def main() -> int:
    if not TRADUCTIONS.exists():
        print("translations.js introuvable : %s" % TRADUCTIONS)
        return 2
    if not GABARITS.is_dir():
        print("Répertoire des gabarits introuvable : %s" % GABARITS)
        return 2

    definies = cles_definies(TRADUCTIONS.read_text(encoding='utf-8', errors='replace'))
    employees = cles_employees(GABARITS)

    manquantes = {}
    for gabarit, cles in sorted(employees.items()):
        absentes = sorted(cles - definies)
        if absentes:
            manquantes[gabarit] = absentes

    total_demandees = len({c for cles in employees.values() for c in cles})
    print("%d clés définies dans translations.js" % len(definies))
    print("%d clés demandées par %d gabarits" % (total_demandees, len(employees)))

    if manquantes:
        print()
        print("MANQUANTES — la page affichera la clé en clair :")
        for gabarit, cles in manquantes.items():
            print("  %s" % gabarit)
            for cle in cles:
                print("      %s" % cle)

    orphelines = cles_orphelines(definies, employees)
    if orphelines:
        print()
        print("Définies mais plus demandées (%d) — sans effet, à titre indicatif :"
              % len(orphelines))
        print("  " + ', '.join(sorted(orphelines)))

    print()
    if manquantes:
        total = sum(len(c) for c in manquantes.values())
        print("ÉCHEC : %d clé(s) manquante(s) sur %d gabarit(s)."
              % (total, len(manquantes)))
        return 1

    print("Aucune clé manquante.")
    return 0


if __name__ == '__main__':
    sys.exit(main())
