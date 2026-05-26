
(function() {
    'use strict';  

    function isUserAuthenticated() {

        return !!document.querySelector('.user-profile-avatar');
    }

    function getTesterUUID() {

        if (isUserAuthenticated()) {
            return null;
        }
        let testerUUID = null;
        try {
            testerUUID = localStorage.getItem('tester_uuid');
        } catch (e) {
            // ignore
        }
        if (!testerUUID) {

            testerUUID = 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
                const r = Math.random() * 16 | 0;
                const v = c == 'x' ? r : (r & 0x3 | 0x8);
                return v.toString(16);
            });
            try {
                localStorage.setItem('tester_uuid', testerUUID);
            } catch (e) {
                // ignore
            }
        }
        return testerUUID;
    }

    function getTesterName() {

        if (isUserAuthenticated()) {
            return null;
        }
        
        // Release behavior: no blocking prompts on any page.
        // If a tester name is needed, it can be set manually via localStorage key `tester_name`.
        try {
            const testerName = localStorage.getItem('tester_name');
            if (testerName && String(testerName).trim()) {
                return String(testerName).trim();
            }
        } catch (e) {
            // Storage can be blocked by browser privacy settings; fall back silently.
        }
        return 'Anonymous';
    }

    function sendAuditEvent(action, entity, entityId, status, metadata, durationMs) {

        if (isUserAuthenticated()) {
            const headers = {
                'Content-Type': 'application/json',  
                'X-CSRFToken': getCSRFToken()  
            };
            fetch('/api/audit-log', {  
                method: 'POST',  
                headers: headers,
                body: JSON.stringify({  
                    action: action,  
                    entity: entity,  
                    entity_id: entityId,  
                    status: status,  
                    metadata: metadata || {},  
                    duration_ms: durationMs  
                })
            }).catch(err => {  
                console.error('Error sending audit event:', err);  
            });
            return;
        }
        
        const testerName = getTesterName();
        const testerUUID = getTesterUUID();

        const hasNonASCII = testerName && /[^\x00-\x7F]/.test(testerName);
        const headers = {
            'Content-Type': 'application/json',  
            'X-Tester-UUID': testerUUID,
            'X-CSRFToken': getCSRFToken()  
        };
        if (hasNonASCII && testerName !== 'Anonymous') {
            headers['X-Tester-Name'] = btoa(encodeURIComponent(testerName));
            headers['X-Tester-Name-Encoded'] = 'base64';
        } else if (testerName && testerName !== 'Anonymous') {
            headers['X-Tester-Name'] = testerName;
        }

        fetch('/api/audit-log', {  
            method: 'POST',  
            headers: headers,
            body: JSON.stringify({  
                action: action,  
                entity: entity,  
                entity_id: entityId,  
                status: status,  
                metadata: metadata || {},  
                duration_ms: durationMs  
            })
        }).catch(err => {  
            console.error('Error sending audit event:', err);  
        });
    }

    const AUDIT_THROTTLE_MS = {
        click: 1000,
        ajax_request: 800,
        ajax_error: 30000,
    };

    function shouldSkipFetchAudit(urlStr) {
        if (!urlStr) return true;
        if (urlStr.indexOf('/api/audit-log') !== -1) return true;
        if (urlStr.indexOf('/api/telemetry') !== -1) return true;
        if (urlStr.indexOf('/api/presence') !== -1) return true;
        if (urlStr.indexOf('/static/') !== -1) return true;
        if (urlStr.indexOf('127.0.0.1:7561') !== -1 || urlStr.indexOf('localhost:7561') !== -1) return true;
        return false;
    }
    const lastAuditSentAt = Object.create(null);

    function sendAuditEventThrottled(action, entity, entityId, status, metadata, durationMs) {
        const throttleMs = AUDIT_THROTTLE_MS[action] || 0;
        if (throttleMs > 0) {
            const now = Date.now();
            const lastSent = lastAuditSentAt[action] || 0;
            if (now - lastSent < throttleMs) {
                return;
            }
            lastAuditSentAt[action] = now;
        }
        sendAuditEvent(action, entity, entityId, status, metadata, durationMs);
    }

    const telemetryQueue = [];
    let lastActivityAt = Date.now();

    function enqueueTelemetry(eventType, payload) {
        telemetryQueue.push({
            event_type: eventType,
            payload: payload || {},
            ts: new Date().toISOString()
        });
    }

    function flushTelemetry(useBeacon) {
        if (!telemetryQueue.length) return;
        const batch = telemetryQueue.splice(0, telemetryQueue.length);
        const body = JSON.stringify({ events: batch });
        if (useBeacon && navigator.sendBeacon) {
            try {
                navigator.sendBeacon('/api/telemetry/batch', new Blob([body], { type: 'application/json' }));
                return;
            } catch (e) {}
        }
        fetch('/api/telemetry/batch', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCSRFToken() },
            body: body,
            keepalive: true,
        }).catch(() => {});
    }

    function getCSRFToken() {
        const meta = document.querySelector('meta[name="csrf-token"]');  
        if (meta) {  
            return meta.getAttribute('content');  
        }
        const body = document.body;  
        if (body && body.dataset && body.dataset.csrfToken) {  
            return body.dataset.csrfToken;  
        }
        return '';  
    }

    document.addEventListener('click', function(e) {
        const target = e.target;  

        if (target.closest('form')) {  
            return;  
        }

        let entity = null;  
        let entityId = null;  
        let action = 'click';  
        
        if (target.tagName === 'BUTTON' || target.tagName === 'A') {  
            const buttonText = target.textContent.trim() || target.getAttribute('aria-label') || target.className;  
            const href = target.getAttribute('href');  

            if (target.classList.contains('neo-button')) {  
                if (target.classList.contains('danger')) {  
                    action = 'click_danger';  
                } else if (target.classList.contains('accent')) {  
                    action = 'click_primary';  
                }
            }

            sendAuditEventThrottled(  
                action,  
                'Button',  
                null,  
                'success',  
                {  
                    button_text: buttonText,  
                    href: href,  
                    class_name: target.className  
                }
            );
        }
    }, true);  

    document.addEventListener('submit', function(e) {
        const form = e.target;  
        if (!form || form.tagName !== 'FORM') {  
            return;  
        }
        
        const formId = form.id || form.name || 'unknown';  
        const formAction = form.action || window.location.pathname;  
        const formMethod = form.method || 'POST';  

        const formData = new FormData(form);  
        const fieldNames = Array.from(formData.keys());  

        sendAuditEvent(  
            'form_submit',  
            'Form',  
            null,  
            'success',  
            {  
                form_id: formId,  
                form_action: formAction,  
                form_method: formMethod,  
                field_names: fieldNames  
            }
        );
    });

    const originalFetch = window.fetch;  
    window.fetch = function(...args) {  
        const startTime = Date.now();  
        const url = args[0];  
        const options = args[1] || {};  
        const method = options.method || 'GET';  
        const urlStr = typeof url === 'string' ? url : (url && typeof url.url === 'string' ? url.url : '');
        if (shouldSkipFetchAudit(urlStr)) {
            return originalFetch.apply(this, args);
        }

        let headersObj = {};
        if (options.headers) {
            if (options.headers instanceof Headers) {

                options.headers.forEach((value, key) => {
                    headersObj[key] = value;
                });
            } else if (typeof options.headers === 'object') {

                headersObj = { ...options.headers };
            }
        }

        if (!isUserAuthenticated()) {
            const testerName = getTesterName();
            const testerUUID = getTesterUUID();

            if (testerName && testerName !== 'Anonymous') {

                const hasNonASCII = /[^\x00-\x7F]/.test(testerName);
                if (hasNonASCII) {

                    headersObj['X-Tester-Name'] = btoa(encodeURIComponent(testerName));
                    headersObj['X-Tester-Name-Encoded'] = 'base64';
                } else {
                    headersObj['X-Tester-Name'] = testerName;
                }
            }
            if (testerUUID) {
                headersObj['X-Tester-UUID'] = testerUUID;
            }
        }

        options.headers = headersObj;
        args[1] = options;
        
        return originalFetch.apply(this, args).then(response => {
            try {
                const rid = response && response.headers ? response.headers.get('X-Request-ID') : null;
                if (rid) {
                    window.__last_request_id = rid;
                    try { localStorage.setItem('last_request_id', rid); } catch (e) {}
                }
            } catch (e) {}
            const durationMs = Date.now() - startTime;
            if (!response.ok && response.status < 500) {
                sendAuditEventThrottled(
                    'ajax_request',
                    'API',
                    null,
                    'error',
                    {
                        url: urlStr || String(url),
                        method: method,
                        status_code: response.status
                    },
                    durationMs
                );
            }

            return response;  
        }).catch(error => {  
            const durationMs = Date.now() - startTime;
            const errName = error && error.name ? String(error.name) : '';
            const errMsg = error && error.message ? String(error.message) : '';
            if (errName === 'AbortError' || errMsg.indexOf('aborted') !== -1) {
                throw error;
            }

            sendAuditEventThrottled(
                'ajax_error',
                'API',
                null,
                'error',
                {
                    url: urlStr || String(url),
                    method: method,
                    error: error.message
                },
                durationMs
            );
            
            throw error;  
        });
    };

    document.addEventListener('change', function(e) {
        const target = e.target;  
        if (target.tagName === 'SELECT' && target.name) {  
            sendAuditEvent(  
                'select_change',  
                'FormField',  
                null,  
                'success',  
                {  
                    field_name: target.name,  
                    field_value: target.value  
                }
            );
        }
    });

    ['mousemove', 'keydown', 'click'].forEach((eventName) => {
        document.addEventListener(eventName, function() {
            lastActivityAt = Date.now();
        }, { passive: true });
    });

    document.addEventListener('visibilitychange', function() {
        enqueueTelemetry('visibility', {
            state: document.visibilityState,
            away_from_tab: document.visibilityState === 'hidden'
        });
    });

    window.addEventListener('focus', function() {
        enqueueTelemetry('window_focus', { focused: true });
    });

    window.addEventListener('blur', function() {
        enqueueTelemetry('window_focus', { focused: false });
    });

    setInterval(function() {
        const idleSec = Math.floor((Date.now() - lastActivityAt) / 1000);
        enqueueTelemetry('presence', { idle_sec: idleSec, idle: idleSec >= 120 });
        flushTelemetry(false);
    }, 60000);

    window.addEventListener('beforeunload', function() {
        flushTelemetry(true);
    });

    if (document.readyState === 'loading') {  
        document.addEventListener('DOMContentLoaded', function() {  
            sendAuditEvent(  
                'page_loaded',  
                'Page',  
                null,  
                'success',  
                {  
                    page_url: window.location.pathname,  
                    page_title: document.title  
                }
            );
        });
    } else {  
        sendAuditEvent(  
            'page_loaded',  
            'Page',  
            null,  
            'success',  
            {  
                page_url: window.location.pathname,  
                page_title: document.title  
            }
        );
    }
    
})();