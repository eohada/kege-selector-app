from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import requests


@dataclass
class PlatformClient:
    base_url: str
    token: str
    timeout_seconds: float = 15.0

    def _headers(self) -> dict[str, str]:
        return {
            'X-Trainer-Token': self.token,
            'Content-Type': 'application/json',
        }

    def get_me(self) -> dict[str, Any]:
        r = requests.get(f'{self.base_url}/internal/trainer/me', headers=self._headers(), timeout=self.timeout_seconds)
        r.raise_for_status()
        return r.json()

    def get_task(self, task_id: int) -> dict[str, Any]:
        r = requests.get(f'{self.base_url}/internal/trainer/task/{int(task_id)}', headers=self._headers(), timeout=self.timeout_seconds)
        r.raise_for_status()
        return r.json()

    def stream_start(self, task_type: int, assignment_type: str = 'homework') -> dict[str, Any]:
        payload = {'task_type': int(task_type), 'assignment_type': assignment_type}
        r = requests.post(f'{self.base_url}/internal/trainer/task/stream/start', json=payload, headers=self._headers(), timeout=self.timeout_seconds)
        r.raise_for_status()
        return r.json()

    def stream_next(self, task_type: int) -> dict[str, Any]:
        payload = {'action': 'next', 'task_type': int(task_type)}
        r = requests.post(f'{self.base_url}/internal/trainer/task/stream/act', json=payload, headers=self._headers(), timeout=self.timeout_seconds)
        r.raise_for_status()
        return r.json()

    def save_session(self, *, task_id: int | None, language: str, code: str, analysis: Any = None, tests: Any = None, messages: Any = None) -> dict[str, Any]:
        payload = {
            'task_id': task_id,
            'language': language,
            'code': code,
            'analysis': analysis,
            'tests': tests,
            'messages': messages,
        }
        r = requests.post(f'{self.base_url}/internal/trainer/session/save', json=payload, headers=self._headers(), timeout=self.timeout_seconds)
        r.raise_for_status()
        return r.json()


def get_platform_base_url() -> str:
    v = (os.environ.get('PLATFORM_BASE_URL') or os.environ.get('TRAINER_PLATFORM_URL') or '').strip()
    if not v:
        return ''
    return v.rstrip('/')

