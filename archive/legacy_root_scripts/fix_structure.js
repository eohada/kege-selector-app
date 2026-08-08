const fs = require('fs');
let content = fs.readFileSync('templates/lesson_homework.html', 'utf8');

// 1. Починим селектор табов для Vanilla JS переключателя.
// Мы обновили классы контейнера табов, но JS все еще искал '.lesson-tabs'.
content = content.replace("const tabBtns = document.querySelectorAll('.lesson-tabs .tab-btn');", "const tabBtns = document.querySelectorAll('[role=\"tablist\"] .tab-btn');");

// 2. Исправим взорванную сетку.
// Проблема в том, что сайдбар был вставлен ПОСЛЕ #createLessonTemplateModal (который может лежать вне .lesson-room-workspace).
// Нам нужно убедиться, что сайдбар сидит ВНУТРИ <div class="lesson-room-workspace ..."> перед его закрывающим </div>.

// Найдем конец левой колонки (main column). В старой верстке он заканчивается около id=form-delete.
// Но надежнее найти конец самого workspace.
// В начале мы уже вставили сайдбар, и он сидит где-то в коде. Сначала вырежем его оттуда.

const sidebarRegex = /<!-- Правая колонка: Sticky Sidebar -->[\s\S]*?<\/aside>/;
const sidebarMatch = content.match(sidebarRegex);

if (sidebarMatch) {
    const sidebarHtml = sidebarMatch[0];
    content = content.replace(sidebarRegex, ''); // Удаляем со старого места
    
    // Удаляем кривой коммент
    content = content.replace('</div> <!-- End of Left Column -->', '');

    // Найдем конец main-column и вставим сайдбар сразу после него
    const endOfMainColumn = '</div> <!-- end of lesson-room-main-column -->';
    if (content.includes(endOfMainColumn)) {
        content = content.replace(endOfMainColumn, endOfMainColumn + '\n\n' + sidebarHtml);
    }
}

fs.writeFileSync('templates/lesson_homework.html', content);
