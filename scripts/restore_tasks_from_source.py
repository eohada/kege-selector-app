#!/usr/bin/env python3
"""
Восстановление content_html задач из источника kompege по source_url (?id=...).

Использование:
  python scripts/restore_tasks_from_source.py --task-ids 6039,6065,6118,4684,6203 --dry-run
  python scripts/restore_tasks_from_source.py --task-ids 6039,6065,6118,4684,6203 --apply
"""
from __future__ import annotations

import argparse
import io
import os
import re
import sys
from collections import defaultdict

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import create_app, db  # noqa: E402
from app.models import Tasks  # noqa: E402
from scraper.playwright_parser import fetch_kompege_listing_from_api  # noqa: E402


TASK_ID_RE = re.compile(r"[?&]id=(\d+)")


def _parse_ids(raw: str) -> list[int]:
    out: list[int] = []
    for part in (raw or "").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            out.append(int(part))
        except ValueError:
            pass
    return out


def _source_task_id(source_url: str | None) -> str | None:
    if not source_url:
        return None
    m = TASK_ID_RE.search(source_url)
    return m.group(1) if m else None


def main() -> int:
    parser = argparse.ArgumentParser(description="Restore selected tasks content_html from kompege API")
    parser.add_argument("--task-ids", required=True, help="Comma-separated local task_id list")
    parser.add_argument("--apply", action="store_true", help="Persist changes")
    parser.add_argument("--dry-run", action="store_true", help="Show planned updates only")
    args = parser.parse_args()

    task_ids = _parse_ids(args.task_ids)
    if not task_ids:
        print("Пустой список --task-ids")
        return 1
    if args.apply and args.dry_run:
        print("Укажите только один режим: --apply или --dry-run")
        return 1

    app = create_app()
    with app.app_context():
        rows = Tasks.query.filter(Tasks.task_id.in_(task_ids)).all()
        by_number: dict[int, list[Tasks]] = defaultdict(list)
        for row in rows:
            by_number[int(row.task_number)].append(row)

        updated = 0
        skipped = 0
        for task_number, tasks in sorted(by_number.items()):
            remote_items = fetch_kompege_listing_from_api(task_number) or []
            remote_by_id = {}
            for item in remote_items:
                rid = str(item.get("taskId") or "").strip()
                if rid:
                    remote_by_id[rid] = item
            print(f"task_number={task_number}: remote_items={len(remote_by_id)} local={len(tasks)}")

            for t in tasks:
                rid = _source_task_id(t.source_url)
                if not rid or rid not in remote_by_id:
                    skipped += 1
                    print(f"  SKIP task_id={t.task_id}: source id not found")
                    continue
                src_html = (remote_by_id[rid].get("contentHtml") or "").strip()
                if not src_html:
                    skipped += 1
                    print(f"  SKIP task_id={t.task_id}: empty source html")
                    continue
                if src_html == (t.content_html or ""):
                    print(f"  SAME task_id={t.task_id}: unchanged")
                    continue
                print(
                    f"  {'APPLY' if args.apply else 'DRY'} task_id={t.task_id}: "
                    f"len {len(t.content_html or '')} -> {len(src_html)}"
                )
                if args.apply:
                    t.content_html = src_html
                updated += 1

        if args.apply:
            db.session.commit()
            print(f"Done: updated={updated}, skipped={skipped}")
        else:
            db.session.rollback()
            print(f"Dry-run: would_update={updated}, skipped={skipped}")
            print("Для применения используйте --apply")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

