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

    var MAIN_TABS = {
        parent_dashboard: true,
        student_dashboard: true,
        dashboard: true,
        schedule: true,
        assignments: true,
        review_queue: true,
        trainer: true,
        theory: true,
        student_analytics: true,
        chief_tester_dashboard: true
    };

    function guessPageNameFromPath(path) {
        if (!path) return '';
        if (path === '/' || path.indexOf('/dashboard') !== -1) {
            return 'dashboard';
        } else if (path.indexOf('/review') !== -1) {
            return 'review_queue';
        } else if (path.indexOf('/trainer') !== -1) {
            return 'trainer';
        } else if (path.indexOf('/theory') !== -1) {
            return 'theory';
        } else if (path.indexOf('/profile') !== -1) {
            return 'profile';
        } else if (path.indexOf('/schedule') !== -1) {
            return 'schedule';
        } else if (path.indexOf('/assignments') !== -1) {
            return 'assignments';
        } else if (path.indexOf('/templates') !== -1) {
            return 'templates';
        } else if (path.indexOf('/generator') !== -1) {
            return 'generator';
        } else if (path.indexOf('/library') !== -1) {
            return 'library';
        } else if (path.indexOf('/groups') !== -1) {
            return 'groups';
        } else if (path.indexOf('/billing') !== -1) {
            return 'billing';
        }
        return '';
    }

    function updateHistoryStack() {
        try {
            var currentUrl = window.location.pathname + window.location.search;
            var stack = JSON.parse(sessionStorage.getItem('bs-history-stack') || '[]');
            var idx = stack.indexOf(currentUrl);
            if (idx !== -1) {
                stack = stack.slice(0, idx + 1);
            } else {
                stack.push(currentUrl);
            }
            sessionStorage.setItem('bs-history-stack', JSON.stringify(stack));
        } catch (e) {
            console.error('History stack error', e);
        }
    }

    function isGoingBackInHistory(targetUrl) {
        try {
            var stack = JSON.parse(sessionStorage.getItem('bs-history-stack') || '[]');
            if (stack.length < 2) return false;
            var prevUrl = stack[stack.length - 2];
            return prevUrl && prevUrl === targetUrl;
        } catch (e) {
            return false;
        }
    }

    function configureHtmx() {
        if (!window.htmx || !window.htmx.config) return false;
        window.htmx.config.globalViewTransitions = false;
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

    function inferTransitionMode(link, targetUrl) {
        var currentPage = getCurrentActivePage();
        var targetPage = '';

        if (link) {
            if (!isInternalNavigableLink(link)) return '';
            targetPage = link.getAttribute('data-nav-key') || '';
        }
        
        if (!targetPage && targetUrl) {
            targetPage = guessPageNameFromPath(targetUrl);
        } else if (link && !targetPage) {
            var href = link.getAttribute('href') || '';
            targetPage = guessPageNameFromPath(href);
        }

        // If no link, it is a history popstate navigation
        var isHistory = !link;
        var goingBack = isHistory && targetUrl ? isGoingBackInHistory(targetUrl) : false;

        if (targetPage && currentPage) {
            var currentOrder = getNavOrder(currentPage);
            var targetOrder = getNavOrder(targetPage);

            // Tab navigation: both pages are main tabs
            if (MAIN_TABS[currentPage] && MAIN_TABS[targetPage]) {
                if (targetOrder === currentOrder) return 'drill-in';
                if (isHistory) {
                    return goingBack ? (targetOrder < currentOrder ? 'swipe-left' : 'swipe-right') : (targetOrder > currentOrder ? 'swipe-right' : 'swipe-left');
                }
                return targetOrder > currentOrder ? 'swipe-right' : 'swipe-left';
            }

            // Drill navigation: at least one is a subpage
            if (isHistory) {
                return goingBack ? 'drill-out' : 'drill-in';
            }
            
            // If clicking a main tab to go back from a subpage
            if (MAIN_TABS[targetPage] && !MAIN_TABS[currentPage]) {
                return 'drill-out';
            }
        }

        // Content area links: drill-in/out
        if (link && link.closest('main.app-main')) {
            var text = (link.textContent || '').trim().toLowerCase();
            var href = link.getAttribute('href') || '';
            if (/←|назад|вернуться|back|к списку|к ученикам|к задачам|к пользователям|к тестировщикам/.test(text) || /[?&](back|return)=/.test(href)) {
                return 'drill-out';
            }
            return 'drill-in';
        }

        return isHistory && goingBack ? 'drill-out' : 'drill-in';
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
        if (!evt || !evt.target) return false;
        var target = evt.target;
        return (typeof target.matches === 'function' && (
            target.matches('main.app-main') || 
            target.matches('body') || 
            target.matches('html')
        )) || (typeof target.querySelector === 'function' && target.querySelector('main.app-main') !== null);
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

    document.addEventListener('click', function(evt) {
        var link = evt.target && evt.target.closest ? evt.target.closest('a[href]') : null;
        if (link) {
            lastClickedLink = link;
        }
    }, true);

    function saveCurrentBodyState() {
        try {
            var url = window.location.pathname + window.location.search;
            var states = JSON.parse(sessionStorage.getItem('bs-body-states') || '{}');
            
            var attrs = {};
            for (var i = 0; i < document.body.attributes.length; i++) {
                var attr = document.body.attributes[i];
                if (attr.name !== 'class' && attr.name !== 'style' && attr.name !== 'id') {
                    attrs[attr.name] = attr.value;
                }
            }
            
            var metas = {};
            var pageSpecific = ['page-endpoint', 'user-timezone-effective', 'user-timezone-mode', 'user-timezone-iana', 'cinema-demo-ids'];
            Array.prototype.slice.call(document.querySelectorAll('head meta')).forEach(function(meta) {
                var key = meta.getAttribute('name') || meta.getAttribute('property');
                if (key && pageSpecific.indexOf(key) !== -1) {
                    metas[key] = meta.getAttribute('content');
                }
            });

            states[url] = {
                className: document.body.className,
                attributes: attrs,
                metas: metas
            };
            sessionStorage.setItem('bs-body-states', JSON.stringify(states));
        } catch (e) {
            console.error('Error saving body state', e);
        }
    }

    function restoreBodyState(targetUrl) {
        try {
            var states = JSON.parse(sessionStorage.getItem('bs-body-states') || '{}');
            var state = states[targetUrl];
            if (state) {
                document.body.className = state.className || '';
                
                var preservedAttrs = ['hx-boost', 'hx-indicator', 'id', 'style'];
                var attrsToRemove = [];
                for (var i = 0; i < document.body.attributes.length; i++) {
                    var attrName = document.body.attributes[i].name;
                    if (preservedAttrs.indexOf(attrName) === -1 && attrName !== 'class') {
                        attrsToRemove.push(attrName);
                    }
                }
                attrsToRemove.forEach(function(attrName) {
                    document.body.removeAttribute(attrName);
                });

                if (state.attributes) {
                    for (var key in state.attributes) {
                        if (Object.prototype.hasOwnProperty.call(state.attributes, key)) {
                            document.body.setAttribute(key, state.attributes[key]);
                        }
                    }
                }

                if (state.metas) {
                    var currentHead = document.head;
                    for (var key in state.metas) {
                        if (Object.prototype.hasOwnProperty.call(state.metas, key)) {
                            var meta = currentHead.querySelector('meta[name="' + key + '"]') || currentHead.querySelector('meta[property="' + key + '"]');
                            if (meta) {
                                meta.setAttribute('content', state.metas[key]);
                            } else {
                                var newMeta = document.createElement('meta');
                                newMeta.setAttribute(key.indexOf('og:') === 0 || key.indexOf('twitter:') === 0 ? 'property' : 'name', key);
                                newMeta.setAttribute('content', state.metas[key]);
                                currentHead.appendChild(newMeta);
                            }
                        }
                    }
                    
                    var pageSpecific = ['page-endpoint', 'user-timezone-effective', 'user-timezone-mode', 'user-timezone-iana', 'cinema-demo-ids'];
                    pageSpecific.forEach(function(key) {
                        if (!Object.prototype.hasOwnProperty.call(state.metas, key)) {
                            var meta = currentHead.querySelector('meta[name="' + key + '"]') || currentHead.querySelector('meta[property="' + key + '"]');
                            if (meta) {
                                meta.remove();
                            }
                        }
                    });
                }
                return true;
            }
        } catch (e) {
            console.error('Error restoring body state', e);
        }
        return false;
    }

    function syncMetaTags(responseDoc) {
        try {
            var newMetas = responseDoc.querySelectorAll('head meta');
            var currentHead = document.head;
            
            var newMetaMap = {};
            Array.prototype.slice.call(newMetas).forEach(function(meta) {
                var key = meta.getAttribute('name') || meta.getAttribute('property');
                if (key) {
                    newMetaMap[key] = meta.getAttribute('content');
                }
            });

            var currentMetas = currentHead.querySelectorAll('meta');
            Array.prototype.slice.call(currentMetas).forEach(function(meta) {
                var key = meta.getAttribute('name') || meta.getAttribute('property');
                if (key) {
                    if (Object.prototype.hasOwnProperty.call(newMetaMap, key)) {
                        meta.setAttribute('content', newMetaMap[key]);
                        delete newMetaMap[key];
                    } else {
                        var pageSpecific = ['page-endpoint', 'user-timezone-effective', 'user-timezone-mode', 'user-timezone-iana', 'cinema-demo-ids'];
                        if (pageSpecific.indexOf(key) !== -1) {
                            meta.remove();
                        }
                    }
                }
            });

            for (var key in newMetaMap) {
                if (Object.prototype.hasOwnProperty.call(newMetaMap, key)) {
                    var newMeta = document.createElement('meta');
                    newMeta.setAttribute(key.indexOf('og:') === 0 || key.indexOf('twitter:') === 0 ? 'property' : 'name', key);
                    newMeta.setAttribute('content', newMetaMap[key]);
                    currentHead.appendChild(newMeta);
                }
            }
        } catch (e) {
            console.error('Error syncing meta tags', e);
        }
    }
 
    function syncHeadStyles(responseDoc) {
        try {
            var newStyles = responseDoc.querySelectorAll('head style, head link[rel="stylesheet"]');
            var currentHead = document.head;
            
            var existingHrefs = [];
            var existingTexts = [];
            
            Array.prototype.slice.call(currentHead.querySelectorAll('link[rel="stylesheet"]')).forEach(function(link) {
                if (link.href) existingHrefs.push(link.href);
            });
            Array.prototype.slice.call(currentHead.querySelectorAll('style')).forEach(function(style) {
                existingTexts.push(style.textContent);
            });
 
            Array.prototype.slice.call(newStyles).forEach(function(el) {
                if (el.tagName.toLowerCase() === 'link') {
                    var href = el.href;
                    if (href && existingHrefs.indexOf(href) === -1) {
                        var newLink = document.createElement('link');
                        newLink.rel = 'stylesheet';
                        newLink.href = el.getAttribute('href');
                        currentHead.appendChild(newLink);
                    }
                } else if (el.tagName.toLowerCase() === 'style') {
                    var text = el.textContent;
                    if (existingTexts.indexOf(text) === -1) {
                        var newStyle = document.createElement('style');
                        newStyle.textContent = text;
                        currentHead.appendChild(newStyle);
                    }
                }
            });
        } catch (e) {
            console.error('Error syncing head styles', e);
        }
    }
 
    function syncHeadScripts(responseDoc) {
        try {
            var newScripts = responseDoc.querySelectorAll('head script');
            var currentHead = document.head;
            
            var existingSrcs = [];
            Array.prototype.slice.call(document.querySelectorAll('script')).forEach(function(script) {
                var src = script.getAttribute('src');
                if (src) {
                    var tempLink = document.createElement('a');
                    tempLink.href = src;
                    existingSrcs.push(tempLink.href);
                }
            });
 
            Array.prototype.slice.call(newScripts).forEach(function(script) {
                var src = script.getAttribute('src');
                if (src) {
                    var tempLink = document.createElement('a');
                    tempLink.href = src;
                    if (existingSrcs.indexOf(tempLink.href) === -1) {
                        var newScript = document.createElement('script');
                        for (var i = 0; i < script.attributes.length; i++) {
                            var attr = script.attributes[i];
                            newScript.setAttribute(attr.name, attr.value);
                        }
                        currentHead.appendChild(newScript);
                    }
                } else {
                    var newScript = document.createElement('script');
                    newScript.textContent = script.textContent;
                    currentHead.appendChild(newScript);
                }
            });
        } catch (e) {
            console.error('Error syncing head scripts', e);
        }
    }
 
    function syncPageMetadataAndAttributes(htmlString) {
        if (!htmlString) return;
        try {
            var parser = new DOMParser();
            var doc = parser.parseFromString(htmlString, 'text/html');
            
            syncMetaTags(doc);
            syncHeadStyles(doc);
            syncHeadScripts(doc);

            // Sync html attributes (such as data-student-theory="1", etc.)
            var newHtml = doc.documentElement;
            if (newHtml) {
                var preservedHtmlAttrs = ['data-theme', 'data-theme-mode', 'lang'];
                var htmlAttrsToRemove = [];
                for (var i = 0; i < document.documentElement.attributes.length; i++) {
                    var attrName = document.documentElement.attributes[i].name;
                    if (preservedHtmlAttrs.indexOf(attrName) === -1) {
                        htmlAttrsToRemove.push(attrName);
                    }
                }
                htmlAttrsToRemove.forEach(function(attrName) {
                    document.documentElement.removeAttribute(attrName);
                });

                for (var i = 0; i < newHtml.attributes.length; i++) {
                    var attr = newHtml.attributes[i];
                    if (preservedHtmlAttrs.indexOf(attr.name) === -1) {
                        document.documentElement.setAttribute(attr.name, attr.value);
                    }
                }
            }

            var newBody = doc.querySelector('body');
            if (newBody) {
                document.body.className = newBody.className;

                var preservedAttrs = ['hx-boost', 'hx-indicator', 'id', 'style'];
                var attrsToRemove = [];
                for (var i = 0; i < document.body.attributes.length; i++) {
                    var attrName = document.body.attributes[i].name;
                    if (preservedAttrs.indexOf(attrName) === -1 && attrName !== 'class') {
                        attrsToRemove.push(attrName);
                    }
                }
                attrsToRemove.forEach(function(attrName) {
                    document.body.removeAttribute(attrName);
                });

                for (var i = 0; i < newBody.attributes.length; i++) {
                    var attr = newBody.attributes[i];
                    if (preservedAttrs.indexOf(attr.name) === -1 && attr.name !== 'class') {
                        document.body.setAttribute(attr.name, attr.value);
                    }
                }
            }
        } catch (e) {
            console.error('Error syncing page metadata and body attributes', e);
        }
    }

    configureHtmxWhenReady(20);

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function() {
            configureHtmxWhenReady(20);
            stripNavHtmxAttrs();
            protectLocalHtmxControls();
            syncActiveNav();
            initTheoryShell();
            if (window.initPremiumSchedule) {
                window.initPremiumSchedule();
            }
            applyPageMotion();
            updateHistoryStack();
            saveCurrentBodyState();
        });
    } else {
        stripNavHtmxAttrs();
        protectLocalHtmxControls();
        syncActiveNav();
        initTheoryShell();
        if (window.initPremiumSchedule) {
            window.initPremiumSchedule();
        }
        applyPageMotion();
        updateHistoryStack();
        saveCurrentBodyState();
    }

    document.body.addEventListener('htmx:beforeRequest', function(evt) {
        window.__htmxSwapping = true;
        if (resetTransitionTimer) {
            clearTimeout(resetTransitionTimer);
            resetTransitionTimer = null;
        }
        var elt = evt.detail && evt.detail.elt;
        var link = elt && elt.closest ? elt.closest('a[href]') : lastClickedLink;
        var path = evt.detail && evt.detail.path;
        
        var isHistory = !elt || elt === document.body || elt === document.documentElement;
        var finalLink = isHistory ? null : link;
        
        setTransitionMode(inferTransitionMode(finalLink, path));
    });

    document.body.addEventListener('htmx:beforeSwap', function(evt) {
        if (isMainSwap(evt) && evt.detail.xhr && evt.detail.xhr.responseText) {
            syncPageMetadataAndAttributes(evt.detail.xhr.responseText);
        }
    });

    document.body.addEventListener('htmx:historyRestore', function(evt) {
        if (evt.detail && evt.detail.path) {
            restoreBodyState(evt.detail.path);
        } else {
            var targetUrl = window.location.pathname + window.location.search;
            restoreBodyState(targetUrl);
        }
    });

    window.addEventListener('popstate', function() {
        var targetUrl = window.location.pathname + window.location.search;
        restoreBodyState(targetUrl);
    });

    document.body.addEventListener('htmx:requestError', function() {
        window.__htmxSwapping = false;
    });
    document.body.addEventListener('htmx:sendError', function() {
        window.__htmxSwapping = false;
    });
    document.body.addEventListener('htmx:afterSettle', function(evt) {
        try {
            if (window.updateThemeToggles) {
                try { window.updateThemeToggles(); } catch (e) {}
            }
            protectLocalHtmxControls();
            stripNavHtmxAttrs(evt && evt.target ? evt.target : document);
            syncActiveNav();
            if (isMainSwap(evt)) {
                closeMobileMenus();
                initTheoryShell(evt.target);
                if (window.initPremiumSchedule) {
                    window.initPremiumSchedule();
                }
                applyPageMotion(evt.target);
                updateHistoryStack();
                saveCurrentBodyState();

                // Re-run global initializers for the swapped DOM scope
                var scope = evt.target;
                if (window.initCsrfHelper) {
                    window.initCsrfHelper(scope);
                }
                if (window.initConfirmModals) {
                    window.initConfirmModals(scope);
                }
                if (window.initFormToastHandlers) {
                    window.initFormToastHandlers(scope);
                }
                if (window.initFilterStorage) {
                    window.initFilterStorage(scope);
                }
                if (window.initFilterStateManager) {
                    window.initFilterStateManager();
                }
                if (window.initScrollToTop) {
                    window.initScrollToTop();
                }
                if (window.BooCanvasOverlay && typeof window.BooCanvasOverlay.init === 'function') {
                    window.BooCanvasOverlay.init();
                }
                if (window.initMobileMenu) {
                    window.initMobileMenu();
                }
                if (typeof window.initStudentForms === 'function') {
                    window.initStudentForms();
                }
                if (typeof window.initStudentCards === 'function') {
                    window.initStudentCards();
                }
                if (typeof window.initLessonPage === 'function') {
                    window.initLessonPage();
                }
                if (typeof window.initAssignmentCreate === 'function') {
                    window.initAssignmentCreate();
                }
                if (typeof window.initTaskGenerator === 'function') {
                    window.initTaskGenerator();
                }
                if (typeof window.initKegeGenerator === 'function') {
                    window.initKegeGenerator();
                }
            }
            if (evt && evt.target && evt.target.id === 'articleContainer') {
                var articleView = document.querySelector('#view-article');
                if (articleView) switchLocalView(articleView, 'drill-in');
            }
        } catch (e) {
            console.error('Error in htmx:afterSettle:', e);
        } finally {
            if (resetTransitionTimer) clearTimeout(resetTransitionTimer);
            resetTransitionTimer = setTimeout(function() {
                document.documentElement.removeAttribute('data-bs-transition');
            }, 1000);
            
            lastClickedLink = null;
            window.__htmxSwapping = false;
        }
    });
})();
