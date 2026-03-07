#!/usr/bin/env python3
"""
Полуавтоматический ревьюер заданий с логированием принятых и удалённых.
Запуск:
    python scripts/review_tasks.py

В портативной сборке (exe): данные ищутся в папке рядом с exe.
Горячие клавиши:
    Right   -- принять и перейти к следующему
    Left    -- удалить и перейти к следующему
    Backspace -- отмена последнего действия
    S       -- пропустить (перейти дальше без пометки)
"""
import json
import os
import sys
import copy
import threading
import webbrowser
import time
from datetime import datetime
from flask import Flask, render_template_string, request, jsonify

# В портативной сборке (PyInstaller) данные — в папке с exe; иначе — корень проекта
if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DATA_FILE = os.path.join(BASE_DIR, 'tasks_export.json')
DELETED_LOG = os.path.join(BASE_DIR, 'tasks_deleted_log.json')
ACCEPTED_LOG = os.path.join(BASE_DIR, 'tasks_accepted_log.json')

app = Flask(__name__)

tasks_data: list[dict] = []
deleted_tasks: list[dict] = []
accepted_tasks: list[dict] = []
review_history: list[dict] = []


def load_data():
    global tasks_data, deleted_tasks, accepted_tasks
    with open(DATA_FILE, 'r', encoding='utf-8') as f:
        tasks_data = json.load(f)
    if os.path.exists(DELETED_LOG):
        with open(DELETED_LOG, 'r', encoding='utf-8') as f:
            deleted_tasks = json.load(f)
    if os.path.exists(ACCEPTED_LOG):
        with open(ACCEPTED_LOG, 'r', encoding='utf-8') as f:
            accepted_tasks = json.load(f)


def save_data():
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(tasks_data, f, ensure_ascii=False, indent=2)


def save_deleted_log():
    with open(DELETED_LOG, 'w', encoding='utf-8') as f:
        json.dump(deleted_tasks, f, ensure_ascii=False, indent=2)


def save_accepted_log():
    with open(ACCEPTED_LOG, 'w', encoding='utf-8') as f:
        json.dump(accepted_tasks, f, ensure_ascii=False, indent=2)


def get_filtered_tasks(task_number=None):
    if task_number is None:
        return tasks_data
    return [t for t in tasks_data if t['task_number'] == task_number]


def get_accepted_ids():
    return set(a['task_id'] for a in accepted_tasks)


HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Review Tasks</title>
<style>
  :root {
    --bg: #0f1117;
    --surface: #1a1d27;
    --surface2: #242836;
    --border: #2e3348;
    --text: #e4e6f0;
    --text-dim: #8b8fa8;
    --accent: #6c7bff;
    --green: #34d399;
    --red: #f87171;
    --orange: #fbbf24;
    --blue: #60a5fa;
  }
  * { margin:0; padding:0; box-sizing:border-box; }
  body {
    font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
    background: var(--bg);
    color: var(--text);
    min-height: 100vh;
  }
  .top-bar {
    background: var(--surface);
    border-bottom: 1px solid var(--border);
    padding: 12px 24px;
    display: flex;
    align-items: center;
    gap: 16px;
    flex-wrap: wrap;
    position: sticky;
    top: 0;
    z-index: 100;
  }
  .top-bar h1 { font-size: 18px; font-weight: 600; white-space: nowrap; }
  .filter-group {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-left: auto;
  }
  .filter-group label { font-size: 13px; color: var(--text-dim); }
  .filter-group select {
    background: var(--surface2);
    color: var(--text);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 6px 12px;
    font-size: 14px;
    cursor: pointer;
  }
  .stats-bar {
    background: var(--surface2);
    padding: 8px 24px;
    display: flex;
    align-items: center;
    gap: 20px;
    font-size: 13px;
    color: var(--text-dim);
    border-bottom: 1px solid var(--border);
    flex-wrap: wrap;
  }
  .stats-bar .num { color: var(--text); font-weight: 600; }
  .stats-bar .num-green { color: var(--green); font-weight: 600; }
  .stats-bar .num-red { color: var(--red); font-weight: 600; }
  .progress-wrap {
    flex: 1;
    max-width: 300px;
    height: 6px;
    background: var(--border);
    border-radius: 3px;
    overflow: hidden;
  }
  .progress-fill {
    height: 100%;
    background: var(--accent);
    border-radius: 3px;
    transition: width .3s;
  }
  .main-container {
    max-width: 960px;
    margin: 24px auto;
    padding: 0 24px;
  }
  .task-card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 12px;
    overflow: hidden;
  }
  .task-card.is-accepted {
    border-color: var(--green);
    box-shadow: 0 0 0 1px var(--green);
  }
  .task-header {
    padding: 16px 20px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    border-bottom: 1px solid var(--border);
    flex-wrap: wrap;
    gap: 8px;
  }
  .task-badge {
    background: var(--accent);
    color: #fff;
    font-size: 13px;
    font-weight: 600;
    padding: 4px 12px;
    border-radius: 20px;
  }
  .accepted-badge {
    background: #1c3b2a;
    color: var(--green);
    font-size: 12px;
    font-weight: 600;
    padding: 3px 10px;
    border-radius: 20px;
    border: 1px solid #285c3e;
  }
  .task-meta {
    font-size: 12px;
    color: var(--text-dim);
    display: flex;
    gap: 16px;
    flex-wrap: wrap;
  }
  .task-meta a { color: var(--accent); text-decoration: none; }
  .task-meta a:hover { text-decoration: underline; }
  .task-body {
    padding: 20px;
    font-size: 15px;
    line-height: 1.7;
    overflow-x: auto;
  }
  .task-body img {
    max-width: 100%;
    height: auto;
    border-radius: 6px;
    margin: 8px 0;
  }
  .task-body table { border-collapse: collapse; margin: 8px 0; }
  .task-body td, .task-body th {
    border: 1px solid var(--border);
    padding: 6px 10px;
    font-size: 14px;
  }
  .task-answer {
    padding: 12px 20px;
    border-top: 1px solid var(--border);
    font-size: 14px;
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .task-answer .label { color: var(--text-dim); }
  .task-answer .value {
    font-weight: 600;
    color: var(--green);
    font-family: 'Consolas', monospace;
    font-size: 16px;
  }
  .actions {
    display: flex;
    justify-content: center;
    gap: 16px;
    margin: 24px 0;
    flex-wrap: wrap;
  }
  .btn {
    padding: 14px 40px;
    font-size: 16px;
    font-weight: 600;
    border: none;
    border-radius: 10px;
    cursor: pointer;
    display: flex;
    align-items: center;
    gap: 8px;
    transition: transform .15s, box-shadow .15s;
  }
  .btn:hover { transform: translateY(-2px); }
  .btn:active { transform: translateY(0); }
  .btn-delete {
    background: #3b1c1c;
    color: var(--red);
    border: 1px solid #5c2828;
  }
  .btn-delete:hover { box-shadow: 0 4px 20px rgba(248,113,113,0.2); }
  .btn-accept {
    background: #1c3b2a;
    color: var(--green);
    border: 1px solid #285c3e;
  }
  .btn-accept:hover { box-shadow: 0 4px 20px rgba(52,211,153,0.2); }
  .btn-skip {
    background: #1c2a3b;
    color: var(--blue);
    border: 1px solid #283e5c;
    padding: 10px 24px;
    font-size: 14px;
  }
  .btn-skip:hover { box-shadow: 0 4px 20px rgba(96,165,250,0.2); }
  .btn-undo {
    background: var(--surface2);
    color: var(--text-dim);
    border: 1px solid var(--border);
    padding: 10px 20px;
    font-size: 13px;
  }
  .keyboard-hint {
    text-align: center;
    font-size: 12px;
    color: var(--text-dim);
    margin-bottom: 24px;
  }
  .keyboard-hint kbd {
    background: var(--surface2);
    border: 1px solid var(--border);
    border-radius: 4px;
    padding: 2px 8px;
    font-family: monospace;
    font-size: 12px;
    color: var(--text);
  }
  .empty-state {
    text-align: center;
    padding: 80px 20px;
    color: var(--text-dim);
    font-size: 18px;
  }
  .toast {
    position: fixed;
    bottom: 24px;
    left: 50%;
    transform: translateX(-50%) translateY(80px);
    padding: 12px 24px;
    border-radius: 10px;
    font-size: 14px;
    font-weight: 600;
    opacity: 0;
    transition: all .3s;
    z-index: 200;
    pointer-events: none;
  }
  .toast.show {
    transform: translateX(-50%) translateY(0);
    opacity: 1;
  }
  .toast-delete { background: #3b1c1c; color: var(--red); border: 1px solid #5c2828; }
  .toast-accept { background: #1c3b2a; color: var(--green); border: 1px solid #285c3e; }
  .toast-undo { background: var(--surface2); color: var(--orange); border: 1px solid var(--border); }
  .nav-counter {
    font-size: 14px;
    color: var(--text-dim);
    text-align: center;
    margin-bottom: 12px;
  }
</style>
</head>
<body>

<div class="top-bar">
  <h1>Review Tasks</h1>
  <div class="filter-group">
    <label>Tип:</label>
    <select id="taskFilter" onchange="changeFilter()">
      <option value="all" {% if not selected_number %}selected{% endif %}>
        Bce ({{ total_tasks }})
      </option>
      {% for num, count, acc, dlt in task_numbers %}
      <option value="{{ num }}" {% if selected_number == num %}selected{% endif %}>
        {{ num }} ({{ count }}) | +{{ acc }} -{{ dlt }}
      </option>
      {% endfor %}
    </select>
  </div>
</div>

<div class="stats-bar">
  <span>B файле: <span class="num">{{ total_tasks }}</span></span>
  <span>B фильтре: <span class="num">{{ filtered_count }}</span></span>
  <span>Принято: <span class="num-green">{{ accepted_count }}</span></span>
  <span>Удалено: <span class="num-red">{{ deleted_count }}</span></span>
  <div class="progress-wrap">
    <div class="progress-fill" id="progressBar" style="width: {{ progress_pct }}%"></div>
  </div>
  <span id="progressText">{{ current_pos + 1 }}/{{ filtered_count }}</span>
</div>

<div class="main-container">
  {% if task %}
  <div class="nav-counter">
    {{ current_pos + 1 }} / {{ filtered_count }}
    &nbsp; (task_id: {{ task.task_id }})
    {% if is_accepted %}
      <span style="color: var(--green); font-weight:600;">-- UZhE PRINYATO</span>
    {% endif %}
  </div>
  <div class="task-card {% if is_accepted %}is-accepted{% endif %}">
    <div class="task-header">
      <div style="display:flex; gap:8px; align-items:center;">
        <span class="task-badge">{{ task.task_number }}</span>
        {% if is_accepted %}<span class="accepted-badge">Accepted</span>{% endif %}
      </div>
      <div class="task-meta">
        <span>ID: {{ task.task_id }}</span>
        {% if task.site_task_id %}<span>Site: {{ task.site_task_id }}</span>{% endif %}
        {% if task.source_url %}<a href="{{ task.source_url }}" target="_blank">Source</a>{% endif %}
        {% if task.difficulty_level %}<span>Diff: {{ task.difficulty_level }}</span>{% endif %}
      </div>
    </div>
    <div class="task-body">
      {{ task.content_html | safe }}
    </div>
    {% if task.answer %}
    <div class="task-answer">
      <span class="label">Answer:</span>
      <span class="value">{{ task.answer }}</span>
    </div>
    {% endif %}
  </div>

  <div class="actions">
    <button class="btn btn-delete" onclick="doAction('delete')" title="Delete (Left)">
      X Удалить
    </button>
    <button class="btn btn-undo" onclick="doAction('undo')" title="Undo (Backspace)">
      Отмена
    </button>
    <button class="btn btn-skip" onclick="doAction('skip')" title="Skip (S)">
      Пропустить
    </button>
    <button class="btn btn-accept" onclick="doAction('accept')" title="Accept (Right)">
      Принять
    </button>
  </div>

  <div class="keyboard-hint">
    <kbd>Left</kbd> удалить &nbsp;&nbsp;
    <kbd>Right</kbd> принять &nbsp;&nbsp;
    <kbd>S</kbd> пропустить &nbsp;&nbsp;
    <kbd>Backspace</kbd> отмена
  </div>
  {% else %}
  <div class="empty-state">
    <p>Bce задания в этом фильтре просмотрены!</p>
    <p style="margin-top:12px; font-size:14px;">
      Выберите другой тип задания или закройте сервер.
    </p>
  </div>
  {% endif %}
</div>

<div class="toast toast-delete" id="toastDelete">Удалено</div>
<div class="toast toast-accept" id="toastAccept">Принято</div>
<div class="toast toast-undo" id="toastUndo">Отменено</div>

<script>
let busy = false;

function showToast(id) {
  const el = document.getElementById(id);
  el.classList.add('show');
  setTimeout(() => el.classList.remove('show'), 800);
}

function changeFilter() {
  const v = document.getElementById('taskFilter').value;
  window.location.href = '/?task_number=' + v + '&pos=0';
}

function getParams() {
  const p = new URLSearchParams(window.location.search);
  return {
    tn: p.get('task_number') || 'all',
    pos: parseInt(p.get('pos') || '0')
  };
}

async function doAction(action) {
  if (busy) return;
  busy = true;
  const {tn, pos} = getParams();

  if (action === 'skip') {
    window.location.href = '/?task_number=' + tn + '&pos=' + (pos + 1);
    return;
  }

  if (action === 'undo') {
    const resp = await fetch('/api/undo', {method: 'POST'});
    if (resp.ok) {
      showToast('toastUndo');
      setTimeout(() => {
        window.location.href = '/?task_number=' + tn + '&pos=' + Math.max(0, pos - 1);
      }, 250);
    }
    busy = false;
    return;
  }

  const resp = await fetch('/api/action', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({task_number: tn, pos: pos, action: action})
  });

  if (resp.ok) {
    if (action === 'delete') {
      showToast('toastDelete');
      setTimeout(() => {
        window.location.href = '/?task_number=' + tn + '&pos=' + pos;
      }, 250);
    } else {
      showToast('toastAccept');
      setTimeout(() => {
        window.location.href = '/?task_number=' + tn + '&pos=' + (pos + 1);
      }, 250);
    }
  }
  busy = false;
}

document.addEventListener('keydown', function(e) {
  if (e.target.tagName === 'SELECT') return;
  if (e.key === 'ArrowRight') { e.preventDefault(); doAction('accept'); }
  if (e.key === 'ArrowLeft')  { e.preventDefault(); doAction('delete'); }
  if (e.key === 'Backspace')  { e.preventDefault(); doAction('undo'); }
  if (e.key === 's' || e.key === 'S') { e.preventDefault(); doAction('skip'); }
});
</script>
</body>
</html>
"""


@app.route('/')
def index():
    task_number_param = request.args.get('task_number', 'all')
    pos = int(request.args.get('pos', 0))

    tn_filter = None if task_number_param == 'all' else int(task_number_param)
    filtered = get_filtered_tasks(tn_filter)

    nums = {}
    for t in tasks_data:
        n = t['task_number']
        nums[n] = nums.get(n, 0) + 1

    accepted_ids_by_num = {}
    for a in accepted_tasks:
        n = a['task_number']
        accepted_ids_by_num[n] = accepted_ids_by_num.get(n, 0) + 1

    deleted_ids_by_num = {}
    for d in deleted_tasks:
        n = d['task_number']
        deleted_ids_by_num[n] = deleted_ids_by_num.get(n, 0) + 1

    task_numbers = []
    for n in sorted(nums.keys()):
        task_numbers.append((n, nums[n], accepted_ids_by_num.get(n, 0), deleted_ids_by_num.get(n, 0)))

    if pos >= len(filtered):
        pos = len(filtered)
        current_task = None
        is_accepted = False
    else:
        current_task = filtered[pos]
        is_accepted = current_task['task_id'] in get_accepted_ids()

    progress_pct = round(pos / len(filtered) * 100, 1) if filtered else 0

    return render_template_string(
        HTML_TEMPLATE,
        task=current_task,
        is_accepted=is_accepted,
        total_tasks=len(tasks_data),
        filtered_count=len(filtered),
        accepted_count=len(accepted_tasks),
        deleted_count=len(deleted_tasks),
        current_pos=pos,
        progress_pct=progress_pct,
        task_numbers=task_numbers,
        selected_number=tn_filter,
    )


@app.route('/api/action', methods=['POST'])
def api_action():
    data = request.json
    tn_param = data.get('task_number', 'all')
    pos = int(data.get('pos', 0))
    action = data.get('action')

    tn_filter = None if tn_param == 'all' else int(tn_param)
    filtered = get_filtered_tasks(tn_filter)

    if pos >= len(filtered):
        return jsonify({'error': 'out of range'}), 400

    task = filtered[pos]
    task_id = task['task_id']

    if action == 'delete':
        review_history.append({
            'action': 'delete',
            'task': copy.deepcopy(task),
            'index_in_main': next(i for i, t in enumerate(tasks_data) if t['task_id'] == task_id)
        })

        tasks_data[:] = [t for t in tasks_data if t['task_id'] != task_id]

        deleted_tasks.append({
            'task_id': task['task_id'],
            'task_number': task['task_number'],
            'site_task_id': task.get('site_task_id'),
            'content_html': task.get('content_html', ''),
            'answer': task.get('answer'),
            'deleted_at': datetime.now().isoformat(),
        })

        save_data()
        save_deleted_log()
        return jsonify({'ok': True, 'remaining': len(tasks_data)})

    if action == 'accept':
        already = task_id in get_accepted_ids()
        if not already:
            accepted_tasks.append({
                'task_id': task['task_id'],
                'task_number': task['task_number'],
                'site_task_id': task.get('site_task_id'),
                'content_html': task.get('content_html', ''),
                'answer': task.get('answer'),
                'accepted_at': datetime.now().isoformat(),
            })
            save_accepted_log()

        review_history.append({
            'action': 'accept',
            'task_id': task_id,
            'was_new': not already,
        })

        return jsonify({'ok': True, 'accepted_total': len(accepted_tasks)})

    return jsonify({'error': 'unknown action'}), 400


@app.route('/api/undo', methods=['POST'])
def api_undo():
    if not review_history:
        return jsonify({'error': 'nothing to undo'}), 400

    last = review_history.pop()

    if last['action'] == 'delete':
        idx = min(last['index_in_main'], len(tasks_data))
        tasks_data.insert(idx, last['task'])

        tid = last['task']['task_id']
        deleted_tasks[:] = [d for d in deleted_tasks if d['task_id'] != tid]

        save_data()
        save_deleted_log()

    elif last['action'] == 'accept' and last.get('was_new'):
        tid = last['task_id']
        accepted_tasks[:] = [a for a in accepted_tasks if a['task_id'] != tid]
        save_accepted_log()

    return jsonify({'ok': True})


if __name__ == '__main__':
    if not os.path.exists(DATA_FILE):
        print("=" * 60)
        print("Файл с заданиями не найден!")
        print()
        print("Положи в эту же папку файл: tasks_export.json")
        print(f"Текущая папка: {BASE_DIR}")
        print("=" * 60)
        try:
            input("Нажми Enter, чтобы выйти...")
        except Exception:
            pass
        sys.exit(1)

    def open_browser():
        time.sleep(1.5)
        webbrowser.open('http://127.0.0.1:5050')

    threading.Thread(target=open_browser, daemon=True).start()

    load_data()
    print(f"Loaded {len(tasks_data)} tasks")
    print(f"Previously deleted: {len(deleted_tasks)}")
    print(f"Previously accepted: {len(accepted_tasks)}")
    print("\nОткроется браузер: http://127.0.0.1:5050")
    print("Стрелка вправо = принять | влево = удалить | S = пропустить | Backspace = отмена")
    app.run(host='127.0.0.1', port=5050, debug=False)
