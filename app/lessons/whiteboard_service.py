"""Объектная доска урока: документ, операции и серверное сохранение."""

from __future__ import annotations

import math
import os
import re
from copy import deepcopy
from dataclasses import dataclass
from threading import RLock
from typing import Any
from uuid import uuid4

from app.models import Lesson, LessonWhiteboard, LessonWhiteboardOperation, db, moscow_now


BOARD_SCHEMA_VERSION = 1
MAX_OPERATION_BATCH = 100
MAX_OBJECTS_PER_PAGE = 1200
MAX_LIVE_POINTS = 4096
MAX_IMPORT_BYTES = 20 * 1024 * 1024
MAX_IMPORT_PAGES = 50
MAX_IMPORT_TOTAL_OBJECTS = MAX_IMPORT_PAGES * MAX_OBJECTS_PER_PAGE
MAX_TEXT_LENGTH = 20000
SUPPORTED_OBJECT_TYPES = {"text", "sticky", "comment", "shape", "arrow", "stroke", "frame", "image", "file"}

_board_operation_locks: dict[int, Any] = {}


class WhiteboardOperationError(ValueError):
    """Операция не соответствует контракту документа."""


@dataclass
class WhiteboardConflict(Exception):
    version: int
    document: dict[str, Any]


def _new_page(title: str, order: int) -> dict[str, Any]:
    return {
        "id": f"page-{uuid4().hex[:12]}",
        "title": title,
        "order": order,
        "objects": [],
    }


def default_control() -> dict[str, Any]:
    return {
        "mode": "hybrid",
        "student_editing": False,
        "board_locked": False,
        "teacher_controls_windows": False,
        "teacher_controls_mode": False,
        "teacher_controls_pages": False,
        "teacher_controls_frames": False,
        "code_sync": True,
        "live_strokes": True,
        "cursor_sync": True,
        "auto_open_terminal_on_run": False,
        "student_code_editing": False,
        "allowed_page_ids": [],
        "allowed_frame_ids": [],
        "locked_page_ids": [],
        "locked_frame_ids": [],
    }


def default_document() -> dict[str, Any]:
    pages = [
        _new_page("Теория", 0),
        _new_page("Разбор", 1),
        _new_page("Практика", 2),
        _new_page("Ответ ученика", 3),
    ]
    return {
        "schema_version": BOARD_SCHEMA_VERSION,
        "pages": pages,
        "active_page_id": pages[0]["id"],
        "settings": {"grid": True, "snap": True, "background": "plain"},
        "presentation": {
            "mode": "edit",
            "follow": False,
            "page_id": pages[0]["id"],
            "frame_id": None,
            "camera": {"pan_x": 0, "pan_y": 0, "scale": 1},
            "control": default_control(),
        },
    }


def portable_document(value: Any) -> dict[str, Any]:
    """Возвращает переносимую часть доски без состояния проведения урока."""
    document = normalize_document(value)
    return {
        "schema_version": BOARD_SCHEMA_VERSION,
        "pages": deepcopy(document["pages"]),
        "active_page_id": document.get("active_page_id"),
        "settings": deepcopy(document.get("settings", {})),
    }


def boostudy_export(value: Any) -> dict[str, Any]:
    return {
        "format": "boostudy.board",
        "format_version": 1,
        "exported_at": moscow_now().isoformat(),
        "document": portable_document(value),
    }


def _finite_number(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _safe_text(value: Any, fallback: str = "") -> str:
    text = str(value or "")
    return text[:MAX_TEXT_LENGTH]


def _safe_import_object(raw: Any, object_id: str, warnings: list[str], converted: list[int]) -> dict[str, Any]:
    """Очищает импортированный объект и не пропускает произвольный HTML/JS."""
    if not isinstance(raw, dict):
        converted[0] += 1
        warnings.append("Один объект пропущен: ожидался JSON-объект")
        return _safe_object({"id": object_id, "type": "sticky", "data": {"text": "Импортированный объект"}})

    object_type = str(raw.get("type") or "sticky").strip().lower()
    if object_type not in SUPPORTED_OBJECT_TYPES:
        converted[0] += 1
        warnings.append(f"Объект типа «{object_type or 'unknown'}» преобразован в заметку")
        object_type = "sticky"

    data = raw.get("data") if isinstance(raw.get("data"), dict) else {}
    clean_data: dict[str, Any] = {}
    for key in ("text", "label", "color", "shape", "mime_type", "name", "url", "size", "data_url", "file_id", "alt"):
        if key not in data:
            continue
        value = data[key]
        if isinstance(value, (str, int, float, bool)) or value is None:
            clean_data[key] = _safe_text(value) if isinstance(value, str) else value
    for key in ("start", "end"):
        point = data.get(key)
        if isinstance(point, dict):
            clean_data[key] = {"x": _finite_number(point.get("x")), "y": _finite_number(point.get("y"))}
    if object_type == "stroke":
        points = data.get("points") if isinstance(data.get("points"), list) else []
        clean_points = []
        for point in points[:MAX_LIVE_POINTS]:
            if not isinstance(point, dict):
                continue
            clean_points.append({"x": _finite_number(point.get("x")), "y": _finite_number(point.get("y"))})
        clean_data["points"] = clean_points
        clean_data["color"] = _safe_text(data.get("color") or "#4f46e5")[:32]
        clean_data["size"] = max(1, min(96, _finite_number(data.get("size"), 4)))
        clean_data["opacity"] = max(0.05, min(1, _finite_number(data.get("opacity"), 1)))
    if data.get("frame_id"):
        clean_data["frame_id"] = str(data["frame_id"])

    item = {
        "id": object_id,
        "type": object_type,
        "x": _finite_number(raw.get("x"), 120),
        "y": _finite_number(raw.get("y"), 120),
        "width": max(1, min(10000, _finite_number(raw.get("width"), 220))),
        "height": max(1, min(10000, _finite_number(raw.get("height"), 120))),
        "rotation": _finite_number(raw.get("rotation")),
        "z_index": _finite_number(raw.get("z_index"), 1),
        "locked": bool(raw.get("locked", False)),
        "data": clean_data,
    }
    return item


def normalize_import_pages(raw_pages: Any) -> tuple[list[dict[str, Any]], list[str], int]:
    """Нормализует страницы и переназначает все идентификаторы импортируемого пакета."""
    if not isinstance(raw_pages, list) or not raw_pages:
        raise WhiteboardOperationError("В файле нет страниц для импорта")
    if len(raw_pages) > MAX_IMPORT_PAGES:
        raise WhiteboardOperationError(f"Можно импортировать не больше {MAX_IMPORT_PAGES} страниц")

    warnings: list[str] = []
    converted = [0]
    page_ids: dict[str, str] = {}
    object_ids: dict[str, str] = {}
    prepared: list[tuple[dict[str, Any], list[tuple[dict[str, Any], str]]]] = []
    total_objects = 0

    for index, raw_page in enumerate(raw_pages):
        if not isinstance(raw_page, dict):
            raise WhiteboardOperationError("Страница импорта должна быть JSON-объектом")
        old_page_id = str(raw_page.get("id") or f"page-{index}")
        new_page_id = f"page-{uuid4().hex[:12]}"
        page_ids[old_page_id] = new_page_id
        raw_objects = raw_page.get("objects") if isinstance(raw_page.get("objects"), list) else []
        if len(raw_objects) > MAX_OBJECTS_PER_PAGE:
            raise WhiteboardOperationError(f"На странице нельзя импортировать больше {MAX_OBJECTS_PER_PAGE} объектов")
        total_objects += len(raw_objects)
        if total_objects > MAX_IMPORT_TOTAL_OBJECTS:
            raise WhiteboardOperationError("В импортируемом документе слишком много объектов")
        object_pairs: list[tuple[dict[str, Any], str]] = []
        for raw_object in raw_objects:
            old_object_id = str(raw_object.get("id") if isinstance(raw_object, dict) else "") or uuid4().hex
            new_object_id = f"object-{uuid4().hex[:12]}"
            object_ids[old_object_id] = new_object_id
            object_pairs.append((raw_object, new_object_id))
        prepared.append((raw_page, object_pairs))

    pages: list[dict[str, Any]] = []
    for index, (raw_page, object_pairs) in enumerate(prepared):
        objects = []
        for raw_object, new_object_id in object_pairs:
            item = _safe_import_object(raw_object, new_object_id, warnings, converted)
            frame_id = item.get("data", {}).get("frame_id")
            if frame_id:
                if frame_id in object_ids:
                    item["data"]["frame_id"] = object_ids[frame_id]
                else:
                    item["data"].pop("frame_id", None)
                    converted[0] += 1
                    warnings.append("У одного объекта удалена ссылка на отсутствующий фрейм")
            objects.append(item)
        title = re.sub(r"\s+", " ", _safe_text(raw_page.get("title"), f"Импорт {index + 1}")).strip()
        pages.append({
            "id": page_ids[str(raw_page.get("id") or f"page-{index}")],
            "title": (title or f"Импорт {index + 1}")[:120],
            "order": index,
            "objects": objects,
        })
    return pages, warnings, converted[0]


def import_boostudy_payload(payload: Any) -> tuple[list[dict[str, Any]], list[str], int]:
    if not isinstance(payload, dict) or payload.get("format") != "boostudy.board":
        raise WhiteboardOperationError("Это не файл BooStudy Board")
    if int(payload.get("format_version") or 0) != 1:
        raise WhiteboardOperationError("Версия файла BooStudy не поддерживается")
    document = payload.get("document") if isinstance(payload.get("document"), dict) else {}
    return normalize_import_pages(document.get("pages"))


def import_excalidraw_payload(payload: Any, title: str = "Памятка Excalidraw") -> tuple[list[dict[str, Any]], list[str], int]:
    if not isinstance(payload, dict) or payload.get("type") != "excalidraw":
        raise WhiteboardOperationError("Это не файл Excalidraw")
    elements = payload.get("elements") if isinstance(payload.get("elements"), list) else []
    if not elements:
        raise WhiteboardOperationError("В Excalidraw-файле нет объектов")
    objects: list[dict[str, Any]] = []
    warnings: list[str] = []
    converted = [0]
    frame_ids: dict[str, str] = {}
    files = payload.get("files") if isinstance(payload.get("files"), dict) else {}
    for element in elements:
        if not isinstance(element, dict) or element.get("isDeleted"):
            continue
        element_type = str(element.get("type") or "").lower()
        x, y = _finite_number(element.get("x")), _finite_number(element.get("y"))
        width = max(1, _finite_number(element.get("width"), 120))
        height = max(1, _finite_number(element.get("height"), 80))
        object_id = f"object-{uuid4().hex[:12]}"
        data: dict[str, Any] = {}
        object_type = "sticky"
        if element_type in {"rectangle", "ellipse", "diamond"}:
            object_type = "shape"
            data["shape"] = element_type
        elif element_type in {"arrow", "line"}:
            object_type = "arrow"
            points = element.get("points") if isinstance(element.get("points"), list) else []
            start = points[0] if points else [0, height / 2]
            end = points[-1] if points else [width, height / 2]
            data.update({"start": {"x": _finite_number(start[0] if isinstance(start, list) and start else 0), "y": _finite_number(start[1] if isinstance(start, list) and len(start) > 1 else height / 2)}, "end": {"x": _finite_number(end[0] if isinstance(end, list) and end else width), "y": _finite_number(end[1] if isinstance(end, list) and len(end) > 1 else height / 2)}})
        elif element_type == "text":
            object_type = "text"
            data["text"] = _safe_text(element.get("text"))
        elif element_type == "freedraw":
            object_type = "stroke"
            points = element.get("points") if isinstance(element.get("points"), list) else []
            data["points"] = [{"x": x + _finite_number(point[0] if isinstance(point, list) and point else 0), "y": y + _finite_number(point[1] if isinstance(point, list) and len(point) > 1 else 0)} for point in points[:MAX_LIVE_POINTS]]
            data.update({"color": _safe_text(element.get("strokeColor") or "#4f46e5")[:32], "size": max(1, min(96, _finite_number(element.get("strokeWidth"), 4))), "opacity": max(.05, min(1, _finite_number(element.get("opacity"), 1) / 100))})
        elif element_type == "frame":
            object_type = "frame"
            frame_ids[str(element.get("id") or object_id)] = object_id
            data["label"] = _safe_text(element.get("name") or "Фрейм")
        elif element_type == "image":
            object_type = "image"
            file_id = _safe_text(element.get("fileId"))
            data["file_id"] = file_id
            data["alt"] = _safe_text(element.get("customData", {}).get("alt") if isinstance(element.get("customData"), dict) else "")
            file_entry = files.get(file_id) if file_id else None
            if isinstance(file_entry, dict):
                data_url = file_entry.get("dataURL") or file_entry.get("dataUrl")
                if isinstance(data_url, str) and data_url.startswith("data:"):
                    data["data_url"] = data_url
                elif file_id:
                    warnings.append(f"Изображение «{file_id}» импортировано без встроенного файла")
            elif file_id:
                warnings.append(f"Изображение «{file_id}» импортировано без встроенного файла")
        else:
            converted[0] += 1
            warnings.append(f"Объект Excalidraw «{element_type or 'unknown'}» преобразован в заметку")
            data["text"] = _safe_text(element.get("text") or element.get("name") or "Импортированный объект")
        objects.append({"id": object_id, "type": object_type, "x": x, "y": y, "width": width, "height": height, "rotation": _finite_number(element.get("angle")), "z_index": len(objects) + 1, "locked": bool(element.get("locked", False)), "data": data})

    for item, element in zip(objects, [element for element in elements if isinstance(element, dict) and not element.get("isDeleted")]):
        frame_id = element.get("frameId")
        if frame_id and str(frame_id) in frame_ids:
            item["data"]["frame_id"] = frame_ids[str(frame_id)]
    pages, page_warnings, page_converted = normalize_import_pages([{"id": "excalidraw-page", "title": os.path.splitext(os.path.basename(title))[0] or "Памятка Excalidraw", "objects": objects}])
    return pages, warnings + page_warnings, converted[0] + page_converted


def validate_import_pages(value: Any) -> list[dict[str, Any]]:
    """Проверяет уже нормализованный пакет, не меняя его идентификаторы повторно."""
    if not isinstance(value, list) or not value or len(value) > MAX_IMPORT_PAGES:
        raise WhiteboardOperationError("Некорректный пакет импортируемых страниц")
    page_ids: set[str] = set()
    object_ids: set[str] = set()
    validated: list[dict[str, Any]] = []
    total_objects = 0
    for index, raw_page in enumerate(value):
        if not isinstance(raw_page, dict):
            raise WhiteboardOperationError("Страница импорта должна быть JSON-объектом")
        page_id = str(raw_page.get("id") or "")
        if not page_id or page_id in page_ids:
            raise WhiteboardOperationError("В импорте есть повторяющийся id страницы")
        page_ids.add(page_id)
        raw_objects = raw_page.get("objects") if isinstance(raw_page.get("objects"), list) else []
        if len(raw_objects) > MAX_OBJECTS_PER_PAGE:
            raise WhiteboardOperationError(f"На странице нельзя импортировать больше {MAX_OBJECTS_PER_PAGE} объектов")
        total_objects += len(raw_objects)
        if total_objects > MAX_IMPORT_TOTAL_OBJECTS:
            raise WhiteboardOperationError("В импортируемом документе слишком много объектов")
        objects = []
        for raw_object in raw_objects:
            if not isinstance(raw_object, dict) or not str(raw_object.get("id") or ""):
                raise WhiteboardOperationError("У импортированного объекта отсутствует id")
            object_id = str(raw_object["id"])
            if object_id in object_ids:
                raise WhiteboardOperationError("В импорте есть повторяющийся id объекта")
            object_ids.add(object_id)
            objects.append(_safe_import_object(raw_object, object_id, [], [0]))
        validated.append({
            "id": page_id,
            "title": _safe_text(raw_page.get("title"), f"Импорт {index + 1}")[:120] or f"Импорт {index + 1}",
            "order": index,
            "objects": objects,
        })
    for page in validated:
        local_object_ids = {item["id"] for item in page["objects"]}
        for item in page["objects"]:
            frame_id = (item.get("data") or {}).get("frame_id")
            if frame_id and frame_id not in object_ids:
                item["data"].pop("frame_id", None)
            elif frame_id and frame_id not in local_object_ids:
                item["data"].pop("frame_id", None)
    return validated


def _object_bounds_for_export(item: dict[str, Any]) -> tuple[float, float, float, float]:
    if item.get("type") != "stroke":
        return (_finite_number(item.get("x")), _finite_number(item.get("y")), max(1, _finite_number(item.get("width"), 1)), max(1, _finite_number(item.get("height"), 1)))
    points = (item.get("data") or {}).get("points") or []
    if not points:
        return (_finite_number(item.get("x")), _finite_number(item.get("y")), 1, 1)
    xs = [_finite_number(point.get("x")) for point in points if isinstance(point, dict)]
    ys = [_finite_number(point.get("y")) for point in points if isinstance(point, dict)]
    if not xs or not ys:
        return (_finite_number(item.get("x")), _finite_number(item.get("y")), 1, 1)
    left, top = min(xs), min(ys)
    return left, top, max(1, max(xs) - left), max(1, max(ys) - top)


def excalidraw_export(value: Any) -> dict[str, Any]:
    """Сериализует BooStudy-объекты в совместимую Excalidraw-сцену."""
    document = portable_document(value)
    elements: list[dict[str, Any]] = []
    now = int(moscow_now().timestamp() * 1000)
    for page in document["pages"]:
        page_objects = page.get("objects") or []
        for item in page_objects:
            x, y, width, height = _object_bounds_for_export(item)
            data = item.get("data") if isinstance(item.get("data"), dict) else {}
            base = {
                "id": str(item.get("id") or uuid4().hex),
                "x": x,
                "y": y,
                "width": width,
                "height": height,
                "angle": _finite_number(item.get("rotation")),
                "strokeColor": str(data.get("color") or "#4f46e5"),
                "backgroundColor": "transparent",
                "fillStyle": "solid",
                "strokeWidth": max(1, _finite_number(data.get("size"), 2)),
                "strokeStyle": "solid",
                "roughness": 0,
                "opacity": round(max(.05, min(1, _finite_number(data.get("opacity"), 1))) * 100),
                "seed": abs(hash(str(item.get("id")))) % 2147483647,
                "version": 1,
                "versionNonce": 1,
                "isDeleted": False,
                "groupIds": [],
                "boundElements": None,
                "updated": now,
                "locked": bool(item.get("locked")),
                "customData": {"boostudy_type": item.get("type"), "boostudy_page_id": page.get("id")},
            }
            object_type = item.get("type")
            if object_type == "shape":
                shape = data.get("shape") or "rect"
                base["type"] = "ellipse" if shape == "ellipse" else "diamond" if shape == "diamond" else "rectangle"
                base["backgroundColor"] = "#eef2ff"
                elements.append(base)
            elif object_type == "frame":
                base["type"] = "frame"
                base["name"] = str(data.get("label") or "Фрейм")[:120]
                base["strokeColor"] = str(data.get("color") or "#818cf8")
                base["backgroundColor"] = "transparent"
                elements.append(base)
            elif object_type in {"text", "sticky", "comment"}:
                text = str(data.get("text") or data.get("label") or "")[:MAX_TEXT_LENGTH]
                if object_type != "text":
                    card = dict(base, type="rectangle", backgroundColor="#fff7cc" if object_type == "sticky" else "#eff6ff")
                    elements.append(card)
                elements.append(dict(base, type="text", text=text, fontSize=16, fontFamily=1, textAlign="left", verticalAlign="top", autoResize=False, containerId=None, originalText=text, baseline=16, backgroundColor="transparent", strokeColor="#1e293b"))
            elif object_type == "arrow":
                start = data.get("start") if isinstance(data.get("start"), dict) else {"x": 0, "y": height / 2}
                end = data.get("end") if isinstance(data.get("end"), dict) else {"x": width, "y": height / 2}
                base.update({"type": "arrow", "points": [[_finite_number(start.get("x")), _finite_number(start.get("y"))], [_finite_number(end.get("x"), width), _finite_number(end.get("y"), height / 2)]], "endArrowhead": "triangle"})
                elements.append(base)
            elif object_type == "stroke":
                points = data.get("points") if isinstance(data.get("points"), list) else []
                base.update({"type": "freedraw", "points": [[_finite_number(point.get("x")) - x, _finite_number(point.get("y")) - y] for point in points if isinstance(point, dict)]})
                elements.append(base)
            elif object_type in {"image", "file"}:
                base.update({"type": "image", "fileId": str(data.get("file_id") or item.get("id")), "status": "saved", "scale": [1, 1], "customData": {**base["customData"], "url": data.get("url"), "name": data.get("name"), "mime_type": data.get("mime_type")}})
                elements.append(base)
            else:
                elements.append(dict(base, type="rectangle"))
    return {
        "type": "excalidraw",
        "version": 2,
        "source": "boostudy",
        "elements": elements,
        "appState": {"viewBackgroundColor": "#ffffff", "gridSize": 20 if document["settings"].get("grid") else None, "zoom": {"value": 1}},
        "files": {},
    }


def normalize_document(value: Any) -> dict[str, Any]:
    document = deepcopy(value) if isinstance(value, dict) else default_document()
    if document.get("schema_version") != BOARD_SCHEMA_VERSION:
        document["schema_version"] = BOARD_SCHEMA_VERSION
    pages = document.get("pages")
    if not isinstance(pages, list) or not pages:
        fresh = default_document()
        pages = fresh["pages"]
        document["pages"] = pages
    for index, page in enumerate(pages):
        if not isinstance(page, dict):
            pages[index] = _new_page(f"Страница {index + 1}", index)
            continue
        page.setdefault("id", f"page-{uuid4().hex[:12]}")
        page.setdefault("title", f"Страница {index + 1}")
        page["order"] = index
        if not isinstance(page.get("objects"), list):
            page["objects"] = []
    active = document.get("active_page_id")
    if not any(page["id"] == active for page in pages):
        document["active_page_id"] = pages[0]["id"]
    settings = document.setdefault("settings", {})
    settings.setdefault("grid", True)
    settings.setdefault("snap", True)
    settings.setdefault("background", "plain")
    presentation = document.setdefault("presentation", {})
    presentation.setdefault("mode", "edit")
    presentation.setdefault("follow", False)
    presentation.setdefault("page_id", document["active_page_id"])
    presentation.setdefault("frame_id", None)
    control = presentation.setdefault("control", {})
    if not isinstance(control, dict):
        control = default_control()
        presentation["control"] = control
    for key, value in default_control().items():
        control.setdefault(key, deepcopy(value))
    if control.get("mode") not in {"guided", "hybrid", "free"}:
        control["mode"] = "hybrid"
    for key in (
        "student_editing",
        "board_locked",
        "teacher_controls_windows",
        "teacher_controls_mode",
        "teacher_controls_pages",
        "teacher_controls_frames",
        "code_sync",
        "live_strokes",
        "cursor_sync",
        "auto_open_terminal_on_run",
        "student_code_editing",
    ):
        control[key] = bool(control.get(key))
    for key in ("allowed_page_ids", "allowed_frame_ids", "locked_page_ids", "locked_frame_ids"):
        if not isinstance(control.get(key), list):
            control[key] = []
        control[key] = [str(item) for item in control[key] if item]
    camera = presentation.setdefault("camera", {})
    if not isinstance(camera, dict):
        camera = {}
        presentation["camera"] = camera
    camera.setdefault("pan_x", 0)
    camera.setdefault("pan_y", 0)
    camera.setdefault("scale", 1)
    timer = presentation.setdefault("timer", {})
    if not isinstance(timer, dict):
        timer = {}
        presentation["timer"] = timer
    timer.setdefault("duration_seconds", 25 * 60)
    timer.setdefault("remaining_seconds", timer["duration_seconds"])
    timer.setdefault("running", False)
    timer.setdefault("started_at", None)
    timer.setdefault("paused_at", None)
    return document


def _page(document: dict[str, Any], page_id: str | None) -> dict[str, Any]:
    requested = page_id or document.get("active_page_id")
    for page in document["pages"]:
        if page.get("id") == requested:
            return page
    raise WhiteboardOperationError("Страница доски не найдена")


def _object(page: dict[str, Any], object_id: str) -> dict[str, Any]:
    for item in page.get("objects", []):
        if item.get("id") == object_id:
            return item
    raise WhiteboardOperationError("Объект доски не найден")


def _safe_object(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise WhiteboardOperationError("Объект доски должен быть JSON-объектом")
    item = deepcopy(raw)
    item.setdefault("id", f"object-{uuid4().hex[:12]}")
    item.setdefault("type", "sticky")
    item.setdefault("x", 120)
    item.setdefault("y", 120)
    item.setdefault("width", 220)
    item.setdefault("height", 120)
    item.setdefault("rotation", 0)
    item.setdefault("z_index", 1)
    item.setdefault("locked", False)
    item.setdefault("data", {})
    if not isinstance(item["data"], dict):
        raise WhiteboardOperationError("Данные объекта должны быть JSON-объектом")
    return item


def _control(document: dict[str, Any]) -> dict[str, Any]:
    return normalize_document(document).get("presentation", {}).get("control", {})


def _page_is_locked(document: dict[str, Any], page_id: str) -> bool:
    return page_id in _control(document).get("locked_page_ids", [])


def _frame_is_locked(document: dict[str, Any], page: dict[str, Any], frame_id: str | None) -> bool:
    if not frame_id:
        return False
    control = _control(document)
    if frame_id in control.get("locked_frame_ids", []):
        return True
    frame = next((item for item in page.get("objects", []) if item.get("id") == frame_id and item.get("type") == "frame"), None)
    return bool(frame and frame.get("locked"))


def _object_is_editable(document: dict[str, Any], page: dict[str, Any], item: dict[str, Any]) -> bool:
    if item.get("locked"):
        return False
    frame_id = (item.get("data") or {}).get("frame_id")
    allowed_frames = _control(document).get("allowed_frame_ids", [])
    if allowed_frames and frame_id not in allowed_frames:
        return False
    return not _frame_is_locked(document, page, frame_id)


def can_student_edit_page(document: dict[str, Any], page_id: str) -> bool:
    control = _control(document)
    if control.get("board_locked") or not control.get("student_editing"):
        return False
    if _page_is_locked(document, page_id):
        return False
    allowed_pages = control.get("allowed_page_ids", [])
    return not allowed_pages or page_id in allowed_pages


def validate_operation_permissions(document: dict[str, Any], operation: dict[str, Any], role: str) -> None:
    """Проверяет серверные права до применения операции или live-действия."""
    if role == "teacher":
        return
    if role == "parent":
        raise WhiteboardOperationError("Родитель может просматривать доску, но не изменять её")
    operation_type = str(operation.get("type") or "")
    if operation_type in {
        "page.create", "page.rename", "page.delete", "page.activate", "settings.update",
        "presentation.update", "control.update", "document.replace", "page.import", "object.lock",
    }:
        raise WhiteboardOperationError("Эта операция доступна только преподавателю")
    page_id = str(operation.get("page_id") or normalize_document(document).get("active_page_id"))
    if not can_student_edit_page(document, page_id):
        raise WhiteboardOperationError("Преподаватель пока не открыл редактирование этой страницы")
    page = _page(normalize_document(document), page_id)

    def validate_item(item: dict[str, Any], patch: dict[str, Any] | None = None) -> None:
        if not _object_is_editable(document, page, item):
            raise WhiteboardOperationError("Объект или его фрейм заблокирован")
        if patch and "locked" in patch:
            raise WhiteboardOperationError("Блокировать объекты может только преподаватель")
        data = (patch or {}).get("data") if patch else item.get("data")
        frame_id = (data or {}).get("frame_id") if isinstance(data, dict) else None
        allowed_frames = _control(document).get("allowed_frame_ids", [])
        if allowed_frames and frame_id not in allowed_frames:
            raise WhiteboardOperationError("Редактирование разрешено только в открытом фрейме")
        if frame_id and _frame_is_locked(document, page, frame_id):
            raise WhiteboardOperationError("Фрейм заблокирован")

    if operation_type == "object.create":
        item = _safe_object(operation.get("object"))
        frame_id = (item.get("data") or {}).get("frame_id")
        allowed_frames = _control(document).get("allowed_frame_ids", [])
        if allowed_frames and frame_id not in allowed_frames:
            raise WhiteboardOperationError("Редактирование разрешено только в открытом фрейме")
        if frame_id and _frame_is_locked(document, page, frame_id):
            raise WhiteboardOperationError("Фрейм заблокирован")
    elif operation_type in {"object.update", "object.delete", "object.duplicate"}:
        validate_item(_object(page, str(operation.get("object_id"))), operation.get("patch"))
    elif operation_type == "object.batch":
        for entry in operation.get("updates") or []:
            validate_item(_object(page, str(entry.get("object_id"))), entry.get("patch") or {})
        for object_id in operation.get("deletes") or []:
            validate_item(_object(page, str(object_id)))
        for raw in operation.get("creates") or []:
            item = _safe_object(raw)
            frame_id = (item.get("data") or {}).get("frame_id")
            allowed_frames = _control(document).get("allowed_frame_ids", [])
            if allowed_frames and frame_id not in allowed_frames:
                raise WhiteboardOperationError("Редактирование разрешено только в открытом фрейме")
            if frame_id and _frame_is_locked(document, page, frame_id):
                raise WhiteboardOperationError("Фрейм заблокирован")


def apply_operation(document: dict[str, Any], operation: dict[str, Any]) -> dict[str, Any]:
    """Применяет одну типизированную операцию и возвращает новый документ."""
    if not isinstance(operation, dict):
        raise WhiteboardOperationError("Операция должна быть JSON-объектом")
    operation_type = (operation.get("type") or "").strip()
    if not operation_type:
        raise WhiteboardOperationError("У операции отсутствует type")
    next_document = normalize_document(document)

    if operation_type == "page.create":
        title = (operation.get("title") or "Новая страница").strip()[:120]
        next_document["pages"].append(_new_page(title or "Новая страница", len(next_document["pages"])))
        return next_document
    if operation_type == "page.rename":
        page = _page(next_document, operation.get("page_id"))
        page["title"] = (operation.get("title") or "Без названия").strip()[:120]
        return next_document
    if operation_type == "page.delete":
        if len(next_document["pages"]) <= 1:
            raise WhiteboardOperationError("Нельзя удалить последнюю страницу")
        page_id = operation.get("page_id") or next_document["active_page_id"]
        next_document["pages"] = [page for page in next_document["pages"] if page["id"] != page_id]
        next_document["pages"] = [dict(page, order=index) for index, page in enumerate(next_document["pages"])]
        if next_document["active_page_id"] == page_id:
            next_document["active_page_id"] = next_document["pages"][0]["id"]
        return next_document
    if operation_type == "page.import":
        pages = validate_import_pages(operation.get("pages"))
        existing_page_ids = {page["id"] for page in next_document["pages"]}
        imported_page_ids = {page["id"] for page in pages}
        if existing_page_ids.intersection(imported_page_ids):
            raise WhiteboardOperationError("Импорт содержит уже существующий id страницы")
        if len(next_document["pages"]) + len(pages) > MAX_IMPORT_PAGES + len(default_document()["pages"]):
            raise WhiteboardOperationError("На доске слишком много страниц")
        next_document["pages"].extend(deepcopy(pages))
        next_document["pages"] = [dict(page, order=index) for index, page in enumerate(next_document["pages"])]
        return next_document
    if operation_type == "page.activate":
        page = _page(next_document, operation.get("page_id"))
        next_document["active_page_id"] = page["id"]
        next_document["presentation"]["page_id"] = page["id"]
        return next_document
    if operation_type == "settings.update":
        settings = operation.get("settings") or {}
        if not isinstance(settings, dict):
            raise WhiteboardOperationError("Настройки доски должны быть объектом")
        next_document["settings"].update({key: settings[key] for key in ("grid", "snap", "background") if key in settings})
        return next_document
    if operation_type == "presentation.update":
        presentation = operation.get("presentation") or {}
        if not isinstance(presentation, dict):
            raise WhiteboardOperationError("Состояние показа должно быть объектом")
        for key in ("mode", "follow", "page_id", "frame_id"):
            if key in presentation:
                next_document["presentation"][key] = deepcopy(presentation[key])
        if "camera" in presentation:
            camera = presentation["camera"]
            if not isinstance(camera, dict):
                raise WhiteboardOperationError("Камера показа должна быть объектом")
            next_document["presentation"]["camera"].update({
                key: camera[key]
                for key in ("pan_x", "pan_y", "scale")
                if key in camera
            })
        if "timer" in presentation:
            timer = presentation["timer"]
            if not isinstance(timer, dict):
                raise WhiteboardOperationError("Таймер урока должен быть объектом")
            next_document["presentation"]["timer"].update({
                key: deepcopy(timer[key])
                for key in ("duration_seconds", "remaining_seconds", "running", "started_at", "paused_at")
                if key in timer
            })
        return next_document
    if operation_type == "control.update":
        control = operation.get("control") or {}
        if not isinstance(control, dict):
            raise WhiteboardOperationError("Параметры доступа к доске должны быть объектом")
        allowed = set(default_control())
        next_document["presentation"]["control"].update({
            key: deepcopy(value)
            for key, value in control.items()
            if key in allowed
        })
        return normalize_document(next_document)
    if operation_type == "document.replace":
        replacement = operation.get("document")
        if not isinstance(replacement, dict):
            raise WhiteboardOperationError("Документ для восстановления отсутствует")
        return normalize_document(replacement)

    page = _page(next_document, operation.get("page_id"))
    objects = page.setdefault("objects", [])
    if operation_type == "object.create":
        if len(objects) >= MAX_OBJECTS_PER_PAGE:
            raise WhiteboardOperationError("На странице слишком много объектов")
        item = _safe_object(operation.get("object"))
        if any(existing.get("id") == item["id"] for existing in objects):
            raise WhiteboardOperationError("Объект с таким id уже существует")
        objects.append(item)
        return next_document
    if operation_type == "object.batch":
        updates = operation.get("updates") or []
        deletes = operation.get("deletes") or []
        creates = operation.get("creates") or []
        if not all(isinstance(entry, dict) for entry in updates):
            raise WhiteboardOperationError("Пакет изменений объектов некорректен")
        if not all(isinstance(object_id, str) for object_id in deletes):
            raise WhiteboardOperationError("Пакет удаления объектов некорректен")
        if not all(isinstance(entry, dict) for entry in creates):
            raise WhiteboardOperationError("Пакет создания объектов некорректен")
        update_targets = []
        for entry in updates:
            object_id = entry.get("object_id")
            patch = entry.get("patch") or {}
            if not isinstance(object_id, str) or not isinstance(patch, dict):
                raise WhiteboardOperationError("Изменение объекта должно содержать object_id и patch")
            target = _object(page, object_id)
            if target.get("locked"):
                raise WhiteboardOperationError("Один из объектов заблокирован")
            update_targets.append((target, patch))
        delete_targets = []
        for object_id in deletes:
            target = _object(page, object_id)
            if target.get("locked"):
                raise WhiteboardOperationError("Один из объектов заблокирован")
            delete_targets.append(target)
        if len(objects) + len(creates) - len(delete_targets) > MAX_OBJECTS_PER_PAGE:
            raise WhiteboardOperationError("На странице слишком много объектов")
        create_targets = [_safe_object(entry) for entry in creates]
        existing_ids = {entry.get("id") for entry in objects}
        create_ids = [entry.get("id") for entry in create_targets]
        if len(create_ids) != len(set(create_ids)) or existing_ids.intersection(create_ids):
            raise WhiteboardOperationError("В пакете есть повторяющиеся id объектов")
        for target, patch in update_targets:
            allowed = {"x", "y", "width", "height", "rotation", "z_index", "data", "locked"}
            target.update({key: deepcopy(value) for key, value in patch.items() if key in allowed})
        if delete_targets:
            deleted_ids = {id(target) for target in delete_targets}
            page["objects"] = [target for target in objects if id(target) not in deleted_ids]
        page["objects"].extend(create_targets)
        return next_document
    object_id = operation.get("object_id")
    item = _object(page, object_id)
    if item.get("locked") and operation_type not in {"object.lock"}:
        raise WhiteboardOperationError("Объект заблокирован")
    if operation_type == "object.update":
        patch = operation.get("patch") or {}
        if not isinstance(patch, dict):
            raise WhiteboardOperationError("Изменения объекта должны быть объектом")
        allowed = {"x", "y", "width", "height", "rotation", "z_index", "data", "locked"}
        item.update({key: deepcopy(value) for key, value in patch.items() if key in allowed})
        return next_document
    if operation_type == "object.delete":
        page["objects"] = [existing for existing in objects if existing.get("id") != object_id]
        return next_document
    if operation_type == "object.lock":
        item["locked"] = bool(operation.get("locked", not item.get("locked", False)))
        return next_document
    if operation_type == "object.duplicate":
        duplicate = deepcopy(item)
        duplicate["id"] = f"object-{uuid4().hex[:12]}"
        duplicate["x"] = float(duplicate.get("x", 0)) + 24
        duplicate["y"] = float(duplicate.get("y", 0)) + 24
        duplicate["locked"] = False
        objects.append(duplicate)
        return next_document
    raise WhiteboardOperationError(f"Неизвестный тип операции: {operation_type}")


def get_or_create_board(lesson_id: int) -> LessonWhiteboard:
    board = LessonWhiteboard.query.filter_by(lesson_id=lesson_id).first()
    if board is None:
        board = LessonWhiteboard(
            lesson_id=lesson_id,
            miro_board_id=f"local-{lesson_id}",
            board_name=f"Комната урока #{lesson_id}",
            provider="boostudy",
            document_state=default_document(),
            document_version=0,
            is_active=True,
            allow_student_edit=True,
        )
        db.session.add(board)
        db.session.commit()
    elif not board.document_state:
        board.document_state = default_document()
        board.document_version = int(board.document_version or 0)
        board.provider = "boostudy"
        db.session.commit()
    return board


def board_payload(board: LessonWhiteboard) -> dict[str, Any]:
    return {
        "schema_version": BOARD_SCHEMA_VERSION,
        "lesson_id": board.lesson_id,
        "provider": board.provider or "boostudy",
        "version": int(board.document_version or 0),
        "document": normalize_document(board.document_state),
        "updated_at": board.updated_at.isoformat() if board.updated_at else None,
        "server_now": int(moscow_now().timestamp() * 1000),
        "legacy_miro": {
            "board_id": board.miro_board_id,
            "view_link": board.miro_view_link,
        },
    }


def _persist_operations_locked(
    board: LessonWhiteboard,
    operations: list[dict[str, Any]],
    user_id: int | None,
    client_id: str | None,
    base_version: int | None = None,
    role: str = "teacher",
) -> tuple[dict[str, Any], list[str]]:
    if not isinstance(operations, list) or not operations or len(operations) > MAX_OPERATION_BATCH:
        raise WhiteboardOperationError("Некорректный пакет операций")
    current_version = int(board.document_version or 0)
    existing_ids = {
        row.operation_id
        for row in LessonWhiteboardOperation.query.filter(
            LessonWhiteboardOperation.whiteboard_id == board.id,
            LessonWhiteboardOperation.operation_id.in_([str(item.get("operation_id")) for item in operations if item.get("operation_id")]),
        ).all()
    }
    pending = [item for item in operations if str(item.get("operation_id")) not in existing_ids]
    if base_version is not None and int(base_version) != current_version and pending:
        raise WhiteboardConflict(current_version, normalize_document(board.document_state))

    document = normalize_document(board.document_state)
    accepted: list[str] = []
    for item in pending:
        operation_id = str(item.get("operation_id") or uuid4().hex)
        validate_operation_permissions(document, item, role)
        document = apply_operation(document, item)
        current_version += 1
        db.session.add(LessonWhiteboardOperation(
            whiteboard_id=board.id,
            operation_id=operation_id,
            version=current_version,
            user_id=user_id,
            operation_type=str(item.get("type") or "unknown")[:64],
            payload={key: value for key, value in item.items() if key != "operation_id"},
        ))
        accepted.append(operation_id)
    board.document_state = document
    board.document_version = current_version
    board.last_saved_by_user_id = user_id
    board.updated_at = moscow_now()
    db.session.commit()
    return board_payload(board), accepted


def persist_operations(
    board: LessonWhiteboard,
    operations: list[dict[str, Any]],
    user_id: int | None,
    client_id: str | None,
    base_version: int | None = None,
    role: str = "teacher",
) -> tuple[dict[str, Any], list[str]]:
    """Serialize operation commits for both Socket.IO and REST callers.

    The local development database is SQLite, so a socket write and a REST
    fallback write must not enter the version check/commit window together.
    Keeping the lock here protects every caller, including future endpoints.
    """
    board_id = int(board.id)
    lock = _board_operation_locks.setdefault(board_id, RLock())
    with lock:
        return _persist_operations_locked(board, operations, user_id, client_id, base_version, role)
