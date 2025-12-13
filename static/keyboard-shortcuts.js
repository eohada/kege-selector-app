// Клавиатурные сокращения для частых действий

class KeyboardShortcuts {
    constructor() {
        this.shortcuts = new Map();
        this.init();
    }
    
    init() {
        document.addEventListener('keydown', (e) => {
            this.handleKeydown(e);
        });
    }
    
    register(keys, callback, description = '') {
        // keys: 'ctrl+s', 'esc', 'ctrl+shift+n'
        const key = this.normalizeKey(keys);
        this.shortcuts.set(key, {callback, description, keys});
    }
    
    normalizeKey(keys) {
        return keys.toLowerCase()
            .replace(/\s+/g, '')
            .split('+')
            .sort()
            .join('+');
    }
    
    handleKeydown(e) {
        const modifiers = [];
        if (e.ctrlKey || e.metaKey) modifiers.push('ctrl');
        if (e.shiftKey) modifiers.push('shift');
        if (e.altKey) modifiers.push('alt');
        
        const key = e.key.toLowerCase();
        const keyCombo = modifiers.length > 0 
            ? [...modifiers, key].sort().join('+')
            : key;
        
        const shortcut = this.shortcuts.get(keyCombo);
        if (shortcut) {
            // Проверяем, что фокус не в поле ввода
            const activeElement = document.activeElement;
            const isInputFocused = activeElement && (
                activeElement.tagName === 'INPUT' ||
                activeElement.tagName === 'TEXTAREA' ||
                activeElement.isContentEditable
            );
            
            // Для некоторых комбинаций разрешаем даже в полях ввода
            const allowedInInput = ['escape', 'ctrl+s', 'ctrl+enter'];
            if (isInputFocused && !allowedInInput.includes(keyCombo)) {
                return;
            }
            
            e.preventDefault();
            shortcut.callback(e);
        }
    }
}

// Глобальный экземпляр
const keyboard = new KeyboardShortcuts();

// Регистрируем стандартные сокращения
document.addEventListener('DOMContentLoaded', () => {
    // Ctrl+S - сохранение формы
    keyboard.register('ctrl+s', (e) => {
        const form = document.querySelector('form:not([data-no-save])');
        if (form) {
            const submitBtn = form.querySelector('button[type="submit"], input[type="submit"]');
            if (submitBtn && !submitBtn.disabled) {
                submitBtn.click();
            }
        }
    }, 'Сохранить форму');
    
    // Escape - закрыть модальное окно
    keyboard.register('escape', () => {
        const modal = document.querySelector('.modal.active, .confirm-modal.active');
        if (modal) {
            const closeBtn = modal.querySelector('.modal-close, .confirm-cancel-btn');
            if (closeBtn) {
                closeBtn.click();
            } else {
                modal.classList.remove('active');
            }
        }
    }, 'Закрыть модальное окно');
    
    // Ctrl+N - создать новый элемент (ученик, урок)
    keyboard.register('ctrl+n', () => {
        const createBtn = document.querySelector('a[href*="/new"], a[href*="/create"], button[data-action="create"]');
        if (createBtn) {
            createBtn.click();
        }
    }, 'Создать новый элемент');
    
    // Ctrl+F - фокус на поиск
    keyboard.register('ctrl+f', () => {
        const searchInput = document.querySelector('input[type="search"], input[name="search"], input[placeholder*="Поиск" i]');
        if (searchInput) {
            searchInput.focus();
            searchInput.select();
        }
    }, 'Фокус на поиск');
    
    // Ctrl+Enter - отправить форму (если в textarea)
    keyboard.register('ctrl+enter', (e) => {
        const activeElement = document.activeElement;
        if (activeElement && activeElement.tagName === 'TEXTAREA') {
            const form = activeElement.closest('form');
            if (form) {
                const submitBtn = form.querySelector('button[type="submit"]');
                if (submitBtn && !submitBtn.disabled) {
                    submitBtn.click();
                }
            }
        }
    }, 'Отправить форму');
});












