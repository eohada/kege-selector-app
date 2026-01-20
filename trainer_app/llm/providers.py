from __future__ import annotations

import os
import re
from typing import Any, Literal

import requests


ProviderName = Literal['groq', 'gemini']


def _strip_html(s: str) -> str:
    s = (s or '').strip()
    if not s:
        return ''
    # Very lightweight HTML stripping (no external deps)
    s = re.sub(r'<script[\s\S]*?</script>', ' ', s, flags=re.IGNORECASE)
    s = re.sub(r'<style[\s\S]*?</style>', ' ', s, flags=re.IGNORECASE)
    s = re.sub(r'<[^>]+>', ' ', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s


class LlmClient:
    provider: ProviderName

    def chat(self, *, messages: list[dict[str, str]], temperature: float = 0.2, max_tokens: int = 800) -> str:
        raise NotImplementedError


class GroqClient(LlmClient):
    provider: ProviderName = 'groq'

    def __init__(self, api_key: str, model: str = 'llama-3.1-70b-versatile', base_url: str = 'https://api.groq.com/openai/v1'):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip('/')

    def chat(self, *, messages: list[dict[str, str]], temperature: float = 0.2, max_tokens: int = 800) -> str:
        payload = {
            'model': self.model,
            'messages': messages,
            'temperature': float(temperature),
            'max_tokens': int(max_tokens),
        }
        r = requests.post(
            f'{self.base_url}/chat/completions',
            json=payload,
            headers={'Authorization': f'Bearer {self.api_key}'},
            timeout=30,
        )
        r.raise_for_status()
        data = r.json()
        try:
            return (data.get('choices') or [{}])[0].get('message', {}).get('content', '') or ''
        except Exception:
            return ''


class GeminiClient(LlmClient):
    provider: ProviderName = 'gemini'

    def __init__(self, api_key: str, model: str = 'gemini-1.5-flash'):
        self.api_key = api_key
        self.model = model

    def chat(self, *, messages: list[dict[str, str]], temperature: float = 0.2, max_tokens: int = 800) -> str:
        # Convert OpenAI-like messages -> Gemini contents
        contents = []
        for m in messages:
            role = (m.get('role') or 'user').strip().lower()
            txt = m.get('content') or ''
            if not txt:
                continue
            gem_role = 'user' if role in ('user', 'system') else 'model'
            contents.append({'role': gem_role, 'parts': [{'text': txt}]})

        body: dict[str, Any] = {
            'contents': contents,
            'generationConfig': {
                'temperature': float(temperature),
                'maxOutputTokens': int(max_tokens),
            },
        }
        url = f'https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?key={self.api_key}'
        r = requests.post(url, json=body, timeout=30)
        r.raise_for_status()
        data = r.json()
        try:
            cand = (data.get('candidates') or [{}])[0]
            parts = cand.get('content', {}).get('parts') or []
            return ''.join([p.get('text') or '' for p in parts]).strip()
        except Exception:
            return ''


def get_llm_client() -> LlmClient | None:
    provider = (os.environ.get('TRAINER_LLM_PROVIDER') or '').strip().lower()

    groq_key = (os.environ.get('GROQ_API_KEY') or '').strip()
    gemini_key = (os.environ.get('GEMINI_API_KEY') or os.environ.get('GOOGLE_AI_STUDIO_API_KEY') or '').strip()

    if provider == 'gemini' and gemini_key:
        model = (os.environ.get('GEMINI_MODEL') or 'gemini-1.5-flash').strip()
        return GeminiClient(api_key=gemini_key, model=model)
    if provider == 'groq' and groq_key:
        model = (os.environ.get('GROQ_MODEL') or 'llama-3.1-70b-versatile').strip()
        return GroqClient(api_key=groq_key, model=model)

    # Auto pick
    if groq_key:
        model = (os.environ.get('GROQ_MODEL') or 'llama-3.1-70b-versatile').strip()
        return GroqClient(api_key=groq_key, model=model)
    if gemini_key:
        model = (os.environ.get('GEMINI_MODEL') or 'gemini-1.5-flash').strip()
        return GeminiClient(api_key=gemini_key, model=model)

    return None


def build_messages_for_help(*, task: dict[str, Any], code: str, analysis: dict[str, Any] | None, history: list[dict[str, str]], knowledge: dict[str, Any] | None = None) -> list[dict[str, str]]:
    sys_prompt = (os.environ.get('TRAINER_SYSTEM_PROMPT') or '').strip()
    if not sys_prompt:
        sys_prompt = (
            "Ты репетитор. Твоя цель — научить ученика решать задачу. "
            "Не давай готовое решение целиком. Веди диалог через наводящие вопросы, проверку гипотез и короткие подсказки. "
            "Если ученик ошибся — объясни правило и попроси исправить. "
            "Будь дружелюбным и конкретным."
        )

    task_text = _strip_html(task.get('content_html') or '')
    task_id = task.get('task_id')
    task_num = task.get('task_number')

    code_txt = (code or '').strip()
    if len(code_txt) > 8000:
        code_txt = code_txt[:8000] + "\n# ... (truncated) ..."

    ctx = [
        {'role': 'system', 'content': sys_prompt},
        {'role': 'system', 'content': f'Контекст задачи: task_number={task_num}, task_id={task_id}.'},
        {'role': 'system', 'content': f'Условие: {task_text}'},
        {'role': 'system', 'content': f'Код ученика:\n```python\n{code_txt}\n```'},
    ]
    if analysis:
        ctx.append({'role': 'system', 'content': f'Статический анализ: {analysis}'})
    if knowledge:
        # Важно: reference_solution существует для ориентирования, но не должен быть выдан ученику целиком.
        ctx.append({'role': 'system', 'content': f"Примеры/знания по задаче: common_mistakes={knowledge.get('common_mistakes')}, hint_ladder={knowledge.get('hint_ladder')}."})

    # Keep last 12 messages max
    trimmed = [m for m in (history or []) if (m.get('role') or '').strip().lower() in ('user', 'assistant')][-12:]
    msgs = ctx + [{'role': m.get('role') or 'user', 'content': m.get('content') or ''} for m in trimmed if (m.get('content') or '').strip()]
    return msgs

