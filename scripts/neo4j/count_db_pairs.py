with open('C:/Users/coren/MedicSearch/scripts/neo4j/build_full_knowledge_graph.py', 'r', encoding='utf-8') as f:
    content = f.read()

has_mechanism = content.count("'mechanism':")
has_recommendation = content.count("'recommendation':")
total_pairs = content.count("{'severity':")
print(f"Total pairs in INTERACTION_DB: ~{total_pairs}")
print(f"Pairs with mechanism: {has_mechanism}")
print(f"Pairs with recommendation: {has_recommendation}")
