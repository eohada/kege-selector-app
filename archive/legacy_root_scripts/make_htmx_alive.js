const fs = require('fs');

let content = fs.readFileSync('templates/lesson_homework.html', 'utf8');

// Возвращаем HTMX логику в форму отправки заданий.
// Исходная рабочая логика в бэкапе использовала hx-post, hx-target и обертку блоков задач.
// Чтобы не переписывать тонну Python-рендеров, мы можем использовать Vanilla JS + fetch для отправки формы без перезагрузки, 
// Либо вернуть атрибут hx-post/hx-swap. Так как в шаблоне BootStudy используется HTMX, я восстановлю его.

// Ищем нашу недавно добавленную форму
const formRegex = /<form id="homework-form" method="POST" data-no-ajax action="\{\% if is_student_view \%\}\{\% if assignment_type == 'homework' \%\}\{\{ url_for\('lessons\.lesson_homework_student_save', lesson_id=lesson\.lesson_id\) \}\}[\s\S]*?">/;

const htmxFormReplacement = `<form id="homework-form" hx-post="{% if is_student_view %}{% if assignment_type == 'homework' %}{{ url_for('lessons.lesson_homework_student_save', lesson_id=lesson.lesson_id) }}{% elif assignment_type == 'classwork' %}{{ url_for('lessons.lesson_classwork_student_save', lesson_id=lesson.lesson_id) }}{% else %}{{ url_for('lessons.lesson_exam_student_save', lesson_id=lesson.lesson_id) }}{% endif %}{% else %}{% if assignment_type == 'homework' %}{{ url_for('lessons.lesson_homework_save', lesson_id=lesson.lesson_id) }}{% elif assignment_type == 'classwork' %}{{ url_for('lessons.lesson_classwork_save', lesson_id=lesson.lesson_id) }}{% else %}{{ url_for('lessons.lesson_exam_save', lesson_id=lesson.lesson_id) }}{% endif %}{% endif %}" hx-swap="none">`; // hx-swap="none" предотвратит замену всего интерфейса и подгрузку голого HTML, но запрос отправится.

if(content.match(formRegex)) {
    content = content.replace(formRegex, htmxFormReplacement);
}

// Теперь нужно восстановить логику сокетов из бэкапа. Она находилась в самом низу файла.
// Считаем все <script> из бэкапа.
const backupContent = fs.readFileSync('templates/lesson_homework_backup_jinja.html', 'utf8');

// Найдем весь большой скрипт `const LESSON_ID =` до конца блока контента.
const scriptStart = backupContent.indexOf('<script>\n        const LESSON_ID');
const scriptEnd = backupContent.lastIndexOf('</script>', backupContent.indexOf('{% endblock %}')) + 9;

if (scriptStart !== -1 && scriptEnd !== -1) {
    const backupScripts = backupContent.substring(scriptStart, scriptEnd);
    
    // Вставим этот оригинальный JS перед закрытием {% endblock %} в нашем новом файле
    // Обязательно уберем наш простой Vanilla JS таб, так как оригинальный скрипт сам переключает табы и синхронизирует их через сокеты и localStorage
    const obsoleteVanillaScriptRegex = /<!-- ============================================== -->\s*<!-- Vanilla JS Переключатель Табов -->\s*<!-- ============================================== -->\s*<script>[\s\S]*?<\/script>/;
    
    content = content.replace(obsoleteVanillaScriptRegex, '');
    content = content.replace('{% endblock %}', '\n\n    <!-- ВОССТАНОВЛЕННЫЙ ОРИГИНАЛЬНЫЙ JAVASCRIPT ИНТЕРАКТИВ И SOCKET.IO -->\n    ' + backupScripts + '\n{% endblock %}');
}

fs.writeFileSync('templates/lesson_homework.html', content);
