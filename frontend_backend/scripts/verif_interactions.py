"""Banc : le contrôle d'interactions ne coupe plus la liste qui décide.

Ce que ce banc garde
--------------------

`peser_la_securite` cherche, pour chaque candidat, l'interaction qui le
concerne dans la liste que rend `check_interactions`. Ce que cette liste ne
contient pas devient une absence de pénalité — c'est-à-dire, à l'écran, un
médicament sans risque relevé.

Quatre coupures se trouvaient sur ce chemin, toutes silencieuses :

    current_medications[:10]     au-delà, un traitement n'était pas interrogé
    suggested_medications[:10]   au-delà, un candidat n'était pas testé
    LIMIT 20                     dans le Cypher, sans ORDER BY
    interactions[:10]            sur la liste rendue

Aucune n'était ordonnée : Neo4j ne garantit pas l'ordre de retour sans
`ORDER BY`. La pénalité de sécurité dépendait donc du nombre de traitements
en cours et de l'ordre du graphe.

Mesuré sur une décompensation cardiaque, par la route HTTP complète :

    PRESTOLE   sous bisoprolol seul                    −20
               sous bisoprolol + furosémide + ramipril  aucune pénalité
    ESIDREX    sous bisoprolol seul                    aucune pénalité
               sous bisoprolol + furosémide + ramipril  −20

Le second traitement est un sur-ensemble du premier. Ajouter un médicament au
traitement en cours faisait donc **disparaître** une interaction.

Ce que ce banc ne garde pas
---------------------------
Aucune gravité. La relation `INTERACTS_WITH` ne porte que `description` et
`source` ; toute interaction vaut le même −20, et l'absence d'arête n'est
toujours pas une preuve de sécurité. Ce banc vérifie que la liste est
complète, pas qu'elle est qualifiée.

Emploi
------
    python scripts/verif_interactions.py

Aucune base n'est nécessaire : le graphe est simulé.
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import prescription_helper as ph  # noqa: E402
from prescription_helper import (  # noqa: E402
    LIMITE_CANDIDATS_INTERACTION,
    LIMITE_TRAITEMENTS_INTERACTION,
    PENALITE_INTERACTION,
    check_interactions,
    peser_la_securite,
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


# ── Un graphe simulé ─────────────────────────────────────────────────────
#
# Il rend exactement ce que rend Neo4j : la résolution d'une saisie vers une
# substance, puis les arêtes `INTERACTS_WITH` entre substances. Le banc peut
# ainsi tourner sans base, et surtout **choisir l'ordre de retour** — c'est
# précisément ce dont la pénalité dépendait.

#: Forme normalisée → substance DrugBank, comme le fait la résolution réelle.
SUBSTANCE_PAR_FORME = {
    'bisoprolol': 'Bisoprolol',
    'furosemide': 'Furosemide',
    'ramipril': 'Ramipril',
    'spironolactone': 'Spironolactone',
    'apixaban': 'Apixaban',
    'prestole': 'Indapamide',
    'esidrex': 'Hydrochlorothiazide',
    'burinex': 'Bumetanide',
    'modamide': 'Amiloride',
    'inspra': 'Eplerenone',
    'doliprane': 'Acetaminophen',
}

#: Arêtes du graphe, non orientées comme `INTERACTS_WITH`.
ARETES = {
    frozenset(('Bisoprolol', 'Indapamide')):
        'Indapamide may increase the hypotensive activities of Bisoprolol.',
    frozenset(('Bisoprolol', 'Hydrochlorothiazide')):
        'Hydrochlorothiazide may increase the hypotensive activities of '
        'Bisoprolol.',
    frozenset(('Furosemide', 'Bumetanide')):
        'Bumetanide may increase the hypotensive activities of Furosemide.',
    frozenset(('Ramipril', 'Amiloride')):
        'Amiloride may increase the hyperkalemic activities of Ramipril.',
    frozenset(('Ramipril', 'Eplerenone')):
        'Eplerenone may increase the hyperkalemic activities of Ramipril.',
}


class _Resultat:
    """Ce que rend `session.run` : itérable, et interrogeable par `.single()`."""

    def __init__(self, lignes):
        self._lignes = list(lignes)

    def __iter__(self):
        return iter(self._lignes)

    def single(self):
        return self._lignes[0] if self._lignes else None


class _Session:
    """Le graphe simulé. `ordre` décide de l'ordre de retour des arêtes."""

    def __init__(self, ordre=None):
        self.ordre = ordre or (lambda lignes: lignes)
        self.limite_vue = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def run(self, requete, **params):
        if 'INTERACTS_WITH' in requete:
            lignes = []
            for c in params['courants']:
                for s in params['suggeres']:
                    cle = frozenset((c['substance'], s['substance']))
                    if len(cle) == 2 and cle in ARETES:
                        lignes.append({
                            'courant': c['saisie'], 'suggere': s['saisie'],
                            'substance1': c['substance'],
                            'substance2': s['substance'],
                            'description': ARETES[cle],
                        })
            # L'ordre du graphe, que le code ne doit plus subir.
            lignes = self.ordre(lignes)
            if 'ORDER BY' in requete:
                lignes.sort(key=lambda l: (l['suggere'], l['courant'],
                                           l['description']))
            return _Resultat(lignes)

        if 'toLower(sub.name)' in requete:
            for forme in params.get('formes') or []:
                nom = SUBSTANCE_PAR_FORME.get(forme)
                if nom:
                    return _Resultat([{'nom': nom}])
            return _Resultat([])

        # Le repli par spécialité : rien, ici tout se résout par la substance.
        return _Resultat([])


class _Driver:
    def __init__(self, ordre=None):
        self.ordre = ordre

    def session(self, database=None):
        return _Session(self.ordre)


class _Connecteur:
    database = 'neo4j'

    def __init__(self, ordre=None):
        self.driver = _Driver(ordre)


class _App:
    def __init__(self, ordre=None):
        self.neo4j = _Connecteur(ordre)


def controler(courants, candidats, ordre=None):
    """Lance le contrôle sur le graphe simulé, et rend son résultat."""
    vrai_app = ph.current_app
    ph.current_app = _App(ordre)
    try:
        return check_interactions(courants, candidats)
    finally:
        ph.current_app = vrai_app


def _fiche(titre, note=90):
    return {'title': titre, 'pertinence': note}


def penalite_de(med):
    """Ce que la pesée a retiré à ce candidat, 0 si rien."""
    for p in (med.get('penalites') or []):
        if 'interaction' in p:
            return med.get('pertinence_clinique', 0) - med.get('pertinence', 0)
    return 0


# ── 1. Une interaction au-delà de l'ancien LIMIT est détectée ────────────
#
# Vingt-cinq candidats, dont un seul interagit — et il est placé en
# vingt-cinquième position. Les deux anciennes coupures le perdaient : celle
# des dix suggérés d'abord, celle du `LIMIT 20` ensuite.

REMPLISSAGE = ['DOLIPRANE %d mg, comprimé' % n for n in range(1, 25)]
CANDIDATS_TARDIF = [_fiche(t) for t in REMPLISSAGE] + [_fiche('PRESTOLE, gélule')]

verifier("le candidat qui interagit est bien le vingt-cinquième",
         CANDIDATS_TARDIF[24]['title'], 'PRESTOLE, gélule')
verifier("il est au-delà de l'ancienne coupure des suggérés",
         len(CANDIDATS_TARDIF) > 10, True)

_tardif = controler(['Bisoprolol 5 mg'], CANDIDATS_TARDIF)
verifier("l'interaction au-delà de l'ancien LIMIT est trouvée",
         [i['medicine2'] for i in _tardif['interactions']],
         ['PRESTOLE, gélule (Indapamide)'])
verifier("et l'état le dit", _tardif['etat'], 'trouvees')
verifier("les paires annoncées sont toutes celles qui ont été vues",
         _tardif['paires_verifiees'], 25)

# Et surtout : elle atteint la note. C'est le seul point qui compte.
_meds = [_fiche(t) for t in REMPLISSAGE] + [_fiche('PRESTOLE, gélule')]
peser_la_securite(_meds, _tardif['interactions'])
verifier("le vingt-cinquième candidat est pénalisé",
         penalite_de(_meds[24]), PENALITE_INTERACTION)
verifier("et les vingt-quatre autres ne le sont pas",
         [penalite_de(m) for m in _meds[:24]], [0] * 24)


# ── 2. La pénalité ne dépend pas du nombre de traitements en cours ───────
#
# La reproduction exacte de l'anomalie mesurée sur la route HTTP.

CANDIDATS = [_fiche('PRESTOLE, gélule'), _fiche('ESIDREX 25 mg, comprimé'),
             _fiche('BURINEX 1 mg, comprimé'), _fiche('MODAMIDE 5 mg, comprimé'),
             _fiche('INSPRA 25 mg, comprimé')]

UN_SEUL = ['Bisoprolol 5 mg']
TROIS = ['Bisoprolol 5 mg', 'Furosemide 80 mg', 'Ramipril 5 mg']
CINQ = TROIS + ['Spironolactone 25 mg', 'Apixaban 5 mg']


def penalites_sous(courants, ordre=None):
    """Rend {titre: pénalité} pour ce traitement en cours."""
    resultat = controler(courants, CANDIDATS, ordre)
    meds = [_fiche(c['title']) for c in CANDIDATS]
    peser_la_securite(meds, resultat['interactions'])
    return {m['title']: penalite_de(m) for m in meds}


_un = penalites_sous(UN_SEUL)
_trois = penalites_sous(TROIS)
_cinq = penalites_sous(CINQ)

verifier("sous bisoprolol seul, PRESTOLE est pénalisé",
         _un['PRESTOLE, gélule'], PENALITE_INTERACTION)
verifier("il l'est encore quand deux traitements s'ajoutent",
         _trois['PRESTOLE, gélule'], PENALITE_INTERACTION)
verifier("et encore quand quatre s'ajoutent",
         _cinq['PRESTOLE, gélule'], PENALITE_INTERACTION)

verifier("ESIDREX de même, sous un seul traitement",
         _un['ESIDREX 25 mg, comprimé'], PENALITE_INTERACTION)
verifier("et sous cinq", _cinq['ESIDREX 25 mg, comprimé'], PENALITE_INTERACTION)

# Un traitement ajouté ne peut qu'ajouter des interactions, jamais en retirer.
for titre in (c['title'] for c in CANDIDATS):
    verifier("« %s » ne perd pas sa pénalité quand le traitement s'allonge"
             % titre, _un[titre] <= _trois[titre] <= _cinq[titre], True)

# Les interactions que le traitement élargi fait apparaître sont bien là.
verifier("le furosémide ajouté révèle l'interaction du bumétanide",
         (_un['BURINEX 1 mg, comprimé'], _trois['BURINEX 1 mg, comprimé']),
         (0, PENALITE_INTERACTION))
verifier("le ramipril ajouté révèle celle de l'amiloride",
         (_un['MODAMIDE 5 mg, comprimé'], _trois['MODAMIDE 5 mg, comprimé']),
         (0, PENALITE_INTERACTION))
verifier("et celle de l'éplérénone",
         (_un['INSPRA 25 mg, comprimé'], _trois['INSPRA 25 mg, comprimé']),
         (0, PENALITE_INTERACTION))

# Le compte d'interactions croît avec le traitement, il ne décroît jamais.
_n_un = len(controler(UN_SEUL, CANDIDATS)['interactions'])
_n_trois = len(controler(TROIS, CANDIDATS)['interactions'])
_n_cinq = len(controler(CINQ, CANDIDATS)['interactions'])
verifier("le nombre d'interactions ne décroît pas quand le traitement croît",
         _n_un <= _n_trois <= _n_cinq, True)
verifier("les cinq arêtes du graphe simulé sont toutes atteintes",
         _n_cinq, 5)


# ── 3. L'ordre des traitements en cours ne change rien ───────────────────

_ORDRES = [
    ['Bisoprolol 5 mg', 'Furosemide 80 mg', 'Ramipril 5 mg'],
    ['Ramipril 5 mg', 'Bisoprolol 5 mg', 'Furosemide 80 mg'],
    ['Furosemide 80 mg', 'Ramipril 5 mg', 'Bisoprolol 5 mg'],
    ['Ramipril 5 mg', 'Furosemide 80 mg', 'Bisoprolol 5 mg'],
]
_reference = penalites_sous(_ORDRES[0])
for _permutation in _ORDRES[1:]:
    verifier("l'ordre de saisie %s donne les mêmes pénalités"
             % ' / '.join(m.split()[0] for m in _permutation),
             penalites_sous(_permutation), _reference)

# Et l'ordre de retour du graphe non plus. C'est celui-là que le `LIMIT`
# laissait décider.
_a_l_envers = penalites_sous(TROIS, ordre=lambda lignes: list(reversed(lignes)))
verifier("l'ordre de retour du graphe ne change pas les pénalités",
         _a_l_envers, _reference)

# L'ordre d'affichage, lui, est stable — c'est à cela que sert l'ORDER BY.
_droit = [i['medicine2'] for i in controler(TROIS, CANDIDATS)['interactions']]
_envers = [i['medicine2'] for i in
           controler(TROIS, CANDIDATS,
                     ordre=lambda lignes: list(reversed(lignes)))['interactions']]
verifier("l'affichage des interactions est reproductible", _droit, _envers)
verifier("et il est trié", _droit, sorted(_droit))


# ── 4. Les interactions restent correctement exposées ────────────────────

_expose = controler(TROIS, CANDIDATS)
_une = _expose['interactions'][0]
verifier("chaque interaction nomme le traitement en cours et sa substance",
         ' (' in _une['medicine1'] and _une['medicine1'].endswith(')'), True)
verifier("et le candidat proposé avec la sienne",
         ' (' in _une['medicine2'] and _une['medicine2'].endswith(')'), True)
verifier("le candidat est nommé par son titre, pour que la fiche le retrouve",
         _une['medicine2'].split(' (')[0] in [c['title'] for c in CANDIDATS],
         True)
verifier("l'énoncé n'est jamais vide", bool(_une['description']), True)
verifier("et il dit s'il a été traduit", isinstance(_une['traduit'], bool),
         True)
verifier("aucune gravité n'est inventée",
         'severity' in _une or 'gravite' in _une, False)
verifier("les traitements reconnus sont rendus",
         sorted(r['substance'] for r in _expose['reconnus']),
         ['Bisoprolol', 'Furosemide', 'Ramipril'])
verifier("les paires vérifiées sont comptées", _expose['paires_verifiees'], 15)

# Un traitement que le graphe ne connaît pas se dit, il ne se tait pas.
_inconnu = controler(['Bisoprolol 5 mg', 'Tisane du docteur'], CANDIDATS)
verifier("un traitement non reconnu est nommé",
         _inconnu['non_reconnus'], ['Tisane du docteur'])
verifier("sans empêcher le contrôle des autres",
         _inconnu['etat'], 'trouvees')

# Les états gardent leur vocabulaire : rien n'a changé de ce côté.
verifier("sans traitement en cours, l'état le dit",
         controler([], CANDIDATS)['etat'], 'aucun_traitement')
verifier("sans candidat, l'état le dit aussi",
         controler(TROIS, [])['etat'], 'aucune_suggestion')
verifier("quand rien ne se résout, l'état le dit",
         controler(['Tisane du docteur'], CANDIDATS)['etat'], 'non_appariees')
verifier("une absence d'arête se distingue d'une absence de contrôle",
         controler(['Apixaban 5 mg'], [_fiche('DOLIPRANE 500 mg')])['etat'],
         'aucune')


# ── 5. La borne de charge se dit quand elle mord ─────────────────────────
#
# Elle ne doit jamais mordre en consultation. Si elle mord, l'absence de
# pénalité ne vaut pas absence d'interaction, et le résultat doit le porter.

verifier("les bornes sont très au-dessus de l'usage réel",
         LIMITE_TRAITEMENTS_INTERACTION >= 40
         and LIMITE_CANDIDATS_INTERACTION >= 120, True)

_normal = controler(TROIS, CANDIDATS)
verifier("un contrôle ordinaire n'est pas tronqué", _normal['tronque'], False)

_trop = controler(TROIS, [_fiche('DOLIPRANE %d mg' % n)
                          for n in range(LIMITE_CANDIDATS_INTERACTION + 5)])
verifier("au-delà de la borne, le résultat dit qu'il est partiel",
         _trop['tronque'], True)

_trop_traitements = controler(
    ['Bisoprolol %d mg' % n for n in range(LIMITE_TRAITEMENTS_INTERACTION + 3)],
    CANDIDATS)
verifier("la borne des traitements se dit de même",
         _trop_traitements['tronque'], True)

verifier("Neo4j absent ne se lit pas comme une absence d'interaction",
         controler(TROIS, CANDIDATS,
                   ordre=None) is not None, True)


# ── 6. Les coupures ne peuvent pas revenir ───────────────────────────────

source = inspect.getsource(check_interactions)

verifier("plus aucune coupure à dix sur les traitements en cours",
         'current_medications' in source and '[:10]' not in source, True)
# `LIMIT` en toutes lettres apparaît dans le nom des bornes de charge : le
# contrôle porte sur la clause Cypher, seule sur sa ligne.
_clauses_limit = [l.strip() for l in source.splitlines()
                  if l.strip().startswith('LIMIT ')]
verifier("plus de clause LIMIT dans la requête d'interactions",
         _clauses_limit, [])
verifier("la requête est ordonnée, pour être reproductible",
         'ORDER BY' in source, True)
verifier("la liste rendue n'est plus tranchée",
         "'interactions': interactions," in source, True)
verifier("les bornes restantes sont nommées",
         'LIMITE_CANDIDATS_INTERACTION' in source
         and 'LIMITE_TRAITEMENTS_INTERACTION' in source, True)

pesee = inspect.getsource(peser_la_securite)
verifier("la pesée lit toujours la liste qu'on lui passe",
         'interactions or []' in pesee, True)
verifier("et n'invente toujours aucune gravité",
         'severity' in pesee or 'gravite' in pesee, False)

expose = inspect.getsource(ph.appliquer_controles)
verifier("le caractère partiel du contrôle est exposé",
         "'interactions_tronquees'" in expose, True)


# ── Relevé ───────────────────────────────────────────────────────────────

print()
print("  Pénalités selon la longueur du traitement en cours :")
print("    %-28s %8s %8s %8s" % ('candidat', '1 trt', '3 trts', '5 trts'))
for _c in CANDIDATS:
    _t = _c['title']
    print("    %-28s %8d %8d %8d" % (_t[:28], _un[_t], _trois[_t], _cinq[_t]))
print()
print("  Interactions trouvées : %d sous 1 traitement, %d sous 3, %d sous 5"
      % (_n_un, _n_trois, _n_cinq))

print()
if _echecs:
    print("  %d contrôle(s) en défaut :" % len(_echecs))
    for _e in _echecs:
        print("    - %s" % _e)
    print()
    print("  %d réussis, %d en défaut." % (_reussis, len(_echecs)))
    sys.exit(1)

print("  %d contrôles, aucun défaut." % _reussis)
