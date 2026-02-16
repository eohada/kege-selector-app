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

    def _extract_by_grid(self, img) -> dict[str, Any] | None:
        """Делим изображение на сетку NxN, OCR каждой ячейки."""
        import cv2
        import numpy as np
        h, w = img.shape[:2]
        for n in (8, 7, 6):
            cell_h, cell_w = h // n, w // n
            if cell_h < 15 or cell_w < 15:
                continue
            matrix = []
            for i in range(n):
                row = []
                for j in range(n):
                    y1, y2 = i * cell_h, min((i + 1) * cell_h, h)
                    x1, x2 = j * cell_w, min((j + 1) * cell_w, w)
                    roi = img[y1:y2, x1:x2]
                    if roi.size == 0:
                        row.append(None)
                        continue
                    result = self.reader.readtext(roi, allowlist='0123456789*')
                    val = None
                    if result:
                        best = max(result, key=lambda r: r[2])
                        txt = (best[1] or '').strip()
                        m = re.match(r'(\d+)', txt)
                        if m:
                            val = int(m.group(1))
                    row.append(val)
                matrix.append(row)
            if any(v is not None for row in matrix for v in row):
                return {'matrix': matrix, 'size': n}
        return self._fallback_full_ocr(img)

    def _fallback_full_ocr(self, img) -> dict[str, Any] | None:
        """Fallback: OCR всего изображения, попытка вытащить числа."""
        import numpy as np
        result = self.reader.readtext(np.array(img))
        numbers = []
        for (_, txt, _) in result:
            for m in re.finditer(r'\d+', txt):
                numbers.append(int(m.group()))
        if len(numbers) >= 16:
            n = 8
            matrix = []
            for i in range(n):
                row = []
                for j in range(n):
                    idx = i * n + j
                    row.append(numbers[idx] if idx < len(numbers) else None)
                matrix.append(row)
            return {'matrix': matrix, 'size': n}
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
