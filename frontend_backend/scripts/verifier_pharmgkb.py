# -*- coding: utf-8 -*-
"""Controles de non-regression sur le profil pharmacogenomique.

Ce que ces controles protegent
------------------------------
Deux decisions de la construction ne se voient pas a la lecture du resultat,
et se casseraient en silence :

1. **Les associations ne sont pas decoupees.** Cinq annotations PharmGKB
   portent deux molecules separees par un point-virgule, sans dire laquelle
   porte le gene. Decouper `acetaminophen; tramadol` attacherait le CYP2D6
   du tramadol au paracetamol seul, donc a toutes les presentations de
   DOLIPRANE. Le controle A verifie que le paracetamol ne porte aucun gene.

2. **« No Clinical PGx » ne declenche aucune alerte.** Ce niveau dit qu'il
   n'y a rien a faire ; le presenter comme les autres inverserait le sens
   de ce que l'agence a ecrit. Le controle D verifie qu'il ne met jamais
   `conduite` a vrai.

Les autres controles ancrent des faits pharmacologiques connus : si le
DPYD disparaissait du fluorouracile, la jointure serait cassee.

    python scripts/verifier_pharmgkb.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'))

import pharmacogenomique as P

_ok = 0
_ko = []


def att(intitule, obtenu, attendu):
    global _ok
    if obtenu == attendu:
        _ok += 1
        print('  [OK ] %s' % intitule)
    else:
        _ko.append(intitule)
        print('  [KO ] %s\n         obtenu %r, attendu %r' % (intitule, obtenu, attendu))


def profil_du_titre(base, motif):
    fiche = base['medicines'].find_one({'title': {'$regex': motif}}, {'_id': 1, 'url': 1})
    if not fiche:
        return None, None
    return fiche, P.profil(fiche, base)


def genes(profil):
    return [] if not profil else [g['symbole'] for g in profil['genes']]


def main():
    uri = os.getenv('MONGO_URI', 'mongodb://localhost:27017/medicsearch')
    base = MongoClient(uri, serverSelectionTimeoutMS=5000)[os.getenv('MONGO_DB', 'medicsearch')]

    print("\nA — une association ne prete jamais son gene a l'un de ses composants")
    molecule = base['pharmgkb_par_substance'].find_one({'_id': 'DB00316'})
    att('le paracetamol est bien indexe', bool(molecule), True)
    att('...et ne porte aucun gene', (molecule or {}).get('genes'), [])
    att('...ni de guide posologique', (molecule or {}).get('guide_posologie'), False)
    _, pgx = profil_du_titre(base, '^DOLIPRANE 100')
    att('une fiche DOLIPRANE n’herite pas du CYP2D6 du tramadol', genes(pgx), [])
    att('...mais sa section reste affichee', pgx is not None, True)

    print('\nB — les faits pharmacologiques connus tiennent')
    for motif, symbole in (('^CLOPIDOGREL ACCORD', 'CYP2C19'),
                           ('^TRAMADOL ALMUS', 'CYP2D6'),
                           ('^ABACAVIR ARROW', 'HLA-B'),
                           ('^SIMVASTATINE ACCORD', 'SLCO1B1')):
        fiche, pgx = profil_du_titre(base, motif)
        if fiche is None:
            print('  [--] %s absent du catalogue, controle saute' % motif)
            continue
        att('%s porte %s' % (motif.lstrip('^'), symbole), symbole in genes(pgx), True)

    print('\nC — le fluorouracile exige le test du DPYD')
    fiche, pgx = profil_du_titre(base, '^FLUOROURACILE')
    if fiche is None:
        print('  [--] absent du catalogue, controle saute')
    else:
        dpyd = next((g for g in (pgx['genes'] if pgx else []) if g['symbole'] == 'DPYD'), None)
        att('le DPYD est nomme', bool(dpyd), True)
        att('...au niveau le plus exigeant', (dpyd or {}).get('niveau'), 'Testing Required')
        att('...et la fiche signale une conduite a tenir', pgx['conduite'], True)

    print("\nD — « No Clinical PGx » ne declenche jamais d'alerte")
    vus = 0
    for molecule in base['pharmgkb_par_substance'].find({'niveau_max': 'No Clinical PGx'}):
        vus += 1
        faux = {'molecules': [molecule], 'genes': molecule['genes']}
        rang = molecule['genes'][0]['rang'] if molecule['genes'] else P.RANG_ABSENT
        if rang < P.RANG_SANS_CONDUITE:
            _ko.append('molecule %s classee conduite a tenir' % molecule['_id'])
    att('au moins une molecule a ce niveau', vus > 0, True)
    att('aucune n’est classee « conduite a tenir »',
        [k for k in _ko if 'conduite a tenir' in k], [])

    print('\nE — les trois absences restent distinctes')
    fiche, pgx = profil_du_titre(base, '^A 313')
    att('specialite hors PharmGKB : pas de section', pgx, None)
    _, connu = profil_du_titre(base, '^DOLIPRANE 100')
    att('molecule connue sans gene : section, liste vide', connu is not None and connu['genes'] == [], True)
    _, agi = profil_du_titre(base, '^CLOPIDOGREL ACCORD')
    att('gene avec conduite : section et signalement', agi is not None and agi['conduite'], True)

    print('\nF — le repli par URL sert les fiches traduites')
    fr = base['medicines'].find_one({'title': {'$regex': '^CLOPIDOGREL ACCORD'}}, {'_id': 1, 'url': 1})
    if fr:
        inconnu = {'_id': 'identifiant-absent', 'url': fr['url']}
        att('un _id inconnu retombe sur l’URL', genes(P.profil(inconnu, base)), ['CYP2C19'])
        att('sans URL ni _id connu, rien', P.profil({'_id': 'x'}, base), None)

    print()
    print('=' * 70)
    if _ko:
        print('%d controle(s) en defaut : %s' % (len(_ko), ', '.join(_ko)))
        return 1
    print('%d controles, aucun defaut.' % _ok)
    return 0


if __name__ == '__main__':
    sys.exit(main())
