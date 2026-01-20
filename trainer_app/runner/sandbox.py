from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
from typing import Any


def is_runner_enabled() -> bool:
    return (os.environ.get('TRAINER_ENABLE_RUNNER') or '').strip().lower() in ('1', 'true', 'yes', 'on')


def run_python_solve_tests(*, code: str, tests: list[dict[str, Any]], timeout_seconds: float = 2.0) -> dict[str, Any]:
    """
    Very restricted runner (MVP, feature-flagged):
    - Requires student code defines solve(s) function.
    - Executes in subprocess with timeout.
    - Returns JSON dict with per-test results.
    """
    code = code or ''
    tests = tests or []

    code_b64 = base64.b64encode(code.encode('utf-8')).decode('ascii')
    tests_json = json.dumps(tests, ensure_ascii=False)

    child = r"""
import base64, json, sys, traceback

code = base64.b64decode(sys.argv[1].encode('ascii')).decode('utf-8', errors='replace')
tests = json.loads(sys.stdin.read() or '[]')

ns = {}
try:
    exec(code, ns, ns)
except Exception as e:
    print(json.dumps({'ok': False, 'error': 'exec_error', 'details': traceback.format_exc()}))
    sys.exit(0)

solve = ns.get('solve')
if not callable(solve):
    print(json.dumps({'ok': False, 'error': 'no_solve', 'details': 'Define solve(s) function for tests.'}))
    sys.exit(0)

out = []
for t in tests:
    name = (t.get('name') or '')
    inp = t.get('input')
    exp = t.get('expected')
    try:
        res = solve(inp)
        got = '' if res is None else str(res)
        out.append({'name': name, 'expected': '' if exp is None else str(exp), 'got': got, 'ok': ('' if exp is None else str(exp)) == got})
    except Exception:
        out.append({'name': name, 'expected': '' if exp is None else str(exp), 'got': None, 'ok': False, 'error': traceback.format_exc()})

print(json.dumps({'ok': True, 'results': out}, ensure_ascii=False))
"""

    try:
        p = subprocess.run(
            [sys.executable, '-I', '-c', child, code_b64],
            input=tests_json,
            text=True,
            capture_output=True,
            timeout=float(timeout_seconds),
        )
    except subprocess.TimeoutExpired:
        return {'ok': False, 'error': 'timeout', 'details': f'Timeout > {timeout_seconds}s'}
    except Exception as e:
        return {'ok': False, 'error': 'runner_error', 'details': str(e)}

    raw = (p.stdout or '').strip()
    if not raw:
        return {'ok': False, 'error': 'no_output', 'details': (p.stderr or '').strip()}
    try:
        return json.loads(raw)
    except Exception:
        return {'ok': False, 'error': 'bad_output', 'details': raw[:2000], 'stderr': (p.stderr or '').strip()[:2000]}

