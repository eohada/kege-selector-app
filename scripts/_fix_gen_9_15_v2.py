#!/usr/bin/env python3
"""
Fix generators for tasks 9 and 15 (v2).
Task 9: proper layered DAG with STRAIGHT arrows, fixed DP.
Task 15: coherent wall patterns (L-shape, staircase, corridor, angle).
"""
import json, os, sys, random, math
sys.stdout.reconfigure(encoding='utf-8')
random.seed(42)

DATA_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'oge_inf_tasks.json')

with open(DATA_FILE, 'r', encoding='utf-8') as f:
    all_tasks = json.load(f)

old_9 = sum(1 for t in all_tasks if t['task_number'] == 9 and t.get('generated'))
old_15 = sum(1 for t in all_tasks if t['task_number'] == 15 and t.get('generated'))
print(f"Removing: task9={old_9}, task15={old_15}")
all_tasks = [t for t in all_tasks if not (t.get('generated') and t['task_number'] in (9, 15))]

NODE_LETTERS = list('АБВГДЕЖЗИКЛМН')
DIFFS = ['easy'] * 67 + ['medium'] * 67 + ['hard'] * 66


def sol_html(steps, answer):
    h = '<p><b>Решение:</b></p>'
    for i, s in enumerate(steps, 1):
        h += f'<p>{i}) {s}</p>'
    h += f'<p><b>Ответ:</b> {answer}</p>'
    return h


def make_task(tn, html, answer, solution, diff):
    return {
        'task_number': tn, 'content_html': html, 'answer': str(answer),
        'solution_html': solution, 'difficulty_level': diff,
        'source_url': None, 'generated': True,
    }


# ════════════════════════════════════════════════════════════════════════
# TASK 9: Layered DAG with STRAIGHT arrows, correct DP
# ════════════════════════════════════════════════════════════════════════

def build_dag(n_nodes):
    """
    Build a DAG with CONTIGUOUS edges only: each node connects to a contiguous
    block of nodes in the next layer. With layers ordered left-to-right, this
    yields no edge crossings. No skip-layer edges (they always cross).
    """
    if n_nodes <= 5:
        layer_sizes = [1, 2, 2]
    elif n_nodes == 6:
        layer_sizes = [1, 2, 2, 1]
    elif n_nodes == 7:
        layer_sizes = [1, 2, 3, 1]
    elif n_nodes == 8:
        layer_sizes = [1, 3, 3, 1]
    elif n_nodes == 9:
        layer_sizes = [1, 3, 3, 2]
    elif n_nodes == 10:
        layer_sizes = [1, 3, 3, 2, 1]
    else:
        layer_sizes = [1, 3, 4, 2, 1]

    while sum(layer_sizes) < n_nodes:
        layer_sizes[len(layer_sizes) // 2] += 1
    while sum(layer_sizes) > n_nodes:
        for i in range(len(layer_sizes) - 2, 0, -1):
            if layer_sizes[i] > 1 and sum(layer_sizes) > n_nodes:
                layer_sizes[i] -= 1

    layers = []
    idx = 0
    for sz in layer_sizes:
        layers.append(list(range(idx, idx + sz)))
        idx += sz

    adj = [[False] * n_nodes for _ in range(n_nodes)]

    for li in range(len(layers) - 1):
        cur = layers[li]
        nxt = layers[li + 1]
        C, N = len(cur), len(nxt)

        # Contiguous bands: node at position i in cur -> nxt[j_start : j_end+1]
        # with j_start <= j_end and intervals ordered (no crossing).
        for i in range(C):
            # Band for i-th node: cover part of [0..N-1] with overlap for paths
            j_lo = (i * N) // C
            j_hi = ((i + 2) * N) // C  # overlap with next
            j_hi = min(j_hi, N - 1)
            if j_lo > j_hi:
                j_hi = j_lo
            # At least one successor; ensure last cur node reaches last nxt
            if i == C - 1 and j_hi < N - 1:
                j_hi = N - 1
            if i == 0 and j_lo > 0:
                j_lo = 0
            for j in range(j_lo, j_hi + 1):
                adj[cur[i]][nxt[j]] = True

        # Ensure every nxt node has at least one predecessor
        for j, v in enumerate(nxt):
            if not any(adj[u][v] for u in cur):
                i = min(j * C // N, C - 1)
                adj[cur[i]][v] = True

    return adj, layers


def render_graph_svg(adj, labels, layers):
    """Render graph with STRAIGHT arrows, style matching OGE references."""
    n = len(labels)
    col_gap = 120
    row_gap = 70
    mx, my = 50, 45
    r = 18

    max_layer = max(len(l) for l in layers)
    w = (len(layers) - 1) * col_gap + mx * 2
    h = max((max_layer - 1) * row_gap + my * 2, my * 2 + row_gap)

    pos = {}
    for li, layer in enumerate(layers):
        x = mx + li * col_gap
        total_h = (len(layer) - 1) * row_gap
        start_y = (h - total_h) / 2
        for ni, node in enumerate(layer):
            y = start_y + ni * row_gap
            pos[node] = (x, y)

    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="0 0 {w} {h}" '
        f'style="max-width:{min(w + 20, 700)}px;display:block;margin:10px auto;'
        f'background:#fff;border-radius:6px;border:1px solid #ddd">\n'
    )

    svg += (
        '<defs>'
        '<marker id="ah" markerWidth="12" markerHeight="8" '
        'refX="11" refY="4" orient="auto" markerUnits="strokeWidth">'
        '<polygon points="0 0.5, 12 4, 0 7.5" fill="#c67030"/>'
        '</marker>'
        '</defs>\n'
    )

    for i in range(n):
        for j in range(n):
            if not adj[i][j]:
                continue
            x1, y1 = pos[i]
            x2, y2 = pos[j]
            dx, dy = x2 - x1, y2 - y1
            dist = math.sqrt(dx * dx + dy * dy)
            if dist < 1:
                continue
            ux, uy = dx / dist, dy / dist
            sx = x1 + ux * (r + 1)
            sy = y1 + uy * (r + 1)
            ex = x2 - ux * (r + 6)
            ey = y2 - uy * (r + 6)
            svg += (
                f'<line x1="{sx:.1f}" y1="{sy:.1f}" '
                f'x2="{ex:.1f}" y2="{ey:.1f}" '
                f'stroke="#c67030" stroke-width="1.8" '
                f'marker-end="url(#ah)"/>\n'
            )

    for i in range(n):
        x, y = pos[i]
        svg += (
            f'<circle cx="{x:.0f}" cy="{y:.0f}" r="{r}" '
            f'fill="none" stroke="#333" stroke-width="1.5"/>\n'
        )
        svg += (
            f'<text x="{x:.0f}" y="{y + 5:.0f}" text-anchor="middle" '
            f'fill="#333" font-size="15" font-weight="bold" '
            f'font-family="serif">{labels[i]}</text>\n'
        )

    svg += '</svg>'
    return svg


def count_paths_dp(adj, n):
    """Count paths from node 0 to node n-1. Indices are topological (all edges u->v with u<v)."""
    dp = [0] * n
    dp[0] = 1
    for v in range(1, n):
        for u in range(v):
            if adj[u][v]:
                dp[v] += dp[u]
    return dp


def count_paths_dfs(adj, n):
    """Verify: count paths from 0 to n-1 by exhaustive DFS."""
    total = [0]
    def dfs(v):
        if v == n - 1:
            total[0] += 1
            return
        for w in range(v + 1, n):
            if adj[v][w]:
                dfs(w)
    dfs(0)
    return total[0]


def gen_task9(count=200):
    results = []
    attempts = 0
    while len(results) < count and attempts < count * 5:
        attempts += 1
        i = len(results)
        diff = DIFFS[i % 200]

        if diff == 'easy':
            n = random.choice([5, 6, 7])
        elif diff == 'medium':
            n = random.choice([7, 8, 9])
        else:
            n = random.choice([9, 10, 11])

        labels = NODE_LETTERS[:n]
        adj, layers = build_dag(n)
        dp = count_paths_dp(adj, n)
        answer = dp[n - 1]

        # Sanity: verify with DFS for small graphs
        if n <= 8:
            dfs_count = count_paths_dfs(adj, n)
            if dfs_count != answer:
                continue

        if answer < 4 or answer > 500:
            continue

        svg = render_graph_svg(adj, labels, layers)

        city_list = ', '.join(labels)
        content = (
            f'<p>На рисунке — схема дорог, связывающих города '
            f'{city_list}. По каждой дороге можно двигаться только '
            f'в одном направлении, указанном стрелкой. Сколько существует '
            f'различных путей из города {labels[0]} в город {labels[-1]}?</p>'
            f'{svg}'
        )

        dp_str = ', '.join(f'{labels[v]}={dp[v]}' for v in range(n))
        steps = [
            f'Подсчитаем количество путей от {labels[0]} до каждой вершины '
            f'методом динамического программирования.',
            f'Для каждой вершины: {dp_str}.',
            f'Количество путей из {labels[0]} в {labels[-1]} равно {answer}.',
        ]
        results.append(make_task(9, content, answer, sol_html(steps, answer), diff))

    return results


# ════════════════════════════════════════════════════════════════════════
# TASK 15: Robot maze with COHERENT wall structures
# ════════════════════════════════════════════════════════════════════════

ROBOT_TEXT = (
    '<p>Исполнитель Робот умеет перемещаться по лабиринту, начерченному '
    'на плоскости, разбитой на клетки. Между соседними (по сторонам) '
    'клетками может стоять стена, через которую Робот не пройдёт.</p>'
    '<p>У Робота есть четыре команды-приказа: <b>вверх, вниз, влево, вправо</b>. '
    'При выполнении любой из этих команд Робот перемещается на одну клетку '
    'в соответствующем направлении. Если Робот получит команду движения '
    'сквозь стену, он разрушится.</p>'
    '<p>Также у Робота есть команда <b>закрасить</b>, при которой '
    'закрашивается клетка, в которой Робот находится.</p>'
    '<p>Ещё четыре команды проверяют истинность условия отсутствия стены '
    'с каждой стороны: <b>сверху свободно, снизу свободно, слева свободно, '
    'справа свободно</b>.</p>'
    '<p>Цикл <b>ПОКА &lt;условие&gt;</b> выполняет команду, пока условие истинно.</p>'
)


def gen_wall_pattern(rows, cols, difficulty):
    """
    Generate coherent wall structures matching OGE style.
    Returns (h_walls, v_walls) — sets of (row, col) pairs for bottom/right borders.
    h_walls: wall on bottom border of cell (row, col)
    v_walls: wall on right border of cell (row, col)
    """
    h_walls = set()
    v_walls = set()

    patterns = ['L_top_right', 'L_top_left', 'L_bottom_right', 'L_bottom_left',
                'staircase_down', 'staircase_up', 'corridor_h', 'corridor_v',
                'T_shape', 'bar_h', 'bar_v']

    if difficulty == 'easy':
        ptype = random.choice(['bar_h', 'bar_v', 'L_top_right', 'L_bottom_left'])
    elif difficulty == 'medium':
        ptype = random.choice(['L_top_right', 'L_top_left', 'L_bottom_right',
                               'corridor_h', 'corridor_v'])
    else:
        ptype = random.choice(['staircase_down', 'staircase_up', 'T_shape',
                               'L_bottom_right', 'L_top_left'])

    if ptype == 'bar_h':
        r = random.randint(1, rows - 3)
        c_start = random.randint(1, max(1, cols - 6))
        length = random.randint(3, min(6, cols - c_start - 1))
        for c in range(c_start, c_start + length):
            h_walls.add((r, c))

    elif ptype == 'bar_v':
        c = random.randint(1, cols - 3)
        r_start = random.randint(1, max(1, rows - 6))
        length = random.randint(3, min(5, rows - r_start - 1))
        for r in range(r_start, r_start + length):
            v_walls.add((r, c))

    elif ptype.startswith('L_'):
        if ptype == 'L_top_right':
            corner_r = random.randint(1, rows // 2)
            corner_c = random.randint(cols // 3, cols - 3)
            h_len = random.randint(2, min(5, corner_c))
            v_len = random.randint(2, min(4, rows - corner_r - 1))
            for c in range(corner_c - h_len, corner_c):
                h_walls.add((corner_r, c))
            for r in range(corner_r, corner_r + v_len):
                v_walls.add((r, corner_c))

        elif ptype == 'L_top_left':
            corner_r = random.randint(1, rows // 2)
            corner_c = random.randint(1, cols // 2)
            h_len = random.randint(2, min(5, cols - corner_c - 1))
            v_len = random.randint(2, min(4, rows - corner_r - 1))
            for c in range(corner_c, corner_c + h_len):
                h_walls.add((corner_r, c))
            for r in range(corner_r, corner_r + v_len):
                v_walls.add((r, corner_c))

        elif ptype == 'L_bottom_right':
            corner_r = random.randint(rows // 2, rows - 2)
            corner_c = random.randint(cols // 3, cols - 3)
            h_len = random.randint(2, min(5, corner_c))
            v_len = random.randint(2, min(4, corner_r))
            for c in range(corner_c - h_len, corner_c):
                h_walls.add((corner_r, c))
            for r in range(corner_r - v_len, corner_r):
                v_walls.add((r, corner_c))

        elif ptype == 'L_bottom_left':
            corner_r = random.randint(rows // 2, rows - 2)
            corner_c = random.randint(1, cols // 2)
            h_len = random.randint(2, min(5, cols - corner_c - 1))
            v_len = random.randint(2, min(4, corner_r))
            for c in range(corner_c, corner_c + h_len):
                h_walls.add((corner_r, c))
            for r in range(corner_r - v_len, corner_r):
                v_walls.add((r, corner_c))

    elif ptype == 'staircase_down':
        r = random.randint(1, max(1, rows // 3))
        c = random.randint(1, max(1, cols // 3))
        steps = random.randint(2, min(4, rows - r - 2, cols - c - 2))
        for s in range(steps):
            h_walls.add((r + s, c + s))
            if s < steps - 1:
                v_walls.add((r + s + 1, c + s))

    elif ptype == 'staircase_up':
        r = random.randint(rows // 2, rows - 3)
        c = random.randint(1, max(1, cols // 3))
        steps = random.randint(2, min(4, r, cols - c - 2))
        for s in range(steps):
            h_walls.add((r - s, c + s))
            if s < steps - 1:
                v_walls.add((r - s, c + s))

    elif ptype == 'corridor_h':
        r1 = random.randint(1, rows // 2 - 1)
        r2 = r1 + random.randint(1, 2)
        c_start = random.randint(1, max(1, cols - 6))
        length = random.randint(3, min(6, cols - c_start - 1))
        for c in range(c_start, c_start + length):
            h_walls.add((r1, c))
            h_walls.add((r2, c))

    elif ptype == 'corridor_v':
        c1 = random.randint(1, cols // 2 - 1)
        c2 = c1 + random.randint(1, 2)
        r_start = random.randint(1, max(1, rows - 5))
        length = random.randint(3, min(5, rows - r_start - 1))
        for r in range(r_start, r_start + length):
            v_walls.add((r, c1))
            v_walls.add((r, c2))

    elif ptype == 'T_shape':
        mid_r = random.randint(2, rows - 3)
        mid_c = random.randint(3, cols - 4)
        h_len = random.randint(2, min(4, cols - mid_c - 1, mid_c))
        v_len = random.randint(2, min(3, rows - mid_r - 1))
        for c in range(mid_c - h_len, mid_c + h_len + 1):
            if 0 <= c < cols:
                h_walls.add((mid_r, c))
        for r in range(mid_r, mid_r + v_len):
            v_walls.add((r, mid_c))

    h_walls = {(r, c) for r, c in h_walls if 0 <= r < rows - 1 and 0 <= c < cols}
    v_walls = {(r, c) for r, c in v_walls if 0 <= r < rows and 0 <= c < cols - 1}

    return h_walls, v_walls, ptype


def render_maze_svg(rows, cols, h_walls, v_walls, robot, paint_cells):
    """Render maze matching OGE reference style: thin grid, thick orange walls."""
    cell = 30
    pad = 8
    w = pad * 2 + cols * cell
    h = pad * 2 + rows * cell

    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="0 0 {w} {h}" '
        f'style="max-width:{min(w + 10, 450)}px;display:block;margin:10px auto;'
        f'background:#fff;border:1px solid #ddd;border-radius:4px">\n'
    )

    for r in range(rows):
        for c in range(cols):
            x = pad + c * cell
            y = pad + r * cell
            fill = '#fff'
            if (r, c) in paint_cells:
                fill = '#f5c89a'
            svg += f'<rect x="{x}" y="{y}" width="{cell}" height="{cell}" fill="{fill}" stroke="#ccc" stroke-width="0.5"/>\n'

    svg += (
        f'<rect x="{pad}" y="{pad}" width="{cols * cell}" height="{rows * cell}" '
        f'fill="none" stroke="#c67030" stroke-width="3"/>\n'
    )

    for (wr, wc) in h_walls:
        x1 = pad + wc * cell
        x2 = x1 + cell
        y = pad + (wr + 1) * cell
        svg += f'<line x1="{x1}" y1="{y}" x2="{x2}" y2="{y}" stroke="#c67030" stroke-width="3"/>\n'

    for (wr, wc) in v_walls:
        y1 = pad + wr * cell
        y2 = y1 + cell
        x = pad + (wc + 1) * cell
        svg += f'<line x1="{x}" y1="{y1}" x2="{x}" y2="{y2}" stroke="#c67030" stroke-width="3"/>\n'

    rr, rc = robot
    cx = pad + rc * cell + cell // 2
    cy = pad + rr * cell + cell // 2
    svg += (
        f'<text x="{cx}" y="{cy + 5}" text-anchor="middle" '
        f'fill="#333" font-size="14" font-weight="bold" '
        f'font-family="serif">\u0420</text>\n'
    )

    svg += '</svg>'
    return svg


def pick_robot_and_paint(rows, cols, h_walls, v_walls, ptype):
    """
    Choose robot position and painted cells based on wall pattern.
    Returns (robot, paint_cells, task_desc, algorithm).
    """
    tasks = []

    if 'bar_h' in ptype or ptype in ('L_top_right', 'L_top_left', 'corridor_h', 'T_shape'):
        if h_walls:
            wall_cols = sorted(set(c for _, c in h_walls))
            wall_row = min(r for r, c in h_walls)

            paint = set()
            for _, c in h_walls:
                if wall_row + 1 < rows:
                    paint.add((wall_row + 1, c))

            robot_r = wall_row + 1
            robot_c = wall_cols[0] if wall_cols else 1

            algo = 'закрасить\nПОКА справа свободно\n  вправо\n  закрасить'
            desc = ('закрасить все клетки, расположенные непосредственно '
                    'под горизонтальной стеной')
            tasks.append((robot_r, robot_c, paint, desc, algo))

    if 'bar_v' in ptype or ptype in ('L_bottom_right', 'L_bottom_left', 'corridor_v'):
        if v_walls:
            wall_rows = sorted(set(r for r, _ in v_walls))
            wall_col = min(c for _, c in v_walls)

            paint = set()
            for r, _ in v_walls:
                if wall_col + 1 < cols:
                    paint.add((r, wall_col + 1))

            robot_r = wall_rows[0]
            robot_c = wall_col + 1

            algo = 'закрасить\nПОКА снизу свободно\n  вниз\n  закрасить'
            desc = ('закрасить все клетки, расположенные непосредственно '
                    'справа от вертикальной стены')
            tasks.append((robot_r, robot_c, paint, desc, algo))

    if 'staircase' in ptype:
        all_wall_cells = set()
        for r, c in h_walls:
            if r + 1 < rows:
                all_wall_cells.add((r + 1, c))
        for r, c in v_walls:
            if c + 1 < cols:
                all_wall_cells.add((r, c + 1))

        paint = all_wall_cells
        if paint:
            sr = min(r for r, c in paint)
            sc = min(c for r, c in paint if r == sr)
            algo = 'закрасить\nПОКА снизу свободно\n  вниз\n  закрасить\n  вправо'
            desc = 'закрасить все клетки, примыкающие к стене снизу и справа'
            tasks.append((sr, sc, paint, desc, algo))

    if 'L_' in ptype and h_walls and v_walls:
        paint = set()
        for r, c in h_walls:
            if r + 1 < rows:
                paint.add((r + 1, c))
        for r, c in v_walls:
            if c + 1 < cols:
                paint.add((r, c + 1))

        if paint:
            sr = min(r for r, c in paint)
            sc = min(c for r, c in paint if r == sr)
            algo = ('закрасить\nПОКА справа свободно\n  вправо\n  закрасить\n'
                    'ПОКА снизу свободно\n  вниз\n  закрасить')
            desc = ('закрасить все клетки, примыкающие к стенам, '
                    'образующим угол')
            tasks.append((sr, sc, paint, desc, algo))

    if not tasks:
        paint = set()
        if h_walls:
            for r, c in h_walls:
                if r + 1 < rows:
                    paint.add((r + 1, c))
        elif v_walls:
            for r, c in v_walls:
                if c + 1 < cols:
                    paint.add((r, c + 1))

        if not paint:
            paint = {(rows // 2, cols // 2)}

        sr = min(r for r, c in paint)
        sc = min(c for r, c in paint if r == sr)
        algo = 'закрасить\nПОКА справа свободно\n  вправо\n  закрасить'
        desc = 'закрасить указанные клетки'
        tasks.append((sr, sc, paint, desc, algo))

    return random.choice(tasks)


def gen_task15(count=200):
    results = []

    for i in range(count):
        diff = DIFFS[i % 200]

        if diff == 'easy':
            rows, cols = random.choice([(6, 8), (7, 8)])
        elif diff == 'medium':
            rows, cols = random.choice([(7, 9), (8, 9)])
        else:
            rows, cols = random.choice([(8, 10), (9, 10)])

        h_walls, v_walls, ptype = gen_wall_pattern(rows, cols, diff)

        if not h_walls and not v_walls:
            h_walls.add((rows // 3, cols // 3))
            h_walls.add((rows // 3, cols // 3 + 1))
            h_walls.add((rows // 3, cols // 3 + 2))

        robot_r, robot_c, paint, desc, algo = pick_robot_and_paint(
            rows, cols, h_walls, v_walls, ptype
        )

        paint.discard((robot_r, robot_c))

        if robot_r < 0 or robot_r >= rows:
            robot_r = max(0, min(rows - 1, robot_r))
        if robot_c < 0 or robot_c >= cols:
            robot_c = max(0, min(cols - 1, robot_c))

        maze_svg = render_maze_svg(rows, cols, h_walls, v_walls, (robot_r, robot_c), paint)

        content = (
            f'{ROBOT_TEXT}'
            f'{maze_svg}'
            f'<p>На рисунке изображён лабиринт. Робот находится в клетке, '
            f'отмеченной буквой <b>\u0420</b>. Серым цветом выделены клетки, '
            f'которые необходимо закрасить.</p>'
            f'<p>Напишите для Робота алгоритм, закрашивающий указанные клетки. '
            f'Алгоритм должен решать задачу для произвольного размера поля '
            f'и любого допустимого расположения стен внутри прямоугольного поля.</p>'
        )

        algo_pre = algo.replace('\n', '<br>')
        solution = (
            f'<p><b>Решение:</b></p>'
            f'<pre style="background:#1a1d27;color:#e4e6f0;padding:12px;'
            f'border-radius:8px;font-size:14px">{algo_pre}</pre>'
            f'<p>Робот последовательно двигается вдоль стены, '
            f'закрашивая каждую клетку на своём пути.</p>'
        )

        results.append(make_task(15, content, '', solution, diff))

    return results


# ════════════════════════════════════════════════════════════════════════
# MAIN
# ════════════════════════════════════════════════════════════════════════

max_id = max(t['site_id'] for t in all_tasks) + 1

print("Generating task 9...")
tasks_9 = gen_task9(200)
print(f"  Generated: {len(tasks_9)}")
answers_9 = [int(t['answer']) for t in tasks_9]
print(f"  Answer range: {min(answers_9)}-{max(answers_9)}, avg={sum(answers_9)/len(answers_9):.1f}")

print("Generating task 15...")
tasks_15 = gen_task15(200)
print(f"  Generated: {len(tasks_15)}")

for t in tasks_9 + tasks_15:
    t['site_id'] = max_id
    max_id += 1

all_tasks.extend(tasks_9)
all_tasks.extend(tasks_15)

with open(DATA_FILE, 'w', encoding='utf-8') as f:
    json.dump(all_tasks, f, ensure_ascii=False, indent=2)

print(f"\nTotal tasks: {len(all_tasks)}")
by_tn = {}
for t in all_tasks:
    n = t['task_number']
    by_tn[n] = by_tn.get(n, 0) + 1
for n in sorted(by_tn):
    print(f"  #{n}: {by_tn[n]}")
