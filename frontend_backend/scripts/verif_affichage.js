/*
 * Toute la chaîne d'affichage, sur des réponses réelles des deux routes.
 *
 * Ce que ce banc garde
 * --------------------
 * `verif_confiance.js` éprouve les fonctions d'analyse sur des textes composés
 * à la main. Celui-ci fait tourner les fonctions d'affichage sur ce que les
 * routes ont réellement rendu : c'est le seul contrôle qui atteste que le
 * modèle écrit la forme que le code attend, et que les gabarits savent rendre
 * la réponse telle qu'elle arrive.
 *
 * Les **deux** écrans de prescription sont éprouvés. Ils rendent la même forme
 * de réponse et lisent le même `static/js/prescription_resultats.js` ; ce banc
 * est ce qui empêche l'un de repartir de son côté. Ils y étaient déjà allés :
 * la page diagnostic n'affichait ni les contre-indications, ni les médicaments
 * écartés, ni l'état du contrôle d'interactions, et n'échappait aucune valeur.
 *
 * Les réponses sont figées dans `donnees/` : le banc tourne sans MongoDB, sans
 * Qdrant, sans Neo4j et sans appel au modèle.
 *
 * Refaire les captures après un changement de la forme des réponses :
 *     python scripts/capturer_reponse.py
 *
 * Emploi
 * ------
 *     node scripts/verif_affichage.js
 */

'use strict';

const fs = require('fs');
const path = require('path');

const RACINE = path.join(__dirname, '..');
const PARTAGE = path.join(RACINE, 'static', 'js', 'prescription_resultats.js');

let reussis = 0;
const echecs = [];

function verifier(intitule, condition) {
    if (condition) reussis += 1;
    else echecs.push(intitule);
}

/* ── Un DOM juste assez réel pour que les scripts se chargent ───────── */

function faireElement(id) {
    return {
        id: id,
        className: '', textContent: '', value: '', href: '',
        style: {}, dataset: {}, enfants: [], tag: '',
        // `innerHTML` remplace le contenu, enfants compris. Une simple
        // propriété ne le faisait pas : les enfants d'un rendu précédent
        // survivaient à `container.innerHTML = ''`, et un contrôle lisait le
        // rendu d'avant en croyant lire celui d'après. Un stub infidèle fait
        // échouer du code juste — ou, pire, passer du code faux.
        _innerHTML: '',
        get innerHTML() { return this._innerHTML; },
        set innerHTML(valeur) {
            this._innerHTML = valeur;
            this.enfants.length = 0;
        },
        options: [], selectedIndex: 0,
        classList: {
            _: new Set(),
            add(...c) { c.forEach((x) => this._.add(x)); },
            remove(...c) { c.forEach((x) => this._.delete(x)); },
            contains(c) { return this._.has(c); },
            toggle() {},
        },
        addEventListener() {}, removeEventListener() {},
        appendChild(n) { this.enfants.push(n); return n; },
        removeChild() {}, setAttribute() {}, getAttribute() { return null; },
        querySelector() { return faireElement('?'); },
        querySelectorAll() { return []; },
        closest() { return null; }, focus() {}, scrollIntoView() {},
        insertAdjacentHTML() {},
    };
}

function faireDocument() {
    const elements = new Map();
    return {
        _elements: elements,
        getElementById(id) {
            if (!elements.has(id)) elements.set(id, faireElement(id));
            return elements.get(id);
        },
        createElement(tag) { const e = faireElement(tag); e.tag = tag; return e; },
        querySelector() { return faireElement('?'); },
        querySelectorAll() { return []; },
        addEventListener() {},
        body: faireElement('body'), documentElement: faireElement('html'),
    };
}

function faireStockage() {
    return {
        _: {},
        getItem(k) { return Object.prototype.hasOwnProperty.call(this._, k) ? this._[k] : null; },
        setItem(k, v) { this._[k] = String(v); },
        removeItem(k) { delete this._[k]; },
    };
}

/* ── Chargement d'un gabarit avec son module partagé ────────────────── */

const NOMS = ['displayDiagnostic', 'displayEcartes', 'displaySuggestions',
              'displayAlerts', 'decouperPrincipal', 'extraireDifferentiels',
              'differentielDominant', 'parseDiagnostic', 'displayResults',
              'echapper'];

function charger(gabarit) {
    const html = fs.readFileSync(path.join(RACINE, 'templates', gabarit), 'utf8');
    // La page charge le module commun avant son propre script ; le banc fait
    // de même, sinon il éprouverait un code amputé de la moitié qui s'exécute.
    const source = fs.readFileSync(PARTAGE, 'utf8') + '\n'
        + [...html.matchAll(/<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/g)]
            .map((m) => m[1])
            .reduce((a, b) => (b.length > a.length ? b : a), '');

    const documentStub = faireDocument();
    const stockage = faireStockage();
    const windowStub = {
        location: { origin: 'http://localhost:5000', href: '', search: '' },
        localStorage: stockage, addEventListener() {},
    };

    const api = new Function(
        'document', 'window', 'localStorage', 'console', 'fetch', 'alert',
        source + '\n;return {' + NOMS.map((n) => n + ': typeof ' + n
            + " === 'function' ? " + n + ' : null').join(', ') + '};'
    )(documentStub, windowStub, stockage, console,
      () => Promise.reject(new Error('réseau interdit dans le banc')), () => {});

    return { api, document: documentStub };
}

function rendu(doc, id) {
    return doc.getElementById(id).enfants
        .map((e) => (e.innerHTML || e.textContent || '')).join('\n');
}

function lireCapture(nom) {
    const chemin = path.join(__dirname, 'donnees', nom);
    if (!fs.existsSync(chemin)) {
        console.error('Capture introuvable : ' + chemin);
        console.error('La refaire avec : python scripts/capturer_reponse.py');
        process.exit(2);
    }
    return JSON.parse(fs.readFileSync(chemin, 'utf8'));
}

/* ── 1. L'assistant de prescription ─────────────────────────────────── */

let charge;
try {
    charge = charger('prescription_assistant.html');
} catch (err) {
    console.error("Le script de l'assistant n'a pas pu être exécuté : " + err.message);
    process.exit(1);
}
const assistant = charge.api;
const docAssistant = charge.document;
const data = lireCapture('reponse_analyse.json');

verifier("le script de l'assistant s'exécute entièrement", true);

[['displayDiagnostic', () => assistant.displayDiagnostic(data.diagnostic)],
 ['displayEcartes', () => assistant.displayEcartes(data)],
 ['displaySuggestions', () => assistant.displaySuggestions(data.medications, data.interactions)],
 ['displayAlerts', () => assistant.displayAlerts(data)]
].forEach(([nom, appel]) => {
    try { appel(); verifier('assistant : ' + nom + ' s exécute', true); }
    catch (err) { echecs.push('assistant : ' + nom + ' a levé : ' + err.message); }
});

const sections = assistant.parseDiagnostic(data.diagnostic);
verifier('les trois sections du compte rendu sont reconnues', sections.length === 3);

const principale = sections.find((s) => /principal|probable/i.test(s.title));
const differentielle = sections.find((s) => /différentiel|differentiel/i.test(s.title));
verifier('la section principale est trouvée', !!principale);
verifier('la section des différentiels est trouvée', !!differentielle);

const dec = assistant.decouperPrincipal(principale ? principale.content : '');
verifier('un nom de diagnostic est isolé', !!dec.nom);
verifier('la confiance est lue sur le texte réel du modèle',
         typeof dec.confiance === 'number');

const diffs = differentielle ? assistant.extraireDifferentiels(differentielle.content) : [];
verifier('des différentiels sont lus', diffs.length > 0);
verifier('leurs probabilités sont lues',
         diffs.length > 0 && diffs.every((d) => typeof d.probabilite === 'number'));
verifier('le garde-fou rend un booléen',
         typeof assistant.differentielDominant(dec.confiance, diffs) === 'boolean');

const diagnostic = rendu(docAssistant, 'diagnosticContent');
verifier('le nom du diagnostic est rendu', diagnostic.indexOf('ds-nom') !== -1);
verifier('la confiance est rendue', diagnostic.indexOf('ds-confiance') !== -1);

/* ── 2. La prescription par diagnostic ──────────────────────────────── */

let chargeDiag;
try {
    chargeDiag = charger('diagnostic_prescription.html');
} catch (err) {
    console.error("Le script de la page diagnostic n'a pas pu être exécuté : "
                  + err.message);
    process.exit(1);
}
const diag = chargeDiag.api;
const docDiag = chargeDiag.document;
const donneesDiag = lireCapture('reponse_diagnostic.json');

verifier('le script de la page diagnostic s exécute entièrement', true);
verifier('la page diagnostic expose displayResults',
         typeof diag.displayResults === 'function');

try {
    diag.displayResults(donneesDiag);
    verifier('diagnostic : displayResults s exécute sur la réponse réelle', true);
} catch (err) {
    echecs.push('diagnostic : displayResults a levé : ' + err.message);
}

/* ── 3. Ce que les deux écrans rendent, comparé ─────────────────────── */

// Les deux lisent le même module : ce qui suit doit valoir des deux côtés.
[['assistant', docAssistant, data], ['diagnostic', docDiag, donneesDiag]]
    .forEach(([ecran, doc, jeu]) => {
        const suggestions = rendu(doc, 'suggestionsContainer');
        verifier(ecran + ' : les médicaments proposés sont rendus',
                 suggestions.indexOf('rx-drug-name') !== -1);
        verifier(ecran + " : aucun nom « undefined » ne subsiste",
                 suggestions.indexOf('undefined') === -1);

        // Le panneau d'interactions ne se cache jamais : il dit ce qui a été
        // vérifié, y compris quand il n'a rien trouvé.
        verifier(ecran + ' : le panneau des interactions est rempli',
                 doc.getElementById('alertsContainer').enfants.length > 0);
        verifier(ecran + ' : la section des interactions est visible',
                 !doc.getElementById('alertsSection').classList.contains('hidden'));

        // Aucune gravité **inventée** : la source n'en porte pas, et
        // « Sévérité : Inconnue » laissait croire qu'il en existe une et
        // qu'on l'ignore.
        //
        // Le contrôle ne peut pas porter sur le mot « severity » dans le
        // rendu : les descriptions de DrugBank disent elles-mêmes « The risk
        // or severity of... », et c'est le texte source, à afficher tel quel.
        // Il porte donc sur l'étiquette qu'ajoutait le code, et sur la lecture
        // du champ — voir aussi le contrôle sur les sources, plus bas.
        const alertes = rendu(doc, 'alertsContainer');
        verifier(ecran + ' : aucune étiquette de gravité ajoutée au rendu',
                 !/(?:s[ée]v[ée]rit[ée]|severity|gravit[ée])\s*(?:&nbsp;)?\s*:/i
                     .test(alertes));

        // Les contre-indications relevées apparaissent sur la fiche.
        const attendues = (jeu.medications || [])
            .some((m) => (m.contre_indications || []).length);
        if (attendues) {
            verifier(ecran + ' : les contre-indications sont rendues',
                     suggestions.indexOf('rx-ci') !== -1);
        }

        // Le panneau des écartés obéit à l'état, des deux côtés.
        const sectionEcartes = doc.getElementById('ecartesSection');
        if (jeu.contraintes_etat === 'aucune') {
            verifier(ecran + ' : sans règle déclenchée, le panneau reste caché',
                     sectionEcartes.classList.contains('hidden'));
        } else {
            verifier(ecran + ' : dès qu une règle tourne, le panneau se montre',
                     !sectionEcartes.classList.contains('hidden'));
            verifier(ecran + ' : le panneau des écartés porte son état',
                     rendu(doc, 'ecartesContainer').length > 0);
        }
    });

// L'assistant a un écarté dans sa capture : sa règle doit être nommée.
// La capture porte une lombalgie chez une insuffisante rénale — le diagnostic
// appelle l'anti-inflammatoire, l'antécédent le refuse. La spécialité écartée
// dépend du catalogue ; c'est la substance en cause qui doit se lire.
const ecartes = rendu(docAssistant, 'ecartesContainer');
verifier('assistant : le médicament écarté est nommé',
         /kétoprof|ketoprof|profenid/i.test(ecartes));
verifier("assistant : l'antécédent en cause est nommé", /insuffisance r/i.test(ecartes));
verifier('assistant : le motif de la règle est rendu', /toxicit|acidose/i.test(ecartes));

/* ── 3 bis. Le rang thérapeutique arrive à l'écran ──────────────────── */

// Les conduites cliniques du dépôt rangent leurs traitements en première
// intention et alternatives. Cette distinction se perdait deux fois : à
// l'assemblage de `get_clinical_fallback`, puis dans `normaliser_medicament`,
// qui reconstruit un dictionnaire champ par champ.
const suggestionsAssistant = rendu(docAssistant, 'suggestionsContainer');
const rangs = (data.medications || []).map((m) => m.rang || '');
const rangsDistincts = [...new Set(rangs)];

verifier('assistant : les médicaments portent un rang',
         rangs.some((r) => r === 'premiere_intention'));
verifier('assistant : la condition qui les fait retenir est portée',
         (data.medications || []).some((m) => m.condition));

if (rangsDistincts.length > 1) {
    verifier('assistant : les groupes de rang sont titrés',
             suggestionsAssistant.indexOf('rx-rang-titre') !== -1);
    verifier('assistant : le titre « Première intention » apparaît',
             /Premi[èe]re intention/.test(suggestionsAssistant));
    verifier('assistant : le titre « Alternatives » apparaît',
             /Alternatives/.test(suggestionsAssistant));
    verifier('assistant : la condition est nommée sous le titre',
             /Retenu pour/.test(suggestionsAssistant));
} else {
    // Un seul groupe : pas d'intertitre, il n'apprendrait rien.
    verifier('assistant : un seul rang, donc aucun intertitre',
             suggestionsAssistant.indexOf('rx-rang-titre') === -1);
}

// La page diagnostic reçoit des candidats sans rang : aucun intertitre ne
// doit apparaître pour un groupe unique.
const suggestionsDiag = rendu(docDiag, 'suggestionsContainer');
const rangsDiag = [...new Set((donneesDiag.medications || []).map((m) => m.rang || ''))];
if (rangsDiag.length <= 1) {
    verifier('diagnostic : un seul rang, donc aucun intertitre',
             suggestionsDiag.indexOf('rx-rang-titre') === -1);
}

// Le score est rendu des deux côtés : c'est lui qui distingue un candidat
// pertinent d'un candidat que le modèle a proposé sans lien thérapeutique.
[['assistant', docAssistant, data], ['diagnostic', docDiag, donneesDiag]]
    .forEach(([ecran, doc, jeu]) => {
        if ((jeu.medications || []).some((m) => typeof m.relevance_score === 'number')) {
            verifier(ecran + ' : le score de pertinence est rendu',
                     rendu(doc, 'suggestionsContainer').indexOf('rx-score') !== -1);
        }
    });

/* ── 3 ter. L'écart de substance est dit à l'écran ──────────────────── */

// Le modèle annonce la substance de ce qu'il propose et il se trompe : HELIKIT
// donné pour de la « clarithromycine » porte de l'urée 13 C. C'est un test
// respiratoire, pas un antibiotique. La note se calcule sur la fiche, et
// l'écart est le signal le plus utile de l'écran : il dit que le modèle a
// parlé de ce qu'il ne connaissait pas.
[['assistant', docAssistant, data], ['diagnostic', docDiag, donneesDiag]]
    .forEach(([ecran, doc, jeu]) => {
        const contredits = (jeu.medications || [])
            .filter((m) => m.substance_annoncee);
        const rendu_ = rendu(doc, 'suggestionsContainer');
        if (contredits.length) {
            verifier(ecran + ' : la contradiction de substance est rendue',
                     rendu_.indexOf('rx-ecart-substance') !== -1);
            verifier(ecran + ' : la substance annoncée est nommée',
                     rendu_.indexOf(contredits[0].substance_annoncee) !== -1);
            verifier(ecran + ' : la substance de la fiche est nommée',
                     rendu_.indexOf((contredits[0].substances || [])[0]) !== -1);
            verifier(ecran + ' : la carte porte la marque de la contradiction',
                     rendu_.indexOf('rx-card-substance-douteuse') !== -1
                     || doc._elements.get('suggestionsContainer').enfants
                         .some((e) => (e.className || '')
                             .indexOf('rx-card-substance-douteuse') !== -1));
        } else {
            // Aucun écart : aucun signalement. Signaler dans le doute ferait
            // perdre au signalement tout son poids.
            verifier(ecran + " : sans écart, aucun signalement de substance",
                     rendu_.indexOf('rx-ecart-substance') === -1);
        }
    });

/* ── 4. Le champ `severity` n'est plus lu nulle part ────────────────── */

// Le rendu ne peut pas trancher seul : « severity » figure dans les
// descriptions de DrugBank elles-mêmes. La question se règle sur les sources —
// aucun affichage ne doit lire ce champ, la source n'en porte pas (P9-1).
[['module partagé', PARTAGE],
 ['gabarit assistant', path.join(RACINE, 'templates', 'prescription_assistant.html')],
 ['gabarit diagnostic', path.join(RACINE, 'templates', 'diagnostic_prescription.html')]
].forEach(([nom, chemin]) => {
    const source = fs.readFileSync(chemin, 'utf8');
    // `.severity` ou `['severity']` : la lecture du champ, pas les noms de
    // classe `severity-badge` et `severity-unknown`, qui sont du style.
    verifier(nom + ' : le champ severity n est plus lu',
             !/\.severity\b|\[['"]severity['"]\]/.test(source));
});

/* ── 5. L'échappement, des deux côtés ───────────────────────────────── */

// La page diagnostic n'échappait aucune valeur : vingt-trois appels d'un côté,
// zéro de l'autre. Un titre contenant un chevron cassait le rendu.
[['assistant', assistant], ['diagnostic', diag]].forEach(([ecran, api]) => {
    verifier(ecran + ' : echapper est disponible', typeof api.echapper === 'function');
    if (typeof api.echapper === 'function') {
        verifier(ecran + ' : le chevron est échappé',
                 api.echapper('<script>').indexOf('<') === -1);
        verifier(ecran + ' : le guillemet droit est échappé',
                 api.echapper('a"b').indexOf('"') === -1);
    }
});

// Les deux sections qui suivent **rejouent** l'affichage sur des jeux
// fabriques, et ecrasent donc le rendu des captures. Elles viennent en
// dernier pour cette raison : placees plus haut, elles faisaient lire a
// une section suivante un panneau qu'elles venaient de remplacer.

/* ── 9. Le traitement en cours écarte, et le dit ────────────────── */

// Le traitement en cours n'était lu que pour les interactions : il n'était
// jamais comparé aux propositions. Chez un patient sous bisoprolol et
// sacubitril/valsartan, l'écran proposait du timolol, du pindolol et du
// trandolapril — deux doublons et une association contre-indiquée.
//
// Les deux motifs ne se confondent pas : le doublon est *inutile*,
// l'association est *dangereuse*. L'écran doit les séparer.
{
    const REDONDANT = {
        title: 'TIMACOR 10 mg, comprimé',
        substances: ['Timolol'],
        etage_ecart: 'redondance',
        motif_ecart: 'Déjà couvert par le traitement en cours : TIMACOR 10 mg, '
            + 'comprimé est un bêta-bloquant, comme « Bisoprolol 5 mg ».',
        couvert_par: {
            etage: 'redondance', traitement: 'Bisoprolol 5 mg',
            classe: 'bêta-bloquant',
            motif: 'Déjà couvert par le traitement en cours : TIMACOR 10 mg, '
                + 'comprimé est un bêta-bloquant, comme « Bisoprolol 5 mg ».'
        }
    };
    const PROSCRIT = {
        title: 'ODRIK 2 mg, gélule',
        substances: ['Trandolapril'],
        etage_ecart: 'association',
        motif_ecart: "Association contre-indiquée : le risque d'angio-œdème "
            + "impose un intervalle de 36 heures. Traitement en cours : "
            + "« Sacubitril/Valsartan 49/51 mg ».",
        couvert_par: {
            etage: 'association', traitement: 'Sacubitril/Valsartan 49/51 mg',
            classe: "inhibiteur de la néprilysine et des récepteurs de l'angiotensine",
            motif: "Association contre-indiquée : le risque d'angio-œdème "
                + "impose un intervalle de 36 heures."
        }
    };

    assistant.displayEcartes({
        contraintes_etat: 'appliquees',
        medicaments_ecartes: [REDONDANT, PROSCRIT],
        ecartes_par_etage: [
            { etage: 'association', libelle: 'Association proscrite', nombre: 1 },
            { etage: 'redondance', libelle: 'Déjà couvert par le traitement en cours', nombre: 1 }
        ],
        contraintes_appliquees: []
    });
    const panneau = rendu(docAssistant, 'ecartesContainer');

    verifier('le groupe « déjà couverts » a son titre',
             /déjà couverts par le traitement en cours/i.test(panneau));
    verifier('le groupe « association proscrite » a le sien',
             /association proscrite/i.test(panneau));
    verifier('le doublon nomme le traitement qui le couvre',
             /Bisoprolol 5 mg/.test(panneau));
    verifier('et la classe partagée', /bêta-bloquant/.test(panneau));
    verifier("l'association dit le danger", /angio/i.test(panneau));
    verifier('et cite le traitement en cours',
             /Sacubitril\/Valsartan/.test(panneau));

    // Le danger se lit avant l'inutile : un médecin qui parcourt le panneau
    // doit rencontrer l'association contre-indiquée en premier.
    verifier("l'association proscrite passe devant la redondance",
             panneau.search(/association proscrite/i)
                 < panneau.search(/déjà couverts/i));
}

/* ── 10. Ne rien avoir à proposer est une réponse ─────────────── */

// Chez un patient déjà sous quadrithérapie de l'insuffisance cardiaque, avec
// une pression à 96/58 et un débit de filtration à 28, tout ce que la classe
// du diagnostic appelait est soit déjà en place, soit proscrit. La conclusion
// juste est « il n'y a rien à ajouter » — et un panneau vide ne la dit pas :
// il se lit comme une panne.
{
    assistant.displaySuggestions([], [], {
        ecartes_par_etage: [
            { etage: 'association', libelle: 'Association proscrite', nombre: 6 },
            { etage: 'redondance', libelle: 'Déjà couvert', nombre: 7 }
        ]
    });
    const vide = rendu(docAssistant, 'suggestionsContainer');
    verifier('sans proposition, l écran ne reste pas muet', vide.length > 0);
    verifier('il dit qu il n y a rien à ajouter',
             /rien à ajouter|aucun traitement à ajouter/i.test(vide));
    verifier('il renvoie à l ajustement des doses en place',
             /doses en place|ajustement/i.test(vide));
    verifier('il compte les candidats couverts', /13/.test(vide));

    // Rien d'examiné du tout ne veut pas dire la même chose que tout écarté :
    // le premier appelle une saisie plus précise, le second un ajustement.
    assistant.displaySuggestions([], [], {});
    const rien = rendu(docAssistant, 'suggestionsContainer');
    verifier('aucun candidat trouvé se dit autrement',
             /aucun candidat/i.test(rien));
    verifier('et suggère de préciser le tableau', /préciser/i.test(rien));
    verifier("ce message ne parle pas d'un traitement en cours",
             !/traitement en cours/i.test(rien));
}


/* ── 11. Les trois niveaux se lisent à l'écran ──────────────────────── */

// Une règle de surveillance n'écarte pas et ne touche pas à la note : elle
// doit donc se lire sur la fiche, sinon elle n'existe pas pour le médecin.
// `par_classe` dit que la substance n'était dans aucune table et que le
// rapprochement s'est fait sur le groupe ATC — le trou de couverture, rendu
// visible plutôt que refermé en silence.
{
    assistant.displaySuggestions([{
        title: 'TENSIONORME, comprimé sécable',
        substances: ['Méthyclothiazide'],
        pertinence: 30,
        penalites: ['pression artérielle systolique inférieure à 100 mmHg (−15)'],
        alertes: [
            { regle: 'natrémie inférieure à 130 mmol/L', cible: 'C03',
              par_classe: true,
              motif: "Hyponatrémie : les diurétiques l'aggravent. — la substance "
                  + "de ce médicament n'est pas reconnue par la règle ; le "
                  + "rapprochement se fait sur sa classe ATC C03, à vérifier." },
            { regle: 'même classe que le traitement en cours', cible: "diurétique de l'anse",
              par_classe: false,
              motif: "Même classe que « Furosemide 80 mg ». Vérifier s'il faut "
                  + "majorer l'existant plutôt qu'ajouter." }
        ]
    }], [], {});
    const fiche = rendu(docAssistant, 'suggestionsContainer');

    verifier('les alertes de surveillance arrivent à l écran',
             /à surveiller/i.test(fiche));
    verifier('la règle en cause est nommée', /natrémie/i.test(fiche));
    verifier('le rapprochement par classe est signalé comme tel',
             /rapprochement par classe/i.test(fiche));
    verifier('et la classe employée est dite', /C03/.test(fiche));
    verifier("l'alerte d'intensification se lit aussi",
             /majorer l’existant|majorer l'existant/i.test(fiche));
    verifier('la pénalité de classement reste visible sur la note',
             /systolique/i.test(fiche));

    // Une fiche sans alerte ne doit pas afficher le bloc : un panneau
    // « à surveiller » vide banaliserait ceux qui ne le sont pas.
    assistant.displaySuggestions([{ title: 'CLAMOXYL 1 g', pertinence: 90 }], [], {});
    verifier('sans alerte, aucun bloc de surveillance',
             !/à surveiller/i.test(rendu(docAssistant, 'suggestionsContainer')));
}

// Sur un traitement en cours, le niveau distingue ce qui est contre-indiqué
// de ce qui demande une surveillance. L'écran les affichait à l'identique.
{
    assistant.displayAlerts({
        interactions: [], interactions_etat: 'aucune',
        traitements_a_reconsiderer: [
            { traitement: 'Spironolactone 25 mg', antecedent: 'kaliémie supérieure à 5,5 mmol/L',
              motif: 'Hyperkaliémie.', niveau: 'exclusion',
              niveau_libelle: 'Contre-indication' },
            { traitement: 'Furosemide 80 mg', antecedent: 'natrémie inférieure à 130 mmol/L',
              motif: 'Hyponatrémie.', niveau: 'surveillance',
              niveau_libelle: 'À surveiller' }
        ]
    });
    const panneau = rendu(docAssistant, 'alertsContainer');
    verifier('le niveau du traitement en cours est rendu',
             /Contre-indication/.test(panneau));
    verifier('et la surveillance se distingue de la contre-indication',
             /À surveiller/.test(panneau));
    verifier('les deux niveaux portent des classes distinctes',
             /rx-niveau-exclusion/.test(panneau)
                 && /rx-niveau-surveillance/.test(panneau));
}

/* ── Relevé ─────────────────────────────────────────────────────────── */

console.log();
console.log('  assistant   : ' + dec.nom + ' (confiance ' + dec.confiance + ' %), '
    + (data.medications || []).length + ' proposé(s), '
    + (data.medicaments_ecartes || []).length + ' écarté(s)');
console.log('  diagnostic  : ' + (donneesDiag.medications || []).length
    + ' proposé(s), ' + (donneesDiag.medicaments_ecartes || []).length
    + ' écarté(s), ' + (donneesDiag.interactions || []).length
    + ' interaction(s) avec les traitements');
console.log();

if (echecs.length) {
    console.log('ÉCHECS (' + echecs.length + ') :');
    echecs.forEach((e) => console.log('  - ' + e));
    console.log();
    console.log(reussis + ' contrôles réussis, ' + echecs.length + ' en échec.');
    process.exit(1);
}
console.log(reussis + ' contrôles sur les réponses réelles des deux écrans, '
    + 'aucun en échec.');
process.exit(0);
