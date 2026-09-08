"""
Lecture des fichiers officiels de la base publique des médicaments.

Deux pièges, vérifiés en phase P1 et traités ici :

- `CIS_CIP_bdpm.txt` est encodé en UTF-8 alors que les six autres fichiers
  sont en latin-1. Un décodage uniforme corrompt les libellés. La règle
  retenue — UTF-8 strict puis repli latin-1 — traite correctement les sept
  fichiers et s'adapte si l'ANSM change d'encodage.

- `CIS_GENER_bdpm.txt` place l'identifiant de groupe générique en première
  colonne ; le CIS s'y trouve en troisième position, contrairement aux autres
  fichiers.
"""

import requests

from . import config

# Position du code CIS dans chaque fichier
CIS_COLUMN = {
    'CIS_bdpm.txt': 0,
    'CIS_CIP_bdpm.txt': 0,
    'CIS_COMPO_bdpm.txt': 0,
    'CIS_HAS_SMR_bdpm.txt': 0,
    'CIS_HAS_ASMR_bdpm.txt': 0,
    'CIS_CPD_bdpm.txt': 0,
    'CIS_GENER_bdpm.txt': 2,
}

# Colonnes de CIS_bdpm.txt, le fichier maître
MASTER_FIELDS = (
    ('cis', 0),
    ('denomination', 1),
    ('forme', 2),
    ('voies_administration', 3),
    ('statut_amm', 4),
    ('procedure_amm', 5),
    ('commercialisation', 6),
    ('date_amm', 7),
    ('statut_bdm', 8),
    ('autorisation_europeenne', 9),
    ('titulaire', 10),
    ('surveillance_renforcee', 11),
)

OPTIONAL_FILES = ('CIS_InfoImportantes.txt',)


def decode(raw):
    """
    Décode selon la règle UTF-8 strict puis latin-1.

    Retourne (texte, encodage retenu).
    """
    try:
        return raw.decode('utf-8'), 'utf-8'
    except UnicodeDecodeError:
        return raw.decode('latin-1'), 'latin-1'


def download(filename, session=None):
    """Télécharge un fichier officiel et retourne son contenu brut."""
    getter = session or requests
    response = getter.get(config.ANSM_DOWNLOAD + filename,
                          headers={'User-Agent': config.USER_AGENT},
                          timeout=config.HTTP_TIMEOUT)
    response.raise_for_status()
    return response.content


def read(filename, session=None):
    """
    Charge un fichier officiel et retourne (lignes, métadonnées).

    Chaque ligne est une liste de champs. Les lignes vides sont écartées.
    Un fichier optionnel vide retourne une liste vide sans lever d'erreur.
    """
    raw = download(filename, session)
    if not raw:
        if filename in OPTIONAL_FILES:
            return [], {'lines': 0, 'encoding': None, 'bytes': 0}
        raise ValueError('fichier officiel vide : %s' % filename)

    text, encoding = decode(raw)
    rows = [line.split('\t') for line in text.split('\n') if line.strip()]
    return rows, {'lines': len(rows), 'encoding': encoding, 'bytes': len(raw)}


def load_master(session=None):
    """
    Charge CIS_bdpm.txt et retourne {cis: {champs}} plus les métadonnées.

    C'est la source autoritaire pour la dénomination, la forme et le titulaire :
    la phase P1 a montré que 12,7 % des titres stockés sont dégradés alors que
    ce fichier les fournit exacts.
    """
    rows, meta = read('CIS_bdpm.txt', session)
    catalogue = {}
    for row in rows:
        if len(row) <= MASTER_FIELDS[-1][1]:
            continue
        record = {name: row[index].strip() for name, index in MASTER_FIELDS}
        if record['cis']:
            catalogue[record['cis']] = record
    return catalogue, meta


def is_active(record):
    """Un médicament actif et commercialisé est prioritaire à la collecte."""
    return (record.get('statut_amm') == 'Autorisation active'
            and record.get('commercialisation', '').startswith('Commercialis'))
