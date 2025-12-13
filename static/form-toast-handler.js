/**
 * Универсальный обработчик форм для немедленного показа toast-уведомлений
 * Перехватывает отправку форм и отправляет их через AJAX, показывая toast сразу
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
                        // В этом случае flash-сообщение будет показано на следующей странице
                        // Но мы можем попробовать извлечь сообщение из ответа или просто перезагрузить
                        const text = await response.text();
                        
                        // Если ответ содержит redirect, следуем ему
                        if (response.redirected || response.url !== window.location.href) {
                            // Показываем общее сообщение об успехе
                            toastManager.success('Операция выполнена успешно!');
                            
                            // Следуем redirect
                            setTimeout(() => {
                                window.location.href = response.url;
                            }, 500);
                        } else {
                            // Если нет redirect, перезагружаем страницу
                            toastManager.info('Сохранение...');
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
    
    // Инициализируем при загрузке DOM
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initFormHandlers);
    } else {
        initFormHandlers();
    }
})();

