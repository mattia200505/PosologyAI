# -*- coding: utf-8 -*-
"""
Libellés d'interface rendus côté serveur.

Les gabarits écrivaient `{{ 'Dosage' if lang == 'en' else 'Posologie' }}`.
Cette forme ne connaît que deux langues : pour toute autre, elle rend le
français. La fiche d'un médicament restait donc à moitié en français pour un
lecteur arabophone, alors même que son contenu était traduit.

`libelle()` conserve le couple anglais/français et y ajoute les langues
supplémentaires par correspondance sur la chaîne anglaise, qui sert de clé.
Une clé absente retombe sur l'anglais puis le français : ajouter une langue ne
peut donc pas produire de trou dans la page.
"""

# Clé : la chaîne anglaise telle qu'elle figure dans les gabarits.
AR = {
    # ── Navigation et cartouches ──────────────────────────────────────
    'AI Summary': 'ملخّص بالذكاء الاصطناعي',
    'Medical Synthesis': 'الخلاصة الطبية',
    'Composition': 'التركيب',
    'Interactions': 'التفاعلات',
    'Knowledge Graph': 'رسم المعرفة',
    'Comments': 'التعليقات',
    'Technical Data': 'بيانات تقنية',
    'Essentials': 'معلومات أساسية',
    'Essential Information': 'معلومات أساسية',
    'Alternatives': 'بدائل',
    'Sources': 'المصادر',
    'Medical Sources': 'المصادر الطبية',
    'Drug Interactions': 'التفاعلات الدوائية',
    'Regulatory status': 'الوضع التنظيمي',
    'Regulatory information': 'معلومات تنظيمية',
    'Molecular Data': 'بيانات جزيئية',
    'Results': 'النتائج',

    # ── Métadonnées de la notice ──────────────────────────────────────
    'Notice updated:': 'تاريخ تحديث النشرة:',
    'Data collected:': 'تاريخ جمع البيانات:',
    'French Public Medication Database': 'قاعدة البيانات العامة الفرنسية للأدوية',
    'Source of this content': 'مصدر هذا المحتوى',
    'Source(s) of this content': 'مصادر هذا المحتوى',
    'Source URL': 'رابط المصدر',
    'Language': 'اللغة',

    # ── Résumé par IA ─────────────────────────────────────────────────
    'Model used:': 'النموذج المستخدم:',
    'Generating summary...': 'جارٍ إنشاء الملخّص...',
    'Summary': 'ملخّص',

    # ── Rubriques cliniques ───────────────────────────────────────────
    'Indications': 'دواعي الاستعمال',
    'Indication': 'دواعي الاستعمال',
    'Indications:': 'دواعي الاستعمال:',
    'Contraindications': 'موانع الاستعمال',
    'Precautions': 'الاحتياطات',
    'Molecular structure': 'التركيب الجزيئي',
    'Molecular formula': 'الصيغة الجزيئية',
    'Molecular weight': 'الكتلة الجزيئية',
    'Source: DrugBank calculated properties.': 'المصدر: الخصائص المحسوبة من DrugBank.',
    'No topological structure: this is a biological molecule (antibody, vaccine, protein), for which a structural formula has no meaning.':
        'لا يوجد تركيب بنائي: هذا دواء بيولوجي — جسم مضاد أو لقاح أو بروتين — لا معنى للصيغة البنائية بشأنه.',
    'Structure too large to be drawn legibly at this scale — this molecule is a peptide or an oligonucleotide. The SMILES above describes it in full.':
        'البنية أوسع من أن تُرسم بوضوح بهذا المقياس — هذا الجزيء ببتيد أو قليل النوكليوتيد. ورمز SMILES أعلاه يصفه كاملًا.',
    # ── Fiches issues de l'EMA, sans RCP ──────────────────────────────
    'Monograph not available here': 'الملخّص غير متوفّر في هذه الصفحة',
    'Monograph unavailable': 'الملخّص غير متوفّر',
    'What this page does not show': 'ما لا تعرضه هذه الصفحة',
    'This medicine is authorised through the European centralised procedure. Its summary of product characteristics is published by the EMA as a separate PDF, which this catalogue does not import. Indications, posology, contraindications and warnings therefore do not appear on this page — their absence here says nothing about the medicine.':
        'رُخِّص هذا الدواء عبر الإجراء المركزي الأوروبي. تنشر الوكالة الأوروبية للأدوية ملخّص خصائص المنتج في ملف PDF منفصل لا يستورده هذا الفهرس. لذلك لا تظهر في هذه الصفحة دواعي الاستعمال ولا الجرعات ولا موانع الاستعمال ولا التحذيرات — وغيابها هنا لا يقول شيئًا عن الدواء.',
    'The interactions listed below come from DrugBank and are unaffected by this limitation.':
        'التفاعلات المذكورة أدناه مصدرها DrugBank ولا يشملها هذا القصور.',
    'Read the official EMA monograph': 'الاطّلاع على الملخّص الرسمي على موقع الوكالة الأوروبية للأدوية',
    'European Medicines Agency — authoritative source for this medicine.':
        'الوكالة الأوروبية للأدوية — المرجع المعتمد لهذا الدواء.',
    # Le libellé a été étendu aux mises en garde, que la convention du domaine
    # présente avec les précautions et non parmi les données techniques.
    'Precautions and warnings': 'الاحتياطات والتحذيرات',
    'Dosage': 'الجرعة',
    'Dosages': 'الجرعات',
    'Dosage(s)': 'الجرعة (الجرعات)',
    'Side Effects': 'الآثار الجانبية',
    'Form': 'الشكل',
    'Pharmaceutical Form': 'الشكل الصيدلاني',
    'Active Substance(s)': 'المادة (المواد) الفعّالة',
    'Active Ingredient': 'المادة الفعّالة',
    'Laboratory': 'المختبر',
    'Drug': 'دواء',
    'Alternative': 'بديل',
    'Interaction': 'تفاعل',
    'FAERS Effect': 'أثر مسجَّل في FAERS',

    # ── Données DrugBank ──────────────────────────────────────────────
    'Description': 'الوصف',
    'Pharmacodynamics': 'الديناميكا الدوائية',
    'Pharmacokinetics': 'الحركية الدوائية',
    'Half-life': 'عمر النصف',
    'Protein Binding': 'الارتباط بالبروتين',
    'Metabolism': 'الاستقلاب',
    'Absorption': 'الامتصاص',
    'Elimination': 'الإطراح',
    'Clearance': 'التصفية',
    'Toxicity': 'السمّية',
    'ATC Codes': 'رموز ATC',
    'Classification': 'التصنيف',
    'Groups': 'المجموعات',
    'Go to DrugBank': 'الانتقال إلى DrugBank',
    'French database available': 'قاعدة بيانات فرنسية متاحة',
    'Efficacy:': 'الفعالية:',
    'Safety:': 'السلامة:',

    # ── États et actions ──────────────────────────────────────────────
    'Load more': 'عرض المزيد',
    'Show more': 'عرض المزيد',
    'View details': 'عرض التفاصيل',
    'Loading interactions...': 'جارٍ تحميل التفاعلات...',
    'Loading alternatives...': 'جارٍ تحميل البدائل...',
    'Loading sources...': 'جارٍ تحميل المصادر...',
    'Loading graph...': 'جارٍ تحميل الرسم...',
    'This section has no content.': 'لا يتضمّن هذا القسم أي محتوى.',
    'No general information available.': 'لا تتوفر معلومات عامة.',
    'No results found.': 'لا توجد نتائج.',
    'Not specified': 'غير محدَّد',
    'Date not available': 'التاريخ غير متوفّر',
    'No comments yet.': 'لا توجد تعليقات بعد.',

    # ── Commentaires ──────────────────────────────────────────────────
    'Add a comment': 'إضافة تعليق',
    'Rating': 'التقييم',
    'Share your thoughts about this medication...': 'شارك رأيك في هذا الدواء...',
    'Submit': 'إرسال',
    'Log in': 'تسجيل الدخول',
    'to leave a comment.': 'لترك تعليق.',
    'comment(s)': 'تعليق (تعليقات)',
    'Edit': 'تعديل',
    'Delete': 'حذف',
    'Delete this comment?': 'هل تريد حذف هذا التعليق؟',
    'Save': 'حفظ',
    'Cancel': 'إلغاء',

    # ── Textes longs ──────────────────────────────────────────────────
    'Other medications with the same active ingredient(s).':
        'أدوية أخرى تحتوي على المادة الفعّالة نفسها.',
    # Le thésaurus ANSM des interactions n'est plus opposable : mise à jour
    # arrêtée depuis septembre 2023, consultable jusqu'au 15 juin 2027. Seuls
    # les RCP et les notices font désormais foi.
    'Verify in the official SmPC (French public medicines database)':
        'راجع ملخّص خصائص المنتج الرسمي (قاعدة البيانات العامة الفرنسية للأدوية)',
    'ANSM interactions thesaurus (archived, no longer updated)':
        'دليل التفاعلات الدوائية الصادر عن ANSM (مؤرشف، لم يعد يُحدَّث)',
    'Summaries of product characteristics and patient leaflets are the only binding official references. The ANSM interactions thesaurus has not been updated since September 2023 and is no longer binding; it remains available for consultation until 15 June 2027.':
        'ملخّصات خصائص المنتج والنشرات الدوائية هي المراجع الرسمية المُلزِمة الوحيدة. لم يُحدَّث دليل التفاعلات الدوائية الصادر عن ANSM منذ سبتمبر 2023 ولم يعد مُلزِمًا؛ ويبقى متاحًا للاطّلاع حتى 15 يونيو 2027.',
    'Visual exploration of Neo4j relationships: active ingredients, interactions, and FAERS adverse events.':
        'استكشاف بصري لعلاقات Neo4j: المواد الفعّالة والتفاعلات والآثار الضائرة المسجَّلة في FAERS.',
    'Data from Neo4j (interactions, ingredients, FAERS adverse events)':
        'بيانات مستخرجة من Neo4j (التفاعلات والمواد الفعّالة والآثار الضائرة FAERS)',
    'See dedicated section below for full DrugBank data':
        'راجع القسم المخصّص أدناه للاطّلاع على بيانات DrugBank كاملة',
    'Enriched with DrugBank data — confidence score':
        'مُثرى ببيانات DrugBank — درجة الثقة',
    'Mechanism of Action': 'آلية التأثير',

    # ── Bandeau de statut réglementaire (regulatory.py) ───────────────
    # Affichage de sécurité : il ne doit jamais retomber dans une langue
    # que le lecteur n'a pas demandée.
    'Safety alert': 'تنبيه سلامة',
    'This medicine is subject to an alert published by the ANSM.':
        'هذا الدواء موضوع تنبيه صادر عن الوكالة الفرنسية للأدوية ANSM.',
    'Not marketed': 'غير مسوَّق',
    'Not currently distributed in French pharmacies. Ask your pharmacist about alternatives.':
        'غير متوفّر حاليًا في الصيدليات الفرنسية. استشر الصيدلي بشأن البدائل.',
    'Additional monitoring': 'مراقبة مُعزَّزة',
    'Subject to additional monitoring across the EU. Report any side effect to your doctor or pharmacist.':
        'يخضع لمراقبة مُعزَّزة في الاتحاد الأوروبي. أبلغ طبيبك أو الصيدلي بأي أثر جانبي.',
    'This medicine no longer holds an active marketing authorisation in France.':
        'لم يعد هذا الدواء يحمل ترخيصًا ساري المفعول للتسويق في فرنسا.',
    'Marketing authorisation': 'ترخيص التسويق',

    # Données réglementaires
    'CIS code': 'رمز CIS',
    'Authorisation date': 'تاريخ الترخيص',
    'Authorisation procedure': 'إجراء الترخيص',
    'European number': 'الرقم الأوروبي',
    'Route(s) of administration': 'طريق (طرق) الإعطاء',
    'Form (ANSM nomenclature)': 'الشكل (تسمية ANSM)',
    'Authorisation holder': 'صاحب الترخيص',
    'Remove from favorites': 'إزالة من المفضّلة',
    'Add to favorites': 'إضافة إلى المفضّلة',
    'posology_warning':
        'هذه الجرعة هي النظام المعتاد للبالغين، في غياب قصور كلوي أو كبدي. '
        'وقد تستدعي التعديل لدى الأطفال أو كبار السنّ أو المصابين بأمراض '
        'الكلى أو الكبد — والطبيب وحده يقرّر ذلك.',
    'This summary is automatically generated and may contain inaccuracies. Always consult a healthcare professional.':
        'هذا الملخّص مُولَّد آليًا وقد يتضمّن أخطاء. استشر دائمًا مختصًّا في الرعاية الصحية.',
}

TRADUCTIONS = {'ar': AR}


def libelle(en, fr, lang=None):
    """
    Rend un libellé dans la langue demandée.

    Ordre de résolution : langue demandée, puis anglais, puis français. Le
    français reste le dernier recours parce que c'est la langue de la source.
    """
    if lang and lang != 'fr':
        table = TRADUCTIONS.get(lang)
        if table:
            traduit = table.get(en)
            if traduit:
                return traduit
        return en          # langue connue du site mais libellé non traduit
    return fr


def couverture(paires):
    """
    Libellés d'un gabarit non encore traduits, par langue.

    Sert au contrôle : un écran à moitié traduit se voit mal à la relecture,
    il se compte facilement.
    """
    manquants = {}
    for lang, table in TRADUCTIONS.items():
        manquants[lang] = sorted({en for en, _ in paires if en not in table})
    return manquants
