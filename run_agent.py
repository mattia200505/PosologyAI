"""
MedicSearch Agent Scraper v1
Agent IA autonome (boucle ReAct + Mistral tool calling) qui collecte les données
médicales d'un médicament depuis ANSM, FDA et PubMed, puis sauvegarde le tout
dans une collection MongoDB dédiée (agent_results) pour validation.

Usage:
    python run_agent.py "DOLIPRANE 500mg"
    python run_agent.py "AMOXICILLINE 1g" --model mistral-small-latest
"""

import argparse
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

# ══════════════════════ CONFIG ══════════════════════

MISTRAL_API_KEY = os.getenv('MISTRAL_API_KEY')
MONGO_URI = os.getenv('MONGO_URI', 'mongodb://localhost:27017')
DB_NAME = os.getenv('MONGO_DB_NAME', 'medicsearch')

MODEL = 'mistral-small-2503'
MAX_STEPS = 8
REQUEST_TIMEOUT = 30
USER_AGENT = 'MedicSearchAgent/1.0 (bot de recherche académique)'

ANSM_API_URL = 'https://base-donnees-publique.medicaments.gouv.fr'
ANSM_AUTOCOMPLETE_URL = ANSM_API_URL + '/api/options_autocompilation'
ANSM_EXTRAIT_URL = ANSM_API_URL + '/medicament/%s/extrait'
ANSM_DUMP_URL = ANSM_API_URL + '/download/file/CIS_bdpm.txt'
FDA_API_URL = 'https://api.fda.gov/drug/event.json'
PUBMED_SEARCH_URL = 'https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi'
PUBMED_SUMMARY_URL = 'https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi'

# ══════════════════════ OUTILS (implémentation) ══════════════════════

def _http_get(url, params=None):
    resp = requests.get(url, params=params, headers={'User-Agent': USER_AGENT},
                        timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    return resp


def search_ansm(medication_name: str) -> dict:
    """Recherche les notices ANSM d'un médicament via l'API officielle de la BDPM."""
    time.sleep(1.0)
    try:
        query = re.sub(r'(\d)(mg|g|ml|µg|mcg|ui|iu)\b', r'\1 \2', medication_name, flags=re.I)
        resp = _http_get(ANSM_AUTOCOMPLETE_URL, params={
            'searchType': 'medicine', 'term': query
        })
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
            return {'error': 'Aucune notice trouvée', 'medication': medication_name}
        return {'medication': medication_name, 'results': results[:15]}
    except Exception as e:
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
        return {'error': str(e), 'medication': medication_name}


def _get_collection():
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    return client[DB_NAME]['agent_results']


def save_results(data: dict) -> dict:
    """Sauvegarde / fusionne des données dans la collection agent_results."""
    try:
        task_id = data.get('task', 'unknown')
        doc_id = hashlib.sha1(task_id.encode()).hexdigest()[:16]
        fields = {k: v for k, v in data.items() if k != 'task'}
        fields['updated_at'] = time.strftime('%Y-%m-%d %H:%M:%S')
        coll = _get_collection()
        coll.update_one(
            {'_id': doc_id},
            {'$set': {'task': task_id, **fields}},
            upsert=True
        )
        return {'saved': True, 'document_id': doc_id}
    except Exception as e:
        return {'saved': False, 'error': str(e)}


# ══════════════════════ SCHÉMAS DES OUTILS ══════════════════════

TOOLS = [
    {
        'type': 'function',
        'function': {
            'name': 'search_ansm',
            'description': 'Recherche les notices officielles ANSM (base publique des médicaments) pour un nom de médicament donné. Retourne une liste de notices candidates avec leur identifiant.',
            'parameters': {
                'type': 'object',
                'properties': {
                    'medication_name': {'type': 'string', 'description': 'Nom du médicament à chercher (ex: DOLIPRANE 500mg)'}
                },
                'required': ['medication_name']
            }
        }
    },
    {
        'type': 'function',
        'function': {
            'name': 'fetch_ansm_notice',
            'description': 'Récupère le contenu structuré d\'une notice ANSM (titre, mise à jour, laboratoire, substances actives, sections) à partir de son identifiant specid.',
            'parameters': {
                'type': 'object',
                'properties': {
                    'specid': {'type': 'string', 'description': 'Identifiant numérique de la notice obtenu via search_ansm'}
                },
                'required': ['specid']
            }
        }
    },
    {
        'type': 'function',
        'function': {
            'name': 'fetch_fda_events',
            'description': 'Récupère les effets indésirables déclarés à la FDA (openFDA) pour un médicament, avec le nombre de déclarations et les réactions les plus fréquentes.',
            'parameters': {
                'type': 'object',
                'properties': {
                    'medication_name': {'type': 'string', 'description': 'Nom générique du médicament (ex: paracetamol)'}
                },
                'required': ['medication_name']
            }
        }
    },
    {
        'type': 'function',
        'function': {
            'name': 'fetch_pubmed',
            'description': 'Recherche les publications scientifiques récentes sur un médicament dans PubMed.',
            'parameters': {
                'type': 'object',
                'properties': {
                    'medication_name': {'type': 'string', 'description': 'Nom du médicament (ex: paracetamol)'}
                },
                'required': ['medication_name']
            }
        }
    },
    {
        'type': 'function',
        'function': {
            'name': 'save_results',
            'description': 'Sauvegarde les données collectées dans la base. Doit être appelé avec un objet contenant le champ "task" (nom de la tâche) et les données organisées par source (ansm, fda, pubmed...).',
            'parameters': {
                'type': 'object',
                'properties': {
                    'task': {'type': 'string', 'description': 'Identifiant de la tâche, ex: "DOLIPRANE 500mg"'},
                    'data': {'type': 'object', 'description': 'Données structurées à sauvegarder (fusionnées par champ)'}
                },
                'required': ['task', 'data']
            }
        }
    }
]

SYSTEM_PROMPT = """Tu es un agent autonome de collecte de données médicales pour la plateforme MedicSearch.

Ta mission : collecter TOUTES les informations disponibles sur le médicament demandé, en français.

Règles :
1. Commence par chercher la notice ANSM (source officielle française), puis complète avec la FDA et PubMed.
2. Choisis la notice ANSM la plus pertinente parmi les candidats (meilleure correspondance de titre).
3. Utilise les effets indésirables FDA avec le nom générique du médicament (ex: paracetamol, amoxicillin).
4. NE JAMAIS inventer de données : si une source échoue ou ne trouve rien, le mentionner explicitement.
5. Une fois les données collectées, appelle obligatoirement l'outil save_results avec un objet contenant "task" (le nom du médicament) et "data" organisé par source : {ansm: {...}, fda: {...}, pubmed: {...}}.
6. Termine par un résumé final en français (max 150 mots) indiquant ce qui a été trouvé et les éventuelles limites."""


# ══════════════════════ BOUCLE AGENT ══════════════════════

TOOL_IMPL = {
    'search_ansm': search_ansm,
    'fetch_ansm_notice': fetch_ansm_notice,
    'fetch_fda_events': fetch_fda_events,
    'fetch_pubmed': fetch_pubmed,
    'save_results': save_results,
}


def _format_args(raw: str) -> dict:
    try:
        args = json.loads(raw or '{}')
        return args if isinstance(args, dict) else {}
    except Exception:
        return {}


def run_agent(task: str, model: str = MODEL, verbose: bool = True):
    if not MISTRAL_API_KEY:
        print('❌ MISTRAL_API_KEY manquante. Ajoutez-la dans le fichier .env')
        sys.exit(1)

    client = Mistral(api_key=MISTRAL_API_KEY)
    messages = [
        {'role': 'system', 'content': SYSTEM_PROMPT},
        {'role': 'user', 'content': f'Médicament à étudier : {task}'},
    ]

    print(f'🤖 Agent démarré — tâche : {task}\n')

    for step in range(1, MAX_STEPS + 1):
        try:
            resp = client.chat.complete(
                model=model,
                messages=messages,
                tools=TOOLS,
                tool_choice='auto',
                max_tokens=1500,
            )
        except Exception as e:
            print(f'❌ Erreur API Mistral : {e}')
            sys.exit(1)

        msg = resp.choices[0].message
        content = msg.content or ''

        if not msg.tool_calls:
            print('━━━ Résumé final de l\'agent ━━━')
            print(content)
            saved = save_results({'task': task, 'medicine_name': task, 'summary': content})
            if saved.get('saved'):
                print(f'\n*Document sauvegardé sous l\'ID : {saved["document_id"]}.*')
            return

        messages.append({
            'role': 'assistant',
            'content': content,
            'tool_calls': [
                {
                    'id': tc.id,
                    'type': 'function',
                    'function': {
                        'name': tc.function.name,
                        'arguments': tc.function.arguments or '{}'
                    }
                }
                for tc in msg.tool_calls
            ]
        })

        for tc in msg.tool_calls:
            name = tc.function.name
            args = _format_args(tc.function.arguments)
            print(f'[étape {step}] 🔧 {name}({json.dumps(args, ensure_ascii=False)[:120]})')

            try:
                if name == 'save_results':
                    payload = dict(args)
                    data = payload.pop('data', {}) or {}
                    result = save_results({'task': payload.get('task', task), **data})
                else:
                    result = TOOL_IMPL[name](**args)
            except TypeError as e:
                result = {'error': f'Arguments invalides pour {name}: {e}'}
            except Exception as e:
                result = {'error': str(e)}

            snippet = json.dumps(result, ensure_ascii=False)[:400]
            print(f'  └─ résultat : {snippet}...' if len(snippet) >= 400 else f'  └─ résultat : {snippet}')

            messages.append({
                'role': 'tool',
                'tool_call_id': tc.id,
                'content': json.dumps(result, ensure_ascii=False)[:12000],
            })
            time.sleep(0.5)

    print('⚠️ Nombre maximal d\'étapes atteint sans réponse finale.')


def main():
    parser = argparse.ArgumentParser(description='MedicSearch Agent Scraper v1')
    parser.add_argument('medication', help='Nom du médicament à étudier (ex: "DOLIPRANE 500mg")')
    parser.add_argument('--model', default=MODEL, help=f'Modèle Mistral (défaut: {MODEL})')
    args = parser.parse_args()
    run_agent(args.medication, args.model)


if __name__ == '__main__':
    main()
