"""Bounded server-side SVG renderers for declarative theory visualizations."""
from __future__ import annotations

import html
import json
import math
from typing import Any

from app.theory.math_validation import MathAnswerError, UnsupportedMathAnswer, evaluate_numeric_expression


MAX_JSON_LENGTH = 12_000
MAX_FUNCTIONS = 4
MAX_PRIMITIVES = 60
MAX_SAMPLES = 360
SVG_NS = 'http://www.w3.org/2000/svg'


def _load_spec(raw: str | dict[str, Any]) -> dict[str, Any]:
    if isinstance(raw, dict):
        data = raw
    else:
        if len(raw or '') > MAX_JSON_LENGTH:
            raise ValueError('Описание визуализации слишком длинное.')
        try:
            data = json.loads(raw)
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError('Ожидается корректный JSON.') from exc
    if not isinstance(data, dict):
        raise ValueError('Корнем описания должен быть JSON-объект.')
    return data


def _number(value: Any, name: str, minimum: float, maximum: float) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f'Поле {name} должно быть числом.') from exc
    if not math.isfinite(result) or not minimum <= result <= maximum:
        raise ValueError(f'Поле {name} вне разрешённого диапазона.')
    return result


def _fmt(value: float) -> str:
    return f'{value:.3f}'.rstrip('0').rstrip('.') or '0'


def render_function_plot(raw_spec: str | dict[str, Any]) -> str:
    """Render a bounded 2D plot; expressions use the safe math AST evaluator."""
    spec = _load_spec(raw_spec)
    x_min = _number(spec.get('x_min', -5), 'x_min', -1000, 1000)
    x_max = _number(spec.get('x_max', 5), 'x_max', -1000, 1000)
    y_min = _number(spec.get('y_min', -5), 'y_min', -1000, 1000)
    y_max = _number(spec.get('y_max', 5), 'y_max', -1000, 1000)
    if x_min >= x_max or y_min >= y_max:
        raise ValueError('Минимум каждой оси должен быть меньше максимума.')
    functions = spec.get('functions', [])
    if not isinstance(functions, list) or not 1 <= len(functions) <= MAX_FUNCTIONS:
        raise ValueError(f'Укажите от 1 до {MAX_FUNCTIONS} функций.')
    width, height, padding = 720, 440, 42
    base_w, base_h = width - 2 * padding, height - 2 * padding
    aspect = str(spec.get('aspect', 'equal')).lower()
    if aspect == 'equal':
        unit_scale = min(base_w / (x_max - x_min), base_h / (y_max - y_min))
        plot_w, plot_h = (x_max - x_min) * unit_scale, (y_max - y_min) * unit_scale
        plot_left = padding + (base_w - plot_w) / 2
        plot_top = padding + (base_h - plot_h) / 2
        x_map = lambda x: plot_left + (x - x_min) * unit_scale
        y_map = lambda y: plot_top + plot_h - (y - y_min) * unit_scale
    elif aspect == 'stretch':
        plot_w, plot_h = base_w, base_h
        plot_left, plot_top = padding, padding
        x_map = lambda x: padding + (x - x_min) / (x_max - x_min) * plot_w
        y_map = lambda y: height - padding - (y - y_min) / (y_max - y_min) * plot_h
    else:
        raise ValueError('aspect допускает только equal или stretch.')
    plot_right, plot_bottom = plot_left + plot_w, plot_top + plot_h
    parts = [
        f'<figure class="theory-visualization theory-function-plot" role="img" aria-label="{html.escape(str(spec.get("title") or "График функции"), quote=True)}">',
        f'<div class="theory-svg-scroll"><svg xmlns="{SVG_NS}" viewBox="0 0 {width} {height}" class="theory-plot-svg" preserveAspectRatio="xMidYMid meet" aria-hidden="true">',
        '<rect width="100%" height="100%" rx="18" fill="#fff"/>',
    ]
    # Grid and labels use at most 22 lines per axis, regardless of range.
    for axis_min, axis_max, mapper, is_x in ((x_min, x_max, x_map, True), (y_min, y_max, y_map, False)):
        span = axis_max - axis_min
        step = 10 ** math.floor(math.log10(span / 10)) if span else 1
        if span / step > 18:
            step *= 2
        first = math.ceil(axis_min / step) * step
        value = first
        iterations = 0
        while value <= axis_max + step * 1e-8 and iterations < 24:
            pos = mapper(value)
            if is_x:
                parts.append(f'<line x1="{_fmt(pos)}" y1="{_fmt(plot_top)}" x2="{_fmt(pos)}" y2="{_fmt(plot_bottom)}" stroke="#e2e8f0" stroke-width="1"/>')
                parts.append(f'<text x="{_fmt(pos)}" y="{_fmt(plot_bottom+19)}" text-anchor="middle" class="theory-plot-label">{html.escape(_fmt(value))}</text>')
            else:
                parts.append(f'<line x1="{_fmt(plot_left)}" y1="{_fmt(pos)}" x2="{_fmt(plot_right)}" y2="{_fmt(pos)}" stroke="#e2e8f0" stroke-width="1"/>')
                parts.append(f'<text x="{padding-9}" y="{_fmt(pos+4)}" text-anchor="end" class="theory-plot-label">{html.escape(_fmt(value))}</text>')
            value += step
            iterations += 1
    intervals = spec.get('intervals', [])
    if isinstance(intervals, list):
        for interval in intervals[:12]:
            if not isinstance(interval, dict): continue
            left = _number(interval.get('x_min'), 'intervals[].x_min', x_min, x_max)
            right = _number(interval.get('x_max'), 'intervals[].x_max', x_min, x_max)
            if left >= right: raise ValueError('В каждом выделенном интервале x_min должен быть меньше x_max.')
            parts.append(f'<rect x="{_fmt(x_map(left))}" y="{_fmt(plot_top)}" width="{_fmt(x_map(right)-x_map(left))}" height="{_fmt(plot_h)}" fill="#fef3c7" fill-opacity="0.52"/>')
    if x_min <= 0 <= x_max:
        x0 = x_map(0)
        parts.append(f'<line x1="{_fmt(x0)}" y1="{_fmt(plot_top)}" x2="{_fmt(x0)}" y2="{_fmt(plot_bottom)}" stroke="#475569" stroke-width="2"/><text x="{_fmt(x0+6)}" y="{_fmt(plot_top+14)}" class="theory-plot-axis">y</text>')
    if y_min <= 0 <= y_max:
        y0 = y_map(0)
        parts.append(f'<line x1="{_fmt(plot_left)}" y1="{_fmt(y0)}" x2="{_fmt(plot_right)}" y2="{_fmt(y0)}" stroke="#475569" stroke-width="2"/><text x="{_fmt(plot_right-10)}" y="{_fmt(y0-7)}" class="theory-plot-axis">x</text>')

    palette = ['#4f46e5', '#059669', '#e11d48', '#d97706']
    legend = []
    sampled_functions: list[list[tuple[float, float] | None]] = []
    for fn_index, function in enumerate(functions):
        if not isinstance(function, dict) or not isinstance(function.get('expression'), str):
            raise ValueError('У каждой функции должны быть expression и необязательный label.')
        expression = function['expression'].strip()
        if len(expression) > 160:
            raise ValueError('Выражение графика слишком длинное.')
        color = palette[fn_index]
        previous: tuple[float, float] | None = None
        segments: list[str] = []
        samples: list[tuple[float, float] | None] = []
        for sample_index in range(MAX_SAMPLES + 1):
            x = x_min + (x_max - x_min) * sample_index / MAX_SAMPLES
            try:
                y = evaluate_numeric_expression(expression, {'x': x})
            except (MathAnswerError, ArithmeticError, ValueError, OverflowError):
                previous = None
                samples.append(None)
                continue
            if not math.isfinite(y) or abs(y) > max(abs(y_min), abs(y_max), 1) * 20:
                previous = None
                samples.append(None)
                continue
            current = (x, y)
            samples.append(current)
            if previous:
                # Break at poles/discontinuities instead of drawing a false bridge.
                if abs(current[1] - previous[1]) < (y_max - y_min) * 0.45:
                    segments.append(f'M {_fmt(x_map(previous[0]))} {_fmt(y_map(previous[1]))} L {_fmt(x_map(current[0]))} {_fmt(y_map(current[1]))}')
            previous = current
        if not segments:
            raise ValueError(f'Не удалось построить график функции {fn_index + 1}.')
        parts.append(f'<path d="{" ".join(segments)}" fill="none" stroke="{color}" stroke-width="3.25" stroke-linecap="round" stroke-linejoin="round"/>')
        sampled_functions.append(samples)
        legend_label = str(function.get('label') or f'y = {expression}')[:120]
        legend.append((color, legend_label))

    if spec.get('show_intersections') is True and len(sampled_functions) > 1:
        shown: list[tuple[float, float]] = []
        for left_index in range(len(sampled_functions)):
            for right_index in range(left_index + 1, len(sampled_functions)):
                left_values, right_values = sampled_functions[left_index], sampled_functions[right_index]
                for sample_index in range(min(len(left_values), len(right_values)) - 1):
                    a0, a1 = left_values[sample_index], left_values[sample_index + 1]
                    b0, b1 = right_values[sample_index], right_values[sample_index + 1]
                    if None in (a0, a1, b0, b1): continue
                    d0, d1 = a0[1] - b0[1], a1[1] - b1[1]
                    if d0 == 0 or d0 * d1 >= 0: continue
                    ratio = abs(d0) / (abs(d0) + abs(d1))
                    x = a0[0] + (a1[0] - a0[0]) * ratio
                    y = a0[1] + (a1[1] - a0[1]) * ratio
                    if x_min <= x <= x_max and y_min <= y <= y_max and all(math.hypot(x-px, y-py) > (x_max-x_min)/80 for px,py in shown):
                        shown.append((x,y))
        for x, y in shown[:24]:
            parts.append(f'<circle cx="{_fmt(x_map(x))}" cy="{_fmt(y_map(y))}" r="5" fill="#0f172a" stroke="#fff" stroke-width="2"/>')

    # Optional declarative points and guide lines are data, never executable code.
    for point in spec.get('points', [])[:30] if isinstance(spec.get('points', []), list) else []:
        if not isinstance(point, dict): continue
        x = _number(point.get('x'), 'points[].x', x_min, x_max)
        y = _number(point.get('y'), 'points[].y', y_min, y_max)
        label = html.escape(str(point.get('label') or f'({_fmt(x)}; {_fmt(y)})')[:60], quote=True)
        parts.append(f'<circle cx="{_fmt(x_map(x))}" cy="{_fmt(y_map(y))}" r="5" fill="#0f172a"/><text x="{_fmt(x_map(x)+8)}" y="{_fmt(y_map(y)-8)}" class="theory-plot-point-label">{label}</text>')
    for line in spec.get('lines', [])[:12] if isinstance(spec.get('lines', []), list) else []:
        if not isinstance(line, dict) or line.get('axis') not in {'x', 'y'}: continue
        axis = line['axis']
        value = _number(line.get('value'), 'lines[].value', x_min if axis == 'x' else y_min, x_max if axis == 'x' else y_max)
        color = '#0ea5e9' if axis == 'x' else '#f97316'
        if axis == 'x':
            pos = x_map(value); parts.append(f'<line x1="{_fmt(pos)}" y1="{_fmt(plot_top)}" x2="{_fmt(pos)}" y2="{_fmt(plot_bottom)}" stroke="{color}" stroke-dasharray="7 5" stroke-width="2"/>')
        else:
            pos = y_map(value); parts.append(f'<line x1="{_fmt(plot_left)}" y1="{_fmt(pos)}" x2="{_fmt(plot_right)}" y2="{_fmt(pos)}" stroke="{color}" stroke-dasharray="7 5" stroke-width="2"/>')
    parts.append('</svg></div>')
    if legend:
        parts.append('<figcaption class="theory-plot-legend">' + ''.join(f'<span><i style="background:{color}"></i>{html.escape(label)}</span>' for color, label in legend) + '</figcaption>')
    parts.append('</figure>')
    return ''.join(parts)


def render_geometry(raw_spec: str | dict[str, Any]) -> str:
    """Render a bounded geometry diagram from points and safe SVG primitives."""
    spec = _load_spec(raw_spec)
    primitives = spec.get('items', [])
    if not isinstance(primitives, list) or len(primitives) > MAX_PRIMITIVES:
        raise ValueError(f'Чертёж должен содержать не более {MAX_PRIMITIVES} примитивов.')
    width, height = 640, 420
    points: dict[str, tuple[float, float]] = {}
    for item in primitives:
        if isinstance(item, dict) and item.get('type') == 'point':
            name = str(item.get('name') or '')
            if not name or len(name) > 12 or name in points:
                raise ValueError('Имя каждой точки должно быть коротким и уникальным.')
            points[name] = (_number(item.get('x'), f'{name}.x', 0, width), _number(item.get('y'), f'{name}.y', 0, height))
    if len(points) > 30:
        raise ValueError('На чертеже допускается не более 30 точек.')

    def point(name: Any) -> tuple[float, float]:
        if str(name) not in points:
            raise ValueError(f'Не найдена точка «{name}».')
        return points[str(name)]

    parts = [f'<figure class="theory-visualization theory-geometry" role="img" aria-label="{html.escape(str(spec.get("title") or "Геометрический чертёж"), quote=True)}"><div class="theory-svg-scroll"><svg xmlns="{SVG_NS}" viewBox="0 0 {width} {height}" class="theory-geometry-svg" aria-hidden="true"><rect width="100%" height="100%" rx="18" fill="#fff"/>']
    for item in primitives:
        if not isinstance(item, dict): continue
        kind = item.get('type')
        color = str(item.get('color') or '#4f46e5')
        if not color.startswith('#') or len(color) not in {4, 7} or not all(c in '0123456789abcdefABCDEF' for c in color[1:]):
            color = '#4f46e5'
        if kind == 'point':
            x, y = point(item['name']); label = html.escape(str(item.get('label') or item['name'])[:30])
            parts.append(f'<circle cx="{_fmt(x)}" cy="{_fmt(y)}" r="4.5" fill="#0f172a"/><text x="{_fmt(x+8)}" y="{_fmt(y-8)}" class="theory-geometry-label">{label}</text>')
        elif kind in {'segment', 'line', 'ray'}:
            x1, y1 = point(item.get('from')); x2, y2 = point(item.get('to'))
            if kind == 'line' or kind == 'ray':
                dx, dy = x2-x1, y2-y1
                if math.hypot(dx, dy) < 1e-8: raise ValueError('Для прямой и луча нужны разные точки.')
                factor_start = -3 if kind == 'line' else 0
                factor_end = 3
                x1, y1, x2, y2 = x1+factor_start*dx, y1+factor_start*dy, x1+factor_end*dx, y1+factor_end*dy
            parts.append(f'<line x1="{_fmt(x1)}" y1="{_fmt(y1)}" x2="{_fmt(x2)}" y2="{_fmt(y2)}" stroke="{color}" stroke-width="2.6" stroke-linecap="round"/>')
            if item.get('equal_marks') in {1, 2, 3} and kind == 'segment':
                dx, dy = x2-x1, y2-y1; length = math.hypot(dx,dy) or 1; mx,my=(x1+x2)/2,(y1+y2)/2; ox,oy=-dy/length*7,dx/length*7
                for offset in range(int(item['equal_marks'])):
                    shift=(offset-(int(item['equal_marks'])-1)/2)*7
                    cx,cy=mx+dx/length*shift,my+dy/length*shift
                    parts.append(f'<line x1="{_fmt(cx-ox)}" y1="{_fmt(cy-oy)}" x2="{_fmt(cx+ox)}" y2="{_fmt(cy+oy)}" stroke="{color}" stroke-width="2"/>')
        elif kind == 'circle':
            cx, cy = point(item.get('center')); radius = _number(item.get('radius'), 'circle.radius', 1, 300)
            parts.append(f'<circle cx="{_fmt(cx)}" cy="{_fmt(cy)}" r="{_fmt(radius)}" fill="none" stroke="{color}" stroke-width="2.6"/>')
        elif kind == 'polygon':
            names = item.get('points', [])
            if not isinstance(names, list) or not 3 <= len(names) <= 12: raise ValueError('У многоугольника должно быть от 3 до 12 вершин.')
            coordinates = ' '.join(f'{_fmt(x)},{_fmt(y)}' for x,y in (point(name) for name in names))
            fill = str(item.get('fill') or '#c7d2fe')
            if not fill.startswith('#') or len(fill) not in {4, 7} or not all(c in '0123456789abcdefABCDEF' for c in fill[1:]):
                fill = '#c7d2fe'
            parts.append(f'<polygon points="{coordinates}" fill="{fill}" fill-opacity="0.28" stroke="{color}" stroke-width="2.6" stroke-linejoin="round"/>')
        elif kind == 'angle':
            a, vertex, b = point(item.get('a')), point(item.get('vertex')), point(item.get('b'))
            radius = _number(item.get('radius', 28), 'angle.radius', 8, 80)
            ax, ay = a[0]-vertex[0], a[1]-vertex[1]; bx, by = b[0]-vertex[0], b[1]-vertex[1]
            al, bl = math.hypot(ax,ay), math.hypot(bx,by)
            if al < 1 or bl < 1: raise ValueError('Угол должен иметь две ненулевые стороны.')
            p1=(vertex[0]+ax/al*radius, vertex[1]+ay/al*radius); p2=(vertex[0]+bx/bl*radius, vertex[1]+by/bl*radius)
            parts.append(f'<path d="M {_fmt(p1[0])} {_fmt(p1[1])} Q {_fmt(vertex[0])} {_fmt(vertex[1])} {_fmt(p2[0])} {_fmt(p2[1])}" fill="none" stroke="{color}" stroke-width="2"/>')
            if item.get('right') is True:
                ux,uy=ax/al,ay/al; vx,vy=bx/bl,by/bl; s=radius*.45; q1=(vertex[0]+ux*s,vertex[1]+uy*s); q2=(q1[0]+vx*s,q1[1]+vy*s); q3=(vertex[0]+vx*s,vertex[1]+vy*s)
                parts.append(f'<polyline points="{_fmt(q1[0])},{_fmt(q1[1])} {_fmt(q2[0])},{_fmt(q2[1])} {_fmt(q3[0])},{_fmt(q3[1])}" fill="none" stroke="{color}" stroke-width="2"/>')
        elif kind == 'label':
            x = _number(item.get('x'), 'label.x', 0, width); y = _number(item.get('y'), 'label.y', 0, height)
            parts.append(f'<text x="{_fmt(x)}" y="{_fmt(y)}" class="theory-geometry-label">{html.escape(str(item.get("text") or "")[:80])}</text>')
        else:
            raise ValueError(f'Тип геометрического примитива «{kind}» не поддерживается.')
    parts.append('</svg></div></figure>')
    return ''.join(parts)
