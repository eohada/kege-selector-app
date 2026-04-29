(function() {
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

    configureHtmxWhenReady(20);

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function() {
            configureHtmxWhenReady(20);
            protectLocalHtmxControls();
            syncActiveNav();
        });
    } else {
        protectLocalHtmxControls();
        syncActiveNav();
    }

    document.body.addEventListener('htmx:afterSettle', function(evt) {
        protectLocalHtmxControls();
        syncActiveNav();
        if (isMainSwap(evt)) closeMobileMenus();
    });
})();
