#!/usr/bin/env python3
"""
Scraper for OGE Informatics tasks from inf-oge.sdamgia.ru.
Collects all 16 task types into data/oge_inf_tasks.json.

Usage:
    python scripts/scrape_oge_inf.py
"""
import json
import os
import re
import time
import random
import requests
from bs4 import BeautifulSoup

BASE_URL = "https://inf-oge.sdamgia.ru"
OUTPUT = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'oge_inf_tasks.json')

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
    'Accept-Language': 'ru-RU,ru;q=0.9,en;q=0.8',
}

TASK_CATEGORIES = {
    1: [21, 33],
    2: [7, 36],
    3: [37, 31, 38],
    4: [3],
    5: [24, 40],
    6: [25],
    7: [41, 42, 17],
    8: [43, 26, 77],
    9: [44, 22],
    10: [45, 46],
    11: [27],
    12: [28],
    13: [30],
    14: [29],
    15: [78],
    16: [79],
}

session = requests.Session()
session.headers.update(HEADERS)


def fetch_page(url, retries=3):
    for attempt in range(retries):
        try:
            resp = session.get(url, timeout=30)
            resp.raise_for_status()
            return resp.text
        except Exception as e:
            print(f"  Retry {attempt+1}/{retries} for {url}: {e}")
            time.sleep(3 * (attempt + 1))
    return None


def extract_problem_ids(html):
    """Extract problem IDs from a category listing page."""
    soup = BeautifulSoup(html, 'html.parser')
    ids = set()
    for link in soup.find_all('a', href=True):
        href = link['href']
        m = re.search(r'problem\?id=(\d+)', href)
        if m:
            ids.add(int(m.group(1)))
    return sorted(ids)


def extract_task_from_problem_page(html, problem_id):
    """Extract task content from an individual problem page."""
    soup = BeautifulSoup(html, 'html.parser')

    task_data = {
        'site_id': problem_id,
        'source_url': f"{BASE_URL}/problem?id={problem_id}",
    }

    pbody = soup.find('div', class_='pbody')
    if not pbody:
        conds = soup.find_all('div', class_='condition_text')
        if conds:
            task_data['content_html'] = str(conds[0])
        else:
            return None
    else:
        cond = pbody.find('div', class_='condition_text')
        if cond:
            task_data['content_html'] = str(cond)
        else:
            task_data['content_html'] = str(pbody)

    answer_div = soup.find('div', class_='answer')
    if answer_div:
        answer_text = answer_div.get_text(strip=True)
        answer_text = re.sub(r'^[Оо]твет:\s*', '', answer_text)
        task_data['answer'] = answer_text.strip()

    solution_div = soup.find('div', class_='solution')
    if solution_div:
        task_data['solution_html'] = str(solution_div)

    return task_data


def extract_tasks_from_listing(html):
    """Extract tasks directly from a category listing page (they show inline)."""
    soup = BeautifulSoup(html, 'html.parser')
    tasks = []

    prob_blocks = soup.find_all('div', class_='prob_maindiv')
    if not prob_blocks:
        prob_blocks = soup.find_all('div', id=re.compile(r'^prob\d+'))

    for block in prob_blocks:
        prob_id = None
        id_attr = block.get('id', '')
        m = re.match(r'prob(\d+)', id_attr)
        if m:
            prob_id = int(m.group(1))

        if not prob_id:
            for link in block.find_all('a', href=True):
                m2 = re.search(r'problem\?id=(\d+)', link['href'])
                if m2:
                    prob_id = int(m2.group(1))
                    break

        if not prob_id:
            num_link = block.find('span', class_='prob_nums')
            if num_link:
                a = num_link.find('a')
                if a:
                    m3 = re.search(r'(\d+)', a.get_text())
                    if m3:
                        prob_id = int(m3.group(1))

        if not prob_id:
            continue

        task_data = {
            'site_id': prob_id,
            'source_url': f"{BASE_URL}/problem?id={prob_id}",
        }

        cond = block.find('div', class_='pbody')
        if cond:
            task_data['content_html'] = str(cond)
        else:
            task_data['content_html'] = str(block)

        ans_span = block.find('div', class_='answer')
        if not ans_span:
            noill = block.find('div', class_='noill')
            if noill:
                ans_text = noill.get_text()
                m_ans = re.search(r'[Оо]твет:\s*(.+?)(?:\.|$)', ans_text)
                if m_ans:
                    task_data['answer'] = m_ans.group(1).strip()
        else:
            ans_text = ans_span.get_text(strip=True)
            ans_text = re.sub(r'^[Оо]твет:\s*', '', ans_text)
            task_data['answer'] = ans_text.strip()

        sol = block.find('div', class_='solution')
        if sol:
            task_data['solution_html'] = str(sol)

        tasks.append(task_data)

    return tasks


def scrape_category(task_number, cat_id):
    """Scrape all tasks from a single category."""
    url = f"{BASE_URL}/test?filter=all&category_id={cat_id}&print=true"
    print(f"  Fetching category {cat_id} (task {task_number})...")

    html = fetch_page(url)
    if not html:
        print(f"  FAILED to fetch category {cat_id}")
        return []

    # Try extracting from listing page first
    tasks = extract_tasks_from_listing(html)

    if not tasks:
        # Fallback: get IDs and fetch individually
        ids = extract_problem_ids(html)
        print(f"    Found {len(ids)} problem IDs, fetching individually...")
        for pid in ids:
            prob_url = f"{BASE_URL}/problem?id={pid}"
            prob_html = fetch_page(prob_url)
            if prob_html:
                task = extract_task_from_problem_page(prob_html, pid)
                if task:
                    tasks.append(task)
            time.sleep(random.uniform(0.5, 1.5))
    else:
        # Parse answers from non-print version if needed
        tasks_without_answer = [t for t in tasks if not t.get('answer')]
        if tasks_without_answer:
            url_normal = f"{BASE_URL}/test?filter=all&category_id={cat_id}"
            html_normal = fetch_page(url_normal)
            if html_normal:
                normal_tasks = extract_tasks_from_listing(html_normal)
                ans_map = {t['site_id']: t.get('answer') for t in normal_tasks if t.get('answer')}
                for t in tasks:
                    if not t.get('answer') and t['site_id'] in ans_map:
                        t['answer'] = ans_map[t['site_id']]

    for t in tasks:
        t['task_number'] = task_number

    print(f"    Got {len(tasks)} tasks")
    return tasks


def main():
    all_tasks = []
    seen_ids = set()

    for task_number in sorted(TASK_CATEGORIES.keys()):
        cat_ids = TASK_CATEGORIES[task_number]
        print(f"\nTask {task_number} ({len(cat_ids)} categories)")

        for cat_id in cat_ids:
            tasks = scrape_category(task_number, cat_id)
            for t in tasks:
                if t['site_id'] not in seen_ids:
                    seen_ids.add(t['site_id'])
                    all_tasks.append(t)
            time.sleep(random.uniform(1.0, 2.5))

    os.makedirs(os.path.dirname(OUTPUT), exist_ok=True)
    with open(OUTPUT, 'w', encoding='utf-8') as f:
        json.dump(all_tasks, f, ensure_ascii=False, indent=2)

    by_num = {}
    for t in all_tasks:
        n = t['task_number']
        by_num[n] = by_num.get(n, 0) + 1

    print(f"\n{'='*50}")
    print(f"Total scraped: {len(all_tasks)} tasks")
    print(f"Saved to: {OUTPUT}")
    print(f"\nDistribution:")
    for n in sorted(by_num):
        has_ans = sum(1 for t in all_tasks if t['task_number'] == n and t.get('answer'))
        print(f"  Task {n:2d}: {by_num[n]:3d} tasks ({has_ans} with answers)")


if __name__ == '__main__':
    main()
