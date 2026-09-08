"""
agent_lib.py — Module partagé de l'écosystème d'agents MedicSearch.

Contient la configuration, les outils ANSM/FDA/PubMed et les
defs de l'API MongoDB utilisés par les agents Collecteur, Vérificateur et Superviseur.
"""

import hashlib
import json
import os
import re
import sys
import time

from html import unescape as html_unescape

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from mistralai import Mistral
from pymongo import MongoClient

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, '.env'))
load_dotenv(os.path.join(BASE_DIR, 'frontend_backend', '.env'), override=True)

MISTRAL_API_KEY = os.getenv('MISTRAL_API_KEY')
MONGO_URI = os.getenv('MONGO_URI', 'mongodb://localhost:27017')
DB_NAME = os.getenv('MONGO_DB_NAME', 'medicsearch')

MODEL = 'mistral-small-2503'
MAX_STEPS = 8
MAX_ATTEMPTS = 3
REQUEST_TIMEOUT = 30
USER_AGENT = 'MedicSearchAgent/1.0 (agent de recherche académique)'

ANSM_API_URL = 'https://base-donnees-publique.medicaments.gouv.fr'
ANSM_AUTOCOMPLETE_URL = ANSM_API_URL + '/api/options_autocompilation'
ANSM_EXTRAIT_URL = ANSM_API_URL + '/medicament/%s/extrait'
FDA_API_URL = 'https://api.fda.gov/drug/event.json'
PUBMED_SEARCH_URL = 'https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi'
PUBMED_SUMMARY_URL = 'https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi'

COLLECTION_RESULTS = 'agent_results'
COLLECTION_REPORTS = 'agent_reports'

# ══════════════════════ HTTP ══════════════════════

def _http_get(url, params=None, attempts=2):
    for i in range(attempts):
        try:
            resp = requests.get(url, params=params, headers={'User-Agent': USER_AGENT},
                                timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            return resp
        except requests.exceptions.RequestException:
            if i == attempts - 1:
                raise
            time.sleep(1.5 * (i + 1))


# ══════════════════════ OUTILS DE COLLECT FOR OFFICIAL SOURCES ══════════════════════

def search_ansm(medication_name: str) -> dict:
    """Recherche les notices ANSM d'un médicament via l'API officielle de la BDPM."""
    time.sleep(1.0)
    try:
        query = re.sub(r'(\d)(mg|g|ml|µg|mcg|ui|iu)\b', r'\1 \2', medication_name, flags=re.I)
        resp = _http_get(ANSM_AUTOCOMPLETE_URL, params={
            'searchType': 'medicine', 'term': query
        })

        # `204 No Content` : la requete a abouti, et l'ANSM n'a rien a
        # rendre. C'est la reponse standard pour un terme inconnu.
        #
        # Mesure sur « QQZZXX INEXISTANT 42 » : HTTP 204, corps vide, zero
        # octet. Le code appelait `resp.json()` dessus, ce qui levait
        # « Expecting value: line 1 column 1 (char 0) » — une reponse
        # parfaitement claire du serveur devenait une erreur de parsing,
        # indistinguable d'une panne. Le superviseur relancait alors trois
        # collectes completes pour un nom que l'ANSM ne connait pas.
        if resp.status_code == 204 or not resp.content.strip():
            return {'error': 'Aucune notice trouvée', 'medication': medication_name,
                    'aucune_notice': True}

        data = resp.json()
        results = []
        for item in data or []:
            url = item.get('url', '')
            m = re.search(r'/medicament/(\d+)/extrait', url)
            if m:
                results.append({
                    'specid': m.group(1),
                    'title': item.get('value', ''),
                    'url': ANSM_API_URL + url
                })
        if not results:
            # La recherche a abouti, et l'ANSM ne connait pas ce nom. C'est
            # un fait sur le catalogue, pas un incident.
            #
            # Les deux cas sortaient sous la meme cle `error`, distingues
            # par le seul libelle. Un appelant qui voudrait les separer
            # devrait comparer une chaine — c'est exactement le piege qui a
            # failli faire passer le veto ANSM a cote de son accent. Le
            # marqueur est explicite ; le libelle reste, pour l'affichage.
            return {'error': 'Aucune notice trouvée', 'medication': medication_name,
                    'aucune_notice': True}
        return {'medication': medication_name, 'results': results[:15]}
    except Exception as e:
        # Une panne : reseau, HTTP, parsing. Elle ne porte pas
        # `aucune_notice` — on ne sait pas ce que l'ANSM aurait repondu.
        return {'error': str(e), 'medication': medication_name}


def _extract_sections(html: str, prefix: str) -> list:
    """Extrait les sections d'une notice ANSM délimitées par <a name='...'>."""
    sections = []
    for m in re.finditer(r'<a name="(' + prefix + r'_\w+|' + prefix + r'\w+)"', html):
        name = m.group(1)
        if name in [s['anchor'] for s in sections]:
            continue
        start = m.end()
        nxt = html.find('<a name="Rcp', start)
        nxt2 = html.find('<a name="Ann3b', start)
        candidates = [i for i in (nxt, nxt2) if i != -1 and i > start]
        end = min(candidates) if candidates else start + 20000
        raw = html[start:end]
        raw = re.sub(r'<script.*?</script>', '', raw, flags=re.S)
        text = html_unescape(re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', raw))).strip()
        title_m = re.search(r'<span id=[\'"][^\'"]*[\'"]>([^<]+)</span>', html[m.start():start])
        title = re.sub(r'\s+', ' ', title_m.group(1)).strip() if title_m else ''
        sections.append({
            'anchor': name,
            'title': title,
            'text': text[:4000]
        })
    return sections


def fetch_ansm_notice(specid: str) -> dict:
    """Récupère le contenu complet d'une notice ANSM (fiche info + RCP + notice)."""
    time.sleep(1.0)
    try:
        resp = _http_get(ANSM_EXTRAIT_URL % specid)
        html = resp.text
        soup = BeautifulSoup(html, 'html.parser')

        title = ''
        title_el = soup.find('h1') or soup.find('h2')
        if title_el:
            candidate = re.sub(r'\s+', ' ', title_el.get_text(' ', strip=True))
            if 'paramètre' not in candidate.lower() and 'affichage' not in candidate.lower():
                title = candidate
        if not title:
            for h in soup.find_all(['h1', 'h2', 'h3']):
                candidate = re.sub(r'\s+', ' ', h.get_text(' ', strip=True))
                if candidate and 'paramètre' not in candidate.lower() and 'affichage' not in candidate.lower() and 'Médicament' not in candidate:
                    title = candidate
                    break

        date_match = re.search(r'Date de l\'autorisation\s*:\s*([\d/]+)', html)
        auth_date = date_match.group(1) if date_match else ''

        info_match = re.search(r'<a name="RcpDateRevision">.*?</a></p>(.{0,500})', html, re.S)
        revision_date = ''
        if info_match:
            rev = re.search(r'([\d/]{8,10})', re.sub(r'<[^>]+>', ' ', info_match.group(1)))
            if rev:
                revision_date = rev.group(1)

        rcp_sections = _extract_sections(html, 'Rcp')
        notice_sections = _extract_sections(html, 'Ann3b')

        def _section(sections, anchor):
            """Retourne la section exacte, ou la première dont l'ancre commence par anchor."""
            for s in sections:
                if s['anchor'] == anchor:
                    return s['text']
            for s in sections:
                if s['anchor'].startswith(anchor):
                    return s['text']
            return ''

        def _section_multi(sections, anchors):
            parts = [_section(sections, a) for a in anchors]
            parts = [p for p in parts if p]
            return ' | '.join(parts)

        return {
            'specid': specid,
            'title': title,
            'authorisation_date': auth_date,
            'revision_date': revision_date,
            'indications': _section(rcp_sections, 'RcpIndicTherap'),
            'posologie': _section_multi(rcp_sections, ['RcpPosoAdmin', 'Rcp_4_2_PosoAdmin']),
            'contre_indications': _section(rcp_sections, 'RcpContreindications'),
            'mises_en_garde': _section_multi(rcp_sections, ['RcpMisesEnGarde', 'Rcp_4_4_MisesEnGarde']),
            'interactions': _section(rcp_sections, 'RcpInteractionsMed'),
            'effets_indesirables': _section(rcp_sections, 'RcpEffetsIndesirables'),
            'surdosage': _section_multi(rcp_sections, ['RcpSurdosage', 'Rcp_4_9_Surdosage']),
            'grossesse_allaitement': _section(rcp_sections, 'RcpFertGrossAllait'),
            'conduite': _section(rcp_sections, 'RcpConduite'),
            'pharmacocinetique': _section_multi(rcp_sections, ['RcpPropPharmacocinetiques', 'Rcp_5_2_PropPharmacocinetique']),
            'titulaire': _section(rcp_sections, 'RcpTitulaireAmm'),
            'notice_quest_ce_que': _section(notice_sections, 'Ann3bQuestceque'),
            'notice_comment_prendre': _section_multi(notice_sections, ['Ann3bCommentPrendre', 'Ann3b_PosoModAdmin']),
            'notice_mises_en_garde': _section(notice_sections, 'Ann3b_MisesEnGarde'),
            'notice_effets_indesirables': _section(notice_sections, 'Ann3bEffetsIndesirables'),
            'notice_conservation': _section(notice_sections, 'Ann3bConservation'),
            'notice_contenu_emballage': _section(notice_sections, 'Ann3bContenu'),
            'rcp_sections_count': len(rcp_sections),
            'notice_sections_count': len(notice_sections)
        }
    except Exception as e:
        return {'error': str(e), 'specid': specid}


def fetch_fda_events(medication_name: str) -> dict:
    """Récupère les effets indésirables déclarés (openFDA)."""
    try:
        data = None
        last_error = ''
        searches = [
            f'patient.drug.medicinalproduct:"{medication_name}"',
            f'patient.drug.openfda.generic_name:"{medication_name}"',
            f'patient.drug.openfda.brand_name:"{medication_name}"',
        ]
        for search in searches:
            try:
                resp = _http_get(FDA_API_URL, params={
                    'search': search, 'limit': 20
                })
                data = resp.json()
                if data.get('results'):
                    break
            except requests.exceptions.HTTPError as e:
                last_error = f'{search} : {e}'
        if not data:
            return {'error': f'Aucune déclaration FDA trouvée ({last_error})',
                    'medication': medication_name}
        results = data.get('results', [])
        reactions = {}
        for r in results:
            for reac in (r.get('patient', {}).get('reaction', []) or []):
                meddra = reac.get('reactionmeddrapt', '')
                if meddra:
                    reactions[meddra] = reactions.get(meddra, 0) + 1
        top_reactions = sorted(reactions.items(), key=lambda kv: -kv[1])[:15]
        return {
            'medication': medication_name,
            'total_reports': data.get('meta', {}).get('results', {}).get('total', 0),
            'top_reactions': [{'reaction': r, 'count': c} for r, c in top_reactions]
        }
    except Exception as e:
        return {'error': str(e), 'medication': medication_name}


def fetch_pubmed(medication_name: str) -> dict:
    """Récupère les publications récentes liées au médicament."""
    try:
        term = f'{medication_name}[Title] AND drug[Title]'
        search = _http_get(PUBMED_SEARCH_URL, params={
            'db': 'pubmed', 'term': term, 'retmax': 5, 'retmode': 'json'
        }).json()
        ids = search.get('esearchresult', {}).get('idlist', [])
        if not ids:
            return {'medication': medication_name, 'studies': [], 'total': 0}

        summary = _http_get(PUBMED_SUMMARY_URL, params={
            'db': 'pubmed', 'id': ','.join(ids), 'retmode': 'json'
        }).json()
        result = summary.get('result', {})
        studies = []
        for pid in ids:
            item = result.get(pid, {})
            studies.append({
                'title': item.get('title', ''),
                'year': (item.get('pubdate', '') or '')[:4],
                'journal': item.get('fulljournalname', ''),
                'link': f"https://pubmed.ncbi.nlm.nih.gov/{pid}/"
            })
        return {'medication': medication_name, 'studies': studies, 'total': len(studies)}
    except Exception as e:
        # `{'error': ..., 'medication_name'}` : une cle sans valeur. Le
        # module entier ne se compilait pas, et les trois agents ne
        # pouvaient donc pas etre importes. La forme juste est celle des
        # trois autres outils du fichier, dont `fetch_fda_events` juste
        # au-dessus : la cle est `medication`, la valeur est le parametre.
        return {'error': str(e), 'medication': medication_name}

# ══════════════════════ MONGO ══════════════════════

def _client():
    return MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)


def _get_collection(name):
    return _client()[DB_NAME][name]


def doc_id_for(task: str) -> str:
    return hashlib.sha1(task.encode()).hexdigest()[:16]


def get_collection_results():
    return _get_collection(COLLECTION_RESULTS)


def get_collection_reports():
    return _get_collection(COLLECTION_REPORTS)


def save_result(task: str, data: dict) -> dict:
    try:
        coll = get_collection_results()
        doc_id = doc_id_for(task)
        fields = {k: v for k, v in data.items() if k != 'task'}
        fields['updated_at'] = time.strftime('%Y-%m-%d %H:%M:%S')
        coll.update_one(
            {'_id': doc_id},
            {'$set': {'task': task, **fields}},
            upsert=True
        )
        return {'saved': True, 'document_id': doc_id}
    except Exception as e:
        return {'saved': False, 'error': str(e)}

# ══════════════════════ MISTRAL ══════════════════════

def mistral_client():
    if not MISTRAL_API_KEY:
        print('❌ MISTRAL_API_KEY manquante. Ajoutez-la dans le fichier .env')
        sys.exit(1)
    return Mistral(api_key=MISTRAL_API_KEY)


#: Combien de fois reessayer un appel au modele, et a partir de quelle
#: attente. L'attente double a chaque essai : 2 s, 4 s, 8 s.
#:
#: Le fournisseur ne renvoie pas d'en-tete `Retry-After` exploitable ici ;
#: a defaut, doubler est la regle habituelle, et elle a le merite de ne
#: pas taper plus fort quand on vient de se faire refuser.
ESSAIS_MODELE = 4
ATTENTE_INITIALE = 2.0

#: Codes qui disent « reessaie plus tard », par opposition a « ta requete
#: est mauvaise ». Reessayer un 400 ne le rendra pas bon ; reessayer un
#: 429 ou un 503, si.
CODES_TEMPORAIRES = (408, 409, 425, 429, 500, 502, 503, 504)


class ErreurTemporaire(RuntimeError):
    """Un echec dont on sait qu'il peut disparaitre tout seul.

    Distinguee d'une erreur de requete pour que l'appelant ne confonde pas
    « le quota est atteint » avec « les donnees sont mauvaises ». Lors du
    test sur DOLIPRANE, le superviseur a compte un `429` comme une
    collecte ratee, a tout relance, et a conclu a un echec de donnees
    alors que rien n'avait ete collecte du tout.
    """


def _est_temporaire(err) -> bool:
    """Dit si l'echec merite d'etre reessaye.

    Le code fait foi quand il est connu ; le texte n'est qu'un repli.
    L'inverse — chercher « rate limit » dans le message avant de regarder
    le code — faisait reessayer quatre fois une reponse `400` dont le
    corps citait le mot. Le banc l'a relevee : une requete mauvaise le
    reste, et la reessayer ne fait que payer trois fois le meme refus.
    """
    #: Le code porte par l'exception, s'il y en a un : il tranche.
    for attribut in ('status_code', 'http_status', 'code', 'status'):
        valeur = getattr(err, attribut, None)
        if isinstance(valeur, int) and 100 <= valeur < 600:
            return valeur in CODES_TEMPORAIRES

    texte = str(err).lower()

    #: Le code lu dans le message, a defaut. « Status 429 » dit la meme
    #: chose que l'attribut, et « Status 400 » aussi.
    trouve = re.search(r'status[ :]+(\d{3})', texte)
    if trouve:
        return int(trouve.group(1)) in CODES_TEMPORAIRES

    #: Sans code, on se rabat sur ce que dit le message.
    return any(marqueur in texte for marqueur in (
        'rate limit', 'rate_limited', 'too many requests', 'timeout',
        'timed out', 'temporarily unavailable', 'service unavailable',
        'connection reset', 'connection aborted'))


def complete(client, messages, tools=None, max_tokens=1500,
             essais=ESSAIS_MODELE, verbose=True):
    """Appelle le modele, en reessayant les echecs temporaires.

    Le test sur DOLIPRANE 1000 mg a bute la-dessus : au deuxieme appel,
    `429 Rate limit exceeded`. L'appel remontait tel quel, le superviseur
    relancait **une collecte entiere** dans la seconde, reprenait un 429,
    puis un troisieme. La tentative finale n'a rien collecte du tout et
    l'echec a ete impute aux donnees.

    Relancer immediatement apres un refus de quota garantit le refus
    suivant. On attend, et on double l'attente.
    """
    attente = ATTENTE_INITIALE
    derniere = None
    for essai in range(1, max(1, essais) + 1):
        try:
            return client.chat.complete(
                model=MODEL,
                messages=messages,
                tools=tools,
                tool_choice='auto' if tools else None,
                max_tokens=max_tokens,
            )
        except Exception as err:
            derniere = err
            if not _est_temporaire(err):
                raise
            if essai == essais:
                break
            if verbose:
                print('   ⏳ echec temporaire (%s) — nouvel essai dans %.0f s '
                      '[%d/%d]' % (type(err).__name__, attente, essai, essais))
            time.sleep(attente)
            attente *= 2

    raise ErreurTemporaire(
        '%d essais epuises sur un echec temporaire : %s' % (essais, derniere))