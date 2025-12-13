"""
Функции экспорта уроков в Markdown
"""
import json
import re
from html import unescape
from importlib import import_module
from app.models import Lesson

BeautifulSoup = None

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

    def html_to_text(html_content):
        if not html_content:
            return ""
        global BeautifulSoup
        if BeautifulSoup is None:
            try:
                BeautifulSoup = import_module('bs4').BeautifulSoup
            except ImportError as exc:
                raise RuntimeError("BeautifulSoup is required for markdown export. Install 'beautifulsoup4'.") from exc

        soup = BeautifulSoup(html_content, 'html.parser')

        for tag in soup(['script', 'style']):
            tag.decompose()

        def collapse_spaces(value: str) -> str:
            return re.sub(r'\s+', ' ', value).strip()

        def sup_sub_text(node):
            text_value = collapse_spaces(node.get_text(separator=' ', strip=True))
            if not text_value:
                return ''
            return text_value

        for sup in list(soup.find_all('sup')):
            sup_content = sup_sub_text(sup)
            replacement = f"$^{{{sup_content}}}$" if sup_content else ''
            sup.replace_with(soup.new_string(replacement))

        for sub in list(soup.find_all('sub')):
            sub_content = sup_sub_text(sub)
            replacement = f"$_{{{sub_content}}}$" if sub_content else ''
            sub.replace_with(soup.new_string(replacement))

        def extract_formula(node) -> str:
            aria = node.get('aria-label')
            if aria:
                return aria.strip()
            annotation = node.select_one('annotation[encoding="application/x-tex"]')
            if annotation:
                return annotation.get_text(strip=True)
            text = node.get_text(strip=True)
            return text

        for katex_span in list(soup.select('.katex, .katex-display, .katex-inline')):
            formula = extract_formula(katex_span)
            if formula:
                is_display = 'katex-display' in katex_span.get('class', [])
                if is_display:
                    katex_span.replace_with(soup.new_string(f"\n\n$${formula}$$\n\n"))
                else:
                    katex_span.replace_with(soup.new_string(f" ${formula}$ "))
            else:
                katex_span.decompose()

        def table_to_markdown(table):
            rows = []
            for tr in table.find_all('tr'):
                cells = []
                for cell in tr.find_all(['th', 'td']):
                    cell_text = cell.get_text(separator=' ', strip=True)
                    cell_text = collapse_spaces(cell_text)
                    cells.append(cell_text)
                if cells:
                    rows.append(cells)
            if not rows:
                return ''

            col_count = max(len(r) for r in rows)
            for row in rows:
                if len(row) < col_count:
                    row.extend([''] * (col_count - len(row)))

            widths = [0] * col_count
            for row in rows:
                for idx, cell in enumerate(row):
                    widths[idx] = max(widths[idx], len(cell))

            def fmt_row(row):
                padded = [
                    row[i].ljust(widths[i]) if widths[i] else row[i]
                    for i in range(col_count)
                ]
                return '| ' + ' | '.join(padded) + ' |'

            header = fmt_row(rows[0])
            separator = '| ' + ' | '.join('-' * max(3, widths[i] or 3) for i in range(col_count)) + ' |'
            body = [fmt_row(row) for row in rows[1:]] if len(rows) > 1 else []
            return '\n'.join([header, separator, *body])

        for table in soup.find_all('table'):
            md = table_to_markdown(table)
            table.replace_with(soup.new_string(f'\n\n{md}\n\n'))

        for img in soup.find_all('img'):
            src = img.get('src', '')
            alt = img.get('alt', '')
            title = img.get('title', '')

            if not src:
                img.decompose()
                continue

            if title:
                markdown_img = f'![{alt}]({src} "{title}")'
            else:
                markdown_img = f'![{alt}]({src})'

            img.replace_with(soup.new_string(f'\n\n{markdown_img}\n\n'))

        # Обработка списков
        def extract_list_item_text(li):
            parts = []
            for child in li.children:
                if isinstance(child, str):
                    text = child.strip()
                    if text:
                        parts.append(text)
                elif hasattr(child, 'name'):
                    if child.name == 'br':
                        parts.append('\n')
                    elif child.name in ['p', 'div']:
                        p_text = child.get_text(separator='\n', strip=True)
                        if p_text:
                            parts.append(p_text)
                    else:
                        child_text = child.get_text(separator=' ', strip=True)
                        if child_text:
                            parts.append(child_text)
            return ' '.join(parts).strip()
        
        for ul in soup.find_all('ul'):
            if not ul.find_parent(['td', 'th', 'table']):
                items = ul.find_all('li', recursive=False)
                if items:
                    list_items = []
                    for li in items:
                        li_text = extract_list_item_text(li)
                        if li_text:
                            list_items.append(f"- {li_text}")
                    if list_items:
                        list_text = '\n'.join(list_items)
                        ul.replace_with(soup.new_string(f'\n\n{list_text}\n\n'))
                    else:
                        ul.decompose()
                else:
                    ul.decompose()
        
        for ol in soup.find_all('ol'):
            if not ol.find_parent(['td', 'th', 'table']):
                items = ol.find_all('li', recursive=False)
                if items:
                    list_items = []
                    for idx, li in enumerate(items):
                        li_text = extract_list_item_text(li)
                        if li_text:
                            list_items.append(f"{idx + 1}. {li_text}")
                    if list_items:
                        list_text = '\n'.join(list_items)
                        ol.replace_with(soup.new_string(f'\n\n{list_text}\n\n'))
                    else:
                        ol.decompose()
                else:
                    ol.decompose()
        
        for br in soup.find_all('br'):
            br.replace_with(soup.new_string('\n'))

        def process_element(elem):
            if elem.name in ['p', 'div']:
                if not elem.find_parent(['td', 'th', 'table']):
                    if elem.get_text(strip=True):
                        if elem.previous_sibling and not isinstance(elem.previous_sibling, str):
                            elem.insert_before('\n\n')
                        if elem.next_sibling and not isinstance(elem.next_sibling, str):
                            elem.insert_after('\n\n')

        for p in soup.find_all('p'):
            process_element(p)
        for div in soup.find_all('div'):
            process_element(div)

        for text_node in soup.find_all(string=True):
            if text_node.parent and text_node.parent.name not in ['script', 'style']:
                text = str(text_node)
                cleaned_text = re.sub(r'[Фф]айлы?\s+к\s+заданию[:\s-]*[^\n]*', '', text, flags=re.IGNORECASE)
                cleaned_text = re.sub(r'[Фф]айлы?\s+к\s+задаче[:\s-]*[^\n]*', '', cleaned_text, flags=re.IGNORECASE)
                cleaned_text = re.sub(r'[Пп]рикреплен[а-яё]*\s+файл[а-яё]*[:\s-]*[^\n]*', '', cleaned_text, flags=re.IGNORECASE)
                if cleaned_text != text:
                    text_node.replace_with(cleaned_text)
        
        text = soup.get_text(separator='\n', strip=False)
        text = unescape(text)
        text = re.sub(r'\r\n?', '\n', text)
        lines = text.split('\n')
        cleaned_lines = []
        for line in lines:
            cleaned_line = re.sub(r'[ \t]+', ' ', line)
            cleaned_lines.append(cleaned_line)
        text = '\n'.join(cleaned_lines)
        text = re.sub(r' \$\$', '\n\n$$', text)
        text = re.sub(r'\$\$ ', '$$\n\n', text)
        text = re.sub(r' \$', ' $', text)
        text = re.sub(r'\$ ', '$ ', text)
        text = re.sub(r' \n', '\n', text)
        text = re.sub(r'\n ', '\n', text)
        text = re.sub(r'\n{4,}', '\n\n\n', text)
        text = re.sub(r'\$\s+([^$]+)\s+\$', r'$\1$', text)
        lines = [line.rstrip() for line in text.splitlines()]
        cleaned = []
        prev_blank = False
        for line in lines:
            stripped = line.strip()
            if stripped:
                cleaned.append(stripped)
                prev_blank = False
            else:
                if not prev_blank:
                    cleaned.append('')
                prev_blank = True
        result = '\n'.join(cleaned).strip()
        return result

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

