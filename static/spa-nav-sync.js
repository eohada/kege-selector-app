(function() {
    var NAV_ORDER = {
        parent_dashboard: 0,
        student_dashboard: 0,
        dashboard: 0,
        student_profile: 1,
        schedule: 2,
        assignments: 3,
        review_queue: 3,
        trainer: 4,
        theory: 5,
        theory_manage: 5,
        student_analytics: 6,
        chief_tester_dashboard: 7,
        reminders: 8,
        generator: 9,
        templates: 10,
        library: 11,
        groups: 12,
        billing: 13,
        faq: 20,
        profile: 30,
        notifications: 31
    };

    var lastClickedLink = null;
    var resetTransitionTimer = null;

    function configureHtmx() {
        if (!window.htmx || !window.htmx.config) return false;
        window.htmx.config.globalViewTransitions = true;
        return true;
    }

    function configureHtmxWhenReady(attemptsLeft) {
        if (configureHtmx()) return;
        if (attemptsLeft <= 0) return;
        setTimeout(function() {
            configureHtmxWhenReady(attemptsLeft - 1);
        }, 50);
    }

    function keyMatches(element, activePage) {
        var raw = element.getAttribute('data-nav-key') || '';
        if (!raw || !activePage) return false;
        return raw.split(/[\s,]+/).filter(Boolean).indexOf(activePage) !== -1;
    }

    function getCurrentActivePage() {
        var main = document.querySelector('main.app-main');
        return main ? (main.getAttribute('data-active-page') || '') : '';
    }

    function getNavOrder(page) {
        return Object.prototype.hasOwnProperty.call(NAV_ORDER, page) ? NAV_ORDER[page] : 50;
    }

    function setTransitionMode(mode) {
        if (!mode) return;
        document.documentElement.setAttribute('data-bs-transition', mode);
        if (resetTransitionTimer) clearTimeout(resetTransitionTimer);
        resetTransitionTimer = setTimeout(function() {
            document.documentElement.removeAttribute('data-bs-transition');
        }, 900);
    }

    function isInternalNavigableLink(link) {
        if (!link || !link.href) return false;
        if (link.target && link.target !== '_self') return false;
        if (link.hasAttribute('download')) return false;
        if (link.getAttribute('href') === '#') return false;
        if (link.origin !== window.location.origin) return false;
        return true;
    }

    function inferTransitionMode(link) {
        if (!isInternalNavigableLink(link)) return '';

        var currentPage = getCurrentActivePage();
        var targetPage = link.getAttribute('data-nav-key') || '';
        if (targetPage) {
            var currentOrder = getNavOrder(currentPage);
            var targetOrder = getNavOrder(targetPage);
            if (targetOrder === currentOrder) return 'drill-in';
            return targetOrder > currentOrder ? 'swipe-right' : 'swipe-left';
        }

        if (link.closest('main.app-main')) {
            var text = (link.textContent || '').trim().toLowerCase();
            var href = link.getAttribute('href') || '';
            if (/назад|к списку|вернуться|back/.test(text) || /[?&](back|return)=/.test(href)) {
                return 'drill-out';
            }
            return 'drill-in';
        }

        return 'swipe-right';
    }

    function syncActiveNav() {
        var main = document.querySelector('main.app-main');
        if (!main) return;

        var activePage = main.getAttribute('data-active-page') || '';
        var megaPages = (main.getAttribute('data-mega-active-pages') || '')
            .split(',')
            .map(function(page) { return page.trim(); })
            .filter(Boolean);

        Array.prototype.slice.call(document.querySelectorAll('[data-nav-key]')).forEach(function(link) {
            link.classList.toggle('active', keyMatches(link, activePage));
        });

        Array.prototype.slice.call(document.querySelectorAll('[data-mega-nav-trigger]')).forEach(function(trigger) {
            trigger.classList.toggle('active', megaPages.indexOf(activePage) !== -1);
        });

        updateNavHighlight(activePage, megaPages);
    }

    function updateNavHighlight(activePage, megaPages) {
        var nav = document.querySelector('.dock-nav');
        var highlight = nav ? nav.querySelector('[data-nav-highlight]') : null;
        if (!nav || !highlight) return;

        var active = nav.querySelector('[data-nav-key].active');
        if (!active && megaPages && megaPages.indexOf(activePage) !== -1) {
            active = nav.querySelector('[data-mega-nav-trigger]');
        }
        if (!active || active.closest('.dock-mega-panel')) {
            highlight.style.opacity = '0';
            return;
        }

        var navRect = nav.getBoundingClientRect();
        var itemRect = active.getBoundingClientRect();
        highlight.style.width = itemRect.width + 'px';
        highlight.style.height = itemRect.height + 'px';
        highlight.style.transform = 'translate3d(' + (itemRect.left - navRect.left) + 'px, ' + (itemRect.top - navRect.top) + 'px, 0)';
        highlight.style.opacity = '1';
    }

    function addDisinherit(element, names) {
        var current = (element.getAttribute('hx-disinherit') || '').split(/\s+/).filter(Boolean);
        names.forEach(function(name) {
            if (current.indexOf(name) === -1) current.push(name);
        });
        element.setAttribute('hx-disinherit', current.join(' '));
    }

    function protectLocalHtmxControls() {
        var main = document.querySelector('main.app-main');
        if (!main) return;

        Array.prototype.slice.call(main.querySelectorAll('form')).forEach(function(form) {
            if (!form.hasAttribute('hx-boost')) form.setAttribute('hx-boost', 'false');
        });

        Array.prototype.slice.call(main.querySelectorAll('[hx-get], [hx-post], [hx-put], [hx-patch], [hx-delete]')).forEach(function(control) {
            if (control.hasAttribute('data-spa-nav')) return;
            addDisinherit(control, ['hx-select', 'hx-target', 'hx-swap', 'hx-push-url']);
        });
    }

    function applyPageMotion(root) {
        var main = root && root.matches && root.matches('main.app-main')
            ? root
            : document.querySelector('main.app-main');
        if (!main) return;

        var selector = [
            '.app-content > *',
            '.glass-panel',
            '.card',
            '.form-section',
            '.theory-card',
            '.theory-bookmark-card',
            '.selection-card',
            '.task-card',
            '.sub-card',
            '.locked-card',
            '.submission-comments',
            '.inspector-card',
            '.workspace-file-card',
            '.lesson-card',
            '.empty-state'
        ].join(',');

        var seen = [];
        Array.prototype.slice.call(main.querySelectorAll(selector)).forEach(function(item) {
            if (seen.indexOf(item) === -1) seen.push(item);
        });

        seen.slice(0, 64).forEach(function(item, index) {
            var group = Math.min(Math.floor(index / 5), 2);
            item.classList.remove('bs-motion-item');
            item.style.setProperty('--motion-group', group);
            item.style.setProperty('--motion-index', index);
            item.classList.add('bs-motion-item');
        });

        main.classList.remove('bs-motion-page-enter');
        // Restart the entrance animation after htmx swaps the main shell.
        void main.offsetWidth;
        main.classList.add('bs-motion-page-enter');
    }

    function closeMobileMenus() {
        Array.prototype.slice.call(document.querySelectorAll('[data-mobile-menu-root]')).forEach(function(root) {
            var toggle = root.querySelector('[data-mobile-menu-toggle]');
            var menu = root.querySelector('[data-mobile-menu]');
            var overlay = root.querySelector('[data-mobile-menu-overlay]');

            if (toggle) toggle.classList.remove('active');
            if (menu) {
                menu.classList.remove('active');
                menu.style.transform = 'translateX(100%)';
            }
            if (overlay) {
                overlay.classList.remove('active');
                overlay.style.display = 'none';
            }
        });

        document.body.style.position = '';
        document.body.style.top = '';
        document.body.style.left = '';
        document.body.style.right = '';
        document.body.style.width = '';
        document.body.style.overflow = '';
    }

    function isMainSwap(evt) {
        return evt && evt.target && evt.target.matches && evt.target.matches('main.app-main');
    }

    document.addEventListener('click', function(evt) {
        var link = evt.target && evt.target.closest ? evt.target.closest('a[href]') : null;
        if (!isInternalNavigableLink(link)) return;
        lastClickedLink = link;
        setTransitionMode(inferTransitionMode(link));
    }, true);

    window.addEventListener('resize', function() {
        var main = document.querySelector('main.app-main');
        if (!main) return;
        var activePage = main.getAttribute('data-active-page') || '';
        var megaPages = (main.getAttribute('data-mega-active-pages') || '').split(',').map(function(page) {
            return page.trim();
        }).filter(Boolean);
        updateNavHighlight(activePage, megaPages);
    });

    configureHtmxWhenReady(20);

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function() {
            configureHtmxWhenReady(20);
            protectLocalHtmxControls();
            syncActiveNav();
            applyPageMotion();
        });
    } else {
        protectLocalHtmxControls();
        syncActiveNav();
        applyPageMotion();
    }

    document.body.addEventListener('htmx:beforeRequest', function(evt) {
        var elt = evt.detail && evt.detail.elt;
        var link = elt && elt.closest ? elt.closest('a[href]') : lastClickedLink;
        setTransitionMode(inferTransitionMode(link));
    });

    document.body.addEventListener('htmx:afterSettle', function(evt) {
        protectLocalHtmxControls();
        syncActiveNav();
        if (isMainSwap(evt)) {
            closeMobileMenus();
            applyPageMotion(evt.target);
        }
        lastClickedLink = null;
    });
})();
