"""
Lecture des attributs administratifs issus du fichier maître de l'ANSM.

Ces dix champs sont alimentés par la réconciliation de synchronisation
(`sync/reconciliation.py`, phase P8-1) et couvrent 99,1 % des fiches — les
manquantes étant les médicaments absents du catalogue officiel.

Le module ne fait que traduire ces valeurs brutes en éléments d'affichage. Il
n'écrit rien et ne devine rien : un champ absent produit une absence, jamais
une valeur par défaut qui laisserait croire à une information vérifiée.

Deux constats de la phase P8-1 déterminent ce qui est affiché :

- `statut_bdm = "Warning disponibilité"` est **strictement équivalent** à
  `commercialisation = "Non commercialisée"` — mesuré sur 1 883 fiches, sans
  une seule exception. Les afficher tous deux serait redondant, seul le second
  est retenu. La valeur `Alerte` (10 fiches) porte en revanche une information
  que la commercialisation ne dit pas, et remonte donc séparément.

- La forme et le titulaire du dump sont plus pauvres que ceux de la notice
  (« Gel buccal » y devient « gel »). Ils vivent dans `forme_canonique` et
  `titulaire_amm` et ne sont affichés qu'en donnée réglementaire, jamais en
  remplacement des valeurs descriptives du bandeau.
"""

AMM_ACTIVE = 'Autorisation active'
NON_COMMERCIALISE = 'Non commercialisée'

# Les dix attributs du fichier maître, plus le code CIS.
CATALOGUE_FIELDS = (
    'cis', 'statut_amm', 'commercialisation', 'date_amm', 'voies_administration',
    'procedure_amm', 'autorisation_europeenne', 'statut_bdm',
    'surveillance_renforcee', 'forme_canonique', 'titulaire_amm',
)


def merge_catalogue(medicine, french_collection):
    """
    Complète une fiche traduite avec les attributs réglementaires du français.

    `medicines_en` est un cache de traduction : la synchronisation n'y écrit
    pas, et ses 90 fiches ne portent donc aucun de ces champs. Les recopier à
    l'écriture créerait une seconde copie à maintenir, qui divergerait dès
    qu'un médicament passerait en rupture. On les lit donc à l'affichage, ce
    qui garantit un statut toujours à jour.

    La jointure se fait sur l'URL : les deux collections ont des `_id`
    distincts — vérifié, 0 correspondance sur 90 par identifiant, 90 sur 90
    par URL.

    Modifie et retourne `medicine`.
    """
    if not medicine or french_collection is None:
        return medicine
    if any(field in medicine for field in CATALOGUE_FIELDS[1:]):
        return medicine                      # déjà servie depuis `medicines`
    url = medicine.get('url')
    if not url:
        return medicine
    try:
        source = french_collection.find_one(
            {'url': url}, {field: 1 for field in CATALOGUE_FIELDS})
    except Exception:                                       # noqa: BLE001
        return medicine
    for field in CATALOGUE_FIELDS:
        if source and field in source:
            medicine[field] = source[field]
    return medicine


def _clean(value):
    """Retourne une chaîne non vide, ou None. Les champs du dump valent '' quand ils sont sans objet."""
    text = (value or '').strip() if isinstance(value, str) else value
    return text or None


def safety_flags(medicine, lang='fr'):
    """
    Signaux de sécurité à porter en tête de fiche, du plus grave au moins grave.

    Retourne une liste de dicts : `level` (critical | warning | info), `icon`,
    `label`, `detail`. Une liste vide signifie qu'il n'y a rien à signaler —
    le gabarit n'affiche alors aucun bandeau plutôt qu'un bandeau vert, qui
    n'apprendrait rien et diluerait les vrais signaux.
    """
    from ui_labels import libelle as _t

    flags = []

    if _clean(medicine.get('statut_bdm')) == 'Alerte':
        flags.append({
            'level': 'critical',
            'icon': 'fa-triangle-exclamation',
            'label': _t('Safety alert', 'Alerte sanitaire', lang),
            'detail': _t('This medicine is subject to an alert published by the ANSM.',
                         "Ce médicament fait l'objet d'une alerte publiée par l'ANSM.",
                         lang),
        })

    statut = _clean(medicine.get('statut_amm'))
    if statut and statut != AMM_ACTIVE:
        # « Autorisation abrogée », « suspendue », « retirée », « archivée ».
        etat = _translate(statut.replace('Autorisation ', ''),
                          _table('statuts', lang))
        flags.append({
            'level': 'critical' if 'suspend' in statut.lower() else 'warning',
            'icon': 'fa-ban',
            'label': '%s : %s' % (_t('Marketing authorisation', 'AMM', lang), etat),
            'detail': _t('This medicine no longer holds an active marketing '
                         'authorisation in France.',
                         "Ce médicament ne dispose plus d'une autorisation de "
                         "mise sur le marché active en France.", lang),
        })

    if _clean(medicine.get('commercialisation')) == NON_COMMERCIALISE:
        flags.append({
            'level': 'warning',
            'icon': 'fa-box-open',
            'label': _t('Not marketed', 'Non commercialisé', lang),
            'detail': _t('Not currently distributed in French pharmacies. '
                         'Ask your pharmacist about alternatives.',
                         "Non distribué en pharmacie actuellement. "
                         "Demandez conseil à votre pharmacien sur les alternatives.",
                         lang),
        })

    if _clean(medicine.get('surveillance_renforcee')) == 'Oui':
        flags.append({
            'level': 'info',
            'icon': 'fa-eye',
            'label': _t('Additional monitoring', 'Surveillance renforcée', lang),
            'detail': _t('Subject to additional monitoring across the EU. Report any '
                         'side effect to your doctor or pharmacist.',
                         "Soumis à une surveillance renforcée dans l'Union européenne. "
                         "Signalez tout effet indésirable à votre médecin ou pharmacien.",
                         lang),
        })

    return flags


# ── Vocabulaires contrôlés ────────────────────────────────────────────
#
# Le fichier maître n'existe qu'en français. Deux de ses champs tirent leurs
# valeurs d'une nomenclature fermée et peuvent donc être traduits par simple
# correspondance, sans appel à un service externe : 5 procédures et 64 voies
# d'administration élémentaires, relevées sur l'intégralité de la base.
#
# La forme pharmaceutique en compte 319, dont des entrées tronquées à la
# source (« capsule molle ou »). Les traduire à la main serait deviner : elle
# reste affichée telle quelle, sous un libellé qui indique sa provenance.

PROCEDURES_EN = {
    'Procédure nationale': 'National procedure',
    'Procédure centralisée': 'Centralised procedure',
    'Procédure décentralisée': 'Decentralised procedure',
    'Procédure de reconnaissance mutuelle': 'Mutual recognition procedure',
    'Enreg phyto (Proc. Nat.)': 'Herbal registration (national procedure)',
    'Enreg phyto (Proc. Dec.)': 'Herbal registration (decentralised procedure)',
    'Enreg homéo (Proc. Nat.)': 'Homeopathic registration (national procedure)',
    'Enreg homéo (Proc. Dec.)': 'Homeopathic registration (decentralised procedure)',
}

ROUTES_EN = {
    'auriculaire': 'auricular', 'cutanée': 'cutaneous', 'dentaire': 'dental',
    'endocervicale': 'endocervical', 'endosinusale': 'endosinusial',
    'endotrachéobronchique': 'endotracheobronchial', 'gastrique': 'gastric',
    'gastro-entérale': 'gastroenteral', 'gingivale': 'gingival',
    'hémodialyse': 'haemodialysis', 'hémofiltration': 'haemofiltration',
    'infiltration': 'infiltration', 'inhalée': 'inhalation',
    'intestinale': 'intestinal', 'intra-murale': 'intramural',
    'intra-utérine': 'intrauterine', 'intraarticulaire': 'intra-articular',
    'intraartérielle': 'intra-arterial', 'intracamérulaire': 'intracameral',
    'intracaverneuse': 'intracavernous', 'intracervicale': 'intracervical',
    'intracholangiopancréatique': 'intracholangiopancreatic',
    'intracisternale': 'intracisternal', 'intracoronaire': 'intracoronary',
    'intracérébroventriculaire': 'intracerebroventricular',
    'intradermique': 'intradermal', 'intradurale': 'intradural',
    'intraglandulaire': 'intraglandular', 'intralymphatique': 'intralymphatic',
    'intralésionnelle': 'intralesional', 'intramusculaire': 'intramuscular',
    'intraoculaire': 'intraocular', 'intraosseuse': 'intraosseous',
    'intrapleurale': 'intrapleural', 'intrapéricardiaque': 'intrapericardial',
    'intrapéritonéale': 'intraperitoneal', 'intraséreuse': 'intraserosal',
    'intrathécale': 'intrathecal', 'intratumorale': 'intratumoral',
    'intraveineuse': 'intravenous', 'intravitréenne': 'intravitreal',
    'intravésicale': 'intravesical', 'laryngopharyngée': 'laryngopharyngeal',
    'nasale': 'nasal', 'ophtalmique': 'ophthalmic', 'orale': 'oral',
    'péri-aréolaire': 'periareolar', 'périarticulaire': 'periarticular',
    'péribulbaire': 'peribulbar', 'péridurale': 'epidural',
    'périneurale': 'perineural', 'péritumorale': 'peritumoral',
    'rectale': 'rectal', 'sous-conjonctivale': 'subconjunctival',
    'sous-cutanée': 'subcutaneous', 'sous-muqueuse': 'submucosal',
    'sublinguale': 'sublingual', 'transdermique': 'transdermal',
    'urétrale': 'urethral', 'vaginale': 'vaginal',
    'voie buccale autre': 'other buccal route',
    'voie extracorporelle autre': 'other extracorporeal route',
    'voie parentérale autre': 'other parenteral route',
    'épilésionnelle': 'epilesional',
}


PROCEDURES_AR = {
    'Procédure nationale': 'إجراء وطني',
    'Procédure centralisée': 'إجراء مركزي',
    'Procédure décentralisée': 'إجراء لامركزي',
    'Procédure de reconnaissance mutuelle': 'إجراء الاعتراف المتبادل',
    'Enreg phyto (Proc. Nat.)': 'تسجيل دواء نباتي (إجراء وطني)',
    'Enreg phyto (Proc. Dec.)': 'تسجيل دواء نباتي (إجراء لامركزي)',
    'Enreg homéo (Proc. Nat.)': 'تسجيل دواء مثلي (إجراء وطني)',
    'Enreg homéo (Proc. Dec.)': 'تسجيل دواء مثلي (إجراء لامركزي)',
}

ROUTES_AR = {
    'auriculaire': 'أذني', 'cutanée': 'جلدي', 'dentaire': 'سنّي',
    'endocervicale': 'داخل عنق الرحم', 'endosinusale': 'داخل الجيوب',
    'endotrachéobronchique': 'داخل الرغامى والقصبات', 'gastrique': 'معدي',
    'gastro-entérale': 'معدي معوي', 'gingivale': 'لثوي',
    'hémodialyse': 'الديال الدموي', 'hémofiltration': 'الترشيح الدموي',
    'infiltration': 'ارتشاح موضعي', 'inhalée': 'استنشاقي',
    'intestinale': 'معوي', 'intra-murale': 'داخل الجدار',
    'intra-utérine': 'داخل الرحم', 'intraarticulaire': 'داخل المفصل',
    'intraartérielle': 'داخل الشريان', 'intracamérulaire': 'داخل حجرة العين',
    'intracaverneuse': 'داخل الجسم الكهفي', 'intracervicale': 'داخل عنق الرحم',
    'intracholangiopancréatique': 'داخل القنوات الصفراوية والبنكرياسية',
    'intracisternale': 'داخل الصهريج', 'intracoronaire': 'داخل الشريان التاجي',
    'intracérébroventriculaire': 'داخل بطينات الدماغ',
    'intradermique': 'داخل الأدمة', 'intradurale': 'داخل الجافية',
    'intraglandulaire': 'داخل الغدة', 'intralymphatique': 'داخل الأوعية اللمفية',
    'intralésionnelle': 'داخل الآفة', 'intramusculaire': 'عضلي',
    'intraoculaire': 'داخل العين', 'intraosseuse': 'داخل العظم',
    'intrapleurale': 'داخل الجنبة', 'intrapéricardiaque': 'داخل التامور',
    'intrapéritonéale': 'داخل الصفاق', 'intraséreuse': 'داخل الغشاء المصلي',
    'intrathécale': 'داخل القِراب', 'intratumorale': 'داخل الورم',
    'intraveineuse': 'وريدي', 'intravitréenne': 'داخل الجسم الزجاجي',
    'intravésicale': 'داخل المثانة', 'laryngopharyngée': 'حنجري بلعومي',
    'nasale': 'أنفي', 'ophtalmique': 'عيني', 'orale': 'فموي',
    'péri-aréolaire': 'حول هالة الثدي', 'périarticulaire': 'حول المفصل',
    'péribulbaire': 'حول مقلة العين', 'péridurale': 'فوق الجافية',
    'périneurale': 'حول العصب', 'péritumorale': 'حول الورم',
    'rectale': 'شرجي', 'sous-conjonctivale': 'تحت الملتحمة',
    'sous-cutanée': 'تحت الجلد', 'sous-muqueuse': 'تحت المخاطية',
    'sublinguale': 'تحت اللسان', 'transdermique': 'عبر الجلد',
    'urétrale': 'إحليلي', 'vaginale': 'مهبلي',
    'voie buccale autre': 'طريق فموي آخر',
    'voie extracorporelle autre': 'طريق خارج الجسم آخر',
    'voie parentérale autre': 'طريق حقني آخر',
    'épilésionnelle': 'فوق الآفة',
}

# Qualificatif du statut d'AMM, tel qu'il apparaît dans le bandeau de sécurité.
# Il restait en français en arabe — « ترخيص التسويق : suspendue » — moitié
# traduit, ce qui est le pire des deux.
STATUTS_AR = {
    'active': 'ساري المفعول',
    'abrogée': 'مُلغى',
    'suspendue': 'موقوف',
    'retirée': 'مسحوب',
    'archivée': 'مؤرشف',
}

STATUTS_EN = {
    'active': 'active',
    'abrogée': 'revoked',
    'suspendue': 'suspended',
    'retirée': 'withdrawn',
    'archivée': 'archived',
}

# Vocabulaire par langue. Le français est absent : c'est la langue des valeurs
# d'origine, aucune correspondance n'est nécessaire.
VOCABULAIRES = {
    'en': {'procedures': PROCEDURES_EN, 'routes': ROUTES_EN, 'statuts': STATUTS_EN},
    'ar': {'procedures': PROCEDURES_AR, 'routes': ROUTES_AR, 'statuts': STATUTS_AR},
}


def _table(nature, lang):
    """
    Table de correspondance d'un vocabulaire dans une langue, ou None.

    None signifie « pas de table » : l'appelant laisse alors la valeur
    française d'origine, plutôt que d'en inventer une.
    """
    return (VOCABULAIRES.get(lang) or {}).get(nature)


def _translate(value, table):
    """Traduit par correspondance. Une valeur inconnue est rendue inchangée."""
    if not table:
        return value
    return table.get(value, value)


# Attributs administratifs : champ en base, libellé français, libellé anglais.
FACTS = (
    ('cis', 'Code CIS', 'CIS code'),
    ('date_amm', "Date d'AMM", 'Authorisation date'),
    ('procedure_amm', "Procédure d'AMM", 'Authorisation procedure'),
    ('autorisation_europeenne', 'Numéro européen', 'European number'),
    ('voies_administration', "Voie(s) d'administration", 'Route(s) of administration'),
    ('forme_canonique', 'Forme (nomenclature ANSM)', 'Form (ANSM nomenclature)'),
    ('titulaire_amm', "Titulaire de l'AMM", 'Authorisation holder'),
)


def regulatory_facts(medicine, lang='fr'):
    """
    Données administratives à présenter en tableau. Les champs vides sont omis.

    Les voies d'administration sont séparées par des points-virgules dans le
    fichier officiel — « cutanée;orale;sublinguale » — et remises en forme ici.
    """
    from ui_labels import libelle as _t

    rows = []
    for field, label_fr, label_en in FACTS:
        value = _clean(medicine.get(field))
        if not value:
            continue
        if field == 'voies_administration':
            parts = [part.strip() for part in value.split(';') if part.strip()]
            parts = [_translate(part, _table('routes', lang)) for part in parts]
            value = ', '.join(parts)
        elif field == 'procedure_amm':
            value = _translate(value, _table('procedures', lang))
        rows.append({'label': _t(label_en, label_fr, lang), 'value': value})
    return rows


def availability_badge(medicine, lang='fr'):
    """
    Pastille compacte pour les listes de résultats, ou None si rien à signaler.

    Volontairement réduite à un seul signal : dans une liste, un empilement de
    pastilles coûterait en lisibilité ce qu'il apporterait en exhaustivité. La
    fiche détaillée porte l'information complète.
    """
    flags = safety_flags(medicine, lang)
    return flags[0] if flags else None
