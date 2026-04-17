#!/usr/bin/env python3
"""
Восстановление поврежденных условий task_number=6 из источника kompege.

Алгоритм:
1) Находит подозрительные строки task6 в БД (обрезанное начало, пустые скобки и т.д.).
2) Загружает актуальный список задач №6 через API kompege.
3) Для каждой подозрительной строки подтягивает contentHtml по source_url(taskId),
   пропускает через clean_html_content и обновляет content_html.

По умолчанию dry-run, для записи используйте --apply.
"""
from __future__ import annotations

import argparse
import io
import os
import re
import sys
from typing import Any

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import create_app, db  # noqa: E402
from app.models import Tasks  # noqa: E402
from scraper.playwright_parser import clean_html_content, fetch_kompege_listing_from_api  # noqa: E402


TASK_ID_RE = re.compile(r"[?&]id=(\d+)")
TAG_RE = re.compile(r"<[^>]+>")


def _plain_text(html: str) -> str:
    text = TAG_RE.sub(" ", html or "")
    text = text.replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip()


def _is_suspicious_task6_content(html: str) -> bool:
    text = _plain_text(html)
    if not text:
        return True
    # Частый артефакт: начало с пустых скобок/обрубка после чистки авторов.
    if re.match(r"^\(\s*\)", text):
        return True
    if text.startswith("Черепаха") and "Исполнитель" not in text[:80]:
        return True
    # Подозрительно короткий текст для №6.
    if len(text) < 220:
        return True
    return False


def _extract_source_task_id(source_url: str | None) -> str | None:
    if not source_url:
        return None
    m = TASK_ID_RE.search(source_url)
    return m.group(1) if m else None


def main() -> int:
    parser = argparse.ArgumentParser(description="Restore broken task6 content_html from kompege source")
    parser.add_argument("--apply", action="store_true", help="Persist updates to DB")
    parser.add_argument("--task-id", type=int, default=0, help="Process only one local task_id")
    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        query = Tasks.query.filter(Tasks.task_number == 6)
        if args.task_id:
            query = query.filter(Tasks.task_id == args.task_id)
        rows = query.order_by(Tasks.task_id.asc()).all()

        suspects: list[Tasks] = [t for t in rows if _is_suspicious_task6_content(t.content_html or "")]
        print(f"task6 total={len(rows)} suspicious={len(suspects)}")
        if not suspects:
            print("Подозрительных записей не найдено.")
            return 0

        items = fetch_kompege_listing_from_api(6)
        by_remote_id: dict[str, Any] = {}
        for item in items or []:
            rid = str(item.get("taskId") or "").strip()
            if rid:
                by_remote_id[rid] = item
        print(f"remote items fetched={len(by_remote_id)}")
        if not by_remote_id:
            print("Не удалось получить данные источника, обновление отменено.")
            return 1

        updated = 0
        not_found = 0
        for t in suspects:
            remote_id = _extract_source_task_id(getattr(t, "source_url", None))
            if not remote_id or remote_id not in by_remote_id:
                not_found += 1
                print(f"SKIP task_id={t.task_id}: source taskId not found")
                continue
            src_html = str(by_remote_id[remote_id].get("contentHtml") or "").strip()
            if not src_html:
                not_found += 1
                print(f"SKIP task_id={t.task_id}: empty contentHtml from source")
                continue
            cleaned = clean_html_content(src_html, task_number=6)
            if not cleaned or cleaned == (t.content_html or ""):
                continue
            print(f"{'APPLY' if args.apply else 'DRY'} task_id={t.task_id}: len {len(t.content_html or '')} -> {len(cleaned)}")
            if args.apply:
                t.content_html = cleaned
            updated += 1

        if args.apply:
            db.session.commit()
            print(f"Done: updated={updated}, not_found={not_found}")
        else:
            db.session.rollback()
            print(f"Dry-run: would_update={updated}, not_found={not_found}")
            print("Для применения запустите с --apply")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

