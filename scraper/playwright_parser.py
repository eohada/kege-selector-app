import os
import sys
import re
import json
from playwright.sync_api import sync_playwright, Page
from playwright_stealth import Stealth
from urllib.robotparser import RobotFileParser
from bs4 import BeautifulSoup
import time

SITE_DOMAIN = "https://kompege.ru"
MAIN_PAGE_URL = f"{SITE_DOMAIN}/task"
ROBOTS_URL = f"{SITE_DOMAIN}/robots.txt"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36"

TASKS_TO_SCRAPE = {
    1: "1",
    2: "2",
    3: "3",
    4: "4",
    5: "5",
    6: "6",
    7: "7",
    8: "8",
    9: "9",
    10: "10",
    11: "11",
    12: "12",
    13: "13",
    14: "14",
    15: "15",
    16: "16",
    17: "17",
    18: "18",
    19: "19",
    22: "22",
    23: "23",
    24: "24",
    25: "25",
    26: "26",
    27: "27",
}

DROPDOWN_SELECTOR = "select"
SEARCH_BUTTON_SELECTOR = "input[type='button'][value='Найти все задачи']"
TASK_BLOCK_SELECTOR = "table tbody tr"
TASK_CONTENT_SELECTOR = "td:nth-child(2) div.task-text"
TASK_DETAILS_SELECTOR = "td:nth-child(2) span.details"

CRAWL_DELAY_SEC = 1

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.append(project_root)

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from core.db_models import Tasks, moscow_now

db_path = os.path.join(project_root, 'data', 'keg_tasks.db')
engine = create_engine(f'sqlite:///{db_path}')
Session = sessionmaker(bind=engine)
session = Session()

def _strip_code_from_answer_line(line: str) -> str:
    """Убирает код из строки ответа: оставляет цифры, пробелы, запятые; вырезает код."""
    if not line or not isinstance(line, str):
        return ''
    line = line.strip()
    # Удалить блоки кода в обратных кавычках
    line = re.sub(r'```[\s\S]*?```', '', line, flags=re.DOTALL)
    line = re.sub(r'`[^`]*`', '', line)
    # Строка похожа на код?
    code_indicators = re.compile(
        r'\b(def|import|from|class|return|print|for\s+\w+\s+in|if\s+.*:|\w+\s*=\s*[\[\{]|\#.*$)',
        re.IGNORECASE
    )
    if code_indicators.search(line) and not re.match(r'^[\d\s\-,\.]+$', line):
        return ''
    # Оставить только цифры, пробелы, запятые, точки, минус (для ответов)
    cleaned = re.sub(r'[^\d\s\-,\.]', ' ', line)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    return cleaned


def _parse_answer_19_21(raw_answer: str) -> list:
    """
    Разбивает блок ответа заданий 19–21 на три строки (19, 20, 21).
    Убирает код, возвращает список из 3 строк (возможно пустых).
    """
    if not raw_answer or not isinstance(raw_answer, str):
        return ['', '', '']
    text = raw_answer.strip()
    # Удалить блоки кода целиком
    text = re.sub(r'```[\s\S]*?```', '', text, flags=re.DOTALL)
    lines = [s.strip() for s in re.split(r'[\r\n]+', text) if s.strip()]
    result = ['', '', '']
    for i, line in enumerate(lines[:3]):
        result[i] = _strip_code_from_answer_line(line)
    return result


def _split_content_19_21(full_html: str):
    """
    Разрезает общий HTML заданий 19–21 на три части по маркерам «Задание 20.» и «Задание 21.».
    Возвращает (html_19, html_20, html_21). Если маркеры не найдены — вся строка в html_19, остальное пусто.
    """
    if not full_html or not full_html.strip():
        return ('', '', '')
    text = full_html
    mark_20 = re.compile(r'Задание\s+20\s*\.', re.IGNORECASE)
    mark_21 = re.compile(r'Задание\s+21\s*\.', re.IGNORECASE)
    m20 = mark_20.search(text)
    m21 = mark_21.search(text)
    if not m20 and not m21:
        return (full_html.strip(), '', '')
    # Границы по смыслу: до «Задание 20.» — 19-е, между 20 и 21 — 20-е, после «Задание 21.» — 21-е
    pos_20 = m20.start() if m20 else len(text)
    pos_21 = m21.start() if m21 else len(text)
    if pos_20 <= pos_21:
        part_19 = text[:pos_20].strip()
        part_20 = text[pos_20:pos_21].strip() if pos_21 < len(text) else text[pos_20:].strip()
        part_21 = text[pos_21:].strip() if pos_21 < len(text) else ''
    else:
        part_19 = text[:pos_21].strip()
        part_20 = ''
        part_21 = text[pos_21:].strip()
    return (part_19, part_20, part_21)


def clean_html_content(html: str, task_number: int = None) -> str:
    """Очистка HTML-контента заданий: удаление фамилий, пустых строк, ответов, видео"""
    if not html:
        return html
    
    soup = BeautifulSoup(html, 'html.parser')
    
    html_str = str(soup)
    
    html_str = re.sub(r'\(\s*[А-ЯЁ]\.\s*[А-ЯЁ]\.\s*[А-ЯЁ][а-яё]+\s*\)', '', html_str)  # (И.О. Фамилия) или (И.О.Фамилия)
    html_str = re.sub(r'\(\s*[А-ЯЁ]\.[А-ЯЁ][а-яё]+\s*\)', '', html_str)  # (И.Фамилия) - БЕЗ пробела после точки
    html_str = re.sub(r'\(\s*[А-ЯЁ]\.\s*[А-ЯЁ][а-яё]+\s*\)', '', html_str)  # (И. Фамилия) - С пробелом
    html_str = re.sub(r'\(\s*[А-ЯЁ][а-яё]{3,}\s*\)', '', html_str)  # (Фамилия) - только фамилия в скобках
    
    html_str = re.sub(r'\b[А-ЯЁ][а-яё]{3,}\s+[А-ЯЁ]\.\s*[А-ЯЁ]\.', '', html_str)  # Фамилия И.О.
    html_str = re.sub(r'\b[А-ЯЁ][а-яё]{3,}\s+[А-ЯЁ]\.', '', html_str)  # Фамилия И.
    html_str = re.sub(r'\b[А-ЯЁ][а-яё]{3,}\s+[А-ЯЁ][а-яё]{2,}', '', html_str)  # Фамилия Имя
    
    html_str = re.sub(r'\s{2,}', ' ', html_str)
    
    soup = BeautifulSoup(html_str, 'html.parser')
    
    for text_node in soup.find_all(string=True):
        if text_node.parent and text_node.parent.name not in ['script', 'style']:
            text = str(text_node)
            cleaned = re.sub(r'[Фф]айлы?\s+к\s+заданию[:\s-]*[^\n<]*', '', text, flags=re.IGNORECASE)
            cleaned = re.sub(r'[Фф]айлы?\s+к\s+задаче[:\s-]*[^\n<]*', '', cleaned, flags=re.IGNORECASE)
            cleaned = re.sub(r'[Пп]рикреплен[а-яё]*\s+файл[а-яё]*[:\s-]*[^\n<]*', '', cleaned, flags=re.IGNORECASE)
            if cleaned != text:
                text_node.replace_with(cleaned)
    
    if task_number == 6:
        # Сначала убираем все видео и iframe
        for tag in soup.find_all(['iframe', 'video', 'source']):
            tag.decompose()
        html_str = str(soup)
        html_str = re.sub(r'<iframe[^>]*>.*?</iframe>', '', html_str, flags=re.IGNORECASE | re.DOTALL)
        html_str = re.sub(r'<video[^>]*>.*?</video>', '', html_str, flags=re.IGNORECASE | re.DOTALL)
        soup = BeautifulSoup(html_str, 'html.parser')
        # Обрезаем контент с первого вхождения «Ответ»/«Видео» и всё, что после (только у задания 6)
        all_tags = soup.find_all(True)
        cut_index = None
        for i, tag in enumerate(all_tags):
            text = (tag.get_text() or '').strip()
            if not text:
                continue
            if re.search(r'\b[Оо]твет\b|[Вв]идео\b|[Aa]nswer\b|[Vv]ideo\b', text, re.IGNORECASE):
                cut_index = i
                break
        if cut_index is not None:
            for j in range(len(all_tags) - 1, cut_index - 1, -1):
                try:
                    all_tags[j].decompose()
                except Exception:
                    pass
        # Дополнительно: удалить узлы, в которых только ответ (число/короткий текст после «Ответ»)
        for elem in soup.find_all(string=re.compile(r'[Оо]твет[а-яё]*\s*[:\s]*\s*[^\n<]{0,80}', re.IGNORECASE)):
            parent = elem.parent
            if parent and parent.name not in ('script', 'style'):
                parent.decompose()
        html_str = str(soup)
        html_str = re.sub(r'<[^>]*>.*?[Оо]твет[а-яё]*[:\s]*[^<]*</[^>]*>', '', html_str, flags=re.IGNORECASE | re.DOTALL)
        html_str = re.sub(r'[Оо]твет[а-яё]*[:\s]*[^\n<]+', '', html_str, flags=re.IGNORECASE)
        soup = BeautifulSoup(html_str, 'html.parser')
    
    if task_number == 5:
        html_str = str(soup)
        html_str = re.sub(r'(<br\s*/?>[\s\n]*)+', ' ', html_str, flags=re.IGNORECASE)
        html_str = re.sub(r'<p>\s*</p>', '', html_str, flags=re.IGNORECASE)
        html_str = re.sub(r'<div>\s*</div>', '', html_str, flags=re.IGNORECASE)
        soup = BeautifulSoup(html_str, 'html.parser')
    
    if task_number == 8:
        for list_tag in soup.find_all(['ul', 'ol']):
            for li in list_tag.find_all('li', recursive=False):
                if li.next_sibling and li.next_sibling.name == 'li':
                    li.insert_after('\n')
    
    html_str = str(soup)
    
    html_str = re.sub(r'(<br\s*/?>[\s\n]*){2,}', ' ', html_str, flags=re.IGNORECASE)
    html_str = re.sub(r'<br\s*/?>', ' ', html_str, flags=re.IGNORECASE)
    
    soup = BeautifulSoup(html_str, 'html.parser')
    
    for tag in soup.find_all(['p', 'div']):
        text_content = tag.get_text(strip=True)
        if not text_content or text_content.isspace():
            if not tag.find_all(['img', 'iframe', 'video', 'ul', 'ol', 'table']):
                tag.decompose()
    
    for tag in soup.find_all(['span', 'strong', 'em', 'b', 'i']):
        if not tag.get_text(strip=True):
            tag.unwrap()  # Удаляем тег, но сохраняем содержимое (если есть)
    
    for tag in soup.find_all(True):
        if tag.string:
            normalized = re.sub(r'\s+', ' ', tag.string)
            if normalized != tag.string:
                tag.string = normalized
    
    for tag in soup.find_all(True):
        attrs_to_remove = [attr for attr in tag.attrs if attr.startswith('data-v-')]
        for attr in attrs_to_remove:
            del tag[attr]
    
    html = str(soup)
    
    html = re.sub(r'[ \t]+', ' ', html)
    
    html = re.sub(r'>\s*\n\s*\n\s*<', '><', html)  # Удаляем пустые строки между тегами
    html = re.sub(r'\n{3,}', '\n', html)  # Более 2 переносов строк заменяем на 1
    
    lines = html.split('\n')
    cleaned_lines = []
    prev_empty = False
    
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.isspace():
            if not prev_empty:
                cleaned_lines.append('')
            prev_empty = True
        else:
            cleaned_lines.append(stripped)
            prev_empty = False
    
    html = '\n'.join(cleaned_lines)
    
    html = html.strip()
    
    html = re.sub(r' {2,}', ' ', html)
    
    return html

def check_robots_txt():
    print(f"[ETL] 1. Проверка {ROBOTS_URL} для User-Agent: {USER_AGENT}...")
    try:
        rp = RobotFileParser()
        rp.set_url(ROBOTS_URL)
        rp.read()

        global CRAWL_DELAY_SEC
        delay = rp.crawl_delay(USER_AGENT)
        if delay:
            CRAWL_DELAY_SEC = delay
            print(f"[ETL] Установлена задержка (Crawl-delay) из robots.txt: {CRAWL_DELAY_SEC} сек.")

        if not rp.can_fetch(USER_AGENT, MAIN_PAGE_URL):
            print(f"[ETL] КРИТИЧЕСКАЯ ОШИБКА: robots.txt ЗАПРЕЩАЕТ доступ к {MAIN_PAGE_URL}")
            return False

        print("[ETL] Проверка robots.txt пройдена.")
        return True
    except Exception as e:
        print(f"[ETL] Ошибка при чтении robots.txt: {e}. (Продолжаем с осторожностью)")
        return True

def fetch_tasks(page: Page, task_number: int, task_value_url: str):
    print(f"[ETL] 3. Выбор типа задания {task_number} (value='{task_value_url}')...")

    try:
        if page.is_closed():
            print(f"[ETL] Ошибка: Страница была закрыта. Перезагружаем...")
            page.goto(MAIN_PAGE_URL, wait_until='domcontentloaded', timeout=60000)
            page.wait_for_timeout(2000)

        dropdown_found = False
        actual_selector = DROPDOWN_SELECTOR

        selectors_to_try = [
            DROPDOWN_SELECTOR,
            "select[name='tasktype']",
            "select#tasktype",
            "select.tasktype",
            "select",
        ]

        for selector in selectors_to_try:
            try:
                if page.locator(selector).count() > 0:
                    page.wait_for_selector(selector, state='visible', timeout=5000)
                    actual_selector = selector
                    dropdown_found = True
                    print(f"[ETL] Селектор найден: {selector}")
                    break
            except:
                continue

        if not dropdown_found:
            raise Exception("Не удалось найти выпадающий список на странице")

        try:
            available_options = page.evaluate("""
                (selector) => {
                    const select = document.querySelector(selector);
                    if (!select) return [];
                    return Array.from(select.options).map(opt => opt.value);
                }
            """, actual_selector)

            if task_value_url not in available_options:
                print(f"[ETL] ПРЕДУПРЕЖДЕНИЕ: Опция '{task_value_url}' недоступна для задания {task_number}. Доступны: {available_options}")
                print(f"[ETL] Пропускаем задание {task_number}.")
                return 0

            page.select_option(actual_selector, value=task_value_url, timeout=10000)
            print(f"[ETL] Выбрана опция: {task_value_url}")
        except Exception as e:
            print(f"[ETL] ОШИБКА при выборе опции '{task_value_url}' для задания {task_number}: {e}")
            print(f"[ETL] Пропускаем задание {task_number}.")
            return 0

        button_found = False
        button_selectors = [
            "input[type='button'][value='Найти все задачи']",
            "input[type='button'][value*='Найти все задачи']",
            "input[value='Найти все задачи']",
            "input[type='button']",
        ]

        for button_selector in button_selectors:
            try:
                button_locator = page.locator(button_selector)
                if button_locator.count() > 0:
                    if button_selector == "input[type='button']":
                        all_buttons = button_locator.all()
                        for btn in all_buttons:
                            try:
                                value = btn.get_attribute('value') or ''
                                if 'найти' in value.lower() and 'задач' in value.lower():
                                    btn.scroll_into_view_if_needed()
                                    btn.click()
                                    print(f"[ETL] Нажата кнопка поиска (найдена по value): {value}")
                                    button_found = True
                                    break
                            except:
                                continue
                        if button_found:
                            break
                    else:
                        button_locator.first.scroll_into_view_if_needed()
                        page.wait_for_selector(button_selector, state='visible', timeout=5000)
                        button_locator.first.click()
                        print(f"[ETL] Нажата кнопка поиска: {button_selector}")
                        button_found = True
                        break
            except Exception as e:
                continue

        if not button_found:
            raise Exception("Не удалось найти и нажать кнопку 'Найти все задачи'")

        page.wait_for_timeout(2000)  # Увеличиваем ожидание после нажатия кнопки

        try:
            page.wait_for_selector("table tbody tr", timeout=20000)
        except Exception as e:
            print(f"[ETL] Предупреждение: таблица не найдена за 20 сек: {e}")
            try:
                page.wait_for_selector("table tr", timeout=5000)
            except:
                pass
        
        try:
            page.wait_for_selector("div.task-text", timeout=5000, state='visible')
        except Exception:
            pass
        
        page.wait_for_timeout(1000)
        
        rows_count = page.locator("table tbody tr").count()
        print(f"[ETL] Найдено строк в таблице: {rows_count}")
        
        print(f"[ETL] Данные для задания {task_number} загружены.")

        try:
            print("[ETL] Быстрый режим: извлекаем задания через evaluate()...")
            items = page.evaluate("""
                () => {
                    const rows = document.querySelectorAll('table tbody tr');
                    const result = [];
                    rows.forEach(row => {
                        const taskIdCell = row.querySelector('td:first-child a');
                        const contentCell = row.querySelector('td:nth-child(2) div.task-text');
                        const detailsCell = row.querySelector('td:nth-child(2) span.details');
                        const fileLinks = row.querySelectorAll('td:nth-child(2) a[href*="/file/"]');
                        
                        if (!taskIdCell || !contentCell) return;
                        
                        const taskId = taskIdCell.getAttribute('href')?.match(/id=(\\d+)/)?.[1];
                        if (!taskId) return;
                        
                        const contentHtml = contentCell.innerHTML || '';
                        const details = detailsCell ? detailsCell.textContent.trim() : '';
                        
                        const files = [];
                        fileLinks.forEach(link => {
                            const href = link.getAttribute('href') || '';
                            const text = link.textContent.trim();
                            files.push({ href: href, text: text });
                        });
                        
                        // Извлекаем ответ, если он есть на странице
                        let answer = '';
                        const answerCell = row.querySelector('td:nth-child(2) .answer, td:nth-child(2) [class*="answer"], td:nth-child(2) [id*="answer"]');
                        if (answerCell) {
                            answer = answerCell.textContent.trim() || answerCell.innerText.trim();
                        }
                        // Также проверяем кнопку "Показать ответ"
                        const showAnswerBtn = row.querySelector('button[onclick*="answer"], button[onclick*="Ответ"], .show-answer, [class*="show-answer"]');
                        if (showAnswerBtn && !answer) {
                            // Пытаемся найти ответ рядом с кнопкой
                            const answerNearBtn = showAnswerBtn.closest('td')?.querySelector('.answer-text, [class*="answer"]');
                            if (answerNearBtn) {
                                answer = answerNearBtn.textContent.trim();
                            }
                        }
                        
                        result.push({
                            taskId: taskId,
                            contentHtml: contentHtml,
                            details: details,
                            files: files,
                            answer: answer
                        });
                    });
                    return result;
                }
            """)
            print(f"[ETL] Быстрый режим: получено {len(items)} записей.")

            def _full_url(href: str) -> str:
                if not href:
                    return href
                if href.startswith('http'):
                    return href
                if href.startswith('/'):
                    return f"{SITE_DOMAIN}{href}"
                return f"{SITE_DOMAIN}/{href}"

            pre_urls = []
            for idx, it in enumerate(items, 1):
                if it.get('taskId'):
                    pre_urls.append(f"{SITE_DOMAIN}/task?id={it['taskId']}")
            existing_by_url = {}
            if pre_urls:
                try:
                    existing_tasks = session.query(Tasks).filter(Tasks.source_url.in_(pre_urls)).all()
                    existing_by_url = {t.source_url: t for t in existing_tasks}
                except Exception as e:
                    print(f"[ETL] Предупреждение: не удалось выполнить пакетный запрос существующих задач: {e}")
                    existing_by_url = {}

            # Для заданий 19: загрузка троек (19, 20, 21) по task_group_id и старый формат (одно задание 19 по source_url)
            existing_by_group = {}
            existing_19_by_source = {}
            if task_number == 19 and pre_urls:
                try:
                    site_ids = [it.get('taskId') for it in items if it.get('taskId')]
                    if site_ids:
                        trio_tasks = session.query(Tasks).filter(
                            Tasks.task_group_id.in_(site_ids),
                            Tasks.task_number.in_([19, 20, 21])
                        ).all()
                        for t in trio_tasks:
                            gid = t.task_group_id
                            if gid not in existing_by_group:
                                existing_by_group[gid] = {}
                            existing_by_group[gid][t.task_number] = t
                    old_19 = session.query(Tasks).filter(Tasks.source_url.in_(pre_urls), Tasks.task_number == 19).all()
                    existing_19_by_source = {t.source_url: t for t in old_19}
                except Exception as e:
                    print(f"[ETL] Предупреждение: не удалось загрузить тройки 19-21: {e}")

            count_added = 0
            count_skipped = 0
            count_updated = 0
            new_tasks_bulk = []

            for idx, it in enumerate(items, 1):
                if not it.get('taskId'):
                    continue

                content_html = it.get('contentHtml') or ''
                if not content_html or len(content_html.strip()) < 10:
                    continue

                real_task_number = task_number
                content_html = clean_html_content(content_html, task_number=real_task_number)

                if not content_html or len(content_html.strip()) < 10:
                    continue

                attached_files = []
                for f in it.get('files', []):
                    href = f.get('href')
                    text = (f.get('text') or '').strip()
                    url = _full_url(href)
                    name = text if text else (href.split('/')[-1] if href else '')
                    if url:
                        attached_files.append({'name': name, 'url': url})
                attached_files_json = json.dumps(attached_files, ensure_ascii=False) if attached_files else None

                source_url = f"{SITE_DOMAIN}/task?id={it['taskId']}"
                
                answer = it.get('answer', '').strip()
                if not answer and it.get('taskId'):
                    try:
                        task_page_url = f"{SITE_DOMAIN}/task?id={it['taskId']}"
                        page.goto(task_page_url, wait_until='domcontentloaded', timeout=30000)
                        page.wait_for_timeout(1000)  # Небольшая задержка для загрузки
                        
                        answer_selectors = [
                            '.answer',
                            '[class*="answer"]',
                            '[id*="answer"]',
                            '.solution',
                            '[class*="solution"]',
                            'button[onclick*="answer"]',
                            'button[onclick*="Ответ"]'
                        ]
                        
                        for selector in answer_selectors:
                            try:
                                answer_elem = page.locator(selector).first
                                if answer_elem.count() > 0:
                                    answer_text = answer_elem.inner_text(timeout=2000)
                                    if answer_text and len(answer_text.strip()) > 0:
                                        answer = answer_text.strip()
                                        break
                            except:
                                continue
                        
                        if not answer:
                            try:
                                show_answer_btn = page.locator('button:has-text("Показать ответ"), button:has-text("показать ответ"), button[onclick*="answer"]').first
                                if show_answer_btn.count() > 0:
                                    show_answer_btn.click()
                                    page.wait_for_timeout(500)
                                    for selector in answer_selectors:
                                        try:
                                            answer_elem = page.locator(selector).first
                                            if answer_elem.count() > 0:
                                                answer_text = answer_elem.inner_text(timeout=2000)
                                                if answer_text and len(answer_text.strip()) > 0:
                                                    answer = answer_text.strip()
                                                    break
                                        except:
                                            continue
                            except:
                                pass
                        
                        page.goto(f"{MAIN_PAGE_URL}?tasktype={task_value_url}", wait_until='domcontentloaded', timeout=30000)
                        page.wait_for_timeout(500)
                    except Exception as e:
                        print(f"[ETL] Предупреждение: не удалось извлечь ответ для задания {it.get('taskId')}: {e}")

                # Задания 19–21: одна задача на источнике = три задания; контент режем по «Задание 20.» / «Задание 21.»
                if task_number == 19:
                    answer_lines = _parse_answer_19_21(answer)
                    content_19, content_20, content_21 = _split_content_19_21(content_html)
                    if not content_20 and not content_21:
                        content_20 = content_21 = content_html
                    elif not content_20:
                        content_20 = content_html
                    elif not content_21:
                        content_21 = content_html
                    group_id = str(it.get('taskId') or '')
                    group_tasks = existing_by_group.get(group_id, {})
                    old_single_19 = existing_19_by_source.get(source_url)
                    contents_by_num = {19: content_19, 20: content_20, 21: content_21}

                    if len(group_tasks) >= 3:
                        any_updated = False
                        for num in (19, 20, 21):
                            t = group_tasks.get(num)
                            if t:
                                part = contents_by_num.get(num) or content_html
                                if t.content_html != part:
                                    t.content_html = part
                                    t.last_scraped = moscow_now()
                                    any_updated = True
                                if t.attached_files != attached_files_json:
                                    t.attached_files = attached_files_json
                                    t.last_scraped = moscow_now()
                                    any_updated = True
                                ans = answer_lines[num - 19] if num - 19 < len(answer_lines) else ''
                                if ans and t.answer != ans:
                                    t.answer = ans
                                    t.last_scraped = moscow_now()
                                    any_updated = True
                        if any_updated:
                            count_updated += 1
                        else:
                            count_skipped += 1
                    elif old_single_19:
                        old_single_19.content_html = content_19
                        old_single_19.attached_files = attached_files_json
                        old_single_19.answer = answer_lines[0] if answer_lines else None
                        old_single_19.task_group_id = group_id
                        old_single_19.site_task_id = it.get('taskId')
                        old_single_19.last_scraped = moscow_now()
                        session.add(old_single_19)
                        count_updated += 1
                        for sub_num, ans in [(20, answer_lines[1] if len(answer_lines) > 1 else ''), (21, answer_lines[2] if len(answer_lines) > 2 else '')]:
                            new_tasks_bulk.append(Tasks(
                                task_number=sub_num,
                                task_group_id=group_id,
                                site_task_id=it.get('taskId'),
                                source_url=source_url,
                                content_html=contents_by_num.get(sub_num) or content_html,
                                answer=ans or None,
                                attached_files=attached_files_json,
                                last_scraped=moscow_now()
                            ))
                        count_added += 2
                    else:
                        for sub_num, ans in [(19, answer_lines[0] if answer_lines else ''), (20, answer_lines[1] if len(answer_lines) > 1 else ''), (21, answer_lines[2] if len(answer_lines) > 2 else '')]:
                            new_tasks_bulk.append(Tasks(
                                task_number=sub_num,
                                task_group_id=group_id,
                                site_task_id=it.get('taskId'),
                                source_url=source_url if sub_num == 19 else source_url,
                                content_html=contents_by_num.get(sub_num) or content_html,
                                answer=ans or None,
                                attached_files=attached_files_json,
                                last_scraped=moscow_now()
                            ))
                        count_added += 3
                    continue

                existing_task = existing_by_url.get(source_url)

                if existing_task:
                    updated = False
                    if existing_task.content_html != content_html:
                        existing_task.content_html = content_html
                        existing_task.last_scraped = moscow_now()
                        updated = True
                    if existing_task.attached_files != attached_files_json:
                        existing_task.attached_files = attached_files_json
                        existing_task.last_scraped = moscow_now()
                        updated = True
                    if answer and existing_task.answer != answer:
                        existing_task.answer = answer
                        existing_task.last_scraped = moscow_now()
                        updated = True
                    if it.get('taskId') and not existing_task.site_task_id:
                        existing_task.site_task_id = it.get('taskId')
                        updated = True
                    if updated:
                        count_updated += 1
                    else:
                        count_skipped += 1
                else:
                    new_tasks_bulk.append(Tasks(
                        task_number=real_task_number,
                        site_task_id=it.get('taskId'),
                        source_url=source_url,
                        content_html=content_html,
                        answer=answer if answer else None,
                        attached_files=attached_files_json,
                        last_scraped=moscow_now()
                    ))
                    count_added += 1

            if new_tasks_bulk:
                try:
                    session.bulk_save_objects(new_tasks_bulk)
                except Exception as e:
                    print(f"[ETL] Предупреждение: пакетная вставка не удалась, сохраняем по одной: {e}")
                    for obj in new_tasks_bulk:
                        session.add(obj)

            try:
                session.commit()
            except Exception as e:
                print(f"[ETL] ОШИБКА при сохранении (быстрый режим): {e}")
                session.rollback()

            print(f"[ETL] (FAST) Добавлено {count_added}, обновлено {count_updated}, пропущено {count_skipped} для типа {task_number}.")
            return count_added
        except Exception as fast_e:
            print(f"[ETL] КРИТИЧЕСКАЯ ОШИБКА: Быстрый режим не сработал для задания {task_number}: {fast_e}")
            import traceback
            traceback.print_exc()
            try:
                session.rollback()
            except Exception:
                pass
            return 0
    except Exception as e:
        print(f"[ETL] КРИТИЧЕСКАЯ ОШИБКА при обработке задания {task_number}: {e}")
        import traceback
        traceback.print_exc()
        try:
            session.rollback()
        except Exception:
            pass
        print(f"[ETL] Пропускаем задание {task_number} и продолжаем работу.")
        return 0

def run_parser():
    if not check_robots_txt():
        return

    print("[ETL] 2. Запуск 'стелс' Playwright в 'ВИДИМОМ' и 'МЕДЛЕННОМ' режиме...")

    stealth = Stealth()
    with stealth.use_sync(sync_playwright()) as p:

        browser = p.chromium.launch(headless=True)

        context = browser.new_context(user_agent=USER_AGENT)
        page = context.new_page()

        try:
            print(f"[ETL] Загрузка главной страницы: {MAIN_PAGE_URL}...")

            page.goto(MAIN_PAGE_URL, wait_until='domcontentloaded', timeout=60000)

            print("[ETL] Ожидание полного рендеринга страницы...")
            page.wait_for_timeout(3000)

            print("[ETL] Поиск выпадающего списка...")
            dropdown_found = False
            selectors_to_try = [
                DROPDOWN_SELECTOR,
                "select[name='tasktype']",
                "select#tasktype",
                "select.tasktype",
                "select",
            ]

            for selector in selectors_to_try:
                try:
                    if page.locator(selector).count() > 0:
                        page.wait_for_selector(selector, state='visible', timeout=10000)
                        print(f"[ETL] Селектор найден и видим: {selector}")
                        dropdown_found = True
                        break
                except Exception as e:
                    continue

            if not dropdown_found:
                print(f"[ETL] Отладочная информация:")
                print(f"[ETL] Текущий URL = {page.url}")
                try:
                    print(f"[ETL] Заголовок страницы: {page.title()}")
                except:
                    print("[ETL] Не удалось получить заголовок")

                try:
                    body_text = page.locator('body').inner_text()[:500] if page.locator('body').count() > 0 else "Не удалось получить текст"
                    print(f"[ETL] Первые 500 символов страницы: {body_text}")
                except:
                    print("[ETL] Не удалось получить текст страницы")

                raise Exception("Не удалось найти выпадающий список на странице")

            print("[ETL] Главная страница и селектор готовы.")

        except Exception as e:
            print(f"[ETL] КРИТИЧЕСКАЯ ОШИБКА: Не удалось загрузить главную страницу или найти селектор. {e}")
            print(f"[ETL] Тип ошибки: {type(e).__name__}")
            try:
                browser.close()
            except:
                pass
            return

        total_added = 0

        for task_num, task_value in TASKS_TO_SCRAPE.items():
            total_added += fetch_tasks(page, task_num, task_value)
            print(f"[ETL] Ожидание {CRAWL_DELAY_SEC} сек...")
            time.sleep(CRAWL_DELAY_SEC)

        browser.close()
        print(f"[ETL] --- Процесс парсинга завершен. Всего добавлено новых заданий: {total_added} ---")

if __name__ == "__main__":
    print("--- Запуск ETL-скрипта для заполнения базы данных (v9, Reinstall) ---")
    print(f"База данных: {db_path}")
    run_parser()
