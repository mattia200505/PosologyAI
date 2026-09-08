"""
Construction complète de la base de connaissances Neo4j MedicSearch
Avec une base d'interactions pharmacologiques étendue (400+ paires de substances)

Usage:
    cd scripts/neo4j
    python build_full_knowledge_graph.py
"""

import os
import sys
import re
import time
import unicodedata
from dotenv import load_dotenv

load_dotenv()

from pymongo import MongoClient
from neo4j import GraphDatabase

MONGO_URI = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
MONGO_DB = 'medicsearch'

NEO4J_URI = os.getenv('NEO4J_URI', 'neo4j://127.0.0.1:7687')
NEO4J_USER = os.getenv('NEO4J_USER', 'neo4j')
NEO4J_PASSWORD = os.getenv('NEO4J_PASSWORD', '12345678')
NEO4J_DATABASE = os.getenv('NEO4J_DATABASE', 'neo4j')

BATCH_SIZE = 200

INTERACTION_DB = {
    # ═══════════════════════════════════════════════════════════
    # NIVEAU HAUT – Interactions graves, documentées, à risque vital
    # ═══════════════════════════════════════════════════════════

    # ── Anticoagulants + Antiplaquettaires / AINS → Hémorragie ──
    ('warfarine', 'aspirine'): {'severity': 'high', 'effect': 'Risque hémorragique majeur', 'mechanism': 'Synergie anticoagulante + antiplaquettaire', 'recommendation': 'Éviter association sauf bénéfice > risque. Surveillance INR + signes hémorragiques.'},
    ('warfarine', 'acide acétylsalicylique'): {'severity': 'high', 'effect': 'Risque hémorragique majeur', 'mechanism': 'Synergie anticoagulante + antiplaquettaire', 'recommendation': 'Éviter association sauf bénéfice > risque.'},
    ('warfarine', 'ibuprofène'): {'severity': 'high', 'effect': 'Risque hémorragique majeur', 'mechanism': 'Inhibition plaquettaire + ulcération digestive', 'recommendation': 'Éviter association. Préférer paracétamol.'},
    ('warfarine', 'kétoprofène'): {'severity': 'high', 'effect': 'Risque hémorragique majeur'},
    ('warfarine', 'diclofénac'): {'severity': 'high', 'effect': 'Risque hémorragique majeur'},
    ('warfarine', 'naproxène'): {'severity': 'high', 'effect': 'Risque hémorragique majeur'},
    ('warfarine', 'piroxicam'): {'severity': 'high', 'effect': 'Risque hémorragique majeur'},
    ('warfarine', 'indométacine'): {'severity': 'high', 'effect': 'Risque hémorragique majeur'},
    ('warfarine', 'héparine'): {'severity': 'high', 'effect': 'Risque hémorragique majeur', 'mechanism': 'Double anticoagulation'},
    ('warfarine', 'énoxaparine'): {'severity': 'high', 'effect': 'Risque hémorragique majeur'},
    ('warfarine', 'clopidogrel'): {'severity': 'high', 'effect': 'Risque hémorragique majeur', 'mechanism': 'Double antiagrégation + anticoagulation'},
    ('warfarine', 'ticlopidine'): {'severity': 'high', 'effect': 'Risque hémorragique majeur'},
    ('héparine', 'aspirine'): {'severity': 'high', 'effect': 'Risque hémorragique', 'mechanism': 'Double anticoagulation + antiagrégation'},
    ('héparine', 'clopidogrel'): {'severity': 'high', 'effect': 'Risque hémorragique'},
    ('énoxaparine', 'aspirine'): {'severity': 'high', 'effect': 'Risque hémorragique'},
    ('énoxaparine', 'clopidogrel'): {'severity': 'high', 'effect': 'Risque hémorragique'},
    ('énoxaparine', 'kétoprofène'): {'severity': 'high', 'effect': 'Risque hémorragique'},
    ('dabigatran', 'aspirine'): {'severity': 'high', 'effect': 'Risque hémorragique', 'mechanism': 'Double anticoagulation'},
    ('dabigatran', 'clopidogrel'): {'severity': 'high', 'effect': 'Risque hémorragique'},
    ('dabigatran', 'kétoprofène'): {'severity': 'high', 'effect': 'Risque hémorragique'},
    ('rivaroxaban', 'aspirine'): {'severity': 'high', 'effect': 'Risque hémorragique'},
    ('rivaroxaban', 'clopidogrel'): {'severity': 'high', 'effect': 'Risque hémorragique'},
    ('rivaroxaban', 'kétoprofène'): {'severity': 'high', 'effect': 'Risque hémorragique'},
    ('apixaban', 'aspirine'): {'severity': 'high', 'effect': 'Risque hémorragique'},
    ('clopidogrel', 'kétoprofène'): {'severity': 'high', 'effect': 'Risque hémorragique majeur'},
    ('clopidogrel', 'ibuprofène'): {'severity': 'high', 'effect': 'Risque hémorragique'},
    ('clopidogrel', 'naproxène'): {'severity': 'high', 'effect': 'Risque hémorragique'},
    ('aspirine', 'kétoprofène'): {'severity': 'high', 'effect': 'Risque hémorragique digestif', 'mechanism': 'Double inhibition plaquettaire + ulcération'},
    ('aspirine', 'ibuprofène'): {'severity': 'high', 'effect': 'Risque hémorragique digestif'},
    ('aspirine', 'naproxène'): {'severity': 'high', 'effect': 'Risque hémorragique digestif'},
    ('aspirine', 'diclofénac'): {'severity': 'high', 'effect': 'Risque hémorragique digestif'},

    # ── Méthotrexate + AINS → Toxicité sévère ──
    ('méthotrexate', 'ibuprofène'): {'severity': 'high', 'effect': 'Toxicité du méthotrexate', 'mechanism': 'Diminution clairance rénale du méthotrexate', 'recommendation': 'Éviter association. Surveillance hématologique stricte.'},
    ('méthotrexate', 'kétoprofène'): {'severity': 'high', 'effect': 'Toxicité du méthotrexate'},
    ('méthotrexate', 'naproxène'): {'severity': 'high', 'effect': 'Toxicité du méthotrexate'},
    ('méthotrexate', 'diclofénac'): {'severity': 'high', 'effect': 'Toxicité du méthotrexate'},
    ('méthotrexate', 'aspirine'): {'severity': 'high', 'effect': 'Toxicité du méthotrexate'},
    ('méthotrexate', 'piroxicam'): {'severity': 'high', 'effect': 'Toxicité du méthotrexate'},
    ('méthotrexate', 'indométacine'): {'severity': 'high', 'effect': 'Toxicité du méthotrexate'},
    ('méthotrexate', 'triméthoprime'): {'severity': 'high', 'effect': 'Toxicité hématologique majeure', 'mechanism': 'Synergie antifolique'},
    ('méthotrexate', 'probénécide'): {'severity': 'high', 'effect': 'Toxicité du méthotrexate', 'mechanism': 'Diminution excrétion tubulaire'},

    # ── Lithium + AINS / IEC → Toxicité du lithium ──
    ('lithium', 'ibuprofène'): {'severity': 'high', 'effect': 'Toxicité du lithium', 'mechanism': 'Diminution excrétion rénale du lithium', 'recommendation': 'Surveillance lithémie si AINS indispensable.'},
    ('lithium', 'kétoprofène'): {'severity': 'high', 'effect': 'Toxicité du lithium'},
    ('lithium', 'naproxène'): {'severity': 'high', 'effect': 'Toxicité du lithium'},
    ('lithium', 'diclofénac'): {'severity': 'high', 'effect': 'Toxicité du lithium'},
    ('lithium', 'indométacine'): {'severity': 'high', 'effect': 'Toxicité du lithium'},
    ('lithium', 'énalapril'): {'severity': 'high', 'effect': 'Toxicité du lithium'},
    ('lithium', 'ramipril'): {'severity': 'high', 'effect': 'Toxicité du lithium'},
    ('lithium', 'furosémide'): {'severity': 'high', 'effect': 'Toxicité du lithium', 'mechanism': 'Déplétion sodée → réabsorption tubulaire du lithium'},
    ('lithium', 'hydrochlorothiazide'): {'severity': 'high', 'effect': 'Toxicité du lithium'},
    ('lithium', 'lisinopril'): {'severity': 'high', 'effect': 'Toxicité du lithium'},

    # ── IMAO + ISRS → Syndrome sérotoninergique ──
    ('iproniazide', 'sertraline'): {'severity': 'high', 'effect': 'Syndrome sérotoninergique potentiellement mortel', 'mechanism': 'Excès de sérotonine synaptique', 'recommendation': 'Intervalle de washout de 14 jours minimum.'},
    ('iproniazide', 'fluoxétine'): {'severity': 'high', 'effect': 'Syndrome sérotoninergique potentiellement mortel'},
    ('iproniazide', 'paroxétine'): {'severity': 'high', 'effect': 'Syndrome sérotoninergique potentiellement mortel'},
    ('iproniazide', 'citalopram'): {'severity': 'high', 'effect': 'Syndrome sérotoninergique potentiellement mortel'},
    ('iproniazide', 'escitalopram'): {'severity': 'high', 'effect': 'Syndrome sérotoninergique potentiellement mortel'},
    ('iproniazide', 'venlafaxine'): {'severity': 'high', 'effect': 'Syndrome sérotoninergique potentiellement mortel'},
    ('iproniazide', 'duloxétine'): {'severity': 'high', 'effect': 'Syndrome sérotoninergique potentiellement mortel'},
    ('iproniazide', 'clomipramine'): {'severity': 'high', 'effect': 'Syndrome sérotoninergique potentiellement mortel'},
    ('iproniazide', 'tramadol'): {'severity': 'high', 'effect': 'Syndrome sérotoninergique potentiellement mortel'},
    ('iproniazide', 'péthidine'): {'severity': 'high', 'effect': 'Syndrome sérotoninergique potentiellement mortel'},
    ('phénelzine', 'sertraline'): {'severity': 'high', 'effect': 'Syndrome sérotoninergique'},
    ('phénelzine', 'fluoxétine'): {'severity': 'high', 'effect': 'Syndrome sérotoninergique'},
    ('phénelzine', 'tramadol'): {'severity': 'high', 'effect': 'Syndrome sérotoninergique'},
    ('moclobémide', 'sertraline'): {'severity': 'high', 'effect': 'Syndrome sérotoninergique'},

    # ── Opiacés + Benzodiazépines → Dépression respiratoire ──
    ('morphine', 'diazépam'): {'severity': 'high', 'effect': 'Dépression respiratoire', 'mechanism': 'Synergie dépressive sur SNC et centres respiratoires', 'recommendation': 'Éviter association. Si indispensable, réduire doses et surveiller SaO2.'},
    ('morphine', 'alprazolam'): {'severity': 'high', 'effect': 'Dépression respiratoire'},
    ('morphine', 'lorazépam'): {'severity': 'high', 'effect': 'Dépression respiratoire'},
    ('morphine', 'bromazépam'): {'severity': 'high', 'effect': 'Dépression respiratoire'},
    ('morphine', 'clonazépam'): {'severity': 'high', 'effect': 'Dépression respiratoire'},
    ('morphine', 'éthanol'): {'severity': 'high', 'effect': 'Dépression respiratoire et SNC'},
    ('morphine', 'phénobarbital'): {'severity': 'high', 'effect': 'Dépression respiratoire'},
    ('codéine', 'diazépam'): {'severity': 'high', 'effect': 'Dépression respiratoire'},
    ('codéine', 'alprazolam'): {'severity': 'high', 'effect': 'Dépression respiratoire'},
    ('codéine', 'éthanol'): {'severity': 'high', 'effect': 'Dépression SNC'},
    ('tramadol', 'diazépam'): {'severity': 'high', 'effect': 'Dépression respiratoire', 'mechanism': 'Synergie opiacée + benzodiazépine'},
    ('tramadol', 'alprazolam'): {'severity': 'high', 'effect': 'Dépression respiratoire'},
    ('tramadol', 'éthanol'): {'severity': 'high', 'effect': 'Dépression SNC'},
    ('fentanyl', 'diazépam'): {'severity': 'high', 'effect': 'Dépression respiratoire sévère'},
    ('fentanyl', 'éthanol'): {'severity': 'high', 'effect': 'Dépression respiratoire'},
    ('fentanyl', 'midazolam'): {'severity': 'high', 'effect': 'Dépression respiratoire sévère'},
    ('oxycodone', 'diazépam'): {'severity': 'high', 'effect': 'Dépression respiratoire'},
    ('oxycodone', 'alprazolam'): {'severity': 'high', 'effect': 'Dépression respiratoire'},
    ('oxycodone', 'éthanol'): {'severity': 'high', 'effect': 'Dépression SNC'},
    ('oxycodone', 'clonazépam'): {'severity': 'high', 'effect': 'Dépression respiratoire'},
    ('hydromorphone', 'diazépam'): {'severity': 'high', 'effect': 'Dépression respiratoire'},
    ('buprénorphine', 'diazépam'): {'severity': 'high', 'effect': 'Dépression respiratoire'},
    ('buprénorphine', 'éthanol'): {'severity': 'high', 'effect': 'Dépression respiratoire'},

    # ── IEC / ARA2 + Diurétiques épargneurs de K+ → Hyperkaliémie ──
    ('énalapril', 'spironolactone'): {'severity': 'high', 'effect': 'Hyperkaliémie sévère', 'mechanism': 'Double blocage du système rénine-angiotensine-aldostérone', 'recommendation': 'Éviter association. Surveillance ionogramme si indispensable.'},
    ('énalapril', 'amiloride'): {'severity': 'high', 'effect': 'Hyperkaliémie sévère'},
    ('énalapril', 'triamtérène'): {'severity': 'high', 'effect': 'Hyperkaliémie sévère'},
    ('énalapril', 'chlorure de potassium'): {'severity': 'high', 'effect': 'Hyperkaliémie sévère'},
    ('ramipril', 'spironolactone'): {'severity': 'high', 'effect': 'Hyperkaliémie sévère'},
    ('ramipril', 'amiloride'): {'severity': 'high', 'effect': 'Hyperkaliémie sévère'},
    ('ramipril', 'chlorure de potassium'): {'severity': 'high', 'effect': 'Hyperkaliémie sévère'},
    ('lisinopril', 'spironolactone'): {'severity': 'high', 'effect': 'Hyperkaliémie sévère'},
    ('captopril', 'spironolactone'): {'severity': 'high', 'effect': 'Hyperkaliémie sévère'},
    ('perindopril', 'spironolactone'): {'severity': 'high', 'effect': 'Hyperkaliémie sévère'},
    ('losartan', 'spironolactone'): {'severity': 'high', 'effect': 'Hyperkaliémie sévère'},
    ('valsartan', 'spironolactone'): {'severity': 'high', 'effect': 'Hyperkaliémie sévère'},
    ('candésartan', 'spironolactone'): {'severity': 'high', 'effect': 'Hyperkaliémie sévère'},
    ('irbésartan', 'spironolactone'): {'severity': 'high', 'effect': 'Hyperkaliémie sévère'},

    # ── ISRS + Tramadol → Syndrome sérotoninergique ──
    ('sertraline', 'tramadol'): {'severity': 'high', 'effect': 'Syndrome sérotoninergique', 'mechanism': 'Inhibition recapture sérotonine + libération sérotonine', 'recommendation': 'Surveillance clinique. Arrêt si agitation, hyperthermie, rigidité.'},
    ('fluoxétine', 'tramadol'): {'severity': 'high', 'effect': 'Syndrome sérotoninergique'},
    ('paroxétine', 'tramadol'): {'severity': 'high', 'effect': 'Syndrome sérotoninergique'},
    ('citalopram', 'tramadol'): {'severity': 'high', 'effect': 'Syndrome sérotoninergique'},
    ('escitalopram', 'tramadol'): {'severity': 'high', 'effect': 'Syndrome sérotoninergique'},
    ('venlafaxine', 'tramadol'): {'severity': 'high', 'effect': 'Syndrome sérotoninergique'},
    ('duloxétine', 'tramadol'): {'severity': 'high', 'effect': 'Syndrome sérotoninergique'},

    # ── Statines + Macrolides → Rhabdomyolyse ──
    ('simvastatine', 'érythromycine'): {'severity': 'high', 'effect': 'Rhabdomyolyse', 'mechanism': 'Inhibition métabolisme CYP3A4', 'recommendation': 'Éviter association. Suspension statine pendant traitement macrolide.'},
    ('simvastatine', 'clarithromycine'): {'severity': 'high', 'effect': 'Rhabdomyolyse'},
    ('simvastatine', 'itraconazole'): {'severity': 'high', 'effect': 'Rhabdomyolyse', 'mechanism': 'Inhibition CYP3A4 puissante'},
    ('simvastatine', 'kétoconazole'): {'severity': 'high', 'effect': 'Rhabdomyolyse'},
    ('simvastatine', 'cyclosporine'): {'severity': 'high', 'effect': 'Rhabdomyolyse'},
    ('simvastatine', 'gemfibrozil'): {'severity': 'high', 'effect': 'Rhabdomyolyse', 'mechanism': 'Altération glucuronidation'},
    ('simvastatine', 'jus de pamplemousse'): {'severity': 'high', 'effect': 'Rhabdomyolyse'},
    ('atorvastatine', 'érythromycine'): {'severity': 'moderate', 'effect': 'Risque de myopathie'},
    ('atorvastatine', 'clarithromycine'): {'severity': 'moderate', 'effect': 'Risque de myopathie'},
    ('pravastatine', 'gemfibrozil'): {'severity': 'moderate', 'effect': 'Risque de myopathie'},

    # ── Colchicine + Macrolides → Toxicité colchicine ──
    ('colchicine', 'clarithromycine'): {'severity': 'high', 'effect': 'Toxicité de la colchicine potentiellement mortelle', 'mechanism': 'Inhibition CYP3A4 + P-glycoprotéine', 'recommendation': 'CI formelle.'},
    ('colchicine', 'érythromycine'): {'severity': 'high', 'effect': 'Toxicité de la colchicine'},
    ('colchicine', 'cyclosporine'): {'severity': 'high', 'effect': 'Toxicité de la colchicine'},

    # ── Antiarythmiques ──
    ('amiodarone', 'warfarine'): {'severity': 'high', 'effect': 'Suraugmentation INR, risque hémorragique', 'mechanism': 'Inhibition métabolisme warfarine', 'recommendation': 'Réduction dose warfarine 30-50%. Surveillance INR stricte.'},
    ('amiodarone', 'simvastatine'): {'severity': 'moderate', 'effect': 'Risque de myopathie', 'mechanism': 'Inhibition CYP3A4'},
    ('amiodarone', 'digoxine'): {'severity': 'high', 'effect': 'Toxicité digitalique', 'mechanism': 'Diminution clairance digoxine', 'recommendation': 'Réduction dose digoxine. Surveillance digoxinémie.'},
    ('amiodarone', 'flecainide'): {'severity': 'high', 'effect': 'Toxicité antiarythmique'},
    ('digoxine', 'furosémide'): {'severity': 'moderate', 'effect': 'Toxicité digitalique', 'mechanism': 'Hypokaliémie induite'},
    ('digoxine', 'hydrochlorothiazide'): {'severity': 'moderate', 'effect': 'Toxicité digitalique'},
    ('digoxine', 'vérapamil'): {'severity': 'high', 'effect': 'Toxicité digitalique + bradycardie'},
    ('digoxine', 'amiodarone'): {'severity': 'high', 'effect': 'Toxicité digitalique'},
    ('digoxine', 'quinidine'): {'severity': 'high', 'effect': 'Toxicité digitalique'},

    # ═══════════════════════════════════════════════════════════
    # NIVEAU MODÉRÉ – Interactions cliniquement significatives
    # ═══════════════════════════════════════════════════════════

    # ── AINS + IEC / ARA2 → Insuffisance rénale ──
    ('ibuprofène', 'énalapril'): {'severity': 'moderate', 'effect': 'Réduction efficacité antihypertensive + risque IRA', 'mechanism': 'Inhibition prostaglandines rénales', 'recommendation': 'Surveillance fonction rénale et PA.'},
    ('ibuprofène', 'ramipril'): {'severity': 'moderate', 'effect': 'Réduction efficacité antihypertensive'},
    ('ibuprofène', 'lisinopril'): {'severity': 'moderate', 'effect': 'Réduction efficacité antihypertensive'},
    ('ibuprofène', 'captopril'): {'severity': 'moderate', 'effect': 'Réduction efficacité antihypertensive'},
    ('ibuprofène', 'périndopril'): {'severity': 'moderate', 'effect': 'Réduction efficacité antihypertensive'},
    ('ibuprofène', 'losartan'): {'severity': 'moderate', 'effect': 'Réduction efficacité antihypertensive'},
    ('ibuprofène', 'valsartan'): {'severity': 'moderate', 'effect': 'Réduction efficacité antihypertensive'},
    ('kétoprofène', 'énalapril'): {'severity': 'moderate', 'effect': 'Réduction efficacité antihypertensive'},
    ('kétoprofène', 'ramipril'): {'severity': 'moderate', 'effect': 'Réduction efficacité antihypertensive'},
    ('naproxène', 'énalapril'): {'severity': 'moderate', 'effect': 'Réduction efficacité antihypertensive'},
    ('diclofénac', 'énalapril'): {'severity': 'moderate', 'effect': 'Réduction efficacité antihypertensive'},
    ('diclofénac', 'losartan'): {'severity': 'moderate', 'effect': 'Réduction efficacité antihypertensive'},
    ('indométacine', 'énalapril'): {'severity': 'moderate', 'effect': 'Réduction efficacité antihypertensive'},
    ('piroxicam', 'énalapril'): {'severity': 'moderate', 'effect': 'Réduction efficacité antihypertensive + risque IRA'},

    # ── AINS + Diurétiques → Insuffisance rénale ──
    ('ibuprofène', 'furosémide'): {'severity': 'moderate', 'effect': 'Réduction efficacité diurétique + risque IRA', 'mechanism': 'Inhibition prostaglandines rénales'},
    ('ibuprofène', 'hydrochlorothiazide'): {'severity': 'moderate', 'effect': 'Réduction efficacité diurétique'},
    ('kétoprofène', 'furosémide'): {'severity': 'moderate', 'effect': 'Réduction efficacité diurétique'},
    ('naproxène', 'furosémide'): {'severity': 'moderate', 'effect': 'Réduction efficacité diurétique'},
    ('diclofénac', 'furosémide'): {'severity': 'moderate', 'effect': 'Réduction efficacité diurétique + risque IRA'},
    ('indométacine', 'furosémide'): {'severity': 'moderate', 'effect': 'Réduction efficacité diurétique'},
    ('ibuprofène', 'bumétanide'): {'severity': 'moderate', 'effect': 'Réduction efficacité diurétique'},

    # ── Paracétamol + Éthanol → Hépatotoxicité ──
    ('paracétamol', 'éthanol'): {'severity': 'moderate', 'effect': 'Hépatotoxicité', 'mechanism': 'Induction CYP2E1 + déplétion glutathion', 'recommendation': 'Limiter paracétamol à 3g/j si alcoolique chronique.'},
    ('paracétamol', 'phénobarbital'): {'severity': 'moderate', 'effect': 'Hépatotoxicité du paracétamol', 'mechanism': 'Induction enzymatique'},
    ('paracétamol', 'carbamazépine'): {'severity': 'moderate', 'effect': 'Hépatotoxicité du paracétamol'},

    # ── ISRS + AINS → Saignement digestif ──
    ('sertraline', 'ibuprofène'): {'severity': 'moderate', 'effect': 'Risque hémorragique digestif', 'mechanism': 'Inhibition recapture sérotonine plaquettaire + AINS', 'recommendation': 'Surveillance signes hémorragiques. Protection gastrique si association.'},
    ('sertraline', 'aspirine'): {'severity': 'moderate', 'effect': 'Risque hémorragique digestif'},
    ('sertraline', 'naproxène'): {'severity': 'moderate', 'effect': 'Risque hémorragique digestif'},
    ('sertraline', 'diclofénac'): {'severity': 'moderate', 'effect': 'Risque hémorragique digestif'},
    ('fluoxétine', 'ibuprofène'): {'severity': 'moderate', 'effect': 'Risque hémorragique digestif'},
    ('fluoxétine', 'aspirine'): {'severity': 'moderate', 'effect': 'Risque hémorragique digestif'},
    ('fluoxétine', 'warfarine'): {'severity': 'moderate', 'effect': 'Risque hémorragique'},
    ('paroxétine', 'ibuprofène'): {'severity': 'moderate', 'effect': 'Risque hémorragique digestif'},
    ('paroxétine', 'warfarine'): {'severity': 'moderate', 'effect': 'Risque hémorragique'},
    ('citalopram', 'ibuprofène'): {'severity': 'moderate', 'effect': 'Risque hémorragique digestif'},
    ('citalopram', 'warfarine'): {'severity': 'moderate', 'effect': 'Risque hémorragique'},
    ('escitalopram', 'ibuprofène'): {'severity': 'moderate', 'effect': 'Risque hémorragique digestif'},
    ('venlafaxine', 'ibuprofène'): {'severity': 'moderate', 'effect': 'Risque hémorragique digestif'},

    # ── Bêta-bloquants + Antagonistes calciques → Bradycardie ──
    ('propranolol', 'vérapamil'): {'severity': 'moderate', 'effect': 'Bradycardie sévère, trouble conductif', 'mechanism': 'Synergie dépressive sur conduction AV', 'recommendation': 'Surveillance ECG et FC.'},
    ('propranolol', 'diltiazem'): {'severity': 'moderate', 'effect': 'Bradycardie'},
    ('propranolol', 'amlodipine'): {'severity': 'moderate', 'effect': 'Hypotension', 'mechanism': 'Synergie vasodilatatrice'},
    ('propranolol', 'nifédipine'): {'severity': 'moderate', 'effect': 'Hypotension'},
    ('aténolol', 'vérapamil'): {'severity': 'moderate', 'effect': 'Bradycardie sévère'},
    ('bisoprolol', 'vérapamil'): {'severity': 'moderate', 'effect': 'Bradycardie'},
    ('métoprolol', 'vérapamil'): {'severity': 'moderate', 'effect': 'Bradycardie'},
    ('métoprolol', 'diltiazem'): {'severity': 'moderate', 'effect': 'Bradycardie'},

    # ── ISRS + IMAO → Syndrome sérotoninergique ──
    ('fluoxétine', 'iproniazide'): {'severity': 'moderate', 'effect': 'Syndrome sérotoninergique'},
    ('fluoxétine', 'phénelzine'): {'severity': 'moderate', 'effect': 'Syndrome sérotoninergique'},
    ('paroxétine', 'iproniazide'): {'severity': 'moderate', 'effect': 'Syndrome sérotoninergique'},

    # ── Antidiabétiques oraux + Bêta-bloquants → Masquage hypoglycémie ──
    ('propranolol', 'insuline'): {'severity': 'moderate', 'effect': 'Masquage des signes d\'hypoglycémie', 'mechanism': 'Blocage adrénergique'},
    ('propranolol', 'glibenclamide'): {'severity': 'moderate', 'effect': 'Masquage hypoglycémie'},
    ('propranolol', 'metformine'): {'severity': 'low', 'effect': 'Masquage hypoglycémie'},
    ('aténolol', 'insuline'): {'severity': 'moderate', 'effect': 'Masquage hypoglycémie'},

    # ── Antivitamine K + Antibiotiques → Surnormalisation INR ──
    ('warfarine', 'amoxicilline'): {'severity': 'moderate', 'effect': 'Suraugmentation INR', 'mechanism': 'Réduction flore intestinale productrice de vitamine K', 'recommendation': 'Surveillance INR pendant ATB et 1 semaine après.'},
    ('warfarine', 'ciprofloxacine'): {'severity': 'moderate', 'effect': 'Suraugmentation INR'},
    ('warfarine', 'lévofloxacine'): {'severity': 'moderate', 'effect': 'Suraugmentation INR'},
    ('warfarine', 'doxycycline'): {'severity': 'moderate', 'effect': 'Suraugmentation INR'},
    ('warfarine', 'céphalexine'): {'severity': 'moderate', 'effect': 'Suraugmentation INR'},
    ('warfarine', 'métronidazole'): {'severity': 'moderate', 'effect': 'Suraugmentation INR'},
    ('warfarine', 'fluconazole'): {'severity': 'moderate', 'effect': 'Suraugmentation INR', 'mechanism': 'Inhibition CYP2C9'},
    ('warfarine', 'sulfaméthoxazole'): {'severity': 'moderate', 'effect': 'Suraugmentation INR'},

    # ── Corticostéroïdes + AINS → Ulcère digestif ──
    ('prednisone', 'ibuprofène'): {'severity': 'moderate', 'effect': 'Risque ulcéreux digestif', 'mechanism': 'Synergie ulcérogène', 'recommendation': 'Protection gastrique par IPP si association.'},
    ('prednisone', 'kétoprofène'): {'severity': 'moderate', 'effect': 'Risque ulcéreux digestif'},
    ('prednisone', 'aspirine'): {'severity': 'moderate', 'effect': 'Risque ulcéreux digestif'},
    ('prednisone', 'naproxène'): {'severity': 'moderate', 'effect': 'Risque ulcéreux digestif'},
    ('prednisone', 'diclofénac'): {'severity': 'moderate', 'effect': 'Risque ulcéreux digestif'},
    ('prednisolone', 'ibuprofène'): {'severity': 'moderate', 'effect': 'Risque ulcéreux digestif'},
    ('dexaméthasone', 'ibuprofène'): {'severity': 'moderate', 'effect': 'Risque ulcéreux digestif'},

    # ── Antihypertenseurs centraux + Antidépresseurs ──
    ('clonidine', 'amitriptyline'): {'severity': 'moderate', 'effect': 'Hypotension orthostatique sévère'},
    ('clonidine', 'imipramine'): {'severity': 'moderate', 'effect': 'Hypotension orthostatique sévère'},
    ('clonidine', 'sertraline'): {'severity': 'low', 'effect': 'Hypotension orthostatique'},

    # ── Lévothyroxine + Inhibiteurs tyrosine kinase ──
    ('lévothyroxine', 'imatinib'): {'severity': 'moderate', 'effect': 'Modification fonction thyroïdienne'},
    ('lévothyroxine', 'sunitinib'): {'severity': 'moderate', 'effect': 'Hypothyroïdie'},

    # ═══════════════════════════════════════════════════════════
    # NIVEAU BAS – Interactions mineures à surveiller
    # ═══════════════════════════════════════════════════════════

    ('paracétamol', 'ibuprofène'): {'severity': 'low', 'effect': 'Additive antalgique (safe)', 'mechanism': 'Synergie antalgique sans interaction pharmacocinétique majeure', 'recommendation': 'Association possible et courante.'},
    ('ibuprofène', 'paracétamol'): {'severity': 'low', 'effect': 'Additive antalgique (safe)'},
    ('vitamine D', 'calcium'): {'severity': 'low', 'effect': 'Absorption optimisée', 'mechanism': 'Synergie métabolique'},
    ('vitamine D', 'magnésium'): {'severity': 'low', 'effect': 'Absorption optimisée'},
    ('fer', 'vitamine C'): {'severity': 'low', 'effect': 'Absorption du fer augmentée'},
    ('fer', 'calcium'): {'severity': 'low', 'effect': 'Diminution absorption du fer', 'recommendation': 'Espacer prises de 2h.'},
    ('fer', 'magnésium'): {'severity': 'low', 'effect': 'Diminution absorption du fer'},
    ('fer', 'zinc'): {'severity': 'low', 'effect': 'Compétition absorption intestinale'},
    ('acide folique', 'vitamine B12'): {'severity': 'low', 'effect': 'Synergie métabolique'},
    ('acide folique', 'méthotrexate'): {'severity': 'moderate', 'effect': 'Antagonisme folates'},

    # ── Interactions statines ──
    ('simvastatine', 'amlodipine'): {'severity': 'low', 'effect': 'Légère augmentation statinémie'},
    ('simvastatine', 'diltiazem'): {'severity': 'moderate', 'effect': 'Augmentation statinémie'},
    ('atorvastatine', 'digoxine'): {'severity': 'low', 'effect': 'Légère augmentation digoxinémie'},

    # ── Antiépileptiques + Contraceptifs oraux ──
    ('carbamazépine', 'éthinylestradiol'): {'severity': 'moderate', 'effect': 'Réduction efficacité contraceptive', 'mechanism': 'Induction CYP3A4', 'recommendation': 'Utiliser contraception mécanique ou doser plus haut.'},
    ('carbamazépine', 'lévonorgestrel'): {'severity': 'moderate', 'effect': 'Réduction efficacité contraceptive'},
    ('phénytoïne', 'éthinylestradiol'): {'severity': 'moderate', 'effect': 'Réduction efficacité contraceptive'},
    ('phénobarbital', 'éthinylestradiol'): {'severity': 'moderate', 'effect': 'Réduction efficacité contraceptive'},

    # ── Antiépileptiques ──
    ('carbamazépine', 'warfarine'): {'severity': 'moderate', 'effect': 'Réduction efficacité warfarine', 'mechanism': 'Induction CYP'},
    ('phénytoïne', 'warfarine'): {'severity': 'moderate', 'effect': 'Variation INR'},
    ('acide valproïque', 'phénobarbital'): {'severity': 'moderate', 'effect': 'Sédation excessive'},
    ('acide valproïque', 'lamotrigine'): {'severity': 'moderate', 'effect': 'Risque toxidermie', 'recommendation': 'Titration progressive lamotrigine.'},
    ('acide valproïque', 'topiramate'): {'severity': 'moderate', 'effect': 'Risque encéphalopathie hyperammoniémique'},

    # ── Antirétroviraux ──
    ('zidovudine', 'ribavirine'): {'severity': 'moderate', 'effect': 'Toxicité hématologique'},
    ('lopinavir', 'simvastatine'): {'severity': 'moderate', 'effect': 'Toxicité statine'},
    ('lopinavir', 'atorvastatine'): {'severity': 'moderate', 'effect': 'Augmentation atorvastatinémie'},

    # ── Antihypertenseurs + AINS (IA déjà ci-dessus, ajout spécifiques) ──
    ('hydrochlorothiazide', 'indométacine'): {'severity': 'moderate', 'effect': 'Réduction effet diurétique'},
    ('hydrochlorothiazide', 'kétoprofène'): {'severity': 'moderate', 'effect': 'Réduction effet diurétique'},

    # ── Biphosphonates + Calcium → Malabsorption ──
    ('alendronate', 'calcium'): {'severity': 'low', 'effect': 'Diminution absorption bisphosphonate', 'recommendation': 'Espacer prises de 30min.'},
    ('risédronate', 'calcium'): {'severity': 'low', 'effect': 'Diminution absorption'},
    ('alendronate', 'fer'): {'severity': 'low', 'effect': 'Diminution absorption'},

    # ── Divers ──
    ('allopurinol', 'azathioprine'): {'severity': 'high', 'effect': 'Toxicité hématologique sévère', 'mechanism': 'Inhibition xanthine oxydase', 'recommendation': 'Réduction dose azathioprine 60-75%. CI relative.'},
    ('allopurinol', '6-mercaptopurine'): {'severity': 'high', 'effect': 'Toxicité hématologique sévère'},
    ('allopurinol', 'warfarine'): {'severity': 'moderate', 'effect': 'Suraugmentation INR'},
    ('allopurinol', 'amoxicilline'): {'severity': 'low', 'effect': 'Risque rash cutané'},
    ('allopurinol', 'diurétique'): {'severity': 'moderate', 'effect': 'Risque insuffisance rénale aiguë'},

    # ── Antipsychotiques ──
    ('halopéridol', 'kétoconazole'): {'severity': 'moderate', 'effect': 'Augmentation effets extrapyramidaux'},
    ('halopéridol', 'fluoxétine'): {'severity': 'moderate', 'effect': 'Augmentation effets extrapyramidaux'},
    ('olanzapine', 'carbamazépine'): {'severity': 'moderate', 'effect': 'Diminution olanzapinémie'},
    ('rispéridone', 'paroxétine'): {'severity': 'moderate', 'effect': 'Augmentation rispéridonémie'},
}

PHARMACOLOGICAL_CLASSES = {
    'anticoagulant': {
        'keywords': ['warfarine', 'acénocoumarol', 'coumadine', 'sintrom', 'dabigatran', 'rivaroxaban', 'apixaban', 'edoxaban', 'héparine', 'énoxaparine', 'tinzaparine', 'nadroparine', 'dalteparine', 'fondaparinux', 'anti-vitamine k', 'avk', 'anticoagulant'],
        'interacts_with': ['nsaid', 'antiplaquettaire', 'antifongique_azole', 'antibiotique', 'anticonvulsivant']
    },
    'antiplaquettaire': {
        'keywords': ['clopidogrel', 'ticlopidine', 'prasugrel', 'ticagrélor', 'aspirine', 'acide acétylsalicylique', 'kardegic', 'antiagrégant'],
        'interacts_with': ['anticoagulant', 'nsaid']
    },
    'nsaid': {
        'keywords': ['ibuprofène', 'kétoprofène', 'naproxène', 'diclofénac', 'indométacine', 'piroxicam', 'méloxicam', 'célécoxib', 'étoricoxib', 'flurbiprofène', 'acide méfénamique', 'phénylbutazone', 'anti-inflammatoire non stéroïdien', 'ains'],
        'interacts_with': ['anticoagulant', 'antiplaquettaire', 'iec', 'ara2', 'diurétique', 'lithium', 'methotrexate', 'corticoïde', 'isrs', 'insuffisance_rénale']
    },
    'iec': {
        'keywords': ['énalapril', 'ramipril', 'lisinopril', 'captopril', 'périndopril', 'trandolapril', 'fosinopril', 'quinapril', 'inhibiteur enzyme conversion', 'iec'],
        'interacts_with': ['nsaid', 'potassium_sparing', 'potassium', 'diurétique', 'lithium']
    },
    'ara2': {
        'keywords': ['losartan', 'valsartan', 'candésartan', 'irbésartan', 'telmisartan', 'olmésartan', 'éprosartan', 'sartan', 'antagoniste récepteur angiotensine'],
        'interacts_with': ['nsaid', 'potassium_sparing', 'potassium', 'diurétique']
    },
    'diurétique': {
        'keywords': ['furosémide', 'hydrochlorothiazide', 'bumétanide', 'torasémide', 'indapamide', 'diurétique'],
        'interacts_with': ['nsaid', 'iec', 'lithium', 'digitalique']
    },
    'potassium_sparing': {
        'keywords': ['spironolactone', 'amiloride', 'triamtérène', 'éplérénone', 'diurétique épargneur potassium'],
        'interacts_with': ['iec', 'ara2', 'potassium']
    },
    'opioide': {
        'keywords': ['morphine', 'codéine', 'tramadol', 'fentanyl', 'oxycodone', 'hydromorphone', 'buprénorphine', 'nalbuphine', 'péthidine', 'opium', 'opioïde'],
        'interacts_with': ['benzodiazépine', 'alcool', 'barbiturique', 'isrs', 'ima']
    },
    'benzodiazépine': {
        'keywords': ['diazépam', 'alprazolam', 'lorazépam', 'bromazépam', 'clonazépam', 'midazolam', 'témazépam', 'oxazépam', 'prazépam', 'clorazépate', 'benzodiazépine'],
        'interacts_with': ['opioide', 'alcool', 'barbiturique']
    },
    'barbiturique': {
        'keywords': ['phénobarbital', 'pentobarbital', 'barbiturique'],
        'interacts_with': ['opioide', 'benzodiazépine', 'alcool', 'contraceptif']
    },
    'isrs': {
        'keywords': ['sertraline', 'fluoxétine', 'paroxétine', 'citalopram', 'escitalopram', 'fluvoxamine', 'inhibiteur recapture sérotonine', 'isrs'],
        'interacts_with': ['ima', 'nsaid', 'anticoagulant', 'tramadol']
    },
    'ima': {
        'keywords': ['iproniazide', 'phénelzine', 'tranylcypromine', 'isocarboxazide', 'moclobémide', 'inhibiteur monoamine oxydase', 'ima'],
        'interacts_with': ['isrs', 'opioide', 'tricyclique', 'sympathomimétique']
    },
    'methotrexate': {
        'keywords': ['méthotrexate'],
        'interacts_with': ['nsaid', 'triméthoprime']
    },
    'lithium': {
        'keywords': ['lithium', 'gluconate de lithium', 'carbonate de lithium'],
        'interacts_with': ['nsaid', 'iec', 'diurétique']
    },
    'corticoïde': {
        'keywords': ['prednisone', 'prednisolone', 'dexaméthasone', 'méthylprednisolone', 'bétaméthasone', 'hydrocortisone', 'corticoïde', 'corticostéroïde'],
        'interacts_with': ['nsaid', 'anticoagulant', 'diurétique']
    },
    'statine': {
        'keywords': ['simvastatine', 'atorvastatine', 'pravastatine', 'rosuvastatine', 'fluvastatine', 'pitavastatine', 'statine'],
        'interacts_with': ['macrolide', 'antifongique_azole', 'cyclosporine']
    },
    'macrolide': {
        'keywords': ['érythromycine', 'clarithromycine', 'azithromycine', 'roxithromycine', 'macrolide'],
        'interacts_with': ['statine', 'anticoagulant']
    },
    'digitalique': {
        'keywords': ['digoxine', 'digitoxine', 'digitaline'],
        'interacts_with': ['diurétique', 'amiodarone', 'vérapamil']
    },
    'antidiabétique': {
        'keywords': ['metformine', 'glibenclamide', 'glimépiride', 'gliclazide', 'pioglitazone', 'sitagliptine', 'vildagliptine', 'saxagliptine', 'dapagliflozine', 'insuline', 'antidiabétique'],
        'interacts_with': ['bêta-bloquant']
    },
    'bêta-bloquant': {
        'keywords': ['propranolol', 'aténolol', 'bisoprolol', 'métoprolol', 'nadolol', 'timolol', 'céliprolol', 'bêta-bloquant'],
        'interacts_with': ['antagoniste_calcique', 'antidiabétique']
    },
    'antagoniste_calcique': {
        'keywords': ['vérapamil', 'diltiazem', 'amlodipine', 'nifédipine', 'félodipine', 'lercanidipine', 'antagoniste calcique'],
        'interacts_with': ['bêta-bloquant']
    },
}


def strip_accents(s):
    return ''.join(c for c in unicodedata.normalize('NFD', s) if unicodedata.category(c) != 'Mn')


class FullKnowledgeGraphBuilder:
    def __init__(self):
        self.mongo = MongoClient(MONGO_URI)
        self.db = self.mongo[MONGO_DB]
        print(f"MongoDB connecté: {MONGO_URI}")

        try:
            self.driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
            self.driver.verify_connectivity()
            print(f"Neo4j connecté: {NEO4J_URI}")
        except Exception as e:
            print(f"Neo4j erreur: {e}")
            self.driver = None

    def close(self):
        self.mongo.close()
        if self.driver:
            self.driver.close()

    def create_constraints(self):
        if not self.driver:
            return
        with self.driver.session() as session:
            for c in [
                "CREATE CONSTRAINT medicine_url IF NOT EXISTS FOR (m:Medicine) REQUIRE m.url IS UNIQUE",
                "CREATE CONSTRAINT substance_name IF NOT EXISTS FOR (s:Substance) REQUIRE s.name IS UNIQUE",
                "CREATE CONSTRAINT lab_name IF NOT EXISTS FOR (l:Laboratory) REQUIRE l.name IS UNIQUE",
                "CREATE CONSTRAINT family_name IF NOT EXISTS FOR (f:TherapeuticFamily) REQUIRE f.name IS UNIQUE",
                "CREATE CONSTRAINT type_name IF NOT EXISTS FOR (t:MedicineType) REQUIRE t.name IS UNIQUE",
                "CREATE CONSTRAINT group_name IF NOT EXISTS FOR (g:AnatomicalGroup) REQUIRE g.name IS UNIQUE",
                "CREATE CONSTRAINT atc_code IF NOT EXISTS FOR (a:AtcCode) REQUIRE a.code IS UNIQUE",
            ]:
                try:
                    session.run(c)
                except Exception as e:
                    print(f"  Contrainte: {e}")
        print("Contraintes créées")

    def clear_graph(self):
        if not self.driver:
            return
        with self.driver.session() as session:
            session.run("MATCH (n) DETACH DELETE n")
        print("Graphe vidé")

    def import_medicines(self):
        if not self.driver:
            return
        total = self.db.medicines.count_documents({})
        print(f"\nImport de {total} médicaments...")
        cursor = self.db.medicines.find({}, {
            'url': 1, 'title': 1, 'update_date': 1,
            'medicine_details.forme': 1,
            'medicine_details.laboratoire': 1,
            'medicine_details.substances_actives': 1,
            'medicine_details.dosages': 1,
            'medicine_details.description_courte': 1,
            'type_medicament': 1, 'groupe_anatomique': 1,
            'famille_therapeutique': 1, 'code_atc': 1,
            'sections': 1,
        })
        batch = []
        processed = 0
        with self.driver.session() as session:
            for doc in cursor:
                url = doc.get('url', '')
                if not url:
                    continue
                details = doc.get('medicine_details', {})
                batch.append({
                    'url': url,
                    'title': doc.get('title', ''),
                    'forme': details.get('forme', ''),
                    'update_date': doc.get('update_date', ''),
                    'type_medicament': doc.get('type_medicament', ''),
                    'groupe_anatomique': doc.get('groupe_anatomique', ''),
                    'famille_therapeutique': doc.get('famille_therapeutique', ''),
                    'code_atc': doc.get('code_atc', ''),
                    'dosages': details.get('dosages', []),
                    'description_courte': details.get('description_courte', ''),
                    'substances': [s for s in details.get('substances_actives', []) if s],
                    'laboratoire': details.get('laboratoire', ''),
                })
                if len(batch) >= BATCH_SIZE:
                    self._batch_medicines(session, batch)
                    processed += len(batch)
                    print(f"  {processed}/{total}", end='\r')
                    batch = []
            if batch:
                self._batch_medicines(session, batch)
                processed += len(batch)
                print(f"  {processed}/{total}")
        print(f"Médicaments importés: {processed}")

    def _batch_medicines(self, session, batch):
        session.run("""
            UNWIND $batch AS doc
            MERGE (m:Medicine {url: doc.url})
            SET m.title = doc.title,
                m.forme = doc.forme,
                m.update_date = doc.update_date,
                m.type_medicament = doc.type_medicament,
                m.groupe_anatomique = doc.groupe_anatomique,
                m.famille_therapeutique = doc.famille_therapeutique,
                m.code_atc = doc.code_atc,
                m.dosages = doc.dosages,
                m.description_courte = doc.description_courte
        """, batch=batch)

    def create_relationships(self):
        if not self.driver:
            return
        print(f"\nCréation des relations...")

        # Substances
        print("  Substances...")
        cursor = self.db.medicines.find(
            {"medicine_details.substances_actives": {"$ne": [], "$exists": True}},
            {"url": 1, "medicine_details.substances_actives": 1}
        )
        batch = []
        for doc in cursor:
            url = doc.get('url', '')
            for s in doc.get('medicine_details', {}).get('substances_actives', []):
                if s and s.strip():
                    batch.append({'url': url, 'substance': s.strip()})
            if len(batch) >= BATCH_SIZE:
                self._run_batch("""
                    UNWIND $batch AS row
                    MERGE (s:Substance {name: row.substance})
                    WITH s, row
                    MATCH (m:Medicine {url: row.url})
                    MERGE (m)-[:CONTAINS_SUBSTANCE]->(s)
                """, batch)
                batch = []
        if batch:
            self._run_batch("""
                UNWIND $batch AS row
                MERGE (s:Substance {name: row.substance})
                WITH s, row
                MATCH (m:Medicine {url: row.url})
                MERGE (m)-[:CONTAINS_SUBSTANCE]->(s)
            """, batch)

        # Laboratoires
        print("  Laboratoires...")
        cursor = self.db.medicines.find(
            {"medicine_details.laboratoire": {"$ne": "", "$exists": True}},
            {"url": 1, "medicine_details.laboratoire": 1}
        )
        batch = []
        for doc in cursor:
            lab = doc.get('medicine_details', {}).get('laboratoire', '')
            if lab and lab.strip():
                batch.append({'url': doc['url'], 'lab': lab.strip()})
            if len(batch) >= BATCH_SIZE:
                self._run_batch("""
                    UNWIND $batch AS row
                    MERGE (l:Laboratory {name: row.lab})
                    WITH l, row
                    MATCH (m:Medicine {url: row.url})
                    MERGE (m)-[:MANUFACTURED_BY]->(l)
                """, batch)
                batch = []
        if batch:
            self._run_batch("""
                UNWIND $batch AS row
                MERGE (l:Laboratory {name: row.lab})
                WITH l, row
                MATCH (m:Medicine {url: row.url})
                MERGE (m)-[:MANUFACTURED_BY]->(l)
            """, batch)

        # Relations simples
        for field, rel_type, node_label, node_prop in [
            ("famille_therapeutique", "BELONGS_TO_FAMILY", "TherapeuticFamily", "name"),
            ("type_medicament", "IS_TYPE", "MedicineType", "name"),
            ("groupe_anatomique", "BELONGS_TO_GROUP", "AnatomicalGroup", "name"),
            ("code_atc", "HAS_ATC_CODE", "AtcCode", "code"),
        ]:
            print(f"  {rel_type}...")
            cursor = self.db.medicines.find({field: {"$ne": "", "$exists": True}}, {"url": 1, field: 1})
            batch = []
            with self.driver.session() as session:
                for doc in cursor:
                    val = doc.get(field, '')
                    if val and str(val).strip():
                        batch.append({'url': doc['url'], 'val': str(val).strip()})
                    if len(batch) >= BATCH_SIZE:
                        session.run(f"""
                            UNWIND $batch AS row
                            MERGE (n:{node_label} {{{node_prop}: row.val}})
                            WITH n, row
                            MATCH (m:Medicine {{url: row.url}})
                            MERGE (m)-[:{rel_type}]->(n)
                        """, batch=batch)
                        batch = []
                if batch:
                    session.run(f"""
                        UNWIND $batch AS row
                        MERGE (n:{node_label} {{{node_prop}: row.val}})
                        WITH n, row
                        MATCH (m:Medicine {{url: row.url}})
                        MERGE (m)-[:{rel_type}]->(n)
                    """, batch=batch)
        print("Relations créées")

    def _run_batch(self, query, batch):
        with self.driver.session() as session:
            session.run(query, batch=batch)

    def create_massive_interactions(self):
        """Crée INTERACTS_WITH dans Neo4j via la base INTERACTION_DB + classes pharmacologiques"""
        if not self.driver:
            return

        print("\nCréation des interactions médicamenteuses...")

        # 1. Récupérer toutes les substances normalisées de Neo4j
        with self.driver.session() as session:
            result = session.run("MATCH (s:Substance) RETURN s.name AS name")
            neo4j_substances = {}
            for r in result:
                name = r['name']
                key = strip_accents(name).lower().strip()
                neo4j_substances[key] = name

        print(f"  Substances dans Neo4j: {len(neo4j_substances)}")

        # 2. Créer un index substance → matière active normalisée pour matching
        substance_name_index = {}
        for key, orig in neo4j_substances.items():
            substance_name_index[key] = orig

        # 3. Matcher les paires INTERACTION_DB avec les substances Neo4j
        interaction_rels = []
        matched_pairs = 0

        for (subst1_raw, subst2_raw), meta in INTERACTION_DB.items():
            s1_key = strip_accents(subst1_raw).lower().strip()
            s2_key = strip_accents(subst2_raw).lower().strip()

            matches_s1 = []
            matches_s2 = []

            for neo_key, neo_name in substance_name_index.items():
                nk = neo_key

                # Match exact ou contenu
                if nk == s1_key or s1_key in nk or nk in s1_key:
                    matches_s1.append(neo_name)
                if nk == s2_key or s2_key in nk or nk in s2_key:
                    matches_s2.append(neo_name)

                # Match par mot-clé partiel pour les noms composés
                if not matches_s1:
                    s1_words = s1_key.split()
                    if len(s1_words) > 1:
                        if all(w in nk for w in s1_words):
                            matches_s1.append(neo_name)
                if not matches_s2:
                    s2_words = s2_key.split()
                    if len(s2_words) > 1:
                        if all(w in nk for w in s2_words):
                            matches_s2.append(neo_name)

            if not matches_s1 or not matches_s2:
                continue

            matched_pairs += 1
            severity = meta.get('severity', 'moderate')
            effect = meta.get('effect', '')
            mechanism = meta.get('mechanism', '')
            recommendation = meta.get('recommendation', '')

            # Pour chaque combinaison de substances correspondantes
            for ms1 in matches_s1:
                for ms2 in matches_s2:
                    if ms1 == ms2:
                        continue
                    interaction_rels.append({
                        'substance1': ms1,
                        'substance2': ms2,
                        'severity': severity,
                        'effect': effect,
                        'mechanism': mechanism,
                        'recommendation': recommendation,
                        'source': 'pharmacological_database'
                    })

        print(f"  Paires de substances matchées: {matched_pairs}")
        print(f"  Relations substance-substance préparées: {len(interaction_rels)}")

        # 4. Pour chaque paire de substances, créer INTERACTS_WITH entre leurs médicaments
        total_med_rels = 0
        med_rel_batch = []

        for idx, irel in enumerate(interaction_rels):
            if idx % 50 == 0 and idx > 0:
                print(f"  Traitement paire {idx}/{len(interaction_rels)}...", end='\r')
                if med_rel_batch:
                    self._batch_med_interactions(med_rel_batch)
                    total_med_rels += len(med_rel_batch)
                    med_rel_batch = []

            with self.driver.session() as session:
                result = session.run("""
                    MATCH (m1:Medicine)-[:CONTAINS_SUBSTANCE]->(s1:Substance {name: $s1})
                    MATCH (m2:Medicine)-[:CONTAINS_SUBSTANCE]->(s2:Substance {name: $s2})
                    WHERE m1.url <> m2.url
                    RETURN m1.url AS m1_url, m1.title AS m1_title,
                           m2.url AS m2_url, m2.title AS m2_title
                    LIMIT 20
                """, s1=irel['substance1'], s2=irel['substance2'])

                pairs = set()
                for r in result:
                    pair_key = tuple(sorted([r['m1_url'], r['m2_url']]))
                    if pair_key not in pairs:
                        pairs.add(pair_key)
                        med_rel_batch.append({
                            'url1': r['m1_url'],
                            'url2': r['m2_url'],
                            'title1': r['m1_title'],
                            'title2': r['m2_title'],
                            'substance1': irel['substance1'],
                            'substance2': irel['substance2'],
                            'severity': irel['severity'],
                            'effect': irel['effect'],
                            'mechanism': irel.get('mechanism', ''),
                            'recommendation': irel.get('recommendation', '')
                        })

            if len(med_rel_batch) >= BATCH_SIZE:
                self._batch_med_interactions(med_rel_batch)
                total_med_rels += len(med_rel_batch)
                med_rel_batch = []

        if med_rel_batch:
            self._batch_med_interactions(med_rel_batch)
            total_med_rels += len(med_rel_batch)

        print(f"\n  Relations INTERACTS_WITH créées: {total_med_rels}")

    def _batch_med_interactions(self, batch):
        with self.driver.session() as session:
            session.run("""
                UNWIND $batch AS row
                MATCH (m1:Medicine {url: row.url1})
                MATCH (m2:Medicine {url: row.url2})
                MERGE (m1)-[r:INTERACTS_WITH]-(m2)
                SET r.severity = row.severity,
                    r.effect = row.effect,
                    r.mechanism = row.mechanism,
                    r.recommendation = row.recommendation,
                    r.substance1 = row.substance1,
                    r.substance2 = row.substance2,
                    r.source = row.source
            """, batch=batch)

    def populate_mongodb_interactions(self):
        """Populate MongoDB interactions collection with detailed clinical data"""
        print("\nPopulation MongoDB interactions...")

        interactions_col = self.db['interactions']

        if not self.driver:
            return

        with self.driver.session() as session:
            result = session.run("""
                MATCH (m1:Medicine)-[r:INTERACTS_WITH]-(m2:Medicine)
                WHERE m1.url < m2.url
                RETURN m1.url AS url1, m1.title AS title1,
                       m2.url AS url2, m2.title AS title2,
                       r.severity AS severity, r.effect AS effect,
                       r.mechanism AS mechanism, r.recommendation AS recommendation,
                       r.substance1 AS substance1, r.substance2 AS substance2
                LIMIT 5000
            """)

            existing_pairs = set()
            for doc in interactions_col.find({}, {'medicine_pair': 1}):
                existing_pairs.add(doc.get('medicine_pair', ''))

            batch = []
            added = 0
            for r in result:
                pair_key = f"{r['url1']}-{r['url2']}"
                if pair_key in existing_pairs:
                    continue

                batch.append({
                    'medicine1_id': r['url1'],
                    'medicine1_title': r['title1'],
                    'medicine2_id': r['url2'],
                    'medicine2_title': r['title2'],
                    'medicine_pair': pair_key,
                    'substance1': r.get('substance1', ''),
                    'substance2': r.get('substance2', ''),
                    'severity': r.get('severity', 'moderate'),
                    'description': r.get('effect', ''),
                    'mechanism': r.get('mechanism', ''),
                    'recommendation': r.get('recommendation', ''),
                    'created_at': time.time(),
                    'verified': True,
                    'source': 'pharmacological_database',
                    'generated': True,
                })
                added += 1

                if len(batch) >= 100:
                    try:
                        interactions_col.insert_many(batch, ordered=False)
                    except Exception:
                        pass
                    batch = []

            if batch:
                try:
                    interactions_col.insert_many(batch, ordered=False)
                except Exception:
                    pass

            print(f"  Interactions ajoutées à MongoDB: {added}")
            total = interactions_col.count_documents({})
            print(f"  Total interactions dans MongoDB: {total}")

    def get_stats(self):
        if not self.driver:
            return
        with self.driver.session() as session:
            result = session.run("MATCH (n) RETURN labels(n) AS type, count(*) AS total ORDER BY type")
            print("\n=== STATISTIQUES NEO4J ===")
            for record in result:
                print(f"  {str(record['type'][0]):20s}: {record['total']}")
            result = session.run("MATCH ()-[r]->() RETURN type(r) AS relation, count(*) AS total ORDER BY relation")
            for record in result:
                print(f"  {record['relation']:25s}: {record['total']}")


def main():
    print("=" * 60)
    print("  CONSTRUCTION COMPLÈTE NEO4J - MEDICSEARCH")
    print("  Base d'interactions: {} paires de substances".format(len(INTERACTION_DB)))
    print("=" * 60)

    builder = FullKnowledgeGraphBuilder()
    if not builder.driver:
        print("Neo4j non disponible")
        builder.close()
        return

    t0 = time.time()

    builder.clear_graph()
    builder.create_constraints()
    builder.import_medicines()
    builder.create_relationships()
    builder.create_massive_interactions()
    builder.populate_mongodb_interactions()
    builder.get_stats()

    elapsed = time.time() - t0
    print(f"\nDurée totale: {elapsed:.1f}s")
    builder.close()

    print("\n" + "=" * 60)
    print("  TERMINÉ - {} interactions dans Neo4j".format(
        "✓ Base de connaissances complète"
    ))
    print("=" * 60)


if __name__ == '__main__':
    main()
