"""Banc de la confrontation des substances annoncées.

Ce que ce banc garde
--------------------
La prescription par diagnostic laisse un modèle de langage choisir les
médicaments, et ce modèle annonce leur substance. Mesuré sur « pneumonie
communautaire » :

    HELIKIT 75 mg   substance annoncée : « Clarithromycine »
                    substance en base  : « urée 13 C »

HELIKIT est un test respiratoire à l'urée pour détecter *H. pylori*. Il ne
contient aucun antibiotique.

**Le pire n'était pas l'invention, c'était sa validation.** La notation lisait
la substance *annoncée* : « clarithromycine » figurant dans la table des
pathologies, elle accordait 50 points à un test diagnostique proposé comme
antibiotique. Le score, censé mesurer la pertinence, récompensait une
hallucination — et la fiche portant la vraie substance était relue dix lignes
plus loin, pour les contre-indications.

La notation lit désormais la fiche. L'écart, lui, n'est pas tu : il est le
signal le plus utile de tout l'écran, puisqu'il dit que le modèle a parlé de ce
qu'il ne connaissait pas.

Emploi
------
    python scripts/verif_substances.py

La confrontation elle-même demande MongoDB ; la comparaison est pure et
s'éprouve sans base.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from prescription_helper import ecart_de_substance  # noqa: E402

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


# ── 1. Le cas mesuré ─────────────────────────────────────────────────────

verifier("« Clarithromycine » annoncée pour de l'urée 13 C est un écart",
         ecart_de_substance('Clarithromycine', ['urée 13 C']), True)


# ── 2. Ce qui ne doit pas être signalé ───────────────────────────────────

verifier("une substance juste ne déclenche rien",
         ecart_de_substance('Périndopril', ['Périndopril']), False)
verifier("la casse ne fait pas un écart",
         ecart_de_substance('Amoxicilline', ['amoxicilline']), False)
verifier("l'accent ne fait pas un écart",
         ecart_de_substance('Budesonide', ['Budésonide']), False)

# Une fiche nomme souvent le sel ou la forme : « périndopril arginine » pour
# « périndopril ». Ce n'est pas une invention, c'est une précision.
verifier("le sel n'est pas un écart",
         ecart_de_substance('Périndopril', ['périndopril arginine']), False)
verifier("l'inverse non plus",
         ecart_de_substance('Périndopril arginine', ['Périndopril']), False)

# Une association : la substance annoncée est l'une des deux.
verifier("une substance parmi plusieurs n'est pas un écart",
         ecart_de_substance('Amoxicilline',
                            ['Amoxicilline', 'Acide clavulanique']), False)


# ── 3. Les cas où l'on ne peut rien affirmer ─────────────────────────────

# Ne rien savoir n'est pas la même chose que constater un écart. Signaler dans
# le doute ferait perdre au signalement tout son poids.
verifier("sans substance annoncée, aucun écart",
         ecart_de_substance('', ['Paracétamol']), False)
verifier("sans substance en base, aucun écart",
         ecart_de_substance('Paracétamol', []), False)
verifier("sans rien du tout, aucun écart", ecart_de_substance('', []), False)
verifier("None ne casse pas", ecart_de_substance(None, None), False)

# Un fragment trop court rencontrerait n'importe quoi par inclusion.
verifier("un fragment de deux lettres ne vaut pas correspondance",
         ecart_de_substance('ur', ['urée 13 C']), True)


# ── 4. Le branchement ────────────────────────────────────────────────────

source = (Path(__file__).resolve().parent.parent / 'prescription_helper.py').read_text(
    encoding='utf-8')
verifier("confronter_substances existe",
         'def confronter_substances(' in source, True)

# La confrontation vit dans `appliquer_controles`, après la normalisation :
# c'est elle qui résout `fiche_id`, au besoin par la spécialité représentative
# d'une dénomination commune. Placée avant, la confrontation ne trouvait aucun
# identifiant et ne faisait rien — sans le dire.
tuyau = source[source.index('def appliquer_controles'):]
tuyau = tuyau[:tuyau.index('\ndef ', 10)]
verifier("le tuyau normalise avant de confronter",
         tuyau.index('normaliser_medicament') < tuyau.index('confronter_substances'),
         True)
verifier("le tuyau confronte avant de noter",
         tuyau.index('confronter_substances') < tuyau.index('compute_clinical_relevance'),
         True)
verifier("le tuyau note avant de trier",
         tuyau.index('compute_clinical_relevance') < tuyau.index('_ordre_therapeutique'),
         True)

app = (Path(__file__).resolve().parent.parent / 'app.py').read_text(encoding='utf-8')
verifier("la route diagnostic passe le diagnostic comme contexte",
         'contexte=diagnostic' in app, True)
verifier("elle ne note plus elle-même, avant le tuyau",
         'prescription_helper.compute_clinical_relevance' in app, False)

module = (Path(__file__).resolve().parent.parent / 'static' / 'js'
          / 'prescription_resultats.js').read_text(encoding='utf-8')
verifier("l'écran affiche l'écart", 'substance_annoncee' in module, True)

# L'annonce se lit sous ses deux formes. Elle est dans `substance` avant la
# normalisation, et repliée dans `substances` après : ne lire que la première
# laissait passer l'écart en silence, une fois la normalisation faite — et la
# confrontation a lieu justement après.
confrontation = source[source.index('def confronter_substances'):]
confrontation = confrontation[:confrontation.index('\ndef ', 10)]
verifier("l'annonce est cherchée dans `substances` aussi",
         "med.get('substances')" in confrontation, True)
verifier("la fiche remplace bien la substance retenue",
         "med['substances'] = list(reelles)" in confrontation, True)

# `normaliser_medicament` reconstruit un dictionnaire champ par champ : le
# signalement doit y figurer, sinon il disparaît entre la confrontation et
# l'écran — c'est ainsi que le rang thérapeutique se perdait (§ 7.10).
verifier("le signalement survit à la normalisation",
         "'substance_annoncee': med.get('substance_annoncee')" in source, True)


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
