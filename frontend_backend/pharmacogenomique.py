"""
Lecture du profil pharmacogenomique d'une specialite.

Le module ne fait que joindre trois collections deja presentes et mettre le
resultat en forme. Il n'ecrit rien, ne calcule aucun risque et ne traduit
aucune donnee en conduite a tenir : ce que PharmGKB dit, la fiche le repete,
avec le nom de l'agence qui le dit.

Le chemin, en deux sauts indexes
--------------------------------
    medicines._id
      -> medicine_enrichment.medicine_id   (index existant)   -> drugbank_ids
      -> pharmgkb_par_substance._id                           -> molecule + genes

`pharmgkb_par_substance` est construite par `scripts/construire_pharmgkb.py`,
qui porte le detail de la jointure avec PharmGKB et les mesures de couverture.

Ce que « pas de donnee » veut dire
----------------------------------
Trois absences differentes, que la fiche ne doit pas confondre :

- la specialite n'atteint aucune molecule PharmGKB (27 % du catalogue) —
  `profil()` rend `None`, la section n'apparait pas ;
- la molecule est connue de PharmGKB mais aucune agence n'a nomme de gene
  (53 % du catalogue) — la section apparait et le dit ;
- une agence a nomme un gene pour dire qu'aucune action n'est requise
  (« No Clinical PGx ») — c'est une information, et elle contredit l'idee
  d'un risque. Elle garde donc son rang, et ne doit jamais etre presentee
  comme les niveaux qui, eux, demandent quelque chose.
"""

#: Rang au-dela duquel une annotation ne demande rien au prescripteur.
#: « Informative PGx » (4) mentionne le gene sans conduite a tenir, « No
#: Clinical PGx » (5) dit explicitement qu'il n'y a rien a faire, et 6 est
#: le rang des annotations dont l'agence n'a pas qualifie le niveau.
RANG_SANS_CONDUITE = 4

#: Rang rendu quand aucun gene n'est nomme. Doit rester superieur a tous les
#: rangs reels pour que le tri place ces molecules en dernier.
RANG_ABSENT = 9


def _identifiants_drugbank(base, medicine):
    """Les identifiants DrugBank de la specialite, via `medicine_enrichment`.

    Les fiches traduites (`medicines_en`, `medicines_ar`) portent un `_id`
    distinct de leur original francais — verifie en phase P8-1 : aucune
    correspondance par identifiant, toutes par URL. On retombe donc sur
    l'URL, seule cle commune aux trois collections.
    """
    enrichissement = base['medicine_enrichment'].find_one(
        {'medicine_id': medicine.get('_id')}, {'drugbank_ids': 1})

    if enrichissement is None and medicine.get('url'):
        original = base['medicines'].find_one({'url': medicine['url']}, {'_id': 1})
        if original:
            enrichissement = base['medicine_enrichment'].find_one(
                {'medicine_id': original['_id']}, {'drugbank_ids': 1})

    if not enrichissement:
        return []
    identifiants = enrichissement.get('drugbank_ids') or []
    return [i for i in identifiants if isinstance(i, str)]


def _fusionner_genes(molecules):
    """Un gene cite par deux molecules de la specialite n'est cite qu'une fois.

    Les associations en portent : une specialite paracetamol + codeine
    atteint deux molecules PharmGKB, et si toutes deux nommaient CYP2D6, la
    liste le repeterait. On garde le rang le plus exigeant et l'union des
    agences, comme le script le fait deja entre agences d'une meme molecule.
    """
    par_symbole = {}
    for molecule in molecules:
        for gene in molecule.get('genes') or []:
            existant = par_symbole.get(gene['symbole'])
            if existant is None:
                par_symbole[gene['symbole']] = dict(
                    gene, agences=list(gene.get('agences') or []),
                    molecules=[molecule['nom']])
                continue
            if gene['rang'] < existant['rang']:
                existant['rang'] = gene['rang']
                existant['niveau'] = gene['niveau']
            existant['agences'] = sorted(
                set(existant['agences']) | set(gene.get('agences') or []))
            if molecule['nom'] not in existant['molecules']:
                existant['molecules'].append(molecule['nom'])

    genes = list(par_symbole.values())
    genes.sort(key=lambda g: (g['rang'], g['symbole']))
    return genes


def profil(medicine, base):
    """Profil pharmacogenomique d'une specialite, ou `None` s'il n'y en a pas.

    Rend un dictionnaire pret pour l'affichage :

        molecules   les molecules PharmGKB atteintes, avec leur nom anglais
        genes       les genes nommes par au moins une agence, du plus
                    exigeant au moins, chacun avec les agences qui le citent
        niveau_max  le niveau le plus exigeant, `None` si aucun gene
        rang_max    son rang, `RANG_ABSENT` si aucun gene
        conduite    vrai si au moins une agence demande quelque chose
        guide       vrai si une recommandation posologique existe (CPIC/DPWG)
    """
    if not medicine or base is None:
        return None

    identifiants = _identifiants_drugbank(base, medicine)
    if not identifiants:
        return None

    try:
        molecules = list(base['pharmgkb_par_substance'].find(
            {'_id': {'$in': identifiants}}))
    except Exception:
        return None
    if not molecules:
        return None

    molecules.sort(key=lambda m: (m.get('rang_max', RANG_ABSENT), m.get('nom') or ''))
    genes = _fusionner_genes(molecules)

    return {
        'molecules': molecules,
        'genes': genes,
        'niveau_max': genes[0]['niveau'] if genes else None,
        'rang_max': genes[0]['rang'] if genes else RANG_ABSENT,
        'conduite': bool(genes) and genes[0]['rang'] < RANG_SANS_CONDUITE,
        'guide': any(m.get('guide_posologie') for m in molecules),
    }
