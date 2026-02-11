from __future__ import annotations

import json
import os
import re
import sys
from typing import Any

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import streamlit as st

from trainer_app.platform_client import PlatformClient, get_platform_base_url
from trainer_app.analyzers.python_static import analyze_python_code
from trainer_app.knowledge import load_task_knowledge
from trainer_app.llm.providers import get_llm_client, get_llm_info, build_messages_for_help
from trainer_app.runner.sandbox import is_runner_enabled, run_python_solve_tests, run_python_program
from app.lessons.utils import normalize_answer_value


st.set_page_config(page_title="Тренажёр КЕГЭ", layout="wide")

try:
    from dotenv import load_dotenv
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    load_dotenv(os.path.join(repo_root, '.env'), override=False)
    load_dotenv(os.path.join(os.path.dirname(__file__), '.env'), override=False)
except Exception:
    pass


def _inject_css():
    st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap');

html, body, [class*="css"] { font-family: 'Inter', system-ui, sans-serif; }

.stApp {
  background: linear-gradient(135deg, #0a0c12 0%, #0d1117 50%, #070910 100%);
}

.block-container { padding-top: 1rem; padding-bottom: 1rem; max-width: 1200px; }

/* Hero */
.hero-box {
  text-align: center;
  padding: 40px 20px 30px;
}
.hero-title {
  font-size: 2.8rem;
  font-weight: 900;
  letter-spacing: -0.03em;
  background: linear-gradient(135deg, #fff 0%, rgba(255,255,255,0.7) 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  margin-bottom: 8px;
}
.hero-sub {
  font-size: 1.1rem;
  color: rgba(255,255,255,0.5);
}

/* Number Grid */
.num-grid {
  display: grid;
  grid-template-columns: repeat(9, 1fr);
  gap: 10px;
  max-width: 600px;
  margin: 30px auto;
}
.num-cell {
  aspect-ratio: 1;
  border-radius: 14px;
  border: 2px solid rgba(255,255,255,0.1);
  background: rgba(255,255,255,0.04);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: all 0.2s ease;
  color: #fff;
  font-weight: 700;
  font-size: 1.1rem;
}
.num-cell:hover {
  border-color: #00ffd5;
  background: rgba(0,255,213,0.1);
  transform: translateY(-3px);
  box-shadow: 0 10px 30px rgba(0,255,213,0.2);
}
.num-cell .count {
  font-size: 0.65rem;
  color: rgba(255,255,255,0.4);
  margin-top: 2px;
}
.num-cell.empty {
  opacity: 0.25;
  cursor: not-allowed;
}

/* Task Card */
.task-card {
  background: linear-gradient(160deg, rgba(20,22,32,0.98), rgba(14,16,24,0.96));
  border: 2px solid rgba(255,255,255,0.1);
  border-radius: 20px;
  padding: 28px;
  margin: 20px 0;
  box-shadow: 0 20px 60px rgba(0,0,0,0.4);
}
.task-card-header {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 20px;
  padding-bottom: 16px;
  border-bottom: 1px solid rgba(255,255,255,0.1);
}
.task-badge {
  padding: 6px 14px;
  border-radius: 999px;
  font-size: 13px;
  font-weight: 600;
  border: 1px solid rgba(255,255,255,0.15);
  background: rgba(255,255,255,0.05);
  color: rgba(255,255,255,0.85);
}
.task-badge.primary {
  border-color: rgba(0,255,213,0.5);
  background: rgba(0,255,213,0.12);
  color: #00ffd5;
}
.task-body {
  color: rgba(255,255,255,0.92);
  font-size: 15px;
  line-height: 1.75;
}
.task-body p { margin-bottom: 12px; }
.task-body img { max-width: 100%; border-radius: 8px; }

/* Action Buttons */
.action-row {
  display: flex;
  gap: 16px;
  margin-top: 24px;
}

/* Style Streamlit buttons */
div.stButton > button {
  border-radius: 14px !important;
  font-weight: 600 !important;
  padding: 14px 28px !important;
  font-size: 15px !important;
  transition: all 0.2s ease !important;
  width: 100%;
}

/* Skip button - red */
div[data-testid="column"]:first-child div.stButton > button {
  border: 2px solid rgba(239,68,68,0.5) !important;
  background: rgba(239,68,68,0.1) !important;
  color: #ef4444 !important;
}
div[data-testid="column"]:first-child div.stButton > button:hover {
  background: rgba(239,68,68,0.25) !important;
  border-color: #ef4444 !important;
  transform: translateY(-2px);
  box-shadow: 0 8px 25px rgba(239,68,68,0.3);
}

/* Accept button - green */
div[data-testid="column"]:last-child div.stButton > button {
  border: 2px solid rgba(16,185,129,0.5) !important;
  background: rgba(16,185,129,0.1) !important;
  color: #10b981 !important;
}
div[data-testid="column"]:last-child div.stButton > button:hover {
  background: rgba(16,185,129,0.25) !important;
  border-color: #10b981 !important;
  transform: translateY(-2px);
  box-shadow: 0 8px 25px rgba(16,185,129,0.3);
}

/* Back button */
.back-btn button {
  border: 1px solid rgba(255,255,255,0.15) !important;
  background: rgba(255,255,255,0.05) !important;
  color: rgba(255,255,255,0.7) !important;
}
.back-btn button:hover {
  background: rgba(255,255,255,0.1) !important;
}

/* Workbench tabs */
button[data-baseweb="tab"] {
  border-radius: 12px !important;
  font-weight: 600 !important;
  padding: 10px 20px !important;
}

/* Code area */
div[data-baseweb="textarea"] textarea {
  border-radius: 12px !important;
  border: 1px solid rgba(255,255,255,0.1) !important;
  background: rgba(0,0,0,0.3) !important;
  color: #fff !important;
  font-family: 'Fira Code', monospace !important;
}

/* Input */
div[data-baseweb="input"] input {
  border-radius: 12px !important;
  border: 1px solid rgba(255,255,255,0.1) !important;
  background: rgba(255,255,255,0.04) !important;
  color: #fff !important;
}
</style>
    """, unsafe_allow_html=True)


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


def _reset_workbench():
    st.session_state['analysis'] = None
    st.session_state['tests'] = None
    st.session_state['messages'] = []
    st.session_state['code'] = ''


def _register_seen(task_type: int, task_id: int):
    seen = st.session_state['seen_task_ids'].setdefault(int(task_type), [])
    if int(task_id) not in seen:
        seen.append(int(task_id))


def _pull_task(client: PlatformClient, task_type: int) -> dict | None:
    seen = st.session_state['seen_task_ids'].get(int(task_type), []) or []
    if not seen:
        resp = client.stream_start(task_type=int(task_type), exclude_task_ids=seen)
    else:
        resp = client.stream_next(task_type=int(task_type), exclude_task_ids=seen)
    t = resp.get('task') if isinstance(resp, dict) else None
    if t and t.get('task_id'):
        _register_seen(int(task_type), int(t.get('task_id')))
        st.session_state['hint_level_by_task'][int(t.get('task_id'))] = 0
        return t
    return None


def _check_answer(expected: str, given: str) -> bool:
    if not expected.strip():
        return False
    variants = [v.strip() for v in re.split(r'[|;\n]+', expected) if v.strip()]
    norm_exp = [normalize_answer_value(v) for v in variants]
    norm_exp = [v for v in norm_exp if v]
    norm_given = normalize_answer_value(given)
    return norm_given in norm_exp and norm_given != ''


def _render_tests(payload: Any):
    if not isinstance(payload, dict) or not payload.get("ok"):
        st.error(f"Ошибка: {payload.get('error', 'неизвестно') if isinstance(payload, dict) else 'нет данных'}")
        return
    results = payload.get("results", [])
    ok = sum(1 for r in results if isinstance(r, dict) and r.get("ok"))
    total = len(results)
    if ok == total:
        st.success(f"✅ Все тесты пройдены: {ok}/{total}")
    else:
        st.warning(f"⚠️ Пройдено: {ok}/{total}")
    for r in results:
        if isinstance(r, dict):
            icon = "✅" if r.get("ok") else "❌"
            st.write(f"{icon} **{r.get('name', 'тест')}**: ожидалось `{r.get('expected')}`, получено `{r.get('got')}`")


def main():
    _inject_css()
    _init_state()

    token = _get_query_param('token')
    qp_task_type = _get_query_param('task_type')
    base_url = get_platform_base_url()

    if not base_url:
        st.error("Не задан PLATFORM_BASE_URL")
        st.stop()
    if not token:
        st.error("Нет token. Открой через платформу (/trainer).")
        st.stop()

    client = PlatformClient(base_url=base_url, token=token)

    if st.session_state['me'] is None:
        try:
            me = client.get_me()
            if not me.get('success'):
                raise RuntimeError(me.get('error', 'unauthorized'))
            st.session_state['me'] = me
        except Exception as e:
            st.error(f"Авторизация: {e}")
            st.stop()

    user = (st.session_state['me'] or {}).get('user', {})
    username = user.get('username', 'пользователь')

    with st.sidebar:
        with st.expander("🔧 Диагностика LLM (403)"):
            if st.button("Проверить ключи и тест Groq", key="diag_btn"):
                try:
                    dr = client.llm_diagnose(test=True)
                    d = (dr.get('diagnose') or {}) if isinstance(dr, dict) else {}
                    st.json(d)
                    if d.get('groq_key_set') and d.get('test_status') == 403:
                        st.warning("403 от Groq. Смотри test_body выше — там причина. Ключ задан на платформе?")
                except Exception as ex:
                    st.error(str(ex))

    counts = {}
    try:
        stats = client.get_task_stats()
        raw = stats.get('counts_by_task_number', {}) if isinstance(stats, dict) else {}
        counts = {int(k): int(v) for k, v in raw.items() if v}
    except Exception:
        pass

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

    if task_type is None and task is None:
        st.markdown(f"""
        <div class="hero-box">
            <div class="hero-title">Тренажёр КЕГЭ</div>
            <div class="hero-sub">Привет, {username}! Выбери номер задания</div>
        </div>
        """, unsafe_allow_html=True)

        st.markdown("### Выбери номер задания")
        
        for row_start in [1, 10, 19]:
            cols = st.columns(9)
            for i, n in enumerate(range(row_start, min(row_start + 9, 28))):
                count = counts.get(n, 0)
                with cols[i]:
                    disabled = count == 0
                    label = f"{n}\n({count})" if count > 0 else f"{n}\n—"
                    if st.button(label, key=f"num_{n}", disabled=disabled, use_container_width=True):
                        st.session_state['task_type'] = n
                        st.session_state['current_card'] = None
                        st.rerun()
        return

    if task is None:
        if current_card is None:
            card = _pull_task(client, int(task_type))
            if card:
                st.session_state['current_card'] = card
                st.rerun()
            else:
                st.warning("Задания закончились!")
                if st.button("← Выбрать другой номер"):
                    st.session_state['task_type'] = None
                    st.rerun()
                return
        
        card = st.session_state['current_card']
        
        if st.button("← Сменить номер", key="back_btn"):
            st.session_state['task_type'] = None
            st.session_state['current_card'] = None
            st.rerun()
        
        st.markdown(f"""
        <div style="text-align:center; margin: 20px 0;">
            <div style="font-size: 1.8rem; font-weight: 800; color: #fff;">Задание №{task_type}</div>
            <div style="color: rgba(255,255,255,0.5); margin-top: 8px;">Пропусти или начни решать</div>
        </div>
        """, unsafe_allow_html=True)
        
        content = (card.get('content_html') or '').strip()
        source_url = card.get('source_url', '')
        source_link = f'<a href="{source_url}" target="_blank" class="task-badge" style="text-decoration:none;">Источник ↗</a>' if source_url else ''
        
        st.markdown(f"""
        <div class="task-card">
            <div class="task-card-header">
                <span class="task-badge primary">№{card.get('task_number')}</span>
                <span class="task-badge">ID {card.get('task_id')}</span>
                {source_link}
            </div>
            <div class="task-body">
                {content}
            </div>
        </div>
        """, unsafe_allow_html=True)
        
        col1, col2 = st.columns(2, gap="large")
        
        with col1:
            if st.button("⬅ ПРОПУСТИТЬ", key="skip_btn", use_container_width=True):
                st.session_state['current_card'] = None
                st.rerun()
        
        with col2:
            if st.button("РЕШАТЬ ➡", key="accept_btn", use_container_width=True):
                st.session_state['task'] = card
                st.session_state['current_card'] = None
                _reset_workbench()
                st.rerun()
        
        return

    tid = int(task.get('task_id', 0))
    knowledge = load_task_knowledge(tid) if tid else None
    tests = (knowledge or {}).get('tests') if isinstance(knowledge, dict) else None

    col1, col2, col3 = st.columns([1, 2, 1])
    with col1:
        if st.button("← Назад", use_container_width=True):
            st.session_state['task'] = None
            st.session_state['current_card'] = None
            _reset_workbench()
            st.rerun()
    with col2:
        st.markdown(f"<div style='text-align:center; font-size:1.3rem; font-weight:700; color:#fff;'>Задание №{task.get('task_number')} · ID {tid}</div>", unsafe_allow_html=True)
    with col3:
        if st.button("→ Следующее", use_container_width=True):
            st.session_state['task'] = None
            st.session_state['current_card'] = None
            _reset_workbench()
            st.rerun()

    tab1, tab2, tab3, tab4 = st.tabs(["📄 Условие", "💻 Решение", "💡 Помощник", "📚 История"])

    with tab1:
        content = (task.get('content_html') or '').strip()
        st.markdown(f"""
        <div class="task-card">
            <div class="task-body">{content}</div>
        </div>
        """, unsafe_allow_html=True)
        if task.get('source_url'):
            st.markdown(f"[Открыть источник ↗]({task.get('source_url')})")

    with tab2:
        _code_val = st.session_state.get('code', '')
        try:
            from streamlit_ace import st_ace
            code = st_ace(value=_code_val, language="python", theme="monokai", key="code_ace")
        except Exception:
            code = st.text_area("Код:", value=_code_val, height=300, key="code_area")
        if code is not None:
            st.session_state['code'] = code
        else:
            code = _code_val

        c1, c2 = st.columns(2)
        with c1:
            if st.button("🔍 Анализ", use_container_width=True):
                st.session_state['analysis'] = analyze_python_code(code)
        with c2:
            if st.button("🗑 Очистить", use_container_width=True):
                st.session_state['code'] = ''
                st.rerun()

        if st.session_state.get('analysis'):
            with st.expander("Результат анализа"):
                st.json(st.session_state['analysis'])

        st.markdown("---")
        st.markdown("### Проверка")

        if not is_runner_enabled():
            st.warning("Запуск выключен (TRAINER_ENABLE_RUNNER=1)")
        else:
            check_tab, run_tab, test_tab = st.tabs(["✅ Ответ", "▶ Запуск", "🧪 Тесты"])

            with check_tab:
                expected = task.get('answer', '')
                ans = st.text_input("Твой ответ:", key="user_answer")
                if st.button("Проверить", key="check_btn"):
                    if not expected:
                        st.warning("Нет ответа в базе")
                    elif not ans.strip():
                        st.warning("Введи ответ")
                    elif _check_answer(expected, ans):
                        st.success("✅ Верно!")
                    else:
                        st.error("❌ Неверно")

            with run_tab:
                stdin = st.text_area("Ввод:", height=100, key="stdin")
                if st.button("▶ Запустить", key="run_btn"):
                    res = run_python_program(code=code, stdin=stdin, timeout_seconds=2.0)
                    st.session_state['run_result'] = res
                res = st.session_state.get('run_result')
                if res:
                    if res.get('ok'):
                        st.success("Выполнено")
                    else:
                        st.error(f"Ошибка: {res.get('error')}")
                        details = res.get('details') or ''
                        if details:
                            with st.expander("Подробности (traceback)"):
                                st.code(details[:8000], language=None)
                    stdout = (res.get('stdout') or '').strip()
                    if stdout:
                        st.code(stdout[:5000])

            with test_tab:
                if not tests:
                    st.info("Нет тестов")
                else:
                    if st.button("🧪 Запустить", key="test_btn"):
                        st.session_state['tests'] = run_python_solve_tests(code=code, tests=tests)
                    if st.session_state.get('tests'):
                        _render_tests(st.session_state['tests'])

        st.markdown("---")
        if st.button("💾 Сохранить прогресс", use_container_width=True):
            try:
                client.save_session(
                    task_id=tid,
                    task_type=task.get('task_number'),
                    language='python',
                    code=code,
                    analysis=st.session_state.get('analysis'),
                    tests=st.session_state.get('tests'),
                    messages=st.session_state.get('messages'),
                )
                st.success("Сохранено!")
            except Exception as e:
                st.error(f"Ошибка: {e}")

    with tab3:
        ladder = (knowledge or {}).get('hint_ladder') if isinstance(knowledge, dict) else None

        if st.button("💡 Получить подсказку", use_container_width=True):
            cur = st.session_state.get('hint_level_by_task', {}).get(tid, 0) or 0
            next_level = min(3, cur + 1)
            hint = None
            lvl = next_level

            # 1) Сначала подсказка с платформы (эталоны из БД)
            try:
                hr = client.get_hint(tid, level=next_level)
                if isinstance(hr, dict) and hr.get('success') and hr.get('hint'):
                    hint = (hr.get('hint') or '').strip()
                    lvl = int(hr.get('level', next_level))
            except Exception:
                pass

            # 2) Фоллбэк: локальная база знаний (hint_ladder с ключом hint)
            if not hint and isinstance(ladder, list):
                sorted_l = sorted([(int(x.get('level', 0)), x.get('hint')) for x in ladder if isinstance(x, dict) and x.get('hint')], key=lambda x: x[0] or 999)
                for l, h in sorted_l:
                    if l > cur:
                        lvl, hint = l, h
                        break

            if hint:
                st.session_state['hint_level_by_task'][tid] = lvl
                st.session_state['messages'].append({'role': 'assistant', 'content': f"Подсказка ({lvl}): {hint}"})
            else:
                try:
                    msgs = build_messages_for_help(task=task, code=code, analysis=st.session_state.get('analysis'), history=st.session_state.get('messages', []) + [{'role': 'user', 'content': 'Дай подсказку.'}], knowledge=knowledge)
                    answer = None
                    try:
                        pr = client.llm_chat(messages=msgs, temperature=0.2, max_tokens=500, task_id=tid, task_type=int(task.get('task_number', 0)))
                        answer = pr.get('answer') if isinstance(pr, dict) else None
                    except Exception:
                        llm = get_llm_client()
                        if llm:
                            answer = llm.chat(messages=msgs, temperature=0.2, max_tokens=500)
                    err_msg = (answer or '').strip()
                    if not err_msg:
                        err_msg = 'Расскажи, что уже сделал — тогда смогу подсказать точнее.'
                    st.session_state['messages'].append({'role': 'assistant', 'content': err_msg})
                except Exception as e:
                    ex_str = str(e)
                    if '403' in ex_str or 'groq_error' in ex_str.lower() or 'forbidden' in ex_str.lower():
                        msg = 'Подсказка от ИИ недоступна (ошибка API 403). Проверьте GROQ_API_KEY или используйте GEMINI_API_KEY. Для этого задания подсказки в базе пока нет — синхронизируйте эталоны в удалённой админке.'
                    elif '401' in ex_str or 'unauthorized' in ex_str.lower():
                        msg = 'ИИ не настроен: неверный API‑ключ. Проверьте GROQ_API_KEY или GEMINI_API_KEY.'
                    else:
                        msg = f'Ошибка: {e}'
                    st.session_state['messages'].append({'role': 'assistant', 'content': msg})
            st.rerun()

        for m in st.session_state.get('messages', []):
            with st.chat_message(m.get('role', 'assistant')):
                st.markdown(m.get('content', ''))

        prompt = st.chat_input("Вопрос...")
        if prompt:
            st.session_state['messages'].append({'role': 'user', 'content': prompt})
            try:
                msgs = build_messages_for_help(task=task, code=code, analysis=st.session_state.get('analysis'), history=st.session_state.get('messages'), knowledge=knowledge)
                answer = None
                try:
                    pr = client.llm_chat(messages=msgs, temperature=0.2, max_tokens=700, task_id=tid, task_type=int(task.get('task_number', 0)))
                    answer = pr.get('answer') if isinstance(pr, dict) else None
                except Exception:
                    llm = get_llm_client()
                    if llm:
                        answer = llm.chat(messages=msgs, temperature=0.2, max_tokens=700)
                txt = (answer or '').strip()
                if not txt:
                    txt = 'LLM не настроен. Задайте GROQ_API_KEY или GEMINI_API_KEY в окружении тренажёра.'
                st.session_state['messages'].append({'role': 'assistant', 'content': txt})
            except Exception as e:
                ex_str = str(e)
                if '403' in ex_str or 'forbidden' in ex_str.lower():
                    msg = 'ИИ недоступен (403). Проверьте API‑ключ и лимиты.'
                elif '401' in ex_str or 'unauthorized' in ex_str.lower():
                    msg = 'ИИ не настроен: неверный API‑ключ.'
                else:
                    msg = f'Ошибка: {e}'
                st.session_state['messages'].append({'role': 'assistant', 'content': msg})
            st.rerun()

    with tab4:
        if st.button("🔄 Обновить", key="hist_refresh"):
            st.session_state['history_loaded'] = False

        if not st.session_state.get('history_loaded'):
            try:
                h = client.list_sessions(limit=25)
                st.session_state['history_items'] = h.get('sessions', []) if isinstance(h, dict) else []
                st.session_state['history_loaded'] = True
            except Exception:
                st.session_state['history_items'] = []
                st.session_state['history_loaded'] = True

        items = st.session_state.get('history_items', [])
        if not items:
            st.info("Нет сохранённых попыток")
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
