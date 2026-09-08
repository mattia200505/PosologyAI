"""
agent_collecte.py — Agent Collecteur.

Boucle ReAct + Mistral qui interroge ANSM, FDA et PubMed pour un médicament,
accumule les résultats de chaque outil dans une structure de données, puis
retourne cette structure SANS écrire en base (l'écriture est réservée au
superviseur après validation).
"""

import json

from agent_lib import (MODEL, MAX_STEPS, mistral_client, complete,
                       search_ansm, fetch_ansm_notice, fetch_fda_events,
                       fetch_pubmed, ErreurTemporaire)

TOOL_IMPL = {
    'search_ansm': search_ansm,
    'fetch_ansm_notice': fetch_ansm_notice,
    'fetch_fda_events': fetch_fda_events,
    'fetch_pubmed': fetch_pubmed,
}

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
]

SYSTEM_PROMPT = (
    "Tu es l'AGENT COLLECTEUR d'un pipeline à trois agents (collecteur, vérificateur, superviseur).\n"
    "Ta mission est UNIQUEMENT de collecter les données médicales du médicament demandé, en français.\n\n"
    "Règles :\n"
    "1. Commence par chercher la notice ANSM (source officielle française), puis complète avec la FDA et PubMed.\n"
    "2. Choisis la notice ANSM la plus pertinente parmi les candidats (meilleure correspondance de titre).\n"
    "3. Utilise les effets indésirables FDA avec le nom générique du médicament (ex: paracetamol, amoxicillin).\n"
    "4. NE JAMAIS inventer de données : si une source échoue ou ne trouve rien, le mentionner explicitement.\n"
    "5. Tu ne sauvegardes rien : réponds simplement par un court résumé de fin quand tu as collecté les données.\n"
)


def _format_args(raw: str) -> dict:
    try:
        args = json.loads(raw or '{}')
        return args if isinstance(args, dict) else {}
    except Exception:
        return {}


def collect(task: str, model: str = MODEL, max_steps: int = MAX_STEPS,
            verbose: bool = True) -> dict:
    client = mistral_client()
    messages = [
        {'role': 'system', 'content': SYSTEM_PROMPT},
        {'role': 'user', 'content': f'Médicament à étudier : {task}'},
    ]

    collected = {
        'task': task,
        'medicine_name': task,
        'ansm': {},
        'fda': {},
        'pubmed': {},
        'summary': '',
    }
    summary = ''

    if verbose:
        print(f'🤖 [Collecteur] — tâche : {task}')

    for step in range(1, max_steps + 1):
        try:
            resp = complete(client, messages, tools=TOOLS, verbose=verbose)
        except ErreurTemporaire as e:
            # Le quota, pas les donnees. Ce qui a deja ete collecte est
            # rendu tel quel et marque : le superviseur doit pouvoir
            # distinguer « rien trouve » de « pas pu demander ».
            if verbose:
                print(f'⏸️ [Collecteur] Interrompu par une limite passagere : {e}')
            return collected | {'error': str(e), 'temporaire': True,
                                'summary': summary}
        except Exception as e:
            if verbose:
                print(f'❌ [Collecteur] Erreur API Mistral : {e}')
            return collected | {'error': str(e), 'summary': summary}

        msg = resp.choices[0].message
        content = msg.content or ''

        if not msg.tool_calls:
            summary = content
            collected['summary'] = content
            if verbose:
                print('━━━ [Collecteur] Résumé de fin ━━━')
                print(content)
            break

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
            if verbose:
                print(f'[étape {step}] 🔧 {name}({json.dumps(args, ensure_ascii=False)[:120]})')

            try:
                result = TOOL_IMPL[name](**args)
            except Exception as e:
                result = {'error': str(e)}

            if name == 'search_ansm':
                collected['ansm_search'] = result
            elif name == 'fetch_ansm_notice':
                existing = collected['ansm']
                if not isinstance(existing, list):
                    existing = [existing] if existing else []
                existing = [e for e in existing if e.get('specid') != result.get('specid')]
                existing.append(result)
                collected['ansm'] = existing
            elif name == 'fetch_fda_events':
                collected['fda'] = result
            elif name == 'fetch_pubmed':
                collected['pubmed'] = result

            if verbose:
                snippet = json.dumps(result, ensure_ascii=False)[:300]
                print(f'  └─ résultat : {snippet}')

            messages.append({
                'role': 'tool',
                'tool_call_id': tc.id,
                'content': json.dumps(result, ensure_ascii=False)[:12000],
            })

    return collected
