// Сохранение состояния фильтров в URL

class FilterStateManager {
    constructor() {
        this.init();
    }
    
    init() {
        // Восстанавливаем состояние фильтров из URL при загрузке
        this.restoreFromURL();
        
        // Сохраняем состояние при изменении фильтров
        this.attachListeners();
    }
    
    restoreFromURL() {
        const params = new URLSearchParams(window.location.search);
        
        // Восстанавливаем значения полей
        const searchInput = document.querySelector('input[name="search"]');
        if (searchInput && params.has('search')) {
            searchInput.value = params.get('search');
        }
        
        const categorySelect = document.querySelector('select[name="category"]');
        if (categorySelect && params.has('category')) {
            categorySelect.value = params.get('category');
        }
        
        const showArchiveInput = document.querySelector('input[name="show_archive"]');
        if (showArchiveInput && params.has('show_archive')) {
            showArchiveInput.value = params.get('show_archive');
        }
    }
    
    attachListeners() {
        // Сохраняем состояние при отправке формы фильтров
        const filterForm = document.querySelector('.filters-panel form');
        if (filterForm) {
            filterForm.addEventListener('submit', (e) => {
                this.saveToURL(filterForm);
            });
        }
        
        // Сохраняем состояние при изменении select
        const categorySelect = document.querySelector('select[name="category"]');
        if (categorySelect) {
            categorySelect.addEventListener('change', () => {
                const form = categorySelect.closest('form');
                if (form) {
                    this.saveToURL(form);
                    // Автоматически отправляем форму при изменении категории
                    setTimeout(() => form.submit(), 100);
                }
            });
        }
    }
    
    saveToURL(form) {
        const formData = new FormData(form);
        const params = new URLSearchParams();
        
        // Сохраняем все параметры формы
        for (const [key, value] of formData.entries()) {
            if (value) {
                params.set(key, value);
            }
        }
        
        // Обновляем URL без перезагрузки страницы
        const newURL = window.location.pathname + (params.toString() ? '?' + params.toString() : '');
        window.history.pushState({}, '', newURL);
    }
    
    clearFilters() {
        const params = new URLSearchParams();
        window.location.href = window.location.pathname;
    }
}

// Инициализация
document.addEventListener('DOMContentLoaded', () => {
    new FilterStateManager();
});













