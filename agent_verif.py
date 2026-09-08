"""
agent_verif.py — Agent Vérificateur.

Vérifie qu'une collecte est exploitable avant intégration en base.
Effectue une analyse déterministe (règles codées, gratuites et rapides) puis,
optionnellement, un contrôle sémantique par LLM. Retourne un verdict structuré :
    {'valid': bool, 'score': int, 'checks': [...], 'issues': [...], 'llm': {...}}
"""

import json

from agent_lib import complete, mistral_client, ErreurTemporaire

REQUIRED_ANSM_FIELDS = [
    'title',
    'indications',
    'posologie',
]

#: Le score au-dessous duquel une collecte est refusee.
#:
#: Il y a huit controles. Mesure : une seule reserve donne 88, deux en
#: donnent 75. A 80, une reserve passe — un champ que l'ANSM ne remplit
#: pour aucune presentation, une recherche PubMed sans resultat — et deux
#: refusent. En dessous, il ne reste pas assez de matiere pour ecrire une
#: fiche.
#:
#: Le chiffre est ici, nomme, pour qu'on puisse le discuter. Il etait
#: implicitement a 100 : `valid = len(issues) == 0`.
SEUIL_ACCEPTATION = 80

#: Les deux manques qu'aucun score ne rachete : sans notice ANSM, il n'y a
#: pas de medicament a decrire.
#:
#: Nommes ici et emis depuis ces memes constantes. Les comparer a des
#: chaines recopiees a la main est ce qui a failli passer : le test etait
#: ecrit « Aucune donnee ANSM », l'emission « Aucune donnée ANSM », et le
#: veto ne se serait jamais declenche.
SANS_DONNEE_ANSM = 'Aucune donnée ANSM'
SANS_NOTICE_VALIDE = 'Aucune notice ANSM valide collectée'
BLOQUANTS = (SANS_DONNEE_ANSM, SANS_NOTICE_VALIDE)

VERIF_SYSTEM_PROMPT = (
    "Tu es l'AGENT VÉRIFICATEUR d'un pipeline à trois agents (collecteur, vérificateur, superviseur).\n"
    "On te fournit les données collectées sur un médicament (JSON).\n"
    "Ta mission : vérifier que les données sont VRAISEMBLABLES, COHÉRENTES et non inventées.\n"
    "Vérifie notamment :\n"
    " - les titres et champs sont non vides et cohérents avec le nom du médicament\n"
    " - les indications/posologies sont plausibles pour ce type de médicament\n"
    " - les sources (ansm, fda, pubmed) sont cohérentes entre elles\n"
    " - aucune donnée aberrante ou manifestement fausse\n"
    "Réponds UNIQUEMENT en JSON avec la structure exacte :\n"
    "{\"valid\": true|false, \"score\": 0..100, \"issues\": [\"...\"]}\n"
    "Exemples de critères de rejet : champs vides, incohérence grave, données impossibles.\n"
)


def _fusionner_notices(notices: list) -> dict:
    """Rassemble les presentations d'un meme medicament en une seule vue.

    Pourquoi cette fonction existe
    ------------------------------
    Le verificateur ne lisait que la **premiere** notice sans erreur :

        chosen = next((a for a in ansm_list if not a.get('error')), {})

    Mesure sur DOLIPRANE 1000 mg. Le collecteur avait rapporte quatre
    presentations ; l'ANSM ne remplit `indications` que pour l'une
    d'elles :

        60234100  comprime               indications vide
        66567738  comprime effervescent  indications vide
        69309629  gelule                 indications RENSEIGNEE
        61681702  poudre pour solution   indications vide

    La premiere de la liste etant le comprime, la collecte etait rejetee
    pour « champ manquant » alors que l'information avait bien ete
    collectee, une ligne plus bas.

    Ce que fait la fusion
    ---------------------
    Pour chaque champ, la premiere valeur non vide rencontree, dans
    l'ordre ou le collecteur a rapporte les presentations. Un champ que
    l'ANSM laisse vide sur une presentation et remplit sur une autre est
    donc considere comme present : c'est le meme medicament.

    Elle ne fabrique rien. Un champ vide partout reste vide, et le
    controle le signalera — mais il dira alors une verite sur la source,
    pas sur l'ordre de la liste.
    """
    fusion = {}
    origines = {}
    for notice in notices:
        for cle, valeur in notice.items():
            if not isinstance(valeur, str):
                fusion.setdefault(cle, valeur)
                continue
            if fusion.get(cle, '').strip():
                continue
            if valeur.strip():
                fusion[cle] = valeur
                origines[cle] = notice.get('specid')
    #: De quelle presentation vient chaque champ retenu. Sans cette trace,
    #: une fusion de quatre notices se lit comme une notice unique, et on
    #: ne peut plus verifier ce qu'on a affirme.
    fusion['_origines'] = origines
    fusion['_presentations'] = [n.get('specid') for n in notices]
    return fusion


def _rules(data: dict) -> dict:
    checks = []
    issues = []

    task = data.get('task', '')
    ansm = data.get('ansm') or {}
    fda = data.get('fda') or {}
    pubmed = data.get('pubmed') or {}
    summary = (data.get('summary') or '').strip()

    ansm_list = ansm if isinstance(ansm, list) else ([ansm] if ansm else [])

    # 1. Présence ANSM
    if ansm_list:
        valides = [a for a in ansm_list if isinstance(a, dict) and not a.get('error')]
        checks.append(('ansm_présente', bool(valides)))
        if not valides:
            issues.append(SANS_NOTICE_VALIDE)
        else:
            fusion = _fusionner_notices(valides)
            for field in REQUIRED_ANSM_FIELDS:
                value = (fusion.get(field) or '').strip()
                ok = len(value) >= 10
                checks.append((f'ansm.{field}', ok))
                if not ok:
                    issues.append(
                        'Champ ANSM absent de toutes les présentations : %s' % field)
    else:
        checks.append(('ansm_présente', False))
        issues.append(SANS_DONNEE_ANSM)

    # 2. FDA
    fda_ok = bool(fda) and not fda.get('error') and fda.get('total_reports', 0) > 0
    checks.append(('fda_présente', fda_ok))
    if not fda_ok:
        issues.append('Données FDA absentes ou vides')

    # 3. PubMed
    pubmed_ok = bool(pubmed) and not pubmed.get('error') and pubmed.get('studies')
    checks.append(('pubmed_présente', pubmed_ok))
    if not pubmed_ok:
        issues.append('Aucune étude PubMed')

    # 4. Résumé final
    summary_ok = len(summary) >= 20
    checks.append(('summary_présent', summary_ok))
    if not summary_ok:
        issues.append('Résumé final absent ou trop court')

    # 5. Cohérence nom de tâche
    task_ok = bool(task)
    checks.append(('task_présent', task_ok))

    score = round(100.0 * sum(1 for _, ok in checks if ok) / max(1, len(checks)))

    #: La decision se prend sur deux choses : aucun manque redhibitoire,
    #: et un score au-dessus du seuil.
    #:
    #: Elle se prenait sur `len(issues) == 0`. Toute reserve, si mineure
    #: soit-elle, rejetait la collecte. Mesure sur DOLIPRANE 1000 mg : la
    #: premiere tentative a marque **92 sur 100** cote regles et 95 cote
    #: LLM, et a ete rejetee pour un seul champ. Le score etait calcule,
    #: affiche, consigne — et n'entrait dans aucune decision.
    #:
    #: Les manques redhibitoires restent bloquants quel que soit le score :
    #: sans notice ANSM, il n'y a pas de medicament a decrire, et un bon
    #: score obtenu sur la FDA et PubMed ne remplace pas la source.
    #: Compare a la constante, pas a une chaine recopiee. Ecrite a la
    #: main, elle etait accentuee a l'emission — « Aucune donnée ANSM » —
    #: et sans accent dans le test : le veto ne se serait jamais declenche.
    bloquants = [i for i in issues if i in BLOQUANTS]
    valid = not bloquants and score >= SEUIL_ACCEPTATION

    return {'valid': valid, 'score': score, 'checks': checks,
            'issues': issues, 'bloquants': bloquants}


def _llm(data: dict, model: str) -> dict:
    client = mistral_client()
    payload = {
        'task': data.get('task'),
        'ansm': data.get('ansm'),
        'fda': data.get('fda'),
        'pubmed': data.get('pubmed'),
        'summary': data.get('summary'),
    }
    messages = [
        {'role': 'system', 'content': VERIF_SYSTEM_PROMPT},
        {'role': 'user', 'content': 'Données collectées (JSON) :\n' + json.dumps(payload, ensure_ascii=False)[:12000]},
    ]
    try:
        resp = complete(client, messages, tools=None, max_tokens=400)
        raw = (resp.choices[0].message.content or '').strip()
        start, end = raw.find('{'), raw.rfind('}')
        parsed = json.loads(raw[start:end + 1]) if start != -1 and end > start else {}
        return {
            'valid': bool(parsed.get('valid')),
            'score': int(parsed.get('score', 0)),
            'issues': parsed.get('issues', []),
        }
    except ErreurTemporaire as e:
        # Le controle n'a pas pu avoir lieu. `valid=None` le dit, et
        # `verify` retombe alors sur les regles deterministes : une panne
        # de quota ne doit ni valider ni invalider une collecte.
        return {'valid': None, 'score': None, 'temporaire': True,
                'issues': [f'Contrôle LLM indisponible (limite passagère) : {e}']}
    except Exception as e:
        return {'valid': None, 'score': None,
                'issues': [f'Erreur vérification LLM : {e}']}


def verify(data: dict, use_llm: bool = True, model: str = 'mistral-small-2503',
           verbose: bool = True) -> dict:
    rules = _rules(data)

    llm = None
    if use_llm:
        if verbose:
            print('🤖 [Vérificateur] analyse LLM…')
        llm = _llm(data, model)
        if verbose:
            print(f'   verdict LLM : valid={llm.get("valid")} score={llm.get("score")} issues={llm.get("issues")}')

    combined_score = rules['score']
    llm_repondu = bool(llm and llm.get('valid') is not None)

    if llm_repondu:
        combined_score = round((combined_score + llm['score']) / 2)

    #: Les regles deterministes sont la barriere. Le LLM peut retirer,
    #: jamais accorder.
    #:
    #: Le seuil s'appliquait au score **combine**, moyenne des regles et du
    #: LLM. Mesure sur KARDEGIC 75 mg : regles 75, LLM 95, moyenne 85 — au
    #: -dessus du seuil, donc accepte, donc publie. Un document sans
    #: indications ni posologie est entre dans `agent_results` parce que le
    #: modele avait confiance. Le LLM ne pouvait plus dire « non » depuis
    #: qu'on lui avait retire son veto booleen, mais il pouvait dire
    #: « oui » assez fort pour couvrir un refus des regles.
    #:
    #: Trois conditions, toutes necessaires :
    #:   - aucun manque redhibitoire ;
    #:   - le score **des regles seules** au-dessus du seuil ;
    #:   - le LLM qui n'a pas explicitement refuse.
    #:
    #: `combined_score` reste calcule et consigne, pour le diagnostic. Il
    #: n'entre plus dans la decision, ni ici ni chez le superviseur, qui ne
    #: lit que `valid`.
    #: `is not False` et non `is True` : un LLM injoignable rend `None`,
    #: et une panne ne doit pas valoir refus. Seul un refus explicite
    #: retire l'acceptation.
    llm_refuse = bool(llm) and llm.get('valid') is False

    combined_valid = (not rules['bloquants']
                      and rules['score'] >= SEUIL_ACCEPTATION
                      and not llm_refuse)

    #: Une panne du LLM n'est pas un verdict.
    #:
    #: Lors du test, un `429 Rate limit exceeded` faisait remonter
    #: `valid=None`, et l'ancien code laissait alors passer le verdict des
    #: regles seules — ce qui est le bon comportement, mais par accident.
    #: Il est desormais dit : sans reponse du LLM, la decision revient aux
    #: regles, et le rapport porte la mention pour qu'on ne prenne pas une
    #: validation partielle pour une validation complete.
    return {
        'valid': combined_valid,
        'score': combined_score,
        'issues': rules['issues'] + (llm.get('issues') if llm else []),
        'seuil': SEUIL_ACCEPTATION,
        'controle_llm': 'complet' if llm_repondu else (
            'indisponible' if use_llm else 'non demande'),
        'rules': rules,
        'llm': llm,
    }
