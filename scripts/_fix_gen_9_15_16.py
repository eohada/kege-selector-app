#!/usr/bin/env python3
"""
Fix generators for tasks 9, 15, 16.
Removes old generated, creates new ones, merges back.
"""
import json, os, sys, random, math
sys.stdout.reconfigure(encoding='utf-8')
random.seed(123)

DATA_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'oge_inf_tasks.json')

with open(DATA_FILE, 'r', encoding='utf-8') as f:
    all_tasks = json.load(f)

old_gen_9 = [t for t in all_tasks if t['task_number'] == 9 and t.get('generated')]
old_gen_15 = [t for t in all_tasks if t['task_number'] == 15 and t.get('generated')]
old_gen_16 = [t for t in all_tasks if t['task_number'] == 16 and t.get('generated')]
print(f"Removing: task9={len(old_gen_9)}, task15={len(old_gen_15)}, task16={len(old_gen_16)}")

all_tasks = [t for t in all_tasks if not (t.get('generated') and t['task_number'] in (9, 15, 16))]

NODE_LETTERS = list('АБВГДЕЖЗИКЛМН')
DIFFS = ['easy'] * 67 + ['medium'] * 67 + ['hard'] * 66


def sol(steps, answer):
    h = '<p><b>Решение:</b></p>'
    for i, s in enumerate(steps, 1):
        h += f'<p>{i}) {s}</p>'
    h += f'<p><b>Ответ:</b> {answer}</p>'
    return h


def make(tn, html, answer, solution, diff):
    return {
        'task_number': tn, 'content_html': html, 'answer': str(answer),
        'solution_html': solution, 'difficulty_level': diff,
        'source_url': None, 'generated': True,
    }


# ════════════════════════════════════════════════════════════════════
# TASK 9: Proper layered DAG with nice SVG
# ════════════════════════════════════════════════════════════════════

def make_layered_dag(n_nodes):
    """Create a DAG with layered structure. Every node from 0..n-1 is placed."""
    nodes = list(range(n_nodes))
    n_layers = max(3, min(5, n_nodes // 2))
    layers = [[] for _ in range(n_layers)]
    layers[0].append(0)
    layers[-1].append(n_nodes - 1)
    remaining = nodes[1:-1]
    random.shuffle(remaining)
    for idx, node in enumerate(remaining):
        layer_idx = 1 + (idx % (n_layers - 2)) if n_layers > 2 else 1
        layers[layer_idx].append(node)
    layers = [sorted(l) for l in layers if l]

    adj = [[False]*n_nodes for _ in range(n_nodes)]

    for li in range(len(layers) - 1):
        cur_layer = layers[li]
        next_layer = layers[li + 1]
        for node in cur_layer:
            targets = random.sample(next_layer, min(len(next_layer), random.randint(1, 3)))
            for t in targets:
                adj[node][t] = True
        for node in next_layer:
            if not any(adj[u][node] for u in cur_layer):
                adj[random.choice(cur_layer)][node] = True

    for li in range(len(layers) - 2):
        cur_layer = layers[li]
        skip_layer = layers[li + 2]
        for node in cur_layer:
            if random.random() < 0.3:
                t = random.choice(skip_layer)
                adj[node][t] = True

    return adj, layers


def render_svg_graph(adj, labels, layers):
    n = len(labels)
    col_spacing = 140
    row_spacing = 80
    margin_x = 60
    margin_y = 50
    r = 20

    max_layer_size = max(len(l) for l in layers)
    w = len(layers) * col_spacing + margin_x * 2
    h = max_layer_size * row_spacing + margin_y * 2

    positions = {}
    for li, layer in enumerate(layers):
        x = margin_x + li * col_spacing
        layer_h = (len(layer) - 1) * row_spacing
        start_y = margin_y + (h - margin_y * 2 - layer_h) / 2
        for ni, node in enumerate(layer):
            y = start_y + ni * row_spacing
            y += random.randint(-8, 8)
            positions[node] = (x, y)

    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" '
           f'style="max-width:100%;background:#fff;border-radius:8px;border:1px solid #ddd">')
    svg += ('<defs><marker id="arrowhead" markerWidth="10" markerHeight="7" '
            'refX="10" refY="3.5" orient="auto" markerUnits="strokeWidth">'
            '<polygon points="0 0, 10 3.5, 0 7" fill="#444"/></marker></defs>')

    for i in range(n):
        for j in range(n):
            if adj[i][j]:
                x1, y1 = positions[i]
                x2, y2 = positions[j]
                dx, dy = x2 - x1, y2 - y1
                dist = math.sqrt(dx*dx + dy*dy)
                if dist < 1:
                    continue
                ux, uy = dx/dist, dy/dist
                sx = x1 + ux * (r + 2)
                sy = y1 + uy * (r + 2)
                ex = x2 - ux * (r + 8)
                ey = y2 - uy * (r + 8)

                mid_x = (sx + ex) / 2
                mid_y = (sy + ey) / 2
                perp_x = -(ey - sy) * 0.15
                perp_y = (ex - sx) * 0.15

                svg += (f'<path d="M{sx:.0f},{sy:.0f} Q{mid_x+perp_x:.0f},{mid_y+perp_y:.0f} '
                        f'{ex:.0f},{ey:.0f}" fill="none" stroke="#555" stroke-width="2" '
                        f'marker-end="url(#arrowhead)"/>')

    for i in range(n):
        x, y = positions[i]
        svg += (f'<circle cx="{x:.0f}" cy="{y:.0f}" r="{r}" '
                f'fill="#5b6abf" stroke="#3d4785" stroke-width="2"/>')
        svg += (f'<text x="{x:.0f}" y="{y+6:.0f}" text-anchor="middle" '
                f'fill="white" font-size="15" font-weight="bold" '
                f'font-family="Arial,sans-serif">{labels[i]}</text>')

    svg += '</svg>'
    return svg


def gen_task9_fixed(count=200):
    results = []
    for i in range(count):
        diff = DIFFS[i % 200]
        if diff == 'easy':
            n = random.choice([5, 6])
        elif diff == 'medium':
            n = random.choice([7, 8])
        else:
            n = random.choice([9, 10, 11])

        labels = NODE_LETTERS[:n]
        adj, layers = make_layered_dag(n)

        dp = [0] * n
        dp[0] = 1
        for v in range(n):
            for u in range(v):
                if adj[u][v]:
                    dp[v] += dp[u]
        answer = dp[n - 1]

        if answer < 3:
            for li in range(len(layers) - 1):
                for node in layers[li]:
                    for t in layers[li + 1]:
                        if not adj[node][t] and random.random() < 0.5:
                            adj[node][t] = True
            dp = [0] * n
            dp[0] = 1
            for v in range(n):
                for u in range(v):
                    if adj[u][v]:
                        dp[v] += dp[u]
            answer = dp[n - 1]

        svg = render_svg_graph(adj, labels, layers)

        content = (
            f'<p>На рисунке — схема дорог, связывающих города '
            f'{", ".join(labels)}. По каждой дороге можно двигаться только '
            f'в одном направлении, указанном стрелкой. Сколько существует '
            f'различных путей из города {labels[0]} в город {labels[-1]}?</p>'
            f'{svg}'
        )

        dp_text = ', '.join(f'{labels[v]}={dp[v]}' for v in range(n))
        steps = [
            f'Метод динамического программирования: считаем кол-во путей от {labels[0]} до каждого города.',
            f'Пути: {dp_text}.',
            f'Ответ: количество путей до {labels[-1]} = {answer}.',
        ]
        results.append(make(9, content, answer, sol(steps, answer), diff))

    return results


# ════════════════════════════════════════════════════════════════════
# TASK 15: Robot maze — proper OGE format
# ════════════════════════════════════════════════════════════════════

ROBOT_PREAMBLE = (
    '<p>Исполнитель Робот умеет перемещаться по лабиринту, начерченному '
    'на плоскости, разбитой на клетки. Между соседними (по сторонам) '
    'клетками может стоять стена, через которую Робот не пройдёт.</p>'
    '<p>У Робота есть четыре команды-приказа: <b>вверх, вниз, влево, вправо</b>. '
    'При выполнении любой команды Робот перемещается на одну клетку '
    'в соответствующем направлении. Если Робот получит команду '
    'движения сквозь стену, он разрушится.</p>'
    '<p>Также у Робота есть команда <b>закрасить</b>, при которой '
    'закрашивается клетка, в которой Робот находится.</p>'
    '<p>Ещё четыре команды проверяют истинность условия отсутствия стены '
    'с каждой стороны: <b>сверху свободно, снизу свободно, слева свободно, '
    'справа свободно</b>.</p>'
    '<p>Цикл ПОКА &lt;условие&gt; выполняет команду, пока условие истинно.</p>'
)


def gen_maze_svg(rows, cols, walls_h, walls_v, robot, paint_cells):
    """Generate a proper maze SVG with numbered axes."""
    cell = 32
    pad = 30
    w = pad * 2 + cols * cell
    h = pad * 2 + rows * cell

    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" '
           f'style="max-width:400px;background:#fff;border:1px solid #ddd;border-radius:4px">')

    for r in range(rows):
        for c in range(cols):
            x = pad + c * cell
            y = pad + r * cell
            fill = '#fff'
            if (r, c) in paint_cells:
                fill = '#d0d0d0'
            svg += f'<rect x="{x}" y="{y}" width="{cell}" height="{cell}" fill="{fill}" stroke="#bbb" stroke-width="0.5"/>'

    rx, ry = robot
    cx = pad + ry * cell + cell // 2
    cy = pad + rx * cell + cell // 2
    svg += f'<circle cx="{cx}" cy="{cy}" r="{cell//3}" fill="#5b6abf"/>'
    svg += (f'<text x="{cx}" y="{cy+4}" text-anchor="middle" fill="white" '
            f'font-size="10" font-weight="bold">R</text>')

    thick = 3
    svg += (f'<rect x="{pad}" y="{pad}" width="{cols*cell}" height="{rows*cell}" '
            f'fill="none" stroke="#333" stroke-width="{thick}"/>')

    for (r, c, side) in walls_h:
        x1 = pad + c * cell
        x2 = x1 + cell
        if side == 'bottom':
            y = pad + (r + 1) * cell
        else:
            y = pad + r * cell
        svg += f'<line x1="{x1}" y1="{y}" x2="{x2}" y2="{y}" stroke="#333" stroke-width="{thick}"/>'

    for (r, c, side) in walls_v:
        y1 = pad + r * cell
        y2 = y1 + cell
        if side == 'right':
            x = pad + (c + 1) * cell
        else:
            x = pad + c * cell
        svg += f'<line x1="{x}" y1="{y1}" x2="{x}" y2="{y2}" stroke="#333" stroke-width="{thick}"/>'

    svg += '</svg>'
    return svg


def gen_task15_fixed(count=200):
    results = []

    patterns = [
        {
            'name': 'горизонтальная полоса',
            'desc': 'закрасить все клетки, расположенные правее Робота и до стены',
            'algo': 'ПОКА справа свободно\n  вправо\n  закрасить',
            'make': lambda rows, cols, rr, rc: {(rr, c) for c in range(rc + 1, cols)},
        },
        {
            'name': 'вертикальная полоса',
            'desc': 'закрасить все клетки, расположенные ниже Робота и до стены',
            'algo': 'ПОКА снизу свободно\n  вниз\n  закрасить',
            'make': lambda rows, cols, rr, rc: {(r, rc) for r in range(rr + 1, rows)},
        },
        {
            'name': 'угол вправо-вниз',
            'desc': 'закрасить все клетки правее Робота до стены, затем все клетки ниже до стены',
            'algo': 'ПОКА справа свободно\n  вправо\n  закрасить\nПОКА снизу свободно\n  вниз\n  закрасить',
            'make': lambda rows, cols, rr, rc: (
                {(rr, c) for c in range(rc + 1, cols)} |
                {(r, cols - 1) for r in range(rr + 1, rows)}
            ),
        },
        {
            'name': 'полоса влево',
            'desc': 'закрасить все клетки, расположенные левее Робота и до стены',
            'algo': 'ПОКА слева свободно\n  влево\n  закрасить',
            'make': lambda rows, cols, rr, rc: {(rr, c) for c in range(0, rc)},
        },
        {
            'name': 'полоса вверх',
            'desc': 'закрасить все клетки, расположенные выше Робота и до стены',
            'algo': 'ПОКА сверху свободно\n  вверх\n  закрасить',
            'make': lambda rows, cols, rr, rc: {(r, rc) for r in range(0, rr)},
        },
        {
            'name': 'угол влево-вверх',
            'desc': 'закрасить все клетки левее Робота до стены, затем все клетки выше до стены',
            'algo': 'ПОКА слева свободно\n  влево\n  закрасить\nПОКА сверху свободно\n  вверх\n  закрасить',
            'make': lambda rows, cols, rr, rc: (
                {(rr, c) for c in range(0, rc)} |
                {(r, 0) for r in range(0, rr)}
            ),
        },
    ]

    for i in range(count):
        diff = DIFFS[i % 200]

        if diff == 'easy':
            rows, cols = 6, 8
            n_extra_walls = random.randint(2, 4)
            pattern = random.choice(patterns[:2])
        elif diff == 'medium':
            rows, cols = 7, 9
            n_extra_walls = random.randint(3, 6)
            pattern = random.choice(patterns[2:4])
        else:
            rows, cols = 8, 10
            n_extra_walls = random.randint(4, 8)
            pattern = random.choice(patterns[2:])

        robot_r = random.randint(1, rows - 2)
        robot_c = random.randint(1, cols - 2)

        walls_h = []
        walls_v = []
        for _ in range(n_extra_walls):
            wr = random.randint(0, rows - 2)
            wc = random.randint(0, cols - 1)
            if (wr, wc) != (robot_r, robot_c) and (wr + 1, wc) != (robot_r, robot_c):
                walls_h.append((wr, wc, 'bottom'))
        for _ in range(n_extra_walls // 2):
            wr = random.randint(0, rows - 1)
            wc = random.randint(0, cols - 2)
            if (wr, wc) != (robot_r, robot_c) and (wr, wc + 1) != (robot_r, robot_c):
                walls_v.append((wr, wc, 'right'))

        paint = pattern['make'](rows, cols, robot_r, robot_c)
        paint.discard((robot_r, robot_c))

        if not paint:
            paint = {(robot_r, c) for c in range(robot_c + 1, cols)}

        maze_svg = gen_maze_svg(rows, cols, walls_h, walls_v, (robot_r, robot_c), paint)

        algo_html = pattern['algo'].replace('\n', '<br>')

        content = (
            f'{ROBOT_PREAMBLE}'
            f'{maze_svg}'
            f'<p>Робот находится в клетке, отмеченной буквой <b>R</b>. '
            f'Задание: {pattern["desc"]}. '
            f'Клетки, которые необходимо закрасить, обозначены серым цветом.</p>'
            f'<p>Напишите для Робота алгоритм, закрашивающий указанные клетки. '
            f'Робот должен закрасить только указанные клетки. '
            f'Алгоритм должен решать задачу для произвольного размера поля '
            f'и любого допустимого расположения стен.</p>'
        )

        solution = (
            f'<p><b>Решение:</b></p>'
            f'<p>Алгоритм:</p>'
            f'<pre style="background:#1a1d27;color:#e4e6f0;padding:12px;border-radius:8px;font-size:14px">'
            f'{pattern["algo"]}</pre>'
            f'<p>Робот последовательно двигается в указанном направлении, '
            f'закрашивая каждую клетку, пока не упрётся в стену.</p>'
        )

        results.append(make(15, content, '', solution, diff))

    return results


# ════════════════════════════════════════════════════════════════════
# TASK 16: Programming with REAL solution code
# ════════════════════════════════════════════════════════════════════

def gen_task16_fixed(count=200):
    results = []

    task_defs = [
        {
            'what': 'количество чётных чисел',
            'code': 'n = int(input())\ncount = 0\nfor i in range(n):\n    x = int(input())\n    if x % 2 == 0:\n        count += 1\nprint(count)',
            'func': lambda nums: sum(1 for x in nums if x % 2 == 0),
            'diff': 'easy',
        },
        {
            'what': 'количество нечётных чисел',
            'code': 'n = int(input())\ncount = 0\nfor i in range(n):\n    x = int(input())\n    if x % 2 != 0:\n        count += 1\nprint(count)',
            'func': lambda nums: sum(1 for x in nums if x % 2 != 0),
            'diff': 'easy',
        },
        {
            'what': 'максимальное число',
            'code': 'n = int(input())\nmaximum = -1\nfor i in range(n):\n    x = int(input())\n    if x > maximum:\n        maximum = x\nprint(maximum)',
            'func': lambda nums: max(nums),
            'diff': 'easy',
        },
        {
            'what': 'минимальное число',
            'code': 'n = int(input())\nminimum = 10001\nfor i in range(n):\n    x = int(input())\n    if x < minimum:\n        minimum = x\nprint(minimum)',
            'func': lambda nums: min(nums),
            'diff': 'easy',
        },
        {
            'what': 'сумму всех чисел',
            'code': 'n = int(input())\ns = 0\nfor i in range(n):\n    x = int(input())\n    s += x\nprint(s)',
            'func': lambda nums: sum(nums),
            'diff': 'easy',
        },
        {
            'what': 'количество чисел, кратных 3',
            'code': 'n = int(input())\ncount = 0\nfor i in range(n):\n    x = int(input())\n    if x % 3 == 0:\n        count += 1\nprint(count)',
            'func': lambda nums: sum(1 for x in nums if x % 3 == 0),
            'diff': 'medium',
        },
        {
            'what': 'сумму чётных чисел',
            'code': 'n = int(input())\ns = 0\nfor i in range(n):\n    x = int(input())\n    if x % 2 == 0:\n        s += x\nprint(s)',
            'func': lambda nums: sum(x for x in nums if x % 2 == 0),
            'diff': 'medium',
        },
        {
            'what': 'количество двузначных чисел',
            'code': 'n = int(input())\ncount = 0\nfor i in range(n):\n    x = int(input())\n    if 10 <= x <= 99:\n        count += 1\nprint(count)',
            'func': lambda nums: sum(1 for x in nums if 10 <= x <= 99),
            'diff': 'medium',
        },
        {
            'what': 'количество чисел, оканчивающихся на 4',
            'code': 'n = int(input())\ncount = 0\nfor i in range(n):\n    x = int(input())\n    if x % 10 == 4:\n        count += 1\nprint(count)',
            'func': lambda nums: sum(1 for x in nums if x % 10 == 4),
            'diff': 'medium',
        },
        {
            'what': 'сумму чисел, кратных 5',
            'code': 'n = int(input())\ns = 0\nfor i in range(n):\n    x = int(input())\n    if x % 5 == 0:\n        s += x\nprint(s)',
            'func': lambda nums: sum(x for x in nums if x % 5 == 0),
            'diff': 'medium',
        },
        {
            'what': 'сумму трёхзначных чисел, кратных 7',
            'code': 'n = int(input())\ns = 0\nfor i in range(n):\n    x = int(input())\n    if 100 <= x <= 999 and x % 7 == 0:\n        s += x\nprint(s)',
            'func': lambda nums: sum(x for x in nums if 100 <= x <= 999 and x % 7 == 0),
            'diff': 'hard',
        },
        {
            'what': 'количество чисел, которые делятся на 3 и при этом оканчиваются на 4',
            'code': 'n = int(input())\ncount = 0\nfor i in range(n):\n    x = int(input())\n    if x % 3 == 0 and x % 10 == 4:\n        count += 1\nprint(count)',
            'func': lambda nums: sum(1 for x in nums if x % 3 == 0 and x % 10 == 4),
            'diff': 'hard',
        },
        {
            'what': 'минимальное чётное число (гарантируется, что хотя бы одно чётное число есть)',
            'code': 'n = int(input())\nmin_even = 10001\nfor i in range(n):\n    x = int(input())\n    if x % 2 == 0 and x < min_even:\n        min_even = x\nprint(min_even)',
            'func': lambda nums: min((x for x in nums if x % 2 == 0), default=0),
            'diff': 'hard',
        },
        {
            'what': 'максимальное число, кратное 3 (гарантируется, что хотя бы одно такое число есть)',
            'code': 'n = int(input())\nmax3 = -1\nfor i in range(n):\n    x = int(input())\n    if x % 3 == 0 and x > max3:\n        max3 = x\nprint(max3)',
            'func': lambda nums: max((x for x in nums if x % 3 == 0), default=0),
            'diff': 'hard',
        },
        {
            'what': 'сумму чисел, больших 50 и при этом кратных 4',
            'code': 'n = int(input())\ns = 0\nfor i in range(n):\n    x = int(input())\n    if x > 50 and x % 4 == 0:\n        s += x\nprint(s)',
            'func': lambda nums: sum(x for x in nums if x > 50 and x % 4 == 0),
            'diff': 'hard',
        },
    ]

    diff_map = {'easy': [], 'medium': [], 'hard': []}
    for td in task_defs:
        diff_map[td['diff']].append(td)

    for i in range(count):
        diff = DIFFS[i % 200]

        pool = diff_map[diff]
        if not pool:
            pool = task_defs
        td = random.choice(pool)

        if diff == 'easy':
            n = random.randint(5, 8)
            max_val = 100
        elif diff == 'medium':
            n = random.randint(8, 15)
            max_val = 500
        else:
            n = random.randint(10, 20)
            max_val = 1000

        nums = [random.randint(1, max_val) for _ in range(n)]
        if 'чётное' in td['what'] and not any(x % 2 == 0 for x in nums):
            nums[0] = random.randint(1, max_val // 2) * 2
        if 'кратное 3' in td['what'] or 'кратных 3' in td['what']:
            if not any(x % 3 == 0 for x in nums):
                nums[0] = random.randint(1, max_val // 3) * 3

        answer = td['func'](nums)
        nums_str = ', '.join(str(x) for x in nums)

        content = (
            f'<p>Напишите программу, которая в последовательности натуральных чисел '
            f'определяет {td["what"]}. Программа получает на вход количество чисел '
            f'в последовательности, а затем сами числа. Числа не превышают {max_val}.</p>'
            f'<p><b>Входные данные:</b> в первой строке — количество чисел N, '
            f'далее N чисел, каждое в отдельной строке.</p>'
            f'<p><b>Пример входных данных:</b></p>'
            f'<pre style="background:#1a1d27;color:#e4e6f0;padding:8px;border-radius:6px;font-size:13px">'
            f'{n}\n' + '\n'.join(str(x) for x in nums) + '</pre>'
            f'<p><b>Пример выходных данных:</b> {answer}</p>'
        )

        solution = (
            f'<p><b>Решение (Python):</b></p>'
            f'<pre style="background:#1a1d27;color:#e4e6f0;padding:12px;border-radius:8px;font-size:14px">'
            f'{td["code"]}</pre>'
            f'<p>Для данного примера ({nums_str}) результат: <b>{answer}</b>.</p>'
        )

        results.append(make(16, content, answer, solution, diff))

    return results


# ════════════════════════════════════════════════════════════════════
# MAIN
# ════════════════════════════════════════════════════════════════════

max_id = max(t['site_id'] for t in all_tasks) + 1

tasks_9 = gen_task9_fixed(200)
tasks_15 = gen_task15_fixed(200)
tasks_16 = gen_task16_fixed(200)

for t in tasks_9 + tasks_15 + tasks_16:
    t['site_id'] = max_id
    max_id += 1

all_tasks.extend(tasks_9)
all_tasks.extend(tasks_15)
all_tasks.extend(tasks_16)

with open(DATA_FILE, 'w', encoding='utf-8') as f:
    json.dump(all_tasks, f, ensure_ascii=False, indent=2)

print(f"Task 9:  {len(tasks_9)} new")
print(f"Task 15: {len(tasks_15)} new")
print(f"Task 16: {len(tasks_16)} new")
print(f"Total in file: {len(all_tasks)}")

by_tn = {}
for t in all_tasks:
    n = t['task_number']
    by_tn[n] = by_tn.get(n, 0) + 1
for n in sorted(by_tn):
    print(f"  #{n}: {by_tn[n]}")
