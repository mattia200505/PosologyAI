"""Banc des formulations réelles, des traitements en cours et de la biologie.

Ce que ce banc garde
--------------------

**Les formulations réelles.** Un dossier écrit « maladie rénale chronique
stade 3b », pas « insuffisance rénale ». Éprouvé sur un cas réel, l'ensemble
des antécédents d'un patient insuffisant cardiaque, rénal et diabétique ne
déclenchait **qu'une seule règle** : la reconnaissance exigeait « insuffisance »
et « rénale » dans le même segment, et le dossier n'employait ni l'un ni
l'autre. Un patient au DFG de 28 pouvait donc recevoir un AINS.

**Les traitements en cours.** Les contraintes ne portaient que sur les
médicaments *proposés*. Le même patient prenait 2 g de metformine par jour
avec un DFG de 28 — contre-indication formelle sous 30 — et rien ne le
signalait : ses traitements ne servaient qu'à chercher des interactions. C'est
pourtant là que se trouvent les erreurs qui durent depuis des mois.

Ils sont **signalés, jamais écartés** : on ne retire pas le traitement d'un
patient depuis un écran, on le porte à la connaissance du médecin.

**La biologie.** Un antécédent est un mot, un résultat est un nombre. « Maladie
rénale chronique » ne dit pas si la metformine est déconseillée ou interdite ;
un DFG à 28 le dit. Les seuils retenus sont ceux des RCP et se relisent dans
`SEUILS_BIOLOGIQUES`.

Emploi
------
    python scripts/verif_biologie.py

Aucune base n'est nécessaire.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from prescription_helper import (  # noqa: E402
    SEUILS_BIOLOGIQUES,
    contraintes_actives,
    contraintes_biologiques,
    traitements_a_reconsiderer,
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


def libelles(saisie: str) -> list:
    return sorted(r['libelle'] for r in contraintes_actives(saisie))


# ── 1. Les formulations réelles d'un dossier ─────────────────────────────

DOSSIER = ("Diabete de type 2, Insuffisance cardiaque chronique a fraction "
           "d ejection reduite, Fibrillation auriculaire permanente, "
           "Hypertension arterielle, Maladie renale chronique stade 3b, "
           "Steatohepatite non alcoolique, Infarctus du myocarde, "
           "Syndrome d apnees obstructives du sommeil, Hypercholesterolemie")

verifier("« maladie rénale chronique » déclenche la règle rénale",
         'insuffisance rénale' in libelles('Maladie renale chronique stade 3b'),
         True)
verifier("« néphropathie » aussi",
         'insuffisance rénale' in libelles('Nephropathie diabetique'), True)
verifier("« insuffisance rénale » n'a pas cessé de fonctionner",
         'insuffisance rénale' in libelles('Insuffisance renale legere'), True)

verifier("« décompensation cardiaque » déclenche la règle cardiaque",
         'insuffisance cardiaque' in libelles('Decompensation cardiaque globale'),
         True)
verifier("« cardiopathie ischémique » ne la déclenche pas\n"
         "      (une coronaropathie n'est pas une insuffisance cardiaque)",
         'insuffisance cardiaque' in libelles('Cardiopathie ischemique'), False)

# Le dossier réel doit maintenant déclencher les deux règles qui comptent.
declenchees = libelles(DOSSIER)
verifier("le dossier réel déclenche la règle rénale",
         'insuffisance rénale' in declenchees, True)
verifier("le dossier réel déclenche la règle cardiaque",
         'insuffisance cardiaque' in declenchees, True)

# Précision : le mot « rénale » seul ne suffit toujours pas, sinon on
# retomberait dans le faux positif du § 2.8.
verifier("« colique néphrétique » ne déclenche pas la règle rénale",
         'insuffisance rénale' in libelles('Colique nephretique'), False)
verifier("« maladie coeliaque » ne déclenche rien",
         libelles('Maladie coeliaque'), [])


# ── 2. Les traitements en cours sont confrontés eux aussi ────────────────

TRAITEMENTS = ['Metformine 1000 mg', 'Ibuprofene 400 mg si douleur',
               'Bisoprolol 5 mg', 'Omeprazole 20 mg']

releves = traitements_a_reconsiderer(TRAITEMENTS, 'Maladie renale chronique stade 3b')
vises = sorted(r['traitement'] for r in releves)

verifier("la metformine est signalée chez l'insuffisant rénal",
         'Metformine 1000 mg' in vises, True)
verifier("l'ibuprofène aussi", 'Ibuprofene 400 mg si douleur' in vises, True)
verifier("l'oméprazole ne l'est pas", 'Omeprazole 20 mg' in vises, False)

verifier("le relevé nomme l'antécédent en cause",
         releves[0]['antecedent'], 'insuffisance rénale')
verifier("il porte un motif lisible", len(releves[0]['motif']) > 10, True)

# Signalés, jamais retirés : on ne supprime pas le traitement d'un patient
# depuis un écran.
verifier("aucun traitement n'est retiré de la liste",
         len(TRAITEMENTS), 4)

verifier("sans antécédent contraignant, rien n'est signalé",
         traitements_a_reconsiderer(TRAITEMENTS, 'Appendicectomie'), [])
verifier("sans traitement, rien n'est signalé",
         traitements_a_reconsiderer([], 'Insuffisance renale'), [])
verifier("None ne casse pas", traitements_a_reconsiderer(None, None), [])

# Le bêta-bloquant chez l'asthmatique : le même mécanisme, sur un autre axe.
asthme = traitements_a_reconsiderer(['Bisoprolol 5 mg'], 'Asthme persistant')
verifier("le bêta-bloquant est signalé chez l'asthmatique",
         [r['traitement'] for r in asthme], ['Bisoprolol 5 mg'])


# ── 3. La biologie ───────────────────────────────────────────────────────

verifier("la table des seuils n'est pas vide", len(SEUILS_BIOLOGIQUES) > 0, True)
for seuil in SEUILS_BIOLOGIQUES:
    nom = seuil.get('libelle', '?')
    for champ in ('libelle', 'cibles', 'motif'):
        verifier("« %s » porte le champ %s" % (nom, champ), champ in seuil, True)
    verifier("« %s » porte des cibles" % nom, bool(seuil['cibles']), True)

    # Une règle porte soit mesure/sens/valeur — le cas courant, une seule
    # mesure — soit `conditions`, une liste de ces mêmes triplets. C'est ce
    # second cas qui fusionne PAS et PAD : deux nombres pour un seul fait
    # clinique, une seule pénalité au lieu de deux qui se déclenchaient
    # presque toujours ensemble.
    conditions = seuil.get('conditions') or [seuil]
    for condition in conditions:
        for champ in ('mesure', 'sens', 'valeur'):
            verifier("« %s » : chaque condition porte %s" % (nom, champ),
                     champ in condition, True)
        verifier("« %s » : sens de comparaison connu" % nom,
                 condition['sens'] in ('<', '>'), True)

# Le cas réel : DFG à 28, la metformine est formellement contre-indiquée.
regles = contraintes_biologiques({'dfg': 28})
cibles = {c for r in regles for c in r['cibles']}
verifier("un DFG à 28 vise la metformine", 'metformine' in cibles, True)
verifier("il vise aussi les AINS", 'ibuprofene' in cibles, True)

verifier("un DFG normal ne déclenche rien", contraintes_biologiques({'dfg': 90}), [])
verifier("un DFG à 45 déclenche la prudence, pas l'interdit",
         any('metformine' in r['cibles'] for r in contraintes_biologiques({'dfg': 45})),
         False)

# Potassium : le patient était à 5,8 sous spironolactone et sartan.
cibles_k = {c for r in contraintes_biologiques({'kaliemie': 5.8}) for c in r['cibles']}
verifier("une kaliémie à 5,8 vise la spironolactone",
         'spironolactone' in cibles_k, True)
verifier("une kaliémie normale ne déclenche rien",
         contraintes_biologiques({'kaliemie': 4.2}), [])

# Les épargneurs de potassium, tous. Le trou est apparu en P3b : la règle
# disait « diurétiques épargneurs de potassium » et ne nommait que deux d'entre
# eux. MODAMIDE — de l'amiloride — a été proposé à un patient à 5,8 mmol/L.
for epargneur in ['Spironolactone 25 mg', 'MODAMIDE 5 mg (amiloride)',
                  'Triamterene 50 mg', 'Eplerenone 25 mg']:
    verifier("« %s » est signalé si la kaliémie est haute" % epargneur[:30],
             bool(traitements_a_reconsiderer([epargneur], '', {'kaliemie': 5.8})),
             True)
verifier("un diurétique de l'anse ne l'est pas pour la kaliémie",
         bool(traitements_a_reconsiderer(['Furosemide 40 mg'], '',
                                         {'kaliemie': 5.8})), False)

verifier("une natrémie basse déclenche une règle",
         len(contraintes_biologiques({'natremie': 128})) > 0, True)
verifier("des transaminases élevées déclenchent une règle",
         len(contraintes_biologiques({'transaminases': 145})) > 0, True)

# Ne rien savoir n'est pas un résultat.
verifier("aucune mesure ne déclenche rien", contraintes_biologiques({}), [])
verifier("None ne casse pas", contraintes_biologiques(None), [])
verifier("une valeur vide est ignorée",
         contraintes_biologiques({'dfg': ''}), [])
verifier("une valeur non numérique est ignorée",
         contraintes_biologiques({'dfg': 'bas'}), [])


# ── 4. Le branchement ────────────────────────────────────────────────────

source = (Path(__file__).resolve().parent.parent / 'prescription_helper.py').read_text(
    encoding='utf-8')
verifier("le tuyau confronte les traitements en cours",
         'traitements_a_reconsiderer(' in source, True)
verifier("le tuyau lit la biologie", 'contraintes_biologiques(' in source, True)

gabarits = [(Path(__file__).resolve().parent.parent / 'templates' / n).read_text(
    encoding='utf-8') for n in ('prescription_assistant.html',
                                'diagnostic_prescription.html')]
for i, g in enumerate(gabarits):
    nom = ('assistant', 'diagnostic')[i]
    verifier("%s : le formulaire porte un champ DFG" % nom, 'dfg' in g, True)
    verifier("%s : le formulaire porte un champ kaliémie" % nom,
             'kaliemie' in g, True)

module = (Path(__file__).resolve().parent.parent / 'static' / 'js'
          / 'prescription_resultats.js').read_text(encoding='utf-8')
verifier("l'écran affiche les traitements à reconsidérer",
         'traitements_a_reconsiderer' in module, True)


# ── Relevé ───────────────────────────────────────────────────────────────

print()
print("  Dossier réel -> règles déclenchées : %s" % ', '.join(declenchees))
print("  Traitements à reconsidérer (DFG bas) : %s" % ', '.join(vises))
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
