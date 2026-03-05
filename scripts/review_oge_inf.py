#!/usr/bin/env python3
"""
Reviewer for OGE Informatics tasks (data/oge_inf_tasks.json).
http://127.0.0.1:5051

Hotkeys:
    Right  -- accept
    Left   -- delete
    S      -- skip
    Backspace -- undo
"""
import json
import os
import sys
import copy
from datetime import datetime
from flask import Flask, render_template_string, request, jsonify

DATA_DIR = os.path.dirname(os.path.dirname(__file__))
DATA_FILE = os.path.join(DATA_DIR, 'data', 'oge_inf_tasks.json')
DELETED_LOG = os.path.join(DATA_DIR, 'data', 'oge_inf_deleted.json')
ACCEPTED_LOG = os.path.join(DATA_DIR, 'data', 'oge_inf_accepted.json')

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


def save_deleted():
    with open(DELETED_LOG, 'w', encoding='utf-8') as f:
        json.dump(deleted_tasks, f, ensure_ascii=False, indent=2)


def save_accepted():
    with open(ACCEPTED_LOG, 'w', encoding='utf-8') as f:
        json.dump(accepted_tasks, f, ensure_ascii=False, indent=2)


SDAMGIA_BASE = "https://inf-oge.sdamgia.ru"


def fix_img_urls(html: str) -> str:
    if not html:
        return html
    return html.replace('src="/get_file', f'src="{SDAMGIA_BASE}/get_file')


def get_filtered(tn=None):
    if tn is None:
        return tasks_data
    return [t for t in tasks_data if t['task_number'] == tn]


def get_accepted_ids():
    return set(a['site_id'] for a in accepted_tasks)


HTML = """
<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>OGE Inf Review</title>
<style>
  :root {
    --bg:#0f1117; --sf:#1a1d27; --sf2:#242836; --bd:#2e3348;
    --tx:#e4e6f0; --dim:#8b8fa8; --ac:#6c7bff;
    --grn:#34d399; --red:#f87171; --org:#fbbf24; --blu:#60a5fa;
  }
  *{margin:0;padding:0;box-sizing:border-box}
  body{font-family:'Segoe UI',system-ui,sans-serif;background:var(--bg);color:var(--tx);min-height:100vh}
  .top{background:var(--sf);border-bottom:1px solid var(--bd);padding:12px 24px;display:flex;align-items:center;gap:16px;flex-wrap:wrap;position:sticky;top:0;z-index:100}
  .top h1{font-size:18px;font-weight:600;white-space:nowrap}
  .fg{display:flex;align-items:center;gap:8px;margin-left:auto}
  .fg label{font-size:13px;color:var(--dim)}
  .fg select{background:var(--sf2);color:var(--tx);border:1px solid var(--bd);border-radius:6px;padding:6px 12px;font-size:14px;cursor:pointer}
  .sb{background:var(--sf2);padding:8px 24px;display:flex;align-items:center;gap:20px;font-size:13px;color:var(--dim);border-bottom:1px solid var(--bd);flex-wrap:wrap}
  .sb .n{color:var(--tx);font-weight:600}
  .sb .ng{color:var(--grn);font-weight:600}
  .sb .nr{color:var(--red);font-weight:600}
  .pw{flex:1;max-width:300px;height:6px;background:var(--bd);border-radius:3px;overflow:hidden}
  .pf{height:100%;background:var(--ac);border-radius:3px;transition:width .3s}
  .mc{max-width:960px;margin:24px auto;padding:0 24px}
  .tc{background:var(--sf);border:1px solid var(--bd);border-radius:12px;overflow:hidden}
  .tc.acc{border-color:var(--grn);box-shadow:0 0 0 1px var(--grn)}
  .th{padding:16px 20px;display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid var(--bd);flex-wrap:wrap;gap:8px}
  .badge{background:var(--ac);color:#fff;font-size:13px;font-weight:600;padding:4px 12px;border-radius:20px}
  .abadge{background:#1c3b2a;color:var(--grn);font-size:12px;font-weight:600;padding:3px 10px;border-radius:20px;border:1px solid #285c3e}
  .tm{font-size:12px;color:var(--dim);display:flex;gap:16px;flex-wrap:wrap}
  .tm a{color:var(--ac);text-decoration:none}
  .tm a:hover{text-decoration:underline}
  .tb{padding:20px;font-size:15px;line-height:1.7;overflow-x:auto}
  .tb img{max-width:100%;height:auto;border-radius:6px;margin:8px 0}
  .tb table{border-collapse:collapse;margin:8px 0}
  .tb td,.tb th{border:1px solid var(--bd);padding:6px 10px;font-size:14px}
  .ta{padding:12px 20px;border-top:1px solid var(--bd);font-size:14px;display:flex;align-items:center;gap:8px}
  .ta .l{color:var(--dim)}
  .ta .v{font-weight:600;color:var(--grn);font-family:'Consolas',monospace;font-size:16px}
  .acts{display:flex;justify-content:center;gap:16px;margin:24px 0;flex-wrap:wrap}
  .btn{padding:14px 40px;font-size:16px;font-weight:600;border:none;border-radius:10px;cursor:pointer;display:flex;align-items:center;gap:8px;transition:transform .15s,box-shadow .15s}
  .btn:hover{transform:translateY(-2px)}
  .btn:active{transform:translateY(0)}
  .bd{background:#3b1c1c;color:var(--red);border:1px solid #5c2828}
  .bd:hover{box-shadow:0 4px 20px rgba(248,113,113,0.2)}
  .ba{background:#1c3b2a;color:var(--grn);border:1px solid #285c3e}
  .ba:hover{box-shadow:0 4px 20px rgba(52,211,153,0.2)}
  .bs{background:#1c2a3b;color:var(--blu);border:1px solid #283e5c;padding:10px 24px;font-size:14px}
  .bu{background:var(--sf2);color:var(--dim);border:1px solid var(--bd);padding:10px 20px;font-size:13px}
  .kh{text-align:center;font-size:12px;color:var(--dim);margin-bottom:24px}
  .kh kbd{background:var(--sf2);border:1px solid var(--bd);border-radius:4px;padding:2px 8px;font-family:monospace;font-size:12px;color:var(--tx)}
  .es{text-align:center;padding:80px 20px;color:var(--dim);font-size:18px}
  .toast{position:fixed;bottom:24px;left:50%;transform:translateX(-50%) translateY(80px);padding:12px 24px;border-radius:10px;font-size:14px;font-weight:600;opacity:0;transition:all .3s;z-index:200;pointer-events:none}
  .toast.show{transform:translateX(-50%) translateY(0);opacity:1}
  .td{background:#3b1c1c;color:var(--red);border:1px solid #5c2828}
  .tac{background:#1c3b2a;color:var(--grn);border:1px solid #285c3e}
  .tu{background:var(--sf2);color:var(--org);border:1px solid var(--bd)}
  .nc{font-size:14px;color:var(--dim);text-align:center;margin-bottom:12px}
</style>
</head>
<body>
<div class="top">
  <h1>OGE Inf Review</h1>
  <div class="fg">
    <label>Tип:</label>
    <select id="f" onchange="cf()">
      <option value="all" {% if not sn %}selected{% endif %}>Bce ({{ tt }})</option>
      {% for num, cnt, ac, dl in tns %}
      <option value="{{ num }}" {% if sn == num %}selected{% endif %}>
        {{ num }} ({{ cnt }}) +{{ ac }} -{{ dl }}
      </option>
      {% endfor %}
    </select>
  </div>
</div>
<div class="sb">
  <span>B файле: <span class="n">{{ tt }}</span></span>
  <span>B фильтре: <span class="n">{{ fc }}</span></span>
  <span>Принято: <span class="ng">{{ acnt }}</span></span>
  <span>Удалено: <span class="nr">{{ dcnt }}</span></span>
  <div class="pw"><div class="pf" style="width:{{ pp }}%"></div></div>
  <span>{{ cp + 1 }}/{{ fc }}</span>
</div>
<div class="mc">
  {% if task %}
  <div class="nc">{{ cp + 1 }} / {{ fc }} (site_id: {{ task.site_id }}){% if ia %} <span style="color:var(--grn);font-weight:600">ACCEPTED</span>{% endif %}</div>
  <div class="tc {% if ia %}acc{% endif %}">
    <div class="th">
      <div style="display:flex;gap:8px;align-items:center">
        <span class="badge">{{ task.task_number }}</span>
        {% if ia %}<span class="abadge">Accepted</span>{% endif %}
      </div>
      <div class="tm">
        <span>ID: {{ task.site_id }}</span>
        {% if task.source_url %}<a href="{{ task.source_url }}" target="_blank">Source</a>{% endif %}
      </div>
    </div>
    <div class="tb">{{ task.content_html | safe }}</div>
    {% if task.answer %}
    <div class="ta"><span class="l">Answer:</span><span class="v">{{ task.answer }}</span></div>
    {% endif %}
  </div>
  <div class="acts">
    <button class="btn bd" onclick="da('delete')">X Удалить</button>
    <button class="btn bu" onclick="da('undo')">Отмена</button>
    <button class="btn bs" onclick="da('skip')">Пропустить</button>
    <button class="btn ba" onclick="da('accept')">Принять</button>
  </div>
  <div class="kh"><kbd>Left</kbd> удалить <kbd>Right</kbd> принять <kbd>S</kbd> пропустить <kbd>Backspace</kbd> отмена</div>
  {% else %}
  <div class="es"><p>Bce задания просмотрены!</p></div>
  {% endif %}
</div>
<div class="toast td" id="tD">Удалено</div>
<div class="toast tac" id="tA">Принято</div>
<div class="toast tu" id="tU">Отменено</div>
<script>
let busy=false;
function st(id){const e=document.getElementById(id);e.classList.add('show');setTimeout(()=>e.classList.remove('show'),800)}
function cf(){window.location.href='/?tn='+document.getElementById('f').value+'&pos=0'}
function gp(){const p=new URLSearchParams(location.search);return{tn:p.get('tn')||'all',pos:parseInt(p.get('pos')||'0')}}
async function da(a){
  if(busy)return;busy=true;const{tn,pos}=gp();
  if(a==='skip'){location.href='/?tn='+tn+'&pos='+(pos+1);return}
  if(a==='undo'){const r=await fetch('/api/undo',{method:'POST'});if(r.ok){st('tU');setTimeout(()=>location.href='/?tn='+tn+'&pos='+Math.max(0,pos-1),250)}busy=false;return}
  const r=await fetch('/api/action',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({tn,pos,action:a})});
  if(r.ok){if(a==='delete'){st('tD');setTimeout(()=>location.href='/?tn='+tn+'&pos='+pos,250)}else{st('tA');setTimeout(()=>location.href='/?tn='+tn+'&pos='+(pos+1),250)}}
  busy=false
}
document.addEventListener('keydown',e=>{
  if(e.target.tagName==='SELECT')return;
  if(e.key==='ArrowRight'){e.preventDefault();da('accept')}
  if(e.key==='ArrowLeft'){e.preventDefault();da('delete')}
  if(e.key==='Backspace'){e.preventDefault();da('undo')}
  if(e.key==='s'||e.key==='S'){e.preventDefault();da('skip')}
})
</script>
</body></html>
"""


@app.route('/')
def index():
    tn_p = request.args.get('tn', 'all')
    pos = int(request.args.get('pos', 0))
    tn_f = None if tn_p == 'all' else int(tn_p)
    filtered = get_filtered(tn_f)

    nums = {}
    for t in tasks_data:
        n = t['task_number']
        nums[n] = nums.get(n, 0) + 1

    a_by_n = {}
    for a in accepted_tasks:
        n = a['task_number']
        a_by_n[n] = a_by_n.get(n, 0) + 1

    d_by_n = {}
    for d in deleted_tasks:
        n = d['task_number']
        d_by_n[n] = d_by_n.get(n, 0) + 1

    tns = [(n, nums[n], a_by_n.get(n, 0), d_by_n.get(n, 0)) for n in sorted(nums)]

    if pos >= len(filtered):
        pos = len(filtered)
        cur = None
        ia = False
    else:
        cur = dict(filtered[pos])
        cur['content_html'] = fix_img_urls(cur.get('content_html', ''))
        ia = cur['site_id'] in get_accepted_ids()

    pp = round(pos / len(filtered) * 100, 1) if filtered else 0

    return render_template_string(HTML, task=cur, ia=ia, tt=len(tasks_data), fc=len(filtered),
                                 acnt=len(accepted_tasks), dcnt=len(deleted_tasks),
                                 cp=pos, pp=pp, tns=tns, sn=tn_f)


@app.route('/api/action', methods=['POST'])
def api_action():
    d = request.json
    tn_p = d.get('tn', 'all')
    pos = int(d.get('pos', 0))
    action = d.get('action')
    tn_f = None if tn_p == 'all' else int(tn_p)
    filtered = get_filtered(tn_f)

    if pos >= len(filtered):
        return jsonify({'error': 'oor'}), 400

    task = filtered[pos]
    sid = task['site_id']

    if action == 'delete':
        review_history.append({
            'action': 'delete', 'task': copy.deepcopy(task),
            'idx': next(i for i, t in enumerate(tasks_data) if t['site_id'] == sid)
        })
        tasks_data[:] = [t for t in tasks_data if t['site_id'] != sid]
        deleted_tasks.append({
            'site_id': sid, 'task_number': task['task_number'],
            'content_html': task.get('content_html', ''), 'answer': task.get('answer'),
            'deleted_at': datetime.now().isoformat(),
        })
        save_data()
        save_deleted()
        return jsonify({'ok': True})

    if action == 'accept':
        already = sid in get_accepted_ids()
        if not already:
            accepted_tasks.append({
                'site_id': sid, 'task_number': task['task_number'],
                'content_html': task.get('content_html', ''), 'answer': task.get('answer'),
                'accepted_at': datetime.now().isoformat(),
            })
            save_accepted()
        review_history.append({'action': 'accept', 'site_id': sid, 'was_new': not already})
        return jsonify({'ok': True})

    return jsonify({'error': 'bad action'}), 400


@app.route('/api/undo', methods=['POST'])
def api_undo():
    if not review_history:
        return jsonify({'error': 'empty'}), 400
    last = review_history.pop()
    if last['action'] == 'delete':
        idx = min(last['idx'], len(tasks_data))
        tasks_data.insert(idx, last['task'])
        deleted_tasks[:] = [d for d in deleted_tasks if d['site_id'] != last['task']['site_id']]
        save_data()
        save_deleted()
    elif last['action'] == 'accept' and last.get('was_new'):
        accepted_tasks[:] = [a for a in accepted_tasks if a['site_id'] != last['site_id']]
        save_accepted()
    return jsonify({'ok': True})


if __name__ == '__main__':
    if not os.path.exists(DATA_FILE):
        print(f"File {DATA_FILE} not found!")
        sys.exit(1)
    load_data()
    print(f"Loaded {len(tasks_data)} tasks")
    print(f"Accepted: {len(accepted_tasks)}, Deleted: {len(deleted_tasks)}")
    print(f"\nOpen: http://127.0.0.1:5051")
    print("Hotkeys: Right=accept | Left=delete | S=skip | Backspace=undo")
    app.run(host='127.0.0.1', port=5051, debug=False)
