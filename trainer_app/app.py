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
    # Load repo root .env and trainer_app/.env if present (best-effort)
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    load_dotenv(os.path.join(repo_root, '.env'), override=False)
    load_dotenv(os.path.join(os.path.dirname(__file__), '.env'), override=False)
except Exception:
    pass


def _inject_css():
    st.markdown(
        """
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap');

  /* Hide default Streamlit chrome */
  #MainMenu {visibility: hidden;}
  footer {visibility: hidden;}
  header {visibility: hidden;}

  html, body, [class*="css"] { font-family: Inter, system-ui, -apple-system, Segoe UI, Roboto, Arial; }

  /* Premium dark background */
  .stApp {
    background:
      radial-gradient(ellipse 1200px 800px at 10% 20%, rgba(99,102,241,0.22), transparent 55%),
      radial-gradient(ellipse 1000px 700px at 90% 10%, rgba(16,185,129,0.18), transparent 50%),
      radial-gradient(ellipse 900px 600px at 50% 90%, rgba(59,130,246,0.12), transparent 50%),
      linear-gradient(180deg, #0a0c12 0%, #070910 100%);
    min-height: 100vh;
  }
  .block-container { padding-top: 0.8rem; padding-bottom: 1.5rem; }

  .stChatInputContainer { padding-top: 0.25rem; }

  /* ===== Number picker panel ===== */
  .number-picker-panel {
    display: flex;
    flex-wrap: wrap;
    gap: 10px;
    justify-content: center;
    padding: 20px 16px;
    background: linear-gradient(160deg, rgba(255,255,255,0.04), rgba(255,255,255,0.015));
    border: 1px solid rgba(255,255,255,0.10);
    border-radius: 20px;
    box-shadow: 0 20px 50px rgba(0,0,0,0.35);
    margin-bottom: 24px;
  }

  .number-btn {
    width: 52px;
    height: 52px;
    border-radius: 14px;
    border: 1px solid rgba(255,255,255,0.12);
    background: linear-gradient(160deg, rgba(255,255,255,0.06), rgba(255,255,255,0.02));
    color: rgba(255,255,255,0.75);
    font-weight: 700;
    font-size: 16px;
    cursor: pointer;
    transition: all 0.2s ease;
    display: flex;
    align-items: center;
    justify-content: center;
  }

  .number-btn:hover {
    border-color: rgba(0,255,213,0.5);
    background: linear-gradient(160deg, rgba(0,255,213,0.12), rgba(0,255,213,0.04));
    color: #00ffd5;
    transform: translateY(-2px);
    box-shadow: 0 8px 24px rgba(0,255,213,0.20);
  }

  .number-btn.active {
    border-color: rgba(0,255,213,0.8);
    background: linear-gradient(160deg, rgba(0,255,213,0.25), rgba(0,255,213,0.10));
    color: #00ffd5;
    box-shadow: 0 0 20px rgba(0,255,213,0.30);
  }

  .number-btn.empty {
    opacity: 0.35;
    cursor: not-allowed;
  }

  /* ===== TikTok-style fullscreen card ===== */
  .swipe-card-container {
    position: relative;
    width: 100%;
    max-width: 900px;
    margin: 0 auto;
    min-height: 70vh;
  }

  .swipe-card {
    position: relative;
    width: 100%;
    min-height: 65vh;
    border-radius: 28px;
    border: 2px solid rgba(255,255,255,0.10);
    background: linear-gradient(165deg, rgba(18,20,30,0.98), rgba(12,14,22,0.96));
    box-shadow:
      0 30px 80px rgba(0,0,0,0.50),
      0 0 0 1px rgba(255,255,255,0.04) inset;
    overflow: hidden;
    transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1);
    cursor: pointer;
  }

  .swipe-card.hover-left {
    border-color: rgba(239,68,68,0.7);
    background: linear-gradient(165deg, rgba(50,15,20,0.98), rgba(25,10,15,0.96));
    box-shadow:
      0 30px 80px rgba(239,68,68,0.25),
      0 0 60px rgba(239,68,68,0.10) inset;
  }

  .swipe-card.hover-right {
    border-color: rgba(16,185,129,0.7);
    background: linear-gradient(165deg, rgba(10,40,30,0.98), rgba(8,25,20,0.96));
    box-shadow:
      0 30px 80px rgba(16,185,129,0.25),
      0 0 60px rgba(16,185,129,0.10) inset;
  }

  .swipe-card-inner {
    padding: 32px 36px;
    position: relative;
    z-index: 2;
  }

  .swipe-card-header {
    display: flex;
    align-items: center;
    gap: 12px;
    margin-bottom: 20px;
    flex-wrap: wrap;
  }

  .swipe-badge {
    display: inline-flex;
    align-items: center;
    padding: 6px 14px;
    border-radius: 999px;
    font-size: 13px;
    font-weight: 600;
    border: 1px solid rgba(255,255,255,0.14);
    background: rgba(255,255,255,0.05);
    color: rgba(255,255,255,0.85);
  }

  .swipe-badge.primary {
    border-color: rgba(0,255,213,0.5);
    background: rgba(0,255,213,0.12);
    color: #00ffd5;
  }

  .swipe-card-body {
    color: rgba(255,255,255,0.92);
    font-size: 16px;
    line-height: 1.75;
    max-height: 50vh;
    overflow-y: auto;
    padding-right: 8px;
  }

  .swipe-card-body::-webkit-scrollbar {
    width: 6px;
  }
  .swipe-card-body::-webkit-scrollbar-track {
    background: rgba(255,255,255,0.04);
    border-radius: 3px;
  }
  .swipe-card-body::-webkit-scrollbar-thumb {
    background: rgba(255,255,255,0.15);
    border-radius: 3px;
  }

  /* Zone hints */
  .zone-hints {
    position: absolute;
    bottom: 0;
    left: 0;
    right: 0;
    display: flex;
    pointer-events: none;
    z-index: 5;
  }

  .zone-hint {
    flex: 1;
    padding: 18px 24px;
    text-align: center;
    font-weight: 700;
    font-size: 14px;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    opacity: 0.5;
    transition: opacity 0.2s ease;
  }

  .zone-hint.left {
    color: #ef4444;
    background: linear-gradient(0deg, rgba(239,68,68,0.15), transparent);
  }

  .zone-hint.right {
    color: #10b981;
    background: linear-gradient(0deg, rgba(16,185,129,0.15), transparent);
  }

  .swipe-card.hover-left .zone-hint.left { opacity: 1; }
  .swipe-card.hover-right .zone-hint.right { opacity: 1; }

  /* Click zones overlay */
  .click-zones {
    position: absolute;
    inset: 0;
    display: flex;
    z-index: 10;
  }

  .click-zone {
    flex: 1;
    cursor: pointer;
  }

  /* ===== Utilities ===== */
  .k-card {
    border: 1px solid rgba(255,255,255,0.10);
    border-radius: 16px;
    padding: 16px 18px;
    background: rgba(255,255,255,0.035);
    box-shadow: 0 14px 35px rgba(0,0,0,0.30);
    backdrop-filter: blur(12px);
  }

  .k-muted { color: rgba(255,255,255,0.65); }
  .k-title { font-weight: 800; letter-spacing: -0.02em; color: #fff; }

  .k-badge {
    display: inline-block;
    padding: 5px 12px;
    border-radius: 999px;
    font-size: 12px;
    font-weight: 600;
    border: 1px solid rgba(255,255,255,0.14);
    background: rgba(255,255,255,0.05);
    margin-right: 6px;
  }
  .k-badge.ok { border-color: rgba(34,197,94,0.55); background: rgba(34,197,94,0.12); color: #22c55e; }
  .k-badge.warn { border-color: rgba(245,158,11,0.55); background: rgba(245,158,11,0.12); color: #f59e0b; }
  .k-badge.err { border-color: rgba(239,68,68,0.55); background: rgba(239,68,68,0.12); color: #ef4444; }

  /* ===== Workbench styling ===== */
  div[data-testid="stCustomComponentV1"] iframe {
    border-radius: 16px;
    border: 1px solid rgba(255,255,255,0.12);
    background: rgba(0,0,0,0.30);
    box-shadow: 0 16px 40px rgba(0,0,0,0.40);
  }

  div.stButton > button {
    border-radius: 14px !important;
    border: 1px solid rgba(255,255,255,0.12) !important;
    background: linear-gradient(180deg, rgba(255,255,255,0.07), rgba(255,255,255,0.02)) !important;
    color: rgba(255,255,255,0.90) !important;
    font-weight: 600 !important;
    padding: 0.65rem 1rem !important;
    transition: all 0.15s ease;
  }
  div.stButton > button:hover {
    border-color: rgba(0,255,213,0.4) !important;
    background: linear-gradient(180deg, rgba(0,255,213,0.10), rgba(0,255,213,0.03)) !important;
    color: #00ffd5 !important;
    transform: translateY(-1px);
  }

  div[data-baseweb="input"] input,
  div[data-baseweb="textarea"] textarea {
    border-radius: 14px !important;
    border: 1px solid rgba(255,255,255,0.10) !important;
    background: rgba(255,255,255,0.03) !important;
  }

  button[data-baseweb="tab"] {
    border-radius: 999px !important;
    margin-right: 8px !important;
    padding: 8px 16px !important;
    font-weight: 600 !important;
  }

  /* Hero section */
  .hero-section {
    text-align: center;
    padding: 24px 16px 8px;
    margin-bottom: 16px;
  }

  .hero-title {
    font-size: 2.2rem;
    font-weight: 900;
    letter-spacing: -0.03em;
    background: linear-gradient(135deg, #fff 0%, rgba(255,255,255,0.75) 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
    margin-bottom: 8px;
  }

  .hero-subtitle {
    font-size: 1rem;
    color: rgba(255,255,255,0.55);
    font-weight: 500;
  }

  /* Stats bar */
  .stats-bar {
    display: flex;
    justify-content: center;
    gap: 24px;
    margin-bottom: 20px;
    flex-wrap: wrap;
  }

  .stat-item {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 8px 16px;
    border-radius: 12px;
    background: rgba(255,255,255,0.04);
    border: 1px solid rgba(255,255,255,0.08);
  }

  .stat-value {
    font-weight: 700;
    font-size: 14px;
    color: #00ffd5;
  }

  .stat-label {
    font-size: 13px;
    color: rgba(255,255,255,0.55);
  }
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
        validation = tests_payload.get("validation")
        if details:
            st.code(str(details)[:4000])
        if validation:
            st.caption("Диагностика (валидация):")
            st.code(json.dumps(validation, ensure_ascii=False, indent=2)[:8000], language="json")
        return

    results = tests_payload.get("results") or []
    if not isinstance(results, list) or not results:
        st.warning("Тесты вернули пустой результат.")
        st.code(json.dumps(tests_payload, ensure_ascii=False, indent=2)[:8000], language="json")
        return

    ok_cnt = 0
    rows: list[dict[str, Any]] = []
    for r in results:
        if not isinstance(r, dict):
            continue
        ok = bool(r.get("ok"))
        ok_cnt += 1 if ok else 0
        rows.append(
            {
                "OK": "✅" if ok else "❌",
                "Тест": r.get("name") or "",
                "Ожидалось": r.get("expected") if r.get("expected") is not None else "",
                "Получилось": r.get("got") if r.get("got") is not None else "",
            }
        )

    total = len(rows)
    if ok_cnt == total:
        st.success(f"Все тесты пройдены: {ok_cnt}/{total}")
    else:
        st.warning(f"Пройдено тестов: {ok_cnt}/{total}")

    st.dataframe(rows, use_container_width=True, hide_index=True)

    failed_errs = []
    for r in results:
        if isinstance(r, dict) and not r.get("ok") and r.get("error"):
            failed_errs.append({"name": r.get("name"), "error": r.get("error")})
    if failed_errs:
        with st.expander("Ошибки в тестах (traceback)", expanded=False):
            for fe in failed_errs[:20]:
                st.markdown(f"**{fe.get('name') or 'тест'}**")
                st.code(str(fe.get("error") or "")[:6000])


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
    st.session_state.setdefault('swipe_action', None)


def _render_task_html(task: dict[str, Any]):
    html = (task.get('content_html') or '').strip()
    if not html:
        st.info("У условия нет HTML-контента.")
        return
    st.markdown(
        f"""
<div class="k-card" style="padding: 18px 20px;">
  <div style="color: rgba(255,255,255,0.92); line-height: 1.7; font-size: 15px;">
    {html}
  </div>
</div>
        """,
        unsafe_allow_html=True,
    )


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


def _render_swipe_card(task: dict[str, Any], card_key: str) -> str | None:
    """
    Render TikTok-style swipe card with left/right click zones.
    Returns 'skip' or 'accept' or None.
    """
    task_id = task.get('task_id') or 0
    task_number = task.get('task_number') or '?'
    source_url = task.get('source_url') or ''
    site_task_id = task.get('site_task_id') or ''
    content_html = (task.get('content_html') or '').strip()

    # Build header badges
    header_html = f'<span class="swipe-badge primary">№{task_number}</span>'
    header_html += f'<span class="swipe-badge">ID {task_id}</span>'
    if source_url:
        header_html += f'<a href="{source_url}" target="_blank" class="swipe-badge" style="text-decoration:none;color:inherit;">Источник ↗</a>'
    if site_task_id:
        header_html += f'<span class="swipe-badge">{site_task_id}</span>'

    # Interactive card with JavaScript
    card_html = f"""
    <div class="swipe-card-container">
      <div class="swipe-card" id="swipe-card-{card_key}">
        <div class="swipe-card-inner">
          <div class="swipe-card-header">
            {header_html}
          </div>
          <div class="swipe-card-body">
            {content_html}
          </div>
        </div>
        <div class="zone-hints">
          <div class="zone-hint left">← Пропустить</div>
          <div class="zone-hint right">Решать →</div>
        </div>
        <div class="click-zones">
          <div class="click-zone" id="zone-left-{card_key}"></div>
          <div class="click-zone" id="zone-right-{card_key}"></div>
        </div>
      </div>
    </div>

    <script>
    (function() {{
      const card = document.getElementById('swipe-card-{card_key}');
      const zoneLeft = document.getElementById('zone-left-{card_key}');
      const zoneRight = document.getElementById('zone-right-{card_key}');

      if (!card || !zoneLeft || !zoneRight) return;

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

      zoneLeft.addEventListener('click', (e) => {{
        e.stopPropagation();
        card.style.transform = 'translateX(-120%) rotate(-15deg)';
        card.style.opacity = '0';
        setTimeout(() => {{
          window.parent.postMessage({{ type: 'swipe_action', action: 'skip', key: '{card_key}' }}, '*');
        }}, 200);
      }});

      zoneRight.addEventListener('click', (e) => {{
        e.stopPropagation();
        card.style.transform = 'translateX(120%) rotate(15deg)';
        card.style.opacity = '0';
        setTimeout(() => {{
          window.parent.postMessage({{ type: 'swipe_action', action: 'accept', key: '{card_key}' }}, '*');
        }}, 200);
      }});
    }})();
    </script>
    """

    # Render and listen for action
    components.html(card_html, height=650, scrolling=False)

    # Check for action via query params (workaround for Streamlit)
    action = st.session_state.get('swipe_action')
    if action:
        st.session_state['swipe_action'] = None
        return action

    return None


def _render_number_picker(counts: dict[int, int], current: int | None) -> int | None:
    """Render beautiful number picker panel. Returns selected number or None."""
    buttons_html = ""
    for n in range(1, 28):
        count = counts.get(n, 0)
        active_class = "active" if n == current else ""
        empty_class = "empty" if count == 0 else ""
        title = f"{count} заданий" if count > 0 else "Нет заданий"
        buttons_html += f'<button class="number-btn {active_class} {empty_class}" data-num="{n}" title="{title}" {"disabled" if count == 0 else ""}>{n}</button>'

    picker_html = f"""
    <div class="number-picker-panel" id="number-picker">
      {buttons_html}
    </div>
    <script>
    (function() {{
      const panel = document.getElementById('number-picker');
      if (!panel) return;
      panel.querySelectorAll('.number-btn:not(.empty)').forEach(btn => {{
        btn.addEventListener('click', () => {{
          const num = btn.getAttribute('data-num');
          window.parent.postMessage({{ type: 'select_number', number: parseInt(num) }}, '*');
        }});
      }});
    }})();
    </script>
    """
    components.html(picker_html, height=100, scrolling=False)
    return None


def main():
    _inject_css()
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

    # ===== STATE: No task type selected — show picker =====
    if task_type is None and task is None:
        st.markdown(
            """
            <div class="hero-section">
              <div class="hero-title">Тренажёр КЕГЭ</div>
              <div class="hero-subtitle">Выбери номер задания и начни тренировку</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        # Stats bar
        total_tasks = sum(counts.values())
        available_numbers = len([n for n, c in counts.items() if c > 0])
        st.markdown(
            f"""
            <div class="stats-bar">
              <div class="stat-item">
                <span class="stat-value">{total_tasks}</span>
                <span class="stat-label">заданий в базе</span>
              </div>
              <div class="stat-item">
                <span class="stat-value">{available_numbers}</span>
                <span class="stat-label">номеров доступно</span>
              </div>
              <div class="stat-item">
                <span class="stat-value">{username}</span>
                <span class="stat-label">пользователь</span>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        st.markdown("#### Выбери номер задания")

        # Number picker with Streamlit buttons (for reliable interaction)
        cols = st.columns(9)
        for i, n in enumerate(range(1, 28)):
            col_idx = i % 9
            count = counts.get(n, 0)
            with cols[col_idx]:
                disabled = count == 0
                label = f"{n}" if count > 0 else f"~{n}~"
                if st.button(
                    label,
                    key=f"pick_{n}",
                    disabled=disabled,
                    use_container_width=True,
                    help=f"{count} заданий" if count > 0 else "Нет заданий",
                ):
                    st.session_state['task_type'] = n
                    st.session_state['current_card'] = None
                    st.rerun()

        return

    # ===== STATE: Task type selected, no active task — show swipe card =====
    if task is None:
        # Load card if needed
        if current_card is None:
            card = _pull_random_task(client, task_type=int(task_type))
            if card:
                st.session_state['current_card'] = card
                current_card = card
            else:
                st.warning("Задания закончились. Попробуй другой номер.")
                if st.button("← Выбрать другой номер"):
                    st.session_state['task_type'] = None
                    st.session_state['current_card'] = None
                    st.rerun()
                return

        # Header
        st.markdown(
            f"""
            <div class="hero-section" style="padding-bottom:0;">
              <div class="hero-title">Задание №{task_type}</div>
              <div class="hero-subtitle">Нажми на левую половину чтобы пропустить, на правую — чтобы решать</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        # Back button
        col1, col2, col3 = st.columns([1, 2, 1])
        with col1:
            if st.button("← Сменить номер", use_container_width=True):
                st.session_state['task_type'] = None
                st.session_state['current_card'] = None
                st.rerun()

        # Render the swipe card
        card_key = f"card_{current_card.get('task_id', 0)}"
        _render_swipe_card(current_card, card_key)

        # Action buttons as fallback (below card)
        st.markdown("")
        bcol1, bcol2 = st.columns(2, gap="large")
        with bcol1:
            if st.button("⬅ Пропустить", use_container_width=True, key="btn_skip"):
                st.session_state['current_card'] = None
                st.rerun()
        with bcol2:
            if st.button("Решать ➡", use_container_width=True, key="btn_accept"):
                st.session_state['task'] = current_card
                st.session_state['current_card'] = None
                _reset_workbench_state()
                st.rerun()

        return

    # ===== STATE: Active task — workbench =====
    tid = int(task.get('task_id') or 0)
    knowledge = load_task_knowledge(tid) if tid else None
    tests = (knowledge or {}).get('tests') if isinstance(knowledge, dict) else None

    # Header
    st.markdown(
        f"""
        <div style="display:flex; align-items:center; gap:16px; margin-bottom:16px; flex-wrap:wrap;">
          <span class="swipe-badge primary" style="font-size:15px;">№{task.get('task_number')}</span>
          <span class="swipe-badge">ID {task.get('task_id')}</span>
          <span class="k-muted">Решаем задание</span>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # Action bar
    a1, a2, a3 = st.columns([1, 1, 1], gap="small")
    with a1:
        if st.button("← К выбору карточки", use_container_width=True):
            st.session_state['task'] = None
            st.session_state['current_card'] = None
            _reset_workbench_state()
            st.rerun()
    with a2:
        if st.button("→ Следующее задание", use_container_width=True):
            st.session_state['task'] = None
            st.session_state['current_card'] = None
            _reset_workbench_state()
            st.rerun()
    with a3:
        if st.button("💾 Сохранить прогресс", use_container_width=True):
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
                st.toast("Сохранено")
            except Exception as e:
                st.error(f"Не удалось сохранить: {e}")

    # Main workbench
    tab_task, tab_solve, tab_help, tab_hist = st.tabs(["📄 Условие", "💻 Решение", "💡 Помощник", "📚 История"])

    with tab_task:
        _render_task_html(task)
        if task.get('source_url'):
            st.markdown(f"[Открыть источник ↗]({task.get('source_url')})")

    with tab_solve:
        st.markdown("### Код")

        code_val = ""
        try:
            from streamlit_ace import st_ace
            code_val = st_ace(
                key="code_editor",
                value=st.session_state.get("code") or "",
                language="python",
                theme="dracula",
                keybinding="vscode",
                height=380,
                min_lines=18,
                font_size=14,
                tab_size=4,
                show_gutter=True,
                wrap=True,
                auto_update=False,
            ) or ""
        except Exception:
            code_val = st.text_area(
                "Код",
                value=st.session_state.get('code') or "",
                height=380,
                placeholder="print('hello')",
            ) or ""

        if len(code_val) > 20000:
            st.warning("Код слишком большой, обрезаю до 20 000 символов.")
            code_val = code_val[:20000]
        st.session_state["code"] = code_val

        c1, c2, c3 = st.columns([1, 1, 1], gap="small")
        if c1.button("🔍 Анализ кода", use_container_width=True, key="btn_analyze"):
            st.session_state['analysis'] = analyze_python_code(st.session_state.get('code') or '')
            hints = (st.session_state['analysis'] or {}).get('hints') or []
            if hints:
                st.session_state['messages'].append({'role': 'assistant', 'content': 'Что я заметил:\n\n- ' + '\n- '.join(hints[:4])})
        if c2.button("🗑 Очистить", use_container_width=True, key="btn_clear_code"):
            st.session_state['code'] = ''
            st.session_state['analysis'] = None
            st.session_state['tests'] = None
        if c3.button("🔄 Сброс чата", use_container_width=True, key="btn_reset_help"):
            st.session_state['messages'] = []
            if tid:
                st.session_state['hint_level_by_task'][tid] = 0

        if st.session_state.get('analysis'):
            with st.expander("Результат анализа", expanded=False):
                st.code(json.dumps(st.session_state['analysis'], ensure_ascii=False, indent=2), language="json")

        st.markdown("### Проверка")

        if not is_runner_enabled():
            st.warning("Запуск кода выключен. Включи `TRAINER_ENABLE_RUNNER=1`.")
        else:
            rt0, rt1, rt2 = st.tabs(["✅ Проверить ответ", "▶ Запустить код", "🧪 Тесты"])

            with rt0:
                expected_answer = (task.get('answer') or '')
                user_answer = st.text_input("Твой ответ", key="answer_input")
                if st.button("Проверить", use_container_width=True, key="btn_check_answer"):
                    if not expected_answer:
                        st.warning("В базе нет правильного ответа.")
                    elif not (user_answer or "").strip():
                        st.warning("Введи ответ.")
                    else:
                        ok, _ = _check_answer_match(expected_answer, user_answer)
                        if ok:
                            st.success("✅ Верно!")
                        else:
                            st.error("❌ Неверно. Попробуй ещё.")

            with rt1:
                stdin_val = st.text_area("Ввод (stdin)", height=100, key="run_stdin", placeholder="5\n1 2 3 4 5")
                expect = st.text_area("Ожидаемый вывод (опционально)", height=80, key="run_expected")

                if st.button("▶ Запустить", use_container_width=True, key="btn_run"):
                    res = run_python_program(code=st.session_state.get('code') or '', stdin=stdin_val, timeout_seconds=2.0)
                    st.session_state['run_result'] = res

                res = st.session_state.get('run_result')
                if isinstance(res, dict):
                    if res.get('ok'):
                        st.success("Выполнено")
                    else:
                        st.error(f"Ошибка: {res.get('error')}")
                        if res.get('details'):
                            st.code(str(res.get('details'))[:3000])

                    st.markdown("**stdout:**")
                    st.code((res.get('stdout') or '')[:8000])
                    if res.get('stderr'):
                        st.markdown("**stderr:**")
                        st.code(res.get('stderr')[:4000])

                    if (expect or '').strip():
                        if (res.get('stdout') or '').strip() == expect.strip():
                            st.success("Вывод совпал!")
                        else:
                            st.warning("Вывод не совпал.")

            with rt2:
                if not tests:
                    st.info("Для этой задачи нет тестов.")
                else:
                    if st.button("🧪 Запустить тесты", use_container_width=True, key="btn_tests"):
                        st.session_state['tests'] = run_python_solve_tests(code=st.session_state.get('code') or '', tests=tests)
                    if st.session_state.get('tests'):
                        _render_tests_block(st.session_state.get('tests'))

    with tab_help:
        ladder = (knowledge or {}).get('hint_ladder') if isinstance(knowledge, dict) else None
        max_lvl = 0
        if isinstance(ladder, list):
            for it in ladder:
                if isinstance(it, dict) and it.get('level'):
                    try:
                        max_lvl = max(max_lvl, int(it.get('level') or 0))
                    except Exception:
                        continue
            if max_lvl <= 0:
                max_lvl = len([it for it in ladder if isinstance(it, dict) and it.get('hint')])
        cur_lvl = int((st.session_state.get('hint_level_by_task') or {}).get(tid, 0) or 0)
        if max_lvl > 0:
            st.progress(min(1.0, float(cur_lvl) / float(max_lvl)))
            st.caption(f"Подсказки: {cur_lvl}/{max_lvl}")

        if st.button("💡 Следующая подсказка", use_container_width=True, key="btn_hint"):
            current_level = cur_lvl
            next_hint = None
            next_level = current_level
            if isinstance(ladder, list) and ladder:
                sorted_ladder = []
                for item in ladder:
                    if isinstance(item, dict) and item.get('hint'):
                        try:
                            lvl = int(item.get('level') or 0)
                        except Exception:
                            lvl = 0
                        sorted_ladder.append((lvl, str(item.get('hint'))))
                sorted_ladder.sort(key=lambda x: (x[0] if x[0] else 10**9))
                if all(lvl == 0 for (lvl, _) in sorted_ladder):
                    sorted_ladder = list(enumerate([h for (_, h) in sorted_ladder], start=1))
                for (lvl, htxt) in sorted_ladder:
                    if int(lvl) > int(current_level):
                        next_level = int(lvl)
                        next_hint = htxt
                        break

            if next_hint:
                st.session_state['hint_level_by_task'][tid] = next_level
                st.session_state['messages'].append({'role': 'assistant', 'content': f"Подсказка ({next_level}): {next_hint}"})
            else:
                try:
                    msgs = build_messages_for_help(
                        task=task,
                        code=st.session_state.get('code') or '',
                        analysis=st.session_state.get('analysis'),
                        history=(st.session_state.get('messages') or []) + [{'role': 'user', 'content': 'Дай подсказку (не решение).'}],
                        knowledge=knowledge,
                    )
                    answer = None
                    try:
                        pr = client.llm_chat(messages=msgs, temperature=0.2, max_tokens=500, task_id=tid, task_type=int(task.get('task_number') or 0))
                        answer = (pr.get('answer') or '') if isinstance(pr, dict) else None
                    except Exception:
                        llm = get_llm_client()
                        if llm:
                            answer = llm.chat(messages=msgs, temperature=0.2, max_tokens=500)
                    answer = (answer or '').strip() or 'Сформулируй, что уже сделал и где застрял.'
                    st.session_state['messages'].append({'role': 'assistant', 'content': answer})
                except Exception as e:
                    st.session_state['messages'].append({'role': 'assistant', 'content': f'Ошибка: {e}'})

        st.markdown("### Чат")
        for m in st.session_state.get('messages') or []:
            with st.chat_message(m.get('role') or 'assistant'):
                st.markdown(m.get('content') or '')

        prompt = st.chat_input("Задай вопрос помощнику…")
        if prompt:
            st.session_state['messages'].append({'role': 'user', 'content': prompt})
            try:
                msgs = build_messages_for_help(
                    task=task,
                    code=st.session_state.get('code') or '',
                    analysis=st.session_state.get('analysis'),
                    history=st.session_state.get('messages'),
                    knowledge=knowledge,
                )
                answer = None
                try:
                    pr = client.llm_chat(messages=msgs, temperature=0.2, max_tokens=700, task_id=tid, task_type=int(task.get('task_number') or 0))
                    answer = (pr.get('answer') or '') if isinstance(pr, dict) else None
                except Exception:
                    llm = get_llm_client()
                    if llm:
                        answer = llm.chat(messages=msgs, temperature=0.2, max_tokens=700)
                if not answer:
                    st.session_state['messages'].append({'role': 'assistant', 'content': 'LLM не настроен.'})
                else:
                    st.session_state['messages'].append({'role': 'assistant', 'content': answer.strip()})
            except Exception as e:
                st.session_state['messages'].append({'role': 'assistant', 'content': f'Ошибка: {e}'})
            st.rerun()

    with tab_hist:
        if st.button("Обновить историю", use_container_width=True, key="btn_hist_refresh"):
            st.session_state['history_loaded'] = False
        if not st.session_state.get('history_loaded'):
            try:
                h = client.list_sessions(limit=25)
                st.session_state['history_items'] = (h.get('sessions') or []) if isinstance(h, dict) else []
                st.session_state['history_loaded'] = True
            except Exception as e:
                st.caption(f"История недоступна: {e}")
                st.session_state['history_items'] = []
                st.session_state['history_loaded'] = True

        items = st.session_state.get('history_items') or []
        if not items:
            st.info("Нет сохранённых попыток.")
        else:
            options = []
            for it in items:
                label = f"#{it.get('session_id')} · №{it.get('task_type')} · {it.get('created_at')}"
                options.append((label, it))
            labels = [o[0] for o in options]
            sel = st.selectbox("Выбери попытку", options=list(range(len(labels))), format_func=lambda i: labels[i], key="hist_sel")
            sel_item = options[int(sel)][1]
            if st.button("Загрузить", use_container_width=True, key="btn_hist_load"):
                try:
                    sid = int(sel_item.get('session_id') or 0)
                    if sid:
                        resp = client.get_session(sid)
                        sess = (resp.get('session') or {}) if isinstance(resp, dict) else {}
                        task_payload = resp.get('task') if isinstance(resp, dict) else None

                        if task_payload:
                            st.session_state['task'] = task_payload
                        else:
                            tid2 = int(sess.get('task_id') or 0)
                            if tid2:
                                t_resp = client.get_task(tid2)
                                tsk2 = t_resp.get('task') if isinstance(t_resp, dict) else None
                                if tsk2:
                                    st.session_state['task'] = tsk2

                        st.session_state['code'] = (sess.get('code') or '')
                        st.session_state['analysis'] = sess.get('analysis')
                        st.session_state['tests'] = sess.get('tests')
                        msgs = sess.get('messages')
                        st.session_state['messages'] = msgs if isinstance(msgs, list) else []

                        if st.session_state.get('task') and st.session_state['task'].get('task_id'):
                            st.session_state['hint_level_by_task'][int(st.session_state['task']['task_id'])] = 0
                        st.rerun()
                except Exception as e:
                    st.error(f"Не удалось открыть: {e}")


if __name__ == '__main__':
    main()
