#!/usr/bin/env python3
"""
Парсер заданий ОГЭ по математике с math-oge.sdamgia.ru.
Сохраняет в data/oge_math_tasks.json.
Запуск: python scripts/scrape_oge_math.py
"""
import json
import os
import re
import time
import random
import requests
from bs4 import BeautifulSoup

BASE_URL = "https://math-oge.sdamgia.ru"
OUTPUT = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'oge_math_tasks.json')
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
    'Accept-Language': 'ru-RU,ru;q=0.9,en;q=0.8',
}
session = requests.Session()
session.headers.update(HEADERS)


def fetch(url, retries=5):
    """Таймаут: 15 с на подключение, 90 с на чтение (сайт может отвечать медленно)."""
    for attempt in range(retries):
        try:
            r = session.get(url, timeout=(15, 90))
            r.raise_for_status()
            return r.text
        except Exception as e:
            wait = 5 * (attempt + 1)
            print(f"  Retry {attempt+1}/{retries}: {e}. Ждём {wait} с...")
            time.sleep(wait)
    return None


def extract_task_from_problem_page(html, prob_id, task_num, base_url):
    """
    Со страницы problem?id=...&print=true достаём только УСЛОВИЕ (текст задания),
    без "Тип N №", "Источник", "Раздел кодификатора ФИПИ".
    """
    soup = BeautifulSoup(html, 'html.parser')
    content_html = ''
    answer = ''
    solution_html = ''

    ans_div = soup.find('div', class_='answer')
    if ans_div:
        answer = re.sub(r'^[Оо]твет:\s*', '', ans_div.get_text(strip=True)).strip()
    if not answer:
        for elem in soup.find_all(string=re.compile(r'[Оо]твет:\s*\S+')):
            s = elem.strip()
            if re.match(r'[Оо]твет:', s):
                answer = re.sub(r'^[Оо]твет:\s*', '', s).strip()
                break

    sol_div = soup.find('div', class_='solution')
    if sol_div:
        solution_html = str(sol_div)

    # Условие: берём pbody и вырезаем только текст задания (без Тип/Источник/ФИПИ/Решение/Ответ)
    pbody = soup.find('div', class_='pbody')
    if pbody:
        raw = str(pbody)
        # 1) Убрать всё начиная с "Решение." — решение и ответ внизу (учитываем мягкий перенос ­)
        raw = re.sub(r'Ре[\s\xad\u200b]*ш[еe\xad\u200b]*[\s\xad\u200b]*ни[еe\xad\u200b]*\s*\.?\s*.*', '', raw, flags=re.DOTALL | re.IGNORECASE)
        # 2) Убрать в начале до конца блока ФИПИ: "Тип N №" + "Источники" + "Раздел кодификатора ФИПИ ... </a>"
        raw = re.sub(r'^.*?Раздел\s+кодификатора\s+ФИПИ[^<]*<a\s[^>]*>.*?</a>\s*', '', raw, flags=re.DOTALL)
        # 3) Оставшиеся ссылки "Источник" / search?keywords — убрать
        raw = re.sub(r'<a\s+href="[^"]*search\?keywords[^"]*"[^>]*>.*?</a>', '', raw)
        raw = re.sub(r'<a\s+href="[^"]*test\?id=\d+[^"]*"[^>]*>.*?</a>', '', raw)
        raw = re.sub(r'Источник[иы]?\s*:.*?(?=<[pa]|$)', '', raw, flags=re.DOTALL)
        content_html = raw.strip() or ''
    if not content_html or len(content_html) < 30:
        # Fallback: первый достаточно большой блок с текстом, похожим на условие
        for div in soup.find_all(['div', 'p']):
            txt = div.get_text()
            if len(txt) > 60 and any(w in txt for w in ('укажите', 'найдите', 'выберите', 'Известно', 'Какое', 'Чему', 'Сколько')):
                if 'Источник:' not in txt[:150]:
                    content_html = str(div)
                    break
    content_html = content_html or f'<p>Задание {prob_id}</p>'

    return {
        'task_id': prob_id,
        'site_id': prob_id,
        'task_number': task_num,
        'source_url': f"{base_url}/problem?id={prob_id}",
        'content_html': content_html,
        'answer': answer,
        'solution_html': solution_html,
    }


def extract_task_ids_from_listing(html):
    """Со страницы категории (print=true) достаёт только пары (problem_id, task_number)."""
    soup = BeautifulSoup(html, 'html.parser')
    task_number_from_title = None
    for el in soup.find_all(['h2', 'h3', 'div', 'p']):
        m = re.search(r'Задания\s+(\d+)', el.get_text())
        if m:
            task_number_from_title = int(m.group(1))
            break

    ids_with_type = []
    for a in soup.find_all('a', href=re.compile(r'problem\?id=\d+')):
        href = a.get('href', '')
        mid = re.search(r'problem\?id=(\d+)', href)
        if not mid:
            continue
        prob_id = int(mid.group(1))
        text = a.get_text(strip=True)
        mtyp = re.search(r'Тип\s+(\d+)', text)
        task_num = int(mtyp.group(1)) if mtyp else task_number_from_title or 1
        ids_with_type.append((prob_id, task_num))

    seen = set()
    return [(pid, tn) for pid, tn in ids_with_type if pid not in seen and not seen.add(pid)]


def extract_tasks_from_print_page(html, base_url):
    """
    Список id заданий — со страницы категории. Само условие (текст задания) —
    всегда с отдельной страницы problem?id=XXX&print=true, чтобы подтянуть только условие.
    """
    pairs = extract_task_ids_from_listing(html)
    tasks = []
    for prob_id, task_num in pairs:
        # Всегда качаем страницу одного задания: там чётко можно вырезать только условие
        prob_html = fetch(f"{base_url}/problem?id={prob_id}&print=true")
        if prob_html:
            t = extract_task_from_problem_page(prob_html, prob_id, task_num, base_url)
            tasks.append(t)
        else:
            tasks.append({
                'task_id': prob_id,
                'site_id': prob_id,
                'task_number': task_num,
                'source_url': f"{base_url}/problem?id={prob_id}",
                'content_html': f'<p>Не удалось загрузить задание {prob_id}.</p>',
                'answer': '',
                'solution_html': '',
            })
        time.sleep(random.uniform(1.0, 2.5))
    return tasks


def scrape_category(category_id):
    url = f"{BASE_URL}/test?category_id={category_id}&filter=all&print=true"
    print(f"  Category {category_id}...")
    html = fetch(url)
    if not html:
        return []
    tasks = extract_tasks_from_print_page(html, BASE_URL)
    for t in tasks:
        t['task_number'] = t.get('task_number') or 1
    return tasks


def main():
    all_tasks = []
    seen_ids = set()
    # ОГЭ математика: номера заданий 1-25. На сайте категории могут идти не по порядку.
    # Пробуем category_id от 1 до 80 (с запасом)
    for cat_id in range(1, 81):
        tasks = scrape_category(cat_id)
        for t in tasks:
            if t['site_id'] not in seen_ids:
                seen_ids.add(t['site_id'])
                all_tasks.append(t)
        if tasks:
            print(f"    Got {len(tasks)} tasks")
        time.sleep(random.uniform(2.0, 4.0))

    os.makedirs(os.path.dirname(OUTPUT), exist_ok=True)
    with open(OUTPUT, 'w', encoding='utf-8') as f:
        json.dump(all_tasks, f, ensure_ascii=False, indent=2)

    by_num = {}
    for t in all_tasks:
        n = t['task_number']
        by_num[n] = by_num.get(n, 0) + 1
    print(f"\nTotal: {len(all_tasks)} tasks -> {OUTPUT}")
    for n in sorted(by_num):
        print(f"  Task {n}: {by_num[n]}")


if __name__ == '__main__':
    main()
