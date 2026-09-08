"""Refait la capture que `verif_affichage.js` éprouve.

Pourquoi une capture figée
--------------------------
`verif_affichage.js` fait tourner les fonctions d'affichage du gabarit sur une
réponse réelle de `/api/prescription/analyze`. Rejouer la route à chaque
exécution demanderait MongoDB, Qdrant, Neo4j et un appel au modèle : le banc
ne tournerait presque jamais. La réponse est donc capturée une fois et rangée
dans `donnees/reponse_analyse.json`.

À rejouer quand la forme de la réponse change — un champ ajouté, un champ
renommé — pour que le banc éprouve la réponse d'aujourd'hui et non celle d'hier.

Le cas est celui du rapport (§ 1) : femme de 68 ans, insuffisance rénale
légère, sous warfarine. C'est lui qui a révélé la plupart des défauts corrigés,
et il déclenche à la fois la contrainte rénale et le contrôle d'interactions.

Le tableau présenté est une lombalgie, et non plus la pneumonie d'origine.
Depuis que le diagnostic pilote la sélection, une pneumonie n'appelle plus
d'anti-inflammatoire : le vivier ne contenait donc plus rien à écarter, et la
capture ne montrait plus la section des écartés. La lombalgie remet les deux
forces en tension — le diagnostic réclame l'AINS, l'insuffisance rénale le
refuse — ce que le banc d'affichage a précisément pour tâche de rendre.

Emploi
------
    python scripts/capturer_reponse.py

MongoDB, Qdrant et Neo4j doivent tourner.
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
DESTINATION = Path(__file__).resolve().parent / 'donnees' / 'reponse_analyse.json'

sys.path.insert(0, str(RACINE))

CAS = {
    'nom': 'Essai',
    'prenom': 'Cas',
    'age': 68,
    'symptomes': "Lombalgie basse depuis 6 jours après un port de charge, "
                 "douleur mécanique calmée au repos, raideur matinale, "
                 "pas de fièvre ni de trouble sphinctérien.",
    'antecedents': "Hypertension artérielle, diabète de type 2, "
                   "insuffisance rénale légère",
    'medicaments_actuels': "Ramipril 10 mg, Metformine 850 mg, Warfarine 5 mg",
    'language': 'fr',
}


#: Le même patient, vu par l'autre écran. La prescription par diagnostic part
#: d'un diagnostic déjà posé là où l'assistant part des symptômes, mais les
#: deux rendent la même forme de réponse et l'affichent avec le même code.
DESTINATION_DIAGNOSTIC = (Path(__file__).resolve().parent / 'donnees'
                          / 'reponse_diagnostic.json')

CAS_DIAGNOSTIC = {
    'diagnostic': "Pneumonie communautaire du lobe inférieur droit, "
                  "forme non sévère.",
    'patient_name': 'Cas Essai',
    'age': 68, 'taille': 162, 'poids': 71, 'sexe': 'F',
    'antecedents': CAS['antecedents'],
    # Séparés par des points, comme le médecin les écrit. C'est la saisie qui
    # n'était pas découpée du tout avant `decouper_traitements`.
    'medicaments_actuels': "Ramipril 10 mg. Metformine 850 mg. Warfarine 5 mg.",
    'lang': 'fr',
}


def _ecrire(destination: Path, data: dict) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with io.open(destination, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print("Capture écrite : %s" % destination.name)
    print("  %d médicament(s) proposé(s), %d écarté(s), %d interaction(s)"
          % (len(data.get('medications') or []),
             len(data.get('medicaments_ecartes') or []),
             len(data.get('interactions') or [])))
    print("  contraintes_etat = %s, interactions_etat = %s"
          % (data.get('contraintes_etat'), data.get('interactions_etat')))


def main() -> int:
    from app import app  # importé ici : il charge les modèles et les bases

    with app.test_client() as client:
        reponse = client.post('/api/prescription/analyze', json=CAS)
        if reponse.status_code != 200:
            print("L'assistant a répondu %d" % reponse.status_code)
            return 1
        data = reponse.get_json()
        if not data or not data.get('success'):
            print("L'assistant a répondu sans succès : %s"
                  % json.dumps(data, ensure_ascii=False)[:400])
            return 1
        _ecrire(DESTINATION, data)

        reponse = client.post('/api/diagnostic-prescription/analyze',
                              json=CAS_DIAGNOSTIC)
        if reponse.status_code != 200:
            print("La prescription par diagnostic a répondu %d"
                  % reponse.status_code)
            return 1
        diagnostic = reponse.get_json()
        if not diagnostic or diagnostic.get('error'):
            print("La prescription par diagnostic a échoué : %s"
                  % json.dumps(diagnostic, ensure_ascii=False)[:400])
            return 1
        _ecrire(DESTINATION_DIAGNOSTIC, diagnostic)

    return 0


if __name__ == '__main__':
    sys.exit(main())
