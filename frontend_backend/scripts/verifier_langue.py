# -*- coding: utf-8 -*-
"""Le choix de langue atteint-il le rendu serveur ?

Ce que ce controle protege
--------------------------
Le site traduit par deux mecanismes qui ne se parlaient pas :

- `translations.js`, cote client, remplace le texte des elements portant
  `data-i18n`. Il ecrit la preference dans `localStorage`.
- `libelle()`, cote serveur, rend 148 libelles — dont 136 sur la seule
  fiche medicament. Il lit la langue dans la requete.

Trois defauts se cumulaient, et le resultat visible etait « le site n'est
pas traduit » alors que la moitie cliente fonctionnait :

1. `medicine_details.html` ouvrait par
   `{% set lang = request.args.get('lang', 'fr') %}`, qui **ecrasait** le
   `lang` calcule par la route. Seule une langue ecrite dans l'URL
   passait ; le cookie que la route lisait etait annule par le gabarit.
2. Le selecteur n'ecrivait que `localStorage`. Le serveur, lui, lit un
   cookie. Personne ne l'ecrivait : le choix ne franchissait pas le
   reseau.
3. Six routes sur sept ne lisaient la langue que dans l'URL.

    python scripts/verifier_langue.py
"""
import os
import re
import sys

import requests

BASE = os.getenv('BASE_URL', 'http://localhost:5000')
DELAI = 240

_ok, _ko = 0, []


def att(intitule, obtenu, attendu):
    global _ok
    if obtenu == attendu:
        _ok += 1
        print('  [OK ] %s' % intitule)
    else:
        _ko.append(intitule)
        print('  [KO ] %s\n         obtenu %r, attendu %r' % (intitule, obtenu, attendu))


def titres(chemin, params=None, cookies=None):
    """Les premiers titres de section rendus par le serveur."""
    r = requests.get(BASE + chemin, params=params or {}, cookies=cookies or {},
                     timeout=DELAI)
    return re.findall(r'<h2>([^<]{3,48})</h2>', r.text)[:4]


def anglais(liste):
    """Vrai si aucun titre ne porte de marque francaise."""
    return liste and not any(re.search(r'[éèêàçù]|^Résumé|essentielles|moléculaire',
                                       t) for t in liste)


def premiere_fiche():
    from pymongo import MongoClient
    base = MongoClient(os.getenv('MONGO_URI', 'mongodb://localhost:27017'),
                       serverSelectionTimeoutMS=5000)['medicsearch']
    d = base['medicines'].find_one({'title': {'$regex': '^CLOPIDOGREL'}}, {'_id': 1})
    return '/medicine/%s' % d['_id']


def main():
    fiche = premiere_fiche()

    print('\nA — la fiche suit la langue passee dans l\'URL')
    fr = titres(fiche)
    en = titres(fiche, params={'lang': 'en'})
    att('sans parametre, la fiche est en francais', anglais(fr), False)
    att('avec ?lang=en, la fiche est en anglais', anglais(en), True)

    print('\nB — la fiche suit le cookie, que le selecteur ecrit')
    par_cookie = titres(fiche, cookies={'preferred_lang': 'en'})
    att('avec le cookie preferred_lang=en, la fiche est en anglais',
        anglais(par_cookie), True)
    att('le cookie donne le meme rendu que le parametre', par_cookie, en)

    print('\nC — le gabarit ne redefinit plus la langue')
    gabarit = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           'templates', 'medicine_details.html')
    with open(gabarit, encoding='utf-8') as f:
        source = f.read()
    # Les commentaires Jinja sont retires avant de chercher : la premiere
    # version de ce controle trouvait le `set lang` **cite dans le
    # commentaire** qui explique justement pourquoi il a ete supprime, et
    # echouait donc sur un fichier corrige.
    code_seul = re.sub(r'{#.*?#}', '', source, flags=re.S)
    att('aucun « set lang » ne masque la variable de la route',
        bool(re.search(r'{%\s*set\s+lang\s*=', code_seul)), False)
    att('le gabarit se declare traduit par le serveur',
        'data-langue-serveur' in code_seul, True)

    print('\nD — une seule facon de lire la langue, pour toutes les routes')
    appli = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         'app.py')
    with open(appli, encoding='utf-8') as f:
        code = f.read()
    att('un point unique la calcule', 'def langue_demandee(' in code, True)
    # Une route qui rend un gabarit traduit ne doit plus lire l'URL seule.
    restantes = re.findall(r"lang\s*=\s*request\.args\.get\('lang',\s*'fr'\)", code)
    att('aucune route ne lit plus que le parametre pour un rendu traduit',
        len(restantes), 0)

    print('\nE — la page « À propos » est traduite, et ses nombres survivent')
    fr = requests.get(BASE + '/a-propos', timeout=DELAI).text
    en = requests.get(BASE + '/a-propos', params={'lang': 'en'}, timeout=DELAI).text
    att('en francais, le titre est francais',
        'Trois régimes de temps' in fr, True)
    att('en anglais, il est traduit', 'Three time regimes' in en, True)
    # Une expression Jinja glissee dans un argument de `libelle` n'est jamais
    # evaluee : elle s'affiche telle quelle. Le defaut est passe inapercu sur
    # cinq mesures avant d'etre vu.
    for nom, page in (('francaise', fr), ('anglaise', en)):
        att('aucune expression Jinja ne fuit dans la version %s' % nom,
            re.findall(r'\{\{[^}]{0,60}\}\}', page), [])
    att('les nombres sont bien calcules en anglais',
        bool(re.search(r'\d[\d   ]* records, \d+ collections', en)), True)

    print('\nF — le selecteur transmet le choix au serveur')
    js = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      'static', 'js', 'translations.js')
    with open(js, encoding='utf-8') as f:
        moteur = f.read()
    att('switchLanguage ecrit le cookie lu par le serveur',
        'preferred_lang' in moteur and 'document.cookie' in moteur, True)

    print()
    print('=' * 70)
    if _ko:
        print('%d controle(s) en defaut : %s' % (len(_ko), ', '.join(_ko)))
        return 1
    print('%d controles, aucun defaut.' % _ok)
    return 0


if __name__ == '__main__':
    sys.exit(main())
