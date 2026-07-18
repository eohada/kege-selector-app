#!/usr/bin/env python3
"""Prepare deterministic local QA accounts for browser release audits.

The script is intentionally local-first. It refuses to run in production unless
--allow-non-local is passed, because it creates users with a known password.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from werkzeug.security import generate_password_hash

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Seed QA users for BooStudy release audit.')
    parser.add_argument('--password', default='123456', help='Password for QA accounts. Default: 123456')
    parser.add_argument(
        '--allow-non-local',
        action='store_true',
        help='Allow running outside local/dev environments. Use only on disposable QA/sandbox DBs.',
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    environment = (os.environ.get('ENVIRONMENT') or 'local').lower()
    if environment not in {'local', 'dev', 'development', 'test'} and not args.allow_non_local:
        print(
            f'Refusing to seed release audit accounts in ENVIRONMENT={environment!r}. '
            'Pass --allow-non-local only for sandbox databases.',
            file=sys.stderr,
        )
        return 2

    from app import create_app
    from app.models import db, Enrollment, FamilyTie, Student, User, UserSubscription, moscow_now
    from app.qa.routes import QA_POOL_USERNAMES

    app = create_app()
    with app.app_context():
        password_hash = generate_password_hash(args.password)
        created: list[str] = []
        touched: list[str] = []

        for username in QA_POOL_USERNAMES:
            user = User.query.filter_by(username=username).first()
            if user is None:
                role = 'student'
                if 'tutor' in username:
                    role = 'tutor'
                elif 'parent' in username:
                    role = 'parent'
                elif 'admin' in username:
                    role = 'admin'
                user = User(
                    username=username,
                    email=f'{username}@qa.local',
                    role=role,
                    password_hash=password_hash,
                    is_active=True,
                    timezone_mode='manual',
                    timezone_iana='Asia/Tomsk',
                )
                if hasattr(user, 'is_qa_pool'):
                    user.is_qa_pool = True
                db.session.add(user)
                db.session.flush()
                created.append(username)
            else:
                user.password_hash = password_hash
                user.is_active = True
                user.timezone_mode = user.timezone_mode or 'manual'
                user.timezone_iana = user.timezone_iana or 'Asia/Tomsk'
                if hasattr(user, 'is_qa_pool'):
                    user.is_qa_pool = True
                touched.append(username)

            if user.role == 'student':
                profile = Student.query.filter_by(user_id=user.id).first()
                if profile is None:
                    profile = Student(
                        user_id=user.id,
                        platform_id=username,
                        name=username.replace('_', ' ').title(),
                        category='test',
                        is_active=True,
                    )
                    db.session.add(profile)
                else:
                    profile.is_active = True
                    profile.platform_id = profile.platform_id or username
                    profile.name = profile.name or username.replace('_', ' ').title()
                    profile.category = profile.category or 'test'

            sub = UserSubscription.query.filter_by(user_id=user.id, status='active').first()
            if sub is None:
                db.session.add(UserSubscription(user_id=user.id, status='active', started_at=moscow_now()))

        db.session.flush()

        student = User.query.filter_by(username='qa_pool_student_1').first()
        tutor = User.query.filter_by(username='qa_pool_tutor_1').first()
        parent = User.query.filter_by(username='qa_pool_parent_1').first()
        if student and tutor and not Enrollment.query.filter_by(student_id=student.id, tutor_id=tutor.id).first():
            db.session.add(Enrollment(student_id=student.id, tutor_id=tutor.id, subject='QA release audit', status='active'))
        if student and parent and not FamilyTie.query.filter_by(parent_id=parent.id, student_id=student.id).first():
            db.session.add(FamilyTie(parent_id=parent.id, student_id=student.id, is_confirmed=True, access_level='full'))

        db.session.commit()

        print('Release audit QA data is ready.')
        print(f'Created: {", ".join(created) if created else "none"}')
        print(f'Updated: {", ".join(touched) if touched else "none"}')
        print('Accounts:')
        for username in QA_POOL_USERNAMES:
            print(f'  {username} / {args.password}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
