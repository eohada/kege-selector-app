#!/usr/bin/env python3
"""
scripts/audit_timezone_dry_run.py

Read-only audit script for database timezones.
Analyzes timestamps and timezones across User profiles, Lessons, Assignments, and Submissions.
NEVER mutates data. Provides a dry-run migration report with sample projections.
"""

import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from datetime import datetime, timezone
from app import create_app
from core.db_models import db, User, UserProfile
from app.models import Lesson, Assignment, Submission
from app.utils.timezone import (
    UTC,
    LEGACY_TIMEZONE_NAME,
    is_valid_timezone,
    canonical_timezone_name,
    format_utc_iso_z,
    to_utc_instant,
    to_viewer_tz,
)


def run_audit(sample_limit: int = 5):
    app = create_app()
    with app.app_context():
        dialect = db.engine.dialect.name
        print("=" * 80)
        print("BOOSTUDY TIMEZONE DRY-RUN AUDIT REPORT")
        print(f"Database dialect: {dialect} | URL: {db.engine.url}")
        print(f"Timestamp: {datetime.now(timezone.utc).isoformat()} (UTC)")
        print("=" * 80)

        # ---------------------------------------------------------
        # 1. USER PROFILES TIMEZONE AUDIT
        # ---------------------------------------------------------
        print("\n[1] USER PROFILES TIMEZONE AUDIT")
        print("-" * 50)
        users = User.query.all()
        total_users = len(users)
        tz_counts = {}
        legacy_tz_count = 0
        canonical_tz_count = 0
        null_tz_count = 0
        unknown_tz_count = 0

        legacy_map = {'moscow': 'Europe/Moscow', 'tomsk': 'Asia/Tomsk'}

        for u in users:
            tz_val = None
            if hasattr(u, 'profile') and u.profile and u.profile.timezone:
                tz_val = u.profile.timezone.strip()
            elif hasattr(u, 'timezone') and u.timezone:
                tz_val = u.timezone.strip()

            if not tz_val:
                null_tz_count += 1
                tz_counts['(null / empty)'] = tz_counts.get('(null / empty)', 0) + 1
            else:
                tz_counts[tz_val] = tz_counts.get(tz_val, 0) + 1
                if tz_val.lower() in legacy_map:
                    legacy_tz_count += 1
                elif is_valid_timezone(tz_val):
                    canonical_tz_count += 1
                else:
                    unknown_tz_count += 1

        print(f"Total Users: {total_users}")
        print(f"  - Canonical IANA Timezones: {canonical_tz_count}")
        print(f"  - Legacy Timezone Strings:  {legacy_tz_count}")
        print(f"  - Unset / NULL (defaults to Europe/Moscow): {null_tz_count}")
        print(f"  - Unknown / Invalid:        {unknown_tz_count}")
        print("\nTimezone Distribution:")
        for tz_name, count in sorted(tz_counts.items(), key=lambda x: x[1], reverse=True):
            status = "Valid IANA" if is_valid_timezone(tz_name) else ("Legacy alias" if tz_name.lower() in legacy_map else "Fallback")
            print(f"  * {tz_name:25s} : {count:4d} users  [{status}]")

        # ---------------------------------------------------------
        # 2. LESSONS AUDIT
        # ---------------------------------------------------------
        print("\n[2] LESSONS AUDIT (Lesson.lesson_date)")
        print("-" * 50)
        lessons = Lesson.query.all()
        total_lessons = len(lessons)
        null_lessons = 0
        naive_lessons = 0
        aware_lessons = 0
        sample_lessons = []

        for l in lessons:
            dt = l.lesson_date
            if dt is None:
                null_lessons += 1
                continue
            if getattr(dt, 'tzinfo', None) is not None:
                aware_lessons += 1
            else:
                naive_lessons += 1

            if len(sample_lessons) < sample_limit:
                utc_dt = to_utc_instant(dt, assume_utc_if_naive=True)
                msk_dt = to_viewer_tz(utc_dt, 'Europe/Moscow')
                tomsk_dt = to_viewer_tz(utc_dt, 'Asia/Tomsk')
                sample_lessons.append({
                    'id': l.lesson_id,
                    'topic': (l.topic or 'Занятие')[:20],
                    'raw_stored': str(dt),
                    'is_aware': dt.tzinfo is not None,
                    'projected_utc_iso': format_utc_iso_z(utc_dt),
                    'msk_display': msk_dt.strftime('%d.%m.%Y %H:%M') if msk_dt else '-',
                    'tomsk_display': tomsk_dt.strftime('%d.%m.%Y %H:%M') if tomsk_dt else '-',
                })

        print(f"Total Lessons: {total_lessons}")
        print(f"  - Naive Datetimes (stored in DB): {naive_lessons}")
        print(f"  - Aware Datetimes:                {aware_lessons}")
        print(f"  - NULL Dates:                     {null_lessons}")

        if sample_lessons:
            print("\nSample Lesson Date Projections:")
            print(f"{'ID':<6} | {'Raw Stored':<20} | {'Projected UTC ISO (Z)':<22} | {'MSK Display':<18} | {'Tomsk Display':<18}")
            print("-" * 92)
            for s in sample_lessons:
                print(f"{s['id']:<6} | {s['raw_stored']:<20} | {s['projected_utc_iso']:<22} | {s['msk_display']:<18} | {s['tomsk_display']:<18}")

        # ---------------------------------------------------------
        # 3. ASSIGNMENTS AUDIT
        # ---------------------------------------------------------
        print("\n[3] ASSIGNMENTS AUDIT (Assignment.deadline)")
        print("-" * 50)
        assignments = Assignment.query.all()
        total_assignments = len(assignments)
        null_dl = 0
        naive_dl = 0
        aware_dl = 0
        sample_assignments = []

        for a in assignments:
            dt = a.deadline
            if dt is None:
                null_dl += 1
                continue
            if getattr(dt, 'tzinfo', None) is not None:
                aware_dl += 1
            else:
                naive_dl += 1

            if len(sample_assignments) < sample_limit:
                utc_dt = to_utc_instant(dt, assume_utc_if_naive=True)
                msk_dt = to_viewer_tz(utc_dt, 'Europe/Moscow')
                sample_assignments.append({
                    'id': a.assignment_id,
                    'title': (a.title or 'Без названия')[:20],
                    'raw_stored': str(dt),
                    'projected_utc_iso': format_utc_iso_z(utc_dt),
                    'msk_display': msk_dt.strftime('%d.%m.%Y %H:%M') if msk_dt else '-',
                })

        print(f"Total Assignments: {total_assignments}")
        print(f"  - Naive Deadlines:  {naive_dl}")
        print(f"  - Aware Deadlines:  {aware_dl}")
        print(f"  - Without Deadline: {null_dl}")

        if sample_assignments:
            print("\nSample Assignment Deadline Projections:")
            print(f"{'ID':<6} | {'Title':<20} | {'Raw Stored':<20} | {'Projected UTC ISO (Z)':<22} | {'MSK Display':<18}")
            print("-" * 95)
            for s in sample_assignments:
                print(f"{s['id']:<6} | {s['title']:<20} | {s['raw_stored']:<20} | {s['projected_utc_iso']:<22} | {s['msk_display']:<18}")

        # ---------------------------------------------------------
        # 4. SUBMISSIONS AUDIT
        # ---------------------------------------------------------
        print("\n[4] SUBMISSIONS AUDIT (Submission.submitted_at)")
        print("-" * 50)
        submissions = Submission.query.all()
        total_subs = len(submissions)
        null_subs = 0
        naive_subs = 0
        aware_subs = 0

        for sub in submissions:
            dt = sub.submitted_at
            if dt is None:
                null_subs += 1
                continue
            if getattr(dt, 'tzinfo', None) is not None:
                aware_subs += 1
            else:
                naive_subs += 1

        print(f"Total Submissions: {total_subs}")
        print(f"  - Naive Submitted At: {naive_subs}")
        print(f"  - Aware Submitted At: {aware_subs}")
        print(f"  - NULL Submitted At:  {null_subs}")

        print("\n" + "=" * 80)
        print("DRY-RUN COMPLETED: 0 database modifications made (READ-ONLY).")
        print("=" * 80)


if __name__ == '__main__':
    run_audit()
