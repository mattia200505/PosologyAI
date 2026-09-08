# -*- coding: utf-8 -*-
"""Import des RCP européens en PDF — action 3.3 de l'audit UX.

`scripts/import_ema.py` a importé 1 548 médicaments autorisés par la procédure
centralisée, en prévenant de ce qui manquerait : « Aucune section de RCP :
l'EMA publie les siens en PDF, hors de ce tableur. » Ces fiches portent donc
`sections: []` et affichent un avertissement à la place de leur monographie.
Ce script comble le trou.

## La source

Chaque page EPAR expose son « product information » en PDF, dans les vingt-cinq
langues de l'Union. **Le français en fait partie** — rien n'est à traduire :

    https://www.ema.europa.eu/fr/documents/product-information/
        <slug>-epar-product-information_fr.pdf

Le PDF réunit l'annexe I (le RCP proprement dit), l'annexe II, l'étiquetage et
la notice. Seule l'annexe I est importée : c'est elle qui porte les rubriques
que la fiche affiche, et son plan est **identique à celui des RCP ANSM** —
1. DÉNOMINATION, 2. COMPOSITION, … 4.3 Contre-indications, 4.5 Interactions.
Les sections extraites se rangent donc dans le schéma existant sans conversion,
et la fiche les rend comme les autres.

## Ce que ce script coûte, et ce que l'EMA en pense

Mesuré sur Lynparza : 4,4 Mo de PDF, 92 pages. Pour 1 548 médicaments, c'est de
l'ordre de **7 Go et 1 548 requêtes** vers les serveurs d'une institution
publique.

> **L'EMA limite le débit.** Une campagne lancée avec une pause d'une seconde a
> reçu **1 257 réponses « HTTP 429 — Too Many Requests » d'affilée**, après
> environ 250 téléchargements réussis. Une pause d'une seconde est donc trop
> rapide pour ce service. Reprendre avec `--pause 5` au minimum, et de
> préférence après plusieurs heures d'interruption.
>
> La première version de ce script ne distinguait pas un 429 d'un 404 : elle a
> encaissé les 1 257 refus sans jamais ralentir. C'est le comportement d'un
> client qu'on a raison de bloquer. Il attend désormais, honore `Retry-After`,
> et **s'arrête au bout de cinq refus consécutifs** — insister n'obtient rien
> et sollicite pour rien.

D'où quatre précautions :

- **simulation par défaut**, comme `import_ema.py` : `--appliquer` est requis
  pour écrire quoi que ce soit ;
- **une pause entre deux requêtes**, réglable, à une seconde par défaut ;
- **cache sur disque** : un PDF déjà téléchargé n'est pas redemandé, de sorte
  qu'une reprise après interruption ne repart pas de zéro ;
- **arrêt sur refus répété**, décrit ci-dessus.

La lecture s'arrête à la fin de l'annexe I plutôt que de parcourir les 92
pages du document : l'extraction passe de douze secondes à deux.

## Invocation

    python -m scripts.import_rcp_ema --limite 5        # simulation, 5 fiches
    python -m scripts.import_rcp_ema --limite 5 --appliquer
    python -m scripts.import_rcp_ema --appliquer       # les 1 548

`--limite` sert aussi à vérifier le rendu sur quelques fiches avant d'engager
le lot entier.
"""
import argparse
import io
import os
import re
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pymongo import MongoClient  # noqa: E402

MONGO_URI = "mongodb://localhost:27017/"
MONGO_DB = "medicsearch"

GABARIT_PDF = ("https://www.ema.europa.eu/fr/documents/product-information/"
               "{slug}-epar-product-information_fr.pdf")

#: Plafond de sécurité : la lecture s'arrête normalement sur « ANNEXE II ».
#: Ce nombre ne sert que si ce marqueur manque, pour ne pas analyser les
#: quatre-vingt-douze pages d'un document dont seules les premières comptent.
PAGES_MAXIMUM = 70

#: Un en-tête qui dit qui appelle et pourquoi. Un script qui interroge 1 548
#: fois un service public sans se nommer est un script qu'on a raison de
#: bloquer.
ENTETES = {'User-Agent': 'MedicSearch/1.0 (import RCP EMA, usage academique)'}

CACHE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     'ressources', 'cache_pdf_ema')

#: Plan du RCP, fixé par le modèle européen (« QRD template ») et identique à
#: celui des RCP ANSM déjà en base.
#:
#: Les intitulés viennent de ce tableau et non du PDF, pour une raison qu'on ne
#: découvre qu'en lisant le texte extrait : pdfplumber rend souvent le numéro
#: seul sur sa ligne, l'intitulé s'étant perdu dans la mise en page. Sur
#: Zebinix, « 4.1 » était suivi directement de « Zebinix est indiqué: », et
#: une lecture naïve prenait cette phrase pour le titre de la rubrique.
#:
#: Se fonder sur la numérotation plutôt que sur le texte a un second effet
#: utile : les fiches EMA portent alors exactement les mêmes intitulés que les
#: fiches ANSM, et la fiche les affiche sans distinction.
PLAN_RCP = [
    ('1', 'DENOMINATION DU MEDICAMENT'),
    ('2', 'COMPOSITION QUALITATIVE ET QUANTITATIVE'),
    ('3', 'FORME PHARMACEUTIQUE'),
    ('4', 'DONNEES CLINIQUES'),
    ('4.1', 'Indications thérapeutiques'),
    ('4.2', "Posologie et mode d'administration"),
    ('4.3', 'Contre-indications'),
    ('4.4', "Mises en garde spéciales et précautions d'emploi"),
    ('4.5', "Interactions avec d'autres médicaments et autres formes d'interactions"),
    ('4.6', 'Fertilité, grossesse et allaitement'),
    ('4.7', "Effets sur l'aptitude à conduire des véhicules et à utiliser des machines"),
    ('4.8', 'Effets indésirables'),
    ('4.9', 'Surdosage'),
    ('5', 'PROPRIETES PHARMACOLOGIQUES'),
    ('5.1', 'Propriétés pharmacodynamiques'),
    ('5.2', 'Propriétés pharmacocinétiques'),
    ('5.3', 'Données de sécurité préclinique'),
    ('6', 'DONNEES PHARMACEUTIQUES'),
    ('6.1', 'Liste des excipients'),
    ('6.2', 'Incompatibilités'),
    ('6.3', 'Durée de conservation'),
    ('6.4', 'Précautions particulières de conservation'),
    ('6.5', "Nature et contenu de l'emballage extérieur"),
    ('6.6', "Précautions particulières d'élimination et de manipulation"),
    ('7', "TITULAIRE DE L'AUTORISATION DE MISE SUR LE MARCHE"),
    ('8', "NUMERO(S) D'AUTORISATION DE MISE SUR LE MARCHE"),
    ('9', "DATE DE PREMIERE AUTORISATION/DE RENOUVELLEMENT DE L'AUTORISATION"),
    ('10', 'DATE DE MISE A JOUR DU TEXTE'),
    # Deux rubriques propres aux radiopharmaceutiques. Les omettre ne les
    # faisait pas disparaître : faute de borne, la rubrique 10 de SomaKit TOC
    # les absorbait toutes deux, soit 77 paragraphes rangés sous « date de
    # mise à jour du texte ».
    ('11', 'DOSIMETRIE'),
    ('12', 'INSTRUCTIONS POUR LA PREPARATION DES RADIOPHARMACEUTIQUES'),
]

#: Fin de l'annexe I. Ce qui suit — annexe II, étiquetage, notice — n'est pas
#: la monographie et ne doit pas s'y déverser. Sans cette borne, la dernière
#: section avalait 201 paragraphes sur Zebinix.
RE_FIN_ANNEXE_I = re.compile(r'^\s*ANNEXE\s+II\b', re.M)

#: Phrase de clôture du RCP, présente sur tous les documents européens : « Des
#: informations détaillées sur ce médicament sont disponibles sur le site
#: internet de l'Agence européenne des médicaments http://www.ema.europa.eu ».
#: Elle sert de borne quand « ANNEXE II » se trouve au-delà des pages lues — le
#: RCP de Zebinix dépasse à lui seul soixante-dix pages, et sans cette seconde
#: borne la rubrique 10 emportait les 373 paragraphes qui la suivent.
RE_FIN_RCP = re.compile(r'ema\.europa\.eu[^\n]*', re.I)

#: Ligne de pied de page répétée sur chaque page du PDF, sans valeur pour le
#: lecteur et qui polluerait chaque rubrique si on la gardait.
RE_BRUIT = re.compile(r'^\s*(\d+\s*)?$|^\s*Page \d+', re.M)


def slug_depuis_url(url):
    """« …/EPAR/lynparza » → « lynparza »."""
    if not url:
        return None
    fin = url.rstrip('/').rsplit('/', 1)[-1]
    return fin.lower() if fin else None


#: Nombre de 429 consécutifs au-delà duquel la campagne s'arrête. Un serveur
#: qui répond « Too Many Requests » demande qu'on cesse ; continuer n'obtient
#: rien et sollicite pour rien. La première version de ce script ne le
#: distinguait pas d'un 404 : elle a encaissé **1 257 refus d'affilée** sans
#: jamais ralentir, ce qui est le comportement d'un client qu'on a raison de
#: bloquer.
REFUS_CONSECUTIFS_MAXIMUM = 5

#: Attentes successives, en secondes, avant de réessayer après un 429. Le
#: serveur a priorité : un en-tête `Retry-After` l'emporte sur cette table.
ATTENTES_REPRISE = (30, 120, 300)


class TropDeRequetes(Exception):
    """Le service a demandé l'arrêt et l'a répété. On s'arrête."""


def telecharger(slug, pause):
    """Rend le PDF, depuis le cache s'il y est déjà.

    Rend `(chemin, état)`. Lève `TropDeRequetes` quand le service refuse
    obstinément : c'est à l'appelant d'interrompre la campagne, pas de
    poursuivre en comptant les échecs.
    """
    os.makedirs(CACHE, exist_ok=True)
    chemin = os.path.join(CACHE, f'{slug}.pdf')
    if os.path.exists(chemin) and os.path.getsize(chemin) > 4096:
        return chemin, 'cache'

    contenu = None
    for essai, attente in enumerate((0,) + ATTENTES_REPRISE):
        if attente:
            print(f"      429 reçu, attente de {attente} s avant reprise")
            time.sleep(attente)
        requete = urllib.request.Request(GABARIT_PDF.format(slug=slug), headers=ENTETES)
        try:
            contenu = urllib.request.urlopen(requete, timeout=90).read()
            break
        except urllib.error.HTTPError as err:
            if err.code != 429:
                time.sleep(pause)
                return None, f'HTTP {err.code}'
            # Le serveur sait mieux que nous combien de temps attendre.
            propose = err.headers.get('Retry-After') if err.headers else None
            if propose and propose.isdigit():
                delai_serveur = int(propose)
                print(f"      429, Retry-After indique {delai_serveur} s")
                time.sleep(min(delai_serveur, 600))
            if essai == len(ATTENTES_REPRISE):
                time.sleep(pause)
                return None, 'HTTP 429'
        except Exception as err:
            time.sleep(pause)
            return None, type(err).__name__

    # La pause s'applique même en cas de succès : c'est elle qui tient le
    # rythme de la campagne.
    time.sleep(pause)
    if contenu is None:
        return None, 'HTTP 429'
    if not contenu.startswith(b'%PDF'):
        return None, 'pas un PDF'
    with open(chemin, 'wb') as fichier:
        fichier.write(contenu)
    return chemin, 'telecharge'


def texte_du_pdf(chemin):
    """Texte de l'annexe I, lue page à page jusqu'à la fin de celle-ci.

    Un nombre de pages fixe ne convenait pas : l'annexe I de Zebinix tient en
    vingt pages, celle de Lynparza en dépasse quarante-cinq — la borne fixe
    tronquait la seconde en plein milieu et la moitié de ses rubriques
    manquaient. On s'arrête donc sur le marqueur d'annexe II, avec un plafond
    pour le cas où celui-ci ferait défaut.
    """
    import pdfplumber
    morceaux = []
    with pdfplumber.open(chemin) as pdf:
        for page in pdf.pages[:PAGES_MAXIMUM]:
            morceaux.append(page.extract_text() or '')
            if RE_FIN_ANNEXE_I.search(morceaux[-1]):
                break
    return '\n'.join(morceaux)


def _sans_titre_repete(contenu, intitule):
    """Retire l'intitulé quand le PDF l'a recopié en tête de son contenu.

    Les deux mises en page coexistent d'un document à l'autre :

        4.3 Contre-indications          4.3
        Hypersensibilité…               Contre-indications
                                        Hypersensibilité…

    La comparaison se fait mot à mot et non sur l'intitulé entier, parce que
    les PDF s'en écartent : le modèle dit « Précautions particulières
    d'élimination et de manipulation », les documents écrivent « … et
    manipulation » ou s'arrêtent à « … d'élimination ». On retire donc le plus
    long préfixe dont chaque mot appartient à l'intitulé, et au moins deux
    d'affilée — un mot isolé serait trop souvent un début de phrase légitime.
    """
    if not contenu:
        return contenu
    def nu(mot):
        # La ponctuation se plie des deux côtés : « Fertilité, » du titre et
        # « Fertilité, » du texte doivent se reconnaître, et la garder d'un
        # seul côté suffisait à faire échouer la comparaison.
        return _sans_accents(mot).strip(":.,;()")

    mots_titre = [nu(m) for m in intitule.split()]
    ensemble = set(mots_titre)
    mots = contenu[0]['text'].split()
    pris = 0
    while pris < len(mots) and nu(mots[pris]) in ensemble:
        pris += 1
    # Deux mots d'affilée, ou l'intitulé entier : « Surdosage » et
    # « Incompatibilités » ne font qu'un mot, et le seuil de deux les excluait
    # tous — c'est-à-dire précisément les rubriques les plus courtes, où le
    # titre recopié pèse le plus lourd dans le contenu.
    if pris < 2 and pris < len(mots_titre):
        return contenu
    reste = ' '.join(mots[pris:]).lstrip(' :.–-')
    if reste:
        contenu[0] = {'text': reste}
    else:
        contenu = contenu[1:]
    return contenu


def _sans_accents(texte):
    """Casse, accents et apostrophes repliés.

    L'apostrophe compte autant que l'accent : le PDF écrit « mode
    d’administration » avec l'apostrophe typographique, la table du plan avec
    l'apostrophe droite. Sans ce repli, la comparaison échouait sur toutes les
    rubriques qui en portent une — 225 titres se retrouvaient recopiés en tête
    de leur propre contenu.
    """
    import unicodedata
    plie = unicodedata.normalize('NFD', texte.lower().replace('’', "'"))
    return ''.join(c for c in plie if unicodedata.category(c) != 'Mn')


def _paragraphes(bloc):
    """Découpe un bloc en énoncés, débarrassé des numéros de page."""
    sorties = []
    for ligne in bloc.split('\n'):
        ligne = ligne.strip()
        if not ligne or RE_BRUIT.match(ligne):
            continue
        sorties.append(ligne)
    # Les lignes d'un même paragraphe sont recollées : un PDF coupe au gré de
    # la mise en page, et une puce par ligne physique rendrait la rubrique
    # illisible. Une nouvelle puce ou une ligne finissant par un point ferme
    # le paragraphe.
    paragraphes, courant = [], ''
    for ligne in sorties:
        if courant and (ligne.startswith(('·', '•', '-', '–')) or courant.endswith(('.', ':', ';'))):
            paragraphes.append(courant)
            courant = ligne
        else:
            courant = (courant + ' ' + ligne).strip()
    if courant:
        paragraphes.append(courant)
    return [{'text': p} for p in paragraphes if len(p) > 2]


def _reperer_plan(texte):
    """Position de chaque rubrique du plan, cherchée dans l'ordre.

    Avancer dans le plan plutôt que chercher toutes les occurrences écarte les
    faux positifs : « 4.2 » revient dans le corps d'une rubrique (« voir
    rubrique 4.2 ») bien plus souvent qu'en tête de ligne, et une recherche
    globale prenait ces renvois pour des titres. En n'acceptant que la
    prochaine rubrique attendue, à partir de la position courante, un renvoi
    interne ne peut pas être confondu avec le titre qui le suit.
    """
    reperes = []
    curseur = 0
    for numero, intitule in PLAN_RCP:
        motif = re.compile(r'^[ \t]*' + re.escape(numero) + r'[.\s]', re.M)
        trouve = motif.search(texte, curseur)
        if not trouve:
            continue
        reperes.append({'numero': numero, 'intitule': intitule,
                        'debut': trouve.start(), 'fin_titre': trouve.end()})
        curseur = trouve.end()
    return reperes


def extraire_sections(texte):
    """Découpe l'annexe I en sections et sous-sections du schéma maison."""
    # Seule « ANNEXE II » borne le texte entier : c'est une frontière réelle du
    # document. La phrase de clôture, elle, ne sert qu'à borner la dernière
    # rubrique, et plus bas — l'employer ici tronquait le RCP à la première
    # mention du site de l'EMA, laquelle figure en 4.8 sur beaucoup de fiches.
    # Humira y perdait neuf sections sur dix, Yesintek cinq.
    fin_annexe = RE_FIN_ANNEXE_I.search(texte)
    if fin_annexe:
        texte = texte[:fin_annexe.start()]

    reperes = _reperer_plan(texte)
    if not reperes:
        return []

    # Un « product information » réunit parfois plusieurs RCP — un par forme
    # pharmaceutique. Signifor en enchaîne deux : ses rubriques 11 et 12 ont
    # été trouvées à la position 111 470, dans le second, et la rubrique 10 du
    # premier s'étendait sur les 67 000 caractères qui les séparent.
    #
    # Le premier RCP s'arrête à sa phrase de clôture, cherchée à partir de la
    # rubrique 9 ou 10 — pas avant : le site de l'EMA est aussi cité en 4.8 sur
    # beaucoup de fiches, et couper là faisait perdre à Humira neuf sections
    # sur dix.
    for repere in reperes:
        if repere['numero'] in ('9', '10'):
            cloture = RE_FIN_RCP.search(texte, repere['fin_titre'])
            if cloture:
                texte = texte[:cloture.end()]
                reperes = [r for r in reperes if r['debut'] < cloture.end()]
            break

    # Chaque rubrique court jusqu'au début de la suivante, celle-ci fût-elle
    # d'un autre niveau : c'est ce qui borne « 4. DONNEES CLINIQUES » à son
    # chapeau, avant que 4.1 ne commence.
    for rang, repere in enumerate(reperes):
        if rang + 1 < len(reperes):
            repere['fin'] = reperes[rang + 1]['debut']
            continue
        # La dernière rubrique n'a pas de suivante pour la borner : sans quoi
        # elle emporte tout ce qui reste du document — 437 paragraphes sur
        # Bimervax. Elle s'arrête à la phrase de clôture du RCP, cherchée à
        # partir de son propre début, et à défaut au bout de quelques lignes.
        cloture = RE_FIN_RCP.search(texte, repere['fin_titre'])
        repere['fin'] = cloture.end() if cloture else min(len(texte),
                                                          repere['fin_titre'] + 600)

    sections = []
    for repere in reperes:
        bloc = texte[repere['fin_titre']:repere['fin']]
        contenu = _paragraphes(bloc)
        if '.' in repere['numero']:
            if not sections:
                continue        # une sous-rubrique sans sa rubrique mère
            sections[-1]['subsections'].append({
                'title': f"{repere['numero']} {repere['intitule']}",
                'content': _sans_titre_repete(contenu, repere['intitule']),
            })
        else:
            sections.append({
                'title': f"{repere['numero']}. {repere['intitule']}",
                'content': _sans_titre_repete(contenu, repere['intitule']),
                'subsections': [],
                'source': 'EMA',
            })
    return sections


#: Un RCP compte au minimum les six rubriques du modèle européen. En dessous,
#: l'extraction a échoué — le PDF de Humira ne rend que dix mille caractères
#: d'apostrophes, sa police n'étant pas lisible par pdfplumber. Importer un
#: moignon d'une seule section serait pire que de ne rien importer : la fiche
#: afficherait une monographie qui n'en est pas une, là où l'avertissement
#: « monographie non disponible » disait vrai.
SECTIONS_MINIMUM = 6


def extraction_exploitable(sections):
    """Dit si le résultat mérite d'être écrit. Rend `(bool, raison)`."""
    if len(sections) < SECTIONS_MINIMUM:
        return False, f'{len(sections)} sections seulement'
    paragraphes = sum(len(s['content']) for s in sections)
    paragraphes += sum(len(sub['content']) for s in sections for sub in s['subsections'])
    if paragraphes < 20:
        return False, f'{paragraphes} paragraphes seulement'
    return True, ''


def run():
    analyseur = argparse.ArgumentParser(description=__doc__)
    analyseur.add_argument('--appliquer', action='store_true',
                           help="écrire dans MongoDB (sinon, simulation)")
    analyseur.add_argument('--limite', type=int, default=0,
                           help="ne traiter que les N premières fiches")
    analyseur.add_argument('--pause', type=float, default=1.0,
                           help="secondes entre deux requêtes (défaut : 1)")
    analyseur.add_argument('--rejouer', action='store_true',
                           help="retraiter aussi les fiches déjà importées")
    options = analyseur.parse_args()

    base = MongoClient(MONGO_URI, serverSelectionTimeoutMS=8000)[MONGO_DB]
    filtre = {'source': 'EMA', 'sections': {'$size': 0}}
    if options.rejouer:
        # Rejoue aussi les fiches déjà importées, pour leur appliquer un
        # correctif d'extraction sans repartir des téléchargements.
        filtre = {'source': 'EMA',
                  '$or': [{'sections': {'$size': 0}}, {'rcp_source': 'EMA'}]}
    total = base.medicines.count_documents(filtre)
    curseur = base.medicines.find(filtre, {'title': 1, 'url': 1, 'rcp_source': 1})
    if options.limite:
        curseur = curseur.limit(options.limite)

    print(f"{total} fiches EMA sans monographie"
          + (f", {options.limite} traitées" if options.limite else ''))
    print(f"mode : {'ÉCRITURE' if options.appliquer else 'simulation'}, "
          f"pause {options.pause} s, cache {CACHE}\n")

    comptes = {'importees': 0, 'sans_slug': 0, 'sans_pdf': 0, 'sans_section': 0}
    refus_consecutifs = 0
    debut = time.time()
    for fiche in curseur:
        slug = slug_depuis_url(fiche.get('url'))
        if not slug:
            comptes['sans_slug'] += 1
            continue

        chemin, etat = telecharger(slug, options.pause)
        if not chemin:
            comptes['sans_pdf'] += 1
            print(f"   {fiche.get('title', '')[:34]:<34} {etat}")
            if etat == 'HTTP 429':
                refus_consecutifs += 1
                if refus_consecutifs >= REFUS_CONSECUTIFS_MAXIMUM:
                    print(f"\n   ARRÊT : {refus_consecutifs} refus consécutifs. "
                          f"Le service demande qu'on cesse ; insister ne rendrait "
                          f"rien et le solliciterait pour rien.")
                    print("   Reprendre plus tard avec une pause plus longue "
                          "(--pause 5). Le cache conserve tout ce qui est déjà pris.")
                    break
            else:
                refus_consecutifs = 0
            continue
        refus_consecutifs = 0

        try:
            sections = extraire_sections(texte_du_pdf(chemin))
        except Exception as err:
            comptes['sans_section'] += 1
            print(f"   {fiche.get('title', '')[:34]:<34} extraction : {err}")
            continue

        exploitable, raison = extraction_exploitable(sections)
        if not exploitable:
            comptes['sans_section'] += 1
            print(f"   {fiche.get('title', '')[:34]:<34} écarté : {raison}")
            # Une exécution précédente a pu écrire un résultat que ce
            # garde-fou refuse aujourd'hui : on le retire plutôt que de le
            # laisser en place, sans quoi le correctif ne corrigerait rien
            # pour les fiches déjà traitées.
            if options.appliquer and fiche.get('rcp_source') == 'EMA':
                base.medicines.update_one(
                    {'_id': fiche['_id']},
                    {'$set': {'sections': []},
                     '$unset': {'rcp_source': '', 'rcp_langue': ''}})
            continue

        comptes['importees'] += 1
        sous_total = sum(len(s['subsections']) for s in sections)
        print(f"   {fiche.get('title', '')[:34]:<34} {len(sections)} sections, "
              f"{sous_total} sous-sections  [{etat}]")

        if options.appliquer:
            base.medicines.update_one(
                {'_id': fiche['_id']},
                {'$set': {'sections': sections,
                          'rcp_source': 'EMA',
                          'rcp_langue': 'fr'}})

    duree = time.time() - debut
    print(f"\n   importées      {comptes['importees']}")
    print(f"   PDF absent     {comptes['sans_pdf']}")
    print(f"   sans section   {comptes['sans_section']}")
    print(f"   sans URL       {comptes['sans_slug']}")
    print(f"   durée          {duree:.0f} s")
    if not options.appliquer:
        print("\n   Simulation : rien n'a été écrit. Ajouter --appliquer.")
    return 0


if __name__ == '__main__':
    sys.exit(run())
