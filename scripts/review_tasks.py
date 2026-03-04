#!/usr/bin/env python3
"""
Полуавтоматический ревьюер заданий.
Запуск:
    pip install flask
    python scripts/review_tasks.py

Откроется http://127.0.0.1:5050
Горячие клавиши:
    → (Right)  — оставить и перейти к следующему
    ← (Left)   — удалить и перейти к следующему
    Backspace   — вернуться к предыдущему (отмена последнего действия)
"""
import json
import os
import sys
import copy
from datetime import datetime
from flask import Flask, render_template_string, request, jsonify, redirect, url_for

DATA_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'tasks_export.json')
DELETED_LOG = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'tasks_deleted_log.json')

app = Flask(__name__)

tasks_data: list[dict] = []
deleted_tasks: list[dict] = []
review_history: list[dict] = []  # для undo

def load_data():
    global tasks_data, deleted_tasks
    with open(DATA_FILE, 'r', encoding='utf-8') as f:
        tasks_data = json.load(f)
    if os.path.exists(DELETED_LOG):
        with open(DELETED_LOG, 'r', encoding='utf-8') as f:
            deleted_tasks = json.load(f)

def save_data():
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(tasks_data, f, ensure_ascii=False, indent=2)

def save_deleted_log():
    with open(DELETED_LOG, 'w', encoding='utf-8') as f:
        json.dump(deleted_tasks, f, ensure_ascii=False, indent=2)

def get_task_numbers():
    nums = sorted(set(t['task_number'] for t in tasks_data))
    return nums

def get_filtered_tasks(task_number=None):
    if task_number is None:
        return tasks_data
    return [t for t in tasks_data if t['task_number'] == task_number]

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Ревьюер заданий</title>
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
  .top-bar h1 {
    font-size: 18px;
    font-weight: 600;
    white-space: nowrap;
  }
  .filter-group {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-left: auto;
  }
  .filter-group label {
    font-size: 13px;
    color: var(--text-dim);
  }
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
    gap: 24px;
    font-size: 13px;
    color: var(--text-dim);
    border-bottom: 1px solid var(--border);
  }
  .stats-bar .num { color: var(--text); font-weight: 600; }
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
  .task-body table {
    border-collapse: collapse;
    margin: 8px 0;
  }
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
  .btn-keep {
    background: #1c3b2a;
    color: var(--green);
    border: 1px solid #285c3e;
  }
  .btn-keep:hover { box-shadow: 0 4px 20px rgba(52,211,153,0.2); }
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
  .toast-keep { background: #1c3b2a; color: var(--green); border: 1px solid #285c3e; }
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
  <h1>Ревьюер заданий</h1>
  <div class="filter-group">
    <label>Тип задания:</label>
    <select id="taskFilter" onchange="changeFilter()">
      <option value="all" {% if not selected_number %}selected{% endif %}>Все ({{ total_tasks }})</option>
      {% for num, count in task_numbers %}
      <option value="{{ num }}" {% if selected_number == num %}selected{% endif %}>
        Задание {{ num }} ({{ count }})
      </option>
      {% endfor %}
    </select>
  </div>
</div>

<div class="stats-bar">
  <span>Всего: <span class="num">{{ total_tasks }}</span></span>
  <span>В фильтре: <span class="num">{{ filtered_count }}</span></span>
  <span>Удалено за сессию: <span class="num" id="deletedCount">{{ deleted_count }}</span></span>
  <div class="progress-wrap">
    <div class="progress-fill" id="progressBar" style="width: {{ progress_pct }}%"></div>
  </div>
  <span id="progressText">{{ current_pos + 1 }}/{{ filtered_count }}</span>
</div>

<div class="main-container">
  {% if task %}
  <div class="nav-counter">
    Задание {{ current_pos + 1 }} из {{ filtered_count }}
    (task_id: {{ task.task_id }})
  </div>
  <div class="task-card">
    <div class="task-header">
      <span class="task-badge">Задание {{ task.task_number }}</span>
      <div class="task-meta">
        <span>ID: {{ task.task_id }}</span>
        {% if task.site_task_id %}<span>Site ID: {{ task.site_task_id }}</span>{% endif %}
        {% if task.source_url %}<a href="{{ task.source_url }}" target="_blank">Источник ↗</a>{% endif %}
        {% if task.difficulty_level %}<span>Сложность: {{ task.difficulty_level }}</span>{% endif %}
      </div>
    </div>
    <div class="task-body">
      {{ task.content_html | safe }}
    </div>
    {% if task.answer %}
    <div class="task-answer">
      <span class="label">Ответ:</span>
      <span class="value">{{ task.answer }}</span>
    </div>
    {% endif %}
  </div>

  <div class="actions">
    <button class="btn btn-delete" onclick="deleteTask()" title="Удалить (←)">
      ✕ Удалить
    </button>
    <button class="btn btn-undo" onclick="undoLast()" title="Отмена (Backspace)">
      ↩ Отмена
    </button>
    <button class="btn btn-keep" onclick="keepTask()" title="Оставить (→)">
      ✓ Оставить
    </button>
  </div>

  <div class="keyboard-hint">
    <kbd>←</kbd> удалить &nbsp;&nbsp;
    <kbd>→</kbd> оставить &nbsp;&nbsp;
    <kbd>Backspace</kbd> отмена
  </div>
  {% else %}
  <div class="empty-state">
    <p>Все задания в этом фильтре просмотрены!</p>
    <p style="margin-top:12px; font-size:14px;">
      Выберите другой тип задания или закройте сервер.
    </p>
  </div>
  {% endif %}
</div>

<div class="toast toast-delete" id="toastDelete">Задание удалено</div>
<div class="toast toast-keep" id="toastKeep">Задание оставлено</div>
<div class="toast toast-undo" id="toastUndo">Действие отменено</div>

<script>
let busy = false;

function showToast(id) {
  const el = document.getElementById(id);
  el.classList.add('show');
  setTimeout(() => el.classList.remove('show'), 1200);
}

function changeFilter() {
  const v = document.getElementById('taskFilter').value;
  window.location.href = '/?task_number=' + v + '&pos=0';
}

async function deleteTask() {
  if (busy) return;
  busy = true;
  const params = new URLSearchParams(window.location.search);
  const tn = params.get('task_number') || 'all';
  const pos = parseInt(params.get('pos') || '0');

  const resp = await fetch('/api/delete', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({task_number: tn, pos: pos})
  });
  if (resp.ok) {
    showToast('toastDelete');
    setTimeout(() => {
      window.location.href = '/?task_number=' + tn + '&pos=' + pos;
    }, 300);
  }
  busy = false;
}

async function keepTask() {
  if (busy) return;
  busy = true;
  const params = new URLSearchParams(window.location.search);
  const tn = params.get('task_number') || 'all';
  const pos = parseInt(params.get('pos') || '0');

  showToast('toastKeep');
  setTimeout(() => {
    window.location.href = '/?task_number=' + tn + '&pos=' + (pos + 1);
  }, 200);
  busy = false;
}

async function undoLast() {
  if (busy) return;
  busy = true;
  const resp = await fetch('/api/undo', {method: 'POST'});
  if (resp.ok) {
    const data = await resp.json();
    showToast('toastUndo');
    const params = new URLSearchParams(window.location.search);
    const tn = params.get('task_number') || 'all';
    const pos = parseInt(params.get('pos') || '0');
    setTimeout(() => {
      window.location.href = '/?task_number=' + tn + '&pos=' + Math.max(0, pos - 1);
    }, 300);
  }
  busy = false;
}

document.addEventListener('keydown', function(e) {
  if (e.key === 'ArrowRight') { e.preventDefault(); keepTask(); }
  if (e.key === 'ArrowLeft') { e.preventDefault(); deleteTask(); }
  if (e.key === 'Backspace') { e.preventDefault(); undoLast(); }
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
    task_numbers = sorted(nums.items())

    if pos >= len(filtered):
        pos = len(filtered)
        current_task = None
    else:
        current_task = filtered[pos]

    progress_pct = 0
    if filtered:
        progress_pct = round(pos / len(filtered) * 100, 1)

    return render_template_string(
        HTML_TEMPLATE,
        task=current_task,
        total_tasks=len(tasks_data),
        filtered_count=len(filtered),
        deleted_count=len(deleted_tasks),
        current_pos=pos,
        progress_pct=progress_pct,
        task_numbers=task_numbers,
        selected_number=tn_filter,
    )


@app.route('/api/delete', methods=['POST'])
def api_delete():
    data = request.json
    tn_param = data.get('task_number', 'all')
    pos = int(data.get('pos', 0))

    tn_filter = None if tn_param == 'all' else int(tn_param)
    filtered = get_filtered_tasks(tn_filter)

    if pos >= len(filtered):
        return jsonify({'error': 'out of range'}), 400

    task_to_delete = filtered[pos]
    task_id = task_to_delete['task_id']

    review_history.append({
        'action': 'delete',
        'task': copy.deepcopy(task_to_delete),
        'index_in_main': next(i for i, t in enumerate(tasks_data) if t['task_id'] == task_id)
    })

    tasks_data[:] = [t for t in tasks_data if t['task_id'] != task_id]

    deleted_tasks.append({
        'task_id': task_to_delete['task_id'],
        'task_number': task_to_delete['task_number'],
        'site_task_id': task_to_delete.get('site_task_id'),
        'deleted_at': datetime.now().isoformat(),
    })

    save_data()
    save_deleted_log()

    return jsonify({'ok': True, 'remaining': len(tasks_data)})


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

    return jsonify({'ok': True, 'remaining': len(tasks_data)})


if __name__ == '__main__':
    if not os.path.exists(DATA_FILE):
        print(f"Файл {DATA_FILE} не найден!")
        sys.exit(1)

    load_data()
    print(f"Загружено {len(tasks_data)} заданий")
    print(f"Ранее удалено: {len(deleted_tasks)}")
    print(f"\nОткрой в браузере: http://127.0.0.1:5050")
    print(f"Горячие клавиши: → оставить | ← удалить | Backspace отмена")
    app.run(host='127.0.0.1', port=5050, debug=False)
