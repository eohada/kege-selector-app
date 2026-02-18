#!/usr/bin/env python3
"""
Ре-парсинг ответов заданий 19–21: для каждого задания 19 без task_group_id
забираем блок ответа с kompege.ru, разбиваем на 3 строки (19, 20, 21), вырезаем код,
обновляем задание 19 и создаём задания 20 и 21 с тем же task_group_id.

Режимы (рекомендуемый способ — без «кривых» данных из БД):

  1) На сервере (без браузера): экспорт списка URL для парсинга:
       python scripts/reparse_task_19_21_answers.py --export-urls urls.json

  2) Локально (с Playwright: pip install playwright && playwright install):
       python scripts/reparse_task_19_21_answers.py --fetch urls.json -o answers.json

  3) На сервере: импорт готовых ответов в БД:
       python scripts/reparse_task_19_21_answers.py --import answers.json [--dry-run]

Прямой запуск (на сервере без Playwright ответы берутся из БД — могут быть кривые):
  python scripts/reparse_task_19_21_answers.py [--dry-run] [--limit N]
  python scripts/reparse_task_19_21_answers.py --no-playwright
"""
from __future__ import annotations

import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


def _strip_code_from_answer_line(line: str) -> str:
    if not line or not isinstance(line, str):
        return ''
    line = line.strip()
    line = re.sub(r'```[\s\S]*?```', '', line, flags=re.DOTALL)
    line = re.sub(r'`[^`]*`', '', line)
    code_indicators = re.compile(
        r'\b(def|import|from|class|return|print|for\s+\w+\s+in|if\s+.*:|\w+\s*=\s*[\[\{]|\#.*$)',
        re.IGNORECASE
    )
    if code_indicators.search(line) and not re.match(r'^[\d\s\-,\.]+$', line):
        return ''
    cleaned = re.sub(r'[^\d\s\-,\.]', ' ', line)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    return cleaned


def parse_answer_19_21(raw_answer: str) -> list:
    if not raw_answer or not isinstance(raw_answer, str):
        return ['', '', '']
    text = raw_answer.strip()
    text = re.sub(r'```[\s\S]*?```', '', text, flags=re.DOTALL)
    lines = [s.strip() for s in re.split(r'[\r\n]+', text) if s.strip()]
    result = ['', '', '']
    for i, line in enumerate(lines[:3]):
        result[i] = _strip_code_from_answer_line(line)
    return result


def fetch_answer_via_requests(url: str) -> str:
    """Получить блок ответа со страницы через requests + BeautifulSoup (без браузера)."""
    try:
        import requests
        from bs4 import BeautifulSoup
    except ImportError:
        return ''
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36'}
    try:
        r = requests.get(url, headers=headers, timeout=15)
        r.raise_for_status()
    except Exception:
        return ''
    soup = BeautifulSoup(r.text, 'html.parser')
    answer_text = ''
    for selector in ['.answer', '[class*="answer"]', '[id*="answer"]', '[class*="Answer"]']:
        for tag in soup.select(selector):
            t = (tag.get_text() or '').strip()
            if t and len(t) < 500 and re.search(r'\d', t):
                answer_text = t
                break
        if answer_text:
            break
    if not answer_text:
        for tag in soup.find_all(string=re.compile(r'Показать ответ', re.I)):
            parent = tag.parent
            if parent:
                next_sib = parent.find_next_sibling()
                if next_sib:
                    t = (next_sib.get_text() or '').strip()
                    if t and len(t) < 500:
                        answer_text = t
                        break
    return answer_text or ''


def get_answer_lines_for_task(task, answer_from_page: str) -> list:
    """
    Возвращает [answer_19, answer_20, answer_21].
    Если answer_from_page непустой — парсим его; иначе пробуем разбить существующий task.answer из БД.
    """
    if answer_from_page and answer_from_page.strip():
        return parse_answer_19_21(answer_from_page)
    existing = (task.answer or '').strip()
    if existing:
        return parse_answer_19_21(existing)
    return ['', '', '']


def fetch_answer_with_playwright(page, url: str) -> str:
    """Получить текст ответа со страницы через Playwright (с кликом «Показать ответ» при необходимости)."""
    try:
        page.goto(url, wait_until='domcontentloaded', timeout=20000)
        page.wait_for_timeout(1500)
        answer_text = ''
        for selector in ['.answer', '[class*="answer"]', '[id*="answer"]']:
            try:
                el = page.locator(selector).first
                if el.count() > 0:
                    answer_text = (el.inner_text(timeout=2000) or '').strip()
                    if answer_text:
                        return answer_text
            except Exception:
                continue
        try:
            btn = page.locator('button:has-text("Показать ответ"), button:has-text("показать ответ")').first
            if btn.count() > 0:
                btn.click()
                page.wait_for_timeout(800)
                for selector in ['.answer', '[class*="answer"]']:
                    try:
                        el = page.locator(selector).first
                        if el.count() > 0:
                            answer_text = (el.inner_text(timeout=2000) or '').strip()
                            if answer_text:
                                return answer_text
                    except Exception:
                        continue
        except Exception:
            pass
    except Exception:
        pass
    return ''


def run_export_urls(out_path: str, limit: int) -> int:
    """Экспорт списка заданий 19 (без task_group_id) в JSON для последующего --fetch. Запуск на сервере."""
    from app import create_app
    from app.models import Tasks
    app = create_app()
    with app.app_context():
        q = Tasks.query.filter(
            Tasks.task_number == 19,
            (Tasks.task_group_id.is_(None)) | (Tasks.task_group_id == ''),
        ).order_by(Tasks.task_id.asc())
        if limit:
            q = q.limit(limit)
        tasks = q.all()
        data = [
            {'task_id': t.task_id, 'source_url': (t.source_url or '').strip(), 'site_task_id': t.site_task_id or ''}
            for t in tasks
            if (t.source_url or '').strip() and 'kompege.ru' in (t.source_url or '')
        ]
        with open(out_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f'Экспортировано URL: {len(data)} -> {out_path}')
    return 0


def run_fetch(urls_path: str, out_path: str) -> int:
    """Локально: по JSON с URL открыть каждую страницу в Playwright, забрать ответ, сохранить в JSON. БД не нужна."""
    with open(urls_path, 'r', encoding='utf-8') as f:
        items = json.load(f)
    if not items:
        print('Список URL пуст.')
        return 0
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print('Установите Playwright: pip install playwright && playwright install', file=sys.stderr)
        return 1
    results = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_extra_http_headers({'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/118.0.0.0'})
        for i, row in enumerate(items):
            task_id = row.get('task_id')
            url = (row.get('source_url') or '').strip()
            if not url or not task_id:
                continue
            answer_text = fetch_answer_with_playwright(page, url)
            answer_lines = parse_answer_19_21(answer_text)
            results[str(task_id)] = answer_lines
            if (i + 1) % 10 == 0:
                print(f'  Обработано: {i + 1}/{len(items)}')
            time.sleep(0.4)
        browser.close()
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f'Сохранено ответов: {len(results)} -> {out_path}')
    return 0


def run_import(answers_path: str, dry_run: bool) -> int:
    """Импорт JSON с ответами в БД: обновить задание 19, создать 20 и 21. Запуск на сервере."""
    with open(answers_path, 'r', encoding='utf-8') as f:
        results = json.load(f)
    if not results:
        print('Файл ответов пуст.')
        return 0
    from app import create_app
    from app.models import db, Tasks
    app = create_app()
    updated = 0
    created = 0
    errors = 0
    with app.app_context():
        for task_id_str, answer_lines in results.items():
            try:
                task_id = int(task_id_str)
            except (TypeError, ValueError):
                continue
            try:
                task = Tasks.query.get(task_id)
                if not task or task.task_number != 19:
                    continue
                if not isinstance(answer_lines, list) or len(answer_lines) < 3:
                    answer_lines = answer_lines if isinstance(answer_lines, list) else []
                    answer_lines = (answer_lines + ['', '', ''])[:3]
                group_id = (task.site_task_id or str(task_id)).strip()
                if not group_id:
                    continue
                if dry_run:
                    print(f'task_id={task_id} group_id={group_id} answers: {answer_lines!r}')
                    updated += 1
                    continue
                task.answer = answer_lines[0] or None
                task.task_group_id = group_id
                db.session.add(task)
                updated += 1
                existing_20_21 = Tasks.query.filter(
                    Tasks.task_group_id == group_id,
                    Tasks.task_number.in_([20, 21])
                ).count()
                if existing_20_21 >= 2:
                    db.session.commit()
                    continue
                source_url = (task.source_url or '').strip()
                for sub_num, ans in [(20, answer_lines[1] if len(answer_lines) > 1 else ''), (21, answer_lines[2] if len(answer_lines) > 2 else '')]:
                    exists = Tasks.query.filter(Tasks.task_group_id == group_id, Tasks.task_number == sub_num).first()
                    if not exists:
                        new_task = Tasks(
                            task_number=sub_num,
                            task_group_id=group_id,
                            site_task_id=task.site_task_id,
                            source_url=source_url,
                            content_html=task.content_html or '',
                            answer=ans or None,
                            attached_files=task.attached_files,
                            last_scraped=task.last_scraped,
                        )
                        db.session.add(new_task)
                        created += 1
                db.session.commit()
                time.sleep(0.02)
            except Exception as e:
                print(f'task_id={task_id_str} error: {e}', file=sys.stderr)
                db.session.rollback()
                errors += 1
    print(f'Обновлено заданий 19: {updated}, создано 20/21: {created}, ошибок: {errors}')
    if dry_run:
        print('[dry-run] БД не изменялась.')
    return 0


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Ре-парсинг ответов 19–21 с источника')
    parser.add_argument('--dry-run', action='store_true', help='Не сохранять в БД (для --import и прямого режима)')
    parser.add_argument('--limit', type=int, default=0, help='Макс. число заданий 19 (0 = все), для --export-urls и прямого режима')
    parser.add_argument('--no-playwright', action='store_true', help='Только requests (для Docker без браузеров Playwright)')
    parser.add_argument('--export-urls', metavar='FILE', help='Экспорт списка URL в JSON (сервер, без браузера)')
    parser.add_argument('--fetch', metavar='URLS_JSON', help='Локально: по JSON с URL спарсить ответы через Playwright, результат в -o')
    parser.add_argument('-o', '--output', metavar='FILE', help='Выходной JSON с ответами (для --fetch)')
    parser.add_argument('--import', dest='import_file', metavar='ANSWERS_JSON', help='Импорт JSON с ответами в БД (сервер)')
    args = parser.parse_args()

    if args.export_urls:
        return run_export_urls(args.export_urls, args.limit or 0)
    if args.fetch:
        if not args.output:
            print('Укажите -o FILE для сохранения ответов (--fetch требует -o)', file=sys.stderr)
            return 1
        return run_fetch(args.fetch, args.output)
    if getattr(args, 'import_file', None):
        return run_import(args.import_file, getattr(args, 'dry_run', False))

    from app import create_app
    from app.models import db, Tasks

    app = create_app()
    with app.app_context():
        q = Tasks.query.filter(
            Tasks.task_number == 19,
            (Tasks.task_group_id.is_(None)) | (Tasks.task_group_id == ''),
        ).order_by(Tasks.task_id.asc())
        if args.limit:
            q = q.limit(args.limit)
        tasks_19 = q.all()

        if not tasks_19:
            print('Нет заданий 19 без task_group_id.')
            return 0

        use_playwright = not args.no_playwright
        playwright_page = None
        _pwr = None
        _browser = None
        if use_playwright:
            try:
                from playwright.sync_api import sync_playwright
                _pwr = sync_playwright().start()
                _browser = _pwr.chromium.launch(headless=True)
                playwright_page = _browser.new_page()
                playwright_page.set_extra_http_headers({'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/118.0.0.0'})
            except Exception as e:
                err_msg = str(e).lower()
                if 'executable' in err_msg or 'doesn\'t exist' in err_msg or 'browser' in err_msg:
                    print('Playwright: браузер не установлен. Запустите с --no-playwright (только requests) или в контейнере: playwright install chromium', file=sys.stderr)
                    use_playwright = False
                else:
                    raise

        updated = 0
        created = 0
        errors = 0
        used_db_fallback = 0

        for task in tasks_19:
            source_url = (task.source_url or '').strip()
            if not source_url or 'kompege.ru' not in source_url:
                continue
            group_id = (task.site_task_id or str(task.task_id) or '').strip()
            if not group_id:
                continue

            try:
                answer_text = fetch_answer_via_requests(source_url)
                if not answer_text and use_playwright and playwright_page:
                    try:
                        playwright_page.goto(source_url, wait_until='domcontentloaded', timeout=20000)
                        playwright_page.wait_for_timeout(1500)
                        for selector in ['.answer', '[class*="answer"]', '[id*="answer"]']:
                            try:
                                el = playwright_page.locator(selector).first
                                if el.count() > 0:
                                    answer_text = (el.inner_text(timeout=2000) or '').strip()
                                    if answer_text:
                                        break
                            except Exception:
                                continue
                        if not answer_text:
                            try:
                                btn = playwright_page.locator('button:has-text("Показать ответ"), button:has-text("показать ответ")').first
                                if btn.count() > 0:
                                    btn.click()
                                    playwright_page.wait_for_timeout(800)
                                    for selector in ['.answer', '[class*="answer"]']:
                                        try:
                                            el = playwright_page.locator(selector).first
                                            if el.count() > 0:
                                                answer_text = (el.inner_text(timeout=2000) or '').strip()
                                                if answer_text:
                                                    break
                                        except Exception:
                                            continue
                            except Exception:
                                pass
                    except Exception as e:
                        if 'Executable' in str(e) or "doesn't exist" in str(e):
                            use_playwright = False
                        else:
                            raise
                    time.sleep(0.4)

                answer_lines = get_answer_lines_for_task(task, answer_text)
                if not answer_text and any(answer_lines) and (task.answer or '').strip():
                    used_db_fallback += 1

                if args.dry_run:
                    print(f'task_id={task.task_id} group_id={group_id} answers: {answer_lines!r}')
                    updated += 1
                    continue

                task.answer = answer_lines[0] or None
                task.task_group_id = group_id
                db.session.add(task)
                updated += 1

                existing_20_21 = Tasks.query.filter(
                    Tasks.task_group_id == group_id,
                    Tasks.task_number.in_([20, 21])
                ).count()
                if existing_20_21 >= 2:
                    db.session.commit()
                    continue

                for sub_num, ans in [(20, answer_lines[1] if len(answer_lines) > 1 else ''), (21, answer_lines[2] if len(answer_lines) > 2 else '')]:
                    exists = Tasks.query.filter(Tasks.task_group_id == group_id, Tasks.task_number == sub_num).first()
                    if not exists:
                        new_task = Tasks(
                            task_number=sub_num,
                            task_group_id=group_id,
                            site_task_id=task.site_task_id,
                            source_url=source_url,
                            content_html=task.content_html or '',
                            answer=ans or None,
                            attached_files=task.attached_files,
                            last_scraped=task.last_scraped,
                        )
                        db.session.add(new_task)
                        created += 1

                db.session.commit()
            except Exception as e:
                print(f'task_id={task.task_id} error: {e}', file=sys.stderr)
                db.session.rollback()
                errors += 1

            time.sleep(0.3)

        if _browser:
            try:
                _browser.close()
            except Exception:
                pass
        if _pwr:
            try:
                _pwr.stop()
            except Exception:
                pass

        print(f'Обновлено заданий 19: {updated}, создано 20/21: {created}, ошибок: {errors}')
        if used_db_fallback:
            print(f'  (из них по ответу из БД, т.к. страница не отдала ответ: {used_db_fallback})')
        if not use_playwright and updated and used_db_fallback == 0 and not any(
            (t.answer or '').strip() for t in tasks_19[:10]
        ):
            print('  Подсказка: ответ на kompege.ru подгружается по кнопке. Без браузера (Playwright) можно использовать только ответ из БД. Установите в контейнере: playwright install chromium')
        if args.dry_run:
            print('[dry-run] БД не изменялась.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
