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

    def get_task_stats(self) -> dict[str, Any]:
        r = requests.get(f'{self.base_url}/internal/trainer/task/stats', headers=self._headers(), timeout=self.timeout_seconds)
        r.raise_for_status()
        return r.json()

    def stream_start(
        self,
        task_type: int,
        assignment_type: str = 'homework',
        *,
        exclude_task_ids: list[int] | None = None,
        task_id: int | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {'task_type': int(task_type), 'assignment_type': assignment_type}
        if exclude_task_ids:
            payload['exclude_task_ids'] = [int(x) for x in exclude_task_ids[:200]]
        if task_id is not None:
            payload['task_id'] = int(task_id)
        r = requests.post(f'{self.base_url}/internal/trainer/task/stream/start', json=payload, headers=self._headers(), timeout=self.timeout_seconds)
        r.raise_for_status()
        return r.json()

    def stream_next(self, task_type: int, *, exclude_task_ids: list[int] | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {'action': 'next', 'task_type': int(task_type)}
        if exclude_task_ids:
            payload['exclude_task_ids'] = [int(x) for x in exclude_task_ids[:200]]
        r = requests.post(f'{self.base_url}/internal/trainer/task/stream/act', json=payload, headers=self._headers(), timeout=self.timeout_seconds)
        r.raise_for_status()
        return r.json()

    def save_session(self, *, task_id: int | None, task_type: int | None, language: str, code: str, analysis: Any = None, tests: Any = None, messages: Any = None) -> dict[str, Any]:
        payload = {
            'task_id': task_id,
            'task_type': task_type,
            'language': language,
            'code': code,
            'analysis': analysis,
            'tests': tests,
            'messages': messages,
        }
        r = requests.post(f'{self.base_url}/internal/trainer/session/save', json=payload, headers=self._headers(), timeout=self.timeout_seconds)
        r.raise_for_status()
        return r.json()

    def list_sessions(self, *, limit: int = 25) -> dict[str, Any]:
        r = requests.get(f'{self.base_url}/internal/trainer/session/list', params={'limit': int(limit)}, headers=self._headers(), timeout=self.timeout_seconds)
        r.raise_for_status()
        return r.json()

    def get_session(self, session_id: int) -> dict[str, Any]:
        r = requests.get(f'{self.base_url}/internal/trainer/session/{int(session_id)}', headers=self._headers(), timeout=self.timeout_seconds)
        r.raise_for_status()
        return r.json()


def get_platform_base_url() -> str:
    v = (os.environ.get('PLATFORM_BASE_URL') or os.environ.get('TRAINER_PLATFORM_URL') or '').strip()
    if not v:
        return ''
    return v.rstrip('/')

