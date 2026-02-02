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
    # Streamlit allows limited styling; this keeps UI cleaner and more "product-like".
    st.markdown(
        """
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

  /* Hide default Streamlit chrome */
  #MainMenu {visibility: hidden;}
  footer {visibility: hidden;}
  header {visibility: hidden;}

  html, body, [class*="css"] { font-family: Inter, system-ui, -apple-system, Segoe UI, Roboto, Arial; }

  /* Reduce top padding + add premium background */
  .stApp {
    background:
      radial-gradient(900px 600px at 15% 10%, rgba(99,102,241,0.18), transparent 60%),
      radial-gradient(900px 600px at 85% 15%, rgba(16,185,129,0.12), transparent 55%),
      radial-gradient(900px 600px at 50% 85%, rgba(59,130,246,0.10), transparent 55%),
      linear-gradient(180deg, rgba(10,12,18,1) 0%, rgba(7,9,14,1) 100%);
  }
  .block-container { padding-top: 1.05rem; padding-bottom: 2.2rem; }

  /* Make chat/input feel tighter */
  .stChatInputContainer { padding-top: 0.25rem; }

  /* Card-ish containers */
  .k-card {
    border: 1px solid rgba(255,255,255,0.10);
    border-radius: 14px;
    padding: 14px 14px;
    background: rgba(255,255,255,0.035);
    box-shadow: 0 12px 30px rgba(0,0,0,0.28);
    backdrop-filter: blur(10px);
  }
  .k-muted { color: rgba(255,255,255,0.70); }
  .k-title { font-weight: 700; letter-spacing: -0.02em; }
  .k-badge {
    display: inline-block;
    padding: 4px 10px;
    border-radius: 999px;
    font-size: 12px;
    border: 1px solid rgba(255,255,255,0.14);
    background: rgba(255,255,255,0.04);
    margin-right: 6px;
  }
  .k-badge.ok { border-color: rgba(34,197,94,0.55); background: rgba(34,197,94,0.10); }
  .k-badge.warn { border-color: rgba(245,158,11,0.55); background: rgba(245,158,11,0.10); }
  .k-badge.err { border-color: rgba(239,68,68,0.55); background: rgba(239,68,68,0.10); }

  .k-panel {
    border: 1px solid rgba(255,255,255,0.12);
    border-radius: 16px;
    padding: 16px 16px;
    background: linear-gradient(160deg, rgba(255,255,255,0.05), rgba(255,255,255,0.02));
    box-shadow: 0 12px 30px rgba(0,0,0,0.30);
  }

  .task-choice-stack { display: grid; gap: 14px; }

  .task-choice-card {
    position: relative;
    border-radius: 16px;
    border: 1px solid rgba(255,255,255,0.12);
    background: linear-gradient(160deg, rgba(15,18,26,0.98), rgba(10,12,18,0.95));
    box-shadow: 0 16px 40px rgba(0,0,0,0.35);
    overflow: hidden;
    transition: border-color .18s ease, box-shadow .18s ease, background .18s ease;
  }

  .task-choice-card:has(.choice-zone.left:hover) {
    border-color: rgba(239,68,68,0.6);
    box-shadow: 0 16px 45px rgba(239,68,68,0.20);
    background: linear-gradient(160deg, rgba(45,10,12,0.98), rgba(12,8,10,0.95));
  }

  .task-choice-card:has(.choice-zone.right:hover) {
    border-color: rgba(16,185,129,0.65);
    box-shadow: 0 16px 45px rgba(16,185,129,0.20);
    background: linear-gradient(160deg, rgba(8,26,20,0.98), rgba(8,12,10,0.95));
  }

  .task-choice-content {
    padding: 16px 16px 18px 16px;
  }

  .task-choice-header {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    align-items: center;
    margin-bottom: 10px;
  }

  .task-choice-body {
    color: rgba(255,255,255,0.92);
    line-height: 1.6;
    font-size: 14.5px;
  }

  .choice-zone {
    position: absolute;
    top: 0;
    bottom: 0;
    width: 50%;
    display: flex;
    align-items: stretch;
  }

  .choice-zone.left { left: 0; }
  .choice-zone.right { right: 0; }

  .choice-zone.left:hover { background: rgba(239,68,68,0.12); }
  .choice-zone.right:hover { background: rgba(16,185,129,0.12); }

  .choice-zone .stButton { width: 100%; height: 100%; }
  .choice-zone .stButton > button {
    width: 100% !important;
    height: 100% !important;
    border: 0 !important;
    border-radius: 0 !important;
    background: transparent !important;
    color: rgba(255,255,255,0.65) !important;
    font-weight: 600 !important;
    letter-spacing: 0.03em !important;
    text-transform: uppercase !important;
  }
  .choice-zone.left .stButton > button { text-align: left !important; padding-left: 14px !important; }
  .choice-zone.right .stButton > button { text-align: right !important; padding-right: 14px !important; }
  .choice-zone .stButton > button:hover { color: rgba(255,255,255,0.92) !important; }

  /* Make code editor (custom component iframe) match style */
  div[data-testid="stCustomComponentV1"] iframe {
    border-radius: 14px;
    border: 1px solid rgba(255,255,255,0.14);
    background: rgba(0,0,0,0.28);
    box-shadow: 0 14px 34px rgba(0,0,0,0.38);
  }

  /* Buttons */
  div.stButton > button {
    border-radius: 12px !important;
    border: 1px solid rgba(255,255,255,0.14) !important;
    background: linear-gradient(180deg, rgba(255,255,255,0.06), rgba(255,255,255,0.02)) !important;
    color: rgba(255,255,255,0.92) !important;
    padding: 0.60rem 0.85rem !important;
    transition: transform .06s ease, background .18s ease, border-color .18s ease;
  }
  div.stButton > button:hover {
    border-color: rgba(255,255,255,0.22) !important;
    background: linear-gradient(180deg, rgba(255,255,255,0.09), rgba(255,255,255,0.03)) !important;
    transform: translateY(-1px);
  }
  div.stButton > button:active { transform: translateY(0px); }

  /* Inputs / selects */
  div[data-baseweb="input"] input,
  div[data-baseweb="textarea"] textarea {
    border-radius: 12px !important;
    border: 1px solid rgba(255,255,255,0.12) !important;
    background: rgba(255,255,255,0.03) !important;
  }

  /* Tabs look */
  button[data-baseweb="tab"] {
    border-radius: 999px !important;
    margin-right: 6px !important;
    padding-top: 6px !important;
    padding-bottom: 6px !important;
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
        # Streamlit >= 1.30
        return (st.query_params.get(name) or '').strip()
    except Exception:
        return (st.experimental_get_query_params().get(name, [''])[0] or '').strip()


def _init_state():
    st.session_state.setdefault('me', None)
    st.session_state.setdefault('task', None)
    st.session_state.setdefault('task_type', 24)
    st.session_state.setdefault('last_task_type', None)
    st.session_state.setdefault('pinned_task_id', None)
    st.session_state.setdefault('candidate_tasks', [])
    st.session_state.setdefault('code', '')
    st.session_state.setdefault('messages', [])
    st.session_state.setdefault('analysis', None)
    st.session_state.setdefault('tests', None)
    # Avoid repeats within a Streamlit session (per task_type)
    st.session_state.setdefault('seen_task_ids', {})  # dict[int, list[int]]
    # Hint ladder progress (per task_id)
    st.session_state.setdefault('hint_level_by_task', {})  # dict[int, int]
    st.session_state.setdefault('history_loaded', False)
    st.session_state.setdefault('history_items', [])
    st.session_state.setdefault('history_selected', None)
    st.session_state.setdefault('layout_mode', 'Фокус')  # Фокус|Разделить


def _render_task_html(task: dict[str, Any]):
    html = (task.get('content_html') or '').strip()
    if not html:
        st.info("У условия нет HTML-контента.")
        return
    # IMPORTANT: avoid inner iframe scrollbars (components.html) — render directly
    # so the page scroll is the only scroll.
    st.markdown(
        f"""
<div class="k-card" style="padding: 16px 16px;">
  <div style="color: rgba(255,255,255,0.92); line-height: 1.65; font-size: 15px;">
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


def _pull_next_candidate(client: PlatformClient, *, task_type: int, pinned_id: int | None = None) -> dict[str, Any] | None:
    seen = st.session_state['seen_task_ids'].get(int(task_type), []) or []
    if pinned_id is not None:
        resp = client.stream_start(task_type=int(task_type), exclude_task_ids=seen, task_id=int(pinned_id))
        st.session_state['pinned_task_id'] = None
    elif not seen:
        resp = client.stream_start(task_type=int(task_type), exclude_task_ids=seen)
    else:
        resp = client.stream_next(task_type=int(task_type), exclude_task_ids=seen)
    t = resp.get('task') if isinstance(resp, dict) else None
    if t and t.get('task_id'):
        _register_seen_task(int(task_type), int(t.get('task_id')))
        st.session_state['hint_level_by_task'][int(t.get('task_id'))] = 0
        return t
    return None


def _ensure_candidate_tasks(client: PlatformClient, *, task_type: int, target: int = 3):
    candidates = st.session_state.get('candidate_tasks') or []
    pinned_id = st.session_state.get('pinned_task_id')
    while len(candidates) < int(target):
        t = _pull_next_candidate(client, task_type=int(task_type), pinned_id=pinned_id)
        pinned_id = None
        if not t:
            break
        candidates.append(t)
    st.session_state['candidate_tasks'] = candidates


def _check_answer_match(expected_raw: str, given_raw: str) -> tuple[bool, list[str]]:
    expected_raw = (expected_raw or '').strip()
    if not expected_raw:
        return False, []
    variants = [v.strip() for v in re.split(r'[|;\n]+', expected_raw) if v.strip()]
    normalized_expected = [normalize_answer_value(v) for v in variants] if variants else [normalize_answer_value(expected_raw)]
    normalized_expected = [v for v in normalized_expected if v != '']
    normalized_given = normalize_answer_value(given_raw)
    return normalized_given in normalized_expected and normalized_given != '', normalized_expected


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
    role = user.get('role') or ''

    if qp_task_type:
        try:
            st.session_state['task_type'] = int(qp_task_type)
        except Exception:
            pass

    # Load stats so user sees which task numbers exist in DB
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

    if counts and int(st.session_state.get('task_type') or 0) not in counts:
        st.session_state['task_type'] = int(sorted(counts.keys())[0])

    # LLM info for status (best-effort)
    llm_info = None
    try:
        resp = client.llm_info()
        llm_info = (resp.get('llm') or {}) if isinstance(resp, dict) else None
    except Exception:
        llm_info = get_llm_info()

    pinned_id: int | None = None
    if qp_task_id:
        try:
            pinned_id = int(qp_task_id)
        except Exception:
            pinned_id = None

    if pinned_id and st.session_state.get('pinned_task_id') is None:
        st.session_state['pinned_task_id'] = int(pinned_id)

    # ===== Top bar =====
    left, mid, right = st.columns([1.35, 1.6, 1.05], gap="large")
    with left:
        st.markdown("## Тренажёр")
        st.markdown(
            "<div class='k-card'>"
            f"<div class='k-title'>Привет, {username}</div>"
            "<div class='k-muted' style='margin-top:4px'>Решай спокойно: код → запуск → проверка → подсказки.</div>"
            "</div>",
            unsafe_allow_html=True,
        )

    with mid:
        st.markdown("### Панель выбора задания")
        st.markdown("<div class='k-panel'>", unsafe_allow_html=True)
        options = list(range(1, 28))

        def _fmt(n: int) -> str:
            c = counts.get(int(n), 0)
            return f"№{n} · в базе: {c}"

        task_type = st.selectbox(
            "Номер задания",
            options=options,
            index=max(0, min(len(options) - 1, int(st.session_state.get('task_type') or 24) - 1)),
            format_func=_fmt,
            key="task_type_picker",
        )
        st.session_state['task_type'] = int(task_type)
        st.session_state['seen_task_ids'].setdefault(int(task_type), [])
        if counts and counts.get(int(task_type), 0) <= 0:
            st.warning("Для этого номера заданий пока нет задач в базе. Выбери другой номер или наполни `Tasks`.")
        st.markdown("</div>", unsafe_allow_html=True)

        st.markdown("")
        st.radio(
            "Режим",
            options=["Фокус", "Разделить"],
            horizontal=True,
            key="layout_mode",
            help="Фокус: рабочая зона на всю ширину, условие сворачивается.\nРазделить: условие слева, код/запуск справа.",
        )

    with right:
        badges = []
        badges.append(_badge(f"раннер: {'ON' if is_runner_enabled() else 'OFF'}", "ok" if is_runner_enabled() else "warn"))
        if isinstance(llm_info, dict) and llm_info.get('configured') and (llm_info.get('picked') or {}).get('provider'):
            picked = llm_info.get('picked') or {}
            badges.append(_badge(f"LLM: {picked.get('provider')}", "ok"))
        else:
            badges.append(_badge("LLM: OFF", "warn"))
        st.markdown("<div class='k-card'>" + "".join(badges) + "</div>", unsafe_allow_html=True)

        with st.expander("Диагностика", expanded=False):
            env_flag = (os.environ.get('TRAINER_ENABLE_RUNNER') or '').strip()
            st.caption(f"role: `{role}`")
            st.caption(f"TRAINER_ENABLE_RUNNER: `{env_flag!r}`")
            if st.button("Проверить LLM", use_container_width=True):
                try:
                    pr = client.llm_ping()
                    ans = (pr.get('answer') or '') if isinstance(pr, dict) else ''
                    st.success(f"Ответ: {str(ans).strip()[:80]}")
                except Exception:
                    llm = get_llm_client()
                    if not llm:
                        st.error("LLM клиент не создан (проверь env).")
                    else:
                        try:
                            ans = llm.chat(
                                messages=[{'role': 'system', 'content': 'Answer with a single word OK.'}, {'role': 'user', 'content': 'ping'}],
                                temperature=0.0,
                                max_tokens=5,
                            )
                            st.success(f"Ответ: {str(ans).strip()[:80]}")
                        except Exception as e:
                            st.error(f"Ошибка LLM: {e}")

    st.markdown("")

    # Track task_type changes
    prev_task_type = st.session_state.get('last_task_type')
    if prev_task_type is None:
        st.session_state['last_task_type'] = int(task_type)
    elif int(prev_task_type) != int(task_type):
        st.session_state['last_task_type'] = int(task_type)
        st.session_state['task'] = None
        st.session_state['candidate_tasks'] = []
        st.session_state['pinned_task_id'] = None
        _reset_workbench_state()

    st.markdown("")

    task = st.session_state.get('task')
    if not task:
        st.markdown("### Карточки выбора")
        if counts and counts.get(int(task_type), 0) <= 0:
            st.info("Выбери номер, где есть задания — карточки появятся автоматически.")
            return

        _ensure_candidate_tasks(client, task_type=int(task_type), target=3)
        candidates = st.session_state.get('candidate_tasks') or []

        if not candidates:
            st.info("Задач не найдено. Попробуй другой номер.")
            return

        st.markdown("<div class='task-choice-stack'>", unsafe_allow_html=True)
        for idx, cand in enumerate(candidates):
            c_tid = int(cand.get('task_id') or 0)
            src_bits = []
            if cand.get("source_url"):
                src_bits.append(f"<a href='{cand.get('source_url')}' target='_blank'>Источник</a>")
            if cand.get("site_task_id"):
                src_bits.append(f"site_id: {cand.get('site_task_id')}")
            body_preview = (cand.get('content_html') or '').strip()
            if len(body_preview) > 550:
                body_preview = body_preview[:550] + "…"

            st.markdown(
                "<div class='task-choice-card'>"
                "<div class='task-choice-content'>"
                "<div class='task-choice-header'>"
                + _badge(f"№{cand.get('task_number')}", "ok")
                + _badge(f"ID {cand.get('task_id')}", "ok")
                + (f"<span class='k-muted'>{' · '.join(src_bits)}</span>" if src_bits else "<span class='k-muted'>Источник не указан</span>")
                + "</div>"
                + f"<div class='task-choice-body'>{body_preview}</div>"
                + "</div>",
                unsafe_allow_html=True,
            )

            left_col, right_col = st.columns([1, 1], gap="small")
            with left_col:
                st.markdown("<div class='choice-zone left'>", unsafe_allow_html=True)
                if st.button("Пропустить", use_container_width=True, key=f"skip_{c_tid}_{idx}"):
                    st.session_state['candidate_tasks'] = [c for c in candidates if int(c.get('task_id') or 0) != c_tid]
                    _ensure_candidate_tasks(client, task_type=int(task_type), target=3)
                    st.rerun()
                st.markdown("</div>", unsafe_allow_html=True)
            with right_col:
                st.markdown("<div class='choice-zone right'>", unsafe_allow_html=True)
                if st.button("Выполнять", use_container_width=True, key=f"accept_{c_tid}_{idx}"):
                    st.session_state['task'] = cand
                    st.session_state['candidate_tasks'] = []
                    _reset_workbench_state()
                    if cand.get('task_id'):
                        st.session_state['hint_level_by_task'][int(cand.get('task_id'))] = 0
                    st.rerun()
                st.markdown("</div>", unsafe_allow_html=True)

            st.markdown("</div>", unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)
        return

    # ===== Task actions (active task) =====
    a1, a2, a3, a4 = st.columns([1, 1, 1, 2], gap="small")
    if a1.button("↩ Вернуться к выбору", use_container_width=True):
        st.session_state['task'] = None
        st.session_state['candidate_tasks'] = []
        _reset_workbench_state()
        st.rerun()

    if a2.button("→ Следующее (через карточки)", use_container_width=True):
        st.session_state['task'] = None
        st.session_state['candidate_tasks'] = []
        _reset_workbench_state()
        _ensure_candidate_tasks(client, task_type=int(task_type), target=3)
        st.rerun()

    if a3.button("💾 Сохранить", use_container_width=True):
        task = st.session_state.get('task') or {}
        if not task:
            st.warning("Сначала выбери задание.")
        else:
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
    a4.markdown("<div class='k-muted' style='padding-top:10px'>Помощник и история — справа. Код и запуск — в «Решение».</div>", unsafe_allow_html=True)

    tid = int(task.get('task_id') or 0)
    knowledge = load_task_knowledge(tid) if tid else None
    tests = (knowledge or {}).get('tests') if isinstance(knowledge, dict) else None

    layout_mode = (st.session_state.get("layout_mode") or "Фокус").strip()

    # Layout:
    # - Focus: no empty space; statement collapses into expander above the workbench.
    # - Split: statement on the left, workbench on the right.
    if layout_mode == "Разделить":
        left_pane, right_pane = st.columns([1.05, 1.25], gap="large")
        with left_pane:
            st.markdown("### Условие")
            src_bits = []
            if task.get("source_url"):
                src_bits.append(f"[Источник]({task.get('source_url')})")
            if task.get("site_task_id"):
                src_bits.append(f"site_id: `{task.get('site_task_id')}`")
            st.markdown(
                "<div class='k-card'>"
                + _badge(f"№{task.get('task_number')}", "ok")
                + _badge(f"ID {task.get('task_id')}", "ok")
                + (" ".join(src_bits) if src_bits else "<span class='k-muted'>Источник не указан.</span>")
                + "</div>",
                unsafe_allow_html=True,
            )
            _render_task_html(task)
        workbench_container = right_pane
    else:
        # Focus mode
        st.markdown("### Рабочая зона")
        with st.expander("Условие (свернуть/развернуть)", expanded=False):
            _render_task_html(task)
        workbench_container = st.container()

    with workbench_container:
        tab_solve, tab_help, tab_hist = st.tabs(["Решение", "Помощник", "История"])

        with tab_solve:
            st.markdown("### Код")
            st.caption("Пишешь код здесь и запускаешь ниже — без переключения вкладок.")

            code_val = ""
            try:
                from streamlit_ace import st_ace  # type: ignore
                code_val = st_ace(
                    key="code_editor",
                    value=st.session_state.get("code") or "",
                    language="python",
                    theme="dracula",
                    keybinding="vscode",
                    height=420,
                    min_lines=20,
                    font_size=14,
                    tab_size=4,
                    show_gutter=True,
                    wrap=True,
                    auto_update=False,  # no rerun while typing
                ) or ""
            except Exception:
                code_val = st.text_area(
                    "Код",
                    value=st.session_state.get('code') or "",
                    height=420,
                    placeholder="print('hello')",
                ) or ""

            if len(code_val) > 20000:
                st.warning("Код слишком большой, обрезаю до 20 000 символов.")
                code_val = code_val[:20000]
            st.session_state["code"] = code_val

            c1, c2, c3 = st.columns([1, 1, 1], gap="small")
            if c1.button("Проанализировать", use_container_width=True, key="btn_analyze"):
                st.session_state['analysis'] = analyze_python_code(st.session_state.get('code') or '')
                hints = (st.session_state['analysis'] or {}).get('hints') or []
                if hints:
                    st.session_state['messages'].append({'role': 'assistant', 'content': 'Что я заметил в коде:\n\n- ' + '\n- '.join(hints[:4])})
            if c2.button("Очистить код", use_container_width=True, key="btn_clear_code"):
                st.session_state['code'] = ''
                st.session_state['analysis'] = None
                st.session_state['tests'] = None
            if c3.button("Сбросить чат/подсказки", use_container_width=True, key="btn_reset_help"):
                st.session_state['messages'] = []
                if tid:
                    st.session_state['hint_level_by_task'][tid] = 0

            if st.session_state.get('analysis') is not None:
                with st.expander("Анализ (MVP)", expanded=False):
                    st.code(json.dumps(st.session_state['analysis'], ensure_ascii=False, indent=2), language="json")

            st.markdown("### Запуск и проверка")
            if not is_runner_enabled():
                st.warning("Запуск кода выключен на сервере. Включи `TRAINER_ENABLE_RUNNER=1` в сервисе тренажёра.")
            else:
                rt0, rt1, rt2 = st.tabs(["Проверить ответ", "Запустить (stdin → stdout)", "Проверить тестами"])
                with rt0:
                    expected_answer = (task.get('answer') or '')
                    st.caption("Сравнение идёт по нормализованным значениям (пробелы/регистр/форматы чисел).")
                    user_answer = st.text_input("Ответ", value=st.session_state.get('answer_input') or "", key="answer_input")
                    if st.button("✅ Проверить ответ", use_container_width=True, key="btn_check_answer"):
                        if not expected_answer:
                            st.warning("В базе нет правильного ответа для этой задачи.")
                        elif not (user_answer or "").strip():
                            st.warning("Введите ответ для проверки.")
                        else:
                            ok, variants = _check_answer_match(expected_answer, user_answer)
                            if ok:
                                st.success("Ответ верный.")
                            else:
                                st.error("Ответ неверный.")
                                if variants:
                                    st.caption("Подсказка: проверь формат ответа (число/строка, без лишних пробелов).")
                with rt1:
                    stdin_val = st.text_area(
                        "Ввод (stdin)",
                        value=st.session_state.get('run_stdin') or "",
                        height=130,
                        placeholder="Например:\n5\n1 2 3 4 5\n",
                        key="run_stdin",
                    )
                    expect = st.text_area(
                        "Ожидаемый вывод (необязательно)",
                        value=st.session_state.get('run_expected') or "",
                        height=90,
                        placeholder="Если заполнишь — я сравню stdout (по .strip()).",
                        key="run_expected",
                    )
                    # When widgets have keys, Streamlit manages st.session_state for them automatically.

                    if st.button("▶ Запустить", use_container_width=True, key="btn_run_program"):
                        res = run_python_program(code=st.session_state.get('code') or '', stdin=stdin_val, timeout_seconds=2.0)
                        st.session_state['run_result'] = res

                    res = st.session_state.get('run_result')
                    if isinstance(res, dict):
                        if res.get('ok'):
                            st.success("Код выполнился.")
                        else:
                            st.error(f"Ошибка запуска: {res.get('error')}")
                            if res.get('details'):
                                st.code(str(res.get('details'))[:4000])

                        out_col, err_col = st.columns(2, gap="small")
                        out_col.markdown("**stdout**")
                        out_col.code((res.get('stdout') or '')[:12000])
                        err_txt = (res.get('stderr') or '')
                        if err_txt:
                            err_col.markdown("**stderr**")
                            err_col.code(err_txt[:6000])

                        if (expect or '').strip():
                            got = (res.get('stdout') or '').strip()
                            exp = (expect or '').strip()
                            if got == exp:
                                st.success("stdout совпал с ожидаемым.")
                            else:
                                st.warning("stdout НЕ совпал с ожидаемым.")

                with rt2:
                    if not tests:
                        st.info("Для этой задачи пока нет тестов в knowledge. Добавим позже при наполнении данных.")
                    else:
                        st.caption("Для тестов добавь функцию `solve(s)`; раннер вызовет её на тестовых input и сравнит expected.")
                        if st.button("🧪 Запустить тесты", use_container_width=True, key="btn_run_tests"):
                            st.session_state['tests'] = run_python_solve_tests(code=st.session_state.get('code') or '', tests=tests)
                        if st.session_state.get('tests') is not None:
                            _render_tests_block(st.session_state.get('tests'))

        with tab_help:
            # Hint progress
            ladder = (knowledge or {}).get('hint_ladder') if isinstance(knowledge, dict) else None
            max_lvl = 0
            if isinstance(ladder, list):
                for it in ladder:
                    if isinstance(it, dict) and it.get('level') is not None:
                        try:
                            max_lvl = max(max_lvl, int(it.get('level') or 0))
                        except Exception:
                            continue
                if max_lvl <= 0:
                    max_lvl = len([it for it in ladder if isinstance(it, dict) and it.get('hint')])
            cur_lvl = int((st.session_state.get('hint_level_by_task') or {}).get(tid, 0) or 0)
            if max_lvl > 0:
                st.progress(min(1.0, float(cur_lvl) / float(max_lvl)))
                st.caption(f"Подсказки: уровень {cur_lvl}/{max_lvl}")

            h1, h2 = st.columns([1.0, 1.0], gap="large")
            with h1:
                st.markdown("### Подсказки")
                if st.button("Получить следующую подсказку", use_container_width=True, key="btn_next_hint"):
                    t = st.session_state.get('task') or {}
                    current_level = int((st.session_state.get('hint_level_by_task') or {}).get(tid, 0) or 0)
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
                        st.session_state['messages'].append({'role': 'assistant', 'content': f"Подсказка (уровень {next_level}): {next_hint}"})
                    else:
                        # fallback: ask LLM for a guided question (without giving full solution)
                        try:
                            msgs = build_messages_for_help(
                                task=t,
                                code=st.session_state.get('code') or '',
                                analysis=st.session_state.get('analysis'),
                                history=(st.session_state.get('messages') or []) + [{'role': 'user', 'content': 'Дай следующую подсказку по шагам (не решение), задай наводящий вопрос.'}],
                                knowledge=knowledge,
                            )
                            answer = None
                            try:
                                pr = client.llm_chat(
                                    messages=msgs,
                                    temperature=0.2,
                                    max_tokens=500,
                                    task_id=int(t.get('task_id') or 0) if t.get('task_id') else None,
                                    task_type=int(t.get('task_number') or 0) if t.get('task_number') else None,
                                )
                                answer = (pr.get('answer') or '') if isinstance(pr, dict) else None
                            except Exception:
                                llm = get_llm_client()
                                if llm:
                                    answer = llm.chat(messages=msgs, temperature=0.2, max_tokens=500)
                            answer = (answer or '').strip() or 'Сформулируй, что именно ты считаешь ответом (строка/число) и какие входные данные.'
                            st.session_state['messages'].append({'role': 'assistant', 'content': answer})
                        except Exception as e:
                            st.session_state['messages'].append({'role': 'assistant', 'content': f'Ошибка обращения к LLM: {e}'})

                with st.expander("Текущий код (preview)", expanded=False):
                    st.code((st.session_state.get('code') or '')[:12000], language="python")

            with h2:
                st.markdown("### Чат помощника")
                for m in st.session_state.get('messages') or []:
                    with st.chat_message(m.get('role') or 'assistant'):
                        st.markdown(m.get('content') or '')

                prompt = st.chat_input("Напиши вопрос помощнику…")
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
                            pr = client.llm_chat(
                                messages=msgs,
                                temperature=0.2,
                                max_tokens=700,
                                task_id=int(task.get('task_id') or 0) if task.get('task_id') else None,
                                task_type=int(task.get('task_number') or 0) if task.get('task_number') else None,
                            )
                            answer = (pr.get('answer') or '') if isinstance(pr, dict) else None
                        except Exception:
                            llm = get_llm_client()
                            if llm:
                                answer = llm.chat(messages=msgs, temperature=0.2, max_tokens=700)
                        if not answer:
                            st.session_state['messages'].append({'role': 'assistant', 'content': 'LLM пока не настроен. Скажи, что ты уже сделал и где застрял.'})
                        else:
                            answer = (answer or '').strip() or 'Не смог сформировать ответ. Попробуй переформулировать вопрос.'
                            st.session_state['messages'].append({'role': 'assistant', 'content': answer})
                    except Exception as e:
                        st.session_state['messages'].append({'role': 'assistant', 'content': f'Ошибка обращения к LLM: {e}'})
                    st.rerun()

        with tab_hist:
            st.markdown("### История попыток")
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
                st.info("Пока нет сохранённых попыток.")
            else:
                options = []
                for it in items:
                    label = f"#{it.get('session_id')} · №{it.get('task_type')} · {it.get('created_at')}"
                    options.append((label, it))
                labels = [o[0] for o in options]
                sel = st.selectbox("Открыть попытку", options=list(range(len(labels))), format_func=lambda i: labels[i], key="hist_sel")
                sel_item = options[int(sel)][1]
                if st.button("Загрузить выбранную", use_container_width=True, key="btn_hist_load"):
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

