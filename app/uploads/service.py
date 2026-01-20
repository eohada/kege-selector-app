from __future__ import annotations

import os
import time
import logging
from typing import Iterable, Optional

from werkzeug.utils import secure_filename

logger = logging.getLogger(__name__)


def save_uploaded_file(
    *,
    file,
    base_folder: str,
    allowed_exts: Iterable[str],
    max_bytes: int,
) -> tuple[str, str, int | None]:
    """
    Сохраняет файл на диск с базовой валидацией.

    Returns: (orig_name, abs_path, size_bytes)
    """
    if not file or not getattr(file, "filename", None):
        raise ValueError("file is required")

    # Важно: secure_filename() выкидывает кириллицу и может "съесть" точку расширения.
    # Например: "презентация.pptx" -> "pptx" (без ".pptx"), и тогда ext становится пустым.
    # Поэтому расширение берём из исходного имени, а безопасное имя собираем отдельно.
    raw_name = str(file.filename or "").strip()
    safe_full = secure_filename(raw_name)

    raw_ext = (os.path.splitext(raw_name)[1] or "").lower()
    safe_ext = (os.path.splitext(safe_full)[1] or "").lower()
    ext_with_dot = raw_ext or safe_ext
    ext = ext_with_dot.lstrip(".")

    safe_base = secure_filename(os.path.splitext(raw_name)[0]) or "file"
    orig = f"{safe_base}{ext_with_dot}"
    if not ext:
        raise ValueError("file type not allowed: (no extension)")
    allowed = {str(x).lower().lstrip(".") for x in (allowed_exts or []) if x}
    if allowed and ext not in allowed:
        raise ValueError(f"file type not allowed: .{ext}")

    os.makedirs(base_folder, exist_ok=True)

    ts = int(time.time())
    stored_name = f"{ts}_{orig}"
    abs_path = os.path.join(base_folder, stored_name)

    # size check (best-effort)
    try:
        file.stream.seek(0, os.SEEK_END)
        size = int(file.stream.tell() or 0)
        file.stream.seek(0)
    except Exception:
        size = None

    if size is not None and size > int(max_bytes):
        raise ValueError("file too large")

    file.save(abs_path)

    # re-check size from disk
    try:
        size = os.path.getsize(abs_path)
    except Exception:
        size = size

    if size is not None and size > int(max_bytes):
        try:
            os.remove(abs_path)
        except Exception:
            pass
        raise ValueError("file too large")

    return orig, abs_path, size

