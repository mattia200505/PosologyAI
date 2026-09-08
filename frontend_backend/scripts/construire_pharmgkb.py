# -*- coding: utf-8 -*-
"""Index pharmacogenomique par substance, a partir des trois collections PharmGKB.

Pourquoi ce fichier existe
--------------------------
Les donnees PharmGKB sont importees depuis fevrier 2026 dans trois
collections, et aucune page ne les lit. Elles ne sont reliees au catalogue
francais par aucune cle : `medicines` porte des noms de specialites
francaises, PharmGKB des noms de molecules anglais.

Le pont existe deja, en deux morceaux :

    medicines._id -> medicine_enrichment.medicine_id -> drugbank_ids
    PHARMGKB_DRUGS['Cross-references'] contient  DrugBank:DB00758

Ce script noue les deux : il ecrit `pharmgkb_par_substance`, indexee par
identifiant DrugBank, que la fiche lit ensuite en une recherche par `_id`.

Pourquoi par substance, et non par specialite
---------------------------------------------
Meme raison que les structures moleculaires (§12 du plan P9) : la
pharmacogenomique porte sur la molecule, pas sur le conditionnement. Les
cinq dosages de PLAVIX partagent le meme clopidogrel et donc le meme
CYP2C19. Indexer par specialite ecrirait 9 856 documents la ou 1 786
suffisent, et ferait diverger les copies au prochain import.

Couverture mesuree sur le catalogue (13 489 fiches enrichies)
-------------------------------------------------------------
    fiches avec un identifiant DrugBank        12 135   (90,0 %)
    fiches atteignant une molecule PharmGKB     9 856   (73,1 %)
    fiches avec un gene identifie par une agence 2 743  (20,3 %)
    fiches dont la molecule a un guide posologique 1 144 (8,5 %)

Les 27 % restants ne sont pas une panne : PharmGKB ne couvre que les
molecules pour lesquelles une donnee pharmacogenomique existe. L'absence
est donc une information, et la fiche doit la dire ainsi.

Les niveaux, et pourquoi l'ordre compte
---------------------------------------
PharmGKB classe ce que l'agence du medicament exige. Le rang est le sien,
repris tel quel :

    1  Testing Required      le test genetique est exige avant prescription
    2  Testing Recommended   il est recommande
    3  Actionable PGx        la notice donne une conduite a tenir
    4  Informative PGx       la notice mentionne le gene, sans conduite
    5  No Clinical PGx       la notice dit qu'aucune action n'est requise

Le cinquieme est le piege : il **contredit** l'idee d'un risque. L'afficher
comme les autres ferait lire un avertissement la ou l'agence a ecrit une
absence de consequence. Le rang est donc conserve jusqu'a l'affichage, et
`niveau_max` retient le plus exigeant, jamais le plus alarmant.

Idempotent : rejouer le script reconstruit la collection a l'identique.

    python scripts/construire_pharmgkb.py            construit
    python scripts/construire_pharmgkb.py --verifier controle sans ecrire
"""
import os
import re
import sys
import time
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'))

CIBLE = 'pharmgkb_par_substance'

#: Le classement de PharmGKB, du plus exigeant au moins. `None` existe dans
#: 417 des 1 356 annotations : l'agence cite le gene sans qualifier le
#: niveau. C'est un rang distinct de « aucune action requise », et non un
#: defaut a combler.
RANGS = {
    'Testing Required': 1,
    'Testing Recommended': 2,
    'Actionable PGx': 3,
    'Informative PGx': 4,
    'No Clinical PGx': 5,
}
RANG_SANS_NIVEAU = 6

REFERENCE_DRUGBANK = re.compile(r'DrugBank:(DB\d+)')


def _oui(valeur):
    """PharmGKB ecrit « Yes »/« No » en toutes lettres, jamais un booleen."""
    return (valeur or '').strip().lower() == 'yes'


def _nombre(valeur):
    """« 51.0 » est un compte, pas une mesure : PharmGKB l'exporte en flottant."""
    try:
        return int(float(valeur))
    except (TypeError, ValueError):
        return 0


def index_des_genes(base):
    """Symbole -> fiche du gene. Les 234 genes cites par les annotations y sont tous."""
    genes = {}
    for g in base['PHARMGKB_GENES'].find(
            {}, {'Symbol': 1, 'Name': 1, 'Is VIP': 1, 'Has CPIC Dosing Guideline': 1,
                 'PharmGKB Accession Id': 1}):
        symbole = (g.get('Symbol') or '').strip()
        if symbole:
            genes[symbole] = g
    return genes


def annotations_par_molecule(base):
    """Nom de molecule (minuscules) -> annotations d'agences la concernant.

    La correspondance est **exacte**, sur la chaine `Chemicals` entiere. Ne
    pas la decouper est une decision de correction, pas une simplification.

    Cinq annotations sur 1 356 portent une association, separee par un
    point-virgule. PharmGKB ne dit jamais lequel des composants porte le
    gene, et la reponse n'est pas devinable :

        acetaminophen; tramadol            CYP2D6    vient du tramadol
        acetaminophen; ... / tramadol      G6PD
        fenofibrate; simvastatin           SLCO1B1   vient de la simvastatine
        glimepiride; pioglitazone          G6PD      vient du glimepiride

    Decouper attacherait CYP2D6 au paracetamol seul, donc a toutes les
    presentations de DOLIPRANE : une affirmation pharmacologique fausse, sur
    la molecule la plus prescrite du catalogue. `acetaminophen` seul n'a
    d'ailleurs aucune annotation, ce qui est la reponse juste.

    La virgule, elle, appartient aux noms — « Ascorbic acid (vitamin C),
    plain », « synthetic conjugated estrogens, A ». Quatre valeurs sur 510
    en portent une, aucune comme separateur. Mesure de l'ecart entre les
    deux strategies : la correspondance exacte relie 505 molecules, le
    fractionnement par virgule 502. Il n'en fait donc gagner aucune, en perd
    trois dont il casse le nom, et ouvre la porte a la mauvaise attribution
    ci-dessus.
    """
    par_nom = defaultdict(list)
    for a in base['PHARMGKB_DRUG_LABELS'].find({}, {
            'Chemicals': 1, 'Genes': 1, 'Testing Level': 1, 'Source': 1}):
        chimiques = (a.get('Chemicals') or '').strip()
        if chimiques:
            par_nom[chimiques.lower()].append(a)
    return par_nom


def genes_de(annotations, genes_connus):
    """Regroupe les annotations par gene, en gardant le niveau le plus exigeant.

    Une meme molecule est annotee par plusieurs agences — clopidogrel l'est
    par la FDA, l'EMA, Swissmedic et la PMDA, qui ne s'accordent pas sur le
    niveau. Les afficher separement obligerait le lecteur a faire lui-meme
    la synthese ; on retient le rang le plus exigeant et on nomme les
    agences qui le portent.
    """
    par_gene = defaultdict(lambda: {'rang': RANG_SANS_NIVEAU, 'niveau': None,
                                    'agences': set()})
    for a in annotations:
        rang = RANGS.get(a.get('Testing Level'), RANG_SANS_NIVEAU)
        agence = (a.get('Source') or '').strip()
        for symbole in (a.get('Genes') or '').split(';'):
            symbole = symbole.strip()
            if not symbole:
                continue
            entree = par_gene[symbole]
            if rang < entree['rang']:
                entree['rang'] = rang
                entree['niveau'] = a.get('Testing Level')
            if agence:
                entree['agences'].add(agence)

    resultat = []
    for symbole, entree in par_gene.items():
        fiche = genes_connus.get(symbole, {})
        resultat.append({
            'symbole': symbole,
            'nom': fiche.get('Name') or None,
            'accession': fiche.get('PharmGKB Accession Id') or None,
            'niveau': entree['niveau'],
            'rang': entree['rang'],
            'vip': _oui(fiche.get('Is VIP')),
            'guide_cpic': _oui(fiche.get('Has CPIC Dosing Guideline')),
            'agences': sorted(entree['agences']),
        })
    resultat.sort(key=lambda g: (g['rang'], g['symbole']))
    return resultat


def construire(base, ecrire=True):
    genes_connus = index_des_genes(base)
    par_nom = annotations_par_molecule(base)

    documents = {}
    sans_reference = 0
    for molecule in base['PHARMGKB_DRUGS'].find({}, {
            'Name': 1, 'Cross-references': 1, 'Dosing Guideline': 1,
            'PharmGKB Accession Id': 1, 'Clinical Annotation Count': 1,
            'Variant Annotation Count': 1}):
        references = REFERENCE_DRUGBANK.findall(molecule.get('Cross-references') or '')
        if not references:
            sans_reference += 1
            continue                     # sans identifiant DrugBank, aucun pont vers le catalogue

        nom = (molecule.get('Name') or '').strip()
        genes = genes_de(par_nom.get(nom.lower(), []), genes_connus)
        document = {
            'nom': nom,
            'accession': molecule.get('PharmGKB Accession Id'),
            'guide_posologie': _oui(molecule.get('Dosing Guideline')),
            'annotations_cliniques': _nombre(molecule.get('Clinical Annotation Count')),
            'annotations_variants': _nombre(molecule.get('Variant Annotation Count')),
            'genes': genes,
            'niveau_max': genes[0]['niveau'] if genes else None,
            'rang_max': genes[0]['rang'] if genes else RANG_SANS_NIVEAU,
            'construit_le': time.strftime('%Y-%m-%d %H:%M:%S'),
        }
        for reference in references:
            documents[reference] = dict(document, _id=reference)

    if not ecrire:
        return documents, sans_reference

    base[CIBLE].delete_many({})
    if documents:
        base[CIBLE].insert_many(list(documents.values()))
    return documents, sans_reference


def main():
    verifier = '--verifier' in sys.argv
    uri = os.getenv('MONGO_URI', 'mongodb://localhost:27017/medicsearch')
    base = MongoClient(uri, serverSelectionTimeoutMS=5000)[os.getenv('MONGO_DB', 'medicsearch')]

    avant = base[CIBLE].count_documents({})
    documents, sans_reference = construire(base, ecrire=not verifier)

    avec_genes = sum(1 for d in documents.values() if d['genes'])
    avec_guide = sum(1 for d in documents.values() if d['guide_posologie'])

    print('%s : %d molecules indexees par identifiant DrugBank'
          % ('CONTROLE' if verifier else CIBLE, len(documents)))
    print('  dont un gene nomme par une agence : %d' % avec_genes)
    print('  dont un guide posologique         : %d' % avec_guide)
    print('  molecules PharmGKB sans reference DrugBank, ecartees : %d' % sans_reference)
    if verifier:
        print('  rien ecrit ; la collection en porte %d' % avant)
    else:
        print('  collection : %d -> %d' % (avant, base[CIBLE].count_documents({})))
    return 0


if __name__ == '__main__':
    sys.exit(main())
