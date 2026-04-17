"""
Нормализация historical заданий в Tasks:
- plain text content_html -> HTML с сохранением переносов;
- attached_files -> единый список dict c ключами name/url/path.

По умолчанию dry-run. Для записи в БД передайте --apply.
"""

import argparse
import io
import json
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


TAG_RE = re.compile(r"<[a-zA-Z!?][^>]*>")


def normalize_task_plain_text_to_html(raw_text: str) -> str:
    text = (raw_text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return '<div class="task-text"></div>'
    escaped = (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
    paragraphs = [p.strip() for p in re.split(r"\n{2,}", escaped) if p.strip()]
    if not paragraphs:
        return '<div class="task-text"></div>'
    html_paragraphs = [f"<p>{paragraph.replace(chr(10), '<br>')}</p>" for paragraph in paragraphs]
    return '<div class="task-text">' + "".join(html_paragraphs) + "</div>"


def normalize_content_html(value: Any) -> str:
    raw = (value or "")
    if not isinstance(raw, str):
        raw = str(raw)
    text = raw.strip()
    if not text:
        return '<div class="task-text"></div>'
    if TAG_RE.search(text):
        return text
    return normalize_task_plain_text_to_html(text)


def normalize_attachments(value: Any) -> list[dict]:
    if not value:
        return []
    data = value
    if isinstance(value, str):
        try:
            data = json.loads(value)
        except Exception:
            return []
    if not isinstance(data, list):
        return []

    out: list[dict] = []
    for item in data:
        if isinstance(item, str):
            url = item.strip()
            if not url:
                continue
            out.append({
                "name": url.split("/")[-1].split("?")[0] or "file",
                "url": url,
            })
            continue
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or item.get("filename") or "").strip()
        path = str(item.get("path") or "").strip()
        url = str(item.get("url") or item.get("href") or "").strip()
        if not (name or path or url):
            continue
        if not name:
            name = (path or url).split("/")[-1].split("?")[0] or "file"
        row = {"name": name}
        if path:
            row["path"] = path.replace("\\", "/")
        if url:
            row["url"] = url
        out.append(row)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Normalize Tasks content_html and attached_files")
    parser.add_argument("--apply", action="store_true", help="Persist changes to DB")
    parser.add_argument("--limit", type=int, default=0, help="Limit number of tasks to scan")
    parser.add_argument("--task-id", type=int, default=0, help="Normalize only one task_id")
    args = parser.parse_args()

    app = create_app()
    scanned = 0
    changed = 0
    changed_content = 0
    changed_attachments = 0

    with app.app_context():
        query = Tasks.query.order_by(Tasks.task_id.asc())
        if args.task_id:
            query = query.filter(Tasks.task_id == args.task_id)
        if args.limit and args.limit > 0:
            query = query.limit(args.limit)
        tasks = query.all()

        for task in tasks:
            scanned += 1
            original_content = task.content_html or ""
            original_attachments_raw = task.attached_files

            normalized_content = normalize_content_html(original_content)
            normalized_attachments = normalize_attachments(original_attachments_raw)
            normalized_attachments_json = json.dumps(normalized_attachments, ensure_ascii=False) if normalized_attachments else None

            task_changed = False
            if normalized_content != original_content:
                task.content_html = normalized_content
                changed_content += 1
                task_changed = True
            if normalized_attachments_json != original_attachments_raw:
                task.attached_files = normalized_attachments_json
                changed_attachments += 1
                task_changed = True
            if task_changed:
                changed += 1

        if args.apply:
            db.session.commit()
        else:
            db.session.rollback()

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"[{mode}] scanned={scanned} changed={changed} content={changed_content} attachments={changed_attachments}")
    if not args.apply:
        print("Ничего не записано. Для применения используйте --apply")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
