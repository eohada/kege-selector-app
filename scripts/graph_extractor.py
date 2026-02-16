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
        _, binary = cv2.threshold(gray, 180, 255, cv2.THRESH_BINARY_INV)
        kernel = np.ones((2, 2), np.uint8)
        binary = cv2.dilate(binary, kernel)

        nodes = self._find_nodes(binary)
        debug = {'img_size': [width, height], 'nodes_count': len(nodes), 'nodes': [{'center': n['center'], 'radius': n['radius']} for n in nodes]}
        if not nodes:
            return None, debug

        labeled_nodes = self._label_nodes(img, nodes)
        debug['labeled'] = [{'label': n['label'], 'center': n['center']} for n in labeled_nodes]
        adjacency_list = self._find_edges(binary, labeled_nodes)
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
        fallback_labels = 'АБВГДЕЖЗИКЛМНОПРСТУФХЦЧШЩ'
        labeled = []
        h, w = original_img.shape[:2]
        for node in nodes:
            x, y = node['center']
            r = node['radius']
            offset = 60
            y1, y2 = max(0, y - offset), min(h, y + offset)
            x1, x2 = max(0, x - offset), min(w, x + offset)
            roi = original_img[y1:y2, x1:x2]
            label = "?"
            if roi.size > 0:
                result = self.reader.readtext(roi, allowlist='АБВГДЕЖЗИКЛМНОПРСТУФХЦЧШЩЭЮЯA-Z')
                if result:
                    best = max(result, key=lambda x: x[2])
                    raw = (best[1] or '?').strip().upper()
                    if len(raw) > 1:
                        raw = raw[0]
                    if raw and raw in fallback_labels + 'AO':
                        label = 'А' if raw == 'A' else ('О' if raw == 'O' else raw)
            labeled.append({'label': label, 'center': (x, y), 'radius': r})
        used = {n['label'] for n in labeled if n['label'] != '?'}
        for i, n in enumerate(labeled):
            if n['label'] == '?':
                for c in fallback_labels:
                    if c not in used:
                        n['label'] = c
                        used.add(c)
                        break
        labeled.sort(key=lambda n: (n['center'][1], n['center'][0]))
        return labeled

    def _find_edges(self, binary_img, labeled_nodes: list) -> dict[str, list[str]]:
        import cv2
        import numpy as np
        adj = {n['label']: [] for n in labeled_nodes if n['label'] != '?' and n['label'] != 'Unknown'}
        for i in range(len(labeled_nodes)):
            for j in range(i + 1, len(labeled_nodes)):
                a, b = labeled_nodes[i], labeled_nodes[j]
                if a['label'] in ('?', 'Unknown') or b['label'] in ('?', 'Unknown'):
                    continue
                if self._check_connection(binary_img, a, b):
                    adj.setdefault(a['label'], []).append(b['label'])
                    adj.setdefault(b['label'], []).append(a['label'])
        return adj

    def _check_connection(self, binary_img, node_a: dict, node_b: dict) -> bool:
        import cv2
        import numpy as np
        p1, p2 = node_a['center'], node_b['center']
        dist = np.hypot(p2[0] - p1[0], p2[1] - p1[1])
        if dist < 5:
            return False
        line_mask = np.zeros_like(binary_img)
        cv2.line(line_mask, p1, p2, 255, 7)
        cv2.circle(line_mask, p1, max(2, node_a['radius']), 0, -1)
        cv2.circle(line_mask, p2, max(2, node_b['radius']), 0, -1)
        intersection = cv2.bitwise_and(binary_img, line_mask)
        line_pixels = cv2.countNonZero(line_mask)
        match_pixels = cv2.countNonZero(intersection)
        if line_pixels == 0:
            return False
        return (match_pixels / line_pixels) > 0.35


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
