const fs = require('fs');
let content = fs.readFileSync('templates/lesson_homework.html', 'utf8');

// Полностью вычистим сломанный верх файла и восстановим базовые теги, которые мы случайно потерли
const cleanHeader = `{% extends 'base.html' %}
{% from '_task_content_block.html' import render_task_content %}
{% block html_attrs %}data-student-lesson-room="1"{% endblock %}
{% block title %}{{ lesson.topic or 'Урок' }} · BooStudy{% endblock %}
{% set active_page = 'student_profile' if (is_student_view or is_parent_view) else 'dashboard' %}
{% block body_attrs %}data-cinema-scene="lesson"{% endblock %}
{% block body_class %}{% if is_student_view or is_parent_view %}layout-student{% else %}layout-teacher teacher-mode{% endif %} min-h-screen{% endblock %}

{% block head_css %}
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <link rel="stylesheet" href="https://unpkg.com/easymde/dist/easymde.min.css">`;

// Находим начало блока head_css (или то место, где он должен быть), удаляем весь мусорный JS сверху.
let cssBlockIndex = content.indexOf('{% block head_css %}');
if (cssBlockIndex !== -1) {
    content = cleanHeader + content.substring(cssBlockIndex + '{% block head_css %}'.length);
} else {
    // В файле вообще мусор, давайте найдем первую оставшуюся часть css
    let styleIndex = content.indexOf('    <style>');
    if(styleIndex !== -1) {
        content = cleanHeader + '\n' + content.substring(styleIndex);
    }
}

fs.writeFileSync('templates/lesson_homework.html', content);
