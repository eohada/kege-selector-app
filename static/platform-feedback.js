(function () {
    'use strict';

    if (window.BooNotify) return;

    const TYPE_META = {
        success: { icon: '✓', label: 'Готово' },
        error: { icon: '!', label: 'Ошибка' },
        danger: { icon: '!', label: 'Ошибка' },
        warning: { icon: '!', label: 'Внимание' },
        info: { icon: 'i', label: 'Информация' }
    };

    function normalizeType(type) {
        return TYPE_META[type] ? type : 'info';
    }

    function escapeHtml(value) {
        const node = document.createElement('div');
        node.textContent = String(value == null ? '' : value);
        return node.innerHTML;
    }

    function getToastContainer() {
        let container = document.getElementById('boo-notify-stack');
        if (container) return container;
        container = document.createElement('div');
        container.id = 'boo-notify-stack';
        container.className = 'boo-notify-stack';
        container.setAttribute('aria-live', 'polite');
        container.setAttribute('aria-atomic', 'false');
        document.body.appendChild(container);
        return container;
    }

    function notify(message, type, options) {
        const normalizedType = normalizeType(type);
        const meta = TYPE_META[normalizedType];
        const settings = Object.assign({ duration: 4500, title: meta.label }, options || {});
        const item = document.createElement('article');
        item.className = 'boo-notify boo-notify--' + normalizedType;
        item.setAttribute('role', normalizedType === 'error' || normalizedType === 'danger' ? 'alert' : 'status');
        item.innerHTML = '' +
            '<span class="boo-notify__icon" aria-hidden="true">' + meta.icon + '</span>' +
            '<div class="boo-notify__body">' +
                '<strong>' + escapeHtml(settings.title) + '</strong>' +
                '<p>' + escapeHtml(message) + '</p>' +
            '</div>' +
            '<button type="button" class="boo-notify__close" aria-label="Закрыть уведомление">×</button>';

        let removed = false;
        const remove = function () {
            if (removed) return;
            removed = true;
            item.classList.remove('is-visible');
            window.setTimeout(function () { item.remove(); }, 180);
        };
        item.querySelector('.boo-notify__close').addEventListener('click', remove);
        getToastContainer().appendChild(item);
        window.requestAnimationFrame(function () { item.classList.add('is-visible'); });
        if (settings.duration > 0) window.setTimeout(remove, settings.duration);
        return item;
    }

    function confirm(options) {
        const settings = Object.assign({
            title: 'Подтвердите действие',
            message: 'Вы уверены, что хотите продолжить?',
            confirmText: 'Продолжить',
            cancelText: 'Отмена',
            variant: 'default'
        }, options || {});

        return new Promise(function (resolve) {
            const overlay = document.createElement('div');
            overlay.className = 'boo-confirm-overlay';
            overlay.innerHTML = '' +
                '<section class="boo-confirm" role="dialog" aria-modal="true" aria-labelledby="boo-confirm-title">' +
                    '<div class="boo-confirm__mark boo-confirm__mark--' + (settings.variant === 'danger' ? 'danger' : 'default') + '" aria-hidden="true">' + (settings.variant === 'danger' ? '!' : '?') + '</div>' +
                    '<div class="boo-confirm__copy">' +
                        '<h2 id="boo-confirm-title">' + escapeHtml(settings.title) + '</h2>' +
                        '<p>' + escapeHtml(settings.message) + '</p>' +
                    '</div>' +
                    '<div class="boo-confirm__actions">' +
                        '<button type="button" class="boo-confirm__button boo-confirm__button--secondary" data-answer="cancel">' + escapeHtml(settings.cancelText) + '</button>' +
                        '<button type="button" class="boo-confirm__button boo-confirm__button--' + (settings.variant === 'danger' ? 'danger' : 'primary') + '" data-answer="confirm">' + escapeHtml(settings.confirmText) + '</button>' +
                    '</div>' +
                '</section>';
            document.body.appendChild(overlay);
            const dialog = overlay.querySelector('.boo-confirm');
            const settle = function (answer) {
                overlay.classList.remove('is-visible');
                window.setTimeout(function () { overlay.remove(); }, 160);
                resolve(answer);
            };
            overlay.addEventListener('click', function (event) {
                if (event.target === overlay) settle(false);
            });
            overlay.querySelector('[data-answer="cancel"]').addEventListener('click', function () { settle(false); });
            overlay.querySelector('[data-answer="confirm"]').addEventListener('click', function () { settle(true); });
            const onKeydown = function (event) {
                if (event.key === 'Escape') settle(false);
                if (event.key === 'Tab') {
                    const buttons = dialog.querySelectorAll('button');
                    if (buttons.length && document.activeElement === buttons[buttons.length - 1] && !event.shiftKey) {
                        event.preventDefault();
                        buttons[0].focus();
                    }
                }
            };
            overlay.addEventListener('keydown', onKeydown);
            window.requestAnimationFrame(function () {
                overlay.classList.add('is-visible');
                overlay.querySelector('[data-answer="confirm"]').focus();
            });
        });
    }

    function prompt(options) {
        const settings = Object.assign({
            title: 'Введите значение', message: '', placeholder: '', value: '', confirmText: 'Сохранить', cancelText: 'Отмена'
        }, options || {});
        return new Promise(function (resolve) {
            const overlay = document.createElement('div');
            overlay.className = 'boo-confirm-overlay';
            overlay.innerHTML = '' +
                '<section class="boo-confirm" role="dialog" aria-modal="true" aria-labelledby="boo-prompt-title">' +
                    '<div class="boo-confirm__mark" aria-hidden="true">+</div>' +
                    '<div class="boo-confirm__copy"><h2 id="boo-prompt-title">' + escapeHtml(settings.title) + '</h2><p>' + escapeHtml(settings.message) + '</p></div>' +
                    '<input class="boo-prompt__input" type="text" maxlength="255" value="' + escapeHtml(settings.value) + '" placeholder="' + escapeHtml(settings.placeholder) + '">' +
                    '<div class="boo-confirm__actions"><button type="button" class="boo-confirm__button boo-confirm__button--secondary" data-answer="cancel">' + escapeHtml(settings.cancelText) + '</button><button type="button" class="boo-confirm__button boo-confirm__button--primary" data-answer="confirm">' + escapeHtml(settings.confirmText) + '</button></div>' +
                '</section>';
            document.body.appendChild(overlay);
            const input = overlay.querySelector('.boo-prompt__input');
            const settle = function (value) {
                overlay.classList.remove('is-visible');
                window.setTimeout(function () { overlay.remove(); }, 160);
                resolve(value);
            };
            overlay.addEventListener('click', function (event) { if (event.target === overlay) settle(null); });
            overlay.querySelector('[data-answer="cancel"]').addEventListener('click', function () { settle(null); });
            overlay.querySelector('[data-answer="confirm"]').addEventListener('click', function () { settle(input.value.trim() || null); });
            input.addEventListener('keydown', function (event) {
                if (event.key === 'Enter') settle(input.value.trim() || null);
                if (event.key === 'Escape') settle(null);
            });
            window.requestAnimationFrame(function () { overlay.classList.add('is-visible'); input.focus(); input.select(); });
        });
    }

    const api = {
        notify: notify,
        confirm: confirm,
        prompt: prompt,
        success: function (message, options) { return notify(message, 'success', options); },
        error: function (message, options) { return notify(message, 'error', options); },
        warning: function (message, options) { return notify(message, 'warning', options); },
        info: function (message, options) { return notify(message, 'info', options); }
    };
    window.BooNotify = api;
    window.toast = api;
    window.showToast = function (message, typeOrMessage) {
        if (TYPE_META[typeOrMessage]) return notify(message, typeOrMessage);
        if (typeof typeOrMessage === 'string' && typeOrMessage) return notify(typeOrMessage, 'info', { title: message });
        return notify(message, 'success');
    };
    document.addEventListener('boostudy:notify', function (event) {
        const detail = event.detail || {};
        notify(detail.message || '', detail.type || 'info', { title: detail.title || TYPE_META[normalizeType(detail.type)].label });
    });
    document.addEventListener('submit', function (event) {
        const form = event.target && event.target.closest ? event.target.closest('form[data-confirm-message]') : null;
        if (!form || form.dataset.confirmed === 'true') {
            if (form) delete form.dataset.confirmed;
            return;
        }
        event.preventDefault();
        event.stopImmediatePropagation();
        confirm({
            title: form.dataset.confirmTitle || 'Подтвердите действие',
            message: form.dataset.confirmMessage,
            confirmText: form.dataset.confirmText || 'Продолжить',
            cancelText: form.dataset.cancelText || 'Отмена',
            variant: form.dataset.confirmVariant || 'default'
        }).then(function (approved) {
            if (!approved) return;
            form.dataset.confirmed = 'true';
            if (typeof form.requestSubmit === 'function') form.requestSubmit(event.submitter || undefined);
            else form.submit();
        });
    }, true);
}());
