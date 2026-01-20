from __future__ import annotations

import json
import os
from typing import Any

import streamlit as st
import streamlit.components.v1 as components

from trainer_app.platform_client import PlatformClient, get_platform_base_url
from trainer_app.analyzers.python_static import analyze_python_code
from trainer_app.knowledge import load_task_knowledge
from trainer_app.llm.providers import get_llm_client, build_messages_for_help
from trainer_app.runner.sandbox import is_runner_enabled, run_python_solve_tests


st.set_page_config(page_title="Тренажёр · AI помощник", layout="wide")


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

    st.sidebar.markdown("### Задание")
    task_type = st.sidebar.number_input("Номер задания", min_value=1, max_value=27, step=1, value=int(st.session_state['task_type']))
    st.session_state['task_type'] = int(task_type)

    colA, colB = st.sidebar.columns(2)
    if colA.button("Старт", use_container_width=True):
        resp = client.stream_start(task_type=int(task_type))
        st.session_state['task'] = resp.get('task')
        st.session_state['analysis'] = None
        st.session_state['tests'] = None
        st.session_state['messages'] = []
        st.session_state['code'] = ''

    if colB.button("Следующее", use_container_width=True):
        resp = client.stream_next(task_type=int(task_type))
        st.session_state['task'] = resp.get('task')
        st.session_state['analysis'] = None
        st.session_state['tests'] = None
        st.session_state['messages'] = []
        st.session_state['code'] = ''

    task = st.session_state.get('task')
    if not task:
        st.title("Тренажёр")
        st.info("Нажми **Старт** слева, чтобы получить задание.")
        return

    st.title(f"Задание {task.get('task_number')} · ID {task.get('task_id')}")
    top = st.columns([2, 1, 1, 1])
    if top[0].button("Сохранить попытку", use_container_width=True):
        try:
            client.save_session(
                task_id=task.get('task_id'),
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
        st.markdown("### Условие")
        _render_task_html(task)

        st.markdown("### Код ученика")
        code_val = st.text_area(
            "Вставь/пиши решение здесь",
            value=st.session_state.get('code') or "",
            height=260,
            placeholder="print('hello')",
        )
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

        if btns[1].button("Подсказка (заглушка)", use_container_width=True):
            st.session_state['messages'].append({'role': 'assistant', 'content': 'Сначала опиши, какую идею ты используешь и какие данные читаешь. Что будет считаться ответом?'})

        if btns[2].button("Очистить", use_container_width=True):
            st.session_state['code'] = ''
            st.session_state['analysis'] = None
            st.session_state['tests'] = None
            st.session_state['messages'] = []

        # Optional runner (feature-flagged)
        knowledge = load_task_knowledge(int(task.get('task_id') or 0)) if task.get('task_id') else None
        tests = (knowledge or {}).get('tests') if isinstance(knowledge, dict) else None
        if tests and is_runner_enabled():
            st.markdown("### Тесты (опционально)")
            st.caption("Для запуска тестов добавь функцию `solve(s)` и не используй опасные импорты. По умолчанию раннер выключен на сервере.")
            if st.button("Запустить тесты", use_container_width=True):
                analysis = st.session_state.get('analysis') or analyze_python_code(st.session_state.get('code') or '')
                st.session_state['analysis'] = analysis
                dangerous = [i for i in (analysis.get('issues') or []) if (i.get('kind') == 'security')]
                if dangerous:
                    st.session_state['tests'] = {'ok': False, 'error': 'security_block', 'details': 'Есть подозрительные импорты, запуск запрещён.'}
                else:
                    st.session_state['tests'] = run_python_solve_tests(code=st.session_state.get('code') or '', tests=tests)

            if st.session_state.get('tests') is not None:
                st.code(json.dumps(st.session_state['tests'], ensure_ascii=False, indent=2), language="json")

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
            llm = get_llm_client()
            if not llm:
                st.session_state['messages'].append({'role': 'assistant', 'content': 'LLM пока не настроен (нет ключей). Скажи, какую идею ты хочешь реализовать, и я задам уточняющие вопросы.'})
                st.rerun()

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
                answer = llm.chat(messages=msgs, temperature=0.2, max_tokens=700)
                answer = (answer or '').strip() or 'Не смог сформировать ответ. Попробуй переформулировать вопрос.'
                st.session_state['messages'].append({'role': 'assistant', 'content': answer})
            except Exception as e:
                st.session_state['messages'].append({'role': 'assistant', 'content': f'Ошибка обращения к LLM: {e}'})
            st.rerun()


if __name__ == '__main__':
    main()

