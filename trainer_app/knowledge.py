from __future__ import annotations

import json
import os
from typing import Any
import logging

logger = logging.getLogger(__name__)


def _repo_root() -> str:
    # trainer_app/knowledge.py -> repo root
    return os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))


def _validate_task_knowledge(data: dict[str, Any]) -> tuple[bool, list[str]]:
    """
    Validate knowledge JSON format.

    Returns: (ok, errors)
    """
    errs: list[str] = []

    def _req_int(key: str):
        v = data.get(key)
        try:
            int(v)
        except Exception:
            errs.append(f'{key} must be int')

    def _opt_str(key: str, *, max_len: int = 20000):
        v = data.get(key)
        if v is None:
            return
        if not isinstance(v, str):
            errs.append(f'{key} must be string')
            return
        if len(v) > max_len:
            errs.append(f'{key} too long (>{max_len})')

    _req_int('task_id')
    _req_int('task_number')
    _opt_str('language', max_len=40)
    _opt_str('title', max_len=400)
    _opt_str('reference_solution', max_len=25000)

    cm = data.get('common_mistakes')
    if cm is not None:
        if not isinstance(cm, list) or any((not isinstance(x, str)) for x in cm):
            errs.append('common_mistakes must be list[str]')
        elif len(cm) > 80:
            errs.append('common_mistakes too long (max 80)')

    ladder = data.get('hint_ladder')
    if ladder is not None:
        if not isinstance(ladder, list):
            errs.append('hint_ladder must be list')
        else:
            if len(ladder) > 20:
                errs.append('hint_ladder too long (max 20)')
            for i, it in enumerate(ladder):
                if not isinstance(it, dict):
                    errs.append(f'hint_ladder[{i}] must be object')
                    continue
                if 'hint' not in it or not isinstance(it.get('hint'), str) or not it.get('hint'):
                    errs.append(f'hint_ladder[{i}].hint must be non-empty string')
                if len(str(it.get('hint') or '')) > 1500:
                    errs.append(f'hint_ladder[{i}].hint too long (max 1500)')
                if 'level' in it:
                    try:
                        int(it.get('level'))
                    except Exception:
                        errs.append(f'hint_ladder[{i}].level must be int')

    tests = data.get('tests')
    if tests is not None:
        if not isinstance(tests, list):
            errs.append('tests must be list')
        else:
            if len(tests) > 80:
                errs.append('tests too long (max 80)')
            for i, t in enumerate(tests):
                if not isinstance(t, dict):
                    errs.append(f'tests[{i}] must be object')
                    continue
                for k in ('name', 'input', 'expected'):
                    if k not in t:
                        errs.append(f'tests[{i}].{k} is required')
                if 'name' in t and not isinstance(t.get('name'), str):
                    errs.append(f'tests[{i}].name must be string')

    return (len(errs) == 0), errs


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
        if not isinstance(data, dict):
            return None
        ok, errs = _validate_task_knowledge(data)
        if not ok:
            logger.warning(f'Invalid trainer knowledge file {path}: {errs}')
            # Strict mode: fail fast
            strict = (os.environ.get('TRAINER_STRICT_KNOWLEDGE') or '').strip().lower() in ('1', 'true', 'yes', 'on')
            if strict:
                return None
        return data
    except Exception:
        return None

