#!/usr/bin/env python3
"""
Парсер заданий ЕГЭ по математике (профиль) с math-ege.sdamgia.ru.
Для заданий с развёрнутым ответом (часть 2) сохраняет решение и критерии оценки.
Результат: data/ege_math_tasks.json

Запуск: python scripts/scrape_ege_math.py
"""
import json
import os
import re
import time
import random
import requests
from bs4 import BeautifulSoup

BASE_URL = "https://math-ege.sdamgia.ru"
OUTPUT = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'ege_math_tasks.json')
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
    'Accept-Language': 'ru-RU,ru;q=0.9,en;q=0.8',
}
session = requests.Session()
session.headers.update(HEADERS)


def fetch(url, retries=3):
    for attempt in range(retries):
        try:
            r = session.get(url, timeout=30)
            r.raise_for_status()
            return r.text
        except Exception as e:
            print(f"  Retry {attempt+1}/{retries}: {e}")
            time.sleep(2 * (attempt + 1))
    return None


def extract_tasks_from_print_page(html, base_url):
    """Парсит print-страницу: условие, ответ, решение, критерии."""
    soup = BeautifulSoup(html, 'html.parser')
    tasks = []
    task_number_from_title = None
    for el in soup.find_all(['h2', 'h3', 'div', 'p']):
        m = re.search(r'Тип\s+(\d+)|Задания?\s+(\d+)', el.get_text())
        if m:
            task_number_from_title = int(m.group(1) or m.group(2))
            break

    for a in soup.find_all('a', href=re.compile(r'problem\?id=\d+')):
        href = a.get('href', '')
        mid = re.search(r'problem\?id=(\d+)', href)
        if not mid:
            continue
        prob_id = int(mid.group(1))
        text = a.get_text(strip=True)
        mtyp = re.search(r'Тип\s+(\d+)', text)
        task_num = int(mtyp.group(1)) if mtyp else task_number_from_title or 1

        block = a.find_parent('div')
        content_html = ''
        answer = ''
        solution_html = ''
        criteria_html = ''
        for _ in range(8):
            if not block:
                break
            block = block.find_parent('div')
            if not block:
                break
            txt = block.get_text()
            html_str = str(block)
            if 'Критерии' in txt or 'балл' in txt.lower():
                criteria_html = html_str
            if 'Ре\u200bше\u200bние' in txt or 'Решение' in txt:
                solution_html = html_str
            if 'Ответ:' in txt or 'Ответ ' in txt:
                ma = re.search(r'[Оо]твет:\s*([^\n]+?)(?:\n|$|Критерии|Ре\u200bше\u200bние)', txt)
                if ma:
                    answer = ma.group(1).strip()
            if len(txt) > 150 and not content_html and 'Тип ' not in txt[:50]:
                content_html = html_str

        if not content_html:
            content_html = f'<p>Задание {prob_id}</p>'

        tasks.append({
            'task_id': prob_id,
            'site_id': prob_id,
            'task_number': task_num,
            'source_url': f"{base_url}/problem?id={prob_id}",
            'content_html': content_html,
            'answer': answer,
            'solution_html': solution_html,
            'criteria_html': criteria_html,
        })

    seen = set()
    unique = []
    for t in tasks:
        if t['site_id'] not in seen:
            seen.add(t['site_id'])
            unique.append(t)
    return unique


def fetch_problem_detail(prob_id, base_url):
    """Для заданий части 2 подтягиваем страницу задания: решение и критерии."""
    html = fetch(f"{base_url}/problem?id={prob_id}")
    if not html:
        return None, None
    soup = BeautifulSoup(html, 'html.parser')
    solution_html = ''
    criteria_html = ''
    sol = soup.find('div', class_='solution')
    if sol:
        solution_html = str(sol)
    for div in soup.find_all('div', class_=re.compile(r'criteria|solution')):
        if 'критери' in div.get_text().lower() or 'балл' in div.get_text().lower():
            criteria_html = str(div)
            break
    if not criteria_html:
        for table in soup.find_all('table'):
            if 'балл' in table.get_text().lower():
                criteria_html = str(table)
                break
    return solution_html or None, criteria_html or None


def scrape_theme(theme_id):
    url = f"{BASE_URL}/test?theme={theme_id}&print=true"
    html = fetch(url)
    if not html:
        return []
    tasks = extract_tasks_from_print_page(html, BASE_URL)
    # Для заданий 13-18 (развёрнутый ответ) подтягиваем решение и критерии со страницы задания
    for t in tasks:
        if t['task_number'] >= 13 and (not t.get('solution_html') or not t.get('criteria_html')):
            sol, crit = fetch_problem_detail(t['site_id'], BASE_URL)
            if sol:
                t['solution_html'] = sol
            if crit:
                t['criteria_html'] = crit
            time.sleep(random.uniform(0.4, 1.0))
    return tasks


def main():
    all_tasks = []
    seen_ids = set()
    # ЕГЭ профиль: задания 1-18. Темы на сайте — по номерам тем, не обязательно 1-18.
    # Перебираем theme от 1 до 350
    for theme_id in range(1, 351):
        tasks = scrape_theme(theme_id)
        for t in tasks:
            if t['site_id'] not in seen_ids:
                seen_ids.add(t['site_id'])
                all_tasks.append(t)
        if tasks:
            print(f"  Theme {theme_id}: {len(tasks)} tasks")
        time.sleep(random.uniform(0.5, 1.5))

    os.makedirs(os.path.dirname(OUTPUT), exist_ok=True)
    with open(OUTPUT, 'w', encoding='utf-8') as f:
        json.dump(all_tasks, f, ensure_ascii=False, indent=2)

    by_num = {}
    for t in all_tasks:
        n = t['task_number']
        by_num[n] = by_num.get(n, 0) + 1
    with_sol = sum(1 for t in all_tasks if t.get('solution_html'))
    with_crit = sum(1 for t in all_tasks if t.get('criteria_html'))
    print(f"\nTotal: {len(all_tasks)} tasks -> {OUTPUT}")
    print(f"  With solution: {with_sol}, with criteria: {with_crit}")
    for n in sorted(by_num):
        print(f"  Task {n}: {by_num[n]}")


if __name__ == '__main__':
    main()
