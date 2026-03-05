"""Extract clean Russian text from task 3 accepted/deleted and find distinguishing phrases."""
import json
import re

accepted = json.load(open('tasks_accepted_log.json', 'r', encoding='utf-8'))
deleted = json.load(open('tasks_deleted_log.json', 'r', encoding='utf-8'))

acc3 = [a for a in accepted if a['task_number'] == 3 and a.get('content_html')]
del3 = [d for d in deleted if d['task_number'] == 3 and d.get('content_html')]


def clean(html):
    t = re.sub(r'<[^>]+>', ' ', html)
    t = re.sub(r'data:image/[^\s"\']+', '', t)
    t = re.sub(r'&nbsp;', ' ', t)
    t = re.sub(r'&\w+;', ' ', t)
    t = re.sub(r'\s+', ' ', t).strip()
    return t


def find_phrases(text, phrases):
    found = []
    for p in phrases:
        if re.search(p, text, re.IGNORECASE):
            found.append(p)
    return found


test_phrases = [
    r'электронн\w*\s+таблиц',
    r'файл\w*\s+электронн',
    r'перемещени\w*\s+автомобил',
    r'автомобил\w+',
    r'транспортн\w+',
    r'температур',
    r'метеоролог',
    r'населённ\w*\s+пункт\w*\s+\w*\s*расстояни',
    r'расстояни\w*\s+\w*\s*населённ',
    r'три\s+поля',
    r'три\s+столбц',
    r'каждая\s+запись',
    r'товар',
    r'продукци',
    r'учени[кц]',
    r'результат\w*\s+\w*\s*экзамен',
    r'олимпиад',
    r'парковк',
    r'стоимост\w+\s+поездк',
    r'определите\s+значение',
]

with open('_task3_analysis.txt', 'w', encoding='utf-8') as out:
    out.write(f"Task 3: accepted={len(acc3)}, deleted={len(del3)}\n\n")

    out.write("=" * 100 + "\n")
    out.write("ACCEPTED TEXTS\n")
    out.write("=" * 100 + "\n\n")
    for i, a in enumerate(acc3):
        text = clean(a['content_html'])
        phrases = find_phrases(text, test_phrases)
        out.write(f"--- ACC #{i+1} id={a['task_id']} ans={a.get('answer','')} ---\n")
        out.write(f"PHRASES: {phrases}\n")
        out.write(f"{text[:600]}\n\n")

    out.write("=" * 100 + "\n")
    out.write("DELETED TEXTS\n")
    out.write("=" * 100 + "\n\n")
    for i, d in enumerate(del3):
        text = clean(d['content_html'])
        phrases = find_phrases(text, test_phrases)
        out.write(f"--- DEL #{i+1} id={d['task_id']} ans={d.get('answer','')} ---\n")
        out.write(f"PHRASES: {phrases}\n")
        out.write(f"{text[:600]}\n\n")

    # Summary
    out.write("=" * 100 + "\n")
    out.write("PHRASE FREQUENCY\n")
    out.write("=" * 100 + "\n\n")
    for p in test_phrases:
        acc_cnt = sum(1 for a in acc3 if re.search(p, clean(a['content_html']), re.IGNORECASE))
        del_cnt = sum(1 for d in del3 if re.search(p, clean(d['content_html']), re.IGNORECASE))
        acc_pct = acc_cnt / len(acc3) * 100 if acc3 else 0
        del_pct = del_cnt / len(del3) * 100 if del3 else 0
        marker = " <<<" if abs(acc_pct - del_pct) > 25 else ""
        out.write(f"  {p:50s}  acc={acc_pct:5.1f}% ({acc_cnt:2d}/{len(acc3)})  del={del_pct:5.1f}% ({del_cnt:2d}/{len(del3)}){marker}\n")

print("Written to _task3_analysis.txt")
