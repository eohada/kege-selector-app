from __future__ import annotations

import json
import os
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


def _render_task_html(task: dict[str, Any]):
    html = (task.get('content_html') or '').strip()
    if not html:
        st.info("У условия нет HTML-контента.")
        return
    components.html(f"""
    <div style="font-family: system-ui, -apple-system, Segoe UI, Roboto, Arial; color: #EAEAEA; line-height:1.6;">
      {html}
    </div>
    """, height=420, scrolling=True)


def main():
    _init_state()

    token = _get_query_param('token')
    qp_task_id = _get_query_param('task_id')
    qp_task_type = _get_query_param('task_type')
    base_url = get_platform_base_url()

    st.sidebar.markdown("### Подключение")
    if not base_url:
        st.sidebar.error("Не задан `PLATFORM_BASE_URL` (URL платформы Flask).")
        st.stop()
    if not token:
        st.sidebar.error("Нет token в URL. Открой тренажёр через платформу (/trainer).")
        st.stop()

    client = PlatformClient(base_url=base_url, token=token)

    if st.session_state['me'] is None:
        try:
            me = client.get_me()
            if not me.get('success'):
                raise RuntimeError(me.get('error') or 'unauthorized')
            st.session_state['me'] = me
        except Exception as e:
            st.sidebar.error(f"Не удалось авторизоваться: {e}")
            st.stop()

    user = (st.session_state['me'] or {}).get('user') or {}
    st.sidebar.success(f"Вход: {user.get('username')} ({user.get('role')})")

    st.sidebar.markdown("### Запуск кода")
    env_flag = (os.environ.get('TRAINER_ENABLE_RUNNER') or '').strip()
    if is_runner_enabled():
        st.sidebar.success(f"Раннер включён (`TRAINER_ENABLE_RUNNER={env_flag or '1'}`)")
    else:
        st.sidebar.warning("Раннер выключен в тренажёре (Streamlit).")
        st.sidebar.caption(f"Сейчас Streamlit видит `TRAINER_ENABLE_RUNNER={env_flag!r}`. Переменную нужно добавить именно в сервис тренажёра, а не только во Flask.")

    st.sidebar.markdown("### LLM")
    # Prefer platform-side LLM proxy (keys live in Flask), fallback to local env-based client.
    llm_info = None
    try:
        resp = client.llm_info()
        llm_info = (resp.get('llm') or {}) if isinstance(resp, dict) else None
    except Exception:
        llm_info = get_llm_info()

    if isinstance(llm_info, dict) and llm_info.get('configured') and (llm_info.get('picked') or {}).get('provider'):
        picked = llm_info.get('picked') or {}
        st.sidebar.success(f"Подключено: {picked.get('provider')} / {picked.get('model')}")
    else:
        st.sidebar.warning("LLM не подключён (нет ключей).")
        st.sidebar.caption("Можно настроить ключи в Flask (прокси) или в Streamlit. Нужны: `GROQ_API_KEY` или `GEMINI_API_KEY`.")

    if st.sidebar.button("Проверить LLM", use_container_width=True):
        # 1) Try platform proxy
        try:
            pr = client.llm_ping()
            ans = (pr.get('answer') or '') if isinstance(pr, dict) else ''
            st.sidebar.success(f"Ответ: {str(ans).strip()[:80]}")
        except Exception:
            # 2) Fallback to direct LLM from Streamlit env
            llm = get_llm_client()
            if not llm:
                st.sidebar.error("LLM клиент не создан (проверь env).")
            else:
                try:
                    ans = llm.chat(
                        messages=[{'role': 'system', 'content': 'Answer with a single word OK.'}, {'role': 'user', 'content': 'ping'}],
                        temperature=0.0,
                        max_tokens=5,
                    )
                    st.sidebar.success(f"Ответ: {str(ans).strip()[:80]}")
                except Exception as e:
                    st.sidebar.error(f"Ошибка LLM: {e}")

    st.sidebar.markdown("### Задание")
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

    # Pick a reasonable default: first available task_number, otherwise keep existing default
    if counts and int(st.session_state.get('task_type') or 0) not in counts:
        st.session_state['task_type'] = int(sorted(counts.keys())[0])

    options = list(range(1, 28))
    def _fmt(n: int) -> str:
        c = counts.get(int(n), 0)
        return f"№{n}  (в базе: {c})"

    task_type = st.sidebar.selectbox(
        "Номер задания",
        options=options,
        index=max(0, min(len(options) - 1, int(st.session_state.get('task_type') or 24) - 1)),
        format_func=_fmt,
    )
    st.session_state['task_type'] = int(task_type)
    st.session_state['seen_task_ids'].setdefault(int(task_type), [])

    if counts and counts.get(int(task_type), 0) <= 0:
        st.sidebar.warning("Для этого номера заданий нет в базе. Нужно сначала наполнить таблицу `Tasks`.")

    colA, colB = st.sidebar.columns(2)
    # Optional: pinned task_id from query params
    pinned_id: int | None = None
    if qp_task_id:
        try:
            pinned_id = int(qp_task_id)
        except Exception:
            pinned_id = None

    if colA.button("Старт", use_container_width=True):
        seen = st.session_state['seen_task_ids'].get(int(task_type), []) or []
        resp = client.stream_start(task_type=int(task_type), exclude_task_ids=seen, task_id=pinned_id)
        st.session_state['task'] = resp.get('task')
        st.session_state['analysis'] = None
        st.session_state['tests'] = None
        st.session_state['messages'] = []
        st.session_state['code'] = ''
        t = st.session_state.get('task') or {}
        if t.get('task_id'):
            seen = st.session_state['seen_task_ids'].setdefault(int(task_type), [])
            if int(t['task_id']) not in seen:
                seen.append(int(t['task_id']))
            # reset hint ladder for this task
            st.session_state['hint_level_by_task'][int(t['task_id'])] = 0

    if colB.button("Следующее", use_container_width=True):
        seen = st.session_state['seen_task_ids'].get(int(task_type), []) or []
        resp = client.stream_next(task_type=int(task_type), exclude_task_ids=seen)
        st.session_state['task'] = resp.get('task')
        st.session_state['analysis'] = None
        st.session_state['tests'] = None
        st.session_state['messages'] = []
        st.session_state['code'] = ''
        t = st.session_state.get('task') or {}
        if t.get('task_id'):
            seen = st.session_state['seen_task_ids'].setdefault(int(task_type), [])
            if int(t['task_id']) not in seen:
                seen.append(int(t['task_id']))
            # reset hint ladder for this task
            st.session_state['hint_level_by_task'][int(t['task_id'])] = 0

    # If task is not started yet but we have pinned task_id: load it once for convenience
    if st.session_state.get('task') is None and pinned_id is not None:
        try:
            resp = client.get_task(pinned_id)
            task = resp.get('task') if isinstance(resp, dict) else None
            if task and int(task.get('task_number') or 0) == int(task_type):
                st.session_state['task'] = task
                seen = st.session_state['seen_task_ids'].setdefault(int(task_type), [])
                if int(task.get('task_id')) not in seen:
                    seen.append(int(task.get('task_id')))
                st.session_state['hint_level_by_task'][int(task.get('task_id'))] = 0
        except Exception:
            pass

    task = st.session_state.get('task')
    if not task:
        st.title("Тренажёр")
        st.info("Нажми **Старт** слева, чтобы получить задание.")
        return

    # Sidebar: history (last attempts)
    st.sidebar.markdown("### История")
    if st.sidebar.button("Обновить историю", use_container_width=True):
        st.session_state['history_loaded'] = False
    if not st.session_state.get('history_loaded'):
        try:
            h = client.list_sessions(limit=25)
            st.session_state['history_items'] = (h.get('sessions') or []) if isinstance(h, dict) else []
            st.session_state['history_loaded'] = True
        except Exception as e:
            st.sidebar.caption(f"История недоступна: {e}")
            st.session_state['history_items'] = []
            st.session_state['history_loaded'] = True

    items = st.session_state.get('history_items') or []
    if items:
        options = []
        for it in items:
            label = f"#{it.get('session_id')} · task {it.get('task_type')} · {it.get('created_at')}"
            options.append((label, it))
        labels = [o[0] for o in options]
        sel = st.sidebar.selectbox("Открыть попытку", options=list(range(len(labels))), format_func=lambda i: labels[i])
        sel_item = options[int(sel)][1]
        if st.sidebar.button("Загрузить", use_container_width=True):
            try:
                sid = int(sel_item.get('session_id') or 0)
                if sid:
                    resp = client.get_session(sid)
                    sess = (resp.get('session') or {}) if isinstance(resp, dict) else {}
                    task_payload = resp.get('task') if isinstance(resp, dict) else None

                    if task_payload:
                        st.session_state['task'] = task_payload
                    else:
                        # fallback: try task_id
                        tid = int(sess.get('task_id') or 0)
                        if tid:
                            t_resp = client.get_task(tid)
                            t = t_resp.get('task') if isinstance(t_resp, dict) else None
                            if t:
                                st.session_state['task'] = t

                    st.session_state['code'] = (sess.get('code') or '')
                    st.session_state['analysis'] = sess.get('analysis')
                    st.session_state['tests'] = sess.get('tests')
                    msgs = sess.get('messages')
                    st.session_state['messages'] = msgs if isinstance(msgs, list) else []

                    # reset hint ladder for restored task
                    t = st.session_state.get('task') or {}
                    if t.get('task_id'):
                        st.session_state['hint_level_by_task'][int(t.get('task_id'))] = 0
                    st.rerun()
            except Exception as e:
                st.sidebar.caption(f"Не удалось открыть: {e}")

    st.title(f"Задание {task.get('task_number')} · ID {task.get('task_id')}")
    top = st.columns([2, 1, 1, 1])
    if top[0].button("Сохранить попытку", use_container_width=True):
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
            st.toast("Сохранено", icon=None)
        except Exception as e:
            st.error(f"Не удалось сохранить: {e}")

    if task.get('source_url'):
        top[1].markdown(f"[Источник]({task.get('source_url')})")

    if task.get('site_task_id'):
        top[2].markdown(f"site_id: `{task.get('site_task_id')}`")

    top[3].markdown(f"тип: `{task.get('task_number')}`")

    left, right = st.columns([1.2, 0.8], gap="large")

    with left:
        # Hint progress
        tid = int(task.get('task_id') or 0)
        knowledge = load_task_knowledge(tid) if tid else None
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
            st.caption(f"Подсказки: уровень {cur_lvl}/{max_lvl}")

        st.markdown("### Условие")
        _render_task_html(task)

        st.markdown("### Код")
        # Prefer full-featured editor (Ace/Monaco) if installed
        code_val = None
        try:
            from streamlit_ace import st_ace  # type: ignore
            # IMPORTANT: don't overwrite editor value on every Streamlit rerun.
            # Use the editor widget state as the source of truth to avoid "rollback while typing".
            editor_key = "code_editor"
            if editor_key not in st.session_state:
                st.session_state[editor_key] = st.session_state.get('code') or ""
            code_val = st_ace(
                key=editor_key,
                value=st.session_state.get(editor_key) or "",
                language="python",
                theme="monokai",
                keybinding="vscode",
                height=360,
                min_lines=18,
                font_size=14,
                tab_size=4,
                show_gutter=True,
                wrap=True,
                # Keep Streamlit state in sync while typing (prevents losing input on reruns).
                auto_update=True,
            )
            st.caption("Редактор: подсветка синтаксиса + keybindings как в IDE.")
        except Exception:
            code_val = st.text_area(
                "Вставь/пиши решение здесь",
                value=st.session_state.get('code') or "",
                height=300,
                placeholder="print('hello')",
            )
            st.caption("Подсветка недоступна: установи `streamlit-ace` (или запусти в окружении, где он уже есть).")
        if code_val is None:
            code_val = ""
        # Do NOT write into st.session_state[editor_key] after widget creation (Streamlit запрещает).
        # Keep a separate mirror value for our app logic.
        st.session_state['code_editor_value'] = code_val
        if len(code_val) > 20000:
            st.warning("Код слишком большой, обрезаю до 20 000 символов.")
            code_val = code_val[:20000]
        st.session_state['code'] = code_val

        btns = st.columns(3)
        if btns[0].button("Проанализировать (MVP)", use_container_width=True):
            code = st.session_state.get('code') or ''
            st.session_state['analysis'] = analyze_python_code(code)
            # Мягко подсказываем прямо в чат
            hints = (st.session_state['analysis'] or {}).get('hints') or []
            if hints:
                st.session_state['messages'].append({'role': 'assistant', 'content': 'Вот что я заметил:\n\n- ' + '\n- '.join(hints[:4])})

        if btns[1].button("Подсказка", use_container_width=True):
            t = st.session_state.get('task') or {}
            tid = int(t.get('task_id') or 0)
            current_level = int((st.session_state.get('hint_level_by_task') or {}).get(tid, 0) or 0)

            knowledge = load_task_knowledge(tid) if tid else None
            ladder = (knowledge or {}).get('hint_ladder') if isinstance(knowledge, dict) else None
            next_hint = None
            next_level = current_level
            if isinstance(ladder, list) and ladder:
                # find next by level field, fallback to list order
                sorted_ladder = []
                for item in ladder:
                    if isinstance(item, dict) and item.get('hint'):
                        try:
                            lvl = int(item.get('level') or 0)
                        except Exception:
                            lvl = 0
                        sorted_ladder.append((lvl, str(item.get('hint'))))
                sorted_ladder.sort(key=lambda x: (x[0] if x[0] else 10**9))
                # if levels are not provided, just use list order
                if all(lvl == 0 for (lvl, _) in sorted_ladder):
                    sorted_ladder = list(enumerate([h for (_, h) in sorted_ladder], start=1))

                for (lvl, h) in sorted_ladder:
                    if int(lvl) > int(current_level):
                        next_level = int(lvl)
                        next_hint = h
                        break

            if next_hint:
                st.session_state['hint_level_by_task'][tid] = next_level
                st.session_state['messages'].append({
                    'role': 'assistant',
                    'content': f"Подсказка (уровень {next_level}): {next_hint}\n\nВопрос: что именно ты будешь хранить в переменной для текущего состояния/прогресса?"
                })
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
                    # Prefer platform proxy, fallback to direct
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
                    answer = (answer or '').strip() or 'Сформулируй, что ты читаешь (строка/числа/файл) и что считаешь ответом. Я подстрою подсказку.'
                    st.session_state['messages'].append({'role': 'assistant', 'content': answer})
                except Exception as e:
                    st.session_state['messages'].append({'role': 'assistant', 'content': f'Ошибка обращения к LLM: {e}'})

        if btns[2].button("Очистить", use_container_width=True):
            st.session_state['code'] = ''
            st.session_state['analysis'] = None
            st.session_state['tests'] = None
            st.session_state['messages'] = []
            t = st.session_state.get('task') or {}
            if t.get('task_id'):
                st.session_state['hint_level_by_task'][int(t['task_id'])] = 0

        # Runner (feature-flagged)
        tests = (knowledge or {}).get('tests') if isinstance(knowledge, dict) else None
        if is_runner_enabled():
            st.markdown("### Запуск")
            st.caption("Раннер работает в ограниченном режиме (таймаут, лимит вывода, allowlist импортов).")

            run_tabs = st.tabs(["Запустить (stdin→stdout)", "Проверить тестами"])

            with run_tabs[0]:
                stdin_val = st.text_area("Ввод (stdin)", value=st.session_state.get('run_stdin') or "", height=140, placeholder="Например:\n5\n1 2 3 4 5\n")
                st.session_state['run_stdin'] = stdin_val
                expect = st.text_area("Ожидаемый вывод (необязательно)", value=st.session_state.get('run_expected') or "", height=90, placeholder="Если заполнишь — я сравню stdout.")
                st.session_state['run_expected'] = expect

                if st.button("▶ Запустить код", use_container_width=True):
                    res = run_python_program(code=st.session_state.get('code') or '', stdin=stdin_val, timeout_seconds=2.0)
                    st.session_state['run_result'] = res

                res = st.session_state.get('run_result')
                if res is not None:
                    ok = bool(res.get('ok'))
                    if ok:
                        st.success("Код выполнился.")
                    else:
                        st.error(f"Ошибка запуска: {res.get('error')}")
                        if res.get('details'):
                            st.code(str(res.get('details'))[:4000])

                    st.markdown("**stdout**")
                    st.code((res.get('stdout') or '')[:12000])
                    if res.get('stderr'):
                        st.markdown("**stderr**")
                        st.code((res.get('stderr') or '')[:6000])

                    if expect.strip():
                        got = (res.get('stdout') or '').strip()
                        exp = expect.strip()
                        if got == exp:
                            st.success("stdout совпал с ожидаемым.")
                        else:
                            st.warning("stdout НЕ совпал с ожидаемым (сравнение по `.strip()`).")

            with run_tabs[1]:
                if not tests:
                    st.info("Для этой задачи пока нет тестов в knowledge. Добавим позже при наполнении данных.")
                else:
                    st.caption("Для тестов добавь функцию `solve(s)`; runner вызовет её на тестовых input и сравнит expected.")
                    if st.button("🧪 Запустить тесты", use_container_width=True):
                        st.session_state['tests'] = run_python_solve_tests(code=st.session_state.get('code') or '', tests=tests)
                    if st.session_state.get('tests') is not None:
                        st.code(json.dumps(st.session_state['tests'], ensure_ascii=False, indent=2), language="json")
        else:
            st.caption("Запуск кода выключен на сервере. Чтобы включить: `TRAINER_ENABLE_RUNNER=1`.")

        if st.session_state.get('analysis') is not None:
            st.markdown("### Анализ")
            st.code(json.dumps(st.session_state['analysis'], ensure_ascii=False, indent=2), language="json")

    with right:
        st.markdown("### Чат помощника")
        for m in st.session_state.get('messages') or []:
            with st.chat_message(m.get('role') or 'assistant'):
                st.markdown(m.get('content') or '')

        prompt = st.chat_input("Напиши вопрос помощнику…")
        if prompt:
            st.session_state['messages'].append({'role': 'user', 'content': prompt})
            # Добавляем knowledge, если есть
            knowledge = load_task_knowledge(int(task.get('task_id') or 0)) if task.get('task_id') else None

            try:
                msgs = build_messages_for_help(
                    task=task,
                    code=st.session_state.get('code') or '',
                    analysis=st.session_state.get('analysis'),
                    history=st.session_state.get('messages'),
                    knowledge=knowledge,
                )
                # Prefer platform proxy, fallback to direct
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
                    st.session_state['messages'].append({'role': 'assistant', 'content': 'LLM пока не настроен (нет ключей). Скажи, какую идею ты хочешь реализовать, и я задам уточняющие вопросы.'})
                else:
                    answer = (answer or '').strip() or 'Не смог сформировать ответ. Попробуй переформулировать вопрос.'
                    st.session_state['messages'].append({'role': 'assistant', 'content': answer})
            except Exception as e:
                st.session_state['messages'].append({'role': 'assistant', 'content': f'Ошибка обращения к LLM: {e}'})
            st.rerun()


if __name__ == '__main__':
    main()

