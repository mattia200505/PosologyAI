/*
 * Banc du degré de confiance et du garde-fou des probabilités.
 *
 * Ce que ce banc garde
 * --------------------
 * L'écran affichait les probabilités des diagnostics différentiels mais avait
 * retiré la confiance de l'hypothèse principale. Un différentiel à 25 %
 * s'affichait donc sans point de comparaison : l'incohérence relevée au § 5 du
 * rapport — une principale à 11 % sous des différentiels à 25 % et 15 % —
 * devenait invisible, pas absente.
 *
 * La confiance revient, et une comparaison dit quand un différentiel la
 * dépasse.
 *
 * Pourquoi ce banc évalue le gabarit au lieu de recopier les fonctions
 * ---------------------------------------------------------------------
 * `node --check` ne vérifie que la syntaxe : une variable employée avant sa
 * déclaration passe le contrôle et casse à l'exécution — c'est arrivé au
 * projet, et toute l'analyse échouait. Une fonction d'affichage se vérifie en
 * l'exécutant. Le script est donc extrait du gabarit et évalué tel quel,
 * derrière un DOM simulé : ce banc éprouve le code réellement servi.
 *
 * Emploi
 * ------
 *     node scripts/verif_confiance.js
 */

'use strict';

const fs = require('fs');
const path = require('path');

const GABARIT = path.join(__dirname, '..', 'templates', 'prescription_assistant.html');

let reussis = 0;
const echecs = [];

function verifier(intitule, obtenu, attendu) {
    const ok = JSON.stringify(obtenu) === JSON.stringify(attendu);
    if (ok) {
        reussis += 1;
    } else {
        echecs.push(intitule
            + '\n      obtenu : ' + JSON.stringify(obtenu)
            + '\n      attendu: ' + JSON.stringify(attendu));
    }
}

/* ── Un DOM juste assez réel pour que le script se charge ───────────── */

function faireElement(id) {
    const el = {
        id: id,
        className: '',
        innerHTML: '',
        textContent: '',
        value: '',
        href: '',
        style: {},
        dataset: {},
        classList: {
            _: new Set(),
            add(...c) { c.forEach((x) => this._.add(x)); },
            remove(...c) { c.forEach((x) => this._.delete(x)); },
            contains(c) { return this._.has(c); },
            toggle(c) { this._.has(c) ? this._.delete(c) : this._.add(c); },
        },
        enfants: [],
        addEventListener() {},
        removeEventListener() {},
        appendChild(n) { this.enfants.push(n); return n; },
        removeChild() {},
        setAttribute() {},
        getAttribute() { return null; },
        querySelector() { return null; },
        querySelectorAll() { return []; },
        closest() { return null; },
        focus() {},
        scrollIntoView() {},
        insertAdjacentHTML() {},
    };
    return el;
}

const elements = new Map();

const documentStub = {
    getElementById(id) {
        if (!elements.has(id)) elements.set(id, faireElement(id));
        return elements.get(id);
    },
    createElement(tag) { const e = faireElement(tag); e.tag = tag; return e; },
    querySelector() { return null; },
    querySelectorAll() { return []; },
    addEventListener() {},
    body: faireElement('body'),
    documentElement: faireElement('html'),
};

const stockage = {
    _: {},
    getItem(k) { return Object.prototype.hasOwnProperty.call(this._, k) ? this._[k] : null; },
    setItem(k, v) { this._[k] = String(v); },
    removeItem(k) { delete this._[k]; },
};

const windowStub = {
    location: { origin: 'http://localhost:5000', href: '', search: '' },
    localStorage: stockage,
    addEventListener() {},
};

/* ── Extraction et évaluation du script du gabarit ──────────────────── */

const html = fs.readFileSync(GABARIT, 'utf8');

// Le gabarit porte plusieurs <script> ; celui qui nous intéresse est le plus
// long, celui qui tient toute la logique d'affichage.
const blocs = [...html.matchAll(/<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/g)]
    .map((m) => m[1]);
if (!blocs.length) {
    console.error('Aucun <script> en ligne trouvé dans le gabarit.');
    process.exit(2);
}

// Les fonctions d'affichage sont communes aux deux écrans de prescription et
// vivent dans un fichier à part. La page les charge avant son propre script ;
// le banc fait de même, sinon il éprouverait un code amputé de la moitié qui
// s'exécute réellement.
const PARTAGE = path.join(__dirname, '..', 'static', 'js', 'prescription_resultats.js');
const source = fs.readFileSync(PARTAGE, 'utf8') + '\n'
    + blocs.reduce((a, b) => (b.length > a.length ? b : a), '');

const EXPORTS = [
    'decouperPrincipal',
    'extraireDifferentiels',
    'decouperDifferentiel',
    'differentielDominant',
    'parseDiagnostic',
    'displayEcartes',
];

let api;
try {
    const fabrique = new Function(
        'document', 'window', 'localStorage', 'console', 'fetch', 'alert',
        source + '\n;return {' + EXPORTS.map((n) => n + ': typeof ' + n
            + " === 'function' ? " + n + ' : null').join(', ') + '};');
    api = fabrique(documentStub, windowStub, stockage, console,
                   () => Promise.reject(new Error('réseau interdit dans le banc')),
                   () => {});
} catch (err) {
    console.error("Le script du gabarit n'a pas pu être exécuté :");
    console.error('  ' + err.message);
    process.exit(1);
}

// Le fait même d'arriver ici est un contrôle : le script s'est exécuté de bout
// en bout, pas seulement compilé.
verifier('le script du gabarit s exécute entièrement', true, true);

EXPORTS.forEach((nom) => {
    verifier('la fonction ' + nom + ' existe', typeof api[nom], 'function');
});

const { decouperPrincipal, extraireDifferentiels, differentielDominant } = api;

/* ── 1. La confiance principale est lue, plus jetée ─────────────────── */

let d = decouperPrincipal('Pneumonie communautaire — Confiance : 70%\nFoyer basal droit.');
verifier('le nom du diagnostic est isolé', d.nom, 'Pneumonie communautaire');
verifier('la confiance est retenue, pas jetée', d.confiance, 70);
verifier('la prose suit', d.prose, 'Foyer basal droit.');

d = decouperPrincipal('Migraine sans aura - Confidence: 90%\nCéphalée pulsatile.');
verifier('la forme anglaise est lue aussi', d.confiance, 90);
verifier('le nom reste propre en anglais', d.nom, 'Migraine sans aura');

d = decouperPrincipal('Pyélonéphrite aiguë — Confiance : 80 %\nFièvre.');
verifier('l espace avant le pour-cent ne gêne pas', d.confiance, 80);

d = decouperPrincipal('**Ulcère gastroduodénal** — Confiance : 70%\nÉpigastralgies.');
verifier('les marqueurs de gras sont retirés du nom', d.nom, 'Ulcère gastroduodénal');
verifier('le gras ne perturbe pas la lecture de la confiance', d.confiance, 70);

d = decouperPrincipal('Syndrome fébrile\nPas de pourcentage ici.');
verifier('sans pourcentage, la confiance est nulle', d.confiance, null);
verifier('sans pourcentage, le nom tient toujours', d.nom, 'Syndrome fébrile');

d = decouperPrincipal('');
verifier('un contenu vide ne casse pas', d.nom, '');
verifier('un contenu vide ne rend pas de confiance', d.confiance, null);

// Non-régression : une première ligne qui est déjà de la prose ne doit pas
// être promue en titre — mieux vaut pas de titre qu un faux titre.
d = decouperPrincipal('Le tableau clinique évoque une atteinte respiratoire basse '
    + 'dont la nature reste à préciser par imagerie.');
verifier('une phrase longue n est pas promue en titre', d.nom, '');

/* ── 2. Les différentiels, non-régression ───────────────────────────── */

let diffs = extraireDifferentiels(
    '[Embolie pulmonaire — Probabilité : 15% — Douleur pleurale]\n'
    + '[Pleurésie — Probabilité : 10% — Épanchement]');
verifier('deux différentiels entre crochets sont lus', diffs.length, 2);
verifier('leurs probabilités sont lues', diffs.map((x) => x.probabilite), [15, 10]);

diffs = extraireDifferentiels(
    'Embolie pulmonaire — Probabilité : 15% — Douleur pleurale\n'
    + 'Pleurésie — Probabilité : 10% — Épanchement');
verifier('la seconde forme, sans crochets, est lue aussi', diffs.length, 2);
verifier('ses probabilités sont lues', diffs.map((x) => x.probabilite), [15, 10]);

verifier('un texte sans différentiel rend une liste vide',
         extraireDifferentiels('Rien à signaler ici.').length, 0);

/* ── 3. Le garde-fou ────────────────────────────────────────────────── */

verifier('un différentiel sous la principale ne déclenche rien',
         differentielDominant(70, [{ probabilite: 15 }, { probabilite: 10 }]), false);

// Le cas observé au § 5 du rapport : principale à 11 %, différentiels à 25 et 15.
verifier('un différentiel au-dessus de la principale est signalé',
         differentielDominant(11, [{ probabilite: 25 }, { probabilite: 15 }]), true);

verifier('l égalité est signalée aussi : elle est tout aussi contradictoire',
         differentielDominant(30, [{ probabilite: 30 }]), true);

verifier('sans confiance connue, rien n est affirmé',
         differentielDominant(null, [{ probabilite: 25 }]), false);

verifier('sans différentiel, rien n est affirmé',
         differentielDominant(70, []), false);

verifier('des différentiels sans probabilité ne déclenchent rien',
         differentielDominant(70, [{ probabilite: null }]), false);

verifier('une liste absente ne casse pas',
         differentielDominant(70, null), false);

// Les six cas mesurés au § 5 du rapport : aucun ne doit être signalé.
const MESURES = [
    [70, [15, 10, 5]],
    [90, [5, 3, 1]],
    [70, [20, 10]],
    [85, [5, 5, 5]],
    [80, [10, 5, 5]],
    [80, [10, 5, 5]],
];
MESURES.forEach(([confiance, probas], i) => {
    verifier('cas mesuré n°' + (i + 1) + ' du rapport : pas de signalement',
             differentielDominant(confiance, probas.map((p) => ({ probabilite: p }))),
             false);
});

/* ── Relevé ─────────────────────────────────────────────────────────── */

console.log();
if (echecs.length) {
    console.log('ÉCHECS (' + echecs.length + ') :');
    echecs.forEach((e) => console.log('  - ' + e));
    console.log();
    console.log(reussis + ' contrôles réussis, ' + echecs.length + ' en échec.');
    process.exit(1);
}
console.log(reussis + ' contrôles, aucun en échec.');
process.exit(0);
