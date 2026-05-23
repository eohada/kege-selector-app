(function() {
    if (window.__spaNavSyncInitialized) return;
    window.__spaNavSyncInitialized = true;

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

    function stripNavHtmxAttrs(root) {
        // Disabled to allow HTMX boosting on navigation links
    }

    function forceFullNavigation(evt) {
        // Disabled to allow HTMX navigation transitions
    }

    function applyPageMotion(root) {
        var scope = root && root.classList ? root : document.querySelector('main.app-main');
        if (!scope) return;

        var cardSelectors = [
            '.glass-panel', '.tactile-card', '.bento-card', '.student-card', 
            '.stat-card', '.filters-panel', '.filters-card', '.template-card', 
            '.profile-card', '.generator-mode', '.card', '.form-section', 
            '.theory-card', '.theory-bookmark-card', '.selection-card', 
            '.task-card', '.sub-card', '.locked-card', '.submission-comments', 
            '.inspector-card', '.empty-state', '.workspace-file-card', '.lesson-card'
        ].join(', ');

        var items = scope.querySelectorAll(cardSelectors);
        items.forEach(function(item, index) {
            item.classList.add('bs-motion-item');
            item.style.setProperty('--motion-index', index);
            item.style.setProperty('--motion-group', Math.floor(index / 4));
        });

        scope.classList.remove('bs-motion-page-enter');
        scope.offsetWidth; // trigger reflow
        scope.classList.add('bs-motion-page-enter');
    }

    function switchLocalView(targetView, mode) {
        if (!targetView) return;
        var container = targetView.parentElement || document;
        var currentView = container.querySelector('.view-section.active');
        if (!currentView || currentView === targetView) {
            targetView.classList.add('active');
            return;
        }
        currentView.classList.remove('active', 'swipe-in-right', 'swipe-in-left', 'drill-in-enter', 'drill-out-enter', 'swipe-out-left', 'swipe-out-right', 'drill-in-leave', 'drill-out-leave');
        targetView.classList.remove('swipe-in-right', 'swipe-in-left', 'drill-in-enter', 'drill-out-enter', 'swipe-out-left', 'swipe-out-right', 'drill-in-leave', 'drill-out-leave');
        targetView.classList.add('active');
    }

    function initTheoryShell(root) {
        var scope = root && root.querySelector ? root : document;
        var main = scope.matches && scope.matches('main.app-main') ? scope : document.querySelector('main.app-main');
        if (!main || !main.querySelector('#view-groups, #view-topics, #view-article')) return;

        var viewGroups = main.querySelector('#view-groups');
        var viewTopics = main.querySelector('#view-topics');
        var viewArticle = main.querySelector('#view-article');
        var grid = main.querySelector('#theoryGrid');
        var bookmarkedGrid = main.querySelector('#bookmarkedGrid');
        var search = main.querySelector('#theorySearch');
        var filterBtns = Array.prototype.slice.call(main.querySelectorAll('.theory-filter'));

        if (![viewGroups, viewTopics, viewArticle].some(function(view) { return view && view.classList.contains('active'); })) {
            if (viewGroups) viewGroups.classList.add('active');
        }

        window.__theoryOpenIndex = function() {
            if (viewGroups) switchLocalView(viewGroups, 'drill-out');
        };

        function setFilter(filter) {
            filterBtns.forEach(function(btn) {
                var active = btn.getAttribute('data-filter') === filter;
                btn.classList.toggle('bg-surface', active);
                btn.classList.toggle('text-primary', active);
                btn.classList.toggle('shadow-sm', active);
                btn.classList.toggle('dark:bg-white/10', active);
                btn.classList.toggle('dark:text-white', active);
                btn.classList.toggle('text-muted', !active);
                btn.classList.toggle('dark:text-dark-muted', !active);
            });

            if (grid) grid.classList.toggle('hidden', filter === 'bookmarked');
            if (bookmarkedGrid) bookmarkedGrid.classList.toggle('hidden', filter !== 'bookmarked');

            var cards = Array.prototype.slice.call((filter === 'bookmarked' ? bookmarkedGrid : grid || document.createElement('div')).querySelectorAll('[data-title]'));
            cards.forEach(function(card) {
                var count = Number(card.getAttribute('data-count') || '1');
                var bookmarkedCount = Number(card.getAttribute('data-bookmarked-count') || '0');
                var visible = true;
                if (filter === 'nonempty') visible = count > 0;
                if (filter === 'bookmarked') visible = bookmarkedCount > 0 || card.classList.contains('theory-bookmark-card');
                card.classList.toggle('hidden', !visible);
            });
        }

        function applySearch() {
            var query = ((search && search.value) || '').trim().toLowerCase();
            [grid, bookmarkedGrid].forEach(function(list) {
                if (!list) return;
                Array.prototype.slice.call(list.querySelectorAll('[data-title]')).forEach(function(card) {
                    var title = card.getAttribute('data-title') || '';
                    card.classList.toggle('hidden', query && title.indexOf(query) === -1);
                });
            });
        }

        filterBtns.forEach(function(btn) {
            if (btn.dataset.bsTheoryBound === '1') return;
            btn.dataset.bsTheoryBound = '1';
            btn.addEventListener('click', function() {
                setFilter(btn.getAttribute('data-filter') || 'all');
                applySearch();
            });
        });

        if (search && search.dataset.bsTheoryBound !== '1') {
            search.dataset.bsTheoryBound = '1';
            search.addEventListener('input', applySearch);
        }

        Array.prototype.slice.call(main.querySelectorAll('a[hx-target="#articleContainer"]')).forEach(function(link) {
            if (link.dataset.bsTheoryArticleBound === '1') return;
            link.dataset.bsTheoryArticleBound = '1';
            link.addEventListener('click', function() {
                if (viewArticle) setTransitionMode('drill-in');
            });
        });

        setFilter('all');
        applySearch();
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

    window.addEventListener('resize', function() {
        var main = document.querySelector('main.app-main');
        if (!main) return;
        var activePage = main.getAttribute('data-active-page') || '';
        var megaPages = (main.getAttribute('data-mega-active-pages') || '').split(',').map(function(page) {
            return page.trim();
        }).filter(Boolean);
        updateNavHighlight(activePage, megaPages);
    });

    document.addEventListener('click', forceFullNavigation, true);

    configureHtmxWhenReady(20);

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function() {
            configureHtmxWhenReady(20);
            stripNavHtmxAttrs();
            protectLocalHtmxControls();
            syncActiveNav();
            initTheoryShell();
            applyPageMotion();
        });
    } else {
        stripNavHtmxAttrs();
        protectLocalHtmxControls();
        syncActiveNav();
        initTheoryShell();
        applyPageMotion();
    }

    document.body.addEventListener('htmx:beforeRequest', function(evt) {
        var elt = evt.detail && evt.detail.elt;
        var link = elt && elt.closest ? elt.closest('a[href]') : lastClickedLink;
        setTransitionMode(inferTransitionMode(link));
    });

    document.body.addEventListener('htmx:afterSettle', function(evt) {
        protectLocalHtmxControls();
        stripNavHtmxAttrs(evt && evt.target ? evt.target : document);
        syncActiveNav();
        if (isMainSwap(evt)) {
            closeMobileMenus();
            initTheoryShell(evt.target);
            applyPageMotion(evt.target);
        }
        if (evt && evt.target && evt.target.id === 'articleContainer') {
            var articleView = document.querySelector('#view-article');
            if (articleView) switchLocalView(articleView, 'drill-in');
        }
        lastClickedLink = null;
    });
})();
