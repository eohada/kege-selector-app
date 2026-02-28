#!/usr/bin/env python3
"""
Разрезка контента у уже сохранённых троек заданий 19–20–21 по маркерам «Задание 20.» и «Задание 21.».
Обновляет content_html у каждой записи в БД: задание 19 — до «Задание 20.»; 20 — между маркерами; 21 — после «Задание 21.»

Запуск (из корня проекта):
  python scripts/split_task_19_21_content.py [--dry-run] [--verbose]
"""
from __future__ import annotations

import os
import re
import sys
from collections import defaultdict

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


def _split_content_19_21(full_html: str):
    """
    Разрезает общий HTML заданий 19–21 на три части по маркерам «Задание 20.» и «Задание 21.».
    Возвращает (html_19, html_20, html_21).
    """
    if not full_html or not full_html.strip():
        return ('', '', '')
    text = full_html
    mark_20 = re.compile(r'Задание\s+20\s*\.', re.IGNORECASE)
    mark_21 = re.compile(r'Задание\s+21\s*\.', re.IGNORECASE)
    m20 = mark_20.search(text)
    m21 = mark_21.search(text)
    if not m20 and not m21:
        return (full_html.strip(), '', '')
    pos_20 = m20.start() if m20 else len(text)
    pos_21 = m21.start() if m21 else len(text)
    if pos_20 <= pos_21:
        part_19 = text[:pos_20].strip()
        part_20 = text[pos_20:pos_21].strip() if pos_21 < len(text) else text[pos_20:].strip()
        part_21 = text[pos_21:].strip() if pos_21 < len(text) else ''
    else:
        part_19 = text[:pos_21].strip()
        part_20 = ''
        part_21 = text[pos_21:].strip()
    return (part_19, part_20, part_21)


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Разрезать контент троек 19–20–21 по маркерам')
    parser.add_argument('--dry-run', action='store_true', help='Не сохранять в БД, только показать план')
    parser.add_argument('--verbose', '-v', action='store_true', help='Подробный вывод')
    args = parser.parse_args()

    from app import create_app
    from app.models import db, Tasks

    app = create_app()
    with app.app_context():
        # Все задания 19, 20, 21 с заданным task_group_id
        tasks = Tasks.query.filter(
            Tasks.task_number.in_([19, 20, 21]),
            Tasks.task_group_id.isnot(None),
            (Tasks.task_group_id != ''),
        ).order_by(Tasks.task_group_id, Tasks.task_number).all()

        by_group = defaultdict(dict)
        for t in tasks:
            gid = (t.task_group_id or '').strip()
            if gid:
                by_group[gid][t.task_number] = t

        # Полные тройки (19, 20, 21 есть в группе)
        triplets = [(gid, by_group[gid]) for gid in by_group if set(by_group[gid]) >= {19, 20, 21}]
        # Одиночные 19 с task_group_id — обновим только content у 19 до «Задание 20.»
        solo_19 = [(gid, by_group[gid]) for gid in by_group if by_group[gid].keys() == {19}]
        print(f'Полных троек 19–20–21: {len(triplets)}, одиночных 19 с group_id: {len(solo_19)}')

        updated = 0
        skipped = 0
        errors = 0

        for gid, group in triplets:
            t19 = group.get(19)
            t20 = group.get(20)
            t21 = group.get(21)
            if not t19 or not t20 or not t21:
                skipped += 1
                continue
            # Берём самый длинный контент как «полный» (часто все три одинаковые)
            full_html = t19.content_html or ''
            for t in (t20, t21):
                ct = (t.content_html or '')
                if len(ct) > len(full_html):
                    full_html = ct
            if not full_html.strip():
                if args.verbose:
                    print(f'  group_id={gid}: пустой контент, пропуск')
                skipped += 1
                continue

            part_19, part_20, part_21 = _split_content_19_21(full_html)
            if not part_20 and not part_21:
                if args.verbose:
                    print(f'  group_id={gid}: маркеры «Задание 20.»/«21.» не найдены, пропуск')
                skipped += 1
                continue

            changed = False
            if (t19.content_html or '').strip() != (part_19 or '').strip():
                t19.content_html = part_19 or None
                changed = True
            if (t20.content_html or '').strip() != (part_20 or '').strip():
                t20.content_html = part_20 or None
                changed = True
            if (t21.content_html or '').strip() != (part_21 or '').strip():
                t21.content_html = part_21 or None
                changed = True

            if changed:
                if args.verbose:
                    print(f'  group_id={gid}: task_id 19={t19.task_id}, 20={t20.task_id}, 21={t21.task_id} — обновлено')
                if not args.dry_run:
                    try:
                        db.session.add(t19)
                        db.session.add(t20)
                        db.session.add(t21)
                    except Exception as e:
                        print(f'  Ошибка group_id={gid}: {e}')
                        errors += 1
                        db.session.rollback()
                        continue
                updated += 1

        for gid, group in solo_19:
            t19 = group.get(19)
            if not t19:
                continue
            full_html = (t19.content_html or '').strip()
            if not full_html:
                skipped += 1
                continue
            part_19, part_20, part_21 = _split_content_19_21(full_html)
            if not part_20 and not part_21:
                skipped += 1
                continue
            if (t19.content_html or '').strip() != (part_19 or '').strip():
                t19.content_html = part_19 or None
                if args.verbose:
                    print(f'  group_id={gid} (только 19): task_id={t19.task_id} — обновлён до «Задание 20.»')
                if not args.dry_run:
                    try:
                        db.session.add(t19)
                    except Exception as e:
                        print(f'  Ошибка group_id={gid}: {e}')
                        errors += 1
                        db.session.rollback()
                        continue
                updated += 1

        if not args.dry_run and updated > 0:
            try:
                db.session.commit()
            except Exception as e:
                print(f'Ошибка commit: {e}')
                db.session.rollback()
                return 1

        print(f'Обновлено записей/троек: {updated}, пропущено: {skipped}, ошибок: {errors}')
        if args.dry_run and updated > 0:
            print('(dry-run: изменения не сохранены)')
        return 0 if errors == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
