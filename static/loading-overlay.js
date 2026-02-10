(function() {
    'use strict';
    var OVERLAY_DELAY_MS = 300;
    var activeFetches = 0;
    var overlayTimer = null;
    var overlayEl = null;

    function getOverlay() {
        if (overlayEl) return overlayEl;
        overlayEl = document.createElement('div');
        overlayEl.id = 'global-loading-overlay';
        overlayEl.className = 'global-loading-overlay';
        overlayEl.setAttribute('aria-hidden', 'true');
        overlayEl.setAttribute('aria-live', 'polite');
        var spinner = document.createElement('div');
        spinner.className = 'global-loading-spinner';
        var text = document.createElement('span');
        text.className = 'global-loading-text';
        text.textContent = 'Загрузка…';
        overlayEl.appendChild(spinner);
        overlayEl.appendChild(text);
        document.body.appendChild(overlayEl);
        return overlayEl;
    }

    function showOverlay() {
        var el = getOverlay();
        el.classList.add('is-active');
        el.setAttribute('aria-hidden', 'false');
    }

    function hideOverlay() {
        if (activeFetches > 0) return;
        if (overlayEl) {
            overlayEl.classList.remove('is-active');
            overlayEl.setAttribute('aria-hidden', 'true');
        }
        if (overlayTimer) {
            clearTimeout(overlayTimer);
            overlayTimer = null;
        }
    }

    function onFetchStart() {
        activeFetches++;
        if (overlayTimer) return;
        overlayTimer = setTimeout(function() {
            overlayTimer = null;
            showOverlay();
        }, OVERLAY_DELAY_MS);
    }

    function onFetchEnd() {
        activeFetches = Math.max(0, activeFetches - 1);
        if (activeFetches === 0) {
            hideOverlay();
        }
    }

    var originalFetch = window.fetch;
    if (typeof originalFetch !== 'function') return;
    window.fetch = function() {
        var args = arguments;
        onFetchStart();
        var p = originalFetch.apply(this, args);
        if (p && typeof p.then === 'function') {
            p.then(function(res) {
                onFetchEnd();
                return res;
            }, function(err) {
                onFetchEnd();
                throw err;
            });
        } else {
            onFetchEnd();
        }
        return p;
    };

    document.addEventListener('DOMContentLoaded', function() {
        document.querySelectorAll('[data-prevent-double-submit="true"]').forEach(function(btn) {
            btn.addEventListener('click', function() {
                if (btn.disabled) return;
                var self = btn;
                self.disabled = true;
                setTimeout(function() {
                    self.disabled = false;
                }, 2500);
            });
        });
    });
})();
