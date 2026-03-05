#!/usr/bin/env python3
"""
Read-only viewer for OGE Informatics tasks with difficulty levels.
http://127.0.0.1:5052

Navigation: Left/Right arrows, filter by task number and difficulty.
"""
import json
import os
import sys
from flask import Flask, render_template_string, request

DATA_DIR = os.path.dirname(os.path.dirname(__file__))
DATA_FILE = os.path.join(DATA_DIR, 'data', 'oge_inf_tasks.json')

SDAMGIA_BASE = "https://inf-oge.sdamgia.ru"

FIPI_LEVELS = {
    1:'Б',2:'Б',3:'Б',4:'Б',5:'Б',6:'Б',7:'Б',
    8:'П',9:'П',10:'Б',11:'Б',12:'Б',
    13:'П',14:'В',15:'В',16:'В',
}

app = Flask(__name__)
tasks_data: list[dict] = []


def load_data():
    global tasks_data
    with open(DATA_FILE, 'r', encoding='utf-8') as f:
        tasks_data = json.load(f)


def fix_imgs(html: str) -> str:
    if not html:
        return html
    return html.replace('src="/get_file', f'src="{SDAMGIA_BASE}/get_file')


def get_filtered(tn=None, diff=None, src=None):
    result = tasks_data
    if tn is not None:
        result = [t for t in result if t['task_number'] == tn]
    if diff is not None:
        result = [t for t in result if t.get('difficulty_level') == diff]
    if src == 'generated':
        result = [t for t in result if t.get('generated')]
    elif src == 'scraped':
        result = [t for t in result if not t.get('generated')]
    return result


HTML = """
<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>OGE Difficulty Viewer</title>
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
  .filters{display:flex;align-items:center;gap:12px;margin-left:auto;flex-wrap:wrap}
  .filters label{font-size:13px;color:var(--dim)}
  .filters select{background:var(--sf2);color:var(--tx);border:1px solid var(--bd);border-radius:6px;padding:6px 12px;font-size:14px;cursor:pointer}

  .sb{background:var(--sf2);padding:10px 24px;display:flex;align-items:center;gap:20px;font-size:13px;color:var(--dim);border-bottom:1px solid var(--bd);flex-wrap:wrap}
  .sb .n{color:var(--tx);font-weight:600}

  .stats-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(140px,1fr));gap:8px;padding:16px 24px;max-width:960px;margin:0 auto}
  .stat-card{background:var(--sf);border:1px solid var(--bd);border-radius:8px;padding:10px 14px;text-align:center}
  .stat-card .num{font-size:20px;font-weight:700;color:var(--tx)}
  .stat-card .lbl{font-size:11px;color:var(--dim);margin-top:2px}
  .stat-card .diff-row{display:flex;justify-content:center;gap:6px;margin-top:6px}
  .diff-mini{font-size:10px;font-weight:600;padding:2px 6px;border-radius:4px}
  .diff-mini.e{background:#1c3b2a;color:var(--grn)}
  .diff-mini.m{background:#3b351c;color:var(--org)}
  .diff-mini.h{background:#3b1c1c;color:var(--red)}

  .mc{max-width:960px;margin:16px auto;padding:0 24px}
  .tc{background:var(--sf);border:1px solid var(--bd);border-radius:12px;overflow:hidden;margin-bottom:16px}
  .th{padding:14px 20px;display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid var(--bd);flex-wrap:wrap;gap:8px}
  .badges{display:flex;gap:6px;align-items:center}
  .badge-tn{background:var(--ac);color:#fff;font-size:13px;font-weight:600;padding:4px 12px;border-radius:20px}
  .badge-fipi{font-size:11px;font-weight:600;padding:3px 8px;border-radius:12px;border:1px solid var(--bd);color:var(--dim)}
  .badge-diff{font-size:12px;font-weight:700;padding:4px 14px;border-radius:20px;text-transform:uppercase;letter-spacing:.5px}
  .badge-diff.easy{background:#1c3b2a;color:var(--grn);border:1px solid #285c3e}
  .badge-diff.medium{background:#3b351c;color:var(--org);border:1px solid #5c4e28}
  .badge-diff.hard{background:#3b1c1c;color:var(--red);border:1px solid #5c2828}

  .tm{font-size:12px;color:var(--dim);display:flex;gap:12px;flex-wrap:wrap}
  .tm a{color:var(--ac);text-decoration:none}
  .tb{padding:20px;font-size:15px;line-height:1.7;overflow-x:auto}
  .tb img{max-width:100%;height:auto;border-radius:6px;margin:8px 0}
  .tb table{border-collapse:collapse;margin:8px 0}
  .tb td,.tb th{border:1px solid var(--bd);padding:6px 10px;font-size:14px}
  .ta{padding:12px 20px;border-top:1px solid var(--bd);font-size:14px;display:flex;align-items:center;gap:8px}
  .ta .l{color:var(--dim)}
  .ta .v{font-weight:600;color:var(--grn);font-family:'Consolas',monospace;font-size:16px}

  .nav{display:flex;justify-content:center;gap:12px;margin:20px 0}
  .nav-btn{padding:10px 28px;font-size:14px;font-weight:600;border:none;border-radius:8px;cursor:pointer;background:var(--sf2);color:var(--tx);border:1px solid var(--bd);transition:all .15s}
  .nav-btn:hover{background:var(--sf);border-color:var(--ac)}
  .nav-btn:disabled{opacity:.3;cursor:default}
  .nav-btn:disabled:hover{background:var(--sf2);border-color:var(--bd)}
  .pos-info{font-size:13px;color:var(--dim);text-align:center;margin-bottom:10px}

  .pw{flex:1;max-width:300px;height:6px;background:var(--bd);border-radius:3px;overflow:hidden}
  .pf{height:100%;background:var(--ac);border-radius:3px;transition:width .3s}

  .kh{text-align:center;font-size:12px;color:var(--dim);margin-bottom:24px}
  .kh kbd{background:var(--sf2);border:1px solid var(--bd);border-radius:4px;padding:2px 8px;font-family:monospace;font-size:12px;color:var(--tx)}
  .es{text-align:center;padding:60px 20px;color:var(--dim);font-size:18px}

  .diff-label{display:inline-block;margin-left:6px;font-size:11px;font-weight:600;padding:2px 8px;border-radius:10px;vertical-align:middle}
  .diff-label.easy{background:#1c3b2a;color:var(--grn)}
  .diff-label.medium{background:#3b351c;color:var(--org)}
  .diff-label.hard{background:#3b1c1c;color:var(--red)}

  .badge-src{font-size:11px;font-weight:600;padding:3px 10px;border-radius:12px}
  .badge-src.scraped{background:#1c2a3b;color:var(--blu);border:1px solid #283e5c}
  .badge-src.generated{background:#2a1c3b;color:#c084fc;border:1px solid #3e285c}

  .solution-block{margin-top:0;border-top:1px solid var(--bd);background:var(--sf2);padding:16px 20px;border-radius:0 0 12px 12px}
  .solution-toggle{background:none;border:1px solid var(--bd);color:var(--ac);padding:8px 20px;border-radius:8px;cursor:pointer;font-size:13px;font-weight:600;width:100%;text-align:left;margin-top:8px;transition:all .15s}
  .solution-toggle:hover{background:var(--sf);border-color:var(--ac)}
  .solution-content{padding:12px 0 0;font-size:14px;line-height:1.7;display:none}
  .solution-content.open{display:block}
  .solution-content p{margin:4px 0}

  .src-filter select{background:var(--sf2);color:var(--tx);border:1px solid var(--bd);border-radius:6px;padding:6px 12px;font-size:14px;cursor:pointer}
</style>
</head>
<body>
<div class="top">
  <h1>OGE Inf - Difficulty Viewer</h1>
  <div class="filters">
    <label>Задание:</label>
    <select id="ftn" onchange="applyFilter()">
      <option value="all" {% if not sel_tn %}selected{% endif %}>Все ({{ total }})</option>
      {% for num, cnt in tn_counts %}
      <option value="{{ num }}" {% if sel_tn == num %}selected{% endif %}>
        #{{ num }} ({{ cnt }})
      </option>
      {% endfor %}
    </select>
    <label>Сложность:</label>
    <select id="fdiff" onchange="applyFilter()">
      <option value="all" {% if not sel_diff %}selected{% endif %}>Все</option>
      <option value="easy" {% if sel_diff == 'easy' %}selected{% endif %}>Easy ({{ diff_counts.easy }})</option>
      <option value="medium" {% if sel_diff == 'medium' %}selected{% endif %}>Medium ({{ diff_counts.medium }})</option>
      <option value="hard" {% if sel_diff == 'hard' %}selected{% endif %}>Hard ({{ diff_counts.hard }})</option>
    </select>
    <label>Источник:</label>
    <select id="fsrc" onchange="applyFilter()">
      <option value="all" {% if not sel_src %}selected{% endif %}>Все</option>
      <option value="scraped" {% if sel_src == 'scraped' %}selected{% endif %}>Спарсенные ({{ src_counts.scraped }})</option>
      <option value="generated" {% if sel_src == 'generated' %}selected{% endif %}>Сгенерированные ({{ src_counts.generated }})</option>
    </select>
  </div>
</div>

<div class="sb">
  <span>Всего: <span class="n">{{ total }}</span></span>
  <span>В фильтре: <span class="n">{{ filtered }}</span></span>
  <span style="color:var(--grn)">Easy: <span class="n">{{ diff_counts.easy }}</span></span>
  <span style="color:var(--org)">Medium: <span class="n">{{ diff_counts.medium }}</span></span>
  <span style="color:var(--red)">Hard: <span class="n">{{ diff_counts.hard }}</span></span>
  <div class="pw"><div class="pf" style="width:{{ pct }}%"></div></div>
  <span>{{ pos + 1 }}/{{ filtered }}</span>
</div>

{% if show_stats %}
<div class="stats-grid">
  {% for num, cnts in stats_by_tn %}
  <div class="stat-card">
    <div class="num">#{{ num }}</div>
    <div class="lbl">{{ cnts.total }} заданий | ФИПИ: {{ cnts.fipi }}</div>
    <div class="diff-row">
      <span class="diff-mini e">{{ cnts.easy }}</span>
      <span class="diff-mini m">{{ cnts.medium }}</span>
      <span class="diff-mini h">{{ cnts.hard }}</span>
    </div>
  </div>
  {% endfor %}
</div>
{% endif %}

<div class="mc">
  {% if task %}
  <div class="pos-info">{{ pos + 1 }} / {{ filtered }}</div>
  <div class="tc">
    <div class="th">
      <div class="badges">
        <span class="badge-tn">#{{ task.task_number }}</span>
        <span class="badge-fipi">ФИПИ: {{ fipi_level }}</span>
        <span class="badge-diff {{ task.difficulty_level }}">{{ diff_label }}</span>
        {% if task.generated %}
        <span class="badge-src generated">Сгенерировано</span>
        {% else %}
        <span class="badge-src scraped">Спарсено</span>
        {% endif %}
      </div>
      <div class="tm">
        <span>ID: {{ task.site_id }}</span>
        {% if task.source_url %}<a href="{{ task.source_url }}" target="_blank">Источник</a>{% endif %}
      </div>
    </div>
    <div class="tb">{{ task.content_html | safe }}</div>
    {% if task.answer %}
    <div class="ta"><span class="l">Ответ:</span><span class="v">{{ task.answer }}</span></div>
    {% endif %}
    {% if task.solution_html %}
    <div class="solution-block">
      <button class="solution-toggle" onclick="this.nextElementSibling.classList.toggle('open');this.textContent=this.nextElementSibling.classList.contains('open')?'▼ Скрыть решение':'▶ Показать решение'">▶ Показать решение</button>
      <div class="solution-content">{{ task.solution_html | safe }}</div>
    </div>
    {% endif %}
  </div>
  <div class="nav">
    <button class="nav-btn" onclick="go(-1)" {% if pos <= 0 %}disabled{% endif %}>&#8592; Назад</button>
    <button class="nav-btn" onclick="go(1)" {% if pos >= filtered - 1 %}disabled{% endif %}>Вперёд &#8594;</button>
  </div>
  <div class="kh"><kbd>&#8592;</kbd> назад <kbd>&#8594;</kbd> вперёд</div>
  {% else %}
  <div class="es">Нет заданий по выбранным фильтрам</div>
  {% endif %}
</div>

<script>
function applyFilter(){
  const tn=document.getElementById('ftn').value;
  const df=document.getElementById('fdiff').value;
  const src=document.getElementById('fsrc').value;
  let url='/?pos=0';
  if(tn!=='all') url+='&tn='+tn;
  if(df!=='all') url+='&diff='+df;
  if(src!=='all') url+='&src='+src;
  location.href=url;
}
function go(delta){
  const p=new URLSearchParams(location.search);
  const pos=parseInt(p.get('pos')||'0')+delta;
  p.set('pos',Math.max(0,pos));
  location.href='/?'+p.toString();
}
document.addEventListener('keydown',e=>{
  if(e.target.tagName==='SELECT')return;
  if(e.key==='ArrowRight'){e.preventDefault();go(1)}
  if(e.key==='ArrowLeft'){e.preventDefault();go(-1)}
})
</script>
</body></html>
"""

DIFF_LABELS = {'easy': 'Лёгкий', 'medium': 'Средний', 'hard': 'Сложный'}


@app.route('/')
def index():
    tn_p = request.args.get('tn')
    diff_p = request.args.get('diff')
    pos = int(request.args.get('pos', 0))

    src_p = request.args.get('src')

    sel_tn = int(tn_p) if tn_p and tn_p != 'all' else None
    sel_diff = diff_p if diff_p and diff_p != 'all' else None
    sel_src = src_p if src_p and src_p != 'all' else None

    filtered = get_filtered(sel_tn, sel_diff, sel_src)
    fc = len(filtered)

    nums = {}
    for t in tasks_data:
        n = t['task_number']
        nums[n] = nums.get(n, 0) + 1
    tn_counts = sorted(nums.items())

    dc = {'easy': 0, 'medium': 0, 'hard': 0}
    sc = {'scraped': 0, 'generated': 0}
    for t in tasks_data:
        d = t.get('difficulty_level', 'medium')
        dc[d] = dc.get(d, 0) + 1
        if t.get('generated'):
            sc['generated'] += 1
        else:
            sc['scraped'] += 1

    stats_by_tn = {}
    for t in tasks_data:
        n = t['task_number']
        if n not in stats_by_tn:
            stats_by_tn[n] = {'easy': 0, 'medium': 0, 'hard': 0, 'total': 0, 'fipi': FIPI_LEVELS.get(n, '?')}
        stats_by_tn[n][t.get('difficulty_level', 'medium')] += 1
        stats_by_tn[n]['total'] += 1
    stats_list = sorted(stats_by_tn.items())

    if pos >= fc:
        pos = max(0, fc - 1)
    if fc == 0:
        cur = None
    else:
        cur = dict(filtered[pos])
        cur['content_html'] = fix_imgs(cur.get('content_html', ''))

    pct = round((pos + 1) / fc * 100, 1) if fc else 0

    return render_template_string(
        HTML,
        task=cur,
        total=len(tasks_data),
        filtered=fc,
        pos=pos,
        pct=pct,
        sel_tn=sel_tn,
        sel_diff=sel_diff,
        sel_src=sel_src,
        tn_counts=tn_counts,
        diff_counts=type('', (), dc)(),
        src_counts=type('', (), sc)(),
        stats_by_tn=stats_list,
        show_stats=(sel_tn is None and sel_diff is None and sel_src is None and pos == 0),
        fipi_level=FIPI_LEVELS.get(cur['task_number'], '?') if cur else '',
        diff_label=DIFF_LABELS.get(cur.get('difficulty_level', ''), '') if cur else '',
    )


if __name__ == '__main__':
    if not os.path.exists(DATA_FILE):
        print(f"File {DATA_FILE} not found!")
        sys.exit(1)
    load_data()
    print(f"Loaded {len(tasks_data)} tasks")
    dc = {}
    for t in tasks_data:
        d = t.get('difficulty_level', 'none')
        dc[d] = dc.get(d, 0) + 1
    for k, v in sorted(dc.items()):
        print(f"  {k}: {v}")
    print(f"\nOpen: http://127.0.0.1:5052")
    print("Navigation: Left/Right arrows")
    app.run(host='127.0.0.1', port=5052, debug=False)
