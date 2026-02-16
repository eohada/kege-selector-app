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
        try:
            import cv2
            import numpy as np
        except ImportError:
            return None
        if self.reader is None:
            return None

        if isinstance(image_input, bytes):
            arr = np.frombuffer(image_input, np.uint8)
            img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        else:
            img = cv2.imread(image_input)
        if img is None:
            return None

        height, width = img.shape[:2]
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        _, binary = cv2.threshold(gray, 180, 255, cv2.THRESH_BINARY_INV)

        nodes = self._find_nodes(binary)
        if not nodes:
            return None
        labeled_nodes = self._label_nodes(img, nodes)
        adjacency_list = self._find_edges(binary, labeled_nodes)
        for key in adjacency_list:
            adjacency_list[key].sort()
        return adjacency_list

    def _find_nodes(self, binary_img) -> list[dict[str, Any]]:
        import cv2
        import math
        contours, _ = cv2.findContours(binary_img, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        nodes = []
        for cnt in contours:
            area = cv2.contourArea(cnt)
            if 30 < area < 1000:
                M = cv2.moments(cnt)
                if M["m00"] != 0:
                    cX = int(M["m10"] / M["m00"])
                    cY = int(M["m01"] / M["m00"])
                    perimeter = cv2.arcLength(cnt, True)
                    if perimeter > 0:
                        circularity = 4 * math.pi * (area / (perimeter * perimeter))
                        if circularity > 0.5:
                            nodes.append({'center': (cX, cY), 'radius': max(2, int(math.sqrt(area / math.pi)))})
        return nodes

    def _label_nodes(self, original_img, nodes: list) -> list[dict[str, Any]]:
        import cv2
        labeled = []
        h, w = original_img.shape[:2]
        for node in nodes:
            x, y = node['center']
            r = node['radius']
            offset = 50
            y1, y2 = max(0, y - offset), min(h, y + offset)
            x1, x2 = max(0, x - offset), min(w, x + offset)
            roi = original_img[y1:y2, x1:x2]
            label = "?"
            if roi.size > 0:
                result = self.reader.readtext(roi, allowlist='АБВГДЕЖЗИКЛМНОПРСТУФХЦЧШЩЭЮЯA-Z')
                if result:
                    best = max(result, key=lambda x: x[2])
                    label = (best[1] or '?').strip().upper()
                    if len(label) > 1:
                        label = label[0]
            labeled.append({'label': label, 'center': (x, y), 'radius': r})
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
        line_mask = np.zeros_like(binary_img)
        cv2.line(line_mask, p1, p2, 255, 2)
        cv2.circle(line_mask, p1, node_a['radius'] + 5, 0, -1)
        cv2.circle(line_mask, p2, node_b['radius'] + 5, 0, -1)
        intersection = cv2.bitwise_and(binary_img, line_mask)
        line_pixels = cv2.countNonZero(line_mask)
        match_pixels = cv2.countNonZero(intersection)
        if line_pixels == 0:
            return False
        return (match_pixels / line_pixels) > 0.6


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
