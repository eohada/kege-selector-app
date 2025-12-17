"""
Функции экспорта уроков в Markdown
"""
import json
import re
from html import unescape
from importlib import import_module
from app.models import Lesson
from bs4 import BeautifulSoup

BeautifulSoup = None

def html_to_text(html_content):
    """
    Конвертирует HTML в чистый Markdown для Obsidian.
    Исправленная версия: корректные формулы, таблицы и картинки.
    """
    if not html_content:
        return ""

    # Блок безопасного импорта (как у тебя было), чтобы не ломалось
    global BeautifulSoup
    if BeautifulSoup is None:
        try:
            from bs4 import BeautifulSoup
        except ImportError as exc:
            raise RuntimeError("BeautifulSoup is required. Install 'beautifulsoup4'") from exc

    soup = BeautifulSoup(html_content, 'html.parser')

    # 1. Удаляем технический мусор
    for tag in soup(['script', 'style', 'meta', 'link']):
        tag.decompose()

    # 2. ИСПРАВЛЕНИЕ ФОРМУЛ (KaTeX)
    # Достаем чистый LaTeX код из скрытых аннотаций
    for math_span in soup.find_all('span', class_='katex'):
        tex_annotation = math_span.find('annotation', attrs={'encoding': 'application/x-tex'})
        if tex_annotation:
            tex = tex_annotation.get_text().strip()
            # Если формула блочная (display mode), делаем ее с отступами
            if 'katex-display' in math_span.get('class', []):
                math_span.replace_with(f"\n$${tex}$$\n")
            else:
                math_span.replace_with(f" ${tex}$ ")

    # 3. ИСПРАВЛЕНИЕ ТАБЛИЦ
    for table in soup.find_all('table'):
        md_rows = []
        rows = table.find_all('tr')
        if not rows: continue
        
        # Считаем макс. кол-во колонок, чтобы таблица не поехала
        max_cols = 0
        for r in rows:
            max_cols = max(max_cols, len(r.find_all(['td', 'th'])))

        for i, row in enumerate(rows):
            cells = row.find_all(['th', 'td'])
            cell_texts = [c.get_text(strip=True).replace('\n', ' ') for c in cells]
            
            # Добиваем пустыми ячейками, если строка короче остальных
            if len(cell_texts) < max_cols:
                cell_texts += [""] * (max_cols - len(cell_texts))

            md_rows.append("| " + " | ".join(cell_texts) + " |")

            # Разделитель после заголовка
            if i == 0: 
                md_rows.append("| " + " | ".join(["---"] * max_cols) + " |")
        
        table.replace_with("\n" + "\n".join(md_rows) + "\n")

    # 4. ОБРАБОТКА КАРТИНОК
    for img in soup.find_all('img'):
        src = img.get('src')
        if src:
            if src.startswith('/'): src = "https://kompege.ru" + src
            img.replace_with(f"\n![Иллюстрация]({src})\n")

    # 5. ФОРМАТИРОВАНИЕ
    for tag in soup.find_all(['b', 'strong']): tag.replace_with(f"**{tag.get_text()}**")
    for tag in soup.find_all(['i', 'em']): tag.replace_with(f"*{tag.get_text()}*")
    
    # Сохраняем абзацы
    for tag in soup.find_all(['p', 'div', 'br']):
        if tag.name == 'br': tag.replace_with("\n")
        else: tag.insert_after("\n")

    # 6. ПОЛУЧЕНИЕ ЧИСТОГО ТЕКСТА
    text = soup.get_text(separator=' ')
    
    # Финальная чистка
    text = re.sub(r'[ \t]+', ' ', text)     # Убираем лишние пробелы
    text = re.sub(r'\n\s*\n', '\n\n', text) # Убираем лишние пустые строки
    
    return text.strip()

def lesson_export_md(lesson_id, assignment_type='homework'):
    """
    Универсальная функция экспорта заданий в Markdown
    assignment_type: 'homework', 'classwork', 'exam'
    """
    from flask import render_template
    from app.models import db
    
    lesson = Lesson.query.get_or_404(lesson_id)
    student = lesson.student

    # Получаем задания по типу
    if assignment_type == 'homework':
        tasks = sorted(lesson.homework_assignments, key=lambda ht: (ht.task.task_number if ht.task and ht.task.task_number is not None else ht.lesson_task_id))
        title = "Домашнее задание"
    elif assignment_type == 'classwork':
        tasks = sorted(lesson.classwork_assignments, key=lambda ht: (ht.task.task_number if ht.task and ht.task.task_number is not None else ht.lesson_task_id))
        title = "Классная работа"
    elif assignment_type == 'exam':
        tasks = sorted(lesson.exam_assignments, key=lambda ht: (ht.task.task_number if ht.task and ht.task.task_number is not None else ht.lesson_task_id))
        title = "Проверочная работа"
    else:
        tasks = sorted(lesson.homework_assignments, key=lambda ht: (ht.task.task_number if ht.task and ht.task.task_number is not None else ht.lesson_task_id))
        title = "Задания"

    ordinal_names = {
        1: "Первое", 2: "Второе", 3: "Третье", 4: "Четвертое", 5: "Пятое",
        6: "Шестое", 7: "Седьмое", 8: "Восьмое", 9: "Девятое", 10: "Десятое",
        11: "Одиннадцатое", 12: "Двенадцатое", 13: "Тринадцатое", 14: "Четырнадцатое", 15: "Пятнадцатое",
        16: "Шестнадцатое", 17: "Семнадцатое", 18: "Восемнадцатое", 19: "Девятнадцатое", 20: "Двадцатое",
        21: "Двадцать первое", 22: "Двадцать второе", 23: "Двадцать третье", 24: "Двадцать четвертое",
        25: "Двадцать пятое", 26: "Двадцать шестое", 27: "Двадцать седьмое"
    }

    markdown_content = f"# {title}\n\n"
    markdown_content += f"**Ученик:** {student.name}\n"
    if lesson.lesson_date:
        markdown_content += f"**Дата урока:** {lesson.lesson_date.strftime('%d.%m.%Y')}\n"
    if lesson.topic:
        markdown_content += f"**Тема:** {lesson.topic}\n"
    markdown_content += f"\n---\n\n"

    for idx, hw_task in enumerate(tasks):
        order_number = idx + 1
        task_name = ordinal_names.get(order_number, f"{order_number}-е")

        markdown_content += f"## {task_name} задание\n\n"

        if not hw_task.task:
            markdown_content += "*Задание не найдено*\n\n"
            continue

        # Используем глобальную функцию html_to_text
        task_text = html_to_text(hw_task.task.content_html) if hw_task.task.content_html else ""
        markdown_content += f"{task_text}\n\n"

        if hw_task.task.attached_files:
            files = json.loads(hw_task.task.attached_files)
            if files:
                markdown_content += "**Прикрепленные файлы:**\n"
                for file in files:
                    markdown_content += f"- [{file['name']}]({file['url']})\n"
                markdown_content += "\n"
        if idx < len(tasks) - 1:
            markdown_content += "---\n\n"

    return render_template('markdown_export.html', markdown_content=markdown_content, lesson=lesson, student=student)

