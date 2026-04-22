"""
Песочница Python для запуска кода ученика (ЕГЭ информатика).

Раннер выполняется в отдельном subprocess; файлы задания — в cwd временной директории.
При наличии xvfb-run в PATH запуск оборачивается для поддержки turtle/tkinter.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile

# Строка кода для python -c: читает пользовательский код из stdin.
# Лимиты рекурсии в _SysStub зашиты в раннер (см. setrecursionlimit).
PYTHON_RUNNER = r"""
import sys as _py_sys
import io
import os
import builtins as _builtins

_cwd = os.getcwd()
_real_open = open
_real_sys = _py_sys

def _safe_open(path, mode='r', encoding=None, **kw):
    if any(c in mode for c in 'wax+'):
        raise PermissionError('Запись файлов запрещена в песочнице')
    abs_path = os.path.abspath(path)
    if not abs_path.startswith(_cwd + os.sep) and abs_path != _cwd:
        raise PermissionError('Доступ к файлам за пределами рабочей директории запрещён')
    if not os.path.isfile(abs_path):
        raise FileNotFoundError(f"Файл не найден: {path}")
    if 'b' in mode:
        return _real_open(abs_path, mode, **kw)
    return _real_open(abs_path, mode, encoding=encoding or 'utf-8', **kw)

class _SysStub:
    version = _real_sys.version
    version_info = _real_sys.version_info

    def setrecursionlimit(self, n):
        n = int(n)
        if n > 5000:
            n = 5000
        elif n < 100:
            n = 100
        _real_sys.setrecursionlimit(n)

    def getrecursionlimit(self):
        return _real_sys.getrecursionlimit()

    def __getattr__(self, name):
        raise AttributeError(f"в песочнице недоступно: sys.{name}")

_sys_stub = _SysStub()

import itertools
import math
import ipaddress
import re
import functools
import collections
import heapq
import bisect
import copy
import random
import operator
import string
import decimal
import datetime
import enum
import statistics
import json
import hashlib
import contextlib
import dataclasses
import typing
import collections.abc as collections_abc
import fractions
import textwrap
import abc as abc_mod
import struct
import binascii

try:
    import turtle
except Exception:
    turtle = None
else:
    # В headless/песочнице done()/mainloop() блокируют процесс, ожидая закрытия окна — таймаут.
    def _turtle_noop(*_a, **_k):
        return None
    turtle.done = _turtle_noop
    turtle.mainloop = _turtle_noop
    turtle.exitonclick = _turtle_noop
    for _cls_name in ('TurtleScreen', '_Screen', 'Screen'):
        if hasattr(turtle, _cls_name):
            _c = getattr(turtle, _cls_name)
            if isinstance(_c, type):
                _c.mainloop = lambda self, *_a, **_k: None
    # turtle внутри вызывает tkinter mainloop(0) — вечный цикл, пока «живо» окно; режем здесь.
    try:
        import tkinter as _tki
        _turtle_orig_tk_mloop = _tki.Misc.mainloop
        def _turtle_tk_mloop(self, n=0):
            if n == 0:
                return None
            return _turtle_orig_tk_mloop(self, n)
        _tki.Misc.mainloop = _turtle_tk_mloop
    except Exception:
        pass

_ALLOWED_MODULES = {
    're': re,
    'itertools': itertools,
    'math': math,
    'ipaddress': ipaddress,
    'functools': functools,
    'collections': collections,
    'heapq': heapq,
    'bisect': bisect,
    'copy': copy,
    'random': random,
    'operator': operator,
    'string': string,
    'decimal': decimal,
    'datetime': datetime,
    'enum': enum,
    'statistics': statistics,
    'json': json,
    'hashlib': hashlib,
    'contextlib': contextlib,
    'dataclasses': dataclasses,
    'typing': typing,
    'collections.abc': collections_abc,
    'fractions': fractions,
    'textwrap': textwrap,
    'abc': abc_mod,
    'struct': struct,
    'binascii': binascii,
    'sys': _sys_stub,
    'turtle': turtle,
}

def _safe_import(name, globals=None, locals=None, fromlist=(), level=0):
    if level != 0:
        raise ImportError('Относительные импорты недоступны в песочнице')
    if name not in _ALLOWED_MODULES:
        raise ImportError(
            "Модуль '" + name + "' недоступен в песочнице. Доступны stdlib-модули для ЕГЭ (см. подсказку в редакторе)."
        )
    mod = _ALLOWED_MODULES[name]
    if mod is None:
        raise ImportError(
            "Модуль turtle недоступен: в образе сервера нужны пакеты tk (python3-tk) и xvfb-run."
        )
    return mod

code = _py_sys.stdin.read()
out = io.StringIO()
err = io.StringIO()
_py_sys.stdout = out
_py_sys.stderr = err
try:
    safe_builtins = {
        'print': print, 'len': len, 'range': range, 'list': list, 'dict': dict, 'str': str,
        'int': int, 'float': float, 'sum': sum, 'min': min, 'max': max, 'abs': abs,
        'sorted': sorted, 'map': map, 'filter': filter, 'zip': zip, 'enumerate': enumerate,
        'tuple': tuple, 'set': set, 'frozenset': frozenset, 'bool': bool, 'True': True,
        'False': False, 'None': None, 'round': round, 'repr': repr, 'ascii': ascii,
        'any': any, 'all': all, 'open': _safe_open, 'input': input, '__import__': _safe_import,
        'type': type, 'isinstance': isinstance, 'issubclass': issubclass, 'chr': chr, 'ord': ord,
        'hex': hex, 'bin': bin, 'pow': pow, 'reversed': reversed, 'bytes': bytes, 'bytearray': bytearray,
        'format': format, 'hash': hash, 'id': id, 'object': object, 'slice': slice, 'complex': complex,
        'divmod': divmod, 'callable': callable, 'iter': iter, 'next': next, 'super': super,
        'property': property, 'staticmethod': staticmethod, 'classmethod': classmethod,
        '__build_class__': _builtins.__build_class__,
        'Exception': Exception, 'ValueError': ValueError,
        'TypeError': TypeError, 'KeyError': KeyError, 'IndexError': IndexError,
        'StopIteration': StopIteration, 'FileNotFoundError': FileNotFoundError,
        'ImportError': ImportError, 'ModuleNotFoundError': ModuleNotFoundError,
        'ZeroDivisionError': ZeroDivisionError, 'RuntimeError': RuntimeError,
        'AttributeError': AttributeError, 'OverflowError': OverflowError,
        'RecursionError': RecursionError, 'AssertionError': AssertionError,
        'NameError': NameError, 'UnboundLocalError': UnboundLocalError,
        'SyntaxError': SyntaxError, 'OSError': OSError, 'MemoryError': MemoryError,
        'LookupError': LookupError, 'ArithmeticError': ArithmeticError,
        'FloatingPointError': FloatingPointError, 'UnicodeError': UnicodeError,
        'UnicodeDecodeError': UnicodeDecodeError, 'UnicodeEncodeError': UnicodeEncodeError,
        'NotImplementedError': NotImplementedError, 'BufferError': BufferError,
        'EOFError': EOFError,
    }
    safe = {
        '__builtins__': safe_builtins,
        're': re,
        'itertools': itertools,
        'math': math,
        'ipaddress': ipaddress,
        'functools': functools,
        'collections': collections,
        'heapq': heapq,
        'bisect': bisect,
        'copy': copy,
        'random': random,
        'operator': operator,
        'string': string,
        'decimal': decimal,
        'datetime': datetime,
        'enum': enum,
        'statistics': statistics,
        'json': json,
        'hashlib': hashlib,
        'contextlib': contextlib,
        'dataclasses': dataclasses,
        'typing': typing,
        'fractions': fractions,
        'textwrap': textwrap,
        'abc': abc_mod,
        'struct': struct,
        'binascii': binascii,
        'collections.abc': collections_abc,
        'sys': _sys_stub,
        'os': None,
    }
    if turtle is not None:
        safe['turtle'] = turtle
    exec(code, safe)
except Exception as e:
    err.write(str(e))
_py_sys.stdout = _real_sys.__stdout__
_py_sys.stderr = _real_sys.__stderr__
print(out.getvalue())
print(err.getvalue(), file=_real_sys.__stderr__)
"""


def normalize_leading_tabs_to_spaces(code: str, tab_width: int = 4) -> str:
    """Заменяет ведущие табы на пробелы в каждой строке (как ожидает PyCharm при 4 пробелах)."""
    if not code or '\t' not in code:
        return code
    lines = code.split('\n')
    out: list[str] = []
    for line in lines:
        i = 0
        while i < len(line) and line[i] in ' \t':
            i += 1
        prefix, rest = line[:i], line[i:]
        prefix = prefix.replace('\t', ' ' * tab_width)
        out.append(prefix + rest)
    return '\n'.join(out)


def _sandbox_timeout_seconds(code: str, explicit: int | None) -> int:
    """Turtle + xvfb + tk: первый запуск и отрисовка часто > 5 с."""
    if explicit is not None:
        return explicit
    c = (code or '').lower()
    if 'turtle' in c:
        return 30
    return 5


def run_python_sandbox(
    code: str,
    timeout_sec: int | None = None,
    task_files: list[tuple[str, bytes]] | None = None,
) -> tuple[str, str]:
    """Запуск кода Python в песочнице. task_files — [(filename, bytes), ...]."""
    tsec = _sandbox_timeout_seconds(code, timeout_sec)
    xvfb = shutil.which('xvfb-run')
    cmd: list[str] = [sys.executable, '-c', PYTHON_RUNNER]
    if xvfb:
        cmd = [xvfb, '-a'] + cmd
    try:
        with tempfile.TemporaryDirectory(prefix='boostudy_sandbox_') as tmpdir:
            if task_files:
                for fname, fbytes in task_files:
                    fpath = os.path.join(tmpdir, fname)
                    with open(fpath, 'wb') as f:
                        f.write(fbytes)
            proc = subprocess.run(
                cmd,
                input=code,
                capture_output=True,
                text=True,
                timeout=tsec,
                cwd=tmpdir,
            )
            return proc.stdout or '', proc.stderr or ''
    except subprocess.TimeoutExpired:
        return '', 'Превышено время выполнения (макс. {} с).'.format(tsec)
    except Exception as e:
        return '', str(e)
