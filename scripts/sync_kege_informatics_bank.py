#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Синхронизация банка ЕГЭ информатики с kompege.ru в основную БД приложения.

Перед первым прогоном сделайте резервную копию БД:
  PostgreSQL: pg_dump ... > backup.sql
  SQLite: скопируйте файл базы.

Флаги:
  --dry-run       только отчёт (без commit в БД и без скачивания файлов)
  --backup-only   вывести напоминание о бэкапе и выйти
  --no-soft-delete  не помечать is_active=False у записей вне whitelist-пула
  --skip-attachments  не скачивать вложения на диск после upsert
  --tasks 1,2,19   только указанные номера заданий (подмножество TASKS_TO_SCRAPE)
  --debug-dom       дамп DOM только если после collect список пуст (диагностика «0 записей»)
  --whitelist-only  импорт только заданий с comment/details по scraper/kege_whitelist.py (узкий пул)
                    по умолчанию импортируются все задачи API; источник и уровень 1–3 пишутся в Tasks.kege_*

Требует: playwright + chromium (playwright install chromium).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import time

import requests

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

ATTACHMENTS_URL_PREFIX = "/attachments/task"


def _safe_filename(name: str) -> str:
    if not name:
        return "file"
    name = re.sub(r"[^\w\s.\-]", "_", name)
    return name.strip() or "file"


def _run_backup_hint_only() -> int:
    print(
        "Сделайте полный бэкап БД перед синхронизацией:\n"
        "  • PostgreSQL: pg_dump \"$DATABASE_URL\" > kege_bank_backup.sql\n"
        "  • SQLite: copy файл *.db в безопасное место\n"
        "Затем запустите этот скрипт без --backup-only."
    )
    return 0


def _maybe_sqlite_file_copy(app) -> None:
    uri = (app.config.get("SQLALCHEMY_DATABASE_URI") or "").strip()
    if not uri.startswith("sqlite:///"):
        return
    path = uri.replace("sqlite:///", "", 1)
    if not os.path.isfile(path):
        return
    bak = path + ".pre_kege_sync.bak"
    try:
        shutil.copy2(path, bak)
        print(f"[backup] SQLite скопирован: {bak}")
    except OSError as e:
        print(f"[backup] Не удалось скопировать SQLite: {e}")


def _download_attachments_for_tasks(app, dry_run: bool) -> None:
    from app.models import db, Tasks

    custom_root = (app.config.get("TASK_ATTACHMENTS_ROOT") or "").strip().rstrip(os.sep) or None
    if custom_root and os.path.isdir(custom_root):
        base_dir = custom_root
    else:
        root = app.root_path or _REPO_ROOT
        base_dir = os.path.join(root, "uploads", "task_attachments")

    os.makedirs(base_dir, exist_ok=True)

    q = Tasks.query.filter(Tasks.attached_files.isnot(None)).filter(Tasks.source_url.like("%kompege.ru%"))
    tasks = q.order_by(Tasks.task_id.asc()).all()
    for task in tasks:
        try:
            files = json.loads(task.attached_files or "[]")
        except Exception:
            continue
        if not files:
            continue

        task_dir = os.path.join(base_dir, str(task.task_id))
        if not dry_run:
            os.makedirs(task_dir, exist_ok=True)

        changed = False
        new_files = []
        for f in files:
            if not isinstance(f, dict):
                new_files.append(f)
                continue
            url = (f.get("url") or f.get("href") or "").strip()
            if not url:
                new_files.append(f)
                continue
            if url.startswith("//"):
                url = "https:" + url
            elif url.startswith("/"):
                url = "https://kompege.ru" + url
            if not (url.startswith("https://kompege.ru") or url.startswith("http://kompege.ru")):
                new_files.append(f)
                continue
            if f.get("path") and str(f.get("path", "")).startswith(ATTACHMENTS_URL_PREFIX):
                new_files.append(f)
                continue

            name = (f.get("name") or f.get("text") or url.split("/")[-1].split("?")[0] or "file").strip()
            safe_name = _safe_filename(name)
            try:
                r = requests.get(
                    url,
                    stream=True,
                    timeout=45,
                    headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
                )
                r.raise_for_status()
                data = r.content
            except Exception as e:
                print(f"  [attach] task_id={task.task_id} skip {url}: {e}")
                new_files.append(f)
                continue

            h8 = hashlib.sha256(data).hexdigest()[:8]
            ext = os.path.splitext(safe_name)[1] or ""
            stored = f"kege_{h8}{ext}" if ext else f"kege_{h8}"
            local_path = os.path.join(task_dir, stored)
            rel_path = f"{ATTACHMENTS_URL_PREFIX}/{task.task_id}/{stored}"

            if dry_run:
                print(f"  [dry-run] task_id={task.task_id} -> {rel_path}")
                new_entry = dict(f)
                new_entry["path"] = rel_path
                new_entry["url"] = url
                new_entry["name"] = name
                new_files.append(new_entry)
                changed = True
                continue

            try:
                with open(local_path, "wb") as out:
                    out.write(data)
            except OSError as e:
                print(f"  [attach] task_id={task.task_id} write fail: {e}")
                new_files.append(f)
                continue

            new_entry = dict(f)
            new_entry["path"] = rel_path
            new_entry["url"] = url
            new_entry["name"] = name
            new_files.append(new_entry)
            changed = True
            time.sleep(0.25)

        if changed and not dry_run:
            task.attached_files = json.dumps(new_files, ensure_ascii=False)
            db.session.add(task)
    if not dry_run:
        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            print(f"[attach] commit error: {e}")


def _soft_delete_stale(
    app,
    ege_id: int,
    active_kege_ids: set[str],
    dry_run: bool,
) -> int:
    from sqlalchemy import and_, or_
    from app.models import db, Tasks

    if not active_kege_ids:
        print("[soft-delete] Пустой пул kege_id после whitelist — пропуск (защита от массового отключения).")
        return 0

    scoped = and_(
        Tasks.course_id == ege_id,
        or_(Tasks.bank_origin.is_(None), Tasks.bank_origin != "manual"),
        or_(
            Tasks.source_url.like("%kompege.ru%"),
            Tasks.bank_origin == "scraped",
        ),
    )

    stale_triplets = Tasks.query.filter(
        scoped,
        Tasks.task_number.in_([19, 20, 21]),
        Tasks.task_group_id.isnot(None),
        ~Tasks.task_group_id.in_(active_kege_ids),
    )
    stale_rest = Tasks.query.filter(
        scoped,
        ~Tasks.task_number.in_([19, 20, 21]),
        Tasks.site_task_id.isnot(None),
        ~Tasks.site_task_id.in_(active_kege_ids),
    )

    n = 0
    if dry_run:
        n = stale_triplets.count() + stale_rest.count()
        print(f"[soft-delete] dry-run: пометили бы is_active=False для ~{n} строк")
        return n

    updated = 0
    for q in (stale_triplets, stale_rest):
        for t in q.all():
            t.is_active = False
            db.session.add(t)
            updated += 1
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"[soft-delete] commit error: {e}")
        raise
    print(f"[soft-delete] is_active=False для {updated} строк вне актуального whitelist-пула")
    return updated


def main() -> int:
    parser = argparse.ArgumentParser(description="Синхронизация банка КЕГЭ с основной БД")
    parser.add_argument("--dry-run", action="store_true", help="Без записи в БД и без файлов")
    parser.add_argument("--backup-only", action="store_true", help="Только текст про бэкап")
    parser.add_argument("--no-soft-delete", action="store_true")
    parser.add_argument(
        "--whitelist-only",
        action="store_true",
        help="Только строки с метками источника из kege_whitelist.py (узкий пул); иначе — все задачи из API",
    )
    parser.add_argument("--skip-attachments", action="store_true")
    parser.add_argument("--tasks", type=str, default="", help="Например: 1,2,19,27")
    parser.add_argument("--no-playwright-delay", action="store_true", help="Не ждать между типами заданий")
    parser.add_argument(
        "--debug-dom",
        action="store_true",
        help="Если collect вернул пустой список — дамп фреймов/tr/href (при успешном API дамп не выводится)",
    )
    args = parser.parse_args()

    if args.backup_only:
        return _run_backup_hint_only()

    task_filter: set[int] | None = None
    if (args.tasks or "").strip():
        task_filter = set()
        for part in str(args.tasks).split(","):
            part = part.strip()
            if part.isdigit():
                task_filter.add(int(part))

    from app import create_app
    from app.models import db
    from app.utils.db_migrations import ensure_schema_columns
    from core.db_models import Course, Tasks
    from playwright.sync_api import sync_playwright
    from playwright_stealth import Stealth
    from scraper.kege_whitelist import details_passes_whitelist
    from scraper.kompege_upsert import upsert_kompege_listing_items
    from scraper.playwright_parser import (
        TASKS_TO_SCRAPE,
        MAIN_PAGE_URL,
        USER_AGENT as PW_UA,
        check_robots_txt,
        collect_kompege_listing_raw_items,
        CRAWL_DELAY_SEC,
    )
    try:
        from scraper.playwright_parser import debug_kompege_listing_page as _debug_kompege_listing_page
    except ImportError:
        _debug_kompege_listing_page = None  # type: ignore[misc,assignment]

    app = create_app()
    with app.app_context():
        ensure_schema_columns(app)
        _maybe_sqlite_file_copy(app)

        ege = Course.query.filter_by(slug="ege_informatics").first()
        if not ege:
            print("Курс ege_informatics не найден в ExamCourses. Создайте курс или проверьте БД.")
            return 2

        if not check_robots_txt():
            print("robots.txt запретил обход — остановка.")
            return 3

        # Подтянуть site_task_id из source_url, если пусто
        if not args.dry_run:
            import re as _re

            pat = _re.compile(r"[?&]id=(\d+)")
            touched = 0
            for t in Tasks.query.filter(Tasks.course_id == ege.id).all():
                if (t.site_task_id or "").strip():
                    continue
                su = (t.source_url or "").strip()
                m = pat.search(su)
                if m:
                    t.site_task_id = m.group(1)
                    db.session.add(t)
                    touched += 1
            if touched:
                try:
                    db.session.commit()
                    print(f"[backfill] site_task_id заполнен для {touched} строк")
                except Exception as e:
                    db.session.rollback()
                    print(f"[backfill] commit: {e}")

        active_kege_ids: set[str] = set()
        stealth = Stealth()
        with stealth.use_sync(sync_playwright()) as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(user_agent=PW_UA)
            page = context.new_page()
            page.goto(MAIN_PAGE_URL, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(3000)

            dropdown_found = False
            for selector in [
                "select",
                "select[name='tasktype']",
                "select#tasktype",
                "select.tasktype",
            ]:
                try:
                    if page.locator(selector).count() > 0:
                        page.wait_for_selector(selector, state="visible", timeout=10000)
                        dropdown_found = True
                        break
                except Exception:
                    continue
            if not dropdown_found:
                print("Не удалось найти выпадающий список на kompege.ru/task")
                browser.close()
                return 4

            total_added = total_updated = total_skipped = 0
            debug_dom_once = False
            for task_num, task_val in TASKS_TO_SCRAPE.items():
                if task_filter is not None and task_num not in task_filter:
                    continue
                raw = collect_kompege_listing_raw_items(page, task_num, task_val)
                if (
                    args.debug_dom
                    and not debug_dom_once
                    and raw is not None
                    and len(raw) == 0
                ):
                    if _debug_kompege_listing_page is None:
                        print(
                            "--debug-dom: в контейнере старый код без debug_kompege_listing_page. "
                            "Сделайте git pull и пересоберите образ web_prod, затем повторите команду."
                        )
                        browser.close()
                        return 8
                    _debug_kompege_listing_page(page)
                    debug_dom_once = True
                if raw is None:
                    continue
                if args.whitelist_only:
                    empty_details = sum(
                        1 for it in raw if not str(it.get("details") or "").strip()
                    )
                    filtered = [it for it in raw if details_passes_whitelist(it.get("details"))]
                    no_substring = len(raw) - empty_details - len(filtered)
                    print(
                        f"[whitelist-only] тип {task_num}: всего {len(raw)}, в пул {len(filtered)} "
                        f"(пустой comment/details: {empty_details}, "
                        f"есть текст, нет подстроки из whitelist: {no_substring})"
                    )
                else:
                    filtered = list(raw)
                    print(f"[sync] тип {task_num}: в пул импорта {len(filtered)} задач (все из API)")
                for it in filtered:
                    if it.get("taskId"):
                        active_kege_ids.add(str(it["taskId"]))
                if not filtered:
                    if not args.no_playwright_delay:
                        time.sleep(CRAWL_DELAY_SEC)
                    continue
                added, upd, skip = upsert_kompege_listing_items(
                    db.session,
                    page,
                    filtered,
                    task_num,
                    task_val,
                    course_id=ege.id,
                    dry_run=args.dry_run,
                )
                total_added += added
                total_updated += upd
                total_skipped += skip
                if not args.no_playwright_delay:
                    time.sleep(CRAWL_DELAY_SEC)

            browser.close()

        print(
            f"[summary] добавлено~{total_added}, обновлено~{total_updated}, пропущено~{total_skipped} "
            f"(dry_run={args.dry_run}); активных kege id в пуле: {len(active_kege_ids)}"
        )

        if not args.no_soft_delete and not args.dry_run:
            _soft_delete_stale(app, ege.id, active_kege_ids, dry_run=False)
        elif not args.no_soft_delete and args.dry_run:
            _soft_delete_stale(app, ege.id, active_kege_ids, dry_run=True)

        if not args.skip_attachments:
            _download_attachments_for_tasks(app, dry_run=args.dry_run)

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nПрервано пользователем.")
        raise SystemExit(130)
