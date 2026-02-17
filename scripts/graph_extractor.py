#!/usr/bin/env python3
"""
Извлечение графа из изображения задания ЕГЭ №1.
Превращает картинку графа (правая часть) в словарь смежности.
"""
from __future__ import annotations

import math
from typing import Any


class GraphExtractor:
    """Извлекает граф (вершины + рёбра) из изображения. OCR меток — только в ROI вокруг каждой вершины."""

    def __init__(self, gpu: bool = False):
        try:
            import easyocr
            self.reader = easyocr.Reader(['ru', 'en'], gpu=gpu, verbose=False)
        except Exception:
            self.reader = None

    def process_image(self, image_input: str | bytes) -> dict[str, list[str]] | None:
        """
        image_input: путь к файлу или bytes изображения.
        Возвращает словарь смежности {'А': ['Б', 'Г'], 'Б': ['А', 'В'], ...} или None при ошибке.
        """
        result, _ = self.process_image_with_debug(image_input)
        return result

    def process_image_with_debug(self, image_input: str | bytes) -> tuple[dict[str, list[str]] | None, dict | None]:
        """
        То же что process_image, но возвращает (result, debug_info).
        debug_info: nodes_count, labeled, edges_checked и т.д.
        """
        try:
            import cv2
            import numpy as np
        except ImportError:
            return None, None
        if self.reader is None:
            return None, None

        if isinstance(image_input, bytes):
            arr = np.frombuffer(image_input, np.uint8)
            img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        else:
            img = cv2.imread(image_input)
        if img is None:
            return None, {'error': 'failed to load image'}

        height, width = img.shape[:2]
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        mean_val = np.mean(gray)
        self._dark_bg = mean_val < 128
        if self._dark_bg:
            _, binary = cv2.threshold(gray, 100, 255, cv2.THRESH_BINARY)
        else:
            _, binary = cv2.threshold(gray, 180, 255, cv2.THRESH_BINARY_INV)
        kernel = np.ones((2, 2), np.uint8)
        binary = cv2.dilate(binary, kernel)

        nodes = self._find_nodes(binary)
        debug = {'img_size': [width, height], 'nodes_count': len(nodes), 'nodes': [{'center': n['center'], 'radius': n['radius']} for n in nodes]}
        if not nodes:
            return None, debug

        labeled_nodes = self._label_nodes(img, nodes)
        debug['labeled'] = [{'label': n['label'], 'center': n['center']} for n in labeled_nodes]
        adjacency_list = self._find_edges(binary, labeled_nodes, gray_img=gray)
        for key in adjacency_list:
            adjacency_list[key].sort()
        debug['adjacency_keys'] = list(adjacency_list.keys())
        return adjacency_list, debug

    def _find_nodes(self, binary_img) -> list[dict[str, Any]]:
        """Вершины — круги. Граф связный, поэтому findContours даёт один контур. Используем HoughCircles."""
        import cv2
        import math
        import numpy as np
        h, w = binary_img.shape[:2]
        nodes = []
        min_r, max_r = 3, min(40, min(w, h) // 6)
        circles = None
        for param2 in (25, 18, 12):
            c = cv2.HoughCircles(
                binary_img, cv2.HOUGH_GRADIENT, dp=1, minDist=max(12, min_r * 3),
                param1=60, param2=param2, minRadius=min_r, maxRadius=max_r
            )
            if c is not None and len(c[0]) >= 6:
                circles = c
                break
            circles = c
        if circles is not None:
            raw = [(int(c[0]), int(c[1]), max(2, int(c[2]))) for c in circles[0]]
            raw = [t for t in raw if t[2] <= 25]
            raw.sort(key=lambda t: -t[2])
            for x, y, r in raw:
                if any(math.hypot(x - n['center'][0], y - n['center'][1]) < max(r, n['radius']) * 1.2 for n in nodes):
                    continue
                nodes.append({'center': (x, y), 'radius': r})
            if len(nodes) > 8:
                chosen, pool = [nodes[0]], nodes[1:]
                while len(chosen) < 8 and pool:
                    def min_dist(p):
                        return min((p['center'][0]-c['center'][0])**2 + (p['center'][1]-c['center'][1])**2 for c in chosen)
                    i = np.argmax([min_dist(p) for p in pool])
                    chosen.append(pool.pop(i))
                nodes = chosen[:8]
        if not nodes:
            contours, _ = cv2.findContours(binary_img, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            for cnt in contours:
                area = cv2.contourArea(cnt)
                if 8 < area < 1500:
                    M = cv2.moments(cnt)
                    if M["m00"] != 0:
                        cX = int(M["m10"] / M["m00"])
                        cY = int(M["m01"] / M["m00"])
                        perimeter = cv2.arcLength(cnt, True)
                        if perimeter > 0:
                            circularity = 4 * math.pi * (area / (perimeter * perimeter))
                            if circularity > 0.35:
                                nodes.append({'center': (cX, cY), 'radius': max(2, int(math.sqrt(area / math.pi)))})
        return nodes

    def _label_nodes(self, original_img, nodes: list) -> list[dict[str, Any]]:
        import cv2
        latin_labels = 'ABCDEFGH'
        # В заданиях №1 обычно метки из ограниченного набора (кириллица)
        target_cyr = 'АБВГДЕЖК'
        cyrillic_labels = 'АБВГДЕЖЗИКЛМНОПРСТУФХЦЧШЩ'

        def normalize_to_cyr(ch: str) -> str:
            """Убираем смешение алфавитов: маппим латиницу-двойника в кириллицу, если возможно."""
            m = {
                'A': 'А',
                'B': 'В',
                'C': 'С',
                'E': 'Е',
                'K': 'К',
                'M': 'М',
                'H': 'Н',
                'O': 'О',
                'P': 'Р',
                'T': 'Т',
                'X': 'Х',
                'Y': 'У',
                'G': 'Г',
                'D': 'Д',
            }
            return m.get(ch, ch)
        labeled = []
        h, w = original_img.shape[:2]
        for node in nodes:
            x, y = node['center']
            r = node['radius']
            offset = 55
            y1, y2 = max(0, y - offset), min(h, y + offset)
            x1, x2 = max(0, x - offset), min(w, x + offset)
            roi = original_img[y1:y2, x1:x2]
            label = "?"
            if roi.size > 0:
                # СНАЧАЛА кириллица (иначе EasyOCR часто отдаёт латиницу A/B/E/K)
                for allowlist in (target_cyr, cyrillic_labels + 'ЭЮЯ', latin_labels):
                    result = self.reader.readtext(roi, allowlist=allowlist)
                    if result:
                        best = max(result, key=lambda x: x[2])
                        raw = (best[1] or '?').strip().upper()
                        if len(raw) > 1:
                            raw = raw[0]
                        if not raw or raw == '?':
                            continue
                        raw = normalize_to_cyr(raw)
                        if raw in target_cyr:
                            label = raw
                            break
                        if raw in cyrillic_labels:
                            label = raw
                            break
            labeled.append({'label': label, 'center': (x, y), 'radius': r})
        used = {n['label'] for n in labeled if n['label'] != '?'}
        # Если нашли хоть одну кириллическую метку — считаем, что весь граф кириллицей
        fallback = target_cyr if any(n['label'] in cyrillic_labels for n in labeled) else latin_labels
        for n in labeled:
            if n['label'] == '?':
                for c in fallback:
                    if c not in used:
                        n['label'] = c
                        used.add(c)
                        break
        labeled.sort(key=lambda n: (n['center'][1], n['center'][0]))
        return labeled

    def _find_edges(self, binary_img, labeled_nodes: list, gray_img=None) -> dict[str, list[str]]:
        import cv2
        import numpy as np
        adj = {n['label']: [] for n in labeled_nodes if n['label'] not in ('?', 'Unknown')}

        # 1) Строим карту рёбер (лучше работает, чем порог по gray для тонких линий)
        if gray_img is not None:
            g = gray_img
            if getattr(self, '_dark_bg', False):
                g = cv2.bitwise_not(g)
            g = cv2.GaussianBlur(g, (3, 3), 0)
            edges_only = cv2.Canny(g, 40, 120)
            edges_only = cv2.dilate(edges_only, np.ones((3, 3), np.uint8), iterations=1)
        else:
            kernel = np.ones((3, 3), np.uint8)
            fat = cv2.dilate(binary_img, kernel, iterations=2)
            edges_only = fat.copy()

        # 2) Удаляем сами вершины (кружки) и небольшую окрестность
        for node in labeled_nodes:
            cx, cy = node['center']
            r = int(node.get('radius', 15))
            cv2.circle(edges_only, (int(cx), int(cy)), r + 8, 0, -1)

        # 3) Детект сегментов рёбер (HoughLinesP)
        h, w = edges_only.shape[:2]
        min_len = max(18, min(h, w) // 16)
        max_gap = max(12, min(h, w) // 40)
        lines = cv2.HoughLinesP(
            edges_only,
            rho=1,
            theta=np.pi / 180,
            threshold=25,
            minLineLength=min_len,
            maxLineGap=max_gap,
        )

        # 4) Маппим концы сегментов к ближайшим вершинам
        def nearest_node(pt):
            x, y = int(pt[0]), int(pt[1])
            best = None
            best_d2 = None
            for n in labeled_nodes:
                cx, cy = n['center']
                dx, dy = x - int(cx), y - int(cy)
                d2 = dx * dx + dy * dy
                r = int(n.get('radius', 15))
                lim = (r + 28) * (r + 28)
                if d2 <= lim and (best_d2 is None or d2 < best_d2):
                    best = n
                    best_d2 = d2
            return best

        votes: dict[tuple[str, str], int] = {}
        if lines is not None:
            for ln in lines:
                x1, y1, x2, y2 = ln[0]
                n1 = nearest_node((x1, y1))
                n2 = nearest_node((x2, y2))
                if not n1 or not n2:
                    continue
                a, b = n1['label'], n2['label']
                if a in ('?', 'Unknown') or b in ('?', 'Unknown') or a == b:
                    continue
                key = tuple(sorted((a, b)))
                votes[key] = votes.get(key, 0) + 1

        # 5) Если Hough ничего не дал — fallback на попарную «толстую линию»
        edges = set()
        # Подтверждаем рёбра: либо есть голосование, либо fallback
        for (a, b), v in votes.items():
            if v < 2:
                continue
            na = next((n for n in labeled_nodes if n['label'] == a), None)
            nb = next((n for n in labeled_nodes if n['label'] == b), None)
            if not na or not nb:
                continue
            # Валидируем пересечением с "толстой линией"
            if self._check_connection_robust(edges_only, na, nb):
                edges.add((a, b))

        if not edges:
            for i in range(len(labeled_nodes)):
                for j in range(i + 1, len(labeled_nodes)):
                    a, b = labeled_nodes[i], labeled_nodes[j]
                    if a['label'] in ('?', 'Unknown') or b['label'] in ('?', 'Unknown'):
                        continue
                    if self._check_connection_robust(edges_only, a, b):
                        edges.add(tuple(sorted((a['label'], b['label']))))

        for a, b in edges:
            adj.setdefault(a, []).append(b)
            adj.setdefault(b, []).append(a)
        return adj

    def _check_connection_robust(self, edges_img, node_a: dict, node_b: dict) -> bool:
        import cv2
        import numpy as np
        p1 = tuple(int(x) for x in node_a['center'])
        p2 = tuple(int(x) for x in node_b['center'])
        line_mask = np.zeros_like(edges_img)
        cv2.line(line_mask, p1, p2, 255, 3)
        intersection = cv2.bitwise_and(edges_img, line_mask)
        line_pixels = cv2.countNonZero(line_mask)
        match_pixels = cv2.countNonZero(intersection)
        if line_pixels == 0:
            return False
        return (match_pixels / line_pixels) > 0.45

    def _check_connection(self, binary_img, node_a: dict, node_b: dict) -> bool:
        import cv2
        import numpy as np
        p1, p2 = node_a['center'], node_b['center']
        dist = np.hypot(p2[0] - p1[0], p2[1] - p1[1])
        if dist < 5:
            return False
        line_mask = np.zeros_like(binary_img)
        cv2.line(line_mask, p1, p2, 255, 3)
        cv2.circle(line_mask, p1, max(3, node_a['radius'] + 1), 0, -1)
        cv2.circle(line_mask, p2, max(3, node_b['radius'] + 1), 0, -1)
        intersection = cv2.bitwise_and(binary_img, line_mask)
        line_pixels = cv2.countNonZero(line_mask)
        match_pixels = cv2.countNonZero(intersection)
        if line_pixels == 0:
            return False
        thresh = 0.25 if getattr(self, '_dark_bg', False) else 0.4
        return (match_pixels / line_pixels) > thresh


def split_table_and_graph(image_input: str | bytes) -> tuple[bytes | None, bytes | None]:
    """
    Режет изображение пополам: левая часть — таблица, правая — граф.
    Возвращает (table_bytes, graph_bytes) или (None, None).
    """
    try:
        import cv2
        import numpy as np
    except ImportError:
        return None, None
    if isinstance(image_input, bytes):
        arr = np.frombuffer(image_input, np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    else:
        img = cv2.imread(image_input)
    if img is None:
        return None, None
    h, w = img.shape[:2]
    mid = w // 2
    left = img[:, :mid]
    right = img[:, mid:]
    _, left_buf = cv2.imencode('.png', left)
    _, right_buf = cv2.imencode('.png', right)
    return left_buf.tobytes(), right_buf.tobytes()
