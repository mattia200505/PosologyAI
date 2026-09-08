// =============================================================================
// DONNÉES EXEMPLES — Knowledge Graph Médicaments
// Usage : CAT sample_data.cypher sample_diseases.cypher | cypher-shell
// =============================================================================

// ─── VI. DRUG CLASSES ────────────────────────────────────────────────────────

MERGE (c:DrugClass {name: 'Antalgique'})
  SET c.mechanism_of_action = 'Inhibition de la cyclooxygénase (COX) et modulation des récepteurs opioïdes',
      c.parent_class = 'Système nerveux',
      c.description = 'Médicaments utilisés pour soulager la douleur';

MERGE (c2:DrugClass {name: 'AINS'})
  SET c2.mechanism_of_action = 'Inhibition non sélective des COX-1 et COX-2 → blocage de la synthèse des prostaglandines',
      c2.parent_class = 'Anti-inflammatoire',
      c2.description = 'Anti-inflammatoires non stéroïdiens';

MERGE (c3:DrugClass {name: 'Anticoagulant'})
  SET c3.mechanism_of_action = 'Inhibition de la cascade de coagulation (anti-Xa, anti-IIa)',
      c3.parent_class = 'Système cardiovasculaire',
      c3.description = 'Médicaments qui réduisent la capacité de coagulation du sang';

MERGE (c4:DrugClass {name: 'Antihypertenseur'})
  SET c4.mechanism_of_action = 'Inhibition de l\'enzyme de conversion (IEC) ou blocage des récepteurs AT1 (ARA2)',
      c4.parent_class = 'Système cardiovasculaire',
      c4.description = 'Médicaments abaissant la pression artérielle';

MERGE (c5:DrugClass {name: 'Antidépresseur'})
  SET c5.mechanism_of_action = 'Inhibition de la recapture de la sérotonine et/ou noradrénaline',
      c5.parent_class = 'Système nerveux',
      c5.description = 'Médicaments utilisés dans le traitement des troubles dépressifs';

MERGE (c6:DrugClass {name: 'Antibiotique'})
  SET c6.mechanism_of_action = 'Inhibition de la synthèse de la paroi bactérienne (β-lactamines)',
      c6.parent_class = 'Anti-infectieux',
      c6.description = 'Médicaments actifs contre les infections bactériennes';

MERGE (c7:DrugClass {name: 'Antidiabétique'})
  SET c7.mechanism_of_action = 'Augmentation de la sensibilité à l\'insuline et/ou stimulation de sa sécrétion',
      c7.parent_class = 'Métabolisme',
      c7.description = 'Médicaments pour le traitement du diabète de type 2';

MERGE (c8:DrugClass {name: 'Hypolipémiant'})
  SET c8.mechanism_of_action = 'Inhibition de la HMG-CoA réductase → baisse du cholestérol LDL',
      c8.parent_class = 'Système cardiovasculaire',
      c8.description = 'Médicaments abaissant le taux de cholestérol sanguin';

// Sous-classes
MERGE (c2)-[:HAS_SUBCLASS]->(:DrugClass {name: 'Inhibiteur COX-2 sélectif', mechanism_of_action: 'Inhibition sélective COX-2 sans effet COX-1', parent_class: 'AINS'});
MERGE (c4)-[:HAS_SUBCLASS]->(:DrugClass {name: 'IEC', mechanism_of_action: 'Inhibition de l\'enzyme de conversion de l\'angiotensine', parent_class: 'Antihypertenseur'});
MERGE (c4)-[:HAS_SUBCLASS]->(:DrugClass {name: 'ARA2', mechanism_of_action: 'Antagoniste des récepteurs AT1 de l\'angiotensine II', parent_class: 'Antihypertenseur'});
MERGE (c6)-[:HAS_SUBCLASS]->(:DrugClass {name: 'Pénicilline', mechanism_of_action: 'Inhibition de la transpeptidase → blocage synthèse peptidoglycane', parent_class: 'Antibiotique'});

// ─── VII. DISEASES ───────────────────────────────────────────────────────────

MERGE (d1:Disease {name: 'Hypertension artérielle'})
  SET d1.symptoms = 'Céphalées, vertiges, acouphènes, épistaxis',
      d1.category = 'Cardiovasculaire',
      d1.icd10_code = 'I10',
      d1.description = 'Élévation chronique de la pression artérielle au-dessus des valeurs normales',
      d1.source = 'HAS',
      d1.confidence_score = 99;

MERGE (d2:Disease {name: 'Diabète de type 2'})
  SET d2.symptoms = 'Polyurie, polydipsie, polyphagie, fatigue, vision floue',
      d2.category = 'Métabolique',
      d2.icd10_code = 'E11',
      d2.description = 'Trouble métabolique caractérisé par une hyperglycémie chronique due à une insulinorésistance',
      d2.source = 'HAS',
      d2.confidence_score = 99;

MERGE (d3:Disease {name: 'Hypercholestérolémie'})
  SET d3.symptoms = 'Aucun symptôme direct (facteur de risque silencieux)',
      d3.category = 'Cardiovasculaire',
      d3.icd10_code = 'E78.0',
      d3.description = 'Taux élevé de cholestérol LDL dans le sang',
      d3.source = 'HAS',
      d3.confidence_score = 99;

MERGE (d4:Disease {name: 'Douleur aiguë'})
  SET d4.symptoms = 'Douleur localisée ou diffuse, aiguë ou chronique',
      d4.category = 'Neurologique',
      d4.icd10_code = 'R52',
      d4.description = 'Expérience sensorielle et émotionnelle désagréable associée à une lésion tissulaire',
      d4.source = 'INRS',
      d4.confidence_score = 98;

MERGE (d5:Disease {name: 'Infection bactérienne'})
  SET d5.symptoms = 'Fièvre, inflammation, douleur, pus, rougeur',
      d5.category = 'Infectieux',
      d5.icd10_code = 'A49',
      d5.description = 'Infection causée par des bactéries pathogènes',
      d5.source = 'OMS',
      d5.confidence_score = 99;

MERGE (d6:Disease {name: 'Dépression majeure'})
  SET d6.symptoms = 'Humeur dépressive, anhédonie, troubles du sommeil, fatigue, idées suicidaires',
      d6.category = 'Psychiatrique',
      d6.icd10_code = 'F32',
      d6.description = 'Trouble de l\'humeur caractérisé par des épisodes dépressifs sévères',
      d6.source = 'DSM-5',
      d6.confidence_score = 98;

MERGE (d7:Disease {name: 'Trouble anxieux généralisé'})
  SET d7.symptoms = 'Anxiété excessive, irritabilité, tension musculaire, troubles du sommeil',
      d7.category = 'Psychiatrique',
      d7.icd10_code = 'F41.1',
      d7.description = 'Anxiété persistante et excessive concernant des événements quotidiens',
      d7.source = 'DSM-5',
      d7.confidence_score = 98;

MERGE (d8:Disease {name: 'Œdème d\'origine veineuse'})
  SET d8.symptoms = 'Jambes lourdes, varices, œdème des membres inférieurs',
      d8.category = 'Vasculaire',
      d8.icd10_code = 'I87.2',
      d8.description = 'Insuffisance veineuse chronique avec rétention d\'eau dans les tissus',
      d8.source = 'HAS',
      d8.confidence_score = 95;

// ─── VIII. ACTIVE INGREDIENTS ────────────────────────────────────────────────

MERGE (i1:ActiveIngredient {name: 'Paracétamol'})
  SET i1.chemical_formula = 'C8H9NO2',
      i1.molecular_weight = 151.16,
      i1.pharmacological_class = 'Antalgique non opioïde',
      i1.mechanism_summary = 'Inhibition centrale des COX, activation des voies sérotoninergiques descendantes',
      i1.source = 'DrugBank',
      i1.confidence_score = 99,
      i1.updated_at = datetime();

MERGE (i2:ActiveIngredient {name: 'Ibuprofène'})
  SET i2.chemical_formula = 'C13H18O2',
      i2.molecular_weight = 206.28,
      i2.pharmacological_class = 'AINS — propionique',
      i2.mechanism_summary = 'Inhibition non sélective COX-1/COX-2, anti-inflammatoire périphérique',
      i2.source = 'DrugBank',
      i2.confidence_score = 99,
      i2.updated_at = datetime();

MERGE (i3:ActiveIngredient {name: 'Amoxicilline'})
  SET i3.chemical_formula = 'C16H19N3O5S',
      i3.molecular_weight = 365.40,
      i3.pharmacological_class = 'β-lactamine — aminopénicilline',
      i3.mechanism_summary = 'Inhibition de la synthèse du peptidoglycane bactérien → lyse osmotique',
      i3.source = 'DrugBank',
      i3.confidence_score = 99,
      i3.updated_at = datetime();

MERGE (i4:ActiveIngredient {name: 'Acide acétylsalicylique'})
  SET i4.chemical_formula = 'C9H8O4',
      i4.molecular_weight = 180.16,
      i4.pharmacological_class = 'AINS — salicylé, antiagrégant plaquettaire',
      i4.mechanism_summary = 'Acétylation irréversible COX-1/COX-2, inhibition de la synthèse des thromboxanes',
      i4.source = 'DrugBank',
      i4.confidence_score = 99,
      i4.updated_at = datetime();

MERGE (i5:ActiveIngredient {name: 'Atorvastatine'})
  SET i5.chemical_formula = 'C33H35FN2O5',
      i5.molecular_weight = 558.64,
      i5.pharmacological_class = 'Statine',
      i5.mechanism_summary = 'Inhibition compétitive de la HMG-CoA réductase → baisse du cholestérol endogène',
      i5.source = 'DrugBank',
      i5.confidence_score = 99,
      i5.updated_at = datetime();

MERGE (i6:ActiveIngredient {name: 'Ramipril'})
  SET i6.chemical_formula = 'C23H32N2O5',
      i6.molecular_weight = 416.51,
      i6.pharmacological_class = 'IEC',
      i6.mechanism_summary = 'Inhibition de l\'enzyme de conversion → baisse angiotensine II et aldostérone',
      i6.source = 'DrugBank',
      i6.confidence_score = 99,
      i6.updated_at = datetime();

MERGE (i7:ActiveIngredient {name: 'Metformine'})
  SET i7.chemical_formula = 'C4H11N5',
      i7.molecular_weight = 129.16,
      i7.pharmacological_class = 'Biguanide',
      i7.mechanism_summary = 'Activation AMPK → inhibition néoglucogenèse hépatique, augmentation sensibilité insuline',
      i7.source = 'DrugBank',
      i7.confidence_score = 99,
      i7.updated_at = datetime();

MERGE (i8:ActiveIngredient {name: 'Sertraline'})
  SET i8.chemical_formula = 'C17H17Cl2N',
      i8.molecular_weight = 306.23,
      i8.pharmacological_class = 'ISRS',
      i8.mechanism_summary = 'Inhibition sélective de la recapture de la sérotonine (5-HT) au niveau présynaptique',
      i8.source = 'DrugBank',
      i8.confidence_score = 99,
      i8.updated_at = datetime();

MERGE (i9:ActiveIngredient {name: 'Diosmine'})
  SET i9.chemical_formula = 'C28H32O15',
      i9.molecular_weight = 608.54,
      i9.pharmacological_class = 'Flavonoïde veinotonique',
      i9.mechanism_summary = 'Augmentation du tonus veineux, protection capillaire, inhibition des prostaglandines',
      i9.source = 'DrugBank',
      i9.confidence_score = 95,
      i9.updated_at = datetime();

MERGE (i10:ActiveIngredient {name: 'Kétoprofène'})
  SET i10.chemical_formula = 'C16H14O3',
      i10.molecular_weight = 254.28,
      i10.pharmacological_class = 'AINS — propionique',
      i10.mechanism_summary = 'Inhibition non sélective COX-1/COX-2, inhibition de la synthèse des prostaglandines',
      i10.source = 'DrugBank',
      i10.confidence_score = 99,
      i10.updated_at = datetime();

// ─── IX. DRUGS ───────────────────────────────────────────────────────────────

// DOLIPRANE
MERGE (drug1:Drug {id: 'D001', title: 'DOLIPRANE 500 mg'})
  SET drug1.generic_name = 'Paracétamol',
      drug1.brand_name = 'Doliprane',
      drug1.atc_code = 'N02BE01',
      drug1.therapeutic_class = 'Antalgique',
      drug1.laboratory = 'Sanofi',
      drug1.form = 'Comprimé',
      drug1.dosage = '500 mg',
      drug1.route = 'Orale',
      drug1.marketing_status = 'Autorisé',
      drug1.source = 'ANSM',
      drug1.confidence_score = 99,
      drug1.updated_at = datetime(),
      drug1.created_at = datetime();

MERGE (drug2:Drug {id: 'D002', title: 'DOLIPRANE 1000 mg'})
  SET drug2.generic_name = 'Paracétamol',
      drug2.brand_name = 'Doliprane',
      drug2.atc_code = 'N02BE01',
      drug2.therapeutic_class = 'Antalgique',
      drug2.laboratory = 'Sanofi',
      drug2.form = 'Comprimé',
      drug2.dosage = '1000 mg',
      drug2.route = 'Orale',
      drug2.marketing_status = 'Autorisé',
      drug2.source = 'ANSM',
      drug2.confidence_score = 99,
      drug2.updated_at = datetime(),
      drug2.created_at = datetime();

// EFFERALGAN
MERGE (drug3:Drug {id: 'D003', title: 'EFFERALGAN 500 mg'})
  SET drug3.generic_name = 'Paracétamol',
      drug3.brand_name = 'Efferalgan',
      drug3.atc_code = 'N02BE01',
      drug3.therapeutic_class = 'Antalgique',
      drug3.laboratory = 'UPSA',
      drug3.form = 'Comprimé effervescent',
      drug3.dosage = '500 mg',
      drug3.route = 'Orale',
      drug3.marketing_status = 'Autorisé',
      drug3.source = 'ANSM',
      drug3.confidence_score = 99,
      drug3.updated_at = datetime(),
      drug3.created_at = datetime();

// ADVIL
MERGE (drug4:Drug {id: 'D004', title: 'ADVIL 400 mg'})
  SET drug4.generic_name = 'Ibuprofène',
      drug4.brand_name = 'Advil',
      drug4.atc_code = 'M01AE01',
      drug4.therapeutic_class = 'AINS',
      drug4.laboratory = 'Pfizer',
      drug4.form = 'Comprimé',
      drug4.dosage = '400 mg',
      drug4.route = 'Orale',
      drug4.marketing_status = 'Autorisé',
      drug4.source = 'ANSM',
      drug4.confidence_score = 99,
      drug4.updated_at = datetime(),
      drug4.created_at = datetime();

// ASPIRINE
MERGE (drug5:Drug {id: 'D005', title: 'ASPIRINE 100 mg'})
  SET drug5.generic_name = 'Acide acétylsalicylique',
      drug5.brand_name = 'Aspirine',
      drug5.atc_code = 'B01AC06',
      drug5.therapeutic_class = 'Antiplaquettaire',
      drug5.laboratory = 'Bayer',
      drug5.form = 'Comprimé',
      drug5.dosage = '100 mg',
      drug5.route = 'Orale',
      drug5.marketing_status = 'Autorisé',
      drug5.source = 'ANSM',
      drug5.confidence_score = 99,
      drug5.updated_at = datetime(),
      drug5.created_at = datetime();

// TAHOR
MERGE (drug6:Drug {id: 'D006', title: 'TAHOR 20 mg'})
  SET drug6.generic_name = 'Atorvastatine',
      drug6.brand_name = 'Tahor',
      drug6.atc_code = 'C10AA05',
      drug6.therapeutic_class = 'Hypolipémiant',
      drug6.laboratory = 'Pfizer',
      drug6.form = 'Comprimé',
      drug6.dosage = '20 mg',
      drug6.route = 'Orale',
      drug6.marketing_status = 'Autorisé',
      drug6.source = 'ANSM',
      drug6.confidence_score = 99,
      drug6.updated_at = datetime(),
      drug6.created_at = datetime();

// TRIATEC
MERGE (drug7:Drug {id: 'D007', title: 'TRIATEC 5 mg'})
  SET drug7.generic_name = 'Ramipril',
      drug7.brand_name = 'Triatec',
      drug7.atc_code = 'C09AA05',
      drug7.therapeutic_class = 'IEC',
      drug7.laboratory = 'Sanofi',
      drug7.form = 'Comprimé',
      drug7.dosage = '5 mg',
      drug7.route = 'Orale',
      drug7.marketing_status = 'Autorisé',
      drug7.source = 'ANSM',
      drug7.confidence_score = 99,
      drug7.updated_at = datetime(),
      drug7.created_at = datetime();

// GLUCOPHAGE
MERGE (drug8:Drug {id: 'D008', title: 'GLUCOPHAGE 1000 mg'})
  SET drug8.generic_name = 'Metformine',
      drug8.brand_name = 'Glucophage',
      drug8.atc_code = 'A10BA02',
      drug8.therapeutic_class = 'Antidiabétique',
      drug8.laboratory = 'Merck',
      drug8.form = 'Comprimé',
      drug8.dosage = '1000 mg',
      drug8.route = 'Orale',
      drug8.marketing_status = 'Autorisé',
      drug8.source = 'ANSM',
      drug8.confidence_score = 99,
      drug8.updated_at = datetime(),
      drug8.created_at = datetime();

// ZOLOFT
MERGE (drug9:Drug {id: 'D009', title: 'ZOLOFT 50 mg'})
  SET drug9.generic_name = 'Sertraline',
      drug9.brand_name = 'Zoloft',
      drug9.atc_code = 'N06AB06',
      drug9.therapeutic_class = 'Antidépresseur ISRS',
      drug9.laboratory = 'Pfizer',
      drug9.form = 'Comprimé',
      drug9.dosage = '50 mg',
      drug9.route = 'Orale',
      drug9.marketing_status = 'Autorisé',
      drug9.source = 'ANSM',
      drug9.confidence_score = 99,
      drug9.updated_at = datetime(),
      drug9.created_at = datetime();

// DAFLON
MERGE (drug10:Drug {id: 'D010', title: 'DAFLON 500 mg'})
  SET drug10.generic_name = 'Diosmine',
      drug10.brand_name = 'Daflon',
      drug10.atc_code = 'C05CA03',
      drug10.therapeutic_class = 'Veinotonique',
      drug10.laboratory = 'Servier',
      drug10.form = 'Comprimé',
      drug10.dosage = '500 mg',
      drug10.route = 'Orale',
      drug10.marketing_status = 'Autorisé',
      drug10.source = 'ANSM',
      drug10.confidence_score = 99,
      drug10.updated_at = datetime(),
      drug10.created_at = datetime();

// AMOXICILLINE BIOGARAN
MERGE (drug11:Drug {id: 'D011', title: 'AMOXICILLINE BIOGARAN 500 mg'})
  SET drug11.generic_name = 'Amoxicilline',
      drug11.brand_name = 'Amoxicilline Biogaran',
      drug11.atc_code = 'J01CA04',
      drug11.therapeutic_class = 'Antibiotique',
      drug11.laboratory = 'Biogaran',
      drug11.form = 'Gélule',
      drug11.dosage = '500 mg',
      drug11.route = 'Orale',
      drug11.marketing_status = 'Autorisé',
      drug11.source = 'ANSM',
      drug11.confidence_score = 99,
      drug11.updated_at = datetime(),
      drug11.created_at = datetime();

// ─── X. EFFECTS ──────────────────────────────────────────────────────────────

MERGE (e1:Effect {id: 'E001', name: 'Nausées'})
  SET e1.severity = 'Modéré',
      e1.frequency = 'Fréquent (>1%)',
      e1.description = 'Sensation de malaise avec envie de vomir',
      e1.source = 'ANSM',
      e1.confidence_score = 95;

MERGE (e2:Effect {id: 'E002', name: 'Hémorragie digestive'})
  SET e2.severity = 'Grave',
      e2.frequency = 'Rare (<0.1%)',
      e2.description = 'Saignement dans le tube digestif, potentiellement mortel',
      e2.source = 'ANSM',
      e2.confidence_score = 98;

MERGE (e3:Effect {id: 'E003', name: 'Toxicité hépatique'})
  SET e3.severity = 'Grave',
      e3.frequency = 'Rare (<0.1%)',
      e3.description = 'Atteinte du foie, risque d\'insuffisance hépatique aiguë à dose excessive',
      e3.source = 'ANSM',
      e3.confidence_score = 99;

MERGE (e4:Effect {id: 'E004', name: 'Somnolence'})
  SET e4.severity = 'Modéré',
      e4.frequency = 'Fréquent (>1%)',
      e4.description = 'Baisse de la vigilance, tendance au sommeil',
      e4.source = 'ANSM',
      e4.confidence_score = 95;

MERGE (e5:Effect {id: 'E005', name: 'Diarrhée'})
  SET e5.severity = 'Modéré',
      e5.frequency = 'Fréquent (>1%)',
      e5.description = 'Émissions fréquentes de selles liquides',
      e5.source = 'ANSM',
      e5.confidence_score = 95;

MERGE (e6:Effect {id: 'E006', name: 'Hypoglycémie'})
  SET e6.severity = 'Grave',
      e6.frequency = 'Peu fréquent (0.1-1%)',
      e6.description = 'Baisse dangereuse du taux de sucre dans le sang',
      e6.source = 'ANSM',
      e6.confidence_score = 98;

MERGE (e7:Effect {id: 'E007', name: 'Toux sèche'})
  SET e7.severity = 'Bénin',
      e7.frequency = 'Fréquent (>1%)',
      e7.description = 'Toux irritative non productive',
      e7.source = 'ANSM',
      e7.confidence_score = 95;

MERGE (e8:Effect {id: 'E008', name: 'Insomnie'})
  SET e8.severity = 'Modéré',
      e8.frequency = 'Peu fréquent (0.1-1%)',
      e8.description = 'Difficultés d\'endormissement ou réveils nocturnes',
      e8.source = 'ANSM',
      e8.confidence_score = 95;

MERGE (e9:Effect {id: 'E009', name: 'Réaction allergique'})
  SET e9.severity = 'Grave',
      e9.frequency = 'Rare (<0.1%)',
      e9.description = 'Urticaire, œdème de Quincke, choc anaphylactique',
      e9.source = 'ANSM',
      e9.confidence_score = 99;

MERGE (e10:Effect {id: 'E010', name: 'Troubles digestifs'})
  SET e10.severity = 'Modéré',
      e10.frequency = 'Fréquent (>1%)',
      e10.description = 'Douleurs abdominales, dyspepsie, flatulences',
      e10.source = 'ANSM',
      e10.confidence_score = 95;

MERGE (e11:Effect {id: 'E011', name: 'Rhabdomyolyse'})
  SET e11.severity = 'Grave',
      e11.frequency = 'Très rare (<0.01%)',
      e11.description = 'Destruction des cellules musculaires → risque d\'insuffisance rénale aiguë',
      e11.source = 'ANSM',
      e11.confidence_score = 99;

// ─── XI. CONTRAINDICATIONS ───────────────────────────────────────────────────

MERGE (c01:Contraindication {id: 'CI001', name: 'Insuffisance hépatique sévère'})
  SET c01.reason = 'Risque de toxicité hépatique grave par accumulation du métabolite toxique NAPQI',
      c01.severity = 'Absolue',
      c01.category = 'Hépatique',
      c01.source = 'ANSM',
      c01.confidence_score = 99;

MERGE (c02:Contraindication {id: 'CI002', name: 'Insuffisance rénale sévère'})
  SET c02.reason = 'Élimination rénale réduite → accumulation et toxicité',
      c02.severity = 'Absolue',
      c02.category = 'Rénal',
      c02.source = 'ANSM',
      c02.confidence_score = 99;

MERGE (c03:Contraindication {id: 'CI003', name: 'Grossesse (3e trimestre)'})
  SET c03.reason = 'Risque de fermeture prématurée du canal artériel fœtal et d\'oligohydramnios',
      c03.severity = 'Absolue',
      c03.category = 'Grossesse',
      c03.source = 'ANSM',
      c03.confidence_score = 99;

MERGE (c04:Contraindication {id: 'CI004', name: 'Allergie aux β-lactamines'})
  SET c04.reason = 'Risque de réaction allergique croisée, potentiellement grave',
      c04.severity = 'Absolue',
      c04.category = 'Allergie',
      c04.source = 'ANSM',
      c04.confidence_score = 99;

MERGE (c05:Contraindication {id: 'CI005', name: 'Ulcère gastroduodénal évolutif'})
  SET c05.reason = 'Risque d\'aggravation de l\'ulcère et d\'hémorragie digestive',
      c05.severity = 'Absolue',
      c05.category = 'Digestif',
      c05.source = 'ANSM',
      c05.confidence_score = 99;

MERGE (c06:Contraindication {id: 'CI006', name: 'Antécédent d\'accident vasculaire cérébral'})
  SET c06.reason = 'Risque hémorragique accru',
      c06.severity = 'Relative',
      c06.category = 'Neurologique',
      c06.source = 'ANSM',
      c06.confidence_score = 98;

MERGE (c07:Contraindication {id: 'CI007', name: 'Insuffisance cardiaque non contrôlée'})
  SET c07.reason = 'Risque de décompensation cardiaque',
      c07.severity = 'Relative',
      c07.category = 'Cardiovasculaire',
      c07.source = 'ANSM',
      c07.confidence_score = 98;

MERGE (c08:Contraindication {id: 'CI008', name: 'Allaitement'})
  SET c08.reason = 'Passage dans le lait maternel, risque pour le nourrisson',
      c08.severity = 'Relative',
      c08.category = 'Pédiatrie',
      c08.source = 'ANSM',
      c08.confidence_score = 95;

// ─── XII. RELATIONS ──────────────────────────────────────────────────────────

// CONTIENT : Drug → ActiveIngredient
MATCH (d:Drug {id: 'D001'}), (i:ActiveIngredient {name: 'Paracétamol'})
  MERGE (d)-[:CONTAINS {dosage: '500 mg', is_active: true}]->(i);
MATCH (d:Drug {id: 'D002'}), (i:ActiveIngredient {name: 'Paracétamol'})
  MERGE (d)-[:CONTAINS {dosage: '1000 mg', is_active: true}]->(i);
MATCH (d:Drug {id: 'D003'}), (i:ActiveIngredient {name: 'Paracétamol'})
  MERGE (d)-[:CONTAINS {dosage: '500 mg', is_active: true}]->(i);
MATCH (d:Drug {id: 'D004'}), (i:ActiveIngredient {name: 'Ibuprofène'})
  MERGE (d)-[:CONTAINS {dosage: '400 mg', is_active: true}]->(i);
MATCH (d:Drug {id: 'D005'}), (i:ActiveIngredient {name: 'Acide acétylsalicylique'})
  MERGE (d)-[:CONTAINS {dosage: '100 mg', is_active: true}]->(i);
MATCH (d:Drug {id: 'D006'}), (i:ActiveIngredient {name: 'Atorvastatine'})
  MERGE (d)-[:CONTAINS {dosage: '20 mg', is_active: true}]->(i);
MATCH (d:Drug {id: 'D007'}), (i:ActiveIngredient {name: 'Ramipril'})
  MERGE (d)-[:CONTAINS {dosage: '5 mg', is_active: true}]->(i);
MATCH (d:Drug {id: 'D008'}), (i:ActiveIngredient {name: 'Metformine'})
  MERGE (d)-[:CONTAINS {dosage: '1000 mg', is_active: true}]->(i);
MATCH (d:Drug {id: 'D009'}), (i:ActiveIngredient {name: 'Sertraline'})
  MERGE (d)-[:CONTAINS {dosage: '50 mg', is_active: true}]->(i);
MATCH (d:Drug {id: 'D010'}), (i:ActiveIngredient {name: 'Diosmine'})
  MERGE (d)-[:CONTAINS {dosage: '500 mg', is_active: true}]->(i);
MATCH (d:Drug {id: 'D011'}), (i:ActiveIngredient {name: 'Amoxicilline'})
  MERGE (d)-[:CONTAINS {dosage: '500 mg', is_active: true}]->(i);

// BELONGS_TO : Drug → DrugClass
MATCH (d:Drug {id: 'D001'}), (c:DrugClass {name: 'Antalgique'}) MERGE (d)-[:BELONGS_TO]->(c);
MATCH (d:Drug {id: 'D002'}), (c:DrugClass {name: 'Antalgique'}) MERGE (d)-[:BELONGS_TO]->(c);
MATCH (d:Drug {id: 'D003'}), (c:DrugClass {name: 'Antalgique'}) MERGE (d)-[:BELONGS_TO]->(c);
MATCH (d:Drug {id: 'D004'}), (c:DrugClass {name: 'AINS'})       MERGE (d)-[:BELONGS_TO]->(c);
MATCH (d:Drug {id: 'D005'}), (c:DrugClass {name: 'AINS'})       MERGE (d)-[:BELONGS_TO]->(c);
MATCH (d:Drug {id: 'D006'}), (c:DrugClass {name: 'Hypolipémiant'}) MERGE (d)-[:BELONGS_TO]->(c);
MATCH (d:Drug {id: 'D007'}), (c:DrugClass {name: 'IEC'})        MERGE (d)-[:BELONGS_TO]->(c);
MATCH (d:Drug {id: 'D008'}), (c:DrugClass {name: 'Antidiabétique'}) MERGE (d)-[:BELONGS_TO]->(c);
MATCH (d:Drug {id: 'D009'}), (c:DrugClass {name: 'Antidépresseur'}) MERGE (d)-[:BELONGS_TO]->(c);
MATCH (d:Drug {id: 'D010'}), (c:DrugClass {name: 'Antalgique'}) MERGE (d)-[:BELONGS_TO]->(c);
MATCH (d:Drug {id: 'D011'}), (c:DrugClass {name: 'Pénicilline'}) MERGE (d)-[:BELONGS_TO]->(c);

// TREATS : Drug → Disease
MATCH (d:Drug {id: 'D001'}), (di:Disease {name: 'Douleur aiguë'})
  MERGE (d)-[:TREATS {rank: 1, evidence_level: 'Fort'}]->(di);
MATCH (d:Drug {id: 'D002'}), (di:Disease {name: 'Douleur aiguë'})
  MERGE (d)-[:TREATS {rank: 1, evidence_level: 'Fort'}]->(di);
MATCH (d:Drug {id: 'D003'}), (di:Disease {name: 'Douleur aiguë'})
  MERGE (d)-[:TREATS {rank: 1, evidence_level: 'Fort'}]->(di);
MATCH (d:Drug {id: 'D004'}), (di:Disease {name: 'Douleur aiguë'})
  MERGE (d)-[:TREATS {rank: 2, evidence_level: 'Fort'}]->(di);
MATCH (d:Drug {id: 'D005'}), (di:Disease {name: 'Douleur aiguë'})
  MERGE (d)-[:TREATS {rank: 3, evidence_level: 'Modéré'}]->(di);
MATCH (d:Drug {id: 'D006'}), (di:Disease {name: 'Hypercholestérolémie'})
  MERGE (d)-[:TREATS {rank: 1, evidence_level: 'Fort'}]->(di);
MATCH (d:Drug {id: 'D007'}), (di:Disease {name: 'Hypertension artérielle'})
  MERGE (d)-[:TREATS {rank: 1, evidence_level: 'Fort'}]->(di);
MATCH (d:Drug {id: 'D008'}), (di:Disease {name: 'Diabète de type 2'})
  MERGE (d)-[:TREATS {rank: 1, evidence_level: 'Fort'}]->(di);
MATCH (d:Drug {id: 'D009'}), (di:Disease {name: 'Dépression majeure'})
  MERGE (d)-[:TREATS {rank: 1, evidence_level: 'Fort'}]->(di);
MATCH (d:Drug {id: 'D009'}), (di:Disease {name: 'Trouble anxieux généralisé'})
  MERGE (d)-[:TREATS {rank: 2, evidence_level: 'Modéré'}]->(di);
MATCH (d:Drug {id: 'D010'}), (di:Disease {name: 'Œdème d\'origine veineuse'})
  MERGE (d)-[:TREATS {rank: 1, evidence_level: 'Modéré'}]->(di);
MATCH (d:Drug {id: 'D011'}), (di:Disease {name: 'Infection bactérienne'})
  MERGE (d)-[:TREATS {rank: 1, evidence_level: 'Fort'}]->(di);

// CAUSES : Drug → Effect
MATCH (d:Drug {id: 'D001'}), (e:Effect {id: 'E001'}) MERGE (d)-[:CAUSES {severity: 'Modéré', frequency: 'Peu fréquent (0.1-1%)'}]->(e);
MATCH (d:Drug {id: 'D001'}), (e:Effect {id: 'E003'}) MERGE (d)-[:CAUSES {severity: 'Grave', frequency: 'Rare (<0.1%) à dose élevée'}]->(e);
MATCH (d:Drug {id: 'D004'}), (e:Effect {id: 'E001'}) MERGE (d)-[:CAUSES {severity: 'Modéré', frequency: 'Fréquent (>1%)'}]->(e);
MATCH (d:Drug {id: 'D004'}), (e:Effect {id: 'E002'}) MERGE (d)-[:CAUSES {severity: 'Grave', frequency: 'Rare (<0.1%)'}]->(e);
MATCH (d:Drug {id: 'D004'}), (e:Effect {id: 'E010'}) MERGE (d)-[:CAUSES {severity: 'Modéré', frequency: 'Fréquent (>1%)'}]->(e);
MATCH (d:Drug {id: 'D005'}), (e:Effect {id: 'E002'}) MERGE (d)-[:CAUSES {severity: 'Grave', frequency: 'Rare (<0.1%)'}]->(e);
MATCH (d:Drug {id: 'D005'}), (e:Effect {id: 'E010'}) MERGE (d)-[:CAUSES {severity: 'Modéré', frequency: 'Fréquent (>1%)'}]->(e);
MATCH (d:Drug {id: 'D006'}), (e:Effect {id: 'E010'}) MERGE (d)-[:CAUSES {severity: 'Modéré', frequency: 'Fréquent (>1%)'}]->(e);
MATCH (d:Drug {id: 'D006'}), (e:Effect {id: 'E011'}) MERGE (d)-[:CAUSES {severity: 'Grave', frequency: 'Très rare (<0.01%)'}]->(e);
MATCH (d:Drug {id: 'D007'}), (e:Effect {id: 'E007'}) MERGE (d)-[:CAUSES {severity: 'Bénin', frequency: 'Fréquent (>1%)'}]->(e);
MATCH (d:Drug {id: 'D008'}), (e:Effect {id: 'E001'}) MERGE (d)-[:CAUSES {severity: 'Modéré', frequency: 'Fréquent (>1%)'}]->(e);
MATCH (d:Drug {id: 'D008'}), (e:Effect {id: 'E006'}) MERGE (d)-[:CAUSES {severity: 'Grave', frequency: 'Peu fréquent (0.1-1%)'}]->(e);
MATCH (d:Drug {id: 'D009'}), (e:Effect {id: 'E001'}) MERGE (d)-[:CAUSES {severity: 'Modéré', frequency: 'Fréquent (>1%)'}]->(e);
MATCH (d:Drug {id: 'D009'}), (e:Effect {id: 'E008'}) MERGE (d)-[:CAUSES {severity: 'Modéré', frequency: 'Fréquent (>1%)'}]->(e);
MATCH (d:Drug {id: 'D009'}), (e:Effect {id: 'E004'}) MERGE (d)-[:CAUSES {severity: 'Modéré', frequency: 'Peu fréquent (0.1-1%)'}]->(e);
MATCH (d:Drug {id: 'D011'}), (e:Effect {id: 'E005'}) MERGE (d)-[:CAUSES {severity: 'Modéré', frequency: 'Fréquent (>1%)'}]->(e);
MATCH (d:Drug {id: 'D011'}), (e:Effect {id: 'E009'}) MERGE (d)-[:CAUSES {severity: 'Grave', frequency: 'Rare (<0.1%)'}]->(e);

// HAS_CONTRAINDICATION : Drug → Contraindication
MATCH (d:Drug {id: 'D001'}), (c:Contraindication {id: 'CI001'}) MERGE (d)-[:HAS_CONTRAINDICATION {reason: 'Risque de toxicité hépatique', severity: 'Absolue'}]->(c);
MATCH (d:Drug {id: 'D004'}), (c:Contraindication {id: 'CI003'}) MERGE (d)-[:HAS_CONTRAINDICATION {reason: 'Toxicité fœtale', severity: 'Absolue'}]->(c);
MATCH (d:Drug {id: 'D004'}), (c:Contraindication {id: 'CI005'}) MERGE (d)-[:HAS_CONTRAINDICATION {reason: 'Risque hémorragique', severity: 'Absolue'}]->(c);
MATCH (d:Drug {id: 'D005'}), (c:Contraindication {id: 'CI005'}) MERGE (d)-[:HAS_CONTRAINDICATION {reason: 'Risque hémorragique', severity: 'Absolue'}]->(c);
MATCH (d:Drug {id: 'D005'}), (c:Contraindication {id: 'CI003'}) MERGE (d)-[:HAS_CONTRAINDICATION {reason: 'Toxicité fœtale', severity: 'Absolue'}]->(c);
MATCH (d:Drug {id: 'D005'}), (c:Contraindication {id: 'CI006'}) MERGE (d)-[:HAS_CONTRAINDICATION {reason: 'Risque hémorragique cérébral', severity: 'Relative'}]->(c);
MATCH (d:Drug {id: 'D011'}), (c:Contraindication {id: 'CI004'}) MERGE (d)-[:HAS_CONTRAINDICATION {reason: 'Allergie croisée', severity: 'Absolue'}]->(c);
MATCH (d:Drug {id: 'D008'}), (c:Contraindication {id: 'CI002'}) MERGE (d)-[:HAS_CONTRAINDICATION {reason: 'Risque d\'acidose lactique', severity: 'Absolue'}]->(c);
MATCH (d:Drug {id: 'D007'}), (c:Contraindication {id: 'CI003'}) MERGE (d)-[:HAS_CONTRAINDICATION {reason: 'Tératogénicité', severity: 'Absolue'}]->(c);

// HAS_MECHANISM : ActiveIngredient → DrugClass
MATCH (i:ActiveIngredient {name: 'Paracétamol'}),              (c:DrugClass {name: 'Antalgique'}) MERGE (i)-[:HAS_MECHANISM]->(c);
MATCH (i:ActiveIngredient {name: 'Ibuprofène'}),               (c:DrugClass {name: 'AINS'})       MERGE (i)-[:HAS_MECHANISM]->(c);
MATCH (i:ActiveIngredient {name: 'Acide acétylsalicylique'}),  (c:DrugClass {name: 'AINS'})       MERGE (i)-[:HAS_MECHANISM]->(c);
MATCH (i:ActiveIngredient {name: 'Atorvastatine'}),            (c:DrugClass {name: 'Hypolipémiant'}) MERGE (i)-[:HAS_MECHANISM]->(c);
MATCH (i:ActiveIngredient {name: 'Ramipril'}),                 (c:DrugClass {name: 'IEC'})        MERGE (i)-[:HAS_MECHANISM]->(c);
MATCH (i:ActiveIngredient {name: 'Metformine'}),               (c:DrugClass {name: 'Antidiabétique'}) MERGE (i)-[:HAS_MECHANISM]->(c);
MATCH (i:ActiveIngredient {name: 'Sertraline'}),               (c:DrugClass {name: 'Antidépresseur'}) MERGE (i)-[:HAS_MECHANISM]->(c);
MATCH (i:ActiveIngredient {name: 'Amoxicilline'}),             (c:DrugClass {name: 'Pénicilline'}) MERGE (i)-[:HAS_MECHANISM]->(c);

// INTERACTS_WITH : Drug → Drug (interactions médicamenteuses)
// Doliprane + Advil → risque de surdosage si pris ensemble (même indication)
MATCH (d1:Drug {id: 'D001'}), (d2:Drug {id: 'D004'})
  MERGE (d1)-[r:INTERACTS_WITH {severity: 'Modérée', mechanism: 'Additif', recommendation: 'Éviter association, risque de surdosage en antalgique', description: 'Potentialisation des effets antalgiques sans bénéfice démontré, risque accru d\'effets indésirables', risk_score: 50}]-(d2);

// Advil + Aspirine → risque hémorragique majoré
MATCH (d1:Drug {id: 'D004'}), (d2:Drug {id: 'D005'})
  MERGE (d1)-[r:INTERACTS_WITH {severity: 'Grave', mechanism: 'Pharmacodynamique — inhibition COX additive', recommendation: 'Contre-indiqué — risque hémorragique élevé', description: 'L\'ibuprofène antagonise l\'effet antiagrégant de l\'aspirine et additionne le risque digestif', risk_score: 85}]-(d2);

// Tahor + Triatec → interaction signalée (statine + IEC, généralement safe)
MATCH (d1:Drug {id: 'D006'}), (d2:Drug {id: 'D007'})
  MERGE (d1)-[r:INTERACTS_WITH {severity: 'Mineure', mechanism: 'Pharmacocinétique', recommendation: 'Surveillance standard, association fréquente', description: 'Interaction cliniquement non significative chez la plupart des patients', risk_score: 15}]-(d2);

// Tahor + Aspirine → risque de saignement majoré
MATCH (d1:Drug {id: 'D006'}), (d2:Drug {id: 'D005'})
  MERGE (d1)-[r:INTERACTS_WITH {severity: 'Modérée', mechanism: 'Pharmacodynamique', recommendation: 'Surveillance des signes hémorragiques', description: 'Majoration modérée du risque de saignement sous statine + antiagrégant', risk_score: 40}]-(d2);

// Metformine + IEC (Triatec) → risk d'hypoglycémie majorée
MATCH (d1:Drug {id: 'D008'}), (d2:Drug {id: 'D007'})
  MERGE (d1)-[r:INTERACTS_WITH {severity: 'Modérée', mechanism: 'Pharmacodynamique', recommendation: 'Surveillance glycémique renforcée', description: 'Majoration de l\'effet hypoglycémiant de la metformine par l\'IEC', risk_score: 45}]-(d2);

// Zoloft + Aspirine → risque hémorragique majoré
MATCH (d1:Drug {id: 'D009'}), (d2:Drug {id: 'D005'})
  MERGE (d1)-[r:INTERACTS_WITH {severity: 'Grave', mechanism: 'Pharmacodynamique — inhibition recapture sérotonine plaquettaire + antiagrégant', recommendation: 'Prudence, surveillance clinique', description: 'Majoration du risque hémorragique par inhibition de la recapture de sérotonine plaquettaire', risk_score: 70}]-(d2);

// Zoloft + Advil → risque hémorragique
MATCH (d1:Drug {id: 'D009'}), (d2:Drug {id: 'D004'})
  MERGE (d1)-[r:INTERACTS_WITH {severity: 'Modérée', mechanism: 'Pharmacodynamique', recommendation: 'Prudence chez les patients à risque hémorragique', description: 'Risque hémor肋ique augmenté par l\'association ISRS + AINS', risk_score: 55}]-(d2);

// Doliprane + Metformine — pas d'interaction significative
MATCH (d1:Drug {id: 'D001'}), (d2:Drug {id: 'D008'})
  MERGE (d1)-[r:INTERACTS_WITH {severity: 'Mineure', mechanism: 'Aucun connu', recommendation: 'Association possible sans risque', description: 'Aucune interaction cliniquement significative documentée', risk_score: 5}]-(d2);

// Amoxicilline + Advil → pas d'interaction
MATCH (d1:Drug {id: 'D011'}), (d2:Drug {id: 'D004'})
  MERGE (d1)-[r:INTERACTS_WITH {severity: 'Mineure', mechanism: 'Aucun connu', recommendation: 'Association possible', description: 'Aucune interaction cliniquement significative documentée', risk_score: 5}]-(d2);

// ─── STATISTIQUES DE VÉRIFICATION ────────────────────────────────────────────

MATCH (d:Drug) WITH count(d) AS drugs
MATCH (i:ActiveIngredient) WITH drugs, count(i) AS ingredients
MATCH (di:Disease) WITH drugs, ingredients, count(di) AS diseases
MATCH (ef:Effect) WITH drugs, ingredients, diseases, count(ef) AS effects
MATCH (ci:Contraindication) WITH drugs, ingredients, diseases, effects, count(ci) AS contraindications
MATCH (dc:DrugClass) WITH drugs, ingredients, diseases, effects, contraindications, count(dc) AS drug_classes
MATCH ()-[r:INTERACTS_WITH]-() WITH drugs, ingredients, diseases, effects, contraindications, drug_classes, count(r) AS interactions
MATCH ()-[r]->() WITH drugs, ingredients, diseases, effects, contraindications, drug_classes, interactions, count(r) AS total_relationships
RETURN '✅ Données exemples chargées' AS status,
       drugs, ingredients, diseases, effects,
       contraindications, drug_classes, interactions, total_relationships;
