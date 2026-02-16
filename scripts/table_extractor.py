#!/usr/bin/env python3
"""
Извлечение таблицы (матрица смежности с длинами дорог) из левой части изображения задания ЕГЭ №1.
"""
from __future__ import annotations

import re
from typing import Any


class TableExtractor:
    """Извлекает матрицу чисел из изображения таблицы."""

    def __init__(self, gpu: bool = False):
        try:
            import easyocr
            self.reader = easyocr.Reader(['ru', 'en'], gpu=gpu, verbose=False)
        except Exception:
            self.reader = None

    def process_image(self, image_input: str | bytes) -> dict[str, Any] | None:
        """
        Возвращает {'matrix': [[...], ...], 'size': N} или None.
        matrix[i][j] — число или None (нет связи). Индексы 0..N-1 соответствуют пунктам 1..N.
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

        return self._extract_by_grid(img)

    def _normalize_ocr_number(self, num: int) -> int | None:
        """Исправление типичных OCR-ошибок: 154→34, 113→13, 111→11, 115→15, 123→23."""
        if 1 <= num <= 99:
            return num
        if 100 <= num <= 199:
            tail = num % 100
            if 10 <= tail <= 99 or tail in (1, 2, 3, 4, 5, 6, 7, 8, 9):
                return tail
        return num if 1 <= num <= 999 else None

    def _extract_by_grid(self, img) -> dict[str, Any] | None:
        """Делим изображение на сетку 8x8. * = связь, числа = длина."""
        import cv2
        import numpy as np
        h, w = img.shape[:2]
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if len(img.shape) == 3 else img
        if np.mean(gray) < 140:
            img = cv2.bitwise_not(img)
        best_matrix, best_count = None, 0
        for header_ratio in (0.10, 0.12, 0.15, 0.18, 0.20, 0.22, 0.25):
            header_h = int(h * header_ratio)
            header_w = int(w * header_ratio)
            data_h, data_w = h - header_h, w - header_w
            cell_h, cell_w = data_h // 8, data_w // 8
            if cell_h < 8 or cell_w < 8:
                continue
            matrix = []
            for i in range(8):
                row = []
                for j in range(8):
                    y1 = header_h + i * cell_h
                    y2 = header_h + (i + 1) * cell_h
                    x1 = header_w + j * cell_w
                    x2 = header_w + (j + 1) * cell_w
                    roi = img[y1:y2, x1:x2]
                    if roi.size == 0:
                        row.append(None)
                        continue
                    val = None
                    if self.reader:
                        result = self.reader.readtext(roi, allowlist='*0123456789')
                        if result:
                            for _, txt, _ in sorted(result, key=lambda x: -x[2]):
                                s = (txt or '').strip()
                                if '*' in s:
                                    val = 1
                                    break
                                m = re.match(r'^(\d+)$', s)
                                if m:
                                    raw_num = int(m.group(1))
                                    val = self._normalize_ocr_number(raw_num)
                                    if val:
                                        break
                    row.append(val)
                matrix.append(row)
            count = sum(1 for row in matrix for v in row if v is not None)
            if count > best_count:
                best_count = count
                best_matrix = matrix
        if best_matrix and best_count > 0:
            return {'matrix': best_matrix, 'size': 8}
        return self._fallback_full_ocr(img)

    def _fallback_full_ocr(self, img) -> dict[str, Any] | None:
        """Fallback: OCR всего изображения. * по bbox или числа по порядку."""
        import numpy as np
        import cv2
        h, w = img.shape[:2]
        ocr_img = img
        if len(img.shape) == 3:
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            if np.mean(gray) < 128:
                ocr_img = cv2.bitwise_not(img)
        result = self.reader.readtext(np.array(ocr_img), allowlist='*0123456789 ')
        matrix = [[None] * 8 for _ in range(8)]
        header_h, header_w = int(h * 0.2), int(w * 0.2)
        data_h, data_w = h - header_h, w - header_w
        for bbox, txt, _ in result:
            s = (txt or '').strip()
            pts = np.array(bbox, dtype=np.int32)
            cx = int(pts[:, 0].mean())
            cy = int(pts[:, 1].mean())
            if cy < header_h or cx < header_w:
                continue
            rel_y, rel_x = (cy - header_h) / data_h, (cx - header_w) / data_w
            if not (0 <= rel_y < 1 and 0 <= rel_x < 1):
                continue
            row_idx, col_idx = min(7, int(rel_y * 8)), min(7, int(rel_x * 8))
            if '*' in s:
                matrix[row_idx][col_idx] = 1
            else:
                m = re.match(r'(\d+)', s)
                if m:
                    num = self._normalize_ocr_number(int(m.group(1)))
                    if num:
                        matrix[row_idx][col_idx] = num
        if any(v is not None for row in matrix for v in row):
            return {'matrix': matrix, 'size': 8}
        numbers = []
        for _, txt, _ in self.reader.readtext(np.array(ocr_img)):
            for m in re.finditer(r'\d+', txt or ''):
                v = self._normalize_ocr_number(int(m.group()))
                if v:
                    numbers.append(v)
        if len(numbers) >= 16:
            matrix = [[None] * 8 for _ in range(8)]
            for i in range(8):
                for j in range(8):
                    idx = i * 8 + j
                    if idx < len(numbers):
                        matrix[i][j] = numbers[idx]
            return {'matrix': matrix, 'size': 8}
        return None


def table_to_adjacency_dict(data: dict) -> dict[str, list[tuple[str, int]]]:
    """
    Превращает matrix в словарь: пункт_i -> [(пункт_j, длина), ...].
    data['matrix'] — матрица, где matrix[i][j] = длина или None.
    """
    matrix = data.get('matrix') or []
    if not matrix:
        return {}
    result = {}
    n = len(matrix)
    for i in range(n):
        result[str(i + 1)] = []
        for j in range(n):
            if i != j and matrix[i][j] is not None:
                result[str(i + 1)].append((str(j + 1), matrix[i][j]))
    return result
