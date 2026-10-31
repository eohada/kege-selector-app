#!/usr/bin/env python3
"""CLI utility for Multi-Teacher schedule historical data backfill.

Sprint 2.2:
Usage:
  # Dry-run (Default, read-only):
  python scripts/backfill_multi_teacher_lessons.py --dry-run

  # Export JSON audit report:
  python scripts/backfill_multi_teacher_lessons.py --dry-run --json-output reports/backfill_audit.json

  # Controlled application on isolated database (DO NOT run on production/user DB):
  python scripts/backfill_multi_teacher_lessons.py --apply --confirm-isolated-db
"""
from __future__ import annotations

import argparse
import json
import os
import sys

# Ensure project root is in PYTHONPATH
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import create_app
from app.schedule.backfill_service import execute_historical_backfill


def main():
    parser = argparse.ArgumentParser(description="Multi-Teacher Schedule Historical Backfill CLI")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Run in dry-run simulation mode without modifying database (Default).",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply updates to database (Default is dry-run mode).",
    )
    parser.add_argument(
        "--confirm-isolated-db",
        action="store_true",
        help="Explicit confirmation that this is an isolated development/test environment.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=500,
        help="Batch size for database commits (default: 500).",
    )
    parser.add_argument(
        "--json-output",
        type=str,
        default=None,
        help="Path to save structured JSON report.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print detailed record-by-record output to stdout.",
    )

    args = parser.parse_args()

    # Fail-closed guard: Disallow --apply without explicit confirmation
    if args.apply and not args.confirm_isolated_db:
        print(
            "ERROR: --apply requires --confirm-isolated-db. "
            "Running backfill with writes on unconfirmed databases is blocked.",
            file=sys.stderr,
        )
        sys.exit(1)

    app = create_app()
    with app.app_context():
        from app.models import db
        from sqlalchemy import inspect as sa_inspect
        inspector = sa_inspect(db.engine)
        table_names = {t.lower() for t in inspector.get_table_names()}
        if "lessons" not in table_names:
            db.create_all()

        is_dry_run = not args.apply
        print(f"=== Multi-Teacher Schedule Backfill [{ 'DRY-RUN (READ-ONLY)' if is_dry_run else 'APPLY MODE' }] ===")

        report = execute_historical_backfill(
            dry_run=is_dry_run,
            batch_size=args.batch_size,
        )

        summary = report.to_dict()["summary"]
        print("-" * 60)
        print(f"Всего уроков проанализировано:        {summary['total_examined']}")
        print(f"Уже имели teacher_id:                {summary['already_resolved']}")
        print(f"Категория 1 (Единственный тьютор):   {summary['cat1_single_tutor_count']}")
        print(f"Категория 2 (Подтверждено артефактом):{summary['cat2_artifact_confirmed_count']}")
        print(f"Категория 3 (Несколько кандидатов):  {summary['cat3_multiple_candidates_count']} (оставлен NULL)")
        print(f"Категория 4 (Тьютор не найден):      {summary['cat4_no_teacher_found_count']} (оставлен NULL)")
        print(f"Категория 5 (Противоречивые данные): {summary['cat5_contradictory_data_count']} (оставлен NULL)")
        print("-" * 60)
        print(f"ИТОГО достоверно разрешено:          {summary['total_confidently_resolved']}")
        print(f"ИТОГО сохранено NULL:                {summary['total_retained_null']}")
        print(f"Статус записи в БД:                  {'БЕЗ ИЗМЕНЕНИЙ (DRY-RUN)' if is_dry_run else 'ИЗМЕНЕНИЯ ПРИМЕНЕНЫ'}")
        print("-" * 60)

        if args.verbose:
            for rec in report.records:
                print(
                    f"[{rec.category}] Lesson #{rec.lesson_id} -> "
                    f"Teacher #{rec.candidate_teacher_id} ({rec.candidate_teacher_name or 'N/A'}), "
                    f"Subject: {rec.subject}. Reason: {rec.resolution_reason}"
                )

        if args.json_output:
            os.makedirs(os.path.dirname(os.path.abspath(args.json_output)), exist_ok=True)
            with open(args.json_output, "w", encoding="utf-8") as f:
                json.dump(report.to_dict(), f, ensure_ascii=False, indent=2)
            print(f"Подробный отчет сохранен в: {args.json_output}")


if __name__ == "__main__":
    main()
