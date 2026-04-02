"""
Парсер kompege.ru → локальная SQLite data/keg_tasks.db (legacy).

Прод-синхронизация банка в основную БД приложения: scripts/sync_kege_informatics_bank.py
(whitelist источников, is_active, soft-delete, вложения).
"""
import os
import sys
import re
import json
import urllib.error
import urllib.request
from playwright.sync_api import sync_playwright, Page
from playwright_stealth import Stealth
from urllib.robotparser import RobotFileParser
from bs4 import BeautifulSoup
import time

SITE_DOMAIN = "https://kompege.ru"
MAIN_PAGE_URL = f"{SITE_DOMAIN}/task"
ROBOTS_URL = f"{SITE_DOMAIN}/robots.txt"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36"

KOMPEGE_API_LIST_URL_TMPL = f"{SITE_DOMAIN}/api/v1/task/number/{{}}"


def _kompege_api_listing_enabled() -> bool:
    v = (os.environ.get("KOMPEGE_USE_API") or "1").strip().lower()
    return v not in ("0", "false", "no", "off")


def fetch_kompege_listing_from_api(task_number: int) -> list:
    """
    Публичный JSON со списком заданий номера ЕГЭ (тот же источник, что SPA после «Найти все задачи»).
    Возвращает [] при ошибке сети/формата. Поля совместимы с upsert_kompege_listing_items.
    """
    if not _kompege_api_listing_enabled():
        return []
    url = KOMPEGE_API_LIST_URL_TMPL.format(int(task_number))
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            raw = resp.read()
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as e:
        print(f"[ETL] API списка заданий: ошибка запроса {url!r}: {e}")
        return []
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        print(f"[ETL] API списка заданий: невалидный JSON: {e}")
        return []
    if not isinstance(data, list):
        return []

    out: list = []
    for o in data:
        if not isinstance(o, dict):
            continue
        tid = o.get("taskId")
        if tid is None:
            continue
        task_id_str = str(int(tid)) if isinstance(tid, (int, float)) else str(tid).strip()
        if not task_id_str:
            continue

        files: list = []
        for f in o.get("files") or []:
            if not isinstance(f, dict):
                continue
            href = f.get("url") or f.get("href") or ""
            text = (f.get("name") or f.get("text") or "").strip()
            if href:
                files.append({"href": href, "text": text})

        details = (o.get("comment") or "").strip()

        if int(task_number) == 19:
            base = (o.get("text") or "").strip()
            subs = [st for st in (o.get("subTask") or []) if isinstance(st, dict)]
            subs.sort(key=lambda x: int(x.get("number") or 0))
            parts = [base]
            for st in subs:
                n = st.get("number")
                tx = (st.get("text") or "").strip()
                if n == 20:
                    parts.append("<p>Задание 20.</p>" + tx)
                elif n == 21:
                    parts.append("<p>Задание 21.</p>" + tx)
            content_html = "".join(parts)
            ans_parts = [str(o.get("key") or "").strip()]
            for st in subs:
                ans_parts.append(str(st.get("key") or "").strip())
            answer = "\n".join(x for x in ans_parts if x)
        else:
            content_html = (o.get("text") or "").strip()
            k = o.get("key")
            answer = str(k).strip() if k is not None else ""
            if not answer:
                answer = (o.get("solve_text") or "").strip()

        out.append(
            {
                "taskId": task_id_str,
                "contentHtml": content_html,
                "details": details,
                "files": files,
                "answer": answer,
            }
        )
    return out


# Скрипт для evaluate: строки таблицы заданий (главный документ или iframe).
KOMPEGE_LISTING_EXTRACT_JS = r"""
() => {
    const rows = document.querySelectorAll('table tbody tr');
    const result = [];
    rows.forEach(row => {
        const idLink = row.querySelector(
            'a[href*="task?id="], a[href*="/task?id="], a[href^="task?id="], a[href*="?id="], a[href*="/task/"]'
        );
        if (!idLink) return;
        const href = idLink.getAttribute('href') || '';
        let idMatch = href.match(/[?&]id=(\d+)/);
        if (!idMatch) idMatch = href.match(/\/task\/(\d+)/i);
        if (!idMatch) return;
        const taskId = idMatch[1];
        let contentCell = row.querySelector('div.task-text');
        if (!contentCell) {
            const tds = row.querySelectorAll('td');
            for (let i = 0; i < tds.length; i++) {
                const td = tds[i];
                const hasTaskLink = td.querySelector(
                    'a[href*="task?id="], a[href*="/task?id="], a[href*="?id="], a[href*="/task/"]'
                );
                const html = (td.innerHTML || '').trim();
                if (hasTaskLink && html.length > 40) {
                    contentCell = td;
                    break;
                }
            }
        }
        if (!contentCell) return;
        const detailsCell = row.querySelector('span.details');
        const fileLinks = row.querySelectorAll('a[href*="/file/"]');
        const contentHtml = (contentCell.innerHTML || '').trim();
        if (contentHtml.length < 10) return;
        const details = detailsCell ? detailsCell.textContent.trim() : '';
        const files = [];
        fileLinks.forEach(link => {
            const h = link.getAttribute('href') || '';
            const text = link.textContent.trim();
            files.push({ href: h, text: text });
        });
        let answer = '';
        const taskTd = contentCell.closest('td');
        if (taskTd) {
            const answerCell = taskTd.querySelector('.answer, [class*="answer"], [id*="answer"]');
            if (answerCell) {
                answer = (answerCell.textContent || answerCell.innerText || '').trim();
            }
        }
        if (!answer) {
            const ac = row.querySelector('.answer, [class*="answer"]');
            if (ac) answer = (ac.textContent || ac.innerText || '').trim();
        }
        const showAnswerBtn = row.querySelector(
            'button[onclick*="answer"], button[onclick*="Ответ"], .show-answer, [class*="show-answer"]'
        );
        if (showAnswerBtn && !answer) {
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
"""


def _extract_listing_items_from_frame(frame) -> list:
    return frame.evaluate(KOMPEGE_LISTING_EXTRACT_JS)


def _merge_listing_batches(merged: list, seen: set, batch: list) -> None:
    for it in batch or []:
        tid = str((it or {}).get("taskId") or "")
        if tid and tid not in seen:
            seen.add(tid)
            merged.append(it)


def _scroll_collect_listing_items(page: Page, frame, rows_count: int) -> list:
    """
    kompege.ru отрисовывает длинный список через виртуализацию: в DOM много пустых tr,
    ссылки и div.task-text появляются только у прокрученных во view строк.
    """
    if rows_count <= 0:
        return []
    merged: list = []
    seen: set = set()
    try:
        step = max(1, int(os.environ.get("KOMPEGE_LIST_SCROLL_STEP", "2")))
    except ValueError:
        step = 2

    _merge_listing_batches(merged, seen, _extract_listing_items_from_frame(frame))

    indices = list(range(0, rows_count, step))
    last = rows_count - 1
    if last >= 0 and last not in indices:
        indices.append(last)

    for idx in indices:
        try:
            frame.evaluate(
                """(idx) => {
                    const rows = document.querySelectorAll('table tbody tr');
                    if (idx < 0 || idx >= rows.length) return;
                    const r = rows[idx];
                    if (r) r.scrollIntoView({ block: 'center', inline: 'nearest' });
                }""",
                idx,
            )
        except Exception:
            continue
        page.wait_for_timeout(80)
        _merge_listing_batches(merged, seen, _extract_listing_items_from_frame(frame))

    # Прокрутка overflow-контейнера и окна — на случай если список привязан не к tr
    try:
        stagnant = 0
        for _ in range(48):
            prev_n = len(merged)
            frame.evaluate(
                r"""() => {
                    let el = document.querySelector('table');
                    while (el && el !== document.body) {
                        const y = getComputedStyle(el);
                        if ((y.overflowY === 'auto' || y.overflowY === 'scroll') &&
                            el.scrollHeight > el.clientHeight + 15) {
                            const step = Math.max(120, Math.floor(el.clientHeight * 0.88));
                            const maxS = el.scrollHeight - el.clientHeight;
                            el.scrollTop = Math.min(maxS, el.scrollTop + step);
                            return 1;
                        }
                        el = el.parentElement;
                    }
                    const sc = document.scrollingElement || document.documentElement;
                    const step = Math.max(120, Math.floor(sc.clientHeight * 0.88));
                    const maxS = sc.scrollHeight - sc.clientHeight;
                    sc.scrollTop = Math.min(maxS, sc.scrollTop + step);
                    return 0;
                }"""
            )
            page.wait_for_timeout(120)
            _merge_listing_batches(merged, seen, _extract_listing_items_from_frame(frame))
            if len(merged) == prev_n:
                stagnant += 1
            else:
                stagnant = 0
            at_bottom = frame.evaluate(
                r"""() => {
                    let el = document.querySelector('table');
                    while (el && el !== document.body) {
                        const y = getComputedStyle(el);
                        if ((y.overflowY === 'auto' || y.overflowY === 'scroll') &&
                            el.scrollHeight > el.clientHeight + 15) {
                            return el.scrollTop + el.clientHeight >= el.scrollHeight - 8;
                        }
                        el = el.parentElement;
                    }
                    const sc = document.scrollingElement || document.documentElement;
                    return sc.scrollTop + sc.clientHeight >= sc.scrollHeight - 8;
                }"""
            )
            if stagnant >= 5 and at_bottom:
                break
            if stagnant >= 14:
                break
    except Exception:
        pass

    if merged:
        print(
            f"[ETL] Виртуальный список: собрано {len(merged)} уникальных записей "
            f"(строк в таблице ≈{rows_count}, шаг индекса при прокрутке={step})."
        )
    return merged


def debug_kompege_listing_page(page: Page) -> None:
    """
    Диагностика DOM после «Найти все задачи»: фреймы, число tr, образец href, первые строки.
    Запуск: python scripts/sync_kege_informatics_bank.py --tasks 1 --debug-dom
    """
    print("[debug-dom] ========== kompege listing DOM ==========")
    for i, fr in enumerate(page.frames):
        try:
            info = fr.evaluate(
                r"""() => {
                const rows = document.querySelectorAll('table tbody tr');
                const r0 = rows[0];
                const links = [];
                document.querySelectorAll('a[href]').forEach((a, j) => {
                    if (j < 25) links.push(a.getAttribute('href'));
                });
                return {
                    tr: rows.length,
                    iframeN: document.querySelectorAll('iframe').length,
                    row0slice: r0 ? r0.outerHTML.slice(0, 4000) : '',
                    links25: links
                };
            }"""
            )
            url = getattr(fr, "url", "") or ""
            print(f"[debug-dom] frame[{i}] url={url[:160]!r}")
            print(f"  table tbody tr: {info.get('tr')}, iframe elements: {info.get('iframeN')}")
            print(f"  first 12 hrefs: {info.get('links25', [])[:12]}")
            rs = info.get("row0slice") or ""
            if rs:
                print(f"  first tr outerHTML (до 4000 симв.):\n{rs}")
        except Exception as e:
            print(f"[debug-dom] frame[{i}] error: {e}")
    print("[debug-dom] =========================================")


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


def collect_kompege_listing_raw_items(page: Page, task_number: int, task_value_url: str):
    """
    Список заданий номера ЕГЭ: сначала GET /api/v1/task/number/{N} (см. fetch_kompege_listing_from_api),
    иначе legacy — DOM на kompege.ru/task после выбора типа и «Найти все задачи».
    None — тип недоступен в списке (пропуск). Иначе список {taskId, contentHtml, details, files, answer}.
    Отключить API: переменная окружения KOMPEGE_USE_API=0.
    """
    api_items = fetch_kompege_listing_from_api(task_number)
    if api_items:
        print(
            f"[ETL] Список типа {task_number} загружен через API "
            f"({len(api_items)} записей): {KOMPEGE_API_LIST_URL_TMPL.format(task_number)}"
        )
        return api_items

    print(f"[ETL] 3. Выбор типа задания {task_number} (value='{task_value_url}')...")

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
        except Exception:
            continue
    if not dropdown_found:
        raise RuntimeError("Не удалось найти выпадающий список на странице")

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
            return None
        page.select_option(actual_selector, value=task_value_url, timeout=10000)
        print(f"[ETL] Выбрана опция: {task_value_url}")
    except Exception as e:
        print(f"[ETL] ОШИБКА при выборе опции '{task_value_url}' для задания {task_number}: {e}")
        print(f"[ETL] Пропускаем задание {task_number}.")
        return None

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
                    for btn in button_locator.all():
                        try:
                            value = btn.get_attribute('value') or ''
                            if 'найти' in value.lower() and 'задач' in value.lower():
                                btn.scroll_into_view_if_needed()
                                btn.click()
                                print(f"[ETL] Нажата кнопка поиска (найдена по value): {value}")
                                button_found = True
                                break
                        except Exception:
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
        except Exception:
            continue
    if not button_found:
        raise RuntimeError("Не удалось найти и нажать кнопку 'Найти все задачи'")

    page.wait_for_timeout(2000)
    try:
        page.wait_for_selector("table tbody tr", timeout=20000)
    except Exception as e:
        print(f"[ETL] Предупреждение: таблица не найдена за 20 сек: {e}")
        try:
            page.wait_for_selector("table tr", timeout=5000)
        except Exception:
            pass
    try:
        page.wait_for_selector("div.task-text", timeout=5000, state='visible')
    except Exception:
        pass
    page.wait_for_timeout(1000)
    rows_count = page.locator("table tbody tr").count()
    print(f"[ETL] Найдено строк в таблице: {rows_count}")
    print(f"[ETL] Данные для задания {task_number} загружены.")

    print("[ETL] Быстрый режим: извлекаем задания через evaluate()...")
    items = _extract_listing_items_from_frame(page.main_frame)
    if not items:
        for fr in page.frames:
            if fr == page.main_frame:
                continue
            try:
                alt = _extract_listing_items_from_frame(fr)
                if alt:
                    print(f"[ETL] Список заданий прочитан из iframe ({len(alt)} шт.): {getattr(fr, 'url', '')!r}")
                    items = alt
                    break
            except Exception:
                continue

    if not items and rows_count > 0:
        print(
            "[ETL] Пустой список при ненулевом числе tr — вероятна виртуализация таблицы; "
            "прокручиваем строки и контейнер..."
        )
        items = _scroll_collect_listing_items(page, page.main_frame, rows_count)

    if not items:
        for fr in page.frames:
            if fr == page.main_frame:
                continue
            try:
                rc = fr.evaluate(
                    "() => document.querySelectorAll('table tbody tr').length"
                )
                rc = int(rc or 0)
            except Exception:
                rc = 0
            if rc <= 0:
                continue
            try:
                alt = _scroll_collect_listing_items(page, fr, rc)
            except Exception:
                alt = []
            if alt:
                print(f"[ETL] Список после прокрутки iframe ({len(alt)} шт.): {getattr(fr, 'url', '')!r}")
                items = alt
                break

    print(f"[ETL] Быстрый режим: получено {len(items)} записей.")
    return items


def fetch_tasks(page: Page, task_number: int, task_value_url: str):
    try:
        items = collect_kompege_listing_raw_items(page, task_number, task_value_url)
        if items is None:
            return 0
        from scraper.kompege_upsert import upsert_kompege_listing_items

        added, upd, skip = upsert_kompege_listing_items(
            session,
            page,
            items,
            task_number,
            task_value_url,
            course_id=None,
            dry_run=False,
            apply_bank_flags=False,
        )
        print(f"[ETL] (FAST) Добавлено {added}, обновлено {upd}, пропущено {skip} для типа {task_number}.")
        return added
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
