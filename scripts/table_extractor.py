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

    def _cell_content_ratio(self, cell_img) -> float:
        """Оценка «заполненности» ячейки: доля тёмных пикселей внутри (после обрезки краёв)."""
        import cv2
        h, w = cell_img.shape[:2]
        crop_margin = max(4, min(h, w) // 8)
        if h <= crop_margin * 2 or w <= crop_margin * 2:
            return 0.0
        roi = cell_img[crop_margin:h - crop_margin, crop_margin:w - crop_margin]
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY) if len(roi.shape) == 3 else roi
        _, thresh = cv2.threshold(gray, 128, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)
        non_zero = cv2.countNonZero(thresh)
        total = int(thresh.size) if thresh is not None else 0
        return (non_zero / total) if total > 0 else 0.0

    def _detect_star(self, cell_img) -> bool:
        """Детект '*' без OCR: по крупнейшей компоненте (устойчиво к шуму/сетке при нормальном кропе)."""
        import cv2
        h, w = cell_img.shape[:2]
        if h < 10 or w < 10:
            return False
        crop_margin = max(3, min(h, w) // 8)
        if h <= crop_margin * 2 or w <= crop_margin * 2:
            return False
        roi = cell_img[crop_margin:h - crop_margin, crop_margin:w - crop_margin]
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY) if len(roi.shape) == 3 else roi
        # Инверсия: контент белый
        bin_img = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)[1]
        # Убираем линии сетки внутри клетки (горизонтальные/вертикальные)
        hh, ww = bin_img.shape[:2]
        hk = max(10, ww // 2)
        vk = max(10, hh // 2)
        horiz = cv2.morphologyEx(bin_img, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (hk, 1)), iterations=1)
        vert = cv2.morphologyEx(bin_img, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, vk)), iterations=1)
        lines = cv2.bitwise_or(horiz, vert)
        clean = cv2.bitwise_and(bin_img, cv2.bitwise_not(lines))
        # Чуть соединяем штрихи '*' (звёздочка тонкая), затем убираем мелкий мусор
        clean = cv2.morphologyEx(clean, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2)), iterations=1)
        clean = cv2.morphologyEx(clean, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2)), iterations=1)
        # Ключевая метрика: доля пикселей после удаления линий.
        filled = cv2.countNonZero(clean)
        total = int(clean.size) if clean is not None else 0
        if total <= 0:
            return False
        ratio = filled / float(total)
        # На "чистых" таблицах: пусто ~0.0–0.005, '*' обычно >=0.02
        return 0.015 <= ratio <= 0.25

    def _analyze_cell(self, cell_img, is_binary_matrix: bool, row_idx: int = -1, col_idx: int = -1) -> int | None:
        """Звёздочки — по плотности пикселей (используется как фоллбек). Числа — OCR с padding."""
        import cv2
        if is_binary_matrix:
            return 1 if self._detect_star(cell_img) else None
        h, w = cell_img.shape[:2]
        crop_margin = max(4, min(h, w) // 8)
        if h <= crop_margin * 2 or w <= crop_margin * 2:
            return None
        roi = cell_img[crop_margin:h - crop_margin, crop_margin:w - crop_margin]
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY) if len(roi.shape) == 3 else roi
        _, thresh = cv2.threshold(gray, 128, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)
        if cv2.countNonZero(thresh) < 5:
            return None
        if not self.reader:
            return None
        padded = cv2.copyMakeBorder(thresh, 10, 10, 10, 10, cv2.BORDER_CONSTANT, value=0)
        final_img = cv2.bitwise_not(padded)
        res = self.reader.readtext(final_img, allowlist='0123456789', detail=0)
        if res:
            numbers = [int(x) for x in res if x.isdigit()]
            if numbers:
                val = max(numbers)
                return self._normalize_ocr_number(val) if val <= 999 else 11
        return None

    def _extract_by_grid(self, img) -> dict[str, Any] | None:
        """Извлекаем 8x8 матрицу из таблицы. Основной путь: находим сетку и режем по линиям."""
        import cv2
        import numpy as np
        h, w = img.shape[:2]
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if len(img.shape) == 3 else img
        if np.mean(gray) < 140:
            img = cv2.bitwise_not(img)

        # 1) Находим границы самой сетки (контур с максимальной площадью)
        bin_full = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)[1]
        bin_full = cv2.morphologyEx(bin_full, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8), iterations=2)
        contours, _ = cv2.findContours(bin_full, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return self._fallback_full_ocr(img)
        cnt = max(contours, key=cv2.contourArea)
        x, y, ww, hh = cv2.boundingRect(cnt)
        if ww < 100 or hh < 100:
            return self._fallback_full_ocr(img)
        pad = max(2, min(10, min(ww, hh) // 50))
        x1, y1 = max(0, x - pad), max(0, y - pad)
        x2, y2 = min(w, x + ww + pad), min(h, y + hh + pad)
        grid = img[y1:y2, x1:x2]

        gh, gw = grid.shape[:2]
        if gh < 120 or gw < 120:
            return self._fallback_full_ocr(img)

        # 2) Ищем линии сетки по проекциям.
        # В типовом задании: слева 2 служебных столбца (заголовок + номера строк) + 8 данных => 10 столбцов => 11 линий.
        # Сверху 2 служебных строки (заголовок + номера столбцов) + 8 данных => 10 строк => 11 линий.
        grid_gray = cv2.cvtColor(grid, cv2.COLOR_BGR2GRAY) if len(grid.shape) == 3 else grid
        grid_bin = cv2.threshold(grid_gray, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)[1]

        def pick_lines_1d(proj: np.ndarray, expected: int) -> list[int]:
            """Ищем центры линий как группы подряд идущих «сильных» колонок/строк."""
            p = proj.astype(np.float32)
            if p.size < 20:
                return []
            pmax = float(p.max()) if p.size else 0.0
            if pmax <= 0:
                return []
            thr = pmax * 0.55
            strong = p >= thr
            centers: list[int] = []
            start = None
            for i, v in enumerate(strong):
                if v and start is None:
                    start = i
                elif (not v) and start is not None:
                    end = i - 1
                    if end - start + 1 >= 2:
                        centers.append((start + end) // 2)
                    start = None
            if start is not None:
                end = len(strong) - 1
                if end - start + 1 >= 2:
                    centers.append((start + end) // 2)
            # Если нашли слишком много (текст/шум), берём самые равномерные 10: крайние + ближайшие к равномерной сетке
            centers = sorted(set(int(c) for c in centers))
            if len(centers) < expected:
                return []
            if len(centers) == expected:
                return centers
            # уменьшаем до expected, подбирая ближайшие к равномерным целям без повторов
            if expected >= 2:
                left, right = centers[0], centers[-1]
                if right <= left:
                    return []
                targets = [left + (i * (right - left) / (expected - 1)) for i in range(expected)]
                chosen: list[int] = []
                used = set()
                for t in targets:
                    # сортируем по близости к target
                    cand = sorted(((abs(c - t), c) for c in centers if c not in used), key=lambda x: x[0])
                    if not cand:
                        break
                    c = int(cand[0][1])
                    chosen.append(c)
                    used.add(c)
                chosen.sort()
                if len(chosen) == expected:
                    return chosen
            return []

        col_proj = grid_bin.sum(axis=0)
        row_proj = grid_bin.sum(axis=1)
        xs = pick_lines_1d(col_proj, expected=11)
        ys = pick_lines_1d(row_proj, expected=11)
        # fallback на равномерное деление, если пики не нашли
        if len(xs) != 11:
            xs = [int(round(i * (gw - 1) / 10)) for i in range(11)]
        if len(ys) != 11:
            ys = [int(round(i * (gh - 1) / 10)) for i in range(11)]

        # Вырезаем ячейки как промежутки МЕЖДУ линиями (центры линий), с запасом внутрь,
        # чтобы не тащить в ROI толщину линий сетки.
        dx = [xs[i + 1] - xs[i] for i in range(len(xs) - 1)]
        dy = [ys[i + 1] - ys[i] for i in range(len(ys) - 1)]
        gap_x = max(2, int(round(max(4.0, min(dx) * 0.10)))) if dx else 3
        gap_y = max(2, int(round(max(4.0, min(dy) * 0.10)))) if dy else 3

        # 3) Извлекаем data-матрицу 8x8: пропускаем 2 верхние строки и 2 левых столбца
        matrix = [[None] * 8 for _ in range(8)]
        for i in range(8):
            for j in range(8):
                yy1, yy2 = ys[i + 2] + gap_y, ys[i + 3] - gap_y
                xx1, xx2 = xs[j + 2] + gap_x, xs[j + 3] - gap_x
                roi = grid[yy1:yy2, xx1:xx2]
                if roi.size == 0:
                    continue
                if i != j and self._detect_star(roi):
                    matrix[i][j] = 1

        # 4) Симметрия (на случай пропусков с одной стороны)
        for i in range(8):
            for j in range(i + 1, 8):
                if matrix[i][j] == 1 or matrix[j][i] == 1:
                    matrix[i][j] = 1
                    matrix[j][i] = 1

        if any(v == 1 for row in matrix for v in row):
            return {'matrix': matrix, 'size': 8}

        # Если звёздочек не нашли — возможно это таблица чисел
        num_matrix = [[None] * 8 for _ in range(8)]
        nums = 0
        for i in range(8):
            for j in range(8):
                if i == j:
                    continue
                yy1, yy2 = ys[i + 2] + gap_y, ys[i + 3] - gap_y
                xx1, xx2 = xs[j + 2] + gap_x, xs[j + 3] - gap_x
                roi = grid[yy1:yy2, xx1:xx2]
                if roi.size == 0:
                    continue
                val = self._analyze_cell(roi, is_binary_matrix=False, row_idx=i + 1, col_idx=j + 1)
                if val is not None:
                    num_matrix[i][j] = val
                    nums += 1
        if nums > 0:
            for i in range(8):
                for j in range(i + 1, 8):
                    if num_matrix[i][j] is None and num_matrix[j][i] is not None:
                        num_matrix[i][j] = num_matrix[j][i]
                    elif num_matrix[i][j] is not None and num_matrix[j][i] is None:
                        num_matrix[j][i] = num_matrix[i][j]
            return {'matrix': num_matrix, 'size': 8}

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
