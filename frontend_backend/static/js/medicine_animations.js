/* ============================================================
   MEDICINE ANIMATIONS — GSAP premium interactions
   Inspired by Apple, Stripe, Linear, Vercel
   ============================================================ */
(function () {
    'use strict';

    if (typeof gsap === 'undefined') return;

    // ── Native smooth scroll ───────────────────────────────
    document.documentElement.style.scrollBehavior = 'smooth';

    // Connect GSAP ticker with native scroll for ScrollTrigger
    if (typeof ScrollTrigger !== 'undefined') {
        gsap.ticker.lagSmoothing(0);
    }

    // ── Utility: observe DOM ready ─────────────────────────
    function ready(fn) {
        if (document.readyState !== 'loading') { fn(); }
        else { document.addEventListener('DOMContentLoaded', fn); }
    }

    // ── Default easing ────────────────────────────────────
    var POWER_OUT = 'power3.out';
    var SPRING = 'back.out(1.4)';

    // ── Entrance animations ───────────────────────────────
    ready(function () {

        // Neutralize CSS entrance animations — GSAP handles them
        gsap.utils.toArray('.section-card, .medicine-hero').forEach(function(el) {
            el.style.animation = 'none';
            el.style.opacity = '0';
        });

        // Hero entrance
        var hero = document.querySelector('.medicine-hero');
        if (hero) {
            gsap.fromTo(hero,
                { opacity: 0, y: -30 },
                { opacity: 1, y: 0, duration: 0.8, ease: POWER_OUT, clearProps: 'y' }
            );
        }

        // Hero content staggered
        var heroName = document.querySelector('.medicine-hero-name');
        var heroSubstance = document.querySelector('.medicine-hero-substance');
        var heroMeta = document.querySelector('.medicine-hero-meta');
        var heroTags = document.querySelector('.medicine-hero-tags');
        var heroFav = document.querySelector('.hero-favorite');

        var heroEls = [heroName, heroSubstance, heroTags, heroMeta, heroFav].filter(Boolean);
        if (heroEls.length && hero) {
            gsap.fromTo(heroEls,
                { opacity: 0, y: 24 },
                { opacity: 1, y: 0, duration: 0.7, ease: POWER_OUT, stagger: 0.08, delay: 0.15, clearProps: 'y' }
            );
        }

        // Sidebar nav entrance
        var sidebar = document.querySelector('.medicine-nav-inner');
        if (sidebar) {
            gsap.fromTo(sidebar,
                { opacity: 0, x: -20 },
                { opacity: 1, x: 0, duration: 0.6, ease: POWER_OUT, delay: 0.25 }
            );
        }

        // Section cards entrance — staggered reveal on load
        var sectionCards = gsap.utils.toArray('.section-card');
        if (sectionCards.length) {
            gsap.fromTo(sectionCards,
                { opacity: 0, y: 30 },
                { opacity: 1, y: 0, duration: 0.6, ease: POWER_OUT, stagger: 0.07, delay: 0.3 }
            );
        }

        // Inner grid cards staggered (clinical, essential, molecule, sources)
        var gridGroups = [
            '.clinical-summary .clinical-card',
            '.essentials-grid .essential-card',
            '.molecule-grid .molecule-card',
            '.sources-grid .source-card',
            '.interactions-list .interaction-card',
            '.ext-db-grid .ext-db-card'
        ];

        gridGroups.forEach(function (sel) {
            var cards = gsap.utils.toArray(sel);
            if (cards.length) {
                gsap.fromTo(cards,
                    { opacity: 0, y: 20, scale: 0.97 },
                    { opacity: 1, y: 0, scale: 1, duration: 0.5, ease: POWER_OUT, stagger: 0.05, delay: 0.5 }
                );
            }
        });

        // Sidebar nav items staggered
        var navItems = gsap.utils.toArray('.medicine-nav-inner .nav-link');
        if (navItems.length) {
            gsap.fromTo(navItems,
                { opacity: 0, x: -12 },
                { opacity: 1, x: 0, duration: 0.4, ease: POWER_OUT, stagger: 0.03, delay: 0.3 }
            );
        }
    });

    // ── Hover animations ──────────────────────────────────
    ready(function () {

        // Section cards
        setupHover('.section-card', {
            enter: { scale: 1.02, y: -3, borderColor: '#6366f1', boxShadow: '0 12px 40px rgba(79,70,229,0.12), 0 4px 12px rgba(0,0,0,0.07)' },
            leave: { scale: 1, y: 0, borderColor: '#e5e7eb', boxShadow: '0 1px 3px rgba(0,0,0,0.04)' },
            duration: 0.4,
            ease: SPRING
        });

        // Clinical cards
        setupHover('.clinical-card', {
            enter: { scale: 1.02, y: -2, boxShadow: '0 8px 24px rgba(0,0,0,0.06)' },
            leave: { scale: 1, y: 0, boxShadow: 'none' },
            duration: 0.35,
            ease: SPRING
        });

        // Essential cards
        setupHover('.essential-card', {
            enter: { scale: 1.02, y: -2, boxShadow: '0 8px 24px rgba(0,0,0,0.06)' },
            leave: { scale: 1, y: 0, boxShadow: 'none' },
            duration: 0.35,
            ease: SPRING
        });

        // Molecule cards
        setupHover('.molecule-card', {
            enter: { scale: 1.025, y: -3, boxShadow: '0 8px 24px rgba(0,0,0,0.06)' },
            leave: { scale: 1, y: 0, boxShadow: 'none' },
            duration: 0.35,
            ease: SPRING
        });

        // Molecule symbol (inside card)
        setupHover('.molecule-card', {
            enter: { },
            leave: { },
            duration: 0.35,
            ease: SPRING,
            onEnter: function (el) {
                var symbol = el.querySelector('.molecule-symbol');
                if (symbol) gsap.to(symbol, { scale: 1.1, borderColor: '#c7d2fe', boxShadow: '0 4px 16px rgba(79,70,229,0.2)', duration: 0.35, ease: SPRING });
            },
            onLeave: function (el) {
                var symbol = el.querySelector('.molecule-symbol');
                if (symbol) gsap.to(symbol, { scale: 1, borderColor: '#e0e7ff', boxShadow: 'none', duration: 0.35, ease: SPRING });
            }
        });

        // Source cards
        setupHover('.source-card', {
            enter: { scale: 1.02, y: -2, boxShadow: '0 8px 24px rgba(99,102,241,0.1)' },
            leave: { scale: 1, y: 0, boxShadow: 'none' },
            duration: 0.35,
            ease: SPRING
        });

        // Interaction cards
        setupHover('.interaction-card', {
            enter: { scale: 1.015, y: -2, boxShadow: '0 8px 20px rgba(0,0,0,0.05)' },
            leave: { scale: 1, y: 0, boxShadow: 'none' },
            duration: 0.35,
            ease: SPRING
        });

        // Ext-db cards
        setupHover('.ext-db-card', {
            enter: { scale: 1.02, y: -2, boxShadow: '0 8px 20px rgba(0,0,0,0.05)' },
            leave: { scale: 1, y: 0, boxShadow: 'none' },
            duration: 0.35,
            ease: SPRING
        });

        // Comment items
        setupHover('.comment-item', {
            enter: { scale: 1.008, y: -1, boxShadow: '0 4px 16px rgba(0,0,0,0.04)' },
            leave: { scale: 1, y: 0, boxShadow: 'none' },
            duration: 0.3,
            ease: SPRING
        });

        // Sidebar nav links
        setupHover('.nav-link', {
            enter: { x: 3 },
            leave: { x: 0 },
            duration: 0.3,
            ease: SPRING
        });

        // Favorite button
        var favBtn = document.querySelector('.favorite-btn');
        if (favBtn) {
            favBtn.style.transition = 'none';
            favBtn.addEventListener('mouseenter', function () {
                gsap.to(this, { scale: 1.04, y: -2, duration: 0.35, ease: SPRING });
                var icon = this.querySelector('.heart-icon');
                if (icon) gsap.to(icon, { scale: 1.25, duration: 0.35, ease: SPRING });
            });
            favBtn.addEventListener('mouseleave', function () {
                gsap.to(this, { scale: 1, y: 0, duration: 0.35, ease: SPRING });
                var icon = this.querySelector('.heart-icon');
                if (icon) gsap.to(icon, { scale: 1, duration: 0.35, ease: SPRING });
            });
        }

        // Source card button
        setupHover('.source-card-btn', {
            enter: { scale: 1.06, boxShadow: '0 2px 6px rgba(79,70,229,0.15)' },
            leave: { scale: 1, boxShadow: 'none' },
            duration: 0.25,
            ease: SPRING
        });

        // Collapsible toggle
        setupHover('.collapsible-toggle', {
            enter: { y: -1 },
            leave: { y: 0 },
            duration: 0.25,
            ease: SPRING
        });

        // Sidebar nav items
        gsap.utils.toArray('.nav-link').forEach(function(el) {
            el.style.transition = 'none';
        });
    });

    // ── Click effects ─────────────────────────────────────
    ready(function () {
        var clickSelectors = [
            '.section-card',
            '.clinical-card',
            '.essential-card',
            '.molecule-card',
            '.source-card',
            '.interaction-card',
            '.ext-db-card',
            '.comment-item',
            '.favorite-btn',
            '.collapsible-toggle',
            '.source-card-btn',
            '.tech-item'
        ];

        clickSelectors.forEach(function (sel) {
            var els = gsap.utils.toArray(sel);
            els.forEach(function (el) {
                el.style.transition = 'none';
                el.addEventListener('mousedown', function () {
                    gsap.to(this, { scale: 0.98, duration: 0.12, ease: 'power2.out', overwrite: 'auto' });
                });
                el.addEventListener('mouseup', function () {
                    gsap.to(this, { scale: 1, duration: 0.25, ease: SPRING, overwrite: 'auto' });
                });
                el.addEventListener('mouseleave', function () {
                    gsap.to(this, { scale: 1, duration: 0.25, ease: SPRING, overwrite: 'auto' });
                });
            });
        });

        // Molecule symbol — clear CSS transition
        gsap.utils.toArray('.molecule-symbol').forEach(function(el) { el.style.transition = 'none'; });
    });

    // ── Scroll-triggered reveals ───────────────────────────
    ready(function () {
        if (typeof ScrollTrigger === 'undefined') return;

        var revealCards = gsap.utils.toArray('.section-card');
        revealCards.forEach(function (card) {
            if (card.getBoundingClientRect().top > window.innerHeight) {
                gsap.fromTo(card,
                    { opacity: 0, y: 40 },
                    { opacity: 1, y: 0, duration: 0.6, ease: POWER_OUT,
                      scrollTrigger: { trigger: card, start: 'top 85%', toggleActions: 'play none none none' } }
                );
            }
        });

        // Animate collapsible content on expand
        var collapsibleContents = gsap.utils.toArray('.collapsible-content');
        collapsibleContents.forEach(function (content) {
            if (content.classList.contains('expanded')) {
                gsap.set(content, { maxHeight: 'none' });
            }
        });
    });

    // ── Smooth scroll nav ─────────────────────────────────
    ready(function () {
        var allNavLinks = document.querySelectorAll('.nav-link[href^="#"]');
        allNavLinks.forEach(function (link) {
            link.addEventListener('click', function (e) {
                e.preventDefault();
                var targetId = this.getAttribute('href').substring(1);
                var target = document.getElementById(targetId);
                if (target) {
                    allNavLinks.forEach(function (l) { l.classList.remove('active'); });
                    this.classList.add('active');
                    target.scrollIntoView({ behavior: 'smooth', block: 'start' });
                    // Offset for sticky header
                    window.scrollBy(0, -100);
                }
            });
        });

        // Scroll spy
        var navLinks = gsap.utils.toArray('.nav-link[href^="#"]');
        var anchors = gsap.utils.toArray('.section-anchor');
        if (navLinks.length && anchors.length) {
            window.addEventListener('scroll', function () {
                var scrollPos = window.scrollY + 120;
                var currentId = '';
                anchors.forEach(function (anchor) {
                    var section = anchor.nextElementSibling;
                    if (!section) return;
                    var sectionTop = section.offsetTop;
                    var sectionHeight = section.offsetHeight;
                    if (scrollPos >= sectionTop && scrollPos < sectionTop + sectionHeight) {
                        currentId = anchor.getAttribute('id');
                    }
                });
                if (currentId) {
                    navLinks.forEach(function (link) {
                        link.classList.remove('active');
                        if (link.getAttribute('href') === '#' + currentId) {
                            link.classList.add('active');
                        }
                    });
                }
            });
        }
    });

    // ── Helper: setupHover ────────────────────────────────
    function setupHover(selector, config) {
        var els = gsap.utils.toArray(selector);
        if (!els.length) return;

        els.forEach(function (el) {
            el.style.transition = 'none';

            el.addEventListener('mouseenter', function () {
                if (config.onEnter) config.onEnter(el);
                var vars = {};
                for (var k in config.enter) { vars[k] = config.enter[k]; }
                vars.duration = config.duration || 0.35;
                vars.ease = config.ease || POWER_OUT;
                vars.overwrite = 'auto';
                gsap.to(el, vars);
            });
            el.addEventListener('mouseleave', function () {
                if (config.onLeave) config.onLeave(el);
                var vars = {};
                for (var k in config.leave) { vars[k] = config.leave[k]; }
                vars.duration = config.duration || 0.35;
                vars.ease = config.ease || POWER_OUT;
                vars.overwrite = 'auto';
                gsap.to(el, vars);
            });
        });
    }

})();
