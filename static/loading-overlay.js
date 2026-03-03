(function() {
    'use strict';
    var OVERLAY_DELAY_MS = 300;
    var activeFetches = 0;
    var overlayTimer = null;
    var overlayEl = null;
    var SKIP_HEADER = 'x-no-loading-overlay';

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
        var opts = (args && args.length > 1) ? args[1] : null;
        var headers = opts && opts.headers ? opts.headers : null;
        var skip = false;
        try {
            if (headers) {
                if (typeof Headers !== 'undefined' && headers instanceof Headers) {
                    var hv = headers.get(SKIP_HEADER) || headers.get('X-No-Loading-Overlay');
                    if (hv && String(hv).toLowerCase() !== 'false' && String(hv) !== '0') skip = true;
                } else if (typeof headers === 'object') {
                    var hv2 = headers[SKIP_HEADER] || headers['X-No-Loading-Overlay'] || headers['x-no-loading-overlay'];
                    if (hv2 && String(hv2).toLowerCase() !== 'false' && String(hv2) !== '0') skip = true;
                }
            }
        } catch (e) {
            skip = false;
        }

        if (!skip) onFetchStart();
        var p = originalFetch.apply(this, args);
        if (p && typeof p.then === 'function') {
            p.then(function(res) {
                if (!skip) onFetchEnd();
                return res;
            }, function(err) {
                if (!skip) onFetchEnd();
                throw err;
            });
        } else {
            if (!skip) onFetchEnd();
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
