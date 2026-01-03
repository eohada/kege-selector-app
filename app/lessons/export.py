"""
Функции экспорта уроков в Markdown
"""
import json
import re
import logging
from html import unescape
from importlib import import_module
from app.models import Lesson

logger = logging.getLogger(__name__)

# Импортируем BeautifulSoup только при необходимости
try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None

def html_to_text(html_content):
    if not html_content:
        return ""

    # Импорты внутри, чтобы ничего не сломать
    import re
    import unicodedata
    global BeautifulSoup
    if BeautifulSoup is None:
        try:
            from bs4 import BeautifulSoup
        except ImportError as exc:
            raise RuntimeError("BeautifulSoup is required.") from exc

    # --- ШАГ 1: Подготовка Soup ---
    soup = BeautifulSoup(html_content, 'html.parser')

    # Удаляем скрипты и стили
    for tag in soup(['script', 'style', 'meta', 'link']):
        tag.decompose()

    # --- ШАГ 2: Агрессивное удаление блоков с файлами ---
    # Если в блоке (p или div) есть ссылка на скачивание ИЛИ слова про файлы -> удаляем блок целиком
    # Это решит проблему с остатками текста "Файлы к заданию:"
    for block in soup.find_all(['p', 'div']):
        block_text = block.get_text(" ", strip=True).lower()
        # Ищем ключевые слова
        if 'файлы к заданию' in block_text or 'прикрепленные файлы' in block_text:
             block.decompose()
             continue
        
        # Если внутри есть ссылка на файл (.xls, .doc и т.д.)
        if block.find('a', href=re.compile(r'\.(xls|xlsx|doc|docx|txt|csv|pdf)$', re.I)):
             # Проверяем, что это именно блок с файлами, а не просто ссылка в тексте
             if len(block_text) < 100: # Если текст короткий, скорее всего это блок скачивания
                 block.decompose()

    # Удаляем оставшиеся одиночные ссылки-файлы
    for a in soup.find_all('a'):
        if a.has_attr('download') or str(a.get('href')).lower().endswith(('.xls', '.xlsx', '.doc', '.docx', '.txt')):
            a.decompose()

    # --- ШАГ 3: Формулы (KaTeX) ---
    for math_span in soup.find_all('span', class_='katex'):
        tex_annotation = math_span.find('annotation', attrs={'encoding': 'application/x-tex'})
        if tex_annotation:
            tex = tex_annotation.get_text().strip()
            if 'katex-display' in math_span.get('class', []):
                math_span.replace_with(f"\n$${tex}$$\n")
            else:
                math_span.replace_with(f" ${tex}$ ")

    # --- ШАГ 4: Таблицы ---
    for table in soup.find_all('table'):
        rows = table.find_all('tr')
        if not rows: continue
        
        # Считаем колонки
        cols_lens = [len(r.find_all(['td', 'th'])) for r in rows]
        max_cols = max(cols_lens) if cols_lens else 0
        
        md_rows = []
        for i, row in enumerate(rows):
            cells = row.find_all(['th', 'td'])
            # Заменяем переносы внутри ячейки на пробелы
            cell_texts = [c.get_text(separator=" ", strip=True).replace('\n', ' ') for c in cells]
            # Добиваем пустые
            cell_texts += [""] * (max_cols - len(cell_texts))
            
            md_rows.append("| " + " | ".join(cell_texts) + " |")
            if i == 0:
                md_rows.append("| " + " | ".join(["---"] * max_cols) + " |")
        
        table.replace_with("\n" + "\n".join(md_rows) + "\n")

    # --- ШАГ 5: Картинки ---
    for img in soup.find_all('img'):
        src = img.get('src', '')
        if src and not any(x in src for x in ['icon', 'file']):
            if src.startswith('/'): src = "https://kompege.ru" + src
            img.replace_with(f"\n![Иллюстрация]({src})\n")
        else:
            img.decompose()

    # --- ШАГ 6: Жирный текст (подготовка) ---
    for tag in soup.find_all(['b', 'strong']): 
        # Оборачиваем, но пустые удалим позже регуляркой
        tag.replace_with(f"**{tag.get_text()}**")
    for tag in soup.find_all(['i', 'em']): 
        tag.replace_with(f"*{tag.get_text()}*")

    # Сохраняем переносы строк
    for tag in soup.find_all(['p', 'div', 'br']):
        if tag.name == 'br': tag.replace_with("\n")
        else: tag.insert_after("\n")

    # --- ШАГ 7: ПОЛУЧЕНИЕ ТЕКСТА ---
    text = soup.get_text(separator=' ')

    # === ЯДЕРНАЯ ЗАЧИСТКА (REGEX) ===
    
    # 1. Нормализация (превращает неразрывные пробелы \xa0 в обычные)
    # Это КРИТИЧНО для работы регулярок
    text = unicodedata.normalize("NFKC", text)

    # 2. Удаляем пустые жирные выделения (****, ** **, **.**)
    # Удаляет: ** **, ** **, **.**
    text = re.sub(r'\*\*\s*[\.]?\s*\*\*', '', text)

    # 3. Удаляем фамилии авторов в начале (А. Кужей)
    # ^ - начало строки, \( - скобка.
    text = re.sub(r'^\s*\([А-Яа-яA-Za-z\.\s\-]{2,40}\)', '', text)

    # 4. Удаляем "Ответ:" в конце
    # Ищет слово Ответ, двоеточие/тире и всё до конца текста
    text = re.sub(r'\n\s*(?:Ответ|Answer)\s*[:\-].*$', '', text, flags=re.IGNORECASE | re.DOTALL)
    
    # 5. Удаляем мусорные фразы, если они выжили после удаления блоков
    text = re.sub(r'Файлы?\s*к\s*задани[юcY].*', '', text, flags=re.IGNORECASE)

    # 6. Финальная косметика
    text = re.sub(r'[ \t]+', ' ', text)       # Убираем двойные пробелы
    text = re.sub(r'\n\s*\n', '\n\n', text)   # Максимум 1 пустая строка
    
    return text.strip()

def safe_markdown_escape(text):
    """Безопасное экранирование текста для Markdown (только для метаданных, не для контента)"""
    if not text:
        return ""
    text = str(text)
    # Экранируем только специальные символы Markdown, НЕ трогая обратные слеши
    # (обратные слеши нужны для LaTeX формул)
    text = text.replace('*', '\\*')
    text = text.replace('_', '\\_')
    text = text.replace('#', '\\#')
    # Убираем null-байты
    text = text.replace('\x00', '')
    return text

def safe_markdown_add(parts):
    """Безопасное добавление частей в markdown через конкатенацию"""
    result = []
    for part in parts:
        if part is None:
            continue
        result.append(str(part))
    return ''.join(result)

def lesson_export_md(lesson_id, assignment_type='homework'):
    """
    Универсальная функция экспорта заданий в Markdown
    assignment_type: 'homework', 'classwork', 'exam'
    """
    from flask import render_template, abort
    from app.models import db
    
    try:
        lesson = Lesson.query.get_or_404(lesson_id)
        
        # Проверяем наличие студента
        if not lesson.student:
            logger.error("Lesson %s has no associated student", lesson_id)
            abort(500, description="Урок не связан со студентом")
        
        student = lesson.student

        # Получаем задания по типу с безопасной сортировкой
        def safe_sort_key(ht):
            """Безопасная функция для сортировки заданий"""
            if not ht or not ht.task:
                return (999999, ht.lesson_task_id if ht else 0)
            task_number = ht.task.task_number if ht.task.task_number is not None else 999999
            return (task_number, ht.lesson_task_id)
        
        if assignment_type == 'homework':
            tasks = sorted(lesson.homework_assignments, key=safe_sort_key) if lesson.homework_assignments else []
            title = "Домашнее задание"
        elif assignment_type == 'classwork':
            tasks = sorted(lesson.classwork_assignments, key=safe_sort_key) if lesson.classwork_assignments else []
            title = "Классная работа"
        elif assignment_type == 'exam':
            tasks = sorted(lesson.exam_assignments, key=safe_sort_key) if lesson.exam_assignments else []
            title = "Проверочная работа"
        else:
            tasks = sorted(lesson.homework_assignments, key=safe_sort_key) if lesson.homework_assignments else []
            title = "Задания"
    except Exception as e:
        logger.error("Error getting lesson %s for export: %s", lesson_id, str(e), exc_info=True)
        abort(500, description="Ошибка при получении данных урока: " + str(e)[:200])

    ordinal_names = {
        1: "Первое", 2: "Второе", 3: "Третье", 4: "Четвертое", 5: "Пятое",
        6: "Шестое", 7: "Седьмое", 8: "Восьмое", 9: "Девятое", 10: "Десятое",
        11: "Одиннадцатое", 12: "Двенадцатое", 13: "Тринадцатое", 14: "Четырнадцатое", 15: "Пятнадцатое",
        16: "Шестнадцатое", 17: "Семнадцатое", 18: "Восемнадцатое", 19: "Девятнадцатое", 20: "Двадцатое",
        21: "Двадцать первое", 22: "Двадцать второе", 23: "Двадцать третье", 24: "Двадцать четвертое",
        25: "Двадцать пятое", 26: "Двадцать шестое", 27: "Двадцать седьмое"
    }

    try:
        # Используем безопасную конкатенацию вместо f-строк
        markdown_content = "# " + str(title) + "\n\n"
        
        # Безопасное получение имени студента
        student_name = str(student.name if student and student.name else "Неизвестный ученик").strip()
        student_name = safe_markdown_escape(student_name)
        markdown_content = markdown_content + "**Ученик:** " + student_name + "\n"
        
        if lesson.lesson_date:
            date_str = lesson.lesson_date.strftime('%d.%m.%Y')
            markdown_content = markdown_content + "**Дата урока:** " + date_str + "\n"
        if lesson.topic:
            topic_safe = safe_markdown_escape(str(lesson.topic).strip())
            markdown_content = markdown_content + "**Тема:** " + topic_safe + "\n"
        markdown_content = markdown_content + "\n---\n\n"

        for idx, hw_task in enumerate(tasks):
            if not hw_task:
                continue
                
            order_number = idx + 1
            task_name = ordinal_names.get(order_number, str(order_number) + "-е")
            task_header = "## " + task_name + " задание\n\n"
            markdown_content = markdown_content + task_header

            if not hw_task.task:
                markdown_content = markdown_content + "*Задание не найдено*\n\n"
                continue

            # Используем глобальную функцию html_to_text с обработкой ошибок
            try:
                if hw_task.task.content_html:
                    task_text = html_to_text(hw_task.task.content_html)
                    # Безопасное добавление текста в markdown
                    if task_text:
                        # Очищаем текст от проблемных символов
                        task_text = task_text.replace('\x00', '')  # Убираем null-байты
                        # Добавляем через конкатенацию
                        markdown_content = markdown_content + task_text + "\n\n"
                    else:
                        markdown_content = markdown_content + "*Текст задания пуст*\n\n"
                else:
                    markdown_content = markdown_content + "*Текст задания отсутствует*\n\n"
            except Exception as e:
                logger.error("Error converting HTML to text for task %s: %s", hw_task.lesson_task_id, str(e), exc_info=True)
                # Безопасное сообщение об ошибке
                try:
                    error_msg = str(e)[:100].replace('\\', '/').replace('\x00', '')
                    error_text = "*Ошибка при обработке текста задания: " + error_msg + "*\n\n"
                    markdown_content = markdown_content + error_text
                except:
                    markdown_content = markdown_content + "*Ошибка при обработке текста задания*\n\n"

            # Безопасная обработка прикрепленных файлов
            # ВАЖНО: оборачиваем в отдельный try-except, чтобы ошибка не прерывала весь экспорт
            try:
                if hw_task.task.attached_files:
                    attached_files_str = str(hw_task.task.attached_files).strip()
                    if not attached_files_str or attached_files_str == 'None' or attached_files_str == 'null':
                        # Пропускаем пустые значения
                        pass
                    else:
                        files = None
                        # Пробуем парсить как JSON БЕЗ ЛЮБЫХ ИЗМЕНЕНИЙ
                        try:
                            files = json.loads(attached_files_str)
                        except (json.JSONDecodeError, ValueError, TypeError) as json_err:
                            # Если JSON невалидный, пробуем ast.literal_eval как запасной вариант
                            try:
                                import ast
                                files = ast.literal_eval(attached_files_str)
                            except (ValueError, SyntaxError, TypeError):
                                # Если и это не сработало, просто логируем и пропускаем
                                logger.debug("Could not parse attached_files for task %s: %s. Raw: %s", 
                                           hw_task.lesson_task_id, str(json_err), attached_files_str[:100])
                                files = None
                        
                        # Добавляем файлы в markdown только если успешно распарсили
                        if files and isinstance(files, list):
                            markdown_content = markdown_content + "**Прикрепленные файлы:**\n"
                            for file in files:
                                if isinstance(file, dict):
                                    try:
                                        file_name = str(file.get('name', 'Неизвестный файл')).strip()
                                        file_url = str(file.get('url', '#')).strip()
                                        # Экранируем только квадратные скобки для Markdown ссылок
                                        file_name = file_name.replace('[', '\\[').replace(']', '\\]')
                                        # Убираем null-байты
                                        file_name = file_name.replace('\x00', '')
                                        file_url = file_url.replace('\x00', '')
                                        file_line = "- [" + file_name + "](" + file_url + ")\n"
                                        markdown_content = markdown_content + file_line
                                    except Exception as file_err:
                                        logger.debug("Error processing file entry: %s", str(file_err))
                                        continue
                            markdown_content = markdown_content + "\n"
            except Exception as e:
                # Логируем, но НЕ прерываем экспорт
                logger.warning("Error processing attached_files for task %s: %s", hw_task.lesson_task_id, str(e), exc_info=True)
                # Продолжаем без файлов
                    
            if idx < len(tasks) - 1:
                markdown_content = markdown_content + "---\n\n"

        # Финальная проверка и очистка markdown_content перед отправкой
        # Убираем потенциально проблемные последовательности
        markdown_content = markdown_content.replace('\x00', '')  # Убираем null-байты
        # Убираем только недопустимые управляющие символы (кроме \n, \t, \r)
        # Сохраняем все печатные символы, включая кириллицу
        cleaned_content = []
        for c in markdown_content:
            # Разрешаем: печатные символы, переносы строк, табуляцию, и все символы с кодом > 127 (кириллица, эмодзи и т.д.)
            if ord(c) >= 32 or c in '\n\t\r' or ord(c) > 127:
                cleaned_content.append(c)
        markdown_content = ''.join(cleaned_content)
        
        return render_template('markdown_export.html', markdown_content=markdown_content, lesson=lesson, student=student)
    except Exception as e:
        error_msg = str(e)
        logger.error("Error generating markdown content for lesson %s: %s", lesson_id, error_msg, exc_info=True)
        # Безопасное сообщение об ошибке
        safe_error = error_msg[:200].replace('\x00', '').replace('\\', '/')
        abort(500, description="Ошибка при генерации Markdown: " + safe_error)

