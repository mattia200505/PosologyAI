# -*- coding: utf-8 -*-
"""
Ré-extraction des substances actives depuis la section COMPOSITION du RCP.

Cible les fiches dont `medicine_details.substances_actives` est vide ou
contient un fragment de phrase — « Pour une ampoule de », « Chaque comprimé
pelliculé contient » — reliquat de l'extraction initiale (P8-5). Le rapport
P9-5 les chiffrait à 462, soit 23,4 % des médicaments sans interaction, et
hors d'atteinte de tout travail sur l'appariement : on n'apparie pas un champ
qui ne contient pas de substance.

La donnée n'a pas eu à être re-scrapée : 448 de ces fiches portent déjà en
base une section « 2. COMPOSITION QUALITATIVE ET QUANTITATIVE » exploitable.

## Le principe : auto-validation

Extraire une substance d'un texte libre, c'est risquer d'en inventer une —
et une substance inventée produit un appariement faux, donc des interactions
fausses, ce que tout le chantier P9 s'est employé à supprimer.

Le texte ne fait donc que **proposer** des candidats. Un candidat n'est retenu
que s'il **résout vers un identifiant DrugBank unique**, par le même chemin que
le matching : nom, synonyme, forme salifiée réduite, dictionnaire FR→EN. On ne
fabrique pas de substance, on récupère celles que la chaîne sait confirmer.

## Deux garde-fous, ajoutés après relecture d'un échantillon

- **La plus courte sous-chaîne qui résout.** Sans cette règle, le texte
  « BRINZOLAMIDE SANDOZ 10 mg » faisait écrire « BRINZOLAMIDE SANDOZ » dans le
  champ : l'identifiant était juste, mais le champ recevait un nom commercial,
  affiché tel quel et utilisé pour rapprocher les alternatives.
- **Le texte est coupé** avant « Pour la liste complète des excipients », et
  une liste d'excipients courants est écartée.

## Résultat mesuré le 13 août 2026

129 fiches récupérées sur 538 ciblées, 78 appariements gagnés, aucun perdu.
Sur les 129, 117 portent une substance dont le nom est proche du nom DrugBank ;
les 12 autres sont des traductions correctes (Adrénaline → Epinephrine,
Paracétamol → Acetaminophen, Glucose → Dextrose).

Les 409 fiches sans candidat validable sont des allergènes, des biologiques,
des solutions d'acides aminés et de l'homéopathie : structurellement hors du
périmètre de DrugBank.

## Invocation

    python -m scripts.extraction_composition              # simulation
    python -m scripts.extraction_composition --appliquer  # écriture

Contrairement à `matching_drugbank.py`, qui écrit par défaut et simule avec
`--dry-run`, ce script **simule par défaut** : il réécrit un champ du
catalogue de référence, et un défaut qui écrit serait le mauvais choix ici.
"""
import re
import sys

from pymongo import MongoClient, UpdateOne

from scripts.matching_drugbank import DCI_FR_EN, build_drugbank_index
from scripts.normalize_shared import normalize_dci, reduce_salt

MONGO_URI = "mongodb://localhost:27017/"
MONGO_DB = "medicsearch"

db = MongoClient(MONGO_URI, serverSelectionTimeoutMS=8000)[MONGO_DB]

# Excipients et mentions qui ne sont jamais le principe actif.
EXCIPIENTS = frozenset({
    'lactose', 'lactose monohydrate', 'amidon', 'amidon de mais', 'cellulose',
    'cellulose microcristalline', 'stearate de magnesium', 'talc', 'saccharose',
    'mannitol', 'sorbitol', 'glycerol', 'eau purifiee', 'eau', 'ethanol',
    'dioxyde de titane', 'silice', 'povidone', 'gelatine', 'glucose',
    'chlorure de sodium', 'acide citrique', 'citrate de sodium', 'sodium',
    'hydroxyde de sodium', 'acide chlorhydrique', 'azote', 'excipients',
    'excipient', 'aromes', 'colorant', 'conservateur',
})

# Fragments de phrase laissés par l'extraction initiale : ils signalent une
# valeur inexploitable, aussi bien en entrée qu'en sortie.
RE_FRAGMENT = re.compile(
    r'\b(chaque|contient|contiennent|flacon|cartouche|poche|dose|delivre|'
    r'inhalation|comprim|gelule|ampoule|reconstitution|compartiment|total|'
    r'pour un|pour une|dans|liste|excipient)\b', re.I)


def texte_composition(medicine):
    """Texte de la section COMPOSITION, sous-sections comprises."""
    for section in (medicine.get('sections') or []):
        if 'COMPOSITION' not in (section.get('title') or '').upper():
            continue
        parts = [c.get('text', '') for c in (section.get('content') or []) if c.get('text')]
        for sub in (section.get('subsections') or []):
            parts += [c.get('text', '') for c in (sub.get('content') or []) if c.get('text')]
        return ' '.join(parts).strip()
    return ''


def candidats(texte, titre):
    """Fragments du texte susceptibles de nommer le principe actif."""
    # Ce qui suit cette mention ne concerne que les excipients.
    utile = re.split(r"[Pp]our la liste compl|[Ee]xcipient", texte)[0]
    bruts = []

    # « ... équivalent à 25 mg d'agomélatine »
    bruts += re.findall(
        r"(?:equivalent|correspondant)\s+a\s+[\d,.\s]*\w*\s+d[e']\s*"
        r"([A-Za-zÀ-ÿ][\w\-'’ ]{3,40})", utile, re.I)
    # « Substance ... 500 mg » : ce qui précède un dosage
    bruts += re.findall(
        r"([A-Za-zÀ-ÿ][\w\-'’ ]{3,40}?)\s*[.\s]*\d+[,.]?\d*\s*(?:mg|g|µg|mcg|UI|%)",
        utile)
    # « contient : Substance »
    bruts += re.findall(
        r"contient\s*:?\s*(?:du |de la |de l['’]|d['’])?([A-Za-zÀ-ÿ][\w\-'’ ]{3,40})",
        utile, re.I)
    # Le titre : les génériques français portent le nom de leur molécule.
    bruts.append(re.split(r'\d', titre)[0])

    vus, propres = set(), []
    for brut in bruts:
        c = re.sub(r'\s+', ' ', brut).strip(" ,;:.'’-")
        n = normalize_dci(c)
        if not n or len(n) < 4 or n in vus or n in EXCIPIENTS:
            continue
        if RE_FRAGMENT.search(n):
            continue
        vus.add(n)
        propres.append(c)
    return propres


def _resout(index, cle):
    if not cle:
        return None
    for source in ('by_dci', 'by_synonym'):
        ids = sorted({e['drugbank_id'] for e in index[source].get(cle, [])})
        if len(ids) == 1:
            return ids[0]
    return None


def _resout_tout(index, candidat):
    n = normalize_dci(candidat)
    r = reduce_salt(candidat)
    for cle in (n, DCI_FR_EN.get(n), r, DCI_FR_EN.get(r or '')):
        dbid = _resout(index, cle)
        if dbid:
            return dbid
    return None


def valide(index, candidat):
    """Rend (substance, drugbank_id) si le candidat résout, sinon None.

    Retient la plus courte sous-chaîne qui résout vers le même identifiant,
    pour ne pas inscrire un nom commercial dans le champ substance.
    """
    dbid = _resout_tout(index, candidat)
    if not dbid:
        return None
    mots = candidat.split()
    for n in range(1, len(mots)):
        court = ' '.join(mots[:n])
        if len(normalize_dci(court) or '') >= 4 and _resout_tout(index, court) == dbid:
            return court, dbid
    return candidat, dbid


def a_besoin_de_reextraction(medicine):
    subs = (medicine.get('medicine_details') or {}).get('substances_actives') or []
    if not subs:
        return True
    return any(RE_FRAGMENT.search(s or '') for s in subs)


def run(appliquer=False):
    cibles = [m for m in db.medicines.find(
        {}, {'title': 1, 'medicine_details': 1, 'sections': 1})
        if a_besoin_de_reextraction(m)]
    print(f"Fiches sans substance exploitable : {len(cibles)}")

    index = build_drugbank_index()

    trouve, ops = [], []
    for medicine in cibles:
        texte = texte_composition(medicine)
        if len(texte) < 30:
            continue
        for candidat in candidats(texte, medicine.get('title', '')):
            resultat = valide(index, candidat)
            if not resultat:
                continue
            substance, dbid = resultat
            trouve.append((medicine.get('title', '')[:40], substance, dbid))
            ops.append(UpdateOne(
                {'_id': medicine['_id']},
                {'$set': {'medicine_details.substances_actives': [substance],
                          'substances_source': 'composition_rcp'}}))
            break

    print(f"Substances récupérées et validées : {len(trouve)}")
    for titre, substance, dbid in trouve[:20]:
        print(f"   {titre:<40} « {substance} » -> {dbid}")
    if len(trouve) > 20:
        print(f"   … et {len(trouve) - 20} autres")

    if not appliquer:
        print("\nSimulation : aucune écriture. Relancer avec --appliquer.")
        return 0

    for i in range(0, len(ops), 500):
        db.medicines.bulk_write(ops[i:i + 500])
    print(f"\n{len(ops)} fiches mises à jour.")
    print("Enchaîner avec le ré-appariement, puis la reconstruction de la "
          "couche substance (cf. rapport P9-3).")
    return len(ops)


if __name__ == '__main__':
    appliquer = '--appliquer' in sys.argv
    if not appliquer:
        print("MODE SIMULATION — aucune écriture en base\n")
    run(appliquer=appliquer)
