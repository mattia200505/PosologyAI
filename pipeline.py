"""
pipeline.py — Point d'entrée CLI de l'écosystème d'agents MedicSearch.

Usage :
    python pipeline.py "DOLIPRANE 500mg"
    python pipeline.py --no-llm "DOLIPRANE 500mg"
    python pipeline.py --batch medicaments.txt
"""

import argparse
import json

from agent_superviseur import process_medicine, run_batch


def main():
    parser = argparse.ArgumentParser(description='Pipeline d\'agents MedicSearch (collecte → vérification → écriture)')
    parser.add_argument('medication', nargs='?', help='Nom du médicament à traiter')
    parser.add_argument('--batch', help='Fichier texte contenant un médicament par ligne')
    parser.add_argument('--no-llm', action='store_true', help='Désactiver la vérification LLM (règles déterministes uniquement)')
    parser.add_argument('--model', default=None, help='Modèle Mistral (défaut: mistral-small-2503)')
    args = parser.parse_args()

    use_llm = not args.no_llm

    if args.batch:
        with open(args.batch, encoding='utf-8') as f:
            medicines = [line for line in f.read().splitlines() if line.strip()]
        print(f'📋 Batch : {len(medicines)} médicaments\n')
        results = run_batch(medicines, use_llm=use_llm)
        summary_counts = {}
        for r in results:
            summary_counts[r['status']] = summary_counts.get(r['status'], 0) + 1
        print('\n━━━ Rapport de batch ━━━')
        print(json.dumps(summary_counts, ensure_ascii=False, indent=2))
        return

    if not args.medication:
        parser.print_help()
        return

    process_medicine(args.medication, use_llm=use_llm)


if __name__ == '__main__':
    main()
