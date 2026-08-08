# -*- coding: utf-8 -*-
"""
Запись/обновление строк Tasks из сырого списка kompege (после collect_kompege_listing_raw_items).
Используется локальным парсером (SQLite) и scripts/sync_kege_informatics_bank.py (основная БД).
"""

from __future__ import annotations

import json
from typing import Any, Optional, Tuple

from core.db_models import Tasks, moscow_now


def upsert_kompege_listing_items(
    session: Any,
    page: Any,
    items: list,
    task_number: int,
    task_value_url: str,
    *,
    course_id: Optional[int] = None,
    dry_run: bool = False,
    apply_bank_flags: bool = True,
) -> Tuple[int, int, int]:
    """
    Возвращает (count_added, count_updated, count_skipped) — в dry_run счётчики «как если бы» применили.
    """
    from scraper.kompege_task_meta import kompege_bank_fields_from_item
    from scraper.playwright_parser import (
        MAIN_PAGE_URL,
        SITE_DOMAIN,
        clean_html_content,
        _parse_answer_19_21,
        _split_content_19_21,
    )

    def _full_url(href: str) -> str:
        if not href:
            return href
        if href.startswith("http"):
            return href
        if href.startswith("/"):
            return f"{SITE_DOMAIN}{href}"
        return f"{SITE_DOMAIN}/{href}"

    def _touch_bank_fields(t: Tasks) -> None:
        if not apply_bank_flags:
            return
        t.is_active = True
        t.bank_origin = "scraped"
        if course_id is not None and t.course_id is None:
            t.course_id = course_id

    pre_urls = []
    for it in items:
        if it.get("taskId"):
            pre_urls.append(f"{SITE_DOMAIN}/task?id={it['taskId']}")
    existing_by_url = {}
    if pre_urls:
        try:
            existing_tasks = session.query(Tasks).filter(Tasks.source_url.in_(pre_urls)).all()
            existing_by_url = {t.source_url: t for t in existing_tasks}
        except Exception as e:
            print(f"[kompege_upsert] Предупреждение: пакетный запрос существующих задач: {e}")
            existing_by_url = {}

    existing_by_group = {}
    existing_19_by_source = {}
    if task_number == 19 and pre_urls:
        try:
            site_ids = [it.get("taskId") for it in items if it.get("taskId")]
            if site_ids:
                trio_tasks = session.query(Tasks).filter(
                    Tasks.task_group_id.in_(site_ids),
                    Tasks.task_number.in_([19, 20, 21]),
                ).all()
                for t in trio_tasks:
                    gid = t.task_group_id
                    if gid not in existing_by_group:
                        existing_by_group[gid] = {}
                    existing_by_group[gid][t.task_number] = t
            old_19 = session.query(Tasks).filter(Tasks.source_url.in_(pre_urls), Tasks.task_number == 19).all()
            existing_19_by_source = {t.source_url: t for t in old_19}
        except Exception as e:
            print(f"[kompege_upsert] Предупреждение: тройки 19–21: {e}")

    count_added = 0
    count_skipped = 0
    count_updated = 0
    new_tasks_bulk = []

    for it in items:
        if not it.get("taskId"):
            continue

        content_html = it.get("contentHtml") or ""
        if not content_html or len(content_html.strip()) < 10:
            continue

        real_task_number = task_number
        content_html = clean_html_content(content_html, task_number=real_task_number)
        if not content_html or len(content_html.strip()) < 10:
            continue

        _kege = kompege_bank_fields_from_item(it, content_html=content_html)

        attached_files = []
        for f in it.get("files", []):
            href = f.get("href")
            text = (f.get("text") or "").strip()
            url = _full_url(href)
            name = text if text else (href.split("/")[-1] if href else "")
            if url:
                attached_files.append({"name": name, "url": url})
        attached_files_json = json.dumps(attached_files, ensure_ascii=False) if attached_files else None

        source_url = f"{SITE_DOMAIN}/task?id={it['taskId']}"

        answer = (it.get("answer") or "").strip()
        if not answer and it.get("taskId"):
            try:
                task_page_url = f"{SITE_DOMAIN}/task?id={it['taskId']}"
                page.goto(task_page_url, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(1000)
                answer_selectors = [
                    ".answer",
                    '[class*="answer"]',
                    '[id*="answer"]',
                    ".solution",
                    '[class*="solution"]',
                    'button[onclick*="answer"]',
                    'button[onclick*="Ответ"]',
                ]
                for selector in answer_selectors:
                    try:
                        answer_elem = page.locator(selector).first
                        if answer_elem.count() > 0:
                            answer_text = answer_elem.inner_text(timeout=2000)
                            if answer_text and len(answer_text.strip()) > 0:
                                answer = answer_text.strip()
                                break
                    except Exception:
                        continue
                if not answer:
                    try:
                        show_answer_btn = page.locator(
                            'button:has-text("Показать ответ"), button:has-text("показать ответ"), button[onclick*="answer"]'
                        ).first
                        if show_answer_btn.count() > 0:
                            show_answer_btn.click()
                            page.wait_for_timeout(500)
                            for selector in answer_selectors:
                                try:
                                    answer_elem = page.locator(selector).first
                                    if answer_elem.count() > 0:
                                        answer_text = answer_elem.inner_text(timeout=2000)
                                        if answer_text and len(answer_text.strip()) > 0:
                                            answer = answer_text.strip()
                                            break
                                except Exception:
                                    continue
                    except Exception:
                        pass
                page.goto(f"{MAIN_PAGE_URL}?tasktype={task_value_url}", wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(500)
            except Exception as e:
                print(f"[kompege_upsert] Предупреждение: ответ для {it.get('taskId')}: {e}")

        if task_number == 19:
            answer_lines = _parse_answer_19_21(answer)
            content_19, content_20, content_21 = _split_content_19_21(content_html)
            if not content_20 and not content_21:
                content_20 = content_21 = content_html
            elif not content_20:
                content_20 = content_html
            elif not content_21:
                content_21 = content_html
            group_id = str(it.get("taskId") or "")
            group_tasks = existing_by_group.get(group_id, {})
            old_single_19 = existing_19_by_source.get(source_url)
            contents_by_num = {19: content_19, 20: content_20, 21: content_21}

            if len(group_tasks) >= 3:
                any_updated = False
                for num in (19, 20, 21):
                    t = group_tasks.get(num)
                    if t:
                        part = contents_by_num.get(num) or content_html
                        if t.content_html != part:
                            t.content_html = part
                            t.last_scraped = moscow_now()
                            any_updated = True
                        if t.attached_files != attached_files_json:
                            t.attached_files = attached_files_json
                            t.last_scraped = moscow_now()
                            any_updated = True
                        ans = answer_lines[num - 19] if num - 19 < len(answer_lines) else ""
                        if ans and t.answer != ans:
                            t.answer = ans
                            t.last_scraped = moscow_now()
                            any_updated = True
                        if (
                            t.kege_source_tag != _kege["kege_source_tag"]
                            or t.kege_difficulty_tier != _kege["kege_difficulty_tier"]
                            or t.difficulty_level != _kege["difficulty_level"]
                        ):
                            t.kege_source_tag = _kege["kege_source_tag"]
                            t.kege_difficulty_tier = _kege["kege_difficulty_tier"]
                            t.difficulty_level = _kege["difficulty_level"]
                            t.last_scraped = moscow_now()
                            any_updated = True
                        _touch_bank_fields(t)
                if any_updated:
                    count_updated += 1
                else:
                    count_skipped += 1
            elif old_single_19:
                old_single_19.content_html = content_19
                old_single_19.attached_files = attached_files_json
                old_single_19.answer = answer_lines[0] if answer_lines else None
                old_single_19.task_group_id = group_id
                old_single_19.site_task_id = it.get("taskId")
                old_single_19.kege_source_tag = _kege["kege_source_tag"]
                old_single_19.kege_difficulty_tier = _kege["kege_difficulty_tier"]
                old_single_19.difficulty_level = _kege["difficulty_level"]
                old_single_19.last_scraped = moscow_now()
                _touch_bank_fields(old_single_19)
                session.add(old_single_19)
                count_updated += 1
                for sub_num, ans in [
                    (20, answer_lines[1] if len(answer_lines) > 1 else ""),
                    (21, answer_lines[2] if len(answer_lines) > 2 else ""),
                ]:
                    kw = dict(
                        task_number=sub_num,
                        task_group_id=group_id,
                        site_task_id=it.get("taskId"),
                        source_url=source_url,
                        content_html=contents_by_num.get(sub_num) or content_html,
                        answer=ans or None,
                        attached_files=attached_files_json,
                        last_scraped=moscow_now(),
                    )
                    if apply_bank_flags:
                        kw["course_id"] = course_id
                        kw["bank_origin"] = "scraped"
                        kw["is_active"] = True
                    kw.update(_kege)
                    new_tasks_bulk.append(Tasks(**kw))
                count_added += 2
            else:
                for sub_num, ans in [
                    (19, answer_lines[0] if answer_lines else ""),
                    (20, answer_lines[1] if len(answer_lines) > 1 else ""),
                    (21, answer_lines[2] if len(answer_lines) > 2 else ""),
                ]:
                    kw = dict(
                        task_number=sub_num,
                        task_group_id=group_id,
                        site_task_id=it.get("taskId"),
                        source_url=source_url,
                        content_html=contents_by_num.get(sub_num) or content_html,
                        answer=ans or None,
                        attached_files=attached_files_json,
                        last_scraped=moscow_now(),
                    )
                    if apply_bank_flags:
                        kw["course_id"] = course_id
                        kw["bank_origin"] = "scraped"
                        kw["is_active"] = True
                    kw.update(_kege)
                    new_tasks_bulk.append(Tasks(**kw))
                count_added += 3
            continue

        existing_task = existing_by_url.get(source_url)
        if existing_task:
            updated = False
            if existing_task.content_html != content_html:
                existing_task.content_html = content_html
                existing_task.last_scraped = moscow_now()
                updated = True
            if existing_task.attached_files != attached_files_json:
                existing_task.attached_files = attached_files_json
                existing_task.last_scraped = moscow_now()
                updated = True
            if answer and existing_task.answer != answer:
                existing_task.answer = answer
                existing_task.last_scraped = moscow_now()
                updated = True
            if it.get("taskId") and not existing_task.site_task_id:
                existing_task.site_task_id = it.get("taskId")
                updated = True
            if (
                existing_task.kege_source_tag != _kege["kege_source_tag"]
                or existing_task.kege_difficulty_tier != _kege["kege_difficulty_tier"]
                or existing_task.difficulty_level != _kege["difficulty_level"]
            ):
                existing_task.kege_source_tag = _kege["kege_source_tag"]
                existing_task.kege_difficulty_tier = _kege["kege_difficulty_tier"]
                existing_task.difficulty_level = _kege["difficulty_level"]
                existing_task.last_scraped = moscow_now()
                updated = True
            _touch_bank_fields(existing_task)
            if updated:
                count_updated += 1
            else:
                count_skipped += 1
        else:
            kw = dict(
                task_number=real_task_number,
                site_task_id=it.get("taskId"),
                source_url=source_url,
                content_html=content_html,
                answer=answer if answer else None,
                attached_files=attached_files_json,
                last_scraped=moscow_now(),
            )
            if apply_bank_flags:
                kw["course_id"] = course_id
                kw["bank_origin"] = "scraped"
                kw["is_active"] = True
            kw.update(_kege)
            new_tasks_bulk.append(Tasks(**kw))
            count_added += 1

    if dry_run:
        session.rollback()
        return count_added, count_updated, count_skipped

    if new_tasks_bulk:
        try:
            session.bulk_save_objects(new_tasks_bulk)
        except Exception as e:
            print(f"[kompege_upsert] Пакетная вставка не удалась, по одной: {e}")
            for obj in new_tasks_bulk:
                session.add(obj)

    try:
        session.commit()
    except Exception as e:
        print(f"[kompege_upsert] Ошибка commit: {e}")
        session.rollback()
        raise

    return count_added, count_updated, count_skipped
