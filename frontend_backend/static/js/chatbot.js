/*
 * Logique de l'assistant flottant PosologyAI.
 *
 * Charge par le composant `components/chatbot.html` (script defer) —
 * l'ancien script inline du gabarit injectait les reponses en innerHTML
 * sans echappement : tout ce qui sort du modele passe desormais par un
 * rendu markdown qui ECHAPPE d'abord le texte. Aucune brique HTML ne
 * provient jamais d'une chaine non filtree.
 */
(function () {
  'use strict';

  var LONGUEUR_MAX = 1000;
  var TIMEOUT_REPONSE_MS = 60000;

  var SUGGESTIONS_LOCALES = [
    "Quels médicaments pour le diabète ?",
    "Paracétamol vs ibuprofène : quelles différences ?",
    "Quelle posologie du doliprane chez l'adulte ?",
    "Médicaments contre le reflux gastrique"
  ];

  var el = {
    toggle: document.getElementById('chatbot-toggle'),
    window: document.getElementById('chatbot-window'),
    close: document.getElementById('chatbot-close'),
    clear: document.getElementById('chatbot-clear'),
    messages: document.getElementById('chatbot-messages'),
    input: document.getElementById('chatbot-input'),
    send: document.getElementById('chatbot-send'),
    suggestionsContainer: document.getElementById('chatbot-suggestions'),
    suggestionsChips: document.getElementById('suggestions-chips')
  };

  if (!el.toggle || !el.window || !el.messages) return;

  var isOpen = false;
  var requeteEnCours = null; // AbortController du message parti

  /* Langue courante posee par le moteur de traduction (translations.js). */
  function langueActuelle() {
    try {
      var l = window.langueCourante && window.langueCourante();
      return (l === 'en' || l === 'ar') ? l : 'fr';
    } catch (e) { return 'fr'; }
  }

  /* Lecture d'une cle des tables de traduction partagees ; a defaut
     (translations.js absent), retourne le texte francais de secours. */
  function _t(cle, secours) {
    try {
      if (typeof window.getStaticTranslation === 'function') {
        var texte = window.getStaticTranslation(cle, langueActuelle());
        if (texte && texte !== cle) return texte;
      }
    } catch (e) { /* table absente : secours */ }
    return secours;
  }

  function scrollToBottom() {
    requestAnimationFrame(function () {
      el.messages.scrollTop = el.messages.scrollHeight;
    });
  }

  function escapeHtml(texte) {
    var div = document.createElement('div');
    div.textContent = String(texte == null ? '' : texte);
    return div.innerHTML;
  }

  /* Rendu markdown minimal mais SUR : le texte est echappe avant toute
     transformation, seules les balises ci-dessous sont produites ici. */
  function renderMarkdown(texte) {
    var html = escapeHtml(texte);

    html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
    html = html.replace(/(^|[^*])\*([^*\n]+)\*/g, '$1<em>$2</em>');
    html = html.replace(/^#{1,3}\s+(.+)$/gm, '<div class="bot-title"><i class="fas fa-info-circle"></i> $1</div>');
    html = html.replace(/^[-•]\s+(.+)$/gm, '<div class="bot-list-item-simple">• $1</div>');
    html = html.replace(/^(\d{1,2})\.\s+(.+)$/gm, '<div class="bot-list-item-simple"><span class="bot-number-small">$1</span>$2</div>');
    // Numéros d'urgence mis en évidence (déjà échappés)
    html = html.replace(/\b(15|112|18)\b(?![^<]*<\/)/g, '<strong class="cb-urgence-num">$1</strong>');

    return html.replace(/\n/g, '<br>');
  }

  function getTime() {
    var now = new Date();
    return String(now.getHours()).padStart(2, '0') + ':' +
           String(now.getMinutes()).padStart(2, '0');
  }

  function addMessage(content, type, emergency, fiches) {
    var div = document.createElement('div');
    div.className = 'chatbot-message ' + (type === 'user' ? 'user-message' : 'bot-message');
    if (emergency) div.classList.add('emergency-message');

    var avatar = document.createElement('div');
    avatar.className = 'message-avatar';
    avatar.innerHTML = type === 'user'
      ? '<i class="fas fa-user"></i>'
      : '<i class="fas fa-robot"></i>';

    var contentDiv = document.createElement('div');
    contentDiv.className = 'message-content';

    var textDiv = document.createElement('div');
    textDiv.className = 'msg-text';
    textDiv.innerHTML = type === 'user'
      ? escapeHtml(content)
      : renderMarkdown(content);
    contentDiv.appendChild(textDiv);

    // Fiches trouvées dans la base : puces cliquables vers la page détaillée.
    if (type === 'bot' && Array.isArray(fiches) && fiches.length > 0 && !emergency) {
      var fichesDiv = document.createElement('div');
      fichesDiv.className = 'cb-fiches';
      fiches.forEach(function (fiche) {
        if (!fiche || !fiche.id || !fiche.titre) return;
        var lien = document.createElement('a');
        lien.className = 'cb-fiche-lien';
        lien.href = '/medicine/' + encodeURIComponent(fiche.id);
        lien.textContent = fiche.titre;
        fichesDiv.appendChild(lien);
      });
      contentDiv.appendChild(fichesDiv);
    }

    var timeDiv = document.createElement('div');
    timeDiv.className = 'msg-time';
    timeDiv.textContent = getTime();
    contentDiv.appendChild(timeDiv);

    div.appendChild(avatar);
    div.appendChild(contentDiv);
    el.messages.appendChild(div);
    hideSuggestions();
    scrollToBottom();
  }

  function addTypingIndicator() {
    var div = document.createElement('div');
    div.className = 'chatbot-message bot-message';
    div.id = 'chatbot-typing';

    var avatar = document.createElement('div');
    avatar.className = 'message-avatar';
    avatar.innerHTML = '<i class="fas fa-robot"></i>';

    var contentDiv = document.createElement('div');
    contentDiv.className = 'message-content typing-indicator';
    for (var i = 0; i < 3; i++) {
      contentDiv.appendChild(document.createElement('span'));
    }

    div.appendChild(avatar);
    div.appendChild(contentDiv);
    el.messages.appendChild(div);
    scrollToBottom();
    return div;
  }

  function removeTypingIndicator() {
    var indicateur = document.getElementById('chatbot-typing');
    if (indicateur) indicateur.remove();
  }

  function hideSuggestions() {
    if (el.suggestionsContainer) el.suggestionsContainer.classList.add('hidden');
  }

  function showSuggestions(questions) {
    if (!el.suggestionsContainer || !el.suggestionsChips) return;
    el.suggestionsChips.innerHTML = '';
    (questions || []).slice(0, 4).forEach(function (q) {
      var chip = document.createElement('button');
      chip.type = 'button';
      chip.className = 'suggestion-chip';
      chip.textContent = q;
      chip.addEventListener('click', function () {
        sendMessage(q);
      });
      el.suggestionsChips.appendChild(chip);
    });
    el.suggestionsContainer.classList.remove('hidden');
    scrollToBottom();
  }

  function loadSuggestions() {
    fetch('/api/chatbot/suggestions?lang=' + encodeURIComponent(langueActuelle()))
      .then(function (r) { return r.ok ? r.json() : Promise.reject(); })
      .then(function (data) {
        showSuggestions(data.success && data.suggestions ? data.suggestions : SUGGESTIONS_LOCALES);
      })
      .catch(function () {
        showSuggestions(SUGGESTIONS_LOCALES);
      });
  }

  function setBusy(enCours) {
    el.send.disabled = enCours || !el.input.value.trim();
    el.input.disabled = enCours;
  }

  function sendMessage(msgPrete) {
    var msg = msgPrete || el.input.value.trim().slice(0, LONGUEUR_MAX);
    if (!msg || requeteEnCours) return;

    addMessage(msg, 'user');
    el.input.value = '';
    setBusy(true);
    hideSuggestions();

    var typing = addTypingIndicator();
    var controleur = new AbortController();
    requeteEnCours = controleur;
    var minuteur = setTimeout(function () { controleur.abort(); }, TIMEOUT_REPONSE_MS);

    fetch('/api/chatbot/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: msg, lang: langueActuelle() }),
      signal: controleur.signal
    })
      .then(function (r) {
        clearTimeout(minuteur);
        return r.json().catch(function () {
          return { success: false, error: _t('cb_erreur_serveur', 'Réponse illisible du serveur.') };
        });
      })
      .then(function (data) {
        removeTypingIndicator();
        if (data.success) {
          addMessage(data.response, 'bot', data.emergency, data.fiches);
        } else if (data.rate_limited) {
          addMessage('⏳ ' + (data.error || _t('cb_rate_limit', 'Trop de messages. Merci de patienter.')), 'bot');
        } else {
          addMessage(_t('cb_erreur_generique', 'Désolé, une erreur s\'est produite. Veuillez réessayer.'), 'bot');
        }
      })
      .catch(function (err) {
        clearTimeout(minuteur);
        removeTypingIndicator();
        addMessage(err && err.name === 'AbortError'
          ? _t('cb_erreur_timeout', 'La réponse met trop de temps à venir. Réessayez dans un instant.')
          : _t('cb_erreur_connexion', 'Erreur de connexion. Vérifiez votre connexion internet.'), 'bot');
      })
      .finally(function () {
        if (requeteEnCours === controleur) requeteEnCours = null;
        setBusy(false);
        el.input.focus();
      });
  }

  function effacerConversation() {
    Array.prototype.forEach.call(
      el.messages.querySelectorAll('.chatbot-message, .chatbot-suggestions'),
      function (nœud) { nœud.remove(); }
    );

    // Message d'accueil reconstruit : la cle i18n est posee sur le noeud
    // puis les tables partagees reecrivent le texte dans la langue active.
    var div = document.createElement('div');
    div.className = 'chatbot-message bot-message';
    div.setAttribute('data-i18n-node', '1');
    var avatar = document.createElement('div');
    avatar.className = 'message-avatar';
    avatar.innerHTML = '<i class="fas fa-robot"></i>';
    var contenu = document.createElement('div');
    contenu.className = 'message-content';
    contenu.setAttribute('data-i18n', 'cb_accueil_sans_chiffres');
    contenu.textContent = _t('cb_accueil_sans_chiffres',
      "Bonjour ! Je suis POSOLOGYAI L'ASSISTANT, votre assistant médical intelligent. Posez-moi vos questions sur les médicaments, leurs indications et leurs interactions.");
    div.appendChild(avatar);
    div.appendChild(contenu);
    el.messages.appendChild(div);

    fetch('/api/chatbot/reset', { method: 'POST' }).catch(function () {});
    loadSuggestions();
  }

  function toggle(force) {
    isOpen = typeof force === 'boolean' ? force : !isOpen;
    el.window.classList.toggle('open', isOpen);
    el.window.classList.remove('hidden');
    el.toggle.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
    if (isOpen) {
      el.input.focus();
      scrollToBottom();
    }
  }

  el.toggle.addEventListener('click', function (e) {
    e.stopPropagation();
    toggle();
  });

  el.close.addEventListener('click', function () { toggle(false); });

  if (el.clear) el.clear.addEventListener('click', effacerConversation);

  el.send.addEventListener('click', function () { sendMessage(); });

  el.input.addEventListener('input', function () {
    el.send.disabled = Boolean(requeteEnCours) || !el.input.value.trim();
  });

  el.input.addEventListener('keydown', function (e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  });

  // Fermeture au clic extérieur ; les touches clavier ferment aussi.
  document.addEventListener('click', function (e) {
    if (isOpen && !el.window.contains(e.target) && !el.toggle.contains(e.target)) {
      toggle(false);
    }
  });
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && isOpen) toggle(false);
  });

  /* Changement de langue : le moteur partage diffuse `posologyai:langue`.
     Les libelles statiques du widget sont repris par translatePage() ; ici
     on ne gere que ce qui est genere en JS : suggestions rechargees dans
     la nouvelle langue et noeuds dynamiques re-traduits. */
  document.addEventListener('posologyai:langue', function () {
    loadSuggestions();
    el.messages.querySelectorAll('[data-i18n]').forEach(function (nœud) {
      var cle = nœud.getAttribute('data-i18n');
      var texte = _t(cle, null);
      if (texte) nœud.textContent = texte;
    });
    if (typeof window.retraduire === 'function') window.retraduire();
  });

  /* Premier chargement des suggestions : attendre DOMContentLoaded quand
     le script s'execute avant, sinon la preference sauvegardee
     (localStorage / ?lang=) n'est pas encore lue par translations.js et
     les puces partaient toujours en francais. */
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', loadSuggestions);
  } else {
    loadSuggestions();
  }
})();
