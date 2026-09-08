/*
 * Affichage des résultats de prescription, commun aux deux écrans.
 *
 * Pourquoi ce fichier existe
 * --------------------------
 * Deux écrans proposent des médicaments et vont en sens inverse : l'assistant
 * part des symptômes pour arriver à un traitement, la prescription par
 * diagnostic part d'un diagnostic déjà posé. Ils rendent la même réponse et
 * n'ont aucune raison de l'afficher différemment.
 *
 * Ils l'affichaient pourtant différemment sur tout. La page diagnostic ne
 * montrait ni les contre-indications, ni les médicaments écartés, ni l'état du
 * contrôle d'interactions ; elle affichait une sévérité que la source ne porte
 * pas ; et elle n'échappait aucune valeur — vingt-trois appels à `echapper()`
 * d'un côté, zéro de l'autre.
 *
 * Recopier ces fonctions dans le second gabarit aurait garanti qu'ils
 * redivergent : c'est ainsi qu'ils en sont arrivés là. Elles vivent donc ici,
 * et les deux pages lisent le même code.
 *
 * Contrat attendu de la page
 * --------------------------
 * Les identifiants d'éléments suivants, quand la section correspondante existe :
 *
 *     suggestionsContainer / suggestionsSection
 *     ecartesContainer     / ecartesSection
 *     alertsContainer      / alertsSection
 *
 * Une section absente est simplement ignorée : chaque écran affiche ce qu'il a.
 */

'use strict';

// Le guillemet droit compte : sans lui, un texte placé dans un attribut se
// coupe au premier guillemet rencontré. Les aria-label et les title composés
// ici sont exposés au même défaut.
function echapper(valeur) {
    return String(valeur === null || valeur === undefined ? '' : valeur)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

function _section(id) {
    return document.getElementById(id);
}

function _montrer(id) {
    var section = _section(id);
    if (section) section.classList.remove('hidden');
}

function _cacher(id) {
    var section = _section(id);
    if (section) section.classList.add('hidden');
}

// Chaque fiche porte les interactions qui la concernent. Elles étaient listées
// dans un panneau séparé : savoir lequel des six médicaments posait problème
// demandait un aller-retour, au moment précis où la décision se prend.
function interactionsDe(titre, interactions) {
    var cible = (titre || '').toLowerCase();
    return (interactions || []).filter(function (i) {
        return String(i.medicine2 || '').toLowerCase().indexOf(cible) === 0;
    });
}

//: Intitulés des rangs thérapeutiques. Les conduites cliniques du dépôt
//: rangent leurs traitements en première intention et alternatives ; cette
//: distinction se perdait avant d'arriver à l'écran, qui présentait un
//: antalgique de première intention et son alternative comme deux
//: propositions équivalentes.
var RANGS = [
    { cle: 'premiere_intention', titre: 'Première intention',
      note: 'Traitement à proposer en premier.' },
    { cle: '', titre: 'Autres candidats',
      note: 'Issus de la recherche dans le catalogue. Aucun rang thérapeutique '
          + 'ne leur est attaché.' },
    { cle: 'alternative', titre: 'Alternatives',
      note: 'Si la première intention ne convient pas ou est contre-indiquée.' },
    { cle: 'adjuvant', titre: 'Adjuvants',
      note: 'Soulagent un symptôme sans traiter sa cause. Ils s’ajoutent au '
          + 'traitement, ils ne le remplacent pas.' }
];

function _enteteRang(rang, medicaments) {
    var bloc = document.createElement('div');
    bloc.className = 'rx-rang';
    // Les conditions qui ont fait retenir ces traitements. Plusieurs peuvent
    // se rencontrer : « fièvre » et « toux » sur le même tableau.
    var conditions = [];
    medicaments.forEach(function (m) {
        if (m.condition && conditions.indexOf(m.condition) === -1) {
            conditions.push(m.condition);
        }
    });
    // Combien de traitements ce rang compte.
    //
    // « Alternatives » suivi de neuf fiches et « Adjuvants » suivi d'une
    // seule s'annoncaient pareil : il fallait descendre jusqu'au rang suivant
    // pour savoir ou l'un s'arretait. Le nombre le dit d'emblee.
    bloc.innerHTML = '<div class="rx-rang-tete">'
        + '<p class="rx-rang-titre">' + echapper(rang.titre) + '</p>'
        + '<span class="rx-rang-compte">' + medicaments.length + '</span>'
        + '</div>'
        + '<p class="rx-rang-note">' + echapper(rang.note)
        + (conditions.length
            ? ' Retenu pour : ' + echapper(conditions.join(', ')) + '.' : '')
        + '</p>';
    return bloc;
}

function displaySuggestions(medications, interactions, data) {
    var container = document.getElementById('suggestionsContainer');
    if (!container) return;
    container.innerHTML = '';

    // Ne rien avoir à proposer est une réponse, pas une panne.
    //
    // Chez un patient déjà sous quadrithérapie de l'insuffisance cardiaque,
    // avec une pression à 96/58 et un débit de filtration à 28, tout ce que la
    // classe du diagnostic appelait est soit déjà en place, soit proscrit. La
    // conclusion juste est « il n'y a rien à ajouter, ajuster l'existant » —
    // et un panneau vide ne la dit pas. Il se lit comme un échec.
    if (!(medications || []).length) {
        container.appendChild(_riposteVide(data || {}));
        _montrer('suggestionsSection');
        return;
    }

    // Les médicaments arrivent déjà dans l'ordre du raisonnement : le
    // regroupement ne fait que le rendre lisible. Un rang sans médicament ne
    // produit aucun intertitre.
    var parRang = {};
    (medications || []).forEach(function (med) {
        var cle = med.rang || '';
        (parRang[cle] = parRang[cle] || []).push(med);
    });
    // Un seul groupe rempli : l'intertitre n'apprendrait rien et prendrait la
    // place d'un médicament.
    var groupesRemplis = RANGS.filter(function (r) {
        return (parRang[r.cle] || []).length;
    });
    var grouper = groupesRemplis.length > 1;

    groupesRemplis.forEach(function (rang) {
        var lot = parRang[rang.cle];
        if (grouper) container.appendChild(_enteteRang(rang, lot));
        lot.forEach(function (med) { _carte(container, med, interactions); });
    });

    _montrer('suggestionsSection');
}

//: Ce que dit l'écran quand il n'a rien à proposer.
//:
//: Le message change selon la raison, parce que les raisons ne se valent pas.
//: « Tout ce qui convenait est déjà prescrit » appelle un ajustement de doses ;
//: « rien n'a été examiné » appelle une saisie plus précise. Un seul message
//: pour les deux ferait passer le premier cas pour le second.
function _riposteVide(data) {
    var bloc = document.createElement('div');
    bloc.className = 'rx-vide';

    var etages = data.ecartes_par_etage || [];
    var compte = function (cle) {
        var trouve = etages.filter(function (e) { return e.etage === cle; })[0];
        return trouve ? trouve.nombre : 0;
    };
    var couverts = compte('redondance') + compte('association');
    var examines = etages.reduce(function (t, e) { return t + e.nombre; }, 0);

    var titre, note;
    if (couverts) {
        titre = 'Aucun traitement à ajouter';
        note = 'Les ' + couverts + ' candidat' + (couverts > 1 ? 's' : '')
            + ' qui répondaient au diagnostic sont déjà couverts par le '
            + 'traitement en cours, ou ne s’y associent pas. L’ajustement '
            + 'porte sur les doses en place, non sur une prescription '
            + 'nouvelle. Le détail figure ci-dessous.';
    } else if (examines) {
        titre = 'Aucune proposition retenue';
        note = 'Les ' + examines + ' candidat' + (examines > 1 ? 's' : '')
            + ' examiné' + (examines > 1 ? 's ont' : ' a')
            + ' été écarté' + (examines > 1 ? 's' : '')
            + ' : le détail et le motif de chacun figurent ci-dessous.';
    } else {
        titre = 'Aucun candidat trouvé';
        note = 'Le tableau clinique n’a appelé aucune classe thérapeutique '
            + 'connue du moteur. Préciser le diagnostic ou les symptômes peut '
            + 'suffire à le relancer.';
    }

    bloc.innerHTML = '<p class="rx-vide-titre">'
        + '<i class="fas fa-circle-info" aria-hidden="true"></i> '
        + echapper(titre) + '</p>'
        + '<p class="rx-vide-note">' + echapper(note) + '</p>';
    return bloc;
}


function _carte(container, med, interactions) {
    var siennes = interactionsDe(med.title, interactions);
    // Les contre-indications relevées dans le RCP, avec la phrase qui les
    // porte : c'est elle qui permet de juger si le rapprochement tient.
    // Rien n'est retiré de la liste, seulement signalé.
    //
    // Déclarée ici, avant son premier usage : posée plus bas, la remontée
    // de `var` la laissait indéfinie à la ligne qui compose la classe de
    // la carte, et l'analyse échouait.
    var ci = med.contre_indications || [];

    // Un vrai lien, et non un <div onclick> : la carte était inatteignable
    // au clavier, et son adresse était construite à partir d'un champ
    // absent, donc cassée.
    var lien = document.createElement('a');
    lien.className = 'rx-card' + (siennes.length ? ' rx-card-signale' : '')
        + (ci.length ? ' rx-card-contre-indique' : '')
        + (med.substance_annoncee ? ' rx-card-substance-douteuse' : '');
    var langue = localStorage.getItem('posologyai_lang') || 'fr';
    var base = med.lien
        || ('/search?search=' + encodeURIComponent(med.title || ''));
    lien.href = base + (base.indexOf('?') === -1 ? '?' : '&') + 'lang=' + langue;

    // Les faits pratiques -- posologie, duree, forme -- etaient trois
    // lignes « Intitule : valeur » empilees, du meme poids que la
    // justification et les alertes qui suivaient. Qui cherche une posologie
    // la relisait a chaque fois au milieu d'une colonne uniforme.
    //
    // Ils passent dans une grille etiquetee : l'intitule au-dessus, en
    // petit, la valeur en dessous. Le regard atteint la valeur sans avoir a
    // lire l'intitule.
    function fait(intitule, valeur) {
        return valeur
            ? '<div class="rx-fait"><dt>' + intitule + '</dt><dd>'
              + echapper(valeur) + '</dd></div>'
            : '';
    }

    function grilleFaits(elements) {
        var remplis = elements.filter(function (e) { return e; });
        return remplis.length
            ? '<dl class="rx-faits">' + remplis.join('') + '</dl>' : '';
    }

    var substances = (med.substances && med.substances.length)
        ? '<span class="rx-substance">' + echapper(med.substances.join(', ')) + '</span>' : '';
    // Le lien d'une dénomination commune ouvre une spécialité qui la
    // contient. Le lecteur doit savoir laquelle, et que d'autres existent.
    var vers = med.representative
        ? '<p class="rx-vers"><i class="fas fa-external-link-alt" aria-hidden="true"></i> Ouvre '
          + echapper(med.representative) + '</p>' : '';
    // Phase P4 : la note clinique s'appelle `pertinence`. Elle partageait
    // `relevance_score` avec la similarite cosinus, qui a son propre champ.
    var note = (typeof med.pertinence === 'number')
        ? med.pertinence
        : (typeof med.relevance_score === 'number' ? med.relevance_score : null);
    var score = (note !== null)
        ? '<span class="rx-score" title="Score de pertinence clinique">'
          + note + '</span>' : '';

    // Ce qui a fait baisser la note, dit en toutes lettres.
    //
    // `peser_la_securite` nomme chaque pénalité depuis qu'elle existe — « une
    // note qui baisse sans raison affichée est pire qu'une note haute et
    // fausse » — et **aucun écran ne lisait le champ**. Le médicament passait
    // de 60 à 30 sans que rien ne l'explique. C'est le banc d'affichage qui
    // l'a relevé, en cherchant la trace d'un déclassement.
    var penalites = (med.penalites || []).length
        ? '<p class="rx-penalites">'
          + '<span class="rx-detail-label">Note abaissée&nbsp;: </span>'
          + med.penalites.map(echapper).join(' · ')
          + '</p>'
        : '';
    // Phase P7 : la classe ATC **et son libelle**, puis l indication
    // DrugBank citee. Le § 4.3 en demande quatre elements ; les deux autres
    // sont le rang, deja affiche, et ce qui a ete ecarte a sa place, dans le
    // panneau voisin.
    var libelles = med.classes_libelles || {};
    var codes = Object.keys(libelles);
    var classe = codes.length
        ? '<p class="rx-classe"><span class="rx-detail-label">Classe : </span>'
          + codes.map(function (c) {
                return echapper(libelles[c]) + ' (' + echapper(c) + ')';
            }).join(', ') + '</p>'
        : '';
    var indication = med.indication
        ? '<p class="rx-indication"><span class="rx-detail-label">Indication : </span>'
          + echapper(med.indication)
          // Une mention plutot qu un silence : de l anglais presente comme du
          // francais serait pire que de l anglais annonce.
          + (med.indication_traduite === false
              ? ' <span class="rx-langue">(source DrugBank, en anglais)</span>' : '')
          + '</p>'
        : '';

    var justification = med.justification
        ? '<div class="rx-explanation"><span class="rx-detail-label">Justification : </span><p>'
          + echapper(med.justification) + '</p></div>' : '';

    // D'où vient la proposition. « Appartenir à la classe que le diagnostic
    // appelle » et « convenir à ce patient » ne sont pas la même chose, et
    // l'écran les affichait pareil : un médicament généré parce que sa classe
    // figurait dans une table se lisait comme une recommandation clinique.
    var origine = ORIGINES[med.origine]
        ? '<p class="rx-origine rx-origine-' + echapper(med.origine) + '">'
          + '<i class="fas fa-' + ORIGINES[med.origine].icone + '" aria-hidden="true"></i> '
          + echapper(ORIGINES[med.origine].libelle) + '</p>'
        : '';

    // Le modèle a annoncé une substance que la fiche contredit. Dit en toutes
    // lettres : HELIKIT proposé comme contenant de la « clarithromycine »
    // porte en réalité de l'urée 13 C, et c'est un test respiratoire, pas un
    // antibiotique. La note, elle, est calculée sur la fiche.
    var ecartSubstance = med.substance_annoncee
        ? '<div class="rx-ecart-substance">'
          + '<p class="rx-ecart-substance-titre">'
          + '<i class="fas fa-exclamation-triangle" aria-hidden="true"></i> '
          + 'Substance annoncée contredite par la fiche</p>'
          + '<p class="rx-ecart-substance-detail">Annoncée : <strong>'
          + echapper(med.substance_annoncee) + '</strong>. Sur la fiche : <strong>'
          + echapper((med.substances || []).join(', ') || 'non renseignée')
          + '</strong>. La justification ci-dessus repose sur la substance '
          + 'annoncée&nbsp;; le score, sur la fiche.</p>'
          + '</div>'
        : '';

    // Les règles de niveau « surveillance ». Elles n'écartent pas et ne
    // touchent pas à la note : le médicament peut rester pertinent, sous
    // réévaluation. Une hyponatrémie sous furosémide appelle une surveillance,
    // pas le verdict « mauvais traitement ».
    //
    // `par_classe` dit que la substance n'était dans aucune table et que le
    // rapprochement s'est fait sur le groupe ATC. C'est le trou de couverture,
    // rendu visible plutôt que refermé en silence.
    var alertes = (med.alertes || []).length
        ? '<div class="rx-alertes">'
          + '<p class="rx-alertes-titre"><i class="fas fa-triangle-exclamation" aria-hidden="true"></i> '
          + 'À surveiller ' + (med.alertes.length > 1
              ? '(' + med.alertes.length + ' points)' : '') + '</p>'
          + med.alertes.map(function (a) {
                return '<p class="rx-alerte'
                    + (a.par_classe ? ' rx-alerte-par-classe' : '') + '">'
                    + '<strong>' + echapper(a.regle) + '</strong> : '
                    + echapper(a.motif)
                    + (a.par_classe
                        ? ' <span class="rx-approx">rapprochement par classe</span>' : '')
                    + '</p>';
            }).join('')
          + '</div>'
        : '';

    var avertissement = ci.length
        ? '<div class="rx-ci">'
          + '<p class="rx-ci-titre"><i class="fas fa-exclamation-triangle" aria-hidden="true"></i> '
          + 'Antécédent rencontré dans les contre-indications du RCP</p>'
          + ci.map(function (c) {
                return '<p class="rx-ci-phrase"><strong>' + echapper(c.terme)
                    + '</strong> : ' + echapper(c.phrase) + '</p>';
            }).join('')
          + '</div>'
        : '';

    var signal = siennes.length
        ? '<div class="rx-interactions">'
          + '<p class="rx-interactions-titre"><i class="fas fa-exclamation-circle" aria-hidden="true"></i> '
          + siennes.length + ' interaction' + (siennes.length > 1 ? 's' : '')
          + ' avec un traitement en cours</p>'
          + siennes.map(function (i) {
                return '<p class="rx-interaction"><strong>'
                    + echapper(String(i.medicine1).replace(/\s*\([^)]*\)\s*$/, ''))
                    + '</strong> ' + echapper(i.description) + '</p>';
            }).join('')
          + '</div>'
        : '';

    // Un cadre vide serait un cadre quand meme : il occuperait sa marge et
    // dessinerait un filet autour de rien. Les fiches sans provenance, sans
    // classe, sans indication ni justification n'en portent donc pas.
    var pourquoi = (origine + classe + indication + justification)
        ? '<div class="rx-pourquoi">'
          + origine + classe + indication + justification
          + '</div>'
        : '';

    // L'ordre de lecture d'une fiche.
    //
    // Tout arrivait en une seule colonne de blocs de meme poids : le nom, la
    // note flottee a droite, trois lignes de details, la justification, la
    // provenance, la classe, l'indication, puis les avertissements. Douze
    // blocs sans hierarchie, ou rien ne disait par quoi commencer.
    //
    // Quatre etages, dans l'ordre ou la question se pose :
    //
    //   1. l'identite   -- quel medicament, quelle substance, quelle note
    //   2. les faits    -- posologie, duree, forme : ce qu'on prescrit
    //   3. le pourquoi  -- provenance, classe, indication, justification
    //   4. les reserves -- ce qui abaisse la note, ce qu'il faut surveiller
    //
    // Rien n'est retire ni ajoute : les memes champs, dans un ordre qui suit
    // le raisonnement plutot que l'ordre ou le code les a construits.
    lien.innerHTML =
        '<div class="rx-card-body">'
        + '<div class="rx-card-tete">'
        +   '<div class="rx-card-identite">'
        +     '<span class="rx-drug-name">'
        +       echapper(med.title || 'Nom non renseigné') + '</span>'
        +     substances
        +   '</div>'
        +   score
        + '</div>'
        + grilleFaits([
              fait('Posologie', med.posologie),
              fait('Durée', med.duration),
              fait('Forme', med.forme)
          ])
        + pourquoi
        + penalites
        + alertes
        + ecartSubstance
        + avertissement
        + signal
        + vers
        + '</div>';
    container.appendChild(lien);
}

//: Les quatre motifs d'écartement, dans l'ordre où ils comptent pour un
//: médecin. L'antécédent d'abord : c'est le seul qui parle du patient.
//:
//: Ils étaient fondus sous un titre unique — « Écartés par les antécédents » —
//: qui n'en nommait qu'un. Sous ce titre s'affichaient des produits non
//: commercialisés, et le premier écarté visible n'avait aucun rapport avec le
//: patient.
//: Les deux premiers parlent du traitement en cours et passent devant : la
//: question « la place est-elle libre ? » précède « ce médicament
//: conviendrait-il ? ». L'association avant la redondance, parce qu'elle
//: signale un danger là où l'autre ne signale qu'un doublon.
var MOTIFS_ECART = [
    { cle: 'association', titre: 'Écartés : association proscrite',
      note: 'Ne se prescrivent pas avec un traitement que le patient prend déjà.' },
    { cle: 'redondance', titre: 'Écartés : déjà couverts par le traitement en cours',
      note: 'Leur classe est déjà occupée. Ajuster l’existant plutôt qu’ajouter.' },
    { cle: 'antecedent', titre: 'Écartés par les antécédents et la biologie',
      note: 'Une règle du dossier patient les contredit.' },
    { cle: 'seuil', titre: 'Écartés faute de pertinence',
      note: 'Aucun lien thérapeutique établi avec le tableau clinique.' },
    { cle: 'classe', titre: 'Écartés par leur classe thérapeutique',
      note: 'Leur classe ne répond pas au tableau, ou ne traite rien.' },
    { cle: 'eligibilite', titre: 'Non prescriptibles',
      note: 'Non commercialisés, ou produits de procédure.' }
];

//: Combien de fiches par motif avant de replier le reste. Trente-six d'un
//: coup noieraient le motif de chacune.
var ECARTES_VISIBLES = 3;

//: Ce qui a fait entrer un médicament dans la liste, dit en clair.
//:
//: Un candidat généré parce que sa classe ATC figurait dans la table du
//: diagnostic n'a pas le même statut qu'une conduite clinique du dépôt. Les
//: deux s'affichaient à l'identique, et le second se lisait comme le premier.
//:
//: `similarite` n'est volontairement pas nommé « suggestion » : une proximité
//: de texte entre des symptômes et un résumé des caractéristiques du produit
//: n'est pas un raisonnement, et le mot ne doit pas laisser croire le
//: contraire.
var ORIGINES = {
    conduite_clinique: {
        libelle: 'Conduite clinique de référence',
        icone: 'book-medical'
    },
    classe_atc: {
        libelle: 'Proposé pour sa classe thérapeutique — à confronter au cas',
        icone: 'sitemap'
    },
    similarite: {
        libelle: 'Remonté par proximité de texte — sans indication vérifiée',
        icone: 'magnifying-glass'
    }
};


function _motifDe(med) {
    if (med.etage_ecart) return med.etage_ecart;
    if (med.ecarte_par) return 'antecedent';
    if (med.sous_le_seuil) return 'seuil';
    return 'eligibilite';
}


function _regleDe(med) {
    // Six étages écartent, et chacun s'explique dans ses propres termes.
    //
    // Le traitement en cours passe en premier : quand un médicament est à la
    // fois redondant et contre-indiqué, c'est la redondance qu'il faut lire —
    // la question de savoir s'il conviendrait ne se pose plus.
    if (med.couvert_par) {
        return {
            antecedent: med.couvert_par.traitement,
            cible: med.couvert_par.classe,
            motif: med.couvert_par.motif
        };
    }
    if (med.ecarte_par) return med.ecarte_par;
    if (med.sous_le_seuil) {
        var note = (typeof med.pertinence === 'number') ? med.pertinence : 0;
        return {
            antecedent: 'pertinence insuffisante',
            motif: 'Note de ' + note + ' sur 100, sous le seuil de '
                + med.sous_le_seuil + '.'
        };
    }
    return {
        antecedent: (med.etage_ecart === 'eligibilite')
            ? 'produit non prescriptible' : 'classe thérapeutique',
        motif: med.motif_ecart || ''
    };
}


function _carteEcartee(med) {
    var regle = _regleDe(med);
    // Une carte, pas un lien : la fiche reste consultable, mais le clic ne
    // doit pas donner à un médicament écarté l'apparence d'une proposition.
    var carte = document.createElement('div');
    carte.className = 'rx-card rx-card-ecarte';

    var substances = (med.substances && med.substances.length)
        ? '<span class="rx-substance">' + echapper(med.substances.join(', ')) + '</span>' : '';

    carte.innerHTML =
        '<div class="rx-card-body">'
        + '<span class="rx-drug-name">'
        + echapper(med.title || med.name || 'Nom non renseigné') + '</span>'
        + substances
        + '<div class="rx-ecart">'
        + '<p class="rx-ecart-titre">Écarté par&nbsp;: <strong>'
        + echapper(regle.antecedent || 'règle') + '</strong></p>'
        + '<p class="rx-ecart-motif">' + echapper(regle.motif || '') + '</p>'
        + '</div>'
        + '</div>';
    return carte;
}


// Les médicaments qu'une règle a retirés de la liste.
//
// Le panneau ne se cache que si rien n'a été écarté et qu'aucune règle n'a
// tourné. Dès qu'une règle a tourné, il dit ce qu'elle a fait, même quand elle
// n'a rien écarté : « aucun antécédent contraignant » et « les règles ont
// tourné sans rien trouver » donnent le même écran vide et ne veulent pas dire
// la même chose. C'est la leçon du panneau d'interactions.
function displayEcartes(data) {
    var container = document.getElementById('ecartesContainer');
    if (!container) return;

    var ecartes = data.medicaments_ecartes || [];
    var regles = data.contraintes_appliquees || [];
    var etat = data.contraintes_etat || 'aucune';

    container.innerHTML = '';

    if (etat === 'aucune' && !ecartes.length) {
        _cacher('ecartesSection');
        return;
    }

    var intro = document.createElement('p');
    intro.className = 'ecartes-etat';
    if (etat === 'tout_ecarte') {
        intro.textContent = 'Tous les médicaments envisagés ont été écartés '
            + 'par les antécédents. Aucune proposition n’est faite.';
    } else if (etat === 'sans_effet' && !ecartes.length) {
        intro.textContent = 'Antécédents contraignants pris en compte ('
            + regles.map(function (r) { return r.antecedent; }).join(', ')
            + ') : aucun médicament proposé n’est visé.';
    } else {
        intro.textContent = ecartes.length + ' médicament'
            + (ecartes.length > 1 ? 's ont été retirés' : ' a été retiré')
            + ' des propositions. Chacun porte la règle qui l’a écarté.';
    }
    container.appendChild(intro);

    // Groupés par motif : un titre qui dit « antécédents » ne doit pas
    // couvrir des produits non commercialisés.
    var parMotif = {};
    ecartes.forEach(function (med) {
        var cle = _motifDe(med);
        (parMotif[cle] = parMotif[cle] || []).push(med);
    });

    MOTIFS_ECART.forEach(function (motif) {
        var lot = parMotif[motif.cle] || [];
        if (!lot.length) return;

        var entete = document.createElement('div');
        entete.className = 'rx-rang';
        entete.innerHTML = '<p class="rx-rang-titre">' + echapper(motif.titre)
            + ' (' + lot.length + ')</p>'
            + '<p class="rx-rang-note">' + echapper(motif.note) + '</p>';
        container.appendChild(entete);

        // Trois d'abord, le reste sur demande — par motif, pas sur le tas.
        var reste = [];
        lot.forEach(function (med, rang) {
            var carte = _carteEcartee(med);
            if (rang < ECARTES_VISIBLES) container.appendChild(carte);
            else reste.push(carte);
        });

        if (reste.length) {
            // Le bouton bascule : ce qu'on a déplié doit pouvoir se replier.
            // Les cartes sont gardées en mémoire plutôt que reconstruites —
            // les rebâtir à chaque bascule referait le travail pour rien.
            var bouton = document.createElement('button');
            bouton.type = 'button';
            bouton.className = 'btn-secondaire-mince rx-voir-plus';
            var deplie = false;
            var libelle = function () {
                bouton.textContent = deplie
                    ? 'Voir moins'
                    : 'Voir les ' + reste.length + ' autres';
                bouton.setAttribute('aria-expanded', deplie ? 'true' : 'false');
            };
            libelle();
            bouton.addEventListener('click', function () {
                if (deplie) {
                    reste.forEach(function (carte) {
                        if (carte.parentNode === container) {
                            container.removeChild(carte);
                        }
                    });
                } else {
                    reste.forEach(function (carte) {
                        container.insertBefore(carte, bouton);
                    });
                }
                deplie = !deplie;
                libelle();
            });
            container.appendChild(bouton);
        }
    });

    _montrer('ecartesSection');
}

//: Ce que dit le panneau quand il n'a trouvé aucune interaction. Les cinq
//: états ne se ressemblent pas et l'écran ne doit pas les confondre.
var MESSAGES_INTERACTIONS = {
    aucune: null,   // composé plus bas : il porte le nombre de paires
    aucun_traitement: 'Aucun traitement en cours n’a été saisi : il n’y avait '
        + 'rien à confronter aux médicaments proposés.',
    aucune_suggestion: 'Aucun médicament n’est proposé : il n’y avait rien '
        + 'à confronter aux traitements en cours.',
    non_appariees: 'Aucun des traitements saisis n’a pu être rattaché à une '
        + 'substance connue. Aucune vérification n’a eu lieu.',
    non_verifiable: 'Le graphe des interactions n’est pas accessible. '
        + 'Aucune vérification n’a eu lieu.'
};

// Le panneau ne se cache plus jamais. Il était masqué quand la liste était
// vide, si bien que « aucune interaction recensée » et « rien n'a pu être
// vérifié » se ressemblaient : dans les deux cas, rien à l'écran. Sur un outil
// de prescription c'est la confusion la plus coûteuse.
function displayAlerts(data) {
    var container = document.getElementById('alertsContainer');
    if (!container) return;

    var interactions = data.interactions || [];
    var etat = data.interactions_etat || (interactions.length ? 'trouvees' : 'non_verifiable');
    var reconnus = data.traitements_reconnus || [];
    var inconnus = data.traitements_non_reconnus || [];
    container.innerHTML = '';

    interactions.forEach(function (interaction) {
        var div = document.createElement('div');
        // Plus de classe par gravité : la source n'en porte aucune.
        div.className = 'alert-item severity-unknown';
        div.innerHTML = '<i class="fas fa-exclamation-circle alert-icon"></i>'
            + '<div>'
            + '<h4>' + echapper(interaction.medicine1) + ' ↔ '
            + echapper(interaction.medicine2) + '</h4>'
            + '<p>' + echapper(interaction.description)
            + (interaction.traduit === false
                ? ' <span class="rx-langue">(en anglais : aucune trame de '
                  + 'traduction ne couvre cet énoncé)</span>' : '')
            + '</p>'
            + '<div class="alert-meta">'
            + '<span class="severity-badge">Source : DrugBank, entre substances actives</span>'
            + '</div></div>';
        container.appendChild(div);
    });

    if (etat !== 'trouvees') {
        var note = document.createElement('p');
        note.className = 'alert-etat';
        note.textContent = (etat === 'aucune')
            ? 'Aucune interaction recensée entre les traitements en cours reconnus '
              + 'et les médicaments proposés. ' + (data.paires_verifiees || 0)
              + ' paire(s) vérifiée(s) dans DrugBank.'
            : (MESSAGES_INTERACTIONS[etat] || MESSAGES_INTERACTIONS.non_verifiable);
        container.appendChild(note);
    }

    // Ce qui n'a pas été reconnu se dit, même quand des interactions ont été
    // trouvées par ailleurs : une ordonnance lue à moitié ne vaut pas une
    // ordonnance sans interaction.
    if (inconnus.length) {
        var reserve = document.createElement('p');
        reserve.className = 'alert-reserve';
        reserve.innerHTML = '<i class="fas fa-info-circle" aria-hidden="true"></i> '
            + 'Non reconnu, donc non vérifié : <strong>'
            + inconnus.map(echapper).join('</strong>, <strong>') + '</strong>.';
        container.appendChild(reserve);
    }
    if (reconnus.length) {
        var lus = document.createElement('p');
        lus.className = 'alert-lus';
        lus.textContent = 'Traitements pris en compte : ' + reconnus.map(function (r) {
            return r.saisie + ' (' + r.substance + ')';
        }).join(', ') + '.';
        container.appendChild(lus);
    }

    // Les interactions des médicaments proposés **entre eux**. Question
    // distincte de la précédente, et toutes deux légitimes : réunies sous un
    // seul intitulé, elles laissaient croire que les traitements du patient
    // avaient été regardés, alors qu'ils ne l'étaient jamais.
    var entreEux = data.interactions_entre_suggestions || [];
    if (entreEux.length) {
        var titre = document.createElement('p');
        titre.className = 'alert-etat';
        titre.textContent = 'Entre les médicaments proposés eux-mêmes :';
        container.appendChild(titre);

        entreEux.forEach(function (interaction) {
            var div = document.createElement('div');
            div.className = 'alert-item severity-unknown';
            div.innerHTML = '<i class="fas fa-exclamation-circle alert-icon"></i>'
                + '<div>'
                + '<h4>' + echapper(interaction.medicine1) + ' ↔ '
                + echapper(interaction.medicine2) + '</h4>'
                + (interaction.description
                    ? '<p>' + echapper(interaction.description) + '</p>' : '')
                + '<div class="alert-meta">'
                + '<span class="severity-badge">Source : DrugBank, entre substances actives</span>'
                + '</div></div>';
            container.appendChild(div);
        });
    }

    // Les traitements que le patient prend **déjà** et que ses antécédents ou
    // ses résultats contredisent.
    //
    // Les contraintes ne portaient que sur les médicaments proposés : un
    // patient sous 2 g de metformine avec un DFG de 28 — contre-indication
    // formelle sous 30 — n'était averti de rien. C'est pourtant là que se
    // trouvent les erreurs qui durent : une proposition nouvelle est relue, un
    // traitement ancien ne l'est plus.
    //
    // Signalés, jamais retirés : on ne supprime pas le traitement d'un patient
    // depuis un écran de suggestion.
    var aRevoir = data.traitements_a_reconsiderer || [];
    if (aRevoir.length) {
        var titreRevoir = document.createElement('p');
        titreRevoir.className = 'alert-etat';
        titreRevoir.textContent = aRevoir.length + ' traitement'
            + (aRevoir.length > 1 ? 's en cours sont à reconsidérer'
                                  : ' en cours est à reconsidérer')
            + ' au vu des antécédents et des résultats du patient :';
        container.appendChild(titreRevoir);

        aRevoir.forEach(function (releve) {
            var div = document.createElement('div');
            div.className = 'alert-item rx-a-revoir';
            div.innerHTML = '<i class="fas fa-exclamation-circle alert-icon"></i>'
                + '<div>'
                + '<h4>' + echapper(releve.traitement) + '</h4>'
                + '<p>' + echapper(releve.motif) + '</p>'
                // Le niveau que la règle porte. Signalés, jamais retirés — on
                // ne retire pas un traitement en cours depuis un écran de
                // suggestion — mais « contre-indiqué » et « à surveiller » ne
                // se lisent pas pareil, et l'écran les affichait à l'identique.
                + '<div class="alert-meta">'
                + (releve.niveau
                    ? '<span class="rx-niveau rx-niveau-' + echapper(releve.niveau)
                      + '">' + echapper(releve.niveau_libelle || releve.niveau)
                      + '</span>' : '')
                + '<span class="severity-badge">'
                + echapper(releve.antecedent) + '</span></div>'
                + '</div>';
            container.appendChild(div);
        });
    }

    // Ce que la biologie a relevé, avec la valeur mesurée. Un nombre ne
    // dépend d'aucune tournure de phrase : c'est la contrainte la plus sûre
    // dont l'écran dispose, et il doit dire sur quoi elle repose.
    var biologie = data.biologie_relevee || [];
    if (biologie.length) {
        var releve = document.createElement('p');
        releve.className = 'alert-lus';
        releve.textContent = 'Seuils biologiques franchis : '
            + biologie.map(function (b) {
                return b.libelle + ' (mesuré : ' + b.valeur + ')';
            }).join(' · ') + '.';
        container.appendChild(releve);
    }

    _montrer('alertsSection');
}
