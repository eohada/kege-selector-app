from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
from typing import Any


def is_runner_enabled() -> bool:
    return (os.environ.get('TRAINER_ENABLE_RUNNER') or '').strip().lower() in ('1', 'true', 'yes', 'on')


def _env_int(name: str, default: int) -> int:
    v = (os.environ.get(name) or '').strip()
    if not v:
        return int(default)
    try:
        return int(v)
    except Exception:
        return int(default)


def _env_float(name: str, default: float) -> float:
    v = (os.environ.get(name) or '').strip()
    if not v:
        return float(default)
    try:
        return float(v)
    except Exception:
        return float(default)


def _get_allowed_imports() -> list[str]:
    """
    Allowlist of stdlib modules permitted in runner.
    By default it's intentionally small; can be extended via env.
    """
    raw = (os.environ.get('TRAINER_RUNNER_ALLOW_IMPORTS') or '').strip()
    if raw:
        items = [x.strip() for x in raw.replace(';', ',').split(',') if x.strip()]
        # normalize to top-level module names
        out = []
        seen = set()
        for it in items:
            top = it.split('.')[0]
            if top and top not in seen:
                seen.add(top)
                out.append(top)
        return out[:50]
    # safe-ish minimal stdlib set (no filesystem/network/process)
    return ['math', 'itertools', 'collections', 'functools', 'heapq', 'bisect', 'string', 're']


def validate_python_code_for_runner(code: str) -> dict[str, Any]:
    """
    Best-effort sandbox validation (NOT a perfect security boundary).
    Blocks:
    - dunder attribute access (e.g. obj.__class__)
    - dangerous builtins usage (eval/exec/compile/open/__import__/globals/locals/etc.)
    - imports outside allowlist
    """
    import ast

    code = code or ''
    if not code.strip():
        return {'ok': False, 'issues': [{'kind': 'empty', 'message': 'Код пустой.'}]}
    if len(code) > 25000:
        return {'ok': False, 'issues': [{'kind': 'too_large', 'message': 'Код слишком большой для запуска.'}]}

    try:
        tree = ast.parse(code, filename='<student_code>')
    except SyntaxError as e:
        return {'ok': False, 'issues': [{'kind': 'syntax', 'message': f'Синтаксическая ошибка: {e.msg}', 'line': e.lineno}]}
    except Exception as e:
        return {'ok': False, 'issues': [{'kind': 'syntax', 'message': f'Ошибка разбора: {e}'}]}

    allowed = set(_get_allowed_imports())
    issues: list[dict[str, Any]] = []

    banned_names = {
        '__import__', 'eval', 'exec', 'compile', 'open', 'input',  # input allowed only for program-run; blocked here
        'globals', 'locals', 'vars', 'dir',
        'getattr', 'setattr', 'delattr',
        'help', 'breakpoint',
    }

    class V(ast.NodeVisitor):
        def visit_Import(self, node: ast.Import):
            for a in node.names:
                top = (a.name or '').split('.')[0]
                if top and top not in allowed:
                    issues.append({'kind': 'security', 'message': f'Импорт "{top}" запрещён в раннере.', 'line': getattr(node, 'lineno', None)})
            self.generic_visit(node)

        def visit_ImportFrom(self, node: ast.ImportFrom):
            mod = (node.module or '').split('.')[0] if node.module else ''
            if mod and mod not in allowed:
                issues.append({'kind': 'security', 'message': f'Импорт "{mod}" запрещён в раннере.', 'line': getattr(node, 'lineno', None)})
            self.generic_visit(node)

        def visit_Attribute(self, node: ast.Attribute):
            if isinstance(node.attr, str) and node.attr.startswith('__'):
                issues.append({'kind': 'security', 'message': 'Доступ к dunder-атрибутам запрещён в раннере.', 'line': getattr(node, 'lineno', None)})
            self.generic_visit(node)

        def visit_Name(self, node: ast.Name):
            if isinstance(node.id, str) and node.id.startswith('__'):
                issues.append({'kind': 'security', 'message': 'Использование dunder-имён запрещено в раннере.', 'line': getattr(node, 'lineno', None)})
            if node.id in banned_names:
                issues.append({'kind': 'security', 'message': f'Использование "{node.id}" запрещено в раннере.', 'line': getattr(node, 'lineno', None)})
            self.generic_visit(node)

        def visit_Call(self, node: ast.Call):
            # block calling dangerous names even via alias
            fn = node.func
            name = None
            if isinstance(fn, ast.Name):
                name = fn.id
            elif isinstance(fn, ast.Attribute):
                name = fn.attr
            if name in banned_names:
                issues.append({'kind': 'security', 'message': f'Вызов "{name}" запрещён в раннере.', 'line': getattr(node, 'lineno', None)})
            self.generic_visit(node)

    V().visit(tree)
    return {'ok': len(issues) == 0, 'issues': issues, 'allowed_imports': sorted(list(allowed))}


def run_python_solve_tests(*, code: str, tests: list[dict[str, Any]], timeout_seconds: float = 2.0) -> dict[str, Any]:
    """
    Very restricted runner (MVP, feature-flagged):
    - Requires student code defines solve(s) function.
    - Executes in subprocess with timeout.
    - Returns JSON dict with per-test results.
    """
    code = code or ''
    tests = tests or []

    # security gate
    v = validate_python_code_for_runner(code)
    if not v.get('ok'):
        return {'ok': False, 'error': 'security_block', 'details': 'Код содержит запрещённые конструкции.', 'validation': v}

    code_b64 = base64.b64encode(code.encode('utf-8')).decode('ascii')
    tests_json = json.dumps(tests, ensure_ascii=False)
    allow_imports = _get_allowed_imports()
    out_limit = _env_int('TRAINER_RUNNER_MAX_OUTPUT_CHARS', 12000)

    child = r"""
import base64, json, sys, traceback

ALLOWED_IMPORTS = set(json.loads(sys.argv[2] or "[]"))
OUT_LIMIT = int(sys.argv[3] or "12000")

def _safe_import(name, globals=None, locals=None, fromlist=(), level=0):
    top = (name or "").split(".")[0]
    if top and top in ALLOWED_IMPORTS:
        return __import__(name, globals, locals, fromlist, level)
    raise ImportError(f"Import blocked: {top}")

class _CappedIO:
    def __init__(self, limit: int):
        self.limit = int(limit)
        self.buf = []
        self.n = 0
    def write(self, s):
        s = "" if s is None else str(s)
        if not s:
            return 0
        left = self.limit - self.n
        if left <= 0:
            raise RuntimeError("output_limit_exceeded")
        chunk = s[:left]
        self.buf.append(chunk)
        self.n += len(chunk)
        if len(s) > left:
            raise RuntimeError("output_limit_exceeded")
        return len(chunk)
    def flush(self):  # pragma: no cover
        return
    def getvalue(self):
        return "".join(self.buf)

try:
    import resource  # type: ignore
    # CPU seconds
    resource.setrlimit(resource.RLIMIT_CPU, (3, 3))
    # 512MB address space
    resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
    # 1MB output files
    resource.setrlimit(resource.RLIMIT_FSIZE, (1 * 1024 * 1024, 1 * 1024 * 1024))
    # limit open files
    resource.setrlimit(resource.RLIMIT_NOFILE, (32, 32))
except Exception:
    pass

code = base64.b64decode(sys.argv[1].encode('ascii')).decode('utf-8', errors='replace')
tests = json.loads(sys.stdin.read() or '[]')

ns = {}
try:
    safe_builtins = {
        # basic types / helpers
        "abs": abs, "all": all, "any": any, "bool": bool, "chr": chr, "divmod": divmod,
        "enumerate": enumerate, "float": float, "int": int, "len": len, "list": list, "map": map,
        "max": max, "min": min, "pow": pow, "range": range, "str": str, "sum": sum, "zip": zip,
        "sorted": sorted, "reversed": reversed,
        # exceptions
        "Exception": Exception, "ValueError": ValueError, "TypeError": TypeError, "RuntimeError": RuntimeError,
        "IndexError": IndexError, "KeyError": KeyError, "ZeroDivisionError": ZeroDivisionError,
        # controlled import
        "__import__": _safe_import,
    }
    ns["__builtins__"] = safe_builtins
    # cap output
    _out = _CappedIO(OUT_LIMIT)
    _err = _CappedIO(OUT_LIMIT)
    sys.stdout = _out
    sys.stderr = _err
    exec(code, ns, ns)
except Exception as e:
    sys.stdout = sys.__stdout__
    sys.stderr = sys.__stderr__
    print(json.dumps({'ok': False, 'error': 'exec_error', 'details': traceback.format_exc()}))
    sys.exit(0)

solve = ns.get('solve')
if not callable(solve):
    sys.stdout = sys.__stdout__
    sys.stderr = sys.__stderr__
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

sys.stdout = sys.__stdout__
sys.stderr = sys.__stderr__
print(json.dumps({'ok': True, 'results': out}, ensure_ascii=False))
"""

    try:
        p = subprocess.run(
            [sys.executable, '-I', '-S', '-c', child, code_b64, json.dumps(allow_imports, ensure_ascii=False), str(out_limit)],
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


def run_python_program(*, code: str, stdin: str = '', timeout_seconds: float = 2.0) -> dict[str, Any]:
    """
    Run student's code as a program with stdin/stdout (best-effort sandbox).
    Intended for "run & check output" UX.
    """
    code = code or ''
    stdin = stdin or ''

    if len(stdin) > 20000:
        stdin = stdin[:20000]

    # Less strict than solve-tests: allow input() here, but still block dangerous stuff
    # We'll reuse validator but allow "input" by removing it from banned list via env toggle.
    # Simpler: temporarily accept input() by not AST-blocking it — so validator above currently blocks input().
    # For program-run, allow input() calls by skipping validation's input ban:
    v = validate_python_code_for_runner(code)
    if not v.get('ok'):
        # If only the "input" ban is triggered, allow program-run.
        issues = v.get('issues') or []
        non_input = [i for i in issues if 'input' not in str(i.get('message') or '')]
        if non_input:
            return {'ok': False, 'error': 'security_block', 'details': 'Код содержит запрещённые конструкции.', 'validation': v}

    code_b64 = base64.b64encode(code.encode('utf-8')).decode('ascii')
    allow_imports = _get_allowed_imports()
    out_limit = _env_int('TRAINER_RUNNER_MAX_OUTPUT_CHARS', 12000)

    child = r"""
import base64, json, sys, traceback

ALLOWED_IMPORTS = set(json.loads(sys.argv[2] or "[]"))
OUT_LIMIT = int(sys.argv[3] or "12000")

def _safe_import(name, globals=None, locals=None, fromlist=(), level=0):
    top = (name or "").split(".")[0]
    if top and top in ALLOWED_IMPORTS:
        return __import__(name, globals, locals, fromlist, level)
    raise ImportError(f"Import blocked: {top}")

class _CappedIO:
    def __init__(self, limit: int):
        self.limit = int(limit)
        self.buf = []
        self.n = 0
    def write(self, s):
        s = "" if s is None else str(s)
        if not s:
            return 0
        left = self.limit - self.n
        if left <= 0:
            raise RuntimeError("output_limit_exceeded")
        chunk = s[:left]
        self.buf.append(chunk)
        self.n += len(chunk)
        if len(s) > left:
            raise RuntimeError("output_limit_exceeded")
        return len(chunk)
    def flush(self):  # pragma: no cover
        return
    def getvalue(self):
        return "".join(self.buf)

try:
    import resource  # type: ignore
    resource.setrlimit(resource.RLIMIT_CPU, (3, 3))
    resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_FSIZE, (1 * 1024 * 1024, 1 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_NOFILE, (32, 32))
except Exception:
    pass

code = base64.b64decode(sys.argv[1].encode('ascii')).decode('utf-8', errors='replace')

ns = {}
out = _CappedIO(OUT_LIMIT)
err = _CappedIO(OUT_LIMIT)
sys.stdout = out
sys.stderr = err
try:
    safe_builtins = {
        "abs": abs, "all": all, "any": any, "bool": bool, "chr": chr, "divmod": divmod,
        "enumerate": enumerate, "float": float, "int": int, "len": len, "list": list, "map": map,
        "max": max, "min": min, "pow": pow, "range": range, "str": str, "sum": sum, "zip": zip,
        "sorted": sorted, "reversed": reversed,
        "print": print, "input": input,
        "Exception": Exception, "ValueError": ValueError, "TypeError": TypeError, "RuntimeError": RuntimeError,
        "IndexError": IndexError, "KeyError": KeyError, "ZeroDivisionError": ZeroDivisionError,
        "__import__": _safe_import,
    }
    ns["__builtins__"] = safe_builtins
    exec(code, ns, ns)
    ok = True
    details = None
except Exception:
    ok = False
    details = traceback.format_exc()

sys.stdout = sys.__stdout__
sys.stderr = sys.__stderr__

print(json.dumps({
    "ok": ok,
    "stdout": out.getvalue(),
    "stderr": err.getvalue(),
    "error": None if ok else "exec_error",
    "details": details,
}, ensure_ascii=False))
"""

    try:
        p = subprocess.run(
            [sys.executable, '-I', '-S', '-c', child, code_b64, json.dumps(allow_imports, ensure_ascii=False), str(out_limit)],
            input=stdin,
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
        return {'ok': False, 'error': 'no_output', 'details': (p.stderr or '').strip()[:2000]}
    try:
        return json.loads(raw)
    except Exception:
        return {'ok': False, 'error': 'bad_output', 'details': raw[:2000], 'stderr': (p.stderr or '').strip()[:2000]}

