"""
Песочница Python для запуска кода ученика (ЕГЭ информатика).

Раннер в subprocess; файлы задания — в cwd. Доступны только: re, itertools, collections,
ipaddress, functools, math, sys (setrecursionlimit/getrecursionlimit), turtle; остальное через __import__ недоступно.
Turtle реализован headless-вектором: запуск кода никогда не открывает системное окно.
"""
from __future__ import annotations

import base64
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
import math as _math
import types as _types

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

import re
import itertools
import collections
import functools
import fnmatch
import ipaddress

class _FakeTurtleModule(_types.SimpleNamespace):
    def __init__(self):
        super().__init__()
        self._lines = []
        self._dots = []
        self._bg = 'white'
        self._default = None
        self.Turtle = self._make_turtle_class()

    def _make_turtle_class(self):
        module = self
        class _FakeTurtle:
            def __init__(self):
                self.x = 0.0
                self.y = 0.0
                self.heading = 0.0
                self.down = True
                self.pen_color = 'black'
                self.pen_width = 2.0

            def _line_to(self, x, y):
                x = float(x)
                y = float(y)
                if self.down:
                    module._lines.append((self.x, self.y, x, y, self.pen_color, self.pen_width))
                self.x, self.y = x, y

            def forward(self, distance):
                rad = _math.radians(self.heading)
                self._line_to(self.x + _math.cos(rad) * float(distance), self.y + _math.sin(rad) * float(distance))
            fd = forward

            def backward(self, distance):
                self.forward(-float(distance))
            bk = backward
            back = backward

            def right(self, angle):
                self.heading -= float(angle)
            rt = right

            def left(self, angle):
                self.heading += float(angle)
            lt = left

            def penup(self):
                self.down = False
            pu = up = penup

            def pendown(self):
                self.down = True
            pd = down = pendown

            def goto(self, x, y=None):
                if y is None:
                    x, y = x
                self._line_to(x, y)
            setpos = setposition = goto

            def setx(self, x):
                self._line_to(x, self.y)

            def sety(self, y):
                self._line_to(self.x, y)

            def home(self):
                self._line_to(0, 0)
                self.heading = 0.0

            def setheading(self, angle):
                self.heading = float(angle)
            seth = setheading

            def position(self):
                return (self.x, self.y)
            pos = position

            def xcor(self):
                return self.x

            def ycor(self):
                return self.y

            def color(self, *args):
                if args:
                    self.pen_color = args[0]
                return (self.pen_color, self.pen_color)

            def pencolor(self, *args):
                if args:
                    self.pen_color = args[0]
                return self.pen_color

            def width(self, value=None):
                if value is not None:
                    self.pen_width = max(1.0, float(value))
                return self.pen_width
            pensize = width

            def speed(self, *_args, **_kwargs):
                return 0

            def dot(self, size=6, color=None):
                module._dots.append((self.x, self.y, float(size), color or self.pen_color))

            def circle(self, radius, extent=None, steps=None):
                radius = float(radius)
                extent = 360.0 if extent is None else float(extent)
                steps = int(steps or max(12, abs(extent) // 12))
                step = extent / max(1, steps)
                for _i in range(max(1, steps)):
                    self.left(step)
                    self.forward(2 * _math.pi * radius * abs(step) / 360.0)

            def hideturtle(self): pass
            def showturtle(self): pass
            def clear(self): module._lines.clear(); module._dots.clear()
            def reset(self): self.clear(); self.home()
        return _FakeTurtle

    def _get_default(self):
        if self._default is None:
            self._default = self.Turtle()
        return self._default

    def __getattr__(self, name):
        if name in {'forward', 'fd', 'backward', 'back', 'bk', 'right', 'rt', 'left', 'lt', 'penup', 'pu', 'up', 'pendown', 'pd', 'down', 'goto', 'setpos', 'setposition', 'setx', 'sety', 'home', 'setheading', 'seth', 'position', 'pos', 'xcor', 'ycor', 'color', 'pencolor', 'width', 'pensize', 'speed', 'dot', 'circle', 'hideturtle', 'showturtle', 'clear', 'reset'}:
            return getattr(self._get_default(), name)
        if name in {'done', 'mainloop', 'exitonclick', 'update'}:
            return lambda *_a, **_k: None
        if name == 'screensize':
            return lambda *_a, **_k: None
        if name == 'bgcolor':
            def _bg(*args):
                if args:
                    self._bg = args[0]
                return self._bg
            return _bg
        raise AttributeError(name)

    def _boostudy_export_svg(self, path):
        items = self._lines or [(0, 0, 1, 1, 'transparent', 1)]
        xs = [p for line in items for p in (line[0], line[2])]
        ys = [p for line in items for p in (line[1], line[3])]
        for x, y, size, _color in self._dots:
            xs.extend([x - size, x + size])
            ys.extend([y - size, y + size])
        pad = 24
        min_x, max_x = min(xs) - pad, max(xs) + pad
        min_y, max_y = min(ys) - pad, max(ys) + pad
        w, h = max(1, max_x - min_x), max(1, max_y - min_y)
        parts = [
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{min_x} {-max_y} {w} {h}" width="{int(w)}" height="{int(h)}">',
            f'<rect x="{min_x}" y="{-max_y}" width="{w}" height="{h}" fill="{self._bg}"/>',
        ]
        for x1, y1, x2, y2, color, width in self._lines:
            parts.append(f'<line x1="{x1}" y1="{-y1}" x2="{x2}" y2="{-y2}" stroke="{color}" stroke-width="{width}" stroke-linecap="round"/>')
        for x, y, size, color in self._dots:
            parts.append(f'<circle cx="{x}" cy="{-y}" r="{size / 2}" fill="{color}"/>')
        parts.append('</svg>')
        with open(path, 'w', encoding='utf-8') as f:
            f.write(''.join(parts))

# В песочнице не импортируем стандартный turtle: его tkinter-окно может кратко
# появиться на машине разработчика и нестабильно ведёт себя внутри web-worker.
# Векторная реализация покрывает допустимый учебный API и экспортируется как SVG.
turtle = _FakeTurtleModule()

_ALLOWED_MODULES = {
    're': re,
    'itertools': itertools,
    'collections': collections,
    'collection': collections,
    'math': _math,
    'fnmatch': fnmatch,
    'ipaddress': ipaddress,
    'functools': functools,
    'sys': _sys_stub,
    'turtle': turtle,
}

def _safe_import(name, globals=None, locals=None, fromlist=(), level=0):
    if level != 0:
        raise ImportError('Относительные импорты недоступны в песочнице')
    if name not in _ALLOWED_MODULES:
        raise ImportError(
            "Модуль '" + name + "' недоступен в песочнице. См. «Доступные библиотеки» в подсказке к редактору кода."
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
        'collections': collections,
        'collection': collections,
        'math': _math,
        'fnmatch': fnmatch,
        'ipaddress': ipaddress,
        'functools': functools,
        'sys': _sys_stub,
        'os': None,
    }
    if turtle is not None:
        safe['turtle'] = turtle
    exec(code, safe)
    if turtle is not None:
        try:
            turtle.update()
            _pss = os.path.join(_cwd, '.boostudy_turtle.ps')
            _scr = turtle.getscreen()
            _cv = _scr.getcanvas()
            _cv.update_idletasks()
            # Центр в turtle — (0,0) по центру холста; рисунок занимает лишь часть. Экспорт «всего квадрата»
            # 0..W даёт огромные поля и ощущение смещения. Экспорт по bbox("all") — только мазня + отступ.
            # Регион: верх-лево (x0,y0), вниз y; width/height в пикселях.
            _bb = _cv.bbox("all")
            if _bb and len(_bb) == 4 and not any(x is None for x in _bb):
                _x0, _y0, _x1, _y1 = (float(t) for t in _bb)
                _pad = 16.0
                _w = int(_x1 - _x0 + 2.0 * _pad)
                _h = int(_y1 - _y0 + 2.0 * _pad)
                if _w < 1:
                    _w = 1
                if _h < 1:
                    _h = 1
                _cv.postscript(
                    file=_pss,
                    colormode="color",
                    x=int(_x0 - _pad),
                    y=int(_y0 - _pad),
                    width=_w,
                    height=_h,
                )
            else:
                _cv.postscript(file=_pss, colormode='color')
        except Exception:
            pass
except Exception as e:
    err.write(f"{type(e).__name__}: {e}")
if turtle is not None and hasattr(turtle, '_boostudy_export_svg'):
    try:
        turtle._boostudy_export_svg(os.path.join(_cwd, '.boostudy_turtle.svg'))
    except Exception:
        pass
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
    """Лимит выполнения кода из редактора в работах (по умолчанию 30 с)."""
    if explicit is not None:
        return explicit
    return 30


# Файл PostScript пишет раннер (tk canvas) в cwd песочницы.
TURTLE_PS_NAME = '.boostudy_turtle.ps'
TURTLE_SVG_NAME = '.boostudy_turtle.svg'
_MAX_TURTLE_PNG = 2_500_000  # ~3.3MB base64

def _postscript_to_png_b64(ps_path: str) -> str | None:
    """PostScript → PNG (нужен ghostscript: gs) или ImageMagick: convert."""
    if not os.path.isfile(ps_path) or os.path.getsize(ps_path) < 8:
        return None
    gs = shutil.which('gs')
    if gs:
        out_png: str | None = None
        try:
            with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as t:
                out_png = t.name
            r = subprocess.run(
                [
                    gs,
                    '-dSAFER',
                    '-dBATCH',
                    '-dNOPAUSE',
                    '-sDEVICE=png16m',
                    '-dGraphicsAlphaBits=4',
                    '-dTextAlphaBits=4',
                    # Без -dEPSCrop: иначе по %%BoundingBox иногда срезались края, совпавшие с холстом
                    '-r150',
                    f'-sOutputFile={out_png}',
                    ps_path,
                ],
                capture_output=True,
                text=True,
                timeout=25,
            )
            if r.returncode == 0 and out_png and os.path.isfile(out_png) and os.path.getsize(out_png) > 0:
                with open(out_png, 'rb') as f:
                    b = f.read()
                if len(b) <= _MAX_TURTLE_PNG:
                    return base64.b64encode(b).decode('ascii')
        except Exception:
            pass
        finally:
            if out_png and os.path.isfile(out_png):
                try:
                    os.unlink(out_png)
                except OSError:
                    pass
    cvt = shutil.which('convert')
    if cvt:
        out_png2: str | None = None
        try:
            with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as t:
                out_png2 = t.name
            r = subprocess.run(
                [cvt, '-density', '150', ps_path, out_png2],
                capture_output=True,
                timeout=25,
            )
            if r.returncode == 0 and out_png2 and os.path.isfile(out_png2) and os.path.getsize(out_png2) > 0:
                with open(out_png2, 'rb') as f:
                    b = f.read()
                if len(b) <= _MAX_TURTLE_PNG:
                    return base64.b64encode(b).decode('ascii')
        except Exception:
            pass
        finally:
            if out_png2 and os.path.isfile(out_png2):
                try:
                    os.unlink(out_png2)
                except OSError:
                    pass
    return None


def _svg_to_b64(svg_path: str) -> str | None:
    if not os.path.isfile(svg_path) or os.path.getsize(svg_path) < 8:
        return None
    try:
        with open(svg_path, 'rb') as f:
            b = f.read()
        if len(b) <= _MAX_TURTLE_PNG:
            return base64.b64encode(b).decode('ascii')
    except Exception:
        return None
    return None


def run_python_sandbox(
    code: str,
    timeout_sec: int | None = None,
    task_files: list[tuple[str, bytes]] | None = None,
) -> tuple[str, str, str | None]:
    """Запуск кода Python в песочнице. Возвращает (stdout, stderr, base64 png или None)."""
    code_in = code or ''
    tsec = _sandbox_timeout_seconds(code, timeout_sec)
    cmd: list[str] = [sys.executable, '-c', PYTHON_RUNNER]
    try:
        with tempfile.TemporaryDirectory(prefix='boostudy_sandbox_') as tmpdir:
            if task_files:
                for fname, fbytes in task_files:
                    fpath = os.path.join(tmpdir, fname)
                    with open(fpath, 'wb') as f:
                        f.write(fbytes)
            proc = subprocess.run(
                cmd,
                input=code_in,
                capture_output=True,
                text=True,
                timeout=tsec,
                cwd=tmpdir,
            )
            stdout = (proc.stdout or '').strip()
            stderr = (proc.stderr or '').strip()
            turtle_b64: str | None = None
            if 'turtle' in (code or '').lower():
                ps = os.path.join(tmpdir, TURTLE_PS_NAME)
                svg = os.path.join(tmpdir, TURTLE_SVG_NAME)
                turtle_b64 = _postscript_to_png_b64(ps) or _svg_to_b64(svg)
            if not turtle_b64 and (not stdout) and (not stderr) and 'turtle' in (code or '').lower():
                stdout = (
                    '[turtle] Код выполнен. В программе нет видимых линий или точек. Можно добавить print(...).'
                )
            return stdout, stderr, turtle_b64
    except subprocess.TimeoutExpired:
        return '', 'Превышено время выполнения (макс. {} с).'.format(tsec), None
    except Exception as e:
        return '', str(e), None
