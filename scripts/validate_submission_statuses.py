"""
Post-migration validation for canonical Submission statuses.

Usage:
  python scripts/validate_submission_statuses.py
"""

from app import create_app
from app.models import db


CANONICAL = {'ASSIGNED', 'IN_PROGRESS', 'SUBMITTED', 'NEEDS_MANUAL_REVIEW', 'GRADED', 'RETURNED'}


def main() -> int:
    app = create_app()
    with app.app_context():
        rows = db.session.execute(
            db.text(
                """
                SELECT status, COUNT(*) AS cnt
                FROM "Submissions"
                GROUP BY status
                ORDER BY status
                """
            )
        ).fetchall()

        bad_rows = [(status, int(cnt)) for status, cnt in rows if status not in CANONICAL]
        if bad_rows:
            print('Found non-canonical statuses:')
            for status, cnt in bad_rows:
                print(f'  - {status}: {cnt}')
            return 1

        print('OK: all Submission.status values are canonical')
        return 0


if __name__ == '__main__':
    raise SystemExit(main())
