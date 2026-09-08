"""
Enrichit les relations INTERACTS_WITH dans Neo4j avec mechanism et recommendation
basés sur l'effet et la sévérité.
"""
from neo4j import GraphDatabase
import os
from dotenv import load_dotenv
load_dotenv()

NEO4J_URI = os.getenv('NEO4J_URI', 'neo4j://127.0.0.1:7687')
NEO4J_USER = os.getenv('NEO4J_USER', 'neo4j')
NEO4J_PASSWORD = os.getenv('NEO4J_PASSWORD', '12345678')

driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))

MECHANISM_MAP = {
    'hémorragique': 'Interference avec la coagulation et la fonction plaquettaire. Synergie anticoagulante/antiplaquettaire.',
    'hémorragie': 'Interference avec la coagulation et la fonction plaquettaire. Synergie anticoagulante/antiplaquettaire.',
    'risque hémorragique': 'Interference avec la coagulation et la fonction plaquettaire. Synergie anticoagulante/antiplaquettaire.',
    'toxicité du méthotrexate': 'Diminution de la clairance rénale du méthotrexate par compétition au niveau de la sécrétion tubulaire.',
    'toxicité du lithium': 'Diminution de l\'excrétion rénale du lithium. Réabsorption tubulaire accrue du sodium et du lithium.',
    'toxicité de la colchicine': 'Inhibition du CYP3A4 et de la glycoproteine P, augmentant les concentrations de colchicine.',
    'syndrome sérotoninergique': 'Excès de sérotonine synaptique par double mécanisme : inhibition recapture + libération.',
    'dépression respiratoire': 'Synergie depressive sur les centres respiratoires du SNC. Potentialisation des effets opioïdes et benzodiazépiniques.',
    'dépression snc': 'Synergie depressive sur le système nerveux central. Potentialisation des effets sédatifs.',
    'hyperkaliémie': 'Double blocage du système rénine-angiotensine-aldostérone. Diminution de l\'excrétion rénale du potassium.',
    'rhabdomyolyse': 'Inhibition du métabolisme hépatique des statines via le CYP3A4. Augmentation des concentrations plasmatiques.',
    'toxicité digitalique': 'Diminution de la clairance rénale de la digoxine. Hypokaliémie favorisant la toxicité.',
    'toxicité hématologique': 'Synergie de myélosuppression. Inhibition de la replication cellulaire médullaire.',
    'antalgique (safe)': 'Synergie antalgique sans interaction pharmacocinétique majeure. Mécanismes d\'action complémentaires.',
    'additive antalgique': 'Synergie antalgique sans interaction pharmacocinétique majeure. Mécanismes d\'action complémentaires.',
    'absorption optimisée': 'Synergie métabolique favorable. Amélioration de la biodisponibilité.',
    'absorption du fer augmentée': 'Augmentation de l\'absorption intestinale du fer par réduction en fer ferreux.',
    'diminution absorption': 'Compétition au niveau de l\'absorption intestinale. Formation de complexes insolubles.',
    'réduction efficacité antihypertensive': 'Inhibition des prostaglandines rénales vasodilatatrices. Rétention hydrosodée.',
    'réduction efficacité diurétique': 'Inhibition de la synthèse des prostaglandines rénales. Rétention hydrosodée.',
    'réduction efficacité contraceptive': 'Induction du CYP3A4 hépatique. Accélération du métabolisme des estrogènes.',
    'hépatotoxicité': 'Induction du CYP2E1 et déplétion du glutathion hépatique. Formation de métabolites toxiques.',
    'bradycardie': 'Synergie dépressive sur la conduction auriculo-ventriculaire et la fréquence cardiaque.',
    'hypotension': 'Synergie vasodilatatrice périphérique. Blocage des mécanismes compensateurs adrénergiques.',
    'masquage hypoglycémie': 'Blocage des récepteurs beta-adrénergiques masquant les signes adrénergiques d\'hypoglycémie.',
    'risque ulcéreux': 'Synergie ulcérogène digestive. Inhibition des prostaglandines protectrices + effet anti-inflammatoire.',
    'antagonisme folates': 'Antagonisme du métabolisme des folates. Inhibition de la dihydrofolate réductase.',
    'sédation excessive': 'Synergie depressive sur le système nerveux central. Potentialisation des effets GABAergiques.',
    'risque toxidermie': 'Interaction métabolique au niveau hépatique. Accumulation de métabolites reactifs.',
    'encéphalopathie hyperammoniémique': 'Inhibition de l\'uréogenèse hépatique. Augmentation de l\'ammoniémie.',
    'insuffisance rénale aiguë': 'Réduction du débit sanguin rénal par inhibition des prostaglandines. Hypoperfusion glomerulaire.',
    'suraugmentation inr': 'Réduction de la flore intestinale productrice de vitamine K. Interference avec le métabolisme de la warfarine.',
    'toxicité statine': 'Inhibition du CYP3A4 ou altération de la glucuronidation. Augmentation des concentrations plasmatiques.',
    'hypothyroïdie': 'Interference avec la fonction thyroïdienne. Inhibition de la peroxydase thyroïdienne.',
    'variation inr': 'Induction ou inhibition du métabolisme hépatique de la warfarine via les cytochromes P450.',
}

RECOMMENDATION_MAP = {
    'high': 'Éviter l\'association sauf si bénéfice attendu > risque. Surveillance clinique et biologique stricte. Envisager alternative thérapeutique.',
    'moderate': 'Surveillance clinique et biologique rapprochée. Adaptation posologique possible. Information du patient sur les signes d\'alerte.',
    'low': 'Aucune précaution particulière. Association possible. Surveillance clinique de routine.',
}

RECOMMENDATION_SPECIFIC = {
    'hémorragique': 'Éviter association. Surveillance INR, TP, TCA et signes hémorragiques (hématomes, gingivorragies, méléna).',
    'hémorragie': 'Éviter association. Surveillance INR, TP, TCA et signes hémorragiques.',
    'toxicité du méthotrexate': 'Éviter association. Surveillance hématologique (NFS) et hépatique stricte. Si indispensable, réduire dose méthotrexate.',
    'toxicité du lithium': 'Surveillance lithémie à J3, J7, puis régulière. Réduction dose lithium si nécessaire. Hydratation adequate.',
    'syndrome sérotoninergique': 'Intervalle de washout de 14 jours minimum. Surveillance clinique : agitation, hyperthermie, rigidité, myoclonies.',
    'dépression respiratoire': 'Éviter association. Si indispensable, réduire doses et surveiller SaO2, fréquence respiratoire. Antidote : naloxone.',
    'dépression snc': 'Éviter association. Surveillance vigilance, éviter conduite automobile. Réduire doses si association nécessaire.',
    'hyperkaliémie': 'Surveillance ionogramme sanguin (kaliémie). Éviter suppléments potassiques. ECG si hyperkaliémie > 5.5 mmol/L.',
    'rhabdomyolyse': 'Éviter association. Suspendre statine pendant traitement. Si indispensable, choisir pravastatine ou rosuvastatine.',
    'toxicité digitalique': 'Surveillance digoxinémie, kaliémie, ECG. Réduction dose digoxine de 30-50%.',
    'additive antalgique': 'Association possible et courante. Respecter doses maximales : paracétamol 4g/j, ibuprofène 1200mg/j.',
    'antalgique (safe)': 'Association possible et courante. Respecter les doses maximales recommandées.',
    'réduction efficacité antihypertensive': 'Surveillance PA. Augmentation possible dose antihypertenseur. Préférer paracétamol comme antalgique.',
    'réduction efficacité diurétique': 'Surveillance PA, diurèse, poids. Augmentation posologie diurétique si nécessaire.',
    'hépatotoxicité': 'Limiter paracétamol à 3g/j chez l alcoolique chronique. Surveillance bilan hépatique (transaminases).',
    'bradycardie': 'Surveillance ECG et fréquence cardiaque. Réduction doses si FC < 50/min. Éviter association à fortes doses.',
    'hypotension': 'Surveillance PA. Ajuster posologies. Prévenir le patient en cas de vertiges orthostatiques.',
    'masquage hypoglycémie': 'Surveillance automesure glycémique. Préférer bêta-bloquant cardiosélectif si nécessaire.',
    'risque ulcéreux': 'Protection gastrique par IPP si association. Surveillance signes digestifs (épigastralgies, méléna).',
    'suraugmentation inr': 'Surveillance INR pendant antibiothérapie et 1 semaine après. Ajustement dose AVK si nécessaire.',
    'toxicité statine': 'Preferer pravastatine ou rosuvastatine (peu métabolisées). Surveillance CPK et NFS.',
    'sédation excessive': 'Réduire doses des deux traitements. Éviter conduite et machines dangereuses.',
    'insuffisance rénale aiguë': 'Surveillance créatininémie et diurèse. Hydratation adequate. Éviter association chez insuffisant rénal.',
}

with driver.session() as s:
    # Récupérer toutes les relations avec leur contexte
    result = s.run("""
        MATCH (m1:Medicine)-[r:INTERACTS_WITH]-(m2:Medicine)
        WHERE (r.mechanism IS NULL OR r.mechanism = '') 
           OR (r.recommendation IS NULL OR r.recommendation = '')
        RETURN m1.url AS url1, m2.url AS url2, r.effect AS effect, r.severity AS severity
    """)

    batch = []
    count = 0
    for rec in result:
        effect = rec['effect'] or ''
        severity = rec['severity'] or 'moderate'
        eff_lower = effect.lower()

        # Determine mechanism
        mechanism = None
        for key, val in MECHANISM_MAP.items():
            if key in eff_lower:
                mechanism = val
                break
        if not mechanism:
            if severity == 'high':
                mechanism = 'Interaction pharmacologique documentée à risque élevé. Mécanisme spécifique non renseigné dans la base.'
            elif severity == 'moderate':
                mechanism = 'Interaction pharmacologique cliniquement significative. Surveillance recommandée.'
            else:
                mechanism = 'Interaction pharmacologique mineure ou additive sans risque significatif.'

        # Determine recommendation
        recommendation = None
        for key, val in RECOMMENDATION_SPECIFIC.items():
            if key in eff_lower:
                recommendation = val
                break
        if not recommendation:
            recommendation = RECOMMENDATION_MAP.get(severity, RECOMMENDATION_MAP['moderate'])

        batch.append({
            'url1': rec['url1'],
            'url2': rec['url2'],
            'mechanism': mechanism,
            'recommendation': recommendation
        })

        if len(batch) >= 200:
            s.run("""
                UNWIND $batch AS row
                MATCH (m1:Medicine {url: row.url1})
                MATCH (m2:Medicine {url: row.url2})
                MATCH (m1)-[r:INTERACTS_WITH]-(m2)
                SET r.mechanism = row.mechanism,
                    r.recommendation = row.recommendation
            """, batch=batch)
            count += len(batch)
            print(f"  Updated: {count}", end='\r')
            batch = []

    if batch:
        s.run("""
            UNWIND $batch AS row
            MATCH (m1:Medicine {url: row.url1})
            MATCH (m2:Medicine {url: row.url2})
            MATCH (m1)-[r:INTERACTS_WITH]-(m2)
            SET r.mechanism = row.mechanism,
                r.recommendation = row.recommendation
        """, batch=batch)
        count += len(batch)

    print(f"\nUpdated {count} relationships with mechanism + recommendation")

    # Verify
    r = s.run("""
        MATCH ()-[r:INTERACTS_WITH]-()
        RETURN
            count(r) AS total,
            sum(CASE WHEN r.mechanism IS NULL OR r.mechanism = '' THEN 1 ELSE 0 END) AS empty_mechanism,
            sum(CASE WHEN r.recommendation IS NULL OR r.recommendation = '' THEN 1 ELSE 0 END) AS empty_recommendation
    """)
    for rec in r:
        print(f"Total: {rec['total']}")
        print(f"Still empty mechanism: {rec['empty_mechanism']}")
        print(f"Still empty recommendation: {rec['empty_recommendation']}")

driver.close()
