
document.addEventListener('DOMContentLoaded', function() {
    const searchInput = document.getElementById('global-search-input');
    const resultsContainer = document.getElementById('global-search-results');
    
    if (!searchInput || !resultsContainer) return;
    
    let searchTimeout;
    let currentSearch = '';
    
    searchInput.addEventListener('input', function() {
        const query = this.value.trim();
        
        clearTimeout(searchTimeout);
        
        if (query.length < 2) {
            resultsContainer.style.display = 'none';
            resultsContainer.classList.remove('active');
            return;
        }

        searchTimeout = setTimeout(() => {
            performSearch(query);
        }, 300);
    });

    document.addEventListener('click', function(e) {
        if (!searchInput.contains(e.target) && !resultsContainer.contains(e.target)) {
            resultsContainer.style.display = 'none';
            resultsContainer.classList.remove('active');
        }
    });

    searchInput.addEventListener('keydown', function(e) {
        if (e.key === 'Escape') {
            resultsContainer.style.display = 'none';
            resultsContainer.classList.remove('active');
            this.blur();
        }
    });
    
    function performSearch(query) {
        if (query === currentSearch) return;
        currentSearch = query;
        
        fetch(`/api/global-search?q=${encodeURIComponent(query)}`)
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    displayResults(data.results, query);
                } else {
                    resultsContainer.innerHTML = `<div style="padding: 1rem; color: var(--text-muted);">${data.error || 'Ошибка поиска'}</div>`;
                    resultsContainer.style.display = 'block';
                    resultsContainer.classList.add('active');
                }
            })
            .catch(error => {
                console.error('Ошибка поиска:', error);
                resultsContainer.innerHTML = `<div style="padding: 1rem; color: var(--danger);">Ошибка при выполнении поиска</div>`;
                resultsContainer.style.display = 'block';
                resultsContainer.classList.add('active');
            });
    }
    
    function displayResults(results, query) {
        if (results.total === 0) {
            resultsContainer.innerHTML = `<div style="padding: 1rem; color: var(--text-muted); text-align: center;">Ничего не найдено</div>`;
            resultsContainer.style.display = 'block';
            resultsContainer.classList.add('active');
            return;
        }
        
        let html = '';

        if (results.students && results.students.length > 0) {
            html += '<div class="search-results-section">';
            html += '<div class="search-results-title">👥 Ученики (' + results.students.length + ')</div>';
            results.students.forEach(student => {
                html += `<a href="${student.url}" class="search-result-item">`;
                html += `<div class="search-result-title">${escapeHtml(student.name)}</div>`;
                html += `<div class="search-result-meta">${student.category || 'Без категории'}${student.is_active ? '' : ' (Архив)'}</div>`;
                html += `</a>`;
            });
            html += '</div>';
        }

        if (results.lessons && results.lessons.length > 0) {
            html += '<div class="search-results-section">';
            html += '<div class="search-results-title">📚 Уроки (' + results.lessons.length + ')</div>';
            results.lessons.forEach(lesson => {
                html += `<a href="${lesson.url}" class="search-result-item">`;
                html += `<div class="search-result-title">${lesson.topic || 'Без темы'}</div>`;
                html += `<div class="search-result-meta">${escapeHtml(lesson.student_name)} | ${lesson.date || 'Без даты'} | ${getStatusLabel(lesson.status)}</div>`;
                html += `</a>`;
            });
            html += '</div>';
        }

        if (results.tasks && results.tasks.length > 0) {
            html += '<div class="search-results-section">';
            html += '<div class="search-results-title">📝 Задания (' + results.tasks.length + ')</div>';
            results.tasks.forEach(task => {
                html += `<a href="${task.url}" class="search-result-item" data-task-id="${task.id}">`;
                html += `<div class="search-result-title">Задание ${task.task_number || task.site_task_id || task.id}</div>`;
                html += `<div class="search-result-meta">ID: ${task.site_task_id || task.id}</div>`;
                if (task.content_preview) {
                    html += `<div class="search-result-preview">${task.content_preview}</div>`;
                }
                html += `</a>`;
            });
            html += '</div>';
        }
        
        resultsContainer.innerHTML = html;
        resultsContainer.style.display = 'block';
        resultsContainer.classList.add('active');
    }
    
    function getStatusLabel(status) {
        const labels = {
            'planned': 'Запланирован',
            'in_progress': 'Идет',
            'completed': 'Проведен',
            'cancelled': 'Отменен'
        };
        return labels[status] || status;
    }
    
    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
});

