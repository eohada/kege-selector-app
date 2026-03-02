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
    st.session_state.setdefault('daily_mix', None)
    st.session_state.setdefault('success_rates', {})
    st.session_state.setdefault('task_start_time', None)
    st.session_state.setdefault('show_hotkeys_modal', True)


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


def _inject_workbench_scripts():
    """Инъекция JS для ресайзера, Focus Mode и хоткеев."""
    st.markdown("""
<script>
(function() {
    if (window.__workbenchScriptsInjected) return;
    window.__workbenchScriptsInjected = true;

    function setupResizer() {
        const resizer = document.querySelector('.workbench-resizer');
        if (!resizer) return;
        const row = resizer.closest('[data-testid="stHorizontalBlock"]');
        if (!row) return;
        const cols = row.querySelectorAll('[data-testid="column"]');
        if (cols.length < 3) return;
        const left = cols[0];
        const right = cols[2];

        let isResizing = false;
        resizer.onmousedown = (e) => {
            isResizing = true;
            document.body.style.cursor = 'col-resize';
            e.preventDefault();
        };

        document.onmousemove = (e) => {
            if (!isResizing) return;
            const rect = row.getBoundingClientRect();
            const width = ((e.clientX - rect.left) / rect.width) * 100;
            if (width > 20 && width < 80) {
                left.style.minWidth = '0';
                left.style.flex = `0 0 ${width}%`;
                left.style.width = `${width}%`;
                right.style.minWidth = '0';
                right.style.flex = `1 1 auto`;
            }
        };

        document.onmouseup = () => {
            isResizing = false;
            document.body.style.cursor = 'default';
        };
    }

    window.toggleFocusMode = function() {
        const el = document.documentElement;
        const current = el.getAttribute('data-focus-mode');
        el.setAttribute('data-focus-mode', current === 'active' ? '' : 'active');
    };

    window.addEventListener('keydown', (e) => {
        if (e.key === 'F11') {
            e.preventDefault();
            window.toggleFocusMode();
        }
        if (e.ctrlKey && e.key === 'Enter') {
            const btns = Array.from(document.querySelectorAll('button'));
            const checkBtn = btns.find(b => b.innerText.includes('Проверить') || b.innerText.includes('ОТПРАВИТЬ'));
            if (checkBtn) checkBtn.click();
        }
        if (e.altKey && e.key === 'ArrowRight') {
            const btns = Array.from(document.querySelectorAll('button'));
            const nextBtn = btns.find(b => b.innerText.includes('Следующее'));
            if (nextBtn) nextBtn.click();
        }
    });

    // Inactivity check for AI pulse
    let lastActivity = Date.now();
    const updateActivity = () => { lastActivity = Date.now(); };
    ['mousedown', 'mousemove', 'keypress', 'scroll', 'touchstart'].forEach(n => document.addEventListener(n, updateActivity));
    
    setInterval(() => {
        const aiBtn = document.querySelector('.floating-ai-btn');
        if (!aiBtn) return;
        const isInactive = (Date.now() - lastActivity) > 180000; // 3 min
        aiBtn.classList.toggle('pulse', isInactive);
    }, 5000);

    setInterval(setupResizer, 1500);
})();
</script>
""", unsafe_allow_html=True)


def main():
    _inject_css()
    _inject_theme_script()
    _inject_workbench_scripts()
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
    success_rates = {}
    try:
        stats = client.get_task_stats()
        raw = stats.get('counts_by_task_number', {}) if isinstance(stats, dict) else {}
        counts = {int(k): int(v) for k, v in raw.items() if v}
        
        rates_resp = client.get_task_success_rates()
        success_rates = rates_resp.get('rates', {}) if isinstance(rates_resp, dict) else {}
        st.session_state['success_rates'] = success_rates
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

    # Hotkeys Modal
    if st.session_state.get('show_hotkeys_modal'):
        with st.container(border=True):
            st.markdown("""
            ### ⌨️ Горячие клавиши Тренажёра
            - **Ctrl + Enter**: Отправить ответ на проверку
            - **Alt + Right**: Следующее задание
            - **F11**: Дзен-режим (Focus Mode)
            - **Ctrl + Space**: Автодополнение (в редакторе)
            """)
            if st.button("Понятно, в бой!"):
                st.session_state['show_hotkeys_modal'] = False
                st.rerun()

    if task_type is None and task is None:
        stats = {}
        try:
            stats = client.get_stats()
        except Exception:
            pass
        sessions_today = stats.get('sessions_today', 0) or 0
        streak = st.session_state.get('session_task_count', 0)
        
        # Визуализация стрик (огня)
        fire_emoji = "🔥" if streak > 0 else "🌑"
        streak_html = f"""
        <div style="display:flex;justify-content:center;margin-top:1.5rem;margin-bottom:0.5rem;">
            <div class="streak-box">
                <span class="streak-fire">{fire_emoji}</span>
                <span class="streak-count">{streak}</span>
                <div class="streak-label">задач в сессии</div>
            </div>
        </div>
        """

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
            <p class="hero-sub">Привет, {username}! Твоя цель на сегодня — прогресс.</p>
            {streak_html}
            <p class="trainer-hero-hint">Решай подобранные задачи или выбирай номера для тренировки конкретных тем.</p>
        </div>
        """, unsafe_allow_html=True)

        # Smart-лента (Daily Mix)
        if st.button("✨ ПОДОБРАНО ДЛЯ ТЕБЯ НА СЕГОДНЯ (DAILY MIX)", use_container_width=True, type="primary"):
            try:
                recs_resp = client.get_recommendations()
                recs = recs_resp.get('recommendations', [])
                if recs:
                    st.session_state['daily_mix'] = recs
                    first = recs[0]
                    st.session_state['task'] = first
                    st.session_state['task_type'] = first.get('task_number')
                    st.session_state['session_task_count'] = streak + 1
                    _reset_workbench()
                    st.rerun()
                else:
                    st.warning("Не удалось подобрать рекомендации.")
            except Exception as e:
                st.error(f"Рекомендации: {e}")

        if show_continue and last_session:
            tt = last_session.get('task_type')
            created = last_session.get('created_at') or ''
            if created and len(created) >= 10:
                created = created[:10] + ' ' + created[11:19] if len(created) > 19 else created[:16]
            st.markdown(f"""
            <div class="task-card trainer-continue-card" style="margin-top:1rem;margin-bottom:0.5rem;padding:1.25rem;">
                <div class="task-card-header" style="margin-bottom:0.5rem;padding-bottom:0.5rem;">
                    <span class="task-badge primary">Продолжить</span>
                </div>
                <p class="task-body" style="margin:0;font-size:0.85rem;">Задание №{tt} · {created}</p>
            </div>
            """, unsafe_allow_html=True)
            if st.button("Продолжить с задания №" + str(tt), key="continue_last", use_container_width=True):
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
                        st.session_state['session_task_count'] = streak + 1
                        st.rerun()
                except Exception as e:
                    st.error(f"Не удалось загрузить сессию: {e}")

        st.markdown("<div style='margin-top:2rem;text-align:center;'>### Сетка заданий</div>", unsafe_allow_html=True)
        
        for row_start in [1, 10, 19]:
            cols = st.columns(9)
            for i, n in enumerate(range(row_start, min(row_start + 9, 28))):
                count = counts.get(n, 0)
                rate = success_rates.get(n)
                
                with cols[i]:
                    disabled = count == 0
                    label = f"{n}\n({count})" if count > 0 else f"{n}\n—"
                    # Инжектируем wrapper для heatmap
                    st.markdown(f"<div class='num-cell-wrapper' data-rate='{rate or 0}'>", unsafe_allow_html=True)
                    if st.button(label, key=f"num_{n}", disabled=disabled, use_container_width=True):
                        st.session_state['task_type'] = n
                        st.session_state['current_card'] = None
                        st.rerun()
                    st.markdown("</div>", unsafe_allow_html=True)
        return

    if task is None and task_type is not None:
        # Бесшовный вход: сразу тянем задачу и в воркбенч
        card = _pull_task(client, int(task_type))
        if card:
            st.session_state['task'] = card
            st.session_state['session_task_count'] = (st.session_state.get('session_task_count', 0) or 0) + 1
            st.session_state['task_start_time'] = datetime.now()
            _reset_workbench()
            st.rerun()
        else:
            st.warning("Задания этого типа закончились!")
            if st.button("← Назад к выбору"):
                st.session_state['task_type'] = None
                st.rerun()
            return

    # Воркбенч
    if task:
        tid = int(task.get('task_id', 0))
        task_num = task.get('task_number')
        knowledge = load_task_knowledge(tid, task_number=task_num) if (tid or task_num) else None
        tests = (knowledge or {}).get('tests') if isinstance(knowledge, dict) else None

        # Панель управления
        ctrl_c1, ctrl_c2, ctrl_c3 = st.columns([1, 2, 1])
        with ctrl_c1:
            st.markdown('<div class="back-btn" id="trainer-back-workbench"></div>', unsafe_allow_html=True)
            if st.button("← Выход", use_container_width=True):
                st.session_state['task'] = None
                _reset_workbench()
                st.rerun()
        with ctrl_c2:
            st.markdown(f"<div style='text-align:center;'><span style='font-size:1.2rem;font-weight:700;'>№{task.get('task_number')}</span> · ID {tid}</div>", unsafe_allow_html=True)
            streak = st.session_state.get('session_task_count', 1)
            st.markdown(f"<p class='trainer-session-strip'>задание в сессии: {streak} <button onclick='window.toggleFocusMode()' style='background:transparent;border:none;cursor:pointer;font-size:0.8rem;margin-left:0.5rem;opacity:0.6;'>[Дзен]</button></p>", unsafe_allow_html=True)
        with ctrl_c3:
            if st.button("→ Следующее", use_container_width=True):
                next_card = _pull_task(client, int(task_type))
                if next_card:
                    st.session_state['task'] = next_card
                    st.session_state['session_task_count'] = streak + 1
                    st.session_state['task_start_time'] = datetime.now()
                    _reset_workbench()
                    st.rerun()
                else:
                    st.session_state['task'] = None
                    st.session_state['task_type'] = None
                    st.rerun()

        # Split-Screen
        w_left, w_resizer, w_right = st.columns([4, 0.1, 6])
        
        with w_left:
            st.markdown('<div class="workbench-left">', unsafe_allow_html=True)
            content = (task.get('content_html') or '').strip()
            st.markdown(f"""
            <div class="task-card" style="padding:1.5rem; margin:0 0 1rem 0;">
                <div class="task-body">{content}</div>
            </div>
            """, unsafe_allow_html=True)
            
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
            
            if task.get('source_url'):
                st.markdown(f"[Открыть источник ↗]({task.get('source_url')})")
            st.markdown('</div>', unsafe_allow_html=True)

        with w_resizer:
            st.markdown('<div class="workbench-resizer"></div>', unsafe_allow_html=True)

        with w_right:
            st.markdown('<div class="workbench-right">', unsafe_allow_html=True)
            _code_val = st.session_state.get('code', '')
            try:
                from streamlit_ace import st_ace
                code = st_ace(value=_code_val, language="python", theme="monokai", key="code_ace", height=400)
            except Exception:
                code = st.text_area("Код:", value=_code_val, height=400, key="code_area")
            
            if code is not None:
                st.session_state['code'] = code
            else:
                code = _code_val

            # Панель действий под кодом
            act_c1, act_c2, act_c3 = st.columns(3)
            with act_c1:
                if st.button("▶ ЗАПУСТИТЬ", use_container_width=True, key="run_main"):
                    st.session_state['run_result'] = run_python_program(code=code, timeout_seconds=2.0)
            with act_c2:
                if st.button("🧪 ТЕСТЫ", use_container_width=True, key="test_main"):
                    if tests:
                        st.session_state['tests'] = run_python_solve_tests(code=code, tests=tests)
                    else:
                        st.info("Нет тестов")
            with act_c3:
                if st.button("🔍 АНАЛИЗ", use_container_width=True, key="analyze_main"):
                    st.session_state['analysis'] = analyze_python_code(code)

            # Ответ
            st.markdown("<div style='margin-top:1rem;'></div>", unsafe_allow_html=True)
            ans_val = st.text_input("Введи ответ:", key="user_answer_wb", placeholder="Ваш ответ...")
            
            if st.button("🚀 ОТПРАВИТЬ НА ПРОВЕРКУ", use_container_width=True, type="primary", key="submit_wb"):
                if not ans_val.strip():
                    st.warning("Сначала введи ответ!")
                else:
                    # Считаем время
                    spent = 0
                    if st.session_state.get('task_start_time'):
                        spent = int((datetime.now() - st.session_state['task_start_time']).total_seconds())
                    
                    try:
                        res = client.submit_answer(tid, ans_val, time_spent_sec=spent)
                        if res.get('is_correct'):
                            st.success("✅ ВЕРНО! Ты молодец!")
                            st.balloons()
                            # Сохраняем в сессию
                            client.save_session(
                                task_id=tid, task_type=task_num, language='python', code=code,
                                analysis=st.session_state.get('analysis'), tests=st.session_state.get('tests')
                            )
                        else:
                            st.error(f"❌ НЕВЕРНО. Ожидалось: {res.get('expected')}")
                    except Exception as e:
                        st.error(f"Ошибка отправки: {e}")

            # Выезжающий терминал (результат запуска)
            run_res = st.session_state.get('run_result')
            if run_res:
                with st.expander("💻 Терминал", expanded=True):
                    if run_res.get('ok'):
                        st.success("Выполнено")
                    else:
                        st.error(f"Ошибка: {run_res.get('error')}")
                    stdout = (run_res.get('stdout') or '').strip()
                    if stdout:
                        st.code(stdout)
                    elif not run_res.get('ok'):
                        st.code(run_res.get('details') or 'Нет деталей')

            # Хинты (Floating Assistant)
            st.markdown('<div id="ai-anchor"></div>', unsafe_allow_html=True)
            with st.expander("🤖 ПОМОЩНИК ИИ", expanded=len(st.session_state.get('messages', [])) > 0):
                ladder = (knowledge or {}).get('hint_ladder') if isinstance(knowledge, dict) else None
                cur_lvl = st.session_state.get('hint_level_by_task', {}).get(tid, 0) or 0
                
                hint_labels = ["Наводящий вопрос", "Ключевая идея", "Скелет кода / Формула"]
                next_lvl = cur_lvl + 1
                
                if next_lvl <= 3:
                    btn_text = f"💡 Дать подсказку: {hint_labels[next_lvl-1]}"
                    if st.button(btn_text, use_container_width=True, key=f"hint_btn_{tid}_{next_lvl}"):
                        hint = None
                        # 1) Платформа
                        try:
                            hr = client.get_hint(tid, level=next_lvl)
                            if hr.get('success'):
                                hint = hr.get('hint')
                        except Exception: pass
                        
                        # 2) Локальный ladder
                        if not hint and isinstance(ladder, list):
                            for l_item in ladder:
                                if int(l_item.get('level', 0)) == next_lvl:
                                    hint = l_item.get('hint') or l_item.get('text')
                                    break
                        
                        # 3) LLM
                        if not hint:
                            try:
                                msgs = build_messages_for_help(
                                    task=task, code=code, analysis=st.session_state.get('analysis'),
                                    history=st.session_state.get('messages', []) + [{'role': 'user', 'content': f'Дай подсказку уровня {next_lvl} ({hint_labels[next_lvl-1]}).'}],
                                    knowledge=knowledge, fallback_mode=True
                                )
                                pr = client.llm_chat(messages=msgs, task_id=tid)
                                hint = pr.get('answer')
                            except Exception as e:
                                hint = f"Ошибка ИИ: {e}"
                        
                        if hint:
                            st.session_state['hint_level_by_task'][tid] = next_lvl
                            st.session_state['messages'].append({'role': 'assistant', 'content': f"**Подсказка {next_lvl} ({hint_labels[next_lvl-1]}):**\n\n{hint}"})
                            st.rerun()

                # История чата
                for m in st.session_state.get('messages', []):
                    with st.chat_message(m.get('role', 'assistant')):
                        st.markdown(m.get('content', ''))

                prompt = st.chat_input("Задать свой вопрос ИИ...")
                if prompt:
                    st.session_state['messages'].append({'role': 'user', 'content': prompt})
                    try:
                        msgs = build_messages_for_help(task=task, code=code, history=st.session_state.get('messages'), knowledge=knowledge)
                        pr = client.llm_chat(messages=msgs, task_id=tid)
                        st.session_state['messages'].append({'role': 'assistant', 'content': pr.get('answer', 'Нет ответа')})
                    except Exception as e:
                        st.session_state['messages'].append({'role': 'assistant', 'content': f"Ошибка: {e}"})
                    st.rerun()

            # Floating Icon for AI
            st.markdown("""
            <div class="floating-ai-btn pulse" onclick="const s = document.querySelector('details:has(#ai-anchor)'); if(s) s.open = !s.open;">
                <span>🤖</span>
            </div>
            """, unsafe_allow_html=True)
            
            st.markdown('</div>', unsafe_allow_html=True)

        return


if __name__ == '__main__':
    main()
