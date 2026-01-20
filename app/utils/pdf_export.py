from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


def html_to_pdf_bytes(html: str, base_url: Optional[str] = None) -> bytes:
    """
    Рендер HTML в PDF через Playwright (chromium).

    Почему так:
    - `playwright` уже есть в зависимостях проекта
    - Не требует системных GTK-библиотек как WeasyPrint
    - Даёт максимально одинаковый результат с браузерной печатью
    """
    try:
        from playwright.sync_api import sync_playwright  # type: ignore
    except Exception as e:
        raise RuntimeError("playwright is not available for PDF export") from e

    html = html or ""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        # Важно: печатные шаблоны должны быть self-contained (inline CSS), чтобы не зависеть от сети.
        # Playwright Python не поддерживает base_url в set_content; параметр оставляем в сигнатуре
        # на будущее (если решим перейти на data: URL + page.goto).
        _ = base_url
        page.set_content(html, wait_until="load")
        pdf_bytes = page.pdf(
            format="A4",
            print_background=True,
            margin={"top": "12mm", "right": "10mm", "bottom": "12mm", "left": "10mm"},
        )
        try:
            page.close()
        except Exception:
            pass
        try:
            browser.close()
        except Exception:
            pass
    return pdf_bytes

