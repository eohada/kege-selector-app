import os
import sys
import re
import json
from playwright.sync_api import sync_playwright, Page
from playwright_stealth import Stealth
from urllib.robotparser import RobotFileParser
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

def clean_html_content(html: str) -> str:
    if not html:
        return html

    html = re.sub(r'\(\s*[А-ЯЁ]\.\s*[А-ЯЁа-яё]+\s*\)', '', html)
    html = re.sub(r'\(\s*[А-ЯЁа-яё]+\s*\)', '', html)

    html = re.sub(r'\s*data-v-[a-f0-9]+="[^"]*"', '', html)

    html = re.sub(r'(<br\s*/?>[\s\n]*){3,}', '<br><br>', html, flags=re.IGNORECASE)

    html = re.sub(r'(<p>\s*</p>[\s\n]*){2,}', '', html, flags=re.IGNORECASE)

    html = re.sub(r'[ \t]+', ' ', html)

    lines = html.split('\n')
    cleaned_lines = [line.strip() for line in lines if line.strip()]
    html = '\n'.join(cleaned_lines)

    return html.strip()

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
            available_options = page.evaluate(, actual_selector)

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

        page.wait_for_timeout(800)

        page.wait_for_selector("table tbody tr", timeout=15000)
        try:
            page.wait_for_selector("div.task-text", timeout=5000, state='visible')
        except Exception:
            pass
        print(f"[ETL] Данные для задания {task_number} загружены.")

        try:
            print("[ETL] Быстрый режим: извлекаем задания через evaluate()...")
            items = page.evaluate(

            )
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

                content_html = clean_html_content(content_html)

                if not content_html or len(content_html.strip()) < 10:
                    continue

                real_task_number = task_number

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
