from __future__ import annotations

import json
import os
import re
import sys
from typing import Any

# Ensure repo root is on sys.path (Streamlit may set cwd to trainer_app/)
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import streamlit as st
import streamlit.components.v1 as components

from trainer_app.platform_client import PlatformClient, get_platform_base_url
from trainer_app.analyzers.python_static import analyze_python_code
from trainer_app.knowledge import load_task_knowledge
from trainer_app.llm.providers import get_llm_client, get_llm_info, build_messages_for_help
from trainer_app.runner.sandbox import is_runner_enabled, run_python_solve_tests, run_python_program
from app.lessons.utils import normalize_answer_value


st.set_page_config(page_title="Тренажёр · AI помощник", layout="wide")

# Optional .env loading (helps local/dev and simple deploys)
try:
    from dotenv import load_dotenv  # type: ignore
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    load_dotenv(os.path.join(repo_root, '.env'), override=False)
    load_dotenv(os.path.join(os.path.dirname(__file__), '.env'), override=False)
except Exception:
    pass


def _inject_minimal_css():
    """Minimal CSS for Streamlit native elements only."""
    st.markdown(
        """
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap');
  #MainMenu {visibility: hidden;}
  footer {visibility: hidden;}
  header {visibility: hidden;}
  html, body, [class*="css"] { font-family: Inter, system-ui, -apple-system, sans-serif; }
  .stApp {
    background: linear-gradient(135deg, #0a0c12 0%, #0d1117 50%, #070910 100%);
    min-height: 100vh;
  }
  .block-container { padding-top: 0.5rem; padding-bottom: 1rem; }
  div.stButton > button {
    border-radius: 14px !important;
    border: 1px solid rgba(255,255,255,0.15) !important;
    background: linear-gradient(180deg, rgba(255,255,255,0.08), rgba(255,255,255,0.02)) !important;
    color: rgba(255,255,255,0.92) !important;
    font-weight: 600 !important;
    padding: 0.7rem 1.2rem !important;
    transition: all 0.2s ease;
  }
  div.stButton > button:hover {
    border-color: rgba(0,255,213,0.5) !important;
    background: linear-gradient(180deg, rgba(0,255,213,0.12), rgba(0,255,213,0.04)) !important;
    color: #00ffd5 !important;
    transform: translateY(-2px);
    box-shadow: 0 8px 25px rgba(0,255,213,0.2);
  }
  div[data-baseweb="input"] input,
  div[data-baseweb="textarea"] textarea {
    border-radius: 12px !important;
    border: 1px solid rgba(255,255,255,0.12) !important;
    background: rgba(255,255,255,0.04) !important;
    color: #fff !important;
  }
  button[data-baseweb="tab"] {
    border-radius: 999px !important;
    font-weight: 600 !important;
  }
  .stTabs [data-baseweb="tab-panel"] { padding-top: 1rem; }
</style>
        """,
        unsafe_allow_html=True,
    )


def _badge(text: str, kind: str = "ok") -> str:
    kind = kind if kind in ("ok", "warn", "err") else "ok"
    safe = (text or "").replace("<", "&lt;").replace(">", "&gt;")
    return f'<span class="k-badge {kind}">{safe}</span>'


def _render_tests_block(tests_payload: Any):
    if not isinstance(tests_payload, dict):
        st.info("Нет результатов тестов.")
        return
    if not tests_payload.get("ok"):
        st.error(f"Тесты не запустились: {tests_payload.get('error')}")
        details = tests_payload.get("details") or ""
        if details:
            st.code(str(details)[:4000])
        return
    results = tests_payload.get("results") or []
    if not isinstance(results, list) or not results:
        st.warning("Тесты вернули пустой результат.")
        return
    ok_cnt = sum(1 for r in results if isinstance(r, dict) and r.get("ok"))
    total = len(results)
    if ok_cnt == total:
        st.success(f"Все тесты пройдены: {ok_cnt}/{total}")
    else:
        st.warning(f"Пройдено тестов: {ok_cnt}/{total}")
    rows = [{"OK": "✅" if r.get("ok") else "❌", "Тест": r.get("name", ""), "Ожидалось": r.get("expected", ""), "Получилось": r.get("got", "")} for r in results if isinstance(r, dict)]
    st.dataframe(rows, use_container_width=True, hide_index=True)


def _get_query_param(name: str) -> str:
    try:
        return (st.query_params.get(name) or '').strip()
    except Exception:
        return (st.experimental_get_query_params().get(name, [''])[0] or '').strip()


def _init_state():
    st.session_state.setdefault('me', None)
    st.session_state.setdefault('task', None)
    st.session_state.setdefault('task_type', None)
    st.session_state.setdefault('current_card', None)
    st.session_state.setdefault('code', '')
    st.session_state.setdefault('messages', [])
    st.session_state.setdefault('analysis', None)
    st.session_state.setdefault('tests', None)
    st.session_state.setdefault('seen_task_ids', {})
    st.session_state.setdefault('hint_level_by_task', {})
    st.session_state.setdefault('history_loaded', False)
    st.session_state.setdefault('history_items', [])


def _reset_workbench_state():
    st.session_state['analysis'] = None
    st.session_state['tests'] = None
    st.session_state['messages'] = []
    st.session_state['code'] = ''


def _register_seen_task(task_type: int, task_id: int):
    seen = st.session_state['seen_task_ids'].setdefault(int(task_type), [])
    if int(task_id) not in seen:
        seen.append(int(task_id))


def _pull_random_task(client: PlatformClient, *, task_type: int) -> dict[str, Any] | None:
    seen = st.session_state['seen_task_ids'].get(int(task_type), []) or []
    if not seen:
        resp = client.stream_start(task_type=int(task_type), exclude_task_ids=seen)
    else:
        resp = client.stream_next(task_type=int(task_type), exclude_task_ids=seen)
    t = resp.get('task') if isinstance(resp, dict) else None
    if t and t.get('task_id'):
        _register_seen_task(int(task_type), int(t.get('task_id')))
        st.session_state['hint_level_by_task'][int(t.get('task_id'))] = 0
        return t
    return None


def _check_answer_match(expected_raw: str, given_raw: str) -> tuple[bool, list[str]]:
    expected_raw = (expected_raw or '').strip()
    if not expected_raw:
        return False, []
    variants = [v.strip() for v in re.split(r'[|;\n]+', expected_raw) if v.strip()]
    normalized_expected = [normalize_answer_value(v) for v in variants] if variants else [normalize_answer_value(expected_raw)]
    normalized_expected = [v for v in normalized_expected if v != '']
    normalized_given = normalize_answer_value(given_raw)
    return normalized_given in normalized_expected and normalized_given != '', normalized_expected


def _render_number_picker_component(counts: dict[int, int], username: str) -> None:
    """Render beautiful fullscreen number picker with all styles embedded."""
    
    buttons_html = ""
    for n in range(1, 28):
        count = counts.get(n, 0)
        disabled = "disabled" if count == 0 else ""
        empty_class = "empty" if count == 0 else ""
        buttons_html += f'<button class="num-btn {empty_class}" data-num="{n}" {disabled}>{n}<span class="count">{count}</span></button>'
    
    html = f'''
<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap" rel="stylesheet">
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{
  font-family: 'Inter', system-ui, -apple-system, sans-serif;
  background: transparent;
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 40px 20px;
}}

.hero {{
  text-align: center;
  margin-bottom: 40px;
}}

.hero-title {{
  font-size: 3rem;
  font-weight: 900;
  letter-spacing: -0.03em;
  background: linear-gradient(135deg, #fff 0%, rgba(255,255,255,0.7) 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
  margin-bottom: 12px;
}}

.hero-subtitle {{
  font-size: 1.1rem;
  color: rgba(255,255,255,0.5);
  font-weight: 500;
}}

.hero-user {{
  margin-top: 20px;
  padding: 10px 24px;
  background: rgba(255,255,255,0.05);
  border: 1px solid rgba(255,255,255,0.1);
  border-radius: 999px;
  display: inline-block;
  color: rgba(255,255,255,0.7);
  font-weight: 600;
}}

.picker-label {{
  font-size: 1rem;
  color: rgba(255,255,255,0.6);
  margin-bottom: 20px;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  font-weight: 600;
}}

.number-grid {{
  display: grid;
  grid-template-columns: repeat(9, 1fr);
  gap: 12px;
  max-width: 650px;
  width: 100%;
}}

.num-btn {{
  aspect-ratio: 1;
  border-radius: 16px;
  border: 2px solid rgba(255,255,255,0.1);
  background: linear-gradient(160deg, rgba(255,255,255,0.06), rgba(255,255,255,0.02));
  color: #fff;
  font-weight: 700;
  font-size: 1.2rem;
  cursor: pointer;
  transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 4px;
  position: relative;
  overflow: hidden;
}}

.num-btn .count {{
  font-size: 0.65rem;
  color: rgba(255,255,255,0.4);
  font-weight: 500;
}}

.num-btn:not(.empty):hover {{
  border-color: rgba(0,255,213,0.7);
  background: linear-gradient(160deg, rgba(0,255,213,0.15), rgba(0,255,213,0.05));
  transform: translateY(-4px) scale(1.05);
  box-shadow: 0 15px 40px rgba(0,255,213,0.3), 0 0 0 1px rgba(0,255,213,0.2) inset;
  color: #00ffd5;
}}

.num-btn:not(.empty):hover .count {{
  color: rgba(0,255,213,0.7);
}}

.num-btn:not(.empty):active {{
  transform: translateY(-2px) scale(1.02);
}}

.num-btn.empty {{
  opacity: 0.25;
  cursor: not-allowed;
}}

@media (max-width: 600px) {{
  .number-grid {{ grid-template-columns: repeat(5, 1fr); gap: 8px; }}
  .hero-title {{ font-size: 2rem; }}
  .num-btn {{ font-size: 1rem; border-radius: 12px; }}
}}
</style>
</head>
<body>
  <div class="hero">
    <div class="hero-title">Тренажёр КЕГЭ</div>
    <div class="hero-subtitle">Выбери номер задания для тренировки</div>
    <div class="hero-user">👤 {username}</div>
  </div>
  
  <div class="picker-label">Номер задания</div>
  
  <div class="number-grid" id="picker">
    {buttons_html}
  </div>

<script>
document.querySelectorAll('.num-btn:not(.empty)').forEach(btn => {{
  btn.addEventListener('click', () => {{
    const num = btn.getAttribute('data-num');
    // Send to Streamlit
    window.parent.postMessage({{
      type: 'streamlit:setComponentValue',
      value: parseInt(num)
    }}, '*');
  }});
}});
</script>
</body>
</html>
'''
    components.html(html, height=550, scrolling=False)


def _render_swipe_card_component(task: dict[str, Any], task_type: int) -> None:
    """Render TikTok-style swipe card with embedded styles and full interactivity."""
    
    task_id = task.get('task_id') or 0
    task_number = task.get('task_number') or '?'
    source_url = task.get('source_url') or ''
    site_task_id = task.get('site_task_id') or ''
    content_html = (task.get('content_html') or '').strip()
    
    # Escape content for embedding
    content_safe = content_html.replace('`', '\\`').replace('${', '\\${')
    
    source_badge = f'<a href="{source_url}" target="_blank" class="badge link">Источник ↗</a>' if source_url else ''
    site_badge = f'<span class="badge">{site_task_id}</span>' if site_task_id else ''
    
    html = f'''
<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap" rel="stylesheet">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/katex.min.css">
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{
  font-family: 'Inter', system-ui, -apple-system, sans-serif;
  background: transparent;
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 20px;
}}

.header {{
  text-align: center;
  margin-bottom: 24px;
}}

.header-title {{
  font-size: 1.8rem;
  font-weight: 800;
  color: #fff;
  margin-bottom: 8px;
}}

.header-hint {{
  font-size: 0.95rem;
  color: rgba(255,255,255,0.5);
}}

.back-btn {{
  position: absolute;
  top: 20px;
  left: 20px;
  padding: 10px 20px;
  border-radius: 12px;
  border: 1px solid rgba(255,255,255,0.15);
  background: rgba(255,255,255,0.05);
  color: rgba(255,255,255,0.8);
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s ease;
}}

.back-btn:hover {{
  background: rgba(255,255,255,0.1);
  border-color: rgba(255,255,255,0.25);
}}

/* Card Container */
.card-wrapper {{
  position: relative;
  width: 100%;
  max-width: 800px;
  perspective: 1000px;
}}

.swipe-card {{
  position: relative;
  width: 100%;
  min-height: 55vh;
  border-radius: 24px;
  border: 2px solid rgba(255,255,255,0.12);
  background: linear-gradient(165deg, rgba(20,22,32,0.98), rgba(14,16,24,0.96));
  box-shadow: 0 30px 80px rgba(0,0,0,0.5), 0 0 0 1px rgba(255,255,255,0.05) inset;
  overflow: hidden;
  transition: all 0.4s cubic-bezier(0.4, 0, 0.2, 1);
  cursor: pointer;
}}

/* Hover states */
.swipe-card.hover-left {{
  border-color: rgba(239,68,68,0.8);
  background: linear-gradient(165deg, rgba(60,20,25,0.98), rgba(30,12,18,0.96));
  box-shadow: 0 30px 80px rgba(239,68,68,0.3), 0 0 80px rgba(239,68,68,0.1) inset;
  transform: rotateY(-2deg) scale(1.01);
}}

.swipe-card.hover-right {{
  border-color: rgba(16,185,129,0.8);
  background: linear-gradient(165deg, rgba(12,45,35,0.98), rgba(8,28,22,0.96));
  box-shadow: 0 30px 80px rgba(16,185,129,0.3), 0 0 80px rgba(16,185,129,0.1) inset;
  transform: rotateY(2deg) scale(1.01);
}}

/* Card content */
.card-inner {{
  padding: 28px 32px;
  position: relative;
  z-index: 2;
}}

.card-header {{
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 20px;
  padding-bottom: 16px;
  border-bottom: 1px solid rgba(255,255,255,0.08);
}}

.badge {{
  display: inline-flex;
  align-items: center;
  padding: 6px 14px;
  border-radius: 999px;
  font-size: 13px;
  font-weight: 600;
  border: 1px solid rgba(255,255,255,0.15);
  background: rgba(255,255,255,0.06);
  color: rgba(255,255,255,0.85);
}}

.badge.primary {{
  border-color: rgba(0,255,213,0.5);
  background: rgba(0,255,213,0.12);
  color: #00ffd5;
}}

.badge.link {{
  text-decoration: none;
  cursor: pointer;
  transition: all 0.2s ease;
}}

.badge.link:hover {{
  background: rgba(255,255,255,0.12);
  border-color: rgba(255,255,255,0.3);
}}

.card-body {{
  color: rgba(255,255,255,0.92);
  font-size: 15px;
  line-height: 1.75;
  max-height: 45vh;
  overflow-y: auto;
  padding-right: 8px;
}}

.card-body::-webkit-scrollbar {{ width: 5px; }}
.card-body::-webkit-scrollbar-track {{ background: rgba(255,255,255,0.03); border-radius: 3px; }}
.card-body::-webkit-scrollbar-thumb {{ background: rgba(255,255,255,0.12); border-radius: 3px; }}

.card-body p {{ margin-bottom: 12px; }}
.card-body img {{ max-width: 100%; border-radius: 8px; margin: 12px 0; }}

/* Zone indicators */
.zone-indicators {{
  position: absolute;
  bottom: 0;
  left: 0;
  right: 0;
  display: flex;
  pointer-events: none;
  z-index: 5;
}}

.zone-indicator {{
  flex: 1;
  padding: 20px;
  text-align: center;
  font-weight: 700;
  font-size: 15px;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  opacity: 0.4;
  transition: opacity 0.3s ease;
}}

.zone-indicator.left {{
  color: #ef4444;
  background: linear-gradient(0deg, rgba(239,68,68,0.2), transparent 80%);
}}

.zone-indicator.right {{
  color: #10b981;
  background: linear-gradient(0deg, rgba(16,185,129,0.2), transparent 80%);
}}

.swipe-card.hover-left .zone-indicator.left {{ opacity: 1; }}
.swipe-card.hover-right .zone-indicator.right {{ opacity: 1; }}

/* Invisible click zones */
.click-zones {{
  position: absolute;
  inset: 0;
  display: flex;
  z-index: 10;
}}

.click-zone {{
  flex: 1;
  cursor: pointer;
}}

/* Exit animation */
.swipe-card.exit-left {{
  transform: translateX(-150%) rotate(-20deg);
  opacity: 0;
}}

.swipe-card.exit-right {{
  transform: translateX(150%) rotate(20deg);
  opacity: 0;
}}

@media (max-width: 600px) {{
  .card-inner {{ padding: 20px; }}
  .header-title {{ font-size: 1.4rem; }}
  .card-body {{ font-size: 14px; }}
}}
</style>
</head>
<body>
  <button class="back-btn" id="backBtn">← Сменить номер</button>

  <div class="header">
    <div class="header-title">Задание №{task_type}</div>
    <div class="header-hint">Наведи на левую часть чтобы пропустить, на правую — решать</div>
  </div>

  <div class="card-wrapper">
    <div class="swipe-card" id="card">
      <div class="card-inner">
        <div class="card-header">
          <span class="badge primary">№{task_number}</span>
          <span class="badge">ID {task_id}</span>
          {source_badge}
          {site_badge}
        </div>
        <div class="card-body">
          {content_html}
        </div>
      </div>
      
      <div class="zone-indicators">
        <div class="zone-indicator left">← Пропустить</div>
        <div class="zone-indicator right">Решать →</div>
      </div>
      
      <div class="click-zones">
        <div class="click-zone" id="zoneLeft"></div>
        <div class="click-zone" id="zoneRight"></div>
      </div>
    </div>
  </div>

<script>
const card = document.getElementById('card');
const zoneLeft = document.getElementById('zoneLeft');
const zoneRight = document.getElementById('zoneRight');
const backBtn = document.getElementById('backBtn');

// Hover effects
zoneLeft.addEventListener('mouseenter', () => {{
  card.classList.remove('hover-right');
  card.classList.add('hover-left');
}});

zoneRight.addEventListener('mouseenter', () => {{
  card.classList.remove('hover-left');
  card.classList.add('hover-right');
}});

card.addEventListener('mouseleave', () => {{
  card.classList.remove('hover-left', 'hover-right');
}});

// Click handlers
zoneLeft.addEventListener('click', () => {{
  card.classList.add('exit-left');
  setTimeout(() => {{
    window.parent.postMessage({{
      type: 'streamlit:setComponentValue',
      value: {{ action: 'skip' }}
    }}, '*');
  }}, 350);
}});

zoneRight.addEventListener('click', () => {{
  card.classList.add('exit-right');
  setTimeout(() => {{
    window.parent.postMessage({{
      type: 'streamlit:setComponentValue',
      value: {{ action: 'accept' }}
    }}, '*');
  }}, 350);
}});

backBtn.addEventListener('click', () => {{
  window.parent.postMessage({{
    type: 'streamlit:setComponentValue',
    value: {{ action: 'back' }}
  }}, '*');
}});
</script>
</body>
</html>
'''
    components.html(html, height=700, scrolling=False)


def _render_task_html(task: dict[str, Any]):
    html = (task.get('content_html') or '').strip()
    if not html:
        st.info("У условия нет HTML-контента.")
        return
    st.markdown(
        f"""
<div style="padding: 20px; background: rgba(255,255,255,0.03); border-radius: 16px; border: 1px solid rgba(255,255,255,0.1);">
  <div style="color: rgba(255,255,255,0.92); line-height: 1.75; font-size: 15px;">
    {html}
  </div>
</div>
        """,
        unsafe_allow_html=True,
    )


def main():
    _inject_minimal_css()
    _init_state()

    token = _get_query_param('token')
    qp_task_id = _get_query_param('task_id')
    qp_task_type = _get_query_param('task_type')
    base_url = get_platform_base_url()

    if not base_url:
        st.error("Не задан `PLATFORM_BASE_URL` (URL платформы Flask).")
        st.stop()
    if not token:
        st.error("Нет token в URL. Открой тренажёр через платформу (/trainer).")
        st.stop()

    client = PlatformClient(base_url=base_url, token=token)

    if st.session_state['me'] is None:
        try:
            me = client.get_me()
            if not me.get('success'):
                raise RuntimeError(me.get('error') or 'unauthorized')
            st.session_state['me'] = me
        except Exception as e:
            st.error(f"Не удалось авторизоваться: {e}")
            st.stop()

    user = (st.session_state['me'] or {}).get('user') or {}
    username = user.get('username') or 'пользователь'

    # Load stats
    counts: dict[int, int] = {}
    try:
        stats = client.get_task_stats()
        raw = (stats.get('counts_by_task_number') or {}) if isinstance(stats, dict) else {}
        if isinstance(raw, dict):
            for k, v in raw.items():
                try:
                    counts[int(k)] = int(v)
                except Exception:
                    continue
    except Exception:
        counts = {}

    # Handle query param task_type
    if qp_task_type and st.session_state.get('task_type') is None:
        try:
            tt = int(qp_task_type)
            if counts.get(tt, 0) > 0:
                st.session_state['task_type'] = tt
        except Exception:
            pass

    task = st.session_state.get('task')
    task_type = st.session_state.get('task_type')
    current_card = st.session_state.get('current_card')

    # ===== STATE 1: No task type — Number Picker =====
    if task_type is None and task is None:
        _render_number_picker_component(counts, username)
        
        # Fallback buttons for selection
        st.markdown("---")
        st.markdown("**Или выбери кнопкой:**")
        cols = st.columns(9)
        for i, n in enumerate(range(1, 28)):
            col_idx = i % 9
            count = counts.get(n, 0)
            with cols[col_idx]:
                if st.button(str(n), key=f"pick_{n}", disabled=count == 0, use_container_width=True):
                    st.session_state['task_type'] = n
                    st.session_state['current_card'] = None
                    st.rerun()
        return

    # ===== STATE 2: Task type selected, show swipe card =====
    if task is None:
        if current_card is None:
            card = _pull_random_task(client, task_type=int(task_type))
            if card:
                st.session_state['current_card'] = card
                current_card = card
            else:
                st.warning("Задания закончились для этого номера.")
                if st.button("← Выбрать другой номер"):
                    st.session_state['task_type'] = None
                    st.session_state['current_card'] = None
                    st.rerun()
                return

        _render_swipe_card_component(current_card, int(task_type))
        
        # Fallback buttons
        st.markdown("---")
        col1, col2, col3 = st.columns([1, 1, 1])
        with col1:
            if st.button("← Сменить номер", use_container_width=True):
                st.session_state['task_type'] = None
                st.session_state['current_card'] = None
                st.rerun()
        with col2:
            if st.button("⬅ Пропустить", use_container_width=True):
                st.session_state['current_card'] = None
                st.rerun()
        with col3:
            if st.button("Решать ➡", use_container_width=True):
                st.session_state['task'] = current_card
                st.session_state['current_card'] = None
                _reset_workbench_state()
                st.rerun()
        return

    # ===== STATE 3: Active task — Workbench =====
    tid = int(task.get('task_id') or 0)
    knowledge = load_task_knowledge(tid) if tid else None
    tests = (knowledge or {}).get('tests') if isinstance(knowledge, dict) else None

    # Header
    st.markdown(f"### Задание №{task.get('task_number')} · ID {task.get('task_id')}")
    
    col1, col2, col3 = st.columns([1, 1, 1])
    with col1:
        if st.button("← К выбору", use_container_width=True):
            st.session_state['task'] = None
            st.session_state['current_card'] = None
            _reset_workbench_state()
            st.rerun()
    with col2:
        if st.button("→ Следующее", use_container_width=True):
            st.session_state['task'] = None
            st.session_state['current_card'] = None
            _reset_workbench_state()
            st.rerun()
    with col3:
        if st.button("💾 Сохранить", use_container_width=True):
            try:
                client.save_session(
                    task_id=task.get('task_id'),
                    task_type=task.get('task_number'),
                    language='python',
                    code=st.session_state.get('code') or '',
                    analysis=st.session_state.get('analysis'),
                    tests=st.session_state.get('tests'),
                    messages=st.session_state.get('messages'),
                )
                st.toast("Сохранено!")
            except Exception as e:
                st.error(f"Ошибка: {e}")

    # Tabs
    tab_task, tab_solve, tab_help, tab_hist = st.tabs(["📄 Условие", "💻 Решение", "💡 Помощник", "📚 История"])

    with tab_task:
        _render_task_html(task)
        if task.get('source_url'):
            st.markdown(f"[Открыть источник ↗]({task.get('source_url')})")

    with tab_solve:
        code_val = ""
        try:
            from streamlit_ace import st_ace
            code_val = st_ace(
                key="code_editor",
                value=st.session_state.get("code") or "",
                language="python",
                theme="dracula",
                height=350,
                font_size=14,
                tab_size=4,
                show_gutter=True,
                wrap=True,
                auto_update=False,
            ) or ""
        except Exception:
            code_val = st.text_area("Код", value=st.session_state.get('code') or "", height=350) or ""

        st.session_state["code"] = code_val[:20000]

        c1, c2 = st.columns(2)
        if c1.button("🔍 Анализ", use_container_width=True):
            st.session_state['analysis'] = analyze_python_code(st.session_state.get('code') or '')
        if c2.button("🗑 Очистить", use_container_width=True):
            st.session_state['code'] = ''
            st.session_state['analysis'] = None

        if st.session_state.get('analysis'):
            with st.expander("Результат анализа"):
                st.json(st.session_state['analysis'])

        st.markdown("### Проверка")
        
        if not is_runner_enabled():
            st.warning("Запуск кода выключен (`TRAINER_ENABLE_RUNNER=1`).")
        else:
            rt0, rt1, rt2 = st.tabs(["✅ Ответ", "▶ Запуск", "🧪 Тесты"])
            
            with rt0:
                expected = task.get('answer') or ''
                user_ans = st.text_input("Твой ответ:", key="ans_input")
                if st.button("Проверить", key="check_ans"):
                    if not expected:
                        st.warning("Нет ответа в базе.")
                    elif not user_ans.strip():
                        st.warning("Введи ответ.")
                    else:
                        ok, _ = _check_answer_match(expected, user_ans)
                        if ok:
                            st.success("✅ Верно!")
                        else:
                            st.error("❌ Неверно.")

            with rt1:
                stdin = st.text_area("stdin:", height=100, key="run_stdin")
                if st.button("▶ Запустить", key="run_btn"):
                    res = run_python_program(code=st.session_state.get('code') or '', stdin=stdin, timeout_seconds=2.0)
                    st.session_state['run_result'] = res
                res = st.session_state.get('run_result')
                if res:
                    if res.get('ok'):
                        st.success("Выполнено")
                    else:
                        st.error(f"Ошибка: {res.get('error')}")
                    st.code(res.get('stdout', '')[:5000])
                    if res.get('stderr'):
                        st.code(res.get('stderr')[:2000])

            with rt2:
                if not tests:
                    st.info("Нет тестов для этой задачи.")
                else:
                    if st.button("🧪 Тесты", key="test_btn"):
                        st.session_state['tests'] = run_python_solve_tests(code=st.session_state.get('code') or '', tests=tests)
                    if st.session_state.get('tests'):
                        _render_tests_block(st.session_state.get('tests'))

    with tab_help:
        ladder = (knowledge or {}).get('hint_ladder') if isinstance(knowledge, dict) else None
        
        if st.button("💡 Подсказка", use_container_width=True):
            cur_lvl = st.session_state.get('hint_level_by_task', {}).get(tid, 0) or 0
            next_hint = None
            next_lvl = cur_lvl
            
            if isinstance(ladder, list) and ladder:
                sorted_l = sorted([(int(x.get('level') or 0), x.get('hint')) for x in ladder if isinstance(x, dict) and x.get('hint')], key=lambda x: x[0] or 999)
                for lvl, htxt in sorted_l:
                    if lvl > cur_lvl:
                        next_lvl = lvl
                        next_hint = htxt
                        break

            if next_hint:
                st.session_state['hint_level_by_task'][tid] = next_lvl
                st.session_state['messages'].append({'role': 'assistant', 'content': f"Подсказка ({next_lvl}): {next_hint}"})
            else:
                try:
                    msgs = build_messages_for_help(task=task, code=st.session_state.get('code') or '', analysis=st.session_state.get('analysis'), history=st.session_state.get('messages', []) + [{'role': 'user', 'content': 'Дай подсказку.'}], knowledge=knowledge)
                    answer = None
                    try:
                        pr = client.llm_chat(messages=msgs, temperature=0.2, max_tokens=500, task_id=tid, task_type=int(task.get('task_number') or 0))
                        answer = pr.get('answer') if isinstance(pr, dict) else None
                    except Exception:
                        llm = get_llm_client()
                        if llm:
                            answer = llm.chat(messages=msgs, temperature=0.2, max_tokens=500)
                    st.session_state['messages'].append({'role': 'assistant', 'content': (answer or '').strip() or 'Расскажи, что уже сделал.'})
                except Exception as e:
                    st.session_state['messages'].append({'role': 'assistant', 'content': f'Ошибка: {e}'})

        for m in st.session_state.get('messages', []):
            with st.chat_message(m.get('role', 'assistant')):
                st.markdown(m.get('content', ''))

        prompt = st.chat_input("Вопрос помощнику...")
        if prompt:
            st.session_state['messages'].append({'role': 'user', 'content': prompt})
            try:
                msgs = build_messages_for_help(task=task, code=st.session_state.get('code') or '', analysis=st.session_state.get('analysis'), history=st.session_state.get('messages'), knowledge=knowledge)
                answer = None
                try:
                    pr = client.llm_chat(messages=msgs, temperature=0.2, max_tokens=700, task_id=tid, task_type=int(task.get('task_number') or 0))
                    answer = pr.get('answer') if isinstance(pr, dict) else None
                except Exception:
                    llm = get_llm_client()
                    if llm:
                        answer = llm.chat(messages=msgs, temperature=0.2, max_tokens=700)
                st.session_state['messages'].append({'role': 'assistant', 'content': (answer or '').strip() or 'LLM не настроен.'})
            except Exception as e:
                st.session_state['messages'].append({'role': 'assistant', 'content': f'Ошибка: {e}'})
            st.rerun()

    with tab_hist:
        if st.button("Обновить", key="hist_refresh"):
            st.session_state['history_loaded'] = False
        if not st.session_state.get('history_loaded'):
            try:
                h = client.list_sessions(limit=25)
                st.session_state['history_items'] = h.get('sessions', []) if isinstance(h, dict) else []
                st.session_state['history_loaded'] = True
            except Exception as e:
                st.caption(f"Ошибка: {e}")
                st.session_state['history_items'] = []
                st.session_state['history_loaded'] = True

        items = st.session_state.get('history_items', [])
        if not items:
            st.info("Нет сохранённых попыток.")
        else:
            labels = [f"#{it.get('session_id')} · №{it.get('task_type')} · {it.get('created_at')}" for it in items]
            sel = st.selectbox("Попытка:", range(len(labels)), format_func=lambda i: labels[i], key="hist_sel")
            if st.button("Загрузить", key="hist_load"):
                try:
                    sid = items[sel].get('session_id')
                    if sid:
                        resp = client.get_session(int(sid))
                        sess = resp.get('session', {}) if isinstance(resp, dict) else {}
                        if resp.get('task'):
                            st.session_state['task'] = resp['task']
                        st.session_state['code'] = sess.get('code', '')
                        st.session_state['analysis'] = sess.get('analysis')
                        st.session_state['messages'] = sess.get('messages', []) if isinstance(sess.get('messages'), list) else []
                        st.rerun()
                except Exception as e:
                    st.error(f"Ошибка: {e}")


if __name__ == '__main__':
    main()
