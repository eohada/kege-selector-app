
(function() {
    'use strict';  

    function isUserAuthenticated() {
        // Проверяем наличие аватара пользователя в DOM - он отображается только для авторизованных
        return !!document.querySelector('.user-profile-avatar');
    }

    function getTesterUUID() {
        // Для авторизованных пользователей не нужен UUID тестировщика
        if (isUserAuthenticated()) {
            return null;
        }
        let testerUUID = localStorage.getItem('tester_uuid');
        if (!testerUUID) {
            // Генерируем UUID один раз и сохраняем навсегда
            testerUUID = 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
                const r = Math.random() * 16 | 0;
                const v = c == 'x' ? r : (r & 0x3 | 0x8);
                return v.toString(16);
            });
            localStorage.setItem('tester_uuid', testerUUID);
        }
        return testerUUID;
    }

    function getTesterName() {
        // Для авторизованных пользователей не запрашиваем имя тестировщика
        if (isUserAuthenticated()) {
            return null; // Возвращаем null, чтобы не отправлять заголовки тестировщика
        }
        
        let testerName = localStorage.getItem('tester_name');  
        if (!testerName) {  
            testerName = prompt('Введи своё имя для тестирования:');  
            if (testerName && testerName.trim()) {  
                testerName = testerName.trim();  
                localStorage.setItem('tester_name', testerName);  
            } else {  
                testerName = 'Anonymous';  
            }
        }
        return testerName;  
    }

    function sendAuditEvent(action, entity, entityId, status, metadata, durationMs) {
        // Для авторизованных пользователей не отправляем заголовки тестировщика
        // Логирование будет происходить через Flask-Login на сервере
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

        // Кодируем имя тестировщика в base64, если оно содержит не-ASCII символы
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

            sendAuditEvent(  
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

        if (typeof url === 'string' && url.includes('/api/audit-log')) {  
            return originalFetch.apply(this, args);  
        }
        
        // Добавляем заголовки тестировщика во все fetch запросы
        // Преобразуем Headers объект в обычный объект, если нужно
        let headersObj = {};
        if (options.headers) {
            if (options.headers instanceof Headers) {
                // Если это Headers объект, преобразуем в обычный объект
                options.headers.forEach((value, key) => {
                    headersObj[key] = value;
                });
            } else if (typeof options.headers === 'object') {
                // Если это обычный объект, копируем его
                headersObj = { ...options.headers };
            }
        }
        
        // Для авторизованных пользователей не отправляем заголовки тестировщика
        if (!isUserAuthenticated()) {
            const testerName = getTesterName();
            const testerUUID = getTesterUUID();
            // Кодируем имя тестировщика в base64, если оно содержит не-ASCII символы
            // HTTP заголовки должны содержать только ISO-8859-1 символы
            if (testerName && testerName !== 'Anonymous') {
                // Проверяем, содержит ли имя не-ASCII символы
                const hasNonASCII = /[^\x00-\x7F]/.test(testerName);
                if (hasNonASCII) {
                    // Кодируем в base64 для безопасной передачи в заголовке
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
        
        // Устанавливаем обновленные заголовки обратно
        options.headers = headersObj;
        args[1] = options;
        
        return originalFetch.apply(this, args).then(response => {
            const durationMs = Date.now() - startTime;
            const status = response.ok ? 'success' : 'error';

            sendAuditEvent(  
                'ajax_request',  
                'API',  
                null,  
                status,  
                {  
                    url: typeof url === 'string' ? url : url.toString(),  
                    method: method,  
                    status_code: response.status  
                },
                durationMs  
            );
            
            return response;  
        }).catch(error => {  
            const durationMs = Date.now() - startTime;  

            sendAuditEvent(  
                'ajax_error',  
                'API',  
                null,  
                'error',  
                {  
                    url: typeof url === 'string' ? url : url.toString(),  
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
    
    console.log('Audit tracker initialized');  
})();
