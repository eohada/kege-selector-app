const fs = require('fs');
let content = fs.readFileSync('templates/lesson_homework.html', 'utf8');

// В Jinja-цикле {% for hw_task in homework_tasks %} мы могли потерять </div>
// Проверим закрывающие теги. Сайдбар должен быть сразу после </div> <!-- end of lesson-room-main-column -->
// Посмотрим, нет ли бага с закрытием тегов перед ним
// Выяснили по логам, что `lesson-room-main-column` закрывается корректно, НО!
// Мы забыли, что таб "whiteboard" и "videocall" тоже присутствовали в старом коде, и они лежат ВНУТРИ `lesson-room-main-column`.
// Если в старом коде перед нашим сайдбаром стоят какие-то другие </div>, то сайдбар выпадает из сетки.

// Убедимся, что сетка задана на правильном уровне:
content = content.replace('<div class="lesson-room-workspace grid grid-cols-1 xl:grid-cols-[1fr_320px] gap-8 items-start relative mt-4">', '<div class="lesson-room-workspace grid grid-cols-1 xl:grid-cols-[1fr_320px] gap-8 items-start relative mt-4">');

// Напишем скрипт-парсинг:
// 1. Найдем открытие `<div class="lesson-room-workspace grid...`
// 2. Найдем `<aside ... id="lesson-sidebar">`
// 3. Если перед сайдбаром стоит слишком много `</div>`, мы это исправим.
// НО самая частая ошибка в таких случаях: Jinja форма или контейнеры внутри таба заданий закрылись неправильно.

// Я посмотрю, где находится закрывающий `</form>` блок с заданиями
let cssFix = `
/* Фикс для утечки CSS-свойств, ломающих грид */
.lesson-room-workspace {
    display: grid !important;
}
.lesson-room-main-column {
    min-width: 0 !important;
}
`;
content = content.replace('</style>', cssFix + '\n</style>');

fs.writeFileSync('templates/lesson_homework.html', content);
