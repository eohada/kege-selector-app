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
    Финальная версия для Obsidian:
    - Без фамилий авторов в начале.
    - Без лишних звездочек (пустых жирных выделений).
    - Без блока 'Прикрепленные файлы'.
    - Без ответа, случайно попавшего в текст задания.
    """
    if not html_content:
        return ""

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

    # 2. УДАЛЕНИЕ ФАЙЛОВ И МУСОРА
    # Удаляем ссылки на скачивание файлов (они не нужны в тексте)
    for a in soup.find_all('a'):
        # Если ссылка на скачивание или ведет на файл
        if a.has_attr('download') or (a.has_attr('href') and a['href'].lower().endswith(('.txt', '.xls', '.xlsx', '.doc', '.docx', '.csv'))):
            a.decompose()

    # Удаляем фразы "Прикрепленные файлы", "Файлы к заданию" из текста
    # Ищем текстовые узлы, содержащие эти фразы, и очищаем их
    trash_phrases = [
        re.compile(r'Файлы к заданию', re.I),
        re.compile(r'Прикрепленн[а-я]+ файл', re.I),
        re.compile(r'Файл к заданию', re.I)
    ]
    for text_node in soup.find_all(string=trash_phrases):
        # Заменяем фразу на пустоту, оставляя остальной текст (если он был в том же узле)
        clean_node = text_node
        for p in trash_phrases:
            clean_node = re.sub(p, '', clean_node)
        text_node.replace_with(clean_node)

    # 3. ИСПРАВЛЕНИЕ ФОРМУЛ (KaTeX)
    for math_span in soup.find_all('span', class_='katex'):
        tex_annotation = math_span.find('annotation', attrs={'encoding': 'application/x-tex'})
        if tex_annotation:
            tex = tex_annotation.get_text().strip()
            if 'katex-display' in math_span.get('class', []):
                math_span.replace_with(f"\n$${tex}$$\n")
            else:
                math_span.replace_with(f" ${tex}$ ")

    # 4. ИСПРАВЛЕНИЕ ТАБЛИЦ
    for table in soup.find_all('table'):
        md_rows = []
        rows = table.find_all('tr')
        if not rows: continue
        
        max_cols = 0
        for r in rows:
            max_cols = max(max_cols, len(r.find_all(['td', 'th'])))

        for i, row in enumerate(rows):
            cells = row.find_all(['th', 'td'])
            cell_texts = [c.get_text(strip=True).replace('\n', ' ') for c in cells]
            if len(cell_texts) < max_cols:
                cell_texts += [""] * (max_cols - len(cell_texts))
            md_rows.append("| " + " | ".join(cell_texts) + " |")
            if i == 0: 
                md_rows.append("| " + " | ".join(["---"] * max_cols) + " |")
        
        table.replace_with("\n" + "\n".join(md_rows) + "\n")

    # 5. КАРТИНКИ
    for img in soup.find_all('img'):
        src = img.get('src')
        if src:
            if src.startswith('/'): src = "https://kompege.ru" + src
            # Проверяем, не иконка ли это файла (иногда бывают маленькие иконки xls)
            if 'file' not in src and 'icon' not in src: 
                img.replace_with(f"\n![Иллюстрация]({src})\n")
            else:
                img.decompose()

    # 6. ФОРМАТИРОВАНИЕ (с защитой от лишних звездочек)
    # Жирный
    for tag in soup.find_all(['b', 'strong']):
        inner_text = tag.get_text(strip=True)
        # Если текста нет или это просто пробел - не оборачиваем в звездочки
        if inner_text:
            tag.replace_with(f"**{tag.get_text()}**")
        else:
            tag.unwrap() # Просто убираем тег, оставляя содержимое (пробелы)

    # Курсив
    for tag in soup.find_all(['i', 'em']):
        inner_text = tag.get_text(strip=True)
        if inner_text:
            tag.replace_with(f"*{tag.get_text()}*")
        else:
            tag.unwrap()

    # Сохраняем абзацы
    for tag in soup.find_all(['p', 'div', 'br']):
        if tag.name == 'br': tag.replace_with("\n")
        else: tag.insert_after("\n")

    # 7. ПОЛУЧЕНИЕ ТЕКСТА И ФИНАЛЬНАЯ ЧИСТКА
    text = soup.get_text(separator=' ')
    
    # Схлопываем пробелы
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n\s*\n', '\n\n', text)
    text = text.strip()

    # --- ПОСТ-ОБРАБОТКА (Regex) ---

    # A. Удаляем фамилию автора в начале (в скобках)
    # Пример: "(А. Кужей) Текст..." -> "Текст..."
    # Логика: Начало строки, скобка, буквы/точки/пробелы, скобка.
    # Ограничиваем длину (до 50 символов), чтобы случайно не удалить пояснение в скобках.
    text = re.sub(r'^\s*\([А-Яа-яЁёA-Za-z\s\.\-]{2,50}\)\s*', '', text)

    # B. Удаляем "Ответ:" в конце текста
    # Ищем "Ответ:", за которым следуют любые символы до конца строки/файла
    text = re.sub(r'\n\s*(?:Ответ|Answer)[:\.]?\s*.*$', '', text, flags=re.IGNORECASE|re.DOTALL)

    # C. Еще раз чистим пустые строки в конце после обрезания ответа
    text = text.strip()

    return text

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

