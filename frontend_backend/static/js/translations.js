/* Trois langues, et trois seulement.
 *
 * Il y en avait six. Les trois autres — chinois, espagnol, allemand —
 * n'avaient aucune table : chaque bascule vers elles partait chercher
 * la traduction sur `/api/translate/batch`, qui appelle Google. Une
 * seconde d'attente au mieux, un texte non traduit au pire si le
 * réseau manque, et une dépendance externe sur toutes les pages.
 *
 * Les trois qui restent sont écrites en dur. La bascule ne touche donc
 * plus le réseau du tout : elle est instantanée par construction, pas
 * par optimisation. */
const LANGUAGES = {
  fr: { label: 'Français', flag: '🇫🇷', dir: 'ltr' },
  en: { label: 'English',  flag: '🇬🇧', dir: 'ltr' },
  ar: { label: 'العربية',  flag: '🇸🇦', dir: 'rtl' },
};

const STATIC_TRANSLATIONS = { fr: {}, en: {}, ar: {} };

function initStaticTranslations() {
  const fr = STATIC_TRANSLATIONS.fr;
  const en = STATIC_TRANSLATIONS.en;
  const ar = STATIC_TRANSLATIONS.ar;


  /* ── La barre de navigation, les modes de recherche, le pied ───────
   *
   * Ces trois composants sont sur toutes les pages du site, et aucun
   * n'avait la moindre clé : la barre restait en français quelle que
   * soit la langue choisie, y compris quand tout le reste de la page
   * avait basculé. Une navigation qui ne suit pas la langue est le
   * premier endroit où l'utilisateur voit que la traduction est
   * partielle.
   *
   * L'arabe est écrit ici avec le reste. Il demande une relecture par
   * un locuteur : la terminologie médicale y est technique, et je ne
   * suis pas en mesure de garantir le registre. */




  /* ── L'assistant conversationnel et la verification d'ordonnance ───
   *
   * Deux surfaces qui n'avaient aucune cle. Le chatbot est present sur
   * les deux accueils ; la page ordonnance est l'un des trois ecrans de
   * decision du produit, et elle annoncait sa portee — « aucune
   * intelligence artificielle n'intervient ici » — uniquement en
   * francais. Une reserve que le lecteur ne comprend pas ne le protege
   * de rien. */
  fr.cb_titre = "POSOLOGYAI L'ASSISTANT";
  en.cb_titre = "POSOLOGYAI ASSISTANT";
  ar.cb_titre = "مساعد POSOLOGYAI";

  fr.cb_placeholder = "Posez votre question...";
  en.cb_placeholder = "Ask your question...";
  ar.cb_placeholder = "اطرح سؤالك...";

  fr.cb_ouvrir = "Ouvrir l'assistant PosologyAI";
  en.cb_ouvrir = "Open the PosologyAI assistant";
  ar.cb_ouvrir = "فتح مساعد PosologyAI";

  fr.cb_fermer = "Fermer l'assistant";
  en.cb_fermer = "Close the assistant";
  ar.cb_fermer = "إغلاق المساعد";

  fr.cb_envoyer = "Envoyer le message";
  en.cb_envoyer = "Send the message";
  ar.cb_envoyer = "إرسال الرسالة";

  fr.cb_en_ligne = "En ligne"; en.cb_en_ligne = "Online"; ar.cb_en_ligne = "متصل";
  fr.cb_effacer = "Effacer la conversation"; en.cb_effacer = "Clear the conversation"; ar.cb_effacer = "مسح المحادثة";
  fr.cb_suggestions = "Essayez :"; en.cb_suggestions = "Try:"; ar.cb_suggestions = "جرّب:";
  fr.cb_avertissement = "Informations indicatives — ne remplacent pas un avis médical. En urgence : 15 ou 112.";
  en.cb_avertissement = "Informational only — does not replace medical advice. In an emergency: call 112.";
  ar.cb_avertissement = "معلومات للاسترشاد فقط — لا تُغني عن استشارة طبية. في الحالات الطارئة: اتصل بالطوارئ.";

  /* Messages generes par chatbot.js (echecs reseau, limites). */
  fr.cb_erreur_generique = "Désolé, une erreur s'est produite. Veuillez réessayer."; en.cb_erreur_generique = "Sorry, an error occurred. Please try again."; ar.cb_erreur_generique = "عذرًا، حدث خطأ. يرجى المحاولة مرة أخرى.";
  fr.cb_erreur_connexion = "Erreur de connexion. Vérifiez votre connexion internet."; en.cb_erreur_connexion = "Connection error. Please check your internet connection."; ar.cb_erreur_connexion = "خطأ في الاتصال. تحقق من اتصالك بالإنترنت.";
  fr.cb_erreur_timeout = "La réponse met trop de temps à venir. Réessayez dans un instant."; en.cb_erreur_timeout = "The answer is taking too long. Please try again in a moment."; ar.cb_erreur_timeout = "يستغرق الرد وقتًا طويلاً. حاول مرة أخرى بعد قليل.";
  fr.cb_erreur_serveur = "Réponse illisible du serveur."; en.cb_erreur_serveur = "Unreadable server response."; ar.cb_erreur_serveur = "رد الخادم غير مقروء.";
  fr.cb_rate_limit = "Trop de messages envoyés. Merci de patienter un instant."; en.cb_rate_limit = "Too many messages sent. Please wait a moment."; ar.cb_rate_limit = "تم إرسال رسائل كثيرة جدًا. يرجى الانتظار قليلاً.";

  fr.cb_accueil_sans_chiffres = "Bonjour ! Je suis POSOLOGYAI L'ASSISTANT, votre assistant médical intelligent. Je peux vous aider à trouver des informations sur les médicaments et leurs interactions. Posez-moi vos questions !";
  en.cb_accueil_sans_chiffres = "Hello! I am POSOLOGYAI ASSISTANT, your intelligent medical assistant. I can help you find information about medicines and their interactions. Ask me your questions!";
  ar.cb_accueil_sans_chiffres = "مرحبًا! أنا مساعد POSOLOGYAI الطبي الذكي. يمكنني مساعدتك في العثور على معلومات عن الأدوية وتفاعلاتها. اطرح أسئلتك!";

  fr.ord_titre_page = "Vérifier une ordonnance - PosologyAI";
  en.ord_titre_page = "Check a prescription - PosologyAI";
  ar.ord_titre_page = "التحقق من وصفة - PosologyAI";

  fr.ord_surtitre = "Vérification";
  en.ord_surtitre = "Verification";
  ar.ord_surtitre = "تحقّق";

  fr.ord_titre = "Vérifier une ordonnance";
  en.ord_titre = "Check a prescription";
  ar.ord_titre = "التحقق من وصفة";

  fr.ord_chapeau = "Composez la liste des médicaments d'une ordonnance. L'écran croise ce que les données recensent : doublons de substance active, interactions entre les lignes, contre-indications, surveillance renforcée.";
  en.ord_chapeau = "Build the list of medicines on a prescription. The screen cross-checks what the data records: duplicate active substances, interactions between lines, contraindications, additional monitoring.";
  ar.ord_chapeau = "كوّن قائمة أدوية الوصفة. تقارن الشاشة ما تسجّله البيانات: تكرار المواد الفعالة، والتفاعلات بين البنود، وموانع الاستعمال، والمراقبة المشددة.";

  fr.ord_portee = "Aucune intelligence artificielle n'intervient ici, et aucun ordre de gravité n'est affiché : la source des interactions, DrugBank, n'en porte pas. Cet écran rapproche des faits, il ne décide pas. Vérifiez chaque point dans le RCP officiel.";
  en.ord_portee = "No artificial intelligence is involved here, and no severity ranking is shown: the interaction source, DrugBank, carries none. This screen brings facts together, it does not decide. Check every point in the official SmPC.";
  ar.ord_portee = "لا يتدخل هنا أي ذكاء اصطناعي، ولا يُعرض أي ترتيب للخطورة: مصدر التفاعلات، DrugBank، لا يحمل أيًّا منه. تجمع هذه الشاشة الوقائع، ولا تقرّر. تحقّق من كل نقطة في ملخص الخصائص الرسمي.";

  fr.ord_lignes = "Lignes de l'ordonnance";
  en.ord_lignes = "Prescription lines";
  ar.ord_lignes = "بنود الوصفة";

  fr.ord_ajouter = "Ajouter un médicament";
  en.ord_ajouter = "Add a medicine";
  ar.ord_ajouter = "إضافة دواء";

  fr.ord_placeholder = "Tapez un nom de médicament, puis choisissez dans la liste…";
  en.ord_placeholder = "Type a medicine name, then choose from the list…";
  ar.ord_placeholder = "اكتب اسم دواء، ثم اختر من القائمة…";

  fr.ord_proposes = "Médicaments proposés";
  en.ord_proposes = "Suggested medicines";
  ar.ord_proposes = "الأدوية المقترحة";

  fr.ord_vide = "Aucune ligne pour l'instant. Ajoutez au moins deux médicaments pour que le croisement ait un sens.";
  en.ord_vide = "No lines yet. Add at least two medicines for the cross-check to mean anything.";
  ar.ord_vide = "لا توجد بنود بعد. أضف دواءين على الأقل ليكون للمقارنة معنى.";

  fr.ord_verifier = "Vérifier l'ordonnance";
  en.ord_verifier = "Check the prescription";
  ar.ord_verifier = "تحقّق من الوصفة";

  fr.ord_tout_retirer = "Tout retirer";
  en.ord_tout_retirer = "Remove all";
  ar.ord_tout_retirer = "إزالة الكل";


  /* ── La page d'accueil ─────────────────────────────────────────────
   *
   * Elle n'avait aucune cle. La porte d'entree du site restait en
   * francais quelle que soit la langue choisie : cinquante-trois
   * chaines, dont tout le hero et les cinq entrees du catalogue.
   *
   * Treize autres chaines de cette page reutilisent des cles qui
   * existaient deja — `hero_title_line1`, `medicaments`, `sources`,
   * `interactions`... Meme texte francais, meme cle, pas de doublon.
   *
   * `ANSM`, `EMA`, `DrugBank` et `24/7` ne sont pas traduits : des noms
   * propres et une notation universelle. */
  fr.acc_hero_sub = "Accédez à des milliers de fiches médicamenteuses, analysez les interactions et obtenez des synthèses intelligentes en un clic.";
  en.acc_hero_sub = "Access thousands of medication records, analyse interactions and get intelligent summaries in one click.";
  ar.acc_hero_sub = "اطّلع على آلاف بطاقات الأدوية، وحلّل التفاعلات، واحصل على خلاصات ذكية بنقرة واحدة.";

  fr.acc_exemples = "Par exemple";
  en.acc_exemples = "For example";
  ar.acc_exemples = "على سبيل المثال";

  fr.acc_plus_connectees = "Les plus connectées du graphe";
  en.acc_plus_connectees = "Most connected in the graph";
  ar.acc_plus_connectees = "الأكثر ارتباطًا في الرسم البياني";

  fr.acc_voir_graphe = "Voir le graphe entier";
  en.acc_voir_graphe = "View the whole graph";
  ar.acc_voir_graphe = "عرض الرسم البياني كاملًا";

  fr.acc_substances = "Substances actives";
  en.acc_substances = "Active substances";
  ar.acc_substances = "المواد الفعالة";

  fr.acc_accessibilite = "Accessibilité";
  en.acc_accessibilite = "Availability";
  ar.acc_accessibilite = "إتاحة";

  fr.acc_fonctionnement = "Fonctionnement";
  en.acc_fonctionnement = "How it works";
  ar.acc_fonctionnement = "طريقة العمل";

  fr.acc_info_diagnostic = "De l'information au diagnostic";
  en.acc_info_diagnostic = "From information to diagnosis";
  ar.acc_info_diagnostic = "من المعلومة إلى التشخيص";

  fr.acc_trois_etapes = "Une approche structurée en trois étapes pour une utilisation médicale rigoureuse et fiable.";
  en.acc_trois_etapes = "A three-step approach for rigorous, reliable medical use.";
  ar.acc_trois_etapes = "منهج من ثلاث خطوات لاستخدام طبي دقيق وموثوق.";

  fr.acc_etape1 = "Saisie des informations";
  en.acc_etape1 = "Entering the information";
  ar.acc_etape1 = "إدخال المعلومات";

  /* Le français ci-dessous est celui du gabarit, au mot près.
   *
   * Il ne l'était plus : la table gardait une version plus courte de ces
   * trois paragraphes, écrite avant que le gabarit ne soit retouché. Sans
   * conséquence tant que rien ne citait la clé — le moteur réécrit aussi
   * le français, et poser l'attribut sur l'ancien texte aurait changé la
   * page française en croyant ne toucher qu'à l'anglais. */
  fr.acc_etape1_txt = "Entrez le nom d'un médicament, une substance active ou un laboratoire. Le moteur de recherche trouve instantanément les résultats les plus pertinents parmi des milliers de fiches.";
  en.acc_etape1_txt = "Enter a medicine name, an active substance or a laboratory. The search engine instantly finds the most relevant results among thousands of records.";
  ar.acc_etape1_txt = "أدخل اسم دواء أو مادة فعالة أو مختبرًا. يجد محرك البحث فورًا أكثر النتائج صلة من بين آلاف البطاقات.";

  fr.acc_etape2 = "Analyse par intelligence artificielle";
  en.acc_etape2 = "Analysis by artificial intelligence";
  ar.acc_etape2 = "التحليل بالذكاء الاصطناعي";

  fr.acc_etape2_txt = "Des résumés clairs et structurés : indications, posologie, effets secondaires, interactions médicamenteuses et précautions d'emploi.";
  en.acc_etape2_txt = "Clear, structured summaries: indications, dosage, side effects, drug interactions and precautions for use.";
  ar.acc_etape2_txt = "خلاصات واضحة ومنظّمة: دواعي الاستعمال، الجرعات، الآثار الجانبية، التفاعلات الدوائية، واحتياطات الاستعمال.";

  fr.acc_etape3 = "Visualisation des résultats";
  en.acc_etape3 = "Viewing the results";
  ar.acc_etape3 = "عرض النتائج";

  fr.acc_etape3_txt = "Des fiches détaillées avec une hiérarchie claire, des données chiffrées, les interactions recensées et les sources d'origine.";
  en.acc_etape3_txt = "Detailed records with a clear hierarchy, figures, the recorded interactions and the original sources.";
  ar.acc_etape3_txt = "بطاقات مفصّلة بترتيب واضح، وأرقام، والتفاعلات المسجّلة، والمصادر الأصلية.";

  fr.acc_resultats_clairs = "Des résultats clairs";
  en.acc_resultats_clairs = "Clear results";
  ar.acc_resultats_clairs = "نتائج واضحة";

  fr.acc_et_structures = "et structurés";
  en.acc_et_structures = "and structured";
  ar.acc_et_structures = "ومنظّمة";

  fr.acc_fiche_txt = "Chaque fiche présente les informations essentielles de manière organisée, pour une lecture rapide et fiable.";
  en.acc_fiche_txt = "Every record lays out the essentials in an organised way, for quick and reliable reading.";
  ar.acc_fiche_txt = "تعرض كل بطاقة المعلومات الأساسية بشكل منظّم، لقراءة سريعة وموثوقة.";

  fr.acc_ci = "Contre-indications";
  en.acc_ci = "Contraindications";
  ar.acc_ci = "موانع الاستعمال";

  fr.acc_ci_txt = "Remontées en tête, texte du RCP sans reformulation.";
  en.acc_ci_txt = "Brought to the top, the SmPC text without rewording.";
  ar.acc_ci_txt = "تُعرض في الأعلى، بنص الخصائص دون إعادة صياغة.";

  fr.acc_inter_txt = "Recensées et traduites, sans classement de gravité : la source n'en publie aucun.";
  en.acc_inter_txt = "Recorded and translated, with no severity ranking: the source publishes none.";
  ar.acc_inter_txt = "مسجّلة ومترجمة، دون تصنيف للخطورة: المصدر لا ينشر أيًّا منه.";

  fr.acc_monographie = "Monographie";
  en.acc_monographie = "Monograph";
  ar.acc_monographie = "الدراسة الدوائية";

  fr.acc_monographie_txt = "Intégrale, dans son ordre réglementaire, après ce qui sert à décider.";
  en.acc_monographie_txt = "Complete, in its regulatory order, after what serves the decision.";
  ar.acc_monographie_txt = "كاملة، بترتيبها التنظيمي، بعد ما يفيد في القرار.";

  fr.acc_formule = "Formule topologique";
  en.acc_formule = "Structural formula";
  ar.acc_formule = "الصيغة البنائية";

  /* ── Trois fins de phrase qui suivent un nombre calcule par le serveur ─
   *
   * « 12 480 molecules dessinees a partir de… », « 8 300 medicaments et
   * 4 100 substances actives. » Le nombre vient de Jinja, la prose est
   * fixe. Poser data-i18n sur le paragraphe entier remplacerait le tout,
   * chiffre compris, par une phrase sans chiffre : la cle ne couvre donc
   * que la partie qui suit le nombre, portee par un <span>. */
  fr.acc_formule_txt = "molécules dessinées à partir de leur structure chimique.";
  en.acc_formule_txt = "molecules drawn from their chemical structure.";
  ar.acc_formule_txt = "جزيء مرسوم انطلاقًا من بنيته الكيميائية.";

  fr.acc_stat_med_et = "médicaments et";
  en.acc_stat_med_et = "medicines and";
  ar.acc_stat_med_et = "دواء و";

  fr.acc_stat_sub = "substances actives.";
  en.acc_stat_sub = "active substances.";
  ar.acc_stat_sub = "مادة فعالة.";

  fr.acc_tout_ce_dont = "Tout ce dont";
  en.acc_tout_ce_dont = "Everything you";
  ar.acc_tout_ce_dont = "كل ما";

  fr.acc_vous_avez_besoin = "vous avez besoin";
  en.acc_vous_avez_besoin = "need";
  ar.acc_vous_avez_besoin = "تحتاج إليه";

  fr.acc_cinq_facons = "Cinq façons d'aborder le même catalogue.";
  en.acc_cinq_facons = "Five ways into the same catalogue.";
  ar.acc_cinq_facons = "خمس طرق للولوج إلى الفهرس نفسه.";

  fr.acc_multicriteres = "Recherche multicritères";
  en.acc_multicriteres = "Multi-criteria search";
  ar.acc_multicriteres = "بحث متعدد المعايير";

  fr.acc_verif_ordonnance = "Vérification d'ordonnance";
  en.acc_verif_ordonnance = "Prescription check";
  ar.acc_verif_ordonnance = "التحقق من الوصفة";

  fr.acc_semantique = "Recherche sémantique";
  en.acc_semantique = "Semantic search";
  ar.acc_semantique = "بحث دلالي";

  fr.acc_resumes = "Résumés intelligents";
  en.acc_resumes = "Intelligent summaries";
  ar.acc_resumes = "خلاصات ذكية";

  /* Les cinq descriptions d'onglets ont, elles aussi, ete rallongees dans
   * le gabarit apres l'ecriture de la table. On reprend la version du
   * gabarit : c'est elle que le visiteur lit aujourd'hui. */
  fr.acc_multicriteres_txt = "Filtrez par substance active, forme, laboratoire, dosage, voie d'administration, statut de commercialisation et famille thérapeutique. Les résultats se classent par pertinence, sur un index qui porte sur ce que le médicament est, non sur ce que sa notice mentionne.";
  en.acc_multicriteres_txt = "Filter by active substance, form, laboratory, dosage, route of administration, marketing status and therapeutic family. Results are ranked by relevance, on an index built on what the medicine is, not on what its leaflet happens to mention.";
  ar.acc_multicriteres_txt = "صفِّ حسب المادة الفعالة والشكل والمختبر والجرعة وطريق الإعطاء وحالة التسويق والعائلة العلاجية. تُرتَّب النتائج حسب الصلة، بالاعتماد على فهرس يقوم على ماهية الدواء، لا على ما تذكره نشرته.";

  fr.acc_ouvrir = "Ouvrir";
  en.acc_ouvrir = "Open";
  ar.acc_ouvrir = "فتح";

  fr.acc_verif_txt = "Composez la liste d'une ordonnance : l'écran croise les doublons de substance active, les interactions entre les lignes, les contre-indications de chaque médicament et les alertes de surveillance renforcée. Aucun modèle de langage n'intervient.";
  en.acc_verif_txt = "Build a prescription list: the screen cross-checks duplicate active substances, interactions between lines, the contraindications of each medicine and additional-monitoring alerts. No language model is involved.";
  ar.acc_verif_txt = "كوّن قائمة وصفة: تقارن الشاشة تكرار المواد الفعالة، والتفاعلات بين البنود، وموانع استعمال كل دواء، وتنبيهات المراقبة المشددة. ولا يتدخل أي نموذج لغوي في ذلك.";

  fr.acc_prescription_txt = "À partir de symptômes, de l'âge et des antécédents, des pistes de traitement assorties de leurs interactions avec les médicaments déjà pris. Les suggestions restent des suggestions : le RCP officiel fait foi.";
  en.acc_prescription_txt = "From symptoms, age and history, treatment options together with their interactions with the medicines already taken. Suggestions remain suggestions: the official product characteristics prevail.";
  ar.acc_prescription_txt = "انطلاقًا من الأعراض والعمر والسوابق، مقترحات علاجية مع تفاعلاتها مع الأدوية المتناولة أصلًا. وتبقى المقترحات مقترحات: فالمرجع هو ملخص خصائص المنتج الرسمي.";

  fr.acc_semantique_txt = "Le moteur vectoriel compare le sens de la requête à celui des fiches, et non ses mots. Il retrouve donc une spécialité décrite approximativement, ou par son indication plutôt que par son nom.";
  en.acc_semantique_txt = "The vector engine compares the meaning of the query with that of the records, not its words. It therefore finds a product described approximately, or by its indication rather than by its name.";
  ar.acc_semantique_txt = "يقارن المحرك المتجهي معنى الطلب بمعنى البطاقات، لا كلماته. فيجد بذلك مستحضرًا موصوفًا وصفًا تقريبيًا، أو بدواعي استعماله بدل اسمه.";

  fr.acc_resumes_txt = "Reformulation de la requête puis synthèse établie à partir du résumé des caractéristiques du produit. Les interactions sont listées sans hiérarchie de gravité : la source n'en publie aucune.";
  en.acc_resumes_txt = "The query is rephrased, then a summary is drawn from the product characteristics. Interactions are listed without a severity ranking: the source publishes none.";
  ar.acc_resumes_txt = "تُعاد صياغة الطلب ثم تُستخلص خلاصة من ملخص خصائص المنتج. وتُسرد التفاعلات دون ترتيب حسب الخطورة: فالمصدر لا ينشر أي ترتيب.";

  fr.acc_sources_txt = "Sources officielles : ANSM, Agence européenne des médicaments, DrugBank.";
  en.acc_sources_txt = "Official sources: ANSM, European Medicines Agency, DrugBank.";
  ar.acc_sources_txt = "مصادر رسمية: ANSM، الوكالة الأوروبية للأدوية، DrugBank.";

  fr.acc_privacy_txt = "Vos données sont protégées et jamais partagées.";
  en.acc_privacy_txt = "Your data is protected and never shared.";
  ar.acc_privacy_txt = "بياناتك محمية ولا تُشارَك أبدًا.";

  fr.acc_cadre = "Cadre académique";
  en.acc_cadre = "Academic setting";
  ar.acc_cadre = "إطار أكاديمي";

  fr.acc_cadre_txt = "Projet universitaire sous supervision pédagogique.";
  en.acc_cadre_txt = "University project under academic supervision.";
  ar.acc_cadre_txt = "مشروع جامعي تحت إشراف تربوي.";

  fr.acc_projet = "PosologyAI, projet académique";
  en.acc_projet = "PosologyAI, an academic project";
  ar.acc_projet = "PosologyAI، مشروع أكاديمي";

  fr.acc_cl_titre1 = "Un nom de médicament,";
  en.acc_cl_titre1 = "One medicine name,";
  ar.acc_cl_titre1 = "اسم دواء واحد،";

  fr.acc_cl_titre2 = "et tout ce qu'on en sait.";
  en.acc_cl_titre2 = "and everything known about it.";
  ar.acc_cl_titre2 = "وكل ما يُعرف عنه.";

  fr.acc_verifier_ordonnance = "Vérifier une ordonnance";
  en.acc_verifier_ordonnance = "Check a prescription";
  ar.acc_verifier_ordonnance = "تحقّق من وصفة";

  fr.acc_comment_construit = "Comment c'est construit";
  en.acc_comment_construit = "How it is built";
  ar.acc_comment_construit = "كيف بُني";

  fr.acc_sae = "Développé dans le cadre de la SAE5.01. Les fiches renvoient vers les sources officielles, qui font foi.";
  en.acc_sae = "Developed as part of the SAE5.01 coursework. The records link to the official sources, which prevail.";
  ar.acc_sae = "طُوّر في إطار وحدة SAE5.01. تحيل البطاقات إلى المصادر الرسمية، وهي المرجع.";


  /* ── Les huit intitules du formulaire patient ──────────────────────
   *
   * Portes par `data-i18n-label` dans l'assistant depuis qu'il existe,
   * et sans aucune entree de table : le moteur ne pouvait rien en faire
   * meme s'il avait lu l'attribut. */
  fr.nom = 'Nom';                     en.nom = 'Last name';            ar.nom = 'اللقب';
  fr.prenom = 'Prénom';               en.prenom = 'First name';        ar.prenom = 'الاسم';
  fr.taille = 'Taille (cm)';          en.taille = 'Height (cm)';       ar.taille = 'الطول (سم)';
  fr.poids = 'Poids (kg)';            en.poids = 'Weight (kg)';        ar.poids = 'الوزن (كغ)';
  fr.genre = 'Genre';                 en.genre = 'Gender';             ar.genre = 'الجنس';
  fr.symptom_description = 'Description des symptômes';
  en.symptom_description = 'Description of symptoms';
  ar.symptom_description = 'وصف الأعراض';
  fr.antecedents = 'Antécédents médicaux';
  en.antecedents = 'Medical history';
  ar.antecedents = 'السوابق الطبية';
  fr.current_meds = 'Traitements en cours';
  en.current_meds = 'Current treatments';
  ar.current_meds = 'العلاجات الحالية';

  /* ── L'arabe qui manquait sur des cles deja bilingues ──────────────
   *
   * Vingt-trois cles avaient leur francais et leur anglais mais pas
   * leur arabe : la page basculait en arabe avec des ilots anglais au
   * milieu. Le repli en cascade les rendait lisibles, il ne les rendait
   * pas traduites. */
  ar.all_routes = 'جميع طرق الإعطاء';
  ar.all_marketing_status = 'المسوّقة والمسحوبة';
  ar.marketed_only = 'المسوّقة فقط';
  ar.not_marketed_only = 'المسحوبة فقط';
  ar.all_monitoring = 'المراقبة: غير محدد';
  ar.monitoring_yes = 'تحت مراقبة مشددة';
  ar.monitoring_no = 'خارج المراقبة المشددة';
  ar.hero_modes_hint = 'البحث الدقيق افتراضيًا؛ يُختار التشابه والمساعد في صفحة النتائج.';
  ar.about_more = 'اعرف المزيد';
  ar.path_state_no_diagnosis = 'لم يُشخَّص بعد';
  ar.path_state_diagnosis = 'التشخيص موجود';
  ar.diagnostic_help_title = 'المساعدة على التشخيص';
  ar.diagnostic_help_desc = 'التشخيص لم يُوضع بعد. تصف أعراض المريض وسياقه؛ '
    + 'تقترح الأداة فرضية سريرية للتحقق منها، ثم الأدوية.';
  ar.diagnostic_feature_1 = 'إدخال أعراض المريض وسياقه';
  ar.diagnostic_feature_2 = 'فرضية سريرية مقترحة، للتحقق منها';
  ar.diagnostic_feature_3 = 'التنبيهات والتوصيات المرتبطة';
  ar.diagnostic_feature_4 = 'إنشاء وصفة طبية';
  ar.prescription_by_diagnostic_title = 'الوصف حسب التشخيص';
  ar.prescription_by_diagnostic_desc = 'التشخيص موجود بالفعل. تُدخله كما هو؛ '
    + 'تقترح الأداة الأدوية المناسبة وتُنبّه إلى التفاعلات بين ما تحتفظ به.';
  ar.prescription_feature_1 = 'إدخال الفرضية السريرية مباشرة';
  ar.prescription_feature_2 = 'أدوية مقترحة من قاعدة البيانات';
  ar.prescription_feature_3 = 'التفاعلات المُنبَّه إليها بين الأدوية المختارة';
  ar.prescription_feature_4 = 'أخذ السوابق والعلاجات الحالية في الحسبان';

  fr.nav_dashboard = 'Tableau de bord';
  en.nav_dashboard = 'Dashboard';
  ar.nav_dashboard = 'لوحة القيادة';

  fr.nav_search = 'Rechercher';
  en.nav_search = 'Search';
  ar.nav_search = 'بحث';

  fr.nav_search_classic = 'Recherche classique';
  en.nav_search_classic = 'Classic search';
  ar.nav_search_classic = 'بحث تقليدي';

  fr.nav_search_classic_desc = 'Par nom, substance, laboratoire';
  en.nav_search_classic_desc = 'By name, substance, laboratory';
  ar.nav_search_classic_desc = 'بالاسم أو المادة الفعالة أو المختبر';

  fr.nav_search_vector = 'Recherche vectorielle';
  en.nav_search_vector = 'Vector search';
  ar.nav_search_vector = 'بحث متجهي';

  fr.nav_search_vector_desc = 'Recherche sémantique avancée';
  en.nav_search_vector_desc = 'Advanced semantic search';
  ar.nav_search_vector_desc = 'بحث دلالي متقدم';

  fr.nav_search_ai = 'Recherche IA';
  en.nav_search_ai = 'AI search';
  ar.nav_search_ai = 'بحث بالذكاء الاصطناعي';

  fr.nav_search_ai_desc = 'Langage naturel';
  en.nav_search_ai_desc = 'Natural language';
  ar.nav_search_ai_desc = 'لغة طبيعية';

  fr.nav_prescription = 'Prescription';
  en.nav_prescription = 'Prescription';
  ar.nav_prescription = 'وصفة طبية';

  fr.nav_ordonnance = 'Ordonnance';
  en.nav_ordonnance = 'Prescription check';
  ar.nav_ordonnance = 'التحقق من الوصفة';

  fr.nav_about = 'À propos';
  en.nav_about = 'About';
  ar.nav_about = 'حول';

  fr.nav_profile = 'Mon profil';
  en.nav_profile = 'My profile';
  ar.nav_profile = 'ملفي الشخصي';

  fr.nav_favorites = 'Mes favoris';
  en.nav_favorites = 'My favourites';
  ar.nav_favorites = 'مفضلاتي';

  fr.nav_admin = 'Administration';
  en.nav_admin = 'Administration';
  ar.nav_admin = 'الإدارة';

  fr.nav_logout = 'Déconnexion';
  en.nav_logout = 'Log out';
  ar.nav_logout = 'تسجيل الخروج';

  fr.nav_login = 'Connexion';
  en.nav_login = 'Log in';
  ar.nav_login = 'تسجيل الدخول';

  fr.nav_main_label = 'Navigation principale';
  en.nav_main_label = 'Main navigation';
  ar.nav_main_label = 'التنقل الرئيسي';

  fr.nav_show = 'Afficher la navigation';
  en.nav_show = 'Show navigation';
  ar.nav_show = 'إظهار التنقل';

  fr.nav_user_menu = 'Menu utilisateur';
  en.nav_user_menu = 'User menu';
  ar.nav_user_menu = 'قائمة المستخدم';

  /* Les trois modes de recherche. */
  fr.mode_exact = 'Exacte';
  en.mode_exact = 'Exact';
  ar.mode_exact = 'دقيق';

  fr.mode_exact_hint = 'nom, substance, laboratoire';
  en.mode_exact_hint = 'name, substance, laboratory';
  ar.mode_exact_hint = 'الاسم، المادة الفعالة، المختبر';

  fr.mode_similar = 'Similarité';
  en.mode_similar = 'Similarity';
  ar.mode_similar = 'التشابه';

  fr.mode_similar_hint = 'molécules et indications proches';
  en.mode_similar_hint = 'related molecules and indications';
  ar.mode_similar_hint = 'جزيئات ودواعي استعمال مشابهة';

  fr.mode_assistant = 'Assistant';
  en.mode_assistant = 'Assistant';
  ar.mode_assistant = 'المساعد';

  fr.mode_assistant_hint = 'une question en français';
  en.mode_assistant_hint = 'a question in plain language';
  ar.mode_assistant_hint = 'سؤال بلغة عادية';

  fr.mode_label = 'Mode de recherche';
  en.mode_label = 'Search mode';
  ar.mode_label = 'وضع البحث';

  /* Le pied de page. */
  fr.footer_databases = "Comment cette base est construite, et ce qu'elle refuse d'afficher";
  en.footer_databases = 'How this database is built, and what it refuses to display';
  ar.footer_databases = 'كيف بُنيت هذه القاعدة، وما ترفض عرضه';

  fr.footer_educational_only = 'Ce site est conçu à des fins éducatives uniquement.';
  en.footer_educational_only = 'This site is designed for educational purposes only.';
  ar.footer_educational_only = 'هذا الموقع مُعدّ لأغراض تعليمية فقط.';

  fr.home = 'Accueil'; en.home = 'Home';
  fr.search = 'Recherche'; en.search = 'Search';
  fr.about = 'À propos'; en.about = 'About';
  fr.contact = 'Contact'; en.contact = 'Contact';

  fr.index_title = 'PosologyAI • Base de données médicamenteuse'; en.index_title = 'PosologyAI • Medical Database';
  fr.hero_title_line1 = 'Votre santé,'; en.hero_title_line1 = 'Your health,';
  fr.hero_title_line2 = 'éclairée par la donnée'; en.hero_title_line2 = 'enlightened by data';
  fr.hero_subtitle = 'Accédez à des milliers de fiches médicamenteuses, analysez les interactions et obtenez des synthèses intelligentes en un clic.'; en.hero_subtitle = 'Access thousands of medication sheets, analyze interactions and get intelligent summaries in one click.';
  fr.hero_modes_hint = 'Recherche exacte par défaut&nbsp;; la similarité et l\'assistant se choisissent sur la page de résultats.'; en.hero_modes_hint = 'Exact search by default; similarity and the assistant are chosen on the results page.';
  fr.trusted_medical_db = 'Base de données médicale de confiance'; en.trusted_medical_db = 'Trusted medical database';
  fr.start_exploring = 'Explorer les médicaments'; en.start_exploring = 'Explore medications';
  fr.try_ai_search = 'Recherche intelligente'; en.try_ai_search = 'Smart search';

  fr.stat_medicines = 'MÉDICAMENTS'; en.stat_medicines = 'MEDICATIONS';
  fr.stat_substances = 'SUBSTANCES ACTIVES'; en.stat_substances = 'ACTIVE SUBSTANCES';
  fr.stat_interactions = 'INTERACTIONS'; en.stat_interactions = 'INTERACTIONS';
  fr.stat_availability = 'ACCESSIBILITÉ'; en.stat_availability = 'AVAILABILITY';

  fr.how_it_works = 'Comment ça marche'; en.how_it_works = 'How it works';
  fr.process_title = 'Notre processus'; en.process_title = 'Our process';
  fr.process_subtitle = 'De la recherche à la découverte'; en.process_subtitle = 'From search to discovery';
  fr.step1_title = 'Recherchez'; en.step1_title = 'Search';
  fr.step1_desc = 'Trouvez un médicament par nom, substance ou symptôme'; en.step1_desc = 'Find a medicine by name, substance or symptom';
  fr.step2_title = 'Analysez'; en.step2_title = 'Analyze';
  fr.step2_desc = 'Consultez les interactions, les résumés IA et les données détaillées'; en.step2_desc = 'Check interactions, AI summaries and detailed data';
  fr.step3_title = 'Décidez'; en.step3_title = 'Decide';
  fr.step3_desc = 'Utilisez les informations pour éclairer vos décisions médicales'; en.step3_desc = 'Use the information to inform your medical decisions';

  fr.ai_powered = 'Propulsé par l\'IA'; en.ai_powered = 'AI-Powered';
  fr.ai_feature_title = 'Intelligence Artificielle au service de la santé'; en.ai_feature_title = 'Artificial Intelligence serving healthcare';
  fr.ai_feature_text1 = 'Notre moteur d\'analyse IA examine des milliers de données pour vous fournir des synthèses claires et pertinentes sur chaque médicament.'; en.ai_feature_text1 = 'Our AI analysis engine examines thousands of data points to provide clear, relevant summaries for each medication.';
  fr.ai_feature_text2 = 'Recherche vectorielle, analyse d\'interactions et génération d\'ordonnances intelligentes : l\'IA transforme votre façon d\'accéder à l\'information médicale.'; en.ai_feature_text2 = 'Vector search, interaction analysis and smart prescription generation: AI transforms how you access medical information.';
  fr.try_ai_now = 'Essayez l\'IA maintenant'; en.try_ai_now = 'Try AI now';
  fr.ai_processing = 'Analyse en cours...'; en.ai_processing = 'Analyzing...';
  fr.visualization = 'Visualisation'; en.visualization = 'Visualization';
  fr.results_title = 'Résultats intelligents'; en.results_title = 'Smart Results';
  fr.results_subtitle = 'Des analyses précises en quelques secondes'; en.results_subtitle = 'Accurate analysis in seconds';

  fr.trust_data = 'Données fiables'; en.trust_data = 'Trusted Data';
  fr.trust_data_desc = 'Sources officielles et mises à jour régulièrement'; en.trust_data_desc = 'Official sources, regularly updated';
  fr.trust_privacy = 'Confidentialité'; en.trust_privacy = 'Privacy';
  fr.trust_privacy_desc = 'Vos données sont protégées et jamais partagées'; en.trust_privacy_desc = 'Your data is protected and never shared';
  fr.trust_academic = 'Recherche académique'; en.trust_academic = 'Academic Research';
  fr.trust_academic_desc = 'Développé dans le cadre universitaire'; en.trust_academic_desc = 'Developed in an academic framework';
  fr.trust_comprehensive = 'Base exhaustive'; en.trust_comprehensive = 'Comprehensive Database';
  fr.trust_comprehensive_desc = 'Des milliers de médicaments répertoriés'; en.trust_comprehensive_desc = 'Thousands of listed medications';

  fr.features = 'Fonctionnalités'; en.features = 'Features';
  fr.features_title = 'POURQUOI POSOLOGYAI ?'; en.features_title = 'WHY POSOLOGYAI?';
  fr.features_subtitle = 'Découvrez toutes les capacités de PosologyAI'; en.features_subtitle = 'Discover all the capabilities of PosologyAI';
  fr.feature_search = 'Recherche intelligente'; en.feature_search = 'Smart Search';
  fr.feature_search_desc = 'Trouvez rapidement ce que vous cherchez'; en.feature_search_desc = 'Find what you\'re looking for quickly';
  fr.feature_vector = 'Recherche vectorielle'; en.feature_vector = 'Vector search';
  fr.feature_vector_desc = 'Trouvez des médicaments par similarité sémantique'; en.feature_vector_desc = 'Find medications by semantic similarity';
  fr.feature_ai = 'Synthèse IA'; en.feature_ai = 'AI Summary';
  fr.feature_ai_desc = 'Résumés intelligents de chaque médicament'; en.feature_ai_desc = 'Smart summaries for each medication';
  fr.feature_chatbot = 'Assistant PosologyBot'; en.feature_chatbot = 'PosologyBot Assistant';
  fr.feature_chatbot_desc = 'Posez vos questions en langage naturel'; en.feature_chatbot_desc = 'Ask questions in natural language';
  fr.feature_prescription = 'Aide à la prescription'; en.feature_prescription = 'Prescription help';
  fr.feature_prescription_desc = 'Générez des ordonnances par diagnostic'; en.feature_prescription_desc = 'Generate prescriptions by diagnosis';

  fr.explore_database = 'Explorer la base de données'; en.explore_database = 'Explore the database';
  fr.about_more = 'Comment cette base est construite'; en.about_more = 'How this database is built';
  fr.about_title = 'PosologyAI — Projet académique'; en.about_title = 'PosologyAI — Academic project';
  fr.about_text1 = 'PosologyAI est une initiative académique développée dans le cadre de la SAE5.01 pour fournir un accès facile et fiable aux informations médicamenteuses.'; en.about_text1 = 'PosologyAI is an academic initiative developed as part of SAE5.01 to provide easy and reliable access to medication information.';
  fr.about_text2 = 'Notre objectif est de centraliser et de rendre accessibles les données sur les médicaments, permettant aux utilisateurs de trouver rapidement les informations dont ils ont besoin.'; en.about_text2 = 'Our goal is to centralize and make medication data accessible, allowing users to quickly find the information they need.';

  /* `nav_search` et `nav_dashboard` etaient redefinis ici, apres l'avoir
   * deja ete plus haut (L423 et L419) avec leur arabe. La derniere
   * affectation gagnant, ces deux lignes-ci imposaient le francais du bloc
   * ancien : le bouton de recherche affichait « Recherche » la ou tous les
   * gabarits ecrivent « Rechercher », et la navigation francaise annoncait
   * « Dashboard » au lieu de « Tableau de bord ». Le defaut ne se voyait
   * qu'apres une bascule de langue — au premier chargement, le texte servi
   * par Flask est celui du gabarit, donc le bon. */
  fr.nav_classic = 'Recherche classique'; en.nav_classic = 'Classic search';
  fr.nav_classic_desc = 'Par nom, substance, laboratoire'; en.nav_classic_desc = 'By name, substance, laboratory';
  fr.nav_vector = 'Recherche vectorielle'; en.nav_vector = 'Vector search';
  fr.nav_vector_desc = 'Recherche sémantique avancée'; en.nav_vector_desc = 'Advanced semantic search';
  fr.nav_ai = 'Recherche IA'; en.nav_ai = 'AI search';
  fr.nav_ai_desc = 'Langage naturel'; en.nav_ai_desc = 'Natural language';
  fr.nav_prescription = 'Prescription'; en.nav_prescription = 'Prescription';
  fr.nav_databases = 'Bases de données'; en.nav_databases = 'Databases';

  fr.login = 'Connexion'; en.login = 'Login';
  fr.profile = 'Mon profil'; en.profile = 'My profile';
  fr.favorites = 'Mes favoris'; en.favorites = 'My favorites';
  fr.admin = 'Administration'; en.admin = 'Administration';
  fr.logout = 'Déconnexion'; en.logout = 'Logout';

  fr.chatbot_welcome = 'Bonjour ! Je suis **PosologyBot**, votre assistant médical intelligent.\nJe peux vous renseigner sur les médicaments, leurs indications, posologies et interactions.'; en.chatbot_welcome = 'Hello! I am **PosologyBot**, your intelligent medical assistant.\nI can help you with medications, their indications, dosages and interactions.';
  fr.chatbot_input_placeholder = 'Posez votre question...'; en.chatbot_input_placeholder = 'Ask your question...';
  fr.chatbot_disclaimer = 'Les informations fournies sont à titre indicatif. Consultez un professionnel de santé.'; en.chatbot_disclaimer = 'Information is for reference only. Consult a healthcare professional.';
  fr.chatbot_suggestions = 'Suggestions :'; en.chatbot_suggestions = 'Suggestions:';
  fr.chatbot_online = 'En ligne'; en.chatbot_online = 'Online';
  fr.chatbot_clear = 'Effacer la conversation'; en.chatbot_clear = 'Clear conversation';
  fr.chatbot_close = 'Fermer'; en.chatbot_close = 'Close';

  fr.just_now = "à l'instant"; en.just_now = 'just now';

  fr.menu_prescription = 'Menu prescription'; en.menu_prescription = 'Prescription menu';
  fr.patient_info = 'Informations patient'; en.patient_info = 'Patient information';
  fr.homme = 'Homme'; en.homme = 'Male';
  fr.femme = 'Femme'; en.femme = 'Female';
  fr.autre = 'Autre'; en.autre = 'Other';
  fr.submit_btn = 'Analyser'; en.submit_btn = 'Analyze';
  fr.reset_btn = 'Réinitialiser'; en.reset_btn = 'Reset';
  fr.loading = 'Chargement...'; en.loading = 'Loading...';
  fr.interactions_title = 'Interactions détectées'; en.interactions_title = 'Detected interactions';
  fr.ai_diagnosis_title = 'Analyse IA'; en.ai_diagnosis_title = 'AI Analysis';
  fr.suggested_medications = 'Médicaments suggérés'; en.suggested_medications = 'Suggested medications';
  // Le panneau couvre quatre motifs — antécédents, pertinence, classe,
  // éligibilité — depuis qu'ils y sont groupés. Un titre qui n'en nommait
  // qu'un couvrait des produits non commercialisés.
  fr.ecartes_title = 'Médicaments écartés'; en.ecartes_title = 'Ruled out, and why';
  fr.recommendations_title = 'Recommandations'; en.recommendations_title = 'Recommendations';
  fr.generate_pdf = 'Générer le PDF'; en.generate_pdf = 'Generate PDF';

  fr.instructions_title = 'Instructions'; en.instructions_title = 'Instructions';
  fr.instructions_text = 'Remplissez les informations patient et décrivez le diagnostic pour obtenir une analyse complète.'; en.instructions_text = 'Fill in patient information and describe the diagnosis to get a complete analysis.';
  fr.medical_diagnosis = 'Diagnostic médical'; en.medical_diagnosis = 'Medical diagnosis';
  fr.patient_name = 'Nom du patient'; en.patient_name = 'Patient name';
  fr.optional = 'Optionnel'; en.optional = 'Optional';
  fr.age = 'Âge'; en.age = 'Age';
  fr.height = 'Taille (cm)'; en.height = 'Height (cm)';
  fr.weight = 'Poids (kg)'; en.weight = 'Weight (kg)';
  fr.gender = 'Sexe'; en.gender = 'Gender';
  fr.gender_unspecified = 'Non précisé'; en.gender_unspecified = 'Unspecified';
  fr.gender_male = 'Masculin'; en.gender_male = 'Male';
  fr.gender_female = 'Féminin'; en.gender_female = 'Female';
  fr.gender_other = 'Autre'; en.gender_other = 'Other';
  fr.medical_history = 'Antécédents médicaux'; en.medical_history = 'Medical history';
  fr.current_medications = 'Médicaments en cours'; en.current_medications = 'Current medications';
  fr.diagnosis = 'Diagnostic'; en.diagnosis = 'Diagnosis';
  fr.diagnostic_tip = 'Décrivez les symptômes, la pathologie suspectée ou les analyses disponibles'; en.diagnostic_tip = 'Describe symptoms, suspected pathology or available tests';
  fr.analyze_button = 'Lancer l\'analyse'; en.analyze_button = 'Start analysis';
  fr.reset_button = 'Réinitialiser'; en.reset_button = 'Reset';
  fr.analyzing = 'Analyse en cours'; en.analyzing = 'Analyzing';
  fr.analyzing_details = 'Notre IA analyse les données et recherche les médicaments pertinents...'; en.analyzing_details = 'Our AI analyzes data and searches for relevant medications...';
  fr.vectorial = 'Vectoriel'; en.vectorial = 'Vector';
  fr.data = 'Données'; en.data = 'Data';
  fr.relations = 'Relations'; en.relations = 'Relations';
  fr.interactions_detected = 'Interactions détectées'; en.interactions_detected = 'Interactions detected';
  fr.medications_suggested = 'Médicaments suggérés'; en.medications_suggested = 'Medications suggested';
  fr.prescription_summary = 'Récapitulatif de l\'ordonnance'; en.prescription_summary = 'Prescription summary';

  fr.patient_name_placeholder = 'Entrez le nom du patient'; en.patient_name_placeholder = 'Enter patient name';
  fr.age_placeholder = 'Ex: 45'; en.age_placeholder = 'E.g. 45';
  fr.height_placeholder = 'Ex: 170'; en.height_placeholder = 'E.g. 170';
  fr.weight_placeholder = 'Ex: 70'; en.weight_placeholder = 'E.g. 70';
  fr.medical_history_placeholder = 'Ex: Diabète, HTA...'; en.medical_history_placeholder = 'E.g. Diabetes, HTN...';
  fr.current_medications_placeholder = 'Ex: Metformine 850mg...'; en.current_medications_placeholder = 'E.g. Metformin 850mg...';
  fr.diagnostic_placeholder = 'Ex: Syndrome grippal avec fièvre >38.5°C depuis 3 jours'; en.diagnostic_placeholder = 'E.g. Flu-like syndrome with fever >38.5°C for 3 days';

  // disclaimer_title et disclaimer_text sont retirés avec le bandeau
  // d'avertissement : plus aucun gabarit ne les demande.

  fr.prescription_help_title = 'Aide à la prescription'; en.prescription_help_title = 'Prescription help';
  fr.prescription_help_subtitle = 'Deux approches complémentaires pour vos prescriptions'; en.prescription_help_subtitle = 'Two complementary approaches for your prescriptions';
  fr.path_state_no_diagnosis = 'Diagnostic non posé'; en.path_state_no_diagnosis = 'No diagnosis yet';
  fr.path_state_diagnosis = 'Diagnostic déjà posé'; en.path_state_diagnosis = 'Diagnosis already made';
  fr.diagnostic_help_title = 'Aide au diagnostic'; en.diagnostic_help_title = 'Diagnostic assistance';
  fr.diagnostic_help_desc = 'Le diagnostic n\'est pas encore posé. Vous décrivez les symptômes et le contexte du patient ; l\'outil propose une hypothèse clinique à valider, puis des médicaments.'; en.diagnostic_help_desc = 'No diagnosis yet. You describe the patient\'s symptoms and context; the tool proposes a clinical hypothesis to validate, then medications.';
  fr.diagnostic_feature_1 = 'Saisie des symptômes et du contexte du patient'; en.diagnostic_feature_1 = 'Entry of patient symptoms and context';
  fr.diagnostic_feature_2 = 'Hypothèse clinique proposée, à valider'; en.diagnostic_feature_2 = 'Clinical hypothesis proposed, to be validated';
  fr.diagnostic_feature_3 = 'Alertes et recommandations associées'; en.diagnostic_feature_3 = 'Related alerts and recommendations';
  fr.diagnostic_feature_4 = 'Génération d\'une ordonnance'; en.diagnostic_feature_4 = 'Prescription generation';
  fr.start_diagnostic = 'Commencer le diagnostic'; en.start_diagnostic = 'Start diagnosis';
  fr.prescription_by_diagnostic_title = 'Prescription par diagnostic'; en.prescription_by_diagnostic_title = 'Prescription by diagnosis';
  fr.prescription_by_diagnostic_desc = 'Le diagnostic est déjà posé. Vous l\'entrez tel quel ; l\'outil propose les médicaments correspondants et signale les interactions entre ceux que vous retenez.'; en.prescription_by_diagnostic_desc = 'The diagnosis is already made. You enter it as is; the tool proposes matching medications and flags interactions between those you keep.';
  fr.prescription_feature_1 = 'Saisie directe de l\'hypothèse clinique'; en.prescription_feature_1 = 'Direct entry of the clinical hypothesis';
  fr.prescription_feature_2 = 'Médicaments suggérés depuis la base'; en.prescription_feature_2 = 'Medications suggested from the database';
  fr.prescription_feature_3 = 'Interactions signalées entre les médicaments retenus'; en.prescription_feature_3 = 'Interactions flagged between the medications kept';
  fr.prescription_feature_4 = 'Antécédents et traitements en cours pris en compte'; en.prescription_feature_4 = 'History and current treatments taken into account';
  fr.prescribe_medications = 'Prescrire des médicaments'; en.prescribe_medications = 'Prescribe medications';

  fr.classic_search_title = 'Recherche classique'; en.classic_search_title = 'Classic search';
  fr.try_classic_search = 'Recherche classique'; en.try_classic_search = 'Classic search';
  fr.try_keywords = 'Recherche par mots-clés'; en.try_keywords = 'Search by keywords';
  fr.all_active_substances = 'Toutes les substances actives'; en.all_active_substances = 'All active substances';
  fr.all_pharmaceutical_forms = 'Toutes les formes pharmaceutiques'; en.all_pharmaceutical_forms = 'All pharmaceutical forms';
  fr.all_laboratories = 'Tous les laboratoires'; en.all_laboratories = 'All laboratories';
  fr.all_dosages = 'Tous les dosages'; en.all_dosages = 'All dosages';
  fr.all_therapeutic_families_atc = 'Toutes les familles thérapeutiques (ATC)'; en.all_therapeutic_families_atc = 'All therapeutic families (ATC)';
  fr.all_medicine_types = 'Tous les types de médicaments'; en.all_medicine_types = 'All medicine types';
  fr.all_routes = 'Toutes les voies d\'administration'; en.all_routes = 'All routes of administration';
  fr.all_marketing_status = 'Commercialisés et retirés'; en.all_marketing_status = 'Marketed and withdrawn';
  fr.marketed_only = 'Commercialisés uniquement'; en.marketed_only = 'Marketed only';
  fr.not_marketed_only = 'Retirés uniquement'; en.not_marketed_only = 'Withdrawn only';
  fr.all_monitoring = 'Surveillance : indifférent'; en.all_monitoring = 'Any monitoring status';
  fr.monitoring_yes = 'Sous surveillance renforcée'; en.monitoring_yes = 'Under additional monitoring';
  fr.monitoring_no = 'Hors surveillance renforcée'; en.monitoring_no = 'Not under additional monitoring';
  fr.search_placeholder = 'Rechercher par nom, substance, laboratoire...'; en.search_placeholder = 'Search by name, substance, laboratory...';

  fr.vector_search_title = 'Recherche vectorielle'; en.vector_search_title = 'Vector search';
  fr.results = 'Résultats'; en.results = 'Results';

  fr.ai_search_title = 'Recherche IA'; en.ai_search_title = 'AI Search';
  fr.ai_results = 'Résultats'; en.ai_results = 'Results';
  fr.ai_search_placeholder = 'Décrivez ce que vous cherchez...'; en.ai_search_placeholder = 'Describe what you are looking for...';
  /* ── Le bloc « Resultats biologiques » des deux ecrans de prescription ──
   *
   * Les unites (mmol/L, mmHg, bpm, mL/min/1,73 m²) ne sont pas traduites :
   * elles sont internationales, et les traduire les rendrait fausses.
   * Les intitules, eux, sont des abreviations francaises qu'un lecteur
   * anglophone ne reconnait pas — DFG se dit eGFR, FEVG se dit LVEF. */
  fr.bio_titre = 'Résultats biologiques'; en.bio_titre = 'Laboratory results';
  fr.bio_facultatif = '(facultatif)'; en.bio_facultatif = '(optional)';
  fr.bio_aide = "Renseignés, ces résultats deviennent des contraintes : ils écartent les médicaments contre-indiqués et signalent les traitements en cours à reconsidérer.";
  en.bio_aide = 'When filled in, these results become constraints: they rule out contraindicated medicines and flag current treatments to reconsider.';
  fr.bio_constantes = 'Constantes'; en.bio_constantes = 'Vital signs';
  fr.bio_dfg = 'DFG'; en.bio_dfg = 'eGFR';
  fr.bio_kaliemie = 'Kaliémie'; en.bio_kaliemie = 'Serum potassium';
  fr.bio_natremie = 'Natrémie'; en.bio_natremie = 'Serum sodium';
  fr.bio_transaminases = 'Transaminases'; en.bio_transaminases = 'Transaminases';
  fr.bio_systolique = 'PA systolique'; en.bio_systolique = 'Systolic BP';
  fr.bio_diastolique = 'PA diastolique'; en.bio_diastolique = 'Diastolic BP';
  fr.bio_frequence = 'Fréquence cardiaque'; en.bio_frequence = 'Heart rate';
  fr.bio_fevg = 'FEVG'; en.bio_fevg = 'LVEF';

  ar.bio_titre = 'النتائج المخبرية';
  ar.bio_facultatif = '(اختياري)';
  ar.bio_aide = 'عند إدخالها، تصبح هذه النتائج قيودًا: فهي تستبعد الأدوية الممنوعة وتنبّه إلى العلاجات الجارية التي ينبغي إعادة النظر فيها.';
  ar.bio_constantes = 'العلامات الحيوية';
  ar.bio_dfg = 'معدل الترشيح الكبيبي';
  ar.bio_kaliemie = 'بوتاسيوم الدم';
  ar.bio_natremie = 'صوديوم الدم';
  ar.bio_transaminases = 'ناقلات الأمين';
  ar.bio_systolique = 'الضغط الانقباضي';
  ar.bio_diastolique = 'الضغط الانبساطي';
  ar.bio_frequence = 'معدل ضربات القلب';
  ar.bio_fevg = 'الكسر القذفي للبطين الأيسر';

  /* Deux libelles qui accompagnent un resultat calcule : le badge de
   * reformulation en recherche IA, et l'etiquette du score de similarite en
   * recherche vectorielle. Tous deux restaient en francais faute de cle. */
  fr.requete_reformulee = 'Requête IA reformulée :'; en.requete_reformulee = 'AI-rephrased query:';
  fr.score_label = 'Score'; en.score_label = 'Score';

  fr.ai_answer_title = "Réponse de l'IA"; en.ai_answer_title = 'AI Answer';
  fr.ai_answer_sub = 'Synthèse générée à partir des notices de la base PosologyAI'; en.ai_answer_sub = 'Summary generated from the PosologyAI database leaflets';
  fr.ai_searching = "L'IA analyse votre question…"; en.ai_searching = 'AI is analyzing your question…';
  fr.ai_sources_title = 'Médicaments correspondants'; en.ai_sources_title = 'Matching medicines';
  fr.no_ai_results = 'Aucun résultat trouvé.'; en.no_ai_results = 'No results found.';
  fr.ai_disclaimer = "Ces informations sont fournies à titre indicatif et ne remplacent pas l'avis d'un professionnel de santé."; en.ai_disclaimer = 'This information is provided for guidance only and does not replace advice from a healthcare professional.';

  fr.card_general_info = 'Informations générales'; en.card_general_info = 'General Information';
  fr.label_trade_name = 'Nom commercial'; en.label_trade_name = 'Trade name';
  fr.label_active_substance = 'Substance active'; en.label_active_substance = 'Active substance';
  fr.label_pharmaceutical_form = 'Forme pharmaceutique'; en.label_pharmaceutical_form = 'Pharmaceutical form';
  fr.label_laboratory = 'Laboratoire'; en.label_laboratory = 'Laboratory';
  fr.tag_analgesic = 'Antalgique'; en.tag_analgesic = 'Analgesic';
  fr.tag_antipyretic = 'Antipyrétique'; en.tag_antipyretic = 'Antipyretic';
  fr.tag_who_level1 = 'Niveau 1 OMS'; en.tag_who_level1 = 'WHO Level 1';
  fr.card_interactions_title = 'Interactions détectées'; en.card_interactions_title = 'Detected interactions';
  fr.label_severe_interactions = 'Interactions graves'; en.label_severe_interactions = 'Severe interactions';
  fr.label_moderate_interactions = 'Interactions modérées'; en.label_moderate_interactions = 'Moderate interactions';
  fr.label_minor_interactions = 'Interactions mineures'; en.label_minor_interactions = 'Minor interactions';
  /* Les trois libelles ci-dessus decrivent une gravite que la fiche
   * n'affiche plus — la source n'en publie aucune. La vitrine annonce
   * desormais ce qu'elle montre vraiment, d'ou ces trois cles-ci. */
  fr.label_interactions_recensees = 'Interactions recensées'; en.label_interactions_recensees = 'Recorded interactions';
  fr.label_substances_concernees = 'Substances concernées'; en.label_substances_concernees = 'Substances involved';
  fr.label_classement_gravite = 'Classement par gravité'; en.label_classement_gravite = 'Severity ranking';
  fr.valeur_aucun = 'aucun'; en.valeur_aucun = 'none';

  ar.label_interactions_recensees = 'التفاعلات المسجّلة';
  ar.label_substances_concernees = 'المواد المعنية';
  ar.label_classement_gravite = 'الترتيب حسب الخطورة';
  ar.valeur_aucun = 'لا يوجد';

  fr.tag_ai_analysis = 'Analyse IA'; en.tag_ai_analysis = 'AI Analysis';
  fr.tag_database = 'Base de données'; en.tag_database = 'Database';
  fr.tag_neo4j_relations = 'Relations Neo4j'; en.tag_neo4j_relations = 'Neo4j Relations';

  fr.footer_rights = 'Tous droits réservés.'; en.footer_rights = 'All rights reserved.';
  fr.footer_educational = 'Ce site est conçu à des fins éducatives uniquement.'; en.footer_educational = 'This site is designed for educational purposes only.';

  fr.login_title = 'CONNEXION'; en.login_title = 'LOGIN';
  fr.login_subtitle = 'Accédez à votre espace personnel'; en.login_subtitle = 'Access your personal space';
  fr.login_email_label = 'ADRESSE EMAIL'; en.login_email_label = 'EMAIL ADDRESS';
  fr.login_email_placeholder = 'Votre adresse email'; en.login_email_placeholder = 'Your email address';
  fr.login_password_label = 'MOT DE PASSE'; en.login_password_label = 'PASSWORD';
  fr.login_password_placeholder = 'Votre mot de passe'; en.login_password_placeholder = 'Your password';
  fr.login_remember = 'SE SOUVENIR DE MOI'; en.login_remember = 'REMEMBER ME';
  fr.login_btn = 'SE CONNECTER'; en.login_btn = 'LOGIN';
  fr.login_register_link = 'CRÉER UN COMPTE'; en.login_register_link = 'CREATE ACCOUNT';
  fr.login_forgot_password = 'MOT DE PASSE OUBLIÉ ?'; en.login_forgot_password = 'FORGOT PASSWORD ?';

  fr.register_title = 'CRÉER UN COMPTE'; en.register_title = 'CREATE ACCOUNT';
  fr.register_subtitle = 'Rejoignez la communauté PosologyAI'; en.register_subtitle = 'Join the PosologyAI community';
  fr.register_section_main = 'INFORMATIONS PRINCIPALES'; en.register_section_main = 'MAIN INFORMATION';
  fr.register_email_label = 'ADRESSE EMAIL'; en.register_email_label = 'EMAIL ADDRESS';
  fr.register_email_placeholder = 'Votre adresse email'; en.register_email_placeholder = 'Your email address';
  fr.register_firstname_label = 'PRÉNOM'; en.register_firstname_label = 'FIRST NAME';
  fr.register_firstname_placeholder = 'Votre prénom'; en.register_firstname_placeholder = 'Your first name';
  fr.register_lastname_label = 'NOM'; en.register_lastname_label = 'LAST NAME';
  fr.register_lastname_placeholder = 'Votre nom'; en.register_lastname_placeholder = 'Your last name';
  fr.register_phone_label = 'TÉLÉPHONE'; en.register_phone_label = 'PHONE';
  fr.register_phone_placeholder = 'Votre numéro de téléphone'; en.register_phone_placeholder = 'Your phone number';
  fr.register_password_label = 'MOT DE PASSE'; en.register_password_label = 'PASSWORD';
  fr.register_password_placeholder = 'Créez un mot de passe sécurisé'; en.register_password_placeholder = 'Create a secure password';
  fr.register_confirm_label = 'CONFIRMER LE MOT DE PASSE'; en.register_confirm_label = 'CONFIRM PASSWORD';
  fr.register_confirm_placeholder = 'Confirmez votre mot de passe'; en.register_confirm_placeholder = 'Confirm your password';
  fr.register_profile_label = 'TYPE DE PROFIL'; en.register_profile_label = 'PROFILE TYPE';
  fr.register_profile_patient = 'Patient / Particulier'; en.register_profile_patient = 'Patient / Individual';
  fr.register_profile_professional = 'Professionnel de santé'; en.register_profile_professional = 'Healthcare professional';
  fr.register_profile_student = 'Étudiant'; en.register_profile_student = 'Student';
  fr.register_profile_other = 'Autre'; en.register_profile_other = 'Other';
  fr.register_terms = "J'accepte les conditions d'utilisation"; en.register_terms = 'I accept the terms of use';
  fr.register_btn = 'S\'INSCRIRE'; en.register_btn = 'SIGN UP';
  fr.register_login_link = 'DÉJÀ INSCRIT ?'; en.register_login_link = 'ALREADY REGISTERED ?';
  fr.register_login_btn = 'SE CONNECTER'; en.register_login_btn = 'LOGIN';
  fr.register_profile_choose = 'Choisir un type d\'utilisateur'; en.register_profile_choose = 'Choose a user type';
  fr.optional_label = 'Optionnel'; en.optional_label = 'Optional';
  fr.register_section_optional = 'INFORMATIONS COMPLÉMENTAIRES'; en.register_section_optional = 'ADDITIONAL INFORMATION';

  // Databases page
  fr.databases_title = 'Infrastructure des données'; en.databases_title = 'Data Infrastructure';
  fr.databases_desc = 'Architecture, statistiques et exploration interactive du graphe de connaissances'; en.databases_desc = 'Architecture, statistics and interactive knowledge graph exploration';
  fr.mongodb_title = 'MongoDB — Base documentaire'; en.mongodb_title = 'MongoDB — Document Database';
  fr.qdrant_title = 'Qdrant — Index vectoriel'; en.qdrant_title = 'Qdrant — Vector Index';
  fr.neo4j_title = 'Neo4j — Graphe de connaissances'; en.neo4j_title = 'Neo4j — Knowledge Graph';
  fr.connected = 'Connecté'; en.connected = 'Connected';
  fr.disconnected = 'Déconnecté'; en.disconnected = 'Disconnected';
  fr.total_documents = 'Documents'; en.total_documents = 'Documents';
  fr.collections = 'Collections'; en.collections = 'Collections';
  fr.types_medicaments = 'Types de médicaments'; en.types_medicaments = 'Medicine types';
  fr.top_laboratoires = 'Top laboratoires'; en.top_laboratoires = 'Top laboratories';
  fr.vecteurs = 'Vecteurs'; en.vecteurs = 'Vectors';
  fr.dimensions = 'Dimensions'; en.dimensions = 'Dimensions';
  fr.noeuds = 'Nœuds'; en.noeuds = 'Nodes';
  fr.relations = 'Relations'; en.relations = 'Relations';
  fr.interactions = 'Interactions'; en.interactions = 'Interactions';
  fr.search_medicine = 'Rechercher un médicament'; en.search_medicine = 'Search medicine';
  fr.visualiser = 'Visualiser'; en.visualiser = 'Visualize';
  fr.graphe_global = 'Graphe global'; en.graphe_global = 'Global graph';
  fr.medicament = 'Médicament'; en.medicament = 'Medicine';
  fr.substances = 'Substances'; en.substances = 'Substances';
  fr.statistiques = 'Statistiques'; en.statistiques = 'Statistics';
  fr.haute = 'Haute'; en.haute = 'High';
  fr.moderée = 'Modérée'; en.moderée = 'Moderate';
  fr.basse = 'Basse'; en.basse = 'Low';
  fr.index_vectoriel = 'Index vectoriel'; en.index_vectoriel = 'Vector Index';
  fr.embeddings = 'embeddings'; en.embeddings = 'embeddings';

  // Dashboard page
  fr.dashboard_title = 'Dashboard'; en.dashboard_title = 'Dashboard';
  fr.dashboard_desc = 'Statistiques en temps réel, analyses et exploration du graphe de connaissances'; en.dashboard_desc = 'Real-time statistics, analytics and knowledge graph exploration';
  fr.medicaments = 'Médicaments'; en.medicaments = 'Medications';
  fr.laboratoires = 'Laboratoires'; en.laboratoires = 'Laboratories';
  fr.types = 'Types'; en.types = 'Types';
  fr.top_interactions = 'Top interactions médicamenteuses'; en.top_interactions = 'Top drug interactions';
  fr.graphe_interactions = "Graphe d'interactions Neo4j"; en.graphe_interactions = 'Neo4j Interaction Graph';
  fr.chargement = 'Chargement...'; en.chargement = 'Loading...';
  fr.aucune_donnee = 'Aucune donnée'; en.aucune_donnee = 'No data';

  /* La legende du graphe et l'attente du tableau de bord. Les quatre
   * premieres sont au singulier : ce sont des categories de noeud, pas des
   * compteurs — `medicaments` et `laboratoires`, au pluriel, servent deja
   * aux tuiles de chiffres juste au-dessus. */
  /* ── La page « Bases de donnees » ──────────────────────────────────────
   *
   * Les intitules de ses cartes et de ses legendes. Les noms de produits
   * (MongoDB, Qdrant, Neo4j) et le type de relation INTERACTS_WITH restent
   * tels quels : ce sont des identifiants, pas des libelles. */
  fr.db_types_medicaments = 'Types de médicaments'; en.db_types_medicaments = 'Medicine types';
  fr.db_top_laboratoires = 'Top laboratoires'; en.db_top_laboratoires = 'Top laboratories';
  fr.db_collection = 'Collection'; en.db_collection = 'Collection';
  fr.db_espace_vectoriel = 'Espace vectoriel'; en.db_espace_vectoriel = 'Vector space';
  fr.db_noeuds = 'Nœuds'; en.db_noeuds = 'Nodes';
  fr.db_relations = 'Relations'; en.db_relations = 'Relationships';
  fr.db_meds_interactions = 'Médicaments avec interactions'; en.db_meds_interactions = 'Medicines with interactions';
  fr.db_rels_interacts = 'Relations INTERACTS_WITH'; en.db_rels_interacts = 'INTERACTS_WITH relationships';
  fr.db_med_central = 'Médicament central'; en.db_med_central = 'Central medicine';
  fr.db_subst_labo_type = 'Substance / Labo / Type'; en.db_subst_labo_type = 'Substance / Lab / Type';
  fr.db_inter_haute = 'Interaction haute'; en.db_inter_haute = 'High interaction';
  fr.db_inter_moderee = 'Interaction modérée'; en.db_inter_moderee = 'Moderate interaction';
  fr.db_inter_basse = 'Interaction basse'; en.db_inter_basse = 'Low interaction';
  fr.db_graphe_inter = 'Graphe des interactions entre médicaments'; en.db_graphe_inter = 'Graph of interactions between medicines';
  fr.db_repartition_noeuds = 'Répartition des nœuds'; en.db_repartition_noeuds = 'Node distribution';
  fr.db_repartition_relations = 'Répartition des relations'; en.db_repartition_relations = 'Relationship distribution';
  fr.db_top_meds = "Top médicaments par nombre d'interactions"; en.db_top_meds = 'Top medicines by number of interactions';
  fr.db_qdrant_insight = "Recherche sémantique vectorielle en temps réel sur l'ensemble des notices médicamenteuses. Les embeddings permettent une recherche par similarité de sens plutôt que par mots-clés exacts.";
  en.db_qdrant_insight = 'Real-time vector semantic search across all medicine leaflets. Embeddings allow searching by similarity of meaning rather than by exact keywords.';

  /* Les encadres de synthese melent une phrase et un nombre calcule. Le
   * nombre reste hors de la cle : une cle ne peut pas accueillir de valeur,
   * et le decoupage est fait pour que l'ordre des mots tienne dans les
   * trois langues — « 12 types de medicaments referencés » devient
   * « 12 medicine types referenced » sans deplacer le chiffre. */
  fr.db_insight_types = 'types de médicaments référencés.'; en.db_insight_types = 'medicine types referenced.';
  fr.db_insight_labs = 'laboratoires principaux.'; en.db_insight_labs = 'main laboratories.';
  fr.db_insight_base = 'Base documentaire de référence pour les médicaments français contenant';
  en.db_insight_base = 'Reference document store for French medicines, containing';
  fr.db_insight_documents = 'documents.'; en.db_insight_documents = 'documents.';
  fr.db_representation = 'Représentation des'; en.db_representation = 'Representation of the';
  fr.db_dimensions_min = 'dimensions'; en.db_dimensions_min = 'dimensions';
  fr.db_neo4j_insight = 'Graphe de connaissances médicamenteuses complet. Explorez les interactions en direct ci-dessus.';
  en.db_neo4j_insight = 'Complete medicines knowledge graph. Explore the interactions live above.';
  fr.db_chip_recherche = 'Vectorielle · Hybride'; en.db_chip_recherche = 'Vector · Hybrid';
  fr.db_chip_appli = 'Flask · IA · Ordonnances'; en.db_chip_appli = 'Flask · AI · Prescriptions';

  ar.db_insight_types = 'من أنواع الأدوية المُدرجة.';
  ar.db_insight_labs = 'من المختبرات الرئيسية.';
  ar.db_insight_base = 'قاعدة وثائقية مرجعية للأدوية الفرنسية تضم';
  ar.db_insight_documents = 'وثيقة.';
  ar.db_representation = 'تمثيل الـ';
  ar.db_dimensions_min = 'بُعد';
  ar.db_neo4j_insight = 'رسم معرفي كامل للأدوية. استكشف التفاعلات مباشرة أعلاه.';
  ar.db_chip_recherche = 'متجهي · هجين';
  ar.db_chip_appli = 'Flask · ذكاء اصطناعي · وصفات';

  ar.db_types_medicaments = 'أنواع الأدوية';
  ar.db_top_laboratoires = 'أبرز المختبرات';
  ar.db_collection = 'مجموعة';
  ar.db_espace_vectoriel = 'الفضاء المتجهي';
  ar.db_noeuds = 'العقد';
  ar.db_relations = 'العلاقات';
  ar.db_meds_interactions = 'أدوية ذات تفاعلات';
  ar.db_rels_interacts = 'علاقات INTERACTS_WITH';
  ar.db_med_central = 'الدواء المركزي';
  ar.db_subst_labo_type = 'مادة / مختبر / نوع';
  ar.db_inter_haute = 'تفاعل مرتفع';
  ar.db_inter_moderee = 'تفاعل متوسط';
  ar.db_inter_basse = 'تفاعل منخفض';
  ar.db_graphe_inter = 'رسم تفاعلات الأدوية';
  ar.db_repartition_noeuds = 'توزيع العقد';
  ar.db_repartition_relations = 'توزيع العلاقات';
  ar.db_top_meds = 'أبرز الأدوية حسب عدد التفاعلات';
  ar.db_qdrant_insight = 'بحث دلالي متجهي آني في كل نشرات الأدوية. تتيح التضمينات البحث بتشابه المعنى بدل الكلمات المفتاحية الحرفية.';

  fr.dash_chargement = 'Chargement du tableau de bord...'; en.dash_chargement = 'Loading the dashboard...';
  fr.dash_en_interaction = 'En interaction'; en.dash_en_interaction = 'Interacting';
  fr.substance = 'Substance'; en.substance = 'Substance';
  fr.laboratoire = 'Laboratoire'; en.laboratoire = 'Laboratory';
  fr.severite_haute = 'Haute sévérité'; en.severite_haute = 'High severity';

  ar.dash_chargement = 'جارٍ تحميل لوحة القيادة...';
  ar.dash_en_interaction = 'متفاعل';
  ar.substance = 'مادة';
  ar.laboratoire = 'مختبر';
  ar.severite_haute = 'خطورة مرتفعة';

  // Profile / Favorites / Common
  fr.profile_title = 'Mon profil'; en.profile_title = 'My Profile';
  fr.favorites_title = 'Mes favoris'; en.favorites_title = 'My Favorites';
  fr.admin_database = 'Administration base de données'; en.admin_database = 'Database Administration';
  fr.page_not_found = 'Page non trouvée'; en.page_not_found = 'Page Not Found';
  fr.server_error = 'Erreur serveur'; en.server_error = 'Server Error';
  fr.retour_accueil = 'Retour à l\'accueil'; en.retour_accueil = 'Back to home';
  fr.donnees_techniques = 'Données techniques'; en.donnees_techniques = 'Technical Data';
  fr.pipeline_donnees = 'Pipeline de données'; en.pipeline_donnees = 'Data Pipeline';
  fr.sources = 'Sources'; en.sources = 'Sources';
  fr.enrichissement = 'Enrichissement'; en.enrichissement = 'Enrichment';
  fr.stockage = 'Stockage'; en.stockage = 'Storage';
  fr.recherche = 'Recherche'; en.recherche = 'Search';
  fr.application = 'Application'; en.application = 'Application';
  fr.voir_details = 'Voir les détails'; en.voir_details = 'Show details';
  fr.voir_graphe = 'Voir le graphe'; en.voir_graphe = 'Show graph';
  fr.charge = 'Chargé'; en.charge = 'Loaded';
  fr.reessayer = 'Réessayer'; en.reessayer = 'Retry';
  fr.profile_subtitle = 'Gérez vos informations personnelles'; en.profile_subtitle = 'Manage your personal information';
  fr.profile_personal_info = 'Informations personnelles'; en.profile_personal_info = 'Personal Information';
  fr.profile_security = 'Sécurité'; en.profile_security = 'Security';
  fr.logout = 'Déconnexion'; en.logout = 'Logout';
  fr.favorites_subtitle = 'Consultez et gérez vos médicaments favoris'; en.favorites_subtitle = 'View and manage your favorite medications';
  fr.retirer_favoris = 'Retirer des favoris'; en.retirer_favoris = 'Remove from favorites';
  fr.rechercher_medicaments = 'Rechercher des médicaments'; en.rechercher_medicaments = 'Search medications';
  fr.no_favorites = 'Aucun favori'; en.no_favorites = 'No favorites';
  fr.favorites_empty_desc = 'Vous n\'avez pas encore ajouté de médicaments à vos favoris.'; en.favorites_empty_desc = 'You haven\'t added any medications to your favorites yet.';

  // ── Arabe ──────────────────────────────────────────────────────────
  // Une cle absente ici retombe sur l anglais puis le francais :
  // getStaticTranslation gere deja cette chaine de repli.

  ar.home = 'الرئيسية';
  ar.search = 'بحث';
  ar.about = 'حول';
  ar.contact = 'اتصل بنا';
  ar.index_title = 'PosologyAI • قاعدة بيانات الأدوية';
  ar.hero_title_line1 = 'صحتك،';
  ar.hero_title_line2 = 'مدعومة بالبيانات';
  ar.hero_subtitle = 'اطّلع على آلاف نشرات الأدوية، وحلّل التفاعلات، واحصل على ملخصات ذكية بنقرة واحدة.';
  ar.trusted_medical_db = 'قاعدة بيانات طبية موثوقة';
  ar.start_exploring = 'استكشاف الأدوية';
  ar.try_ai_search = 'بحث ذكي';
  ar.stat_medicines = 'الأدوية';
  ar.stat_substances = 'المواد الفعّالة';
  ar.stat_interactions = 'التفاعلات';
  ar.stat_availability = 'إمكانية الوصول';
  ar.how_it_works = 'كيف يعمل';
  ar.process_title = 'منهجيتنا';
  ar.process_subtitle = 'من البحث إلى الاكتشاف';
  ar.step1_title = 'ابحث';
  ar.step1_desc = 'ابحث عن دواء بالاسم أو المادة الفعّالة أو العَرَض';
  ar.step2_title = 'حلّل';
  ar.step2_desc = 'راجع التفاعلات وملخصات الذكاء الاصطناعي والبيانات التفصيلية';
  ar.step3_title = 'قرّر';
  ar.step3_desc = 'استعن بالمعلومات لاتخاذ قراراتك الطبية';
  ar.ai_powered = 'مدعوم بالذكاء الاصطناعي';
  ar.ai_feature_title = 'الذكاء الاصطناعي في خدمة الصحة';
  ar.ai_feature_text1 = 'يحلّل محرّكنا آلاف البيانات ليقدّم لك ملخصات واضحة وموثوقة عن كل دواء.';
  ar.ai_feature_text2 = 'البحث الدلالي وتحليل التفاعلات وتوليد الوصفات الذكية: الذكاء الاصطناعي يغيّر طريقة وصولك إلى المعلومة الطبية.';
  ar.try_ai_now = 'جرّب الذكاء الاصطناعي الآن';
  ar.ai_processing = 'جارٍ التحليل...';
  ar.visualization = 'التصور البياني';
  ar.results_title = 'نتائج ذكية';
  ar.results_subtitle = 'تحليلات دقيقة في ثوانٍ';
  ar.trust_data = 'بيانات موثوقة';
  ar.trust_data_desc = 'مصادر رسمية تُحدَّث بانتظام';
  ar.trust_privacy = 'الخصوصية';
  ar.trust_privacy_desc = 'بياناتك محمية ولا تُشارَك أبدًا';
  ar.trust_academic = 'بحث أكاديمي';
  ar.trust_academic_desc = 'طُوِّر في إطار جامعي';
  ar.trust_comprehensive = 'قاعدة شاملة';
  ar.trust_comprehensive_desc = 'آلاف الأدوية المُفهرسة';
  ar.features = 'الميزات';
  ar.features_title = 'لماذا POSOLOGYAI؟';
  ar.features_subtitle = 'اكتشف كل إمكانات PosologyAI';
  ar.feature_search = 'بحث ذكي';
  ar.feature_search_desc = 'اعثر بسرعة على ما تبحث عنه';
  ar.feature_vector = 'بحث دلالي';
  ar.feature_vector_desc = 'اعثر على الأدوية بالتشابه الدلالي';
  ar.feature_ai = 'ملخّص بالذكاء الاصطناعي';
  ar.feature_ai_desc = 'ملخصات ذكية لكل دواء';
  ar.feature_chatbot = 'مساعد PosologyBot';
  ar.feature_chatbot_desc = 'اطرح أسئلتك بلغة طبيعية';
  ar.feature_prescription = 'مساعدة على الوصف الطبي';
  ar.feature_prescription_desc = 'أنشئ وصفات طبية حسب التشخيص';
  ar.explore_database = 'استكشاف قاعدة البيانات';
  ar.about_title = 'PosologyAI — مشروع أكاديمي';
  ar.about_text1 = 'PosologyAI مبادرة أكاديمية طُوِّرت في إطار SAE5.01 لتوفير وصول سهل وموثوق إلى معلومات الأدوية.';
  ar.about_text2 = 'هدفنا هو تجميع بيانات الأدوية وإتاحتها، بما يمكّن المستخدمين من العثور بسرعة على ما يحتاجونه.';
  ar.nav_search = 'بحث';
  ar.nav_classic = 'بحث تقليدي';
  ar.nav_classic_desc = 'بالاسم أو المادة الفعّالة أو المختبر';
  ar.nav_vector = 'بحث دلالي';
  ar.nav_vector_desc = 'بحث دلالي متقدّم';
  ar.nav_ai = 'بحث بالذكاء الاصطناعي';
  ar.nav_ai_desc = 'لغة طبيعية';
  ar.nav_prescription = 'الوصفة الطبية';
  ar.nav_databases = 'قواعد البيانات';
  ar.nav_dashboard = 'لوحة المتابعة';
  ar.login = 'تسجيل الدخول';
  ar.profile = 'ملفي الشخصي';
  ar.favorites = 'مفضّلاتي';
  ar.admin = 'الإدارة';
  ar.logout = 'تسجيل الخروج';
  ar.chatbot_welcome = 'مرحبًا! أنا **PosologyBot**، مساعدك الطبي الذكي.\nيمكنني إفادتك بشأن الأدوية ودواعي استعمالها وجرعاتها وتفاعلاتها.';
  ar.chatbot_input_placeholder = 'اطرح سؤالك...';
  ar.chatbot_disclaimer = 'المعلومات المقدَّمة إرشادية فقط. استشر مختصًّا في الرعاية الصحية.';
  ar.chatbot_suggestions = 'اقتراحات:';
  ar.chatbot_online = 'متصل';
  ar.chatbot_clear = 'مسح المحادثة';
  ar.chatbot_close = 'إغلاق';
  ar.just_now = 'الآن';
  ar.menu_prescription = 'قائمة الوصفة';
  ar.patient_info = 'معلومات المريض';
  ar.homme = 'ذكر';
  ar.femme = 'أنثى';
  ar.autre = 'أخرى';
  ar.submit_btn = 'تحليل';
  ar.reset_btn = 'إعادة تعيين';
  ar.loading = 'جارٍ التحميل...';
  ar.interactions_title = 'التفاعلات المكتشفة';
  ar.ai_diagnosis_title = 'تحليل بالذكاء الاصطناعي';
  ar.suggested_medications = 'الأدوية المقترحة';
  ar.ecartes_title = 'الأدوية المستبعدة';
  ar.recommendations_title = 'التوصيات';
  ar.generate_pdf = 'إنشاء ملف PDF';
  ar.instructions_title = 'التعليمات';
  ar.instructions_text = 'املأ معلومات المريض وصف التشخيص للحصول على تحليل كامل.';
  ar.medical_diagnosis = 'التشخيص الطبي';
  ar.patient_name = 'اسم المريض';
  ar.optional = 'اختياري';
  ar.age = 'العمر';
  ar.height = 'الطول (سم)';
  ar.weight = 'الوزن (كغ)';
  ar.gender = 'الجنس';
  ar.gender_unspecified = 'غير محدَّد';
  ar.gender_male = 'ذكر';
  ar.gender_female = 'أنثى';
  ar.gender_other = 'أخرى';
  ar.medical_history = 'السوابق المرضية';
  ar.current_medications = 'الأدوية الحالية';
  ar.diagnosis = 'التشخيص';
  ar.diagnostic_tip = 'صف الأعراض أو المرض المشتبه به أو التحاليل المتوفّرة';
  ar.analyze_button = 'بدء التحليل';
  ar.reset_button = 'إعادة تعيين';
  ar.analyzing = 'جارٍ التحليل';
  ar.analyzing_details = 'يحلّل الذكاء الاصطناعي البيانات ويبحث عن الأدوية المناسبة...';
  ar.vectorial = 'دلالي';
  ar.data = 'البيانات';
  ar.relations = 'العلاقات';
  ar.interactions_detected = 'التفاعلات المكتشفة';
  ar.medications_suggested = 'الأدوية المقترحة';
  ar.prescription_summary = 'ملخّص الوصفة الطبية';
  ar.patient_name_placeholder = 'أدخل اسم المريض';
  ar.age_placeholder = 'مثال: 45';
  ar.height_placeholder = 'مثال: 170';
  ar.weight_placeholder = 'مثال: 70';
  ar.medical_history_placeholder = 'مثال: السكري، ارتفاع ضغط الدم...';
  ar.current_medications_placeholder = 'مثال: ميتفورمين 850 ملغ...';
  ar.diagnostic_placeholder = 'مثال: متلازمة شبيهة بالإنفلونزا مع حمّى تتجاوز 38.5 °م منذ ثلاثة أيام';
  ar.prescription_help_title = 'مساعدة على الوصف الطبي';
  ar.prescription_help_subtitle = 'مقاربتان متكاملتان لوصفاتك الطبية';
  ar.start_diagnostic = 'بدء التشخيص';
  ar.prescribe_medications = 'وصف الأدوية';
  ar.classic_search_title = 'بحث تقليدي';
  ar.try_classic_search = 'بحث تقليدي';
  ar.try_keywords = 'بحث بالكلمات المفتاحية';
  ar.all_active_substances = 'جميع المواد الفعّالة';
  ar.all_pharmaceutical_forms = 'جميع الأشكال الصيدلانية';
  ar.all_laboratories = 'جميع المختبرات';
  ar.all_dosages = 'جميع الجرعات';
  ar.all_therapeutic_families_atc = 'جميع الفئات العلاجية (ATC)';
  ar.all_medicine_types = 'جميع أنواع الأدوية';
  ar.search_placeholder = 'ابحث بالاسم أو المادة الفعّالة أو المختبر...';
  ar.vector_search_title = 'بحث دلالي';
  ar.results = 'النتائج';
  ar.ai_search_title = 'بحث بالذكاء الاصطناعي';
  ar.ai_results = 'النتائج';
  ar.ai_search_placeholder = 'صف ما تبحث عنه...';
  ar.requete_reformulee = 'الطلب بعد إعادة صياغته بالذكاء الاصطناعي:';
  ar.score_label = 'الدرجة';
  ar.ai_answer_title = 'رد الذكاء الاصطناعي';
  ar.ai_answer_sub = 'ملخّص مُنشأ من نشرات قاعدة بيانات PosologyAI';
  ar.ai_searching = 'يقوم الذكاء الاصطناعي بتحليل سؤالك...';
  ar.ai_sources_title = 'الأدوية المطابقة';
  ar.no_ai_results = 'لا توجد نتائج.';
  ar.ai_disclaimer = 'هذه المعلومات للاسترشاد فقط ولا تُغني عن استشارة أخصائي الرعاية الصحية.';
  ar.card_general_info = 'معلومات عامة';
  ar.label_trade_name = 'الاسم التجاري';
  ar.label_active_substance = 'المادة الفعّالة';
  ar.label_pharmaceutical_form = 'الشكل الصيدلاني';
  ar.label_laboratory = 'المختبر';
  ar.tag_analgesic = 'مسكّن للألم';
  ar.tag_antipyretic = 'خافض للحرارة';
  ar.tag_who_level1 = 'المستوى 1 حسب منظمة الصحة العالمية';
  ar.card_interactions_title = 'التفاعلات المكتشفة';
  ar.label_severe_interactions = 'تفاعلات خطيرة';
  ar.label_moderate_interactions = 'تفاعلات متوسطة';
  ar.label_minor_interactions = 'تفاعلات طفيفة';
  ar.tag_ai_analysis = 'تحليل بالذكاء الاصطناعي';
  ar.tag_database = 'قاعدة البيانات';
  ar.tag_neo4j_relations = 'علاقات Neo4j';
  ar.footer_rights = 'جميع الحقوق محفوظة.';
  ar.footer_educational = 'هذا الموقع مُعدّ لأغراض تعليمية فقط.';
  ar.login_title = 'تسجيل الدخول';
  ar.login_subtitle = 'ادخل إلى مساحتك الشخصية';
  ar.login_email_label = 'البريد الإلكتروني';
  ar.login_email_placeholder = 'بريدك الإلكتروني';
  ar.login_password_label = 'كلمة المرور';
  ar.login_password_placeholder = 'كلمة المرور الخاصة بك';
  ar.login_remember = 'تذكّرني';
  ar.login_btn = 'تسجيل الدخول';
  ar.login_register_link = 'إنشاء حساب';
  ar.login_forgot_password = 'هل نسيت كلمة المرور؟';
  ar.register_title = 'إنشاء حساب';
  ar.register_subtitle = 'انضم إلى مجتمع PosologyAI';
  ar.register_section_main = 'المعلومات الأساسية';
  ar.register_email_label = 'البريد الإلكتروني';
  ar.register_email_placeholder = 'بريدك الإلكتروني';
  ar.register_firstname_label = 'الاسم';
  ar.register_firstname_placeholder = 'اسمك';
  ar.register_lastname_label = 'اللقب';
  ar.register_lastname_placeholder = 'لقبك';
  ar.register_phone_label = 'الهاتف';
  ar.register_phone_placeholder = 'رقم هاتفك';
  ar.register_password_label = 'كلمة المرور';
  ar.register_password_placeholder = 'أنشئ كلمة مرور آمنة';
  ar.register_confirm_label = 'تأكيد كلمة المرور';
  ar.register_confirm_placeholder = 'أكّد كلمة المرور';
  ar.register_profile_label = 'نوع الحساب';
  ar.register_profile_patient = 'مريض / فرد';
  ar.register_profile_professional = 'مختصّ في الرعاية الصحية';
  ar.register_profile_student = 'طالب';
  ar.register_profile_other = 'أخرى';
  ar.register_terms = 'أوافق على شروط الاستخدام';
  ar.register_btn = 'تسجيل';
  ar.register_login_link = 'مسجَّل بالفعل؟';
  ar.register_login_btn = 'تسجيل الدخول';
  ar.register_profile_choose = 'اختر نوع المستخدم';
  ar.optional_label = 'اختياري';
  ar.register_section_optional = 'معلومات إضافية';
  ar.databases_title = 'بنية البيانات';
  ar.databases_desc = 'البنية والإحصاءات والاستكشاف التفاعلي لرسم المعرفة';
  ar.mongodb_title = 'MongoDB — قاعدة بيانات وثائقية';
  ar.qdrant_title = 'Qdrant — فهرس دلالي';
  ar.neo4j_title = 'Neo4j — رسم المعرفة';
  ar.connected = 'متصل';
  ar.disconnected = 'غير متصل';
  ar.total_documents = 'الوثائق';
  ar.collections = 'المجموعات';
  ar.types_medicaments = 'أنواع الأدوية';
  ar.top_laboratoires = 'أبرز المختبرات';
  ar.vecteurs = 'المتجهات';
  ar.dimensions = 'الأبعاد';
  ar.noeuds = 'العُقد';
  ar.interactions = 'التفاعلات';
  ar.search_medicine = 'ابحث عن دواء';
  ar.visualiser = 'عرض بياني';
  ar.graphe_global = 'الرسم الشامل';
  ar.medicament = 'دواء';
  ar.substances = 'المواد';
  ar.statistiques = 'الإحصاءات';
  ar.haute = 'مرتفعة';
  ar.moderée = 'متوسطة';
  ar.basse = 'منخفضة';
  ar.index_vectoriel = 'الفهرس الدلالي';
  ar.embeddings = 'التمثيلات المتجهية';
  ar.dashboard_title = 'لوحة المتابعة';
  ar.dashboard_desc = 'إحصاءات آنية وتحليلات واستكشاف لرسم المعرفة';
  ar.medicaments = 'الأدوية';
  ar.laboratoires = 'المختبرات';
  ar.types = 'الأنواع';
  ar.top_interactions = 'أبرز التفاعلات الدوائية';
  ar.graphe_interactions = 'رسم التفاعلات Neo4j';
  ar.chargement = 'جارٍ التحميل...';
  ar.aucune_donnee = 'لا توجد بيانات';
  ar.profile_title = 'ملفي الشخصي';
  ar.favorites_title = 'مفضّلاتي';
  ar.admin_database = 'إدارة قاعدة البيانات';
  ar.page_not_found = 'الصفحة غير موجودة';
  ar.server_error = 'خطأ في الخادم';
  ar.retour_accueil = 'العودة إلى الرئيسية';
  ar.donnees_techniques = 'بيانات تقنية';
  ar.pipeline_donnees = 'سلسلة معالجة البيانات';
  ar.sources = 'المصادر';
  ar.enrichissement = 'الإثراء';
  ar.stockage = 'التخزين';
  ar.recherche = 'البحث';
  ar.application = 'التطبيق';
  ar.voir_details = 'عرض التفاصيل';
  ar.voir_graphe = 'عرض الرسم';
  ar.charge = 'تم التحميل';
  ar.reessayer = 'إعادة المحاولة';
  ar.profile_subtitle = 'أدر معلوماتك الشخصية';
  ar.profile_personal_info = 'المعلومات الشخصية';
  ar.profile_security = 'الأمان';
  ar.favorites_subtitle = 'اطّلع على أدويتك المفضّلة وأدرها';
  ar.retirer_favoris = 'إزالة من المفضّلة';
  ar.rechercher_medicaments = 'البحث عن أدوية';
  ar.no_favorites = 'لا توجد مفضّلات';
  ar.favorites_empty_desc = 'لم تضف أي دواء إلى مفضّلاتك بعد.';
}

initStaticTranslations();

/* La clé sous laquelle la langue choisie est retenue.
 *
 * Il y en avait deux. Ce fichier écrivait `posologyai_lang` ; cinq
 * gabarits — recherche vectorielle, recherche IA, assistant, diagnostic,
 * menu de prescription — lisaient `preferred_lang` et ne voyaient donc
 * jamais le choix du sélecteur. Ils traduisaient d'après une préférence
 * que plus personne n'écrivait.
 *
 * Nommée ici, exportée sur `window` : les gabarits la lisent au lieu de
 * réécrire la chaîne, et une troisième clé ne peut plus apparaître par
 * copie approximative. */
const CLE_LANGUE = 'posologyai_lang';

let currentLang = 'fr';

function getLangDir(lang) {
  return LANGUAGES[lang] ? LANGUAGES[lang].dir : 'ltr';
}

function getFlag(lang) {
  return LANGUAGES[lang] ? LANGUAGES[lang].flag : '🌐';
}

function getLangLabel(lang) {
  return LANGUAGES[lang] ? LANGUAGES[lang].label : lang;
}

/* `loadApiTranslations` a été retirée avec les trois langues qui en
 * dépendaient. Elle interrogeait `/api/translate/batch`, mettait le
 * résultat en cache dans `localStorage`, et c'était le seul endroit du
 * moteur qui touchait au réseau. La route côté serveur existe toujours ;
 * plus rien ici ne l'appelle. */

function getStaticTranslation(key, lang) {
  if (STATIC_TRANSLATIONS[lang] && STATIC_TRANSLATIONS[lang][key]) {
    return STATIC_TRANSLATIONS[lang][key];
  }
  if (lang === 'fr') return STATIC_TRANSLATIONS.fr[key] || key;

  /* Repli en cascade : arabe manquant -> anglais -> français -> la clé
   * elle-même. Montrer la clé brute serait pire que de montrer une autre
   * langue, mais laisser un blanc serait pire encore. */
  if (STATIC_TRANSLATIONS.en && STATIC_TRANSLATIONS.en[key]) {
    return STATIC_TRANSLATIONS.en[key];
  }
  return STATIC_TRANSLATIONS.fr[key] || key;
}

function translatePage() {
  const lang = currentLang;
  const dir = getLangDir(lang);

  document.documentElement.lang = lang;
  document.documentElement.dir = dir;

  document.querySelectorAll('[data-i18n]').forEach(el => {
    const key = el.getAttribute('data-i18n');
    const text = getStaticTranslation(key, lang);
    if (text) el.innerHTML = text;
  });

  document.querySelectorAll('[data-i18n-placeholder]').forEach(el => {
    const key = el.getAttribute('data-i18n-placeholder');
    const text = getStaticTranslation(key, lang);
    if (text) el.placeholder = text;
  });

  document.querySelectorAll('[data-i18n-title]').forEach(el => {
    const key = el.getAttribute('data-i18n-title');
    const text = getStaticTranslation(key, lang);
    if (text) el.title = text;
  });

  /* Les intitulés de formulaire.
   *
   * `data-i18n-label` existait déjà dans l'assistant de prescription,
   * sur huit `<label>` — nom, prénom, taille, poids, genre, symptômes,
   * antécédents, traitements en cours. Le moteur ne l'a jamais lu : ces
   * huit intitulés sont restés en français dans toutes les langues
   * depuis qu'ils ont été écrits.
   *
   * `textContent` et non `innerHTML` : ces nœuds contiennent parfois une
   * icône voisine, et réécrire le HTML l'emporterait. */
  document.querySelectorAll('[data-i18n-label]').forEach(el => {
    const key = el.getAttribute('data-i18n-label');
    const text = getStaticTranslation(key, lang);
    if (text) el.textContent = text;
  });

  /* Les libellés que seuls les lecteurs d'écran entendent.
   *
   * Attribut distinct de `data-i18n-label`, qui désigne un intitulé
   * visible. Les confondre ferait écrire un `aria-label` sur un `<label>`
   * — invisible et sans effet — ou remplacerait le texte d'un bouton par
   * la description destinée aux lecteurs d'écran.
   *
   * Sans lui, un utilisateur voyant passait toute l'interface en arabe
   * pendant qu'un utilisateur aveugle continuait d'entendre « Afficher la
   * navigation » en français : la traduction s'arrêtait exactement là où
   * on ne la voyait pas. */
  document.querySelectorAll('[data-i18n-aria]').forEach(el => {
    const key = el.getAttribute('data-i18n-aria');
    const text = getStaticTranslation(key, lang);
    if (text) el.setAttribute('aria-label', text);
  });

  const switcher = document.getElementById('langSwitcherBtn');
  if (switcher) {
    const flag = getFlag(lang);
    const label = getLangLabel(lang);
    const flagEl = switcher.querySelector('.lang-flag');
    const labelEl = switcher.querySelector('.lang-label');
    if (flagEl) flagEl.textContent = flag;
    if (labelEl) labelEl.textContent = label;
  }

  const currentFlag = document.getElementById('currentLangFlag');
  const currentLabel = document.getElementById('currentLangLabel');
  if (currentFlag) currentFlag.textContent = getFlag(lang);
  if (currentLabel) currentLabel.textContent = getLangLabel(lang);

  if (dir === 'rtl') {
    document.body.classList.add('rtl');
  } else {
    document.body.classList.remove('rtl');
  }

  document.querySelectorAll('.chatbot-name, .chatbot-toggle, .chatbot-header-btn').forEach(el => {
    el.style.direction = dir;
  });
}

/* Aucun `await`, aucun `fetch` : les trois tables sont déjà en mémoire
 * quand ce fichier a fini de se charger. Le seul coût est le parcours
 * du DOM, quelques millisecondes.
 *
 * Elle était `async` et attendait le réseau pour toute langue autre que
 * le français et l'anglais. Le mot-clé est retiré plutôt que laissé par
 * prudence : une fonction `async` que personne n'attend rend une
 * promesse ignorée, et le prochain lecteur croirait qu'il reste une
 * attente à gérer. */
/* Le serveur lit la langue dans un cookie, jamais dans localStorage.
 *
 * 148 libelles sont poses par `libelle()` cote serveur — 136 sur la seule
 * fiche medicament. Le selecteur n'ecrivait que localStorage : le choix ne
 * franchissait pas le reseau, et ces libelles restaient en francais
 * pendant que le reste de la page basculait.
 *
 * Un an de duree, `SameSite=Lax` : le cookie ne sert qu'a l'affichage et
 * ne doit pas voyager sur des requetes tierces. */
function poserCookieLangue(lang) {
  const an = 60 * 60 * 24 * 365;
  document.cookie = 'preferred_lang=' + encodeURIComponent(lang) +
    ';path=/;max-age=' + an + ';SameSite=Lax';
}

function switchLanguage(lang) {
  if (lang === currentLang) return;
  if (!LANGUAGES[lang]) return;

  currentLang = lang;
  localStorage.setItem(CLE_LANGUE, lang);
  poserCookieLangue(lang);

  /* Les pages dont le serveur a pose les libelles ne peuvent pas basculer
   * dans le navigateur : leur texte n'est pas dans la table cliente. Elles
   * se signalent par `data-langue-serveur`, et on les recharge — le cookie
   * vient d'etre ecrit, le serveur rendra la bonne langue.
   *
   * Les autres gardent la bascule instantanee, sans requete. */
  if (document.body && document.body.dataset.langueServeur) {
    location.reload();
    return;
  }

  translatePage();
  translateDynamicContent();

  /* Les widgets qui construisent leur contenu en JS (suggestions du
   * chatbot, messages reconstruits...) ne peuvent pas suivre le parcours
   * DOM de translatePage : un evenement leur signale la nouvelle langue,
   * sans timer ni relecture de localStorage. */
  document.dispatchEvent(new CustomEvent('posologyai:langue', { detail: { lang: lang } }));
}

function translateDynamicContent() {
  const lang = currentLang;
  if (lang === 'fr') return;

  document.querySelectorAll('.translatable-form').forEach(el => {
    if (!el.dataset.originalFr) el.dataset.originalFr = el.textContent;
    const fr = el.dataset.originalFr;
    if (lang === 'en' && STATIC_TRANSLATIONS.en[fr]) {
      el.textContent = STATIC_TRANSLATIONS.en[fr];
    } else if (fr) {
      el.textContent = translatePharmaForm(fr, lang);
    }
  });

  document.querySelectorAll('.translatable-type').forEach(el => {
    if (!el.dataset.originalFr) el.dataset.originalFr = el.textContent;
    const fr = el.dataset.originalFr;
    if (lang === 'en' && medicineTypeTranslations[fr]) {
      el.textContent = medicineTypeTranslations[fr];
    }
  });

  document.querySelectorAll('.translatable-family').forEach(el => {
    if (!el.dataset.originalFr) el.dataset.originalFr = el.textContent;
    const fr = el.dataset.originalFr;
    if (lang === 'en' && therapeuticFamilyTranslations[fr]) {
      el.textContent = therapeuticFamilyTranslations[fr];
    }
  });

  translateFormsDropdown(lang !== 'fr');
}

function translatePharmaForm(frenchText, targetLang) {
  if (!frenchText) return frenchText;
  if (targetLang === 'fr') return frenchText;
  if (targetLang === 'en') {
    const pharmaKeywords = {
      'comprimé': 'tablet', 'gélule': 'capsule', 'capsule': 'capsule',
      'solution': 'solution', 'suspension': 'suspension', 'sirop': 'syrup',
      'poudre': 'powder', 'granulés': 'granules', 'crème': 'cream',
      'pommade': 'ointment', 'gel': 'gel', 'lotion': 'lotion',
      'spray': 'spray', 'collyre': 'eye drops', 'suppositoire': 'suppository',
      'ovule': 'vaginal tablet', 'ampoule': 'ampoule', 'flacon': 'vial',
      'seringue': 'syringe', 'patch': 'patch', 'implant': 'implant',
      'injectable': 'injectable', 'inhalation': 'inhalation',
      'nébuliseur': 'nebulizer', 'aérosol': 'aerosol', 'mousse': 'foam',
      'émulsion': 'emulsion', 'shampooing': 'shampoo',
      'gouttes': 'drops', 'pastille': 'lozenge', 'compresse': 'compress',
      'pelliculé': 'film-coated', 'enrobé': 'coated',
      'effervescent': 'effervescent', 'orodispersible': 'orodispersible',
      'gastro-résistant': 'gastro-resistant', 'libération prolongée': 'extended-release',
      'libération modifiée': 'modified-release', 'à croquer': 'chewable',
      'sécable': 'scored', 'buvable': 'oral',
      'cutané': 'cutaneous', 'ophtalmique': 'ophthalmic',
      'auriculaire': 'ear', 'nasal': 'nasal', 'rectal': 'rectal',
      'vaginal': 'vaginal', 'sublingual': 'sublingual',
      'buccal': 'buccal', 'transdermique': 'transdermal',
      'intraveineux': 'intravenous', 'intramusculaire': 'intramuscular',
      'sous-cutané': 'subcutaneous', 'topique': 'topical',
      'usage externe': 'external use', 'usage oral': 'oral use',
      'unidose': 'single-dose', 'vernis': 'nail lacquer',
      'bain de bouche': 'mouthwash', 'pansement': 'dressing',
    };
    let result = frenchText.toLowerCase();
    for (const [fr, en] of Object.entries(pharmaKeywords)) {
      result = result.replace(new RegExp(fr, 'gi'), en);
    }
    return result.charAt(0).toUpperCase() + result.slice(1);
  }
  return frenchText;
}

const medicineTypeTranslations = {
  "Analgésiques (douleur)": "Analgesics (pain)",
  "Antipyrétiques (fièvre)": "Antipyretics (fever)",
  "Anti-inflammatoires non stéroïdiens (AINS)": "Non-steroidal anti-inflammatory drugs (NSAIDs)",
  "Corticoïdes": "Corticosteroids",
  "Antibiotiques": "Antibiotics",
  "Antiviraux": "Antivirals",
  "Antifongiques": "Antifungals",
  "Antiparasitaires": "Antiparasitics",
  "Anxiolytiques": "Anxiolytics",
  "Hypnotiques (somnifères)": "Hypnotics (sleep aids)",
  "Antidépresseurs": "Antidepressants",
  "Antipsychotiques (neuroleptiques)": "Antipsychotics (neuroleptics)",
  "Antiépileptiques": "Antiepileptics",
  "Antihypertenseurs": "Antihypertensives",
  "Anticoagulants": "Anticoagulants",
  "Antidiabétiques": "Antidiabetics",
  "Bronchodilatateurs": "Bronchodilators",
  "Antihistaminiques": "Antihistamines",
  "Anti-ulcéreux (IPP, anti-H2)": "Anti-ulcer drugs (PPIs, anti-H2)",
  "Diurétiques": "Diuretics",
  "Vaccins": "Vaccines",
};

const therapeuticFamilyTranslations = {
  "Anti-infectieux généraux à usage systémique": "General anti-infectives for systemic use",
  "Antinéoplasiques et immunomodulateurs": "Antineoplastic and immunomodulating agents",
  "Appareil digestif et métabolisme": "Alimentary tract and metabolism",
  "Divers": "Various",
  "Médicaments dermatologiques": "Dermatological preparations",
  "Organes sensoriels": "Sensory organs",
  "Produits antiparasitaires": "Antiparasitic products",
  "Préparations systémiques hormonales": "Systemic hormonal preparations",
  "Sang et organes hématopoïétiques": "Blood and blood forming organs",
  "Système cardiovasculaire": "Cardiovascular system",
  "Système génito-urinaire et hormones sexuelles": "Genitourinary system and sex hormones",
  "Système musculo-squelettique": "Musculoskeletal system",
  "Système nerveux": "Nervous system",
  "Système respiratoire": "Respiratory system",
};

function translateFormsDropdown(isEnglish) {
  document.querySelectorAll('select[name="forme"] option:not([value=""])').forEach(option => {
    if (!option.dataset.originalFr) option.dataset.originalFr = option.textContent;
    if (isEnglish) {
      option.textContent = translatePharmaForm(option.dataset.originalFr, 'en');
    } else {
      option.textContent = option.dataset.originalFr;
    }
  });
}

function setupLanguageSwitcher() {
  const container = document.getElementById('langSwitcherContainer');
  if (!container) return;

  const lang = currentLang;
  container.innerHTML = `
    <div class="lang-switcher">
      <button id="langSwitcherBtn" class="lang-btn" title="Changer la langue">
        <span class="lang-flag">${getFlag(lang)}</span>
        <span class="lang-label">${getLangLabel(lang)}</span>
        <i class="fas fa-chevron-down lang-chevron"></i>
      </button>
      <div class="lang-dropdown" id="langDropdown">
        ${Object.entries(LANGUAGES).map(([code, info]) => `
          <button class="lang-option${code === lang ? ' active' : ''}" data-lang="${code}">
            <span class="lang-option-flag">${info.flag}</span>
            <span class="lang-option-label">${info.label}</span>
          </button>
        `).join('')}
      </div>
    </div>
  `;

  document.getElementById('langSwitcherBtn').addEventListener('click', function (e) {
    e.stopPropagation();
    const dd = document.getElementById('langDropdown');
    dd.classList.toggle('show');
  });

  document.querySelectorAll('.lang-option').forEach(btn => {
    btn.addEventListener('click', function () {
      const langCode = this.dataset.lang;
      document.querySelectorAll('.lang-option').forEach(o => o.classList.remove('active'));
      this.classList.add('active');
      document.getElementById('langDropdown').classList.remove('show');
      switchLanguage(langCode);
    });
  });

  document.addEventListener('click', function () {
    const dd = document.getElementById('langDropdown');
    if (dd) dd.classList.remove('show');
  });
}

function loadLanguagePreference() {
  const saved = localStorage.getItem(CLE_LANGUE);
  const urlParams = new URLSearchParams(window.location.search);
  const urlLang = urlParams.get('lang');

  if (urlLang && LANGUAGES[urlLang]) {
    currentLang = urlLang;
    localStorage.setItem(CLE_LANGUE, urlLang);
  } else if (saved && LANGUAGES[saved]) {
    currentLang = saved;
  } else {
    currentLang = navigator.language && navigator.language.startsWith('en') ? 'en' : 'fr';
  }
}

function initTranslations() {
  loadLanguagePreference();
  /* Aligne le cookie sur la preference retenue : un visiteur qui revient
   * avec « en » en memoire doit recevoir un rendu serveur anglais des la
   * page suivante, sans avoir a rebasculer. */
  poserCookieLangue(currentLang);

  setupLanguageSwitcher();
  translatePage();
  translateDynamicContent();

  setTimeout(translateDynamicContent, 500);
}

document.addEventListener('DOMContentLoaded', initTranslations);

/* Mis à disposition des gabarits, qui avaient chacun leur propre lecture
 * de la préférence. Un seul endroit décide désormais du nom de la clé et
 * de ce que « changer de langue » veut dire. */
window.CLE_LANGUE = CLE_LANGUE;
window.switchLanguage = switchLanguage;
window.langueCourante = function () { return currentLang; };

/* Pour les pages qui inserent du contenu apres coup : elles rappellent
 * la traduction sur les noeuds neufs au lieu d'entretenir leur propre
 * table. Trois tables concurrentes vivaient dans les gabarits, chacune
 * avec ses langues et ses cles. */
window.retraduire = function () { translatePage(); translateDynamicContent(); };

/* Le chatbot construit ses messages en JS (erreurs, accueil reconstruit,
 * suggestions) : il lit les memes cles que le gabarit au lieu d'avoir sa
 * propre table. */
window.getStaticTranslation = getStaticTranslation;
