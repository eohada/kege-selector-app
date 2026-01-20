from __future__ import annotations

import json
import os
from typing import Any


def _repo_root() -> str:
    # trainer_app/knowledge.py -> repo root
    return os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))


def load_task_knowledge(task_id: int) -> dict[str, Any] | None:
    try:
        task_id_int = int(task_id)
    except Exception:
        return None

    path = os.path.join(_repo_root(), 'trainer_knowledge', 'tasks', f'{task_id_int}.json')
    if not os.path.exists(path):
        return None
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except Exception:
        return None

