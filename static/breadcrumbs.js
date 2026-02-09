
function createBreadcrumbs(items) {

    const breadcrumbs = document.createElement('nav');
    breadcrumbs.className = 'breadcrumbs';
    breadcrumbs.setAttribute('aria-label', 'Навигационная цепочка');
    
    const list = document.createElement('ol');
    list.className = 'breadcrumbs-list';
    
    items.forEach((item, index) => {
        const listItem = document.createElement('li');
        listItem.className = 'breadcrumbs-item';
        
        if (index === items.length - 1) {

            listItem.setAttribute('aria-current', 'page');
            const span = document.createElement('span');
            span.className = 'breadcrumbs-current';
            span.textContent = item.label;
            listItem.appendChild(span);
        } else {

            const link = document.createElement('a');
            link.href = item.url || '#';
            link.className = 'breadcrumbs-link';
            link.textContent = item.label;
            listItem.appendChild(link);
        }
        
        list.appendChild(listItem);
    });
    
    breadcrumbs.appendChild(list);
    return breadcrumbs;
}

function initBreadcrumbs() {
    const breadcrumbsContainer = document.querySelector('.breadcrumbs-container');
    if (!breadcrumbsContainer) return;
    
    const path = window.location.pathname;
    const items = [{label: 'Главная', url: '/'}];

    const pathParts = path.split('/').filter(p => p);
    
    if (pathParts.length === 0) {
        items[0].label = 'Главная';
    } else {

        if (pathParts[0] === 'dashboard' || pathParts[0] === 'student') {
            items.push({label: 'Ученики', url: '/dashboard'});
            
            if (pathParts[0] === 'student' && pathParts[1]) {

                const studentName = document.querySelector('h1')?.textContent || 'Профиль ученика';
                items.push({label: studentName});
            }
        } else if (pathParts[0] === 'schedule') {
            items.push({label: 'Расписание'});
        } else if (pathParts[0] === 'generator' || pathParts[0] === 'kege-generator') {
            items.push({label: 'Генератор заданий'});
        } else if (pathParts[0] === 'lesson') {
            items.push({label: 'Урок'});
            if (pathParts[2] === 'homework-tasks' || pathParts[2] === 'classwork-tasks' || pathParts[2] === 'exam-tasks') {
                const type = pathParts[2].replace('-tasks', '').replace('homework', 'Домашнее задание')
                    .replace('classwork', 'Классная работа').replace('exam', 'Проверочная работа');
                items.push({label: type});
            }
        } else if (pathParts[0] === 'update-plans') {
            items.push({label: 'Планы'});
        } else if (pathParts[0] === 'student' && pathParts.length > 1 && pathParts[1] === 'statistics') {
            items.push({label: 'Ученики', url: '/dashboard'});
            const studentName = document.querySelector('h1')?.textContent?.replace('Прогресс по заданиям: ', '') || 'Статистика';
            items.push({label: studentName, url: window.location.pathname.replace('/statistics', '')});
            items.push({label: 'Статистика'});
        } else if (pathParts[0] === 'generator' || pathParts[0] === 'kege-generator') {
            items.push({label: 'Генератор заданий'});
        }
    }
    
    const breadcrumbs = createBreadcrumbs(items);
    breadcrumbsContainer.appendChild(breadcrumbs);
}

document.addEventListener('DOMContentLoaded', initBreadcrumbs);
