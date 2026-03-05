#!/usr/bin/env python3
"""
Assign difficulty_level to every OGE Informatics task.

Strategy:
  1. Compute a numeric complexity_score per task using task-specific heuristics
  2. Within each task_number, split into easy/medium/hard by percentile
     (~33% each, adjusted for small groups)

FIPI 2026 baseline:
  Базовый (Б):     1,2,3,4,5,6,7,10,11,12
  Повышенный (П):  8,9,13
  Высокий (В):     14,15,16
"""

import json
import re
import os
import sys
import html as html_mod
from collections import defaultdict

sys.stdout.reconfigure(encoding='utf-8')

DATA_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'oge_inf_tasks.json')

with open(DATA_FILE, 'r', encoding='utf-8') as f:
    tasks = json.load(f)


def clean(h):
    t = re.sub(r'<[^>]+>', ' ', h or '')
    t = html_mod.unescape(t)
    t = re.sub(r'\s+', ' ', t).strip()
    return t.replace('\u00ad', '')


def rows(h):
    return len(re.findall(r'<tr', h or '', re.IGNORECASE))


def ans_len(t):
    a = str(t.get('answer', '') or '').strip()
    return len(a)


def ans_num(t):
    a = str(t.get('answer', '') or '').strip()
    try:
        return abs(int(a))
    except (ValueError, TypeError):
        return 0


def tlen(t):
    return len(clean(t.get('content_html', '')))


def cond_count(t):
    txt = clean(t.get('content_html', ''))
    kws = [r'\bИ\b', r'\bИЛИ\b', r'\bНЕ\b', r'∧', r'∨', r'¬']
    return sum(len(re.findall(k, txt)) for k in kws)


def graph_nodes(t):
    txt = clean(t.get('content_html', ''))
    m = re.findall(r'(?:города|пунктов?)\s+((?:[А-ЯA-Z],?\s*)+)', txt)
    if m:
        return len(re.findall(r'[А-ЯA-Z]', m[0]))
    return 6


# ─── Complexity score functions (return float 0..100) ──────────────────

def score_task1(t):
    """Кодирование. Differentiators: multi-step conversion, answer complexity."""
    txt = clean(t.get('content_html', ''))
    al = ans_len(t)
    has_conversion = bool(re.search(r'(Кбайт|Мбайт|килобайт|мегабайт)', txt, re.IGNORECASE))
    has_multi_step = bool(re.search(r'(сколько.*бит|байт.*символ|разрядн)', txt, re.IGNORECASE))
    score = 0
    score += min(len(txt) / 6, 30)
    score += min(al * 3, 20)
    if has_conversion: score += 20
    if has_multi_step: score += 15
    return score


def score_task2(t):
    """Декодирование. Differentiators: table complexity, answer length."""
    r = rows(t.get('content_html', ''))
    al = ans_len(t)
    txt = clean(t.get('content_html', ''))
    score = 0
    score += min(r * 8, 30)
    score += min(al * 5, 30)
    score += min(len(txt) / 10, 20)
    has_ambiguity = bool(re.search(r'(однозначн|единственн|неоднозначн)', txt, re.IGNORECASE))
    if has_ambiguity: score += 15
    return score


def score_task3(t):
    """Логика. Differentiators: condition count, variable count."""
    cc = cond_count(t)
    txt = clean(t.get('content_html', ''))
    vars_count = len(set(re.findall(r'\b[xXyYzZwW]\b', txt, re.IGNORECASE)))
    score = 0
    score += min(cc * 12, 40)
    score += min(vars_count * 8, 20)
    score += min(len(txt) / 8, 25)
    has_range = bool(re.search(r'(наибольш|наименьш|диапазон|отрезок)', txt, re.IGNORECASE))
    if has_range: score += 10
    return score


def score_task4(t):
    """Кратчайший путь / файловая система. Differentiators: table size, node count."""
    r = rows(t.get('content_html', ''))
    an = ans_num(t)
    txt = clean(t.get('content_html', ''))
    score = 0
    score += min(r * 5, 35)
    score += min(an * 2, 25)
    score += min(len(txt) / 10, 20)
    cities = len(re.findall(r'\b[А-ЯA-Z]\b', txt))
    score += min(cities * 1.5, 15)
    return score


def score_task5(t):
    """Алгоритм-исполнитель. Differentiators: number of commands, answer magnitude."""
    an = ans_num(t)
    txt = clean(t.get('content_html', ''))
    commands = len(re.findall(r'(прибавь|умножь|вычти|раздели|команд)', txt, re.IGNORECASE))
    score = 0
    score += min(an * 1.5, 30)
    score += min(commands * 6, 25)
    score += min(len(txt) / 12, 25)
    has_unknown = bool(re.search(r'(неизвестн|найдите\s+b|найдите\s+a)', txt, re.IGNORECASE))
    if has_unknown: score += 15
    return score


def score_task6(t):
    """Программа с условием. Differentiators: code structure, branching."""
    txt = clean(t.get('content_html', ''))
    h = t.get('content_html', '')
    branches = len(re.findall(r'(if\b|elif\b|else\b|если\b|иначе\b)', txt, re.IGNORECASE))
    vars_used = len(set(re.findall(r'\b([a-z])\b', txt)))
    an = ans_num(t)
    score = 0
    score += min(branches * 5, 30)
    score += min(vars_used * 4, 20)
    score += min(an * 2, 20)
    score += min(len(txt) / 20, 20)
    return score


def score_task7(t):
    """IP-адреса / URL. Differentiators: fragment ambiguity, text length."""
    txt = clean(t.get('content_html', ''))
    al = ans_len(t)
    digit_frags = re.findall(r'\d+', txt)
    score = 0
    score += min(len(digit_frags) * 2.5, 30)
    score += min(al * 4, 25)
    score += min(len(txt) / 8, 25)
    has_url = bool(re.search(r'(http|ftp|www|сервер)', txt, re.IGNORECASE))
    if has_url: score += 10
    return score


def score_task8(t):
    """Множества / поисковые запросы. Differentiators: query count, conditions."""
    cc = cond_count(t)
    r = rows(t.get('content_html', ''))
    txt = clean(t.get('content_html', ''))
    queries = len(re.findall(r'(запрос|страниц)', txt, re.IGNORECASE))
    an = ans_num(t)
    score = 0
    score += min(cc * 6, 25)
    score += min(r * 4, 20)
    score += min(queries * 3, 15)
    score += min(an / 100, 20)
    score += min(len(txt) / 15, 15)
    return score


def score_task9(t):
    """Графы — количество путей. Differentiators: node count, answer magnitude."""
    nodes = graph_nodes(t)
    an = ans_num(t)
    score = 0
    score += min(nodes * 5, 40)
    score += min(an * 1.2, 35)
    txt = clean(t.get('content_html', ''))
    score += min(len(txt) / 10, 15)
    return score


def score_task10(t):
    """Системы счисления. Differentiators: number length, base type, operations."""
    txt = clean(t.get('content_html', ''))
    al = ans_len(t)
    an = ans_num(t)
    score = 0
    score += min(al * 6, 30)
    score += min(an / 100, 20)
    has_arith = bool(re.search(r'(сложите|вычтите|сумм|разност|произвед)', txt, re.IGNORECASE))
    has_base8 = bool(re.search(r'(восьмерич|восьмеричн)', txt, re.IGNORECASE))
    has_base16 = bool(re.search(r'(шестнадцатерич)', txt, re.IGNORECASE))
    if has_arith: score += 25
    if has_base16: score += 10
    if has_base8: score += 5
    score += min(len(txt) / 10, 15)
    return score


def score_task11(t):
    """Поиск в файлах. Differentiators: specificity of search, multiple conditions."""
    txt = clean(t.get('content_html', ''))
    conditions = len(re.findall(r'(подкаталог|каталог|архив|расширени|размер)', txt, re.IGNORECASE))
    score = 0
    score += min(conditions * 8, 35)
    score += min(len(txt) / 8, 35)
    has_multi = bool(re.search(r'(и\s+при\s+этом|одновременно|оба\s+услови)', txt, re.IGNORECASE))
    if has_multi: score += 20
    return score


def score_task12(t):
    """Подсчёт файлов. Differentiators: number of conditions, file types."""
    txt = clean(t.get('content_html', ''))
    extensions = len(re.findall(r'\.\w{2,4}\b', txt))
    conditions = len(re.findall(r'(подкаталог|каталог|размер|объём|расширени)', txt, re.IGNORECASE))
    score = 0
    score += min(extensions * 8, 25)
    score += min(conditions * 6, 25)
    score += min(len(txt) / 6, 30)
    has_size = bool(re.search(r'(размер|объём|байт|Кбайт)', txt, re.IGNORECASE))
    if has_size: score += 15
    return score


def score_task13(t):
    """Презентация / документ. Differentiators: number of requirements, criteria count."""
    txt = clean(t.get('content_html', ''))
    criteria = len(re.findall(r'(\d\.\s|\d\)\s|—\s|•)', txt))
    slides = len(re.findall(r'(слайд)', txt, re.IGNORECASE))
    formatting = len(re.findall(r'(шрифт|размер|выравнив|отступ|интервал|маркир|нумерац)', txt, re.IGNORECASE))
    score = 0
    score += min(criteria * 4, 30)
    score += min(slides * 3, 15)
    score += min(formatting * 5, 25)
    score += min(len(txt) / 80, 20)
    return score


def score_task14(t):
    """Электронные таблицы. Differentiators: question count, formula complexity."""
    txt = clean(t.get('content_html', ''))
    r = rows(t.get('content_html', ''))
    questions = len(re.findall(r'(Определите|Найдите|Вычислите|Какой|Сколько|Каков)', txt, re.IGNORECASE))
    formulas = len(re.findall(r'(СУММ|СРЗНАЧ|СЧЁТ|МАКС|МИН|ЕСЛИ|SUM|AVG|COUNT|MAX|MIN|IF|формул)', txt, re.IGNORECASE))
    score = 0
    score += min(questions * 8, 30)
    score += min(r * 3, 20)
    score += min(formulas * 6, 20)
    score += min(len(txt) / 25, 20)
    return score


def score_task15(t):
    """Робот. Differentiators: grid size, command complexity, conditions."""
    txt = clean(t.get('content_html', ''))
    cmds = len(re.findall(r'(вверх|вниз|влево|вправо|закрасить)', txt, re.IGNORECASE))
    conditions = len(re.findall(r'(стена|свободн|условие|проверк)', txt, re.IGNORECASE))
    loops = len(re.findall(r'(цикл|пока|нц\b|кц\b)', txt, re.IGNORECASE))
    score = 0
    score += min(cmds * 1.5, 25)
    score += min(conditions * 3, 25)
    score += min(loops * 6, 25)
    score += min(len(txt) / 60, 20)
    return score


def score_task16(t):
    """Программирование. Differentiators: array ops, conditions, output complexity."""
    txt = clean(t.get('content_html', ''))
    has_array = bool(re.search(r'(массив|последовательност|чисел.*введ|введ.*чис)', txt, re.IGNORECASE))
    has_sort = bool(re.search(r'(сортиров|упорядоч|наибольш|наименьш)', txt, re.IGNORECASE))
    has_divisibility = bool(re.search(r'(делится|кратн|остаток|четн|нечетн)', txt, re.IGNORECASE))
    has_string = bool(re.search(r'(строк|символ|длин)', txt, re.IGNORECASE))
    conditions = len(re.findall(r'(и при этом|одновременно|или|и\s+заканчив|и\s+делит)', txt, re.IGNORECASE))
    score = 0
    if has_array: score += 15
    if has_sort: score += 15
    if has_divisibility: score += 10
    if has_string: score += 10
    score += min(conditions * 8, 25)
    score += min(len(txt) / 12, 20)
    return score


SCORE_FUNCS = {
    1: score_task1, 2: score_task2, 3: score_task3,
    4: score_task4, 5: score_task5, 6: score_task6,
    7: score_task7, 8: score_task8, 9: score_task9,
    10: score_task10, 11: score_task11, 12: score_task12,
    13: score_task13, 14: score_task14, 15: score_task15,
    16: score_task16,
}


def assign_by_percentile(group):
    """Split sorted group into ~33/33/33 easy/medium/hard."""
    n = len(group)
    if n <= 2:
        for item in group:
            item['task']['difficulty_level'] = 'medium'
        return

    group.sort(key=lambda x: x['score'])

    p33 = n // 3
    p66 = 2 * n // 3

    for i, item in enumerate(group):
        if i < p33:
            item['task']['difficulty_level'] = 'easy'
        elif i < p66:
            item['task']['difficulty_level'] = 'medium'
        else:
            item['task']['difficulty_level'] = 'hard'


# ─── Main ──────────────────────────────────────────────────────────────

def main():
    groups = defaultdict(list)

    for task in tasks:
        tn = task['task_number']
        func = SCORE_FUNCS.get(tn, lambda t: 50)
        s = func(task)
        groups[tn].append({'task': task, 'score': s})

    for tn in groups:
        assign_by_percentile(groups[tn])

    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(tasks, f, ensure_ascii=False, indent=2)

    stats = defaultdict(lambda: {'easy': 0, 'medium': 0, 'hard': 0, 'total': 0})
    for task in tasks:
        tn = task['task_number']
        d = task['difficulty_level']
        stats[tn][d] += 1
        stats[tn]['total'] += 1

    print(f"Обработано: {len(tasks)} заданий\n")
    print(f"{'#':>3} | {'ФИПИ':>5} | {'easy':>5} | {'med':>5} | {'hard':>5} | {'total':>5} | Визуал")
    print("-" * 75)

    fipi = {1:'Б',2:'Б',3:'Б',4:'Б',5:'Б',6:'Б',7:'Б',8:'П',9:'П',10:'Б',11:'Б',12:'Б',13:'П',14:'В',15:'В',16:'В'}
    totals = {'easy': 0, 'medium': 0, 'hard': 0}

    for tn in sorted(stats):
        s = stats[tn]
        pe = round(s['easy']/s['total']*100)
        pm = round(s['medium']/s['total']*100)
        ph = round(s['hard']/s['total']*100)
        bar = f"{'🟢'*(pe//10)}{'🟡'*(pm//10)}{'🔴'*(ph//10)}"
        print(f"{tn:>3} |   {fipi.get(tn,'?'):>3} | {s['easy']:>5} | {s['medium']:>5} | {s['hard']:>5} | {s['total']:>5} | {bar} {pe}/{pm}/{ph}%")
        totals['easy'] += s['easy']
        totals['medium'] += s['medium']
        totals['hard'] += s['hard']

    print("-" * 75)
    print(f"    |       | {totals['easy']:>5} | {totals['medium']:>5} | {totals['hard']:>5} | {len(tasks):>5} |")
    print(f"\nОбщее: easy={round(totals['easy']/len(tasks)*100)}% "
          f"medium={round(totals['medium']/len(tasks)*100)}% "
          f"hard={round(totals['hard']/len(tasks)*100)}%")

    print("\n=== Примеры (по 1 задачу каждого уровня для каждого номера) ===\n")
    for tn in sorted(stats):
        g = groups[tn]
        g.sort(key=lambda x: x['score'])
        for diff in ['easy', 'medium', 'hard']:
            ex = next((x for x in g if x['task']['difficulty_level'] == diff), None)
            if ex:
                txt = clean(ex['task'].get('content_html', ''))[:100]
                ans = ex['task'].get('answer', '-') or '-'
                print(f"  [{tn:>2}/{diff:>6}] score={ex['score']:.0f}  id={ex['task']['site_id']:<8}  ans={str(ans)[:12]:<13} {txt}...")


if __name__ == '__main__':
    main()
