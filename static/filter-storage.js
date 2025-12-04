// Утилита для сохранения и восстановления состояния фильтров
class FilterStorage {
    constructor(storageKey = 'dashboard_filters') {
        this.storageKey = storageKey;
    }

    // Сохранить состояние фильтров
    save(filters) {
        try {
            const data = {
                ...filters,
                timestamp: Date.now()
            };
            localStorage.setItem(this.storageKey, JSON.stringify(data));
        } catch (e) {
            console.warn('Не удалось сохранить фильтры:', e);
        }
    }

    // Загрузить состояние фильтров
    load() {
        try {
            const data = localStorage.getItem(this.storageKey);
            if (!data) return null;
            
            const parsed = JSON.parse(data);
            // Проверяем, не устарели ли данные (старше 7 дней)
            const maxAge = 7 * 24 * 60 * 60 * 1000; // 7 дней
            if (parsed.timestamp && Date.now() - parsed.timestamp > maxAge) {
                this.clear();
                return null;
            }
            
            // Удаляем timestamp перед возвратом
            delete parsed.timestamp;
            return parsed;
        } catch (e) {
            console.warn('Не удалось загрузить фильтры:', e);
            return null;
        }
    }

    // Очистить сохраненные фильтры
    clear() {
        try {
            localStorage.removeItem(this.storageKey);
        } catch (e) {
            console.warn('Не удалось очистить фильтры:', e);
        }
    }

    // Восстановить фильтры в форму
    restoreForm(formSelector) {
        const saved = this.load();
        if (!saved) return;

        const form = document.querySelector(formSelector);
        if (!form) return;

        // Восстанавливаем значения полей
        Object.keys(saved).forEach(key => {
            const field = form.querySelector(`[name="${key}"]`);
            if (field) {
                if (field.type === 'checkbox') {
                    field.checked = saved[key] === 'true' || saved[key] === true;
                } else if (field.tagName === 'SELECT') {
                    field.value = saved[key];
                } else {
                    field.value = saved[key];
                }
            }
        });
    }

    // Сохранить текущее состояние формы
    saveForm(formSelector) {
        const form = document.querySelector(formSelector);
        if (!form) return;

        const formData = new FormData(form);
        const filters = {};
        
        for (const [key, value] of formData.entries()) {
            filters[key] = value;
        }

        // Также сохраняем значения из URL параметров, если форма не отправлена
        const urlParams = new URLSearchParams(window.location.search);
        urlParams.forEach((value, key) => {
            if (!filters[key]) {
                filters[key] = value;
            }
        });

        this.save(filters);
    }
}

// Инициализация для dashboard
document.addEventListener('DOMContentLoaded', () => {
    const filterStorage = new FilterStorage('dashboard_filters');
    const form = document.querySelector('.filters-panel form');
    
    if (form) {
        // Восстанавливаем фильтры при загрузке страницы
        filterStorage.restoreForm('.filters-panel form');
        
        // Сохраняем фильтры при изменении
        form.addEventListener('change', () => {
            filterStorage.saveForm('.filters-panel form');
        });
        
        // Сохраняем фильтры при отправке формы
        form.addEventListener('submit', () => {
            filterStorage.saveForm('.filters-panel form');
        });
        
        // Сохраняем фильтры при вводе в поле поиска (с задержкой)
        const searchInput = form.querySelector('input[name="search"]');
        if (searchInput) {
            let searchTimeout;
            searchInput.addEventListener('input', () => {
                clearTimeout(searchTimeout);
                searchTimeout = setTimeout(() => {
                    filterStorage.saveForm('.filters-panel form');
                }, 500);
            });
        }
    }
    
    // Очистка фильтров при нажатии на "Сбросить"
    const resetBtn = document.querySelector('a[href*="dashboard"][href*="show_archive"]');
    if (resetBtn && resetBtn.textContent.includes('Сбросить')) {
        resetBtn.addEventListener('click', () => {
            filterStorage.clear();
        });
    }
});


