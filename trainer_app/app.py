from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote

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
    theme_path = os.path.join(os.path.dirname(__file__), 'static', 'trainer_theme.css')
    if os.path.isfile(theme_path):
        with open(theme_path, 'r', encoding='utf-8') as f:
            css = f.read()
        st.markdown(f'<style>\n{css}\n</style>', unsafe_allow_html=True)
    else:
        st.markdown(
            '<style>html,body{font-family:system-ui,sans-serif;background:#06080D;color:#fff;}</style>',
            unsafe_allow_html=True,
        )


def _inject_theme_script():
    """Скрипт приёма темы от родителя (postMessage) и из query params."""
    st.markdown("""
<script>
(function() {
  if (window.__trainerThemeListener) return;
  window.__trainerThemeListener = true;
  function apply(t) {
    if (t === 'light' || t === 'dark') document.documentElement.setAttribute('data-theme', t);
  }
  window.addEventListener('message', function(e) {
    if (e.data && e.data.type === 'trainer-theme' && (e.data.theme === 'light' || e.data.theme === 'dark'))
      apply(e.data.theme);
  });
  var q = new URLSearchParams(window.location.search);
  var param = q.get('theme');
  if (param === 'light' || param === 'dark') apply(param);
  if (window.parent !== window) {
    setTimeout(function() { window.parent.postMessage({ type: 'trainer-theme-request' }, '*'); }, 300);
  }
})();
</script>
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
    st.session_state.setdefault('session_task_count', 0)


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
    _inject_theme_script()
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

    # Отладочный режим для создателя (trainer.manage_knowledge)
    permissions = (st.session_state.get('me') or {}).get('permissions') or []
    is_creator = 'trainer.manage_knowledge' in permissions

    with st.sidebar:
        with st.expander("🔧 Диагностика LLM (403)"):
            if st.button("Проверить ключи и тест LLM", key="diag_btn"):
                try:
                    dr = client.llm_diagnose(test=True)
                    d = (dr.get('diagnose') or {}) if isinstance(dr, dict) else {}
                    st.json(d)
                    if not d.get('test_success') and d.get('test_error'):
                        err = (d.get('test_error') or '')
                        if '403' in err or 'forbidden' in err.lower():
                            st.warning("403 / Forbidden. Настройте GIGACHAT_CREDENTIALS в окружении.")
                        elif 'gigachat' in err.lower() and 'ssl' in err.lower():
                            st.info("GigaChat SSL: установите GIGACHAT_CA_BUNDLE_FILE или GIGACHAT_VERIFY_SSL_CERTS=false для разработки")
                except Exception as ex:
                    st.error(str(ex))

        if is_creator:
            with st.expander("📋 Задания для проверки фоллбэка"):
                st.caption("Без hints в БД, но с trainer_knowledge — фоллбэк сработает.")
                if st.button("Загрузить список", key="fallback_load_btn"):
                    try:
                        fc = client.get_fallback_candidates()
                        cts = (fc.get('counts_by_task_number') or {})
                        st.session_state['fallback_candidates'] = {int(k): int(v) for k, v in cts.items() if v}
                        st.session_state['fallback_candidates_loaded'] = True
                    except Exception as e:
                        st.error(f"Ошибка: {str(e)[:150]}")
                fc_cached = st.session_state.get('fallback_candidates') or {}
                fc_loaded = st.session_state.get('fallback_candidates_loaded', False)
                if fc_cached:
                    st.markdown("**Без hints, с knowledge:**")
                    for n in sorted(fc_cached.keys()):
                        cnt = fc_cached[n]
                        if st.button(f"№{n} ({cnt} шт)", key=f"fc_btn_{n}"):
                            st.session_state['task_type'] = n
                            st.session_state['task'] = None
                            st.session_state['current_card'] = None
                            st.rerun()
                elif fc_loaded:
                    st.warning("Нет заданий без hints с knowledge. Добавьте trainer_knowledge или синхронизируйте эталоны.")
                else:
                    st.info("Нажмите «Загрузить список».")

        if is_creator and st.session_state.get('task'):
            task = st.session_state['task']
            tid = int(task.get('task_id', 0))
            task_num = task.get('task_number')
            knowledge = load_task_knowledge(tid, task_number=task_num) if (tid or task_num) else None
            has_hints = task.get('has_hints_in_db', False)
            has_knowledge = bool(knowledge) and (knowledge.get('hint_ladder') or knowledge.get('common_mistakes') or knowledge.get('reference_solution'))
            rag_index_exists = False
            try:
                from trainer_app.llm.rag import _get_index_path
                import os
                rag_index_exists = os.path.exists(_get_index_path())
            except Exception:
                pass
            with st.expander("🐛 Отладка задания (создатель)"):
                st.caption("Для теста LLM-фоллбэка: выбирай задания без hints в БД, но с knowledge или RAG.")
                st.markdown(f"- **hints в БД:** {'да' if has_hints else 'нет'}")
                st.markdown(f"- **trainer_knowledge:** {'да' if has_knowledge else 'нет'}")
                st.markdown(f"- **RAG индекс:** {'есть' if rag_index_exists else 'нет'}")
                rag_cache_key = f'rag_has_examples_{tid}'
                rag_has_examples = st.session_state.get(rag_cache_key)
                if st.button("Проверить RAG для задания", key="rag_check_btn"):
                    rag_has_examples = False
                    if rag_index_exists and (task.get('content_html') or '').strip():
                        try:
                            from trainer_app.llm.rag import retrieve_similar_hints
                            examples = retrieve_similar_hints(task.get('content_html') or '', k=1)
                            rag_has_examples = bool(examples)
                            st.session_state[rag_cache_key] = rag_has_examples
                            st.markdown(f"- **RAG примеры для задания:** {'да' if rag_has_examples else 'нет'}")
                        except Exception as e:
                            st.warning(f"RAG: {str(e)[:100]}")
                    else:
                        st.info("RAG индекс не найден или задание без текста.")
                elif rag_has_examples is not None:
                    st.markdown(f"- **RAG примеры для задания:** {'да' if rag_has_examples else 'нет'}")
                if not has_hints:
                    if has_knowledge or rag_has_examples:
                        st.success("→ Подходит для проверки LLM-фоллбэка")
                    elif not has_knowledge and not rag_index_exists:
                        st.warning("→ Нет контекста: LLM не вызовется")
                    elif not has_knowledge and rag_index_exists and rag_has_examples is None:
                        st.info("→ Нажмите «Проверить RAG», чтобы узнать, есть ли примеры")

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
        stats = {}
        try:
            stats = client.get_stats()
        except Exception:
            pass
        sessions_today = stats.get('sessions_today', 0) or 0
        last_session = stats.get('last_session')
        def _last_session_ok(ls):
            if not ls or not ls.get('session_id'):
                return False
            created = ls.get('created_at')
            if not created:
                return True
            try:
                dt = datetime.fromisoformat(created.replace('Z', '+00:00'))
                if dt.tzinfo:
                    now = datetime.now(timezone.utc)
                else:
                    now = datetime.now()
                return (now - dt).days < 7
            except Exception:
                return True
        show_continue = _last_session_ok(last_session)

        st.markdown(f"""
        <div class="hero-box">
            <p class="hero-eyebrow">тренажёр</p>
            <h1 class="hero-title">Тренажёр КЕГЭ</h1>
            <p class="hero-sub">Привет, {username}! Выбери номер задания</p>
            <p class="trainer-hero-hint">Выбери номер — получи задание — решай с подсказками или переходи к следующему.</p>
            <p class="hero-sub" style="margin-top:0.25rem;font-size:0.9rem;">Сегодня: {sessions_today} заданий</p>
        </div>
        """, unsafe_allow_html=True)

        if show_continue and last_session:
            tt = last_session.get('task_type')
            created = last_session.get('created_at') or ''
            if created and len(created) >= 10:
                created = created[:10] + ' ' + created[11:19] if len(created) > 19 else created[:16]
            st.markdown(f"""
            <div class="task-card trainer-continue-card" style="margin-bottom:1rem;">
                <div class="task-card-header">
                    <span class="task-badge primary">Продолжить</span>
                </div>
                <p class="task-body" style="margin:0;">Задание №{tt} · {created}</p>
            </div>
            """, unsafe_allow_html=True)
            if st.button("Продолжить с задания №" + str(tt), key="continue_last", use_container_width=True, type="primary"):
                try:
                    resp = client.get_session(int(last_session['session_id']))
                    if resp.get('success') and resp.get('session') and resp.get('task'):
                        sess = resp['session']
                        st.session_state['task'] = resp['task']
                        st.session_state['task_type'] = sess.get('task_type')
                        st.session_state['code'] = sess.get('code') or ''
                        st.session_state['analysis'] = sess.get('analysis')
                        st.session_state['tests'] = sess.get('tests')
                        st.session_state['messages'] = (sess.get('messages') or []) if isinstance(sess.get('messages'), list) else []
                        st.session_state['current_card'] = None
                        st.session_state['session_task_count'] = (st.session_state.get('session_task_count') or 0) + 1
                        st.rerun()
                except Exception as e:
                    st.error(f"Не удалось загрузить сессию: {e}")

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
        
        st.markdown('<div class="back-btn" id="trainer-back-btn"></div>', unsafe_allow_html=True)
        if st.button("← Сменить номер", key="back_btn", use_container_width=True):
            st.session_state['task_type'] = None
            st.session_state['current_card'] = None
            st.rerun()
        
        st.markdown(f"""
        <div class="trainer-screen-title">Задание №{task_type}</div>
        <p class="trainer-screen-sub">Пропусти или начни решать</p>
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
                st.session_state['session_task_count'] = (st.session_state.get('session_task_count') or 0) + 1
                _reset_workbench()
                st.rerun()
        
        return

    tid = int(task.get('task_id', 0))
    task_num = task.get('task_number')
    knowledge = load_task_knowledge(tid, task_number=task_num) if (tid or task_num) else None
    tests = (knowledge or {}).get('tests') if isinstance(knowledge, dict) else None

    col1, col2, col3 = st.columns([1, 2, 1])
    session_task_count = st.session_state.get('session_task_count', 0) or 0
    with col1:
        st.markdown('<div class="back-btn" id="trainer-back-workbench"></div>', unsafe_allow_html=True)
        if st.button("← Назад", use_container_width=True):
            st.session_state['task'] = None
            st.session_state['current_card'] = None
            _reset_workbench()
            st.rerun()
    with col2:
        st.markdown(f"<div class='trainer-screen-title'>Задание №{task.get('task_number')} · ID {tid}</div>", unsafe_allow_html=True)
        st.markdown(f"<p class='trainer-session-strip'>Сессия: задание {session_task_count}</p>", unsafe_allow_html=True)
    with col3:
        if st.button("→ Следующее", use_container_width=True):
            next_card = _pull_task(client, int(task_type))
            if next_card:
                st.session_state['task'] = next_card
                st.session_state['current_card'] = None
                st.session_state['session_task_count'] = session_task_count + 1
                _reset_workbench()
                st.rerun()
            else:
                st.session_state['task'] = None
                st.session_state['task_type'] = None
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
        # Вложения
        af_raw = task.get('attached_files')
        if af_raw:
            try:
                files = json.loads(af_raw) if isinstance(af_raw, str) else (af_raw if isinstance(af_raw, list) else [])
            except Exception:
                files = []
            if files:
                st.markdown("**📎 Вложения:**")
                for f in files:
                    if isinstance(f, dict):
                        path = f.get('path') or f.get('url') or ''
                        name = f.get('name') or f.get('filename') or (path.split('/')[-1] if path else 'файл')
                    else:
                        path = str(f).strip()
                        name = path.split('/')[-1] if path else 'файл'
                    if path and not path.startswith('http'):
                        attach_url = f"{get_platform_base_url()}/internal/trainer/task/{tid}/attachment?path={quote(path)}&token={client.token}"
                        st.markdown(f"- [{name}]({attach_url})")
                    elif path:
                        st.markdown(f"- [{name}]({path})")

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
        cur = st.session_state.get('hint_level_by_task', {}).get(tid, 0) or 0
        btn_label = "💡 Следующая подсказка" if cur > 0 else "💡 Получить подсказку"

        if st.button(btn_label, use_container_width=True):
            next_level = min(3, cur + 1)
            hint = None
            lvl = next_level
            platform_404 = False

            # 1) Сначала подсказка с платформы (эталоны из БД)
            try:
                hr = client.get_hint(tid, level=next_level)
                if isinstance(hr, dict):
                    if hr.get('success') and hr.get('hint'):
                        hint = (hr.get('hint') or '').strip()
                        lvl = int(hr.get('level', next_level))
                    elif hr.get('error') == 'no_hint':
                        platform_404 = True
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
                st.session_state['messages'].append({'role': 'assistant', 'content': f"Подсказка номер {lvl}: {hint}"})
            elif platform_404:
                # Фоллбэк: LLM придумывает подсказку, опираясь ТОЛЬКО на наш контекст (knowledge, RAG)
                has_context = bool(
                    (isinstance(ladder, list) and ladder)
                    or (isinstance(knowledge, dict) and (knowledge.get('common_mistakes') or knowledge.get('reference_solution')))
                )
                from trainer_app.llm.rag import get_rag_examples_prompt
                if not has_context:
                    has_context = bool(get_rag_examples_prompt(task.get('content_html') or '', k=1))
                if has_context:
                    try:
                        msgs = build_messages_for_help(
                            task=task,
                            code=code,
                            analysis=st.session_state.get('analysis'),
                            history=st.session_state.get('messages', []) + [{'role': 'user', 'content': f'Дай подсказку уровня {next_level}.'}],
                            knowledge=knowledge,
                            fallback_mode=True,
                        )
                        answer = None
                        try:
                            pr = client.llm_chat(messages=msgs, temperature=0.2, max_tokens=500, task_id=tid, task_type=int(task.get('task_number', 0)))
                            answer = pr.get('answer') if isinstance(pr, dict) else None
                        except Exception:
                            llm = get_llm_client()
                            if llm:
                                answer = llm.chat(messages=msgs, temperature=0.2, max_tokens=500)
                        err_msg = (answer or '').strip()
                        if err_msg:
                            st.session_state['hint_level_by_task'][tid] = next_level
                            st.session_state['messages'].append({'role': 'assistant', 'content': f"Подсказка номер {next_level}: {err_msg}"})
                        else:
                            st.session_state['messages'].append({'role': 'assistant', 'content': 'Для этого задания готовых подсказок нет. Попробуй сформулировать вопрос в чате ниже.'})
                    except Exception as e:
                        ex_str = str(e)
                        if '403' in ex_str or 'gigachat_error' in ex_str.lower() or 'forbidden' in ex_str.lower():
                            msg = 'Подсказка от ИИ недоступна (ошибка API 403). Настройте GIGACHAT_CREDENTIALS. Для этого задания подсказок в базе нет.'
                        elif '401' in ex_str or 'unauthorized' in ex_str.lower():
                            msg = 'ИИ не настроен: неверный API‑ключ.'
                        else:
                            msg = f'Ошибка: {e}'
                        st.session_state['messages'].append({'role': 'assistant', 'content': msg})
                else:
                    st.session_state['messages'].append({'role': 'assistant', 'content': 'Для этого задания готовых подсказок нет. Добавьте эталон в trainer_knowledge или синхронизируйте эталоны в админке. Либо сформулируйте свой вопрос в чате — попробую подсказать по аналогии.'})
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
                    if '403' in ex_str or 'gigachat_error' in ex_str.lower() or 'forbidden' in ex_str.lower():
                        msg = 'Подсказка от ИИ недоступна (ошибка API 403). Настройте GIGACHAT_CREDENTIALS. Для этого задания подсказки в базе пока нет — синхронизируйте эталоны в удалённой админке.'
                    elif '401' in ex_str or 'unauthorized' in ex_str.lower():
                        msg = 'ИИ не настроен: неверный API‑ключ. Проверьте GIGACHAT_CREDENTIALS.'
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
                    txt = 'LLM не настроен. Задайте GIGACHAT_CREDENTIALS в окружении тренажёра.'
                st.session_state['messages'].append({'role': 'assistant', 'content': txt})
            except Exception as e:
                ex_str = str(e)
                if '403' in ex_str or 'forbidden' in ex_str.lower():
                    msg = 'ИИ недоступен (403). Настройте GIGACHAT_CREDENTIALS или проверьте API‑ключ и лимиты.'
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
