"""
agent_superviseur.py — Agent Superviseur (orchestrateur).

Coordonne le Collecteur et le Vérificateur pour chaque médicament :
 1. lance le collecteur
 2. fait vérifier les données
 3. relance la collecte (max MAX_ATTEMPTS) si le verdict est négatif
 4. n'écrit en base que si le verdict final est positif
 5. consigne un rapport d'activité dans agent_reports
"""

import time

from agent_lib import (MAX_ATTEMPTS, save_result, get_collection_reports,
                       doc_id_for, ATTENTE_INITIALE)

from agent_collecte import collect
from agent_verif import verify


#: Les motifs d'echec, nommes. Un rapport doit dire **pourquoi** il n'a
#: rien ecrit, pas seulement qu'il n'a rien ecrit.
#:
#: Ils se confondaient tous en `failed`. Releve sur les 66 rapports
#: existants : quatre causes bien distinctes, un seul statut.
#:
#:     ZZZQXW MEDICAMENT INEXISTANT   failed   l'ANSM ne connait pas ce nom
#:     HYDROCHLOROTHIAZIDE ARROW      failed   HTTP 500 de l'ANSM
#:     OXYPLASTINE 46%                failed   notice trouvee, contenu pauvre
#:     SEREPROSTA 160 mg              failed   notice trouvee, contenu pauvre
#:
#: L'information etait recuperable dans `attempts[].issues`, mais il
#: fallait la reconstituer. Un statut qui demande une reconstitution ne
#: dit rien a qui relit la base six mois plus tard.
INTROUVABLE = 'not_found'          # l'ANSM a repondu, et ne connait pas ce nom
SOURCE_INDISPONIBLE = 'source_indisponible'   # la recherche ANSM a echoue
INTERROMPU = 'interrompu'          # limite passagere du modele, apres reprises
INSUFFISANT = 'insuffisant'        # notice trouvee, contenu rejete par les regles
ECHEC = 'failed'                   # aucune des causes ci-dessus n'est etablie

#: Ce que chaque motif dit a l'ecran. Le rapport en base porte le code,
#: la console porte la phrase : ni l'un ni l'autre ne se devine.
MOTIF_ICONE = {
    INTROUVABLE: '🔍',
    SOURCE_INDISPONIBLE: '📡',
    INTERROMPU: '⏸️',
    INSUFFISANT: '📄',
    ECHEC: '❌',
}

MOTIF_PHRASE = {
    INTROUVABLE: "L'ANSM ne connaît pas ce nom — rien écrit, et ce n'est pas "
                 'un jugement sur le médicament.',
    SOURCE_INDISPONIBLE: "La recherche ANSM a échoué — on ignore ce qu'elle "
                         "aurait répondu. Rien écrit, rien conclu.",
    INTERROMPU: "Aucune tentative n'a pu aboutir (limite passagère) — rien "
                'écrit, aucun jugement porté sur ce médicament.',
    INSUFFISANT: 'Notice trouvée, mais son contenu ne suffit pas aux règles — '
                 'rien écrit.',
    ECHEC: 'Échec — aucune cause établie.',
}


def _motif_echec(data: dict, attempts: list) -> str:
    """Nomme la cause d'un echec, sans rien decider.

    Cette fonction ne participe a aucune decision : le verdict est deja
    pris, l'ecriture deja refusee. Elle ne fait que qualifier ce qui
    s'est passe, pour que `agent_reports` soit relisible.

    L'ordre des questions va du plus certain au plus vague :

    1. toutes les tentatives interrompues -> on n'a rien pu demander ;
    2. l'ANSM a repondu qu'elle ne connait pas -> absence etablie ;
    3. la recherche ANSM a echoue -> on ne sait pas, la source est muette ;
    4. des notices ont ete collectees -> c'est leur contenu qui manque ;
    5. sinon, `failed` : aucune cause etablie, et on ne l'invente pas.
    """
    if attempts and all(a.get('status') == INTERROMPU for a in attempts):
        return INTERROMPU

    recherche = (data or {}).get('ansm_search') or {}
    if recherche.get('aucune_notice'):
        return INTROUVABLE
    if recherche.get('error'):
        return SOURCE_INDISPONIBLE

    notices = (data or {}).get('ansm') or []
    if not isinstance(notices, list):
        notices = [notices]
    if [n for n in notices if isinstance(n, dict) and not n.get('error')]:
        return INSUFFISANT

    return ECHEC


def _write_report(task: str, run: dict):
    coll = get_collection_reports()
    doc_id = doc_id_for(task) + '_' + time.strftime('%Y%m%d%H%M%S')
    coll.insert_one({'_id': doc_id, 'task': task, **run})


def process_medicine(task: str, use_llm: bool = True, max_attempts: int = MAX_ATTEMPTS,
                     verbose: bool = True) -> dict:
    attempts = []
    final = None
    #: La derniere collecte, quelle qu'elle vaille. Lue en fin de course
    #: par `_motif_echec`, qui a besoin de savoir ce que la source a
    #: repondu — et non seulement que le verdict etait negatif.
    data = None

    for attempt in range(1, max_attempts + 1):
        if verbose:
            print(f'\n━━━ [Superviseur] Tentative {attempt}/{max_attempts} — {task} ━━━')

        data = collect(task, verbose=verbose)

        # Une collecte interrompue par une limite passagere n'est pas une
        # collecte ratee : rien n'a ete demande a la source.
        #
        # Mesure sur DOLIPRANE 1000 mg. La tentative 2 a pris un 429, la 3
        # aussi, et le rapport final a conclu « Aucune donnee ANSM /
        # Donnees FDA absentes / Aucune etude PubMed » — un verdict sur des
        # donnees que personne n'etait alle chercher. Le quota etait
        # epuise, pas le medicament introuvable.
        if data.get('temporaire'):
            attente = ATTENTE_INITIALE * (2 ** (attempt - 1))
            attempts.append({
                'attempt': attempt,
                'status': 'interrompu',
                'score': None,
                'issues': [data.get('error', 'limite passagère')],
            })
            if attempt < max_attempts:
                if verbose:
                    print('⏸️ [Superviseur] Limite passagère — pause de %.0f s '
                          'avant la tentative suivante.' % attente)
                time.sleep(attente)
                continue
            if verbose:
                print('⏸️ [Superviseur] Limite passagère sur la dernière '
                      'tentative — rien écrit, rien conclu sur les données.')
            break

        if verbose:
            print(f'\n━━━ [Superviseur] Vérification de la collecte ━━━')
        verdict = verify(data, use_llm=use_llm, verbose=verbose)

        record = {
            'attempt': attempt,
            'status': 'valid' if verdict['valid'] else 'rejected',
            'score': verdict['score'],
            'issues': verdict['issues'],
        }
        attempts.append(record)

        if verdict['valid']:
            final = {'data': data, 'verdict': verdict}
            if verbose:
                print(f'✅ [Superviseur] Collecte validée (score {verdict["score"]})')
            break

        if verbose:
            print(f'⚠️ [Superviseur] Rejetée (score {verdict["score"]}) : {" / ".join(verdict["issues"]) or "aucun critère rempli"}')

        # Recommencer ne sert que si le resultat peut changer.
        #
        # Mesure sur « QQZZXX INEXISTANT 42 » : trois collectes completes,
        # quinze appels au modele, trente-neuf secondes — pour un nom que
        # l'ANSM ne connait pas, ce que la premiere recherche avait etabli.
        # Les deux tentatives suivantes ont repose la meme question au meme
        # catalogue et recu la meme reponse.
        #
        # Le marqueur vient de `search_ansm`, qui ne le pose que lorsque la
        # requete a **abouti** et n'a rien rendu. Une panne reseau, un 429,
        # un 5xx, un delai depasse ne le portent pas : ces cas gardent
        # entierement le mecanisme de reprise, traite plus haut.
        #
        # Le verdict est deja calcule, enregistre et affiche. Cette sortie
        # ne change ni le veto, ni le seuil, ni la decision : elle cesse
        # seulement de reposer une question dont la reponse est acquise.
        if (data.get('ansm_search') or {}).get('aucune_notice'):
            if verbose:
                print("🛑 [Superviseur] L'ANSM ne connaît pas ce nom — inutile "
                      'de relancer la collecte.')
            break

    if final is None:
        # « Rejete » et « interrompu » ne disent pas la meme chose. Le
        # premier est un jugement sur les donnees, le second dit qu'on n'a
        # pas pu les obtenir. Les confondre ferait conclure a un medicament
        # inexploitable la ou le quota etait simplement atteint — et ce
        # verdict, une fois consigne dans `agent_reports`, se relit ensuite
        # comme un fait.
        statut = _motif_echec(data, attempts)
        result = {
            'task': task,
            'status': statut,
            'attempts': attempts,
            'written': False,
        }
        _write_report(task, {'status': statut, 'attempts': attempts})
        if verbose:
            print('%s [Superviseur] %s' % (MOTIF_ICONE.get(statut, '❌'),
                                           MOTIF_PHRASE.get(statut,
                                               'Échec après %d tentatives — rien écrit en base.'
                                               % max_attempts)))
        return result

    data = final['data']
    data['validation'] = {
        'score': final['verdict']['score'],
        'issues': final['verdict']['issues'],
        'valid': True,
        'attempts': attempts,
        'validated_at': time.strftime('%Y-%m-%d %H:%M:%S'),
    }

    saved = save_result(task, data)

    _write_report(task, {
        'status': 'written',
        'score': final['verdict']['score'],
        'attempts': attempts,
        'document_id': saved.get('document_id'),
    })

    if verbose:
        print(f'\n💾 [Superviseur] Document écrit sous l\'ID : {saved.get("document_id")}')

    return {
        'task': task,
        'status': 'written',
        'document_id': saved.get('document_id'),
        'score': final['verdict']['score'],
        'attempts': attempts,
        'written': saved.get('saved', False),
    }


def run_batch(medicines, use_llm: bool = True, verbose: bool = True) -> list:
    results = []
    for task in medicines:
        task = task.strip()
        if not task:
            continue
        results.append(process_medicine(task, use_llm=use_llm, verbose=verbose))
        time.sleep(1)
    return results
