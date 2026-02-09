
class FilterStorage {
    constructor(storageKey = 'dashboard_filters') {
        this.storageKey = storageKey;
    }

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

    load() {
        try {
            const data = localStorage.getItem(this.storageKey);
            if (!data) return null;
            
            const parsed = JSON.parse(data);

            const maxAge = 7 * 24 * 60 * 60 * 1000;
            if (parsed.timestamp && Date.now() - parsed.timestamp > maxAge) {
                this.clear();
                return null;
            }

            delete parsed.timestamp;
            return parsed;
        } catch (e) {
            console.warn('Не удалось загрузить фильтры:', e);
            return null;
        }
    }

    clear() {
        try {
            localStorage.removeItem(this.storageKey);
        } catch (e) {
            console.warn('Не удалось очистить фильтры:', e);
        }
    }

    restoreForm(formSelector) {
        const saved = this.load();
        if (!saved) return;

        const form = document.querySelector(formSelector);
        if (!form) return;

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

    saveForm(formSelector) {
        const form = document.querySelector(formSelector);
        if (!form) return;

        const formData = new FormData(form);
        const filters = {};
        
        for (const [key, value] of formData.entries()) {
            filters[key] = value;
        }

        const urlParams = new URLSearchParams(window.location.search);
        urlParams.forEach((value, key) => {
            if (!filters[key]) {
                filters[key] = value;
            }
        });

        this.save(filters);
    }
}

document.addEventListener('DOMContentLoaded', () => {
    const filterStorage = new FilterStorage('dashboard_filters');
    const form = document.querySelector('.filters-panel form');
    
    if (form) {

        filterStorage.restoreForm('.filters-panel form');

        form.addEventListener('change', () => {
            filterStorage.saveForm('.filters-panel form');
        });

        form.addEventListener('submit', () => {
            filterStorage.saveForm('.filters-panel form');
        });

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

    const resetBtn = document.querySelector('a[href*="dashboard"][href*="show_archive"]');
    if (resetBtn && resetBtn.textContent.includes('Сбросить')) {
        resetBtn.addEventListener('click', () => {
            filterStorage.clear();
        });
    }
});

