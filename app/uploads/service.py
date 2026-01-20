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

    orig = secure_filename(file.filename)
    if not orig:
        raise ValueError("invalid filename")

    ext = (os.path.splitext(orig)[1] or "").lower().lstrip(".")
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

