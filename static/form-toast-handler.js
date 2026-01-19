/**
 * Универсальный обработчик форм и POST-запросов для немедленного показа toast-уведомлений
 * Перехватывает отправку форм и POST-запросы, отправляет их через AJAX, показывая toast сразу
 */

(function() {
    'use strict';
    
    // Проверяем, что toast доступен
    if (typeof toast === 'undefined' && typeof window.toast === 'undefined') {
        console.warn('Toast manager not found. Form toast handler will not work.');
        return;
    }
    
    const toastManager = typeof toast !== 'undefined' ? toast : window.toast;
    
    /**
     * Обрабатывает POST-запросы через AJAX для немедленного показа toast
     */
    function handlePostRequest(url, formData, options = {}) {
        return new Promise(async (resolve, reject) => {
            try {
                const csrfToken = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') ||
                                  formData.get('csrf_token');
                
                const headers = {
                    'X-Requested-With': 'XMLHttpRequest'
                };
                
                if (csrfToken) {
                    headers['X-CSRFToken'] = csrfToken;
                }
                
                const response = await fetch(url, {
                    method: 'POST',
                    body: formData,
                    headers: headers
                });
                
                const contentType = response.headers.get('content-type');
                
                if (contentType && contentType.includes('application/json')) {
                    const result = await response.json();
                    resolve(result);
                } else {
                    // HTML ответ - значит это обычный endpoint с redirect
                    // Показываем общее сообщение об успехе
                    if (options.showSuccessMessage !== false) {
                        toastManager.success(options.successMessage || 'Операция выполнена успешно!');
                    }
                    
                    // Следуем redirect
                    if (response.redirected || response.url !== window.location.href) {
                        setTimeout(() => {
                            window.location.href = response.url;
                        }, options.delay || 500);
                    } else {
                        setTimeout(() => {
                            window.location.reload();
                        }, options.delay || 500);
                    }
                    resolve({ success: true, redirected: true });
                }
            } catch (error) {
                reject(error);
            }
        });
    }
    
    /**
     * Инициализирует обработку форм на странице
     */
    function initFormHandlers() {
        // Находим все формы, которые должны обрабатываться через AJAX
        const forms = document.querySelectorAll('form[method="POST"]:not([data-no-ajax])');
        
        forms.forEach(form => {
            // Пропускаем формы, которые уже обрабатываются специальным кодом
            if (form.id === 'create-student-form' || 
                form.classList.contains('edit-student-form') ||
                form.id === 'createLessonForm' ||
                form.id === 'templateForm') {
                return;
            }
            
            // Пропускаем формы завершения урока
            if (form.action && form.action.includes('lesson_complete')) {
                return;
            }
            
            // Пропускаем формы редактирования пользователей (админка) - они должны отправляться обычным способом
            if (form.action && (form.action.includes('/admin/users/') || form.action.includes('/admin/user'))) {
                return;
            }
            
            // Пропускаем формы с атрибутом data-no-ajax
            if (form.hasAttribute('data-no-ajax')) {
                return;
            }
            
            // Проверяем, что форма содержит CSRF токен (значит это форма приложения)
            const csrfToken = form.querySelector('input[name="csrf_token"]');
            if (!csrfToken) {
                return;
            }
            
            form.addEventListener('submit', async function(e) {
                // Проверяем, не обрабатывается ли форма уже другим кодом
                if (form.dataset.ajaxHandled === 'true') {
                    return;
                }
                
                e.preventDefault();
                form.dataset.ajaxHandled = 'true';
                
                const formData = new FormData(form);
                const submitButton = form.querySelector('button[type="submit"], input[type="submit"]');
                const originalText = submitButton ? (submitButton.textContent || submitButton.value) : '';
                
                // Показываем индикатор загрузки
                let loaderId = null;
                if (typeof loading !== 'undefined' && loading) {
                    loaderId = loading.show(form, 'Сохранение...');
                } else if (submitButton) {
                    submitButton.disabled = true;
                    if (submitButton.tagName === 'BUTTON') {
                        submitButton.textContent = 'Сохранение...';
                    }
                }
                
                try {
                    // Получаем CSRF токен
                    const csrfTokenValue = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') ||
                                          csrfToken.value;
                    
                    const headers = {
                        'X-Requested-With': 'XMLHttpRequest'
                    };
                    
                    if (csrfTokenValue) {
                        headers['X-CSRFToken'] = csrfTokenValue;
                    }
                    
                    // Отправляем форму через AJAX
                    const response = await fetch(form.action || window.location.href, {
                        method: 'POST',
                        body: formData,
                        headers: headers
                    });
                    
                    // Проверяем тип ответа
                    const contentType = response.headers.get('content-type');
                    
                    if (contentType && contentType.includes('application/json')) {
                        // JSON ответ - значит это API endpoint
                        const result = await response.json();
                        
                        if (result.success) {
                            toastManager.success(result.message || 'Операция выполнена успешно!');
                            
                            // Если есть redirect URL в ответе, используем его
                            if (result.redirect) {
                                setTimeout(() => {
                                    window.location.href = result.redirect;
                                }, 500);
                            } else if (response.status === 201 || response.status === 200) {
                                // Перезагружаем страницу через небольшую задержку
                                setTimeout(() => {
                                    window.location.reload();
                                }, 500);
                            }
                        } else {
                            toastManager.error(result.error || 'Ошибка при выполнении операции');
                            
                            // Восстанавливаем кнопку
                            if (loaderId && typeof loading !== 'undefined' && loading) {
                                loading.hide(loaderId);
                            } else if (submitButton) {
                                submitButton.disabled = false;
                                if (submitButton.tagName === 'BUTTON') {
                                    submitButton.textContent = originalText;
                                }
                            }
                            form.dataset.ajaxHandled = 'false';
                        }
                    } else {
                        // HTML ответ - значит это обычный endpoint с redirect
                        // Показываем общее сообщение об успехе сразу
                        const successMessage = form.dataset.successMessage || 
                                               submitButton?.dataset.successMessage || 
                                               'Операция выполнена успешно!';
                        toastManager.success(successMessage);
                        
                        // Если ответ содержит redirect, следуем ему
                        if (response.redirected || response.status === 302 || response.status === 301) {
                            // Получаем URL из заголовка Location или из response.url
                            const redirectUrl = response.headers.get('Location') || response.url;
                            if (redirectUrl && redirectUrl !== window.location.href) {
                                setTimeout(() => {
                                    window.location.href = redirectUrl;
                                }, 500);
                            } else {
                                setTimeout(() => {
                                    window.location.reload();
                                }, 500);
                            }
                        } else {
                            // Если нет redirect, перезагружаем страницу
                            setTimeout(() => {
                                window.location.reload();
                            }, 500);
                        }
                    }
                } catch (error) {
                    console.error('Ошибка при отправке формы:', error);
                    
                    toastManager.error('Ошибка при сохранении. Попробуйте еще раз.');
                    
                    // Восстанавливаем кнопку
                    if (loaderId && typeof loading !== 'undefined' && loading) {
                        loading.hide(loaderId);
                    } else if (submitButton) {
                        submitButton.disabled = false;
                        if (submitButton.tagName === 'BUTTON') {
                            submitButton.textContent = originalText;
                        }
                    }
                    form.dataset.ajaxHandled = 'false';
                }
            });
        });
    }
    
    /**
     * Инициализирует обработку POST-кнопок и ссылок
     */
    function initPostButtons() {
        // Находим все формы и кнопки, которые отправляют POST запросы
        const postButtons = document.querySelectorAll('button[type="submit"], input[type="submit"], form[method="POST"] button, a[data-method="POST"]');
        const postForms = document.querySelectorAll('form[method="POST"]');
        
        // Обрабатываем кнопки внутри форм
        postForms.forEach(form => {
            const buttons = form.querySelectorAll('button[type="submit"], input[type="submit"]');
            buttons.forEach(button => {
                if (button.dataset.ajaxHandled === 'true') return;
                
                button.addEventListener('click', async function(e) {
                    // Проверяем, не обрабатывается ли форма уже
                    if (form.dataset.ajaxHandled === 'true') return;

                    // Пропускаем формы, которые явно должны отправляться нативно (важно для formaction)
                    if (form.hasAttribute('data-no-ajax')) return;
                    
                    // Пропускаем специальные формы
                    if (form.id === 'create-student-form' || 
                        form.classList.contains('edit-student-form') ||
                        form.id === 'createLessonForm' ||
                        form.id === 'templateForm' ||
                        (form.action && form.action.includes('lesson_complete'))) {
                        return;
                    }
                    
                    // Пропускаем, если это не основная кнопка отправки
                    if (e.target !== button) return;
                    
                    e.preventDefault();
                    e.stopPropagation();
                    
                    button.dataset.ajaxHandled = 'true';
                    form.dataset.ajaxHandled = 'true';
                    
                    const formData = new FormData(form);
                    const originalText = button.textContent || button.value;
                    
                    // Показываем индикатор загрузки
                    let loaderId = null;
                    if (typeof loading !== 'undefined' && loading) {
                        loaderId = loading.show(form, 'Выполнение...');
                    } else {
                        button.disabled = true;
                        if (button.tagName === 'BUTTON') {
                            button.textContent = 'Выполнение...';
                        }
                    }
                    
                    try {
                        // Уважаем formaction у конкретной кнопки (иначе "Сдать работу" уедет в form.action)
                        const targetUrl = button.getAttribute('formaction') || form.action || window.location.href;

                        const result = await handlePostRequest(targetUrl, formData, {
                            successMessage: button.dataset.successMessage || 'Операция выполнена успешно!',
                            delay: 500
                        });
                        
                        if (result && result.success && !result.redirected) {
                            toastManager.success(result.message || 'Операция выполнена успешно!');
                        }
                    } catch (error) {
                        console.error('Ошибка при отправке формы:', error);
                        toastManager.error('Ошибка при выполнении операции. Попробуйте еще раз.');
                        
                        if (loaderId && typeof loading !== 'undefined' && loading) {
                            loading.hide(loaderId);
                        } else {
                            button.disabled = false;
                            if (button.tagName === 'BUTTON') {
                                button.textContent = originalText;
                            }
                        }
                        button.dataset.ajaxHandled = 'false';
                        form.dataset.ajaxHandled = 'false';
                    }
                });
            });
        });
        
        // Обрабатываем ссылки с data-method="POST"
        document.querySelectorAll('a[data-method="POST"]').forEach(link => {
            if (link.dataset.ajaxHandled === 'true') return;
            
            link.addEventListener('click', async function(e) {
                e.preventDefault();
                link.dataset.ajaxHandled = 'true';
                
                const formData = new FormData();
                const csrfToken = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') ||
                                  document.querySelector('input[name="csrf_token"]')?.value;
                if (csrfToken) {
                    formData.append('csrf_token', csrfToken);
                }
                
                try {
                    await handlePostRequest(link.href, formData, {
                        successMessage: link.dataset.successMessage || 'Операция выполнена успешно!',
                        delay: 500
                    });
                } catch (error) {
                    console.error('Ошибка при выполнении POST запроса:', error);
                    toastManager.error('Ошибка при выполнении операции. Попробуйте еще раз.');
                    link.dataset.ajaxHandled = 'false';
                }
            });
        });
    }
    
    // Инициализируем при загрузке DOM
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => {
            initFormHandlers();
            initPostButtons();
        });
    } else {
        initFormHandlers();
        initPostButtons();
    }
})();

