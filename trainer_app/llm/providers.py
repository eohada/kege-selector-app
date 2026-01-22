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


def _env_float(name: str, default: float) -> float:
    v = (os.environ.get(name) or '').strip()
    if not v:
        return float(default)
    try:
        return float(v)
    except Exception:
        return float(default)


def _request_with_retries(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    json_body: Any | None = None,
    timeout: float = 30.0,
    max_attempts: int = 3,
) -> requests.Response:
    """
    Best-effort retry for transient errors (429/5xx, network issues).
    No external deps; uses a simple incremental backoff.
    """
    last_exc: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            r = requests.request(method, url, headers=headers, json=json_body, timeout=timeout)
            if r.status_code in (429, 500, 502, 503, 504) and attempt < max_attempts:
                try:
                    import time
                    time.sleep(0.6 * attempt)
                except Exception:
                    pass
                continue
            return r
        except Exception as e:
            last_exc = e
            if attempt < max_attempts:
                try:
                    import time
                    time.sleep(0.6 * attempt)
                except Exception:
                    pass
                continue
            raise
    if last_exc:
        raise last_exc
    raise RuntimeError("request_failed")


class GroqClient(LlmClient):
    provider: ProviderName = 'groq'

    def __init__(self, api_key: str, model: str = 'llama-3.3-70b-versatile', base_url: str = 'https://api.groq.com/openai/v1'):
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
        timeout = _env_float('TRAINER_LLM_TIMEOUT_SECONDS', 30.0)
        r = _request_with_retries(
            'POST',
            f'{self.base_url}/chat/completions',
            json_body=payload,
            headers={
                'Authorization': f'Bearer {self.api_key}',
                'Content-Type': 'application/json',
            },
            timeout=timeout,
            max_attempts=int(os.environ.get('TRAINER_LLM_MAX_ATTEMPTS') or 3),
        )
        if r.status_code >= 400:
            # surface a compact error for UI
            try:
                data = r.json()
                msg = (data.get('error') or {}).get('message') or data.get('message') or r.text
            except Exception:
                msg = r.text
            raise RuntimeError(f'groq_error {r.status_code}: {str(msg)[:500]}')
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
        # Convert OpenAI-like messages -> Gemini contents (+ systemInstruction)
        sys_parts: list[str] = []
        contents = []
        for m in messages:
            role = (m.get('role') or 'user').strip().lower()
            txt = m.get('content') or ''
            if not txt:
                continue
            if role == 'system':
                sys_parts.append(txt)
                continue
            gem_role = 'user' if role == 'user' else 'model'
            contents.append({'role': gem_role, 'parts': [{'text': txt}]})

        body: dict[str, Any] = {
            'contents': contents,
            'generationConfig': {
                'temperature': float(temperature),
                'maxOutputTokens': int(max_tokens),
            },
        }
        if sys_parts:
            body['systemInstruction'] = {'parts': [{'text': '\n\n'.join(sys_parts)}]}
        url = f'https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?key={self.api_key}'
        timeout = _env_float('TRAINER_LLM_TIMEOUT_SECONDS', 30.0)
        r = _request_with_retries(
            'POST',
            url,
            json_body=body,
            headers={'Content-Type': 'application/json'},
            timeout=timeout,
            max_attempts=int(os.environ.get('TRAINER_LLM_MAX_ATTEMPTS') or 3),
        )
        if r.status_code >= 400:
            raise RuntimeError(f'gemini_error {r.status_code}: {r.text[:500]}')
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
        model = (os.environ.get('GROQ_MODEL') or 'llama-3.3-70b-versatile').strip()
        return GroqClient(api_key=groq_key, model=model)

    # Auto pick
    if groq_key:
        model = (os.environ.get('GROQ_MODEL') or 'llama-3.3-70b-versatile').strip()
        return GroqClient(api_key=groq_key, model=model)
    if gemini_key:
        model = (os.environ.get('GEMINI_MODEL') or 'gemini-1.5-flash').strip()
        return GeminiClient(api_key=gemini_key, model=model)

    return None


def get_llm_info() -> dict[str, Any]:
    """
    For UI/diagnostics only (do not return keys).
    """
    provider = (os.environ.get('TRAINER_LLM_PROVIDER') or '').strip().lower()
    groq_key = (os.environ.get('GROQ_API_KEY') or '').strip()
    gemini_key = (os.environ.get('GEMINI_API_KEY') or os.environ.get('GOOGLE_AI_STUDIO_API_KEY') or '').strip()

    picked = None
    if provider == 'groq' and groq_key:
        picked = {'provider': 'groq', 'model': (os.environ.get('GROQ_MODEL') or 'llama-3.3-70b-versatile').strip()}
    elif provider == 'gemini' and gemini_key:
        picked = {'provider': 'gemini', 'model': (os.environ.get('GEMINI_MODEL') or 'gemini-1.5-flash').strip()}
    else:
        if groq_key:
            picked = {'provider': 'groq', 'model': (os.environ.get('GROQ_MODEL') or 'llama-3.3-70b-versatile').strip()}
        elif gemini_key:
            picked = {'provider': 'gemini', 'model': (os.environ.get('GEMINI_MODEL') or 'gemini-1.5-flash').strip()}

    return {
        'configured': bool(picked),
        'picked': picked,
        'timeout_seconds': _env_float('TRAINER_LLM_TIMEOUT_SECONDS', 30.0),
        'max_attempts': int(os.environ.get('TRAINER_LLM_MAX_ATTEMPTS') or 3),
    }


def build_messages_for_help(*, task: dict[str, Any], code: str, analysis: dict[str, Any] | None, history: list[dict[str, str]], knowledge: dict[str, Any] | None = None) -> list[dict[str, str]]:
    sys_prompt = (os.environ.get('TRAINER_SYSTEM_PROMPT') or '').strip()
    if not sys_prompt:
        sys_prompt = (
            "Ты репетитор. Твоя цель — научить ученика решать задачу. "
            "Не давай готовое решение целиком. Веди диалог через наводящие вопросы, проверку гипотез и короткие подсказки. "
            "Если ученик ошибся — объясни правило и попроси исправить. "
            "Будь дружелюбным и конкретным.\n\n"
            "ФОРМАТ ОТВЕТА (всегда):\n"
            "1) Вопрос ученику (1-2 предложения)\n"
            "2) Подсказка (коротко, без полного решения)\n"
            "3) Проверка понимания (что нужно проверить/какой мини-тест сделать)\n\n"
            "ОГРАНИЧЕНИЯ:\n"
            "- НЕЛЬЗЯ выдавать полностью готовое решение.\n"
            "- НЕЛЬЗЯ давать длинный код (если очень нужно — максимум 8 строк псевдокода/наброска).\n"
            "- Можно ссылаться на типовые ошибки и hint_ladder, но reference_solution использовать только как внутренний ориентир."
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
        if knowledge.get('reference_solution'):
            ctx.append({'role': 'system', 'content': "reference_solution присутствует, но его НЕЛЬЗЯ выдавать ученику целиком. Используй только для понимания правильной идеи."})

    # Keep last 12 messages max
    trimmed = [m for m in (history or []) if (m.get('role') or '').strip().lower() in ('user', 'assistant')][-12:]
    msgs = ctx + [{'role': m.get('role') or 'user', 'content': m.get('content') or ''} for m in trimmed if (m.get('content') or '').strip()]
    return msgs

