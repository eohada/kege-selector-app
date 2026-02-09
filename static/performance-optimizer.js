

class PerformanceOptimizer {
    constructor() {
        this.init();
    }
    
    init() {

        this.lazyLoadImages();

        this.optimizeLargeLists();

        this.debounceSearch();
    }
    
    lazyLoadImages() {
        if ('IntersectionObserver' in window) {
            const imageObserver = new IntersectionObserver((entries, observer) => {
                entries.forEach(entry => {
                    if (entry.isIntersecting) {
                        const img = entry.target;
                        if (img.dataset.src) {
                            img.src = img.dataset.src;
                            img.removeAttribute('data-src');
                            observer.unobserve(img);
                        }
                    }
                });
            });
            
            document.querySelectorAll('img[data-src]').forEach(img => {
                imageObserver.observe(img);
            });
        }
    }
    
    optimizeLargeLists() {

        const largeLists = document.querySelectorAll('.students-grid, .lessons-list');
        largeLists.forEach(list => {
            const items = list.querySelectorAll('.student-card, .lesson-card');
            if (items.length > 50) {

                this.addPagination(list, items);
            }
        });
    }
    
    addPagination(list, items) {
        const itemsPerPage = 20;
        let currentPage = 1;
        const totalPages = Math.ceil(items.length / itemsPerPage);

        items.forEach((item, index) => {
            if (index >= itemsPerPage) {
                item.style.display = 'none';
            }
        });

        const pagination = document.createElement('div');
        pagination.className = 'pagination-controls';
        pagination.innerHTML = `
            <button class="pagination-btn" data-action="prev">‹ Назад</button>
            <span class="pagination-info">Страница ${currentPage} из ${totalPages}</span>
            <button class="pagination-btn" data-action="next">Вперёд ›</button>
        `;
        
        list.parentElement.insertBefore(pagination, list.nextSibling);

        pagination.querySelector('[data-action="prev"]').addEventListener('click', () => {
            if (currentPage > 1) {
                currentPage--;
                this.showPage(items, currentPage, itemsPerPage);
                pagination.querySelector('.pagination-info').textContent = `Страница ${currentPage} из ${totalPages}`;
            }
        });
        
        pagination.querySelector('[data-action="next"]').addEventListener('click', () => {
            if (currentPage < totalPages) {
                currentPage++;
                this.showPage(items, currentPage, itemsPerPage);
                pagination.querySelector('.pagination-info').textContent = `Страница ${currentPage} из ${totalPages}`;
            }
        });
    }
    
    showPage(items, page, itemsPerPage) {
        const start = (page - 1) * itemsPerPage;
        const end = start + itemsPerPage;
        
        items.forEach((item, index) => {
            if (index >= start && index < end) {
                item.style.display = '';
            } else {
                item.style.display = 'none';
            }
        });
    }
    
    debounceSearch() {
        const searchInputs = document.querySelectorAll('input[name="search"], input[type="search"]');
        searchInputs.forEach(input => {
            let timeout;
            input.addEventListener('input', () => {
                clearTimeout(timeout);
                timeout = setTimeout(() => {

                    const form = input.closest('form');
                    if (form && form.dataset.autoSubmit !== 'false') {

                    }
                }, 500);
            });
        });
    }
}

document.addEventListener('DOMContentLoaded', () => {
    new PerformanceOptimizer();
});

