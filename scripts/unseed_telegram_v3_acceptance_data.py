"""
Safely remove all test data created by seed_telegram_v3_acceptance_data.py using manifest.
Guarantees clean database state without affecting production or other real records.
"""
import os
import sys
import json

root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if root not in sys.path:
    sys.path.insert(0, root)

from wsgi import app
from app.models import (
    db, UserRole, Student, Lesson,
    Assignment, Submission, FamilyTie
)
from core.db_models import BugReport, TelegramDelivery, UserNotification


def unseed_acceptance_data():
    manifest_path = os.path.join(root, 'instance', 'telegram_acceptance_seed_manifest.json')
    if not os.path.exists(manifest_path):
        print(f"[-] No acceptance manifest found at {manifest_path}. Nothing to unseed.")
        return

    with open(manifest_path, 'r', encoding='utf-8') as f:
        manifest = json.load(f)

    with app.app_context():
        print(f"[*] Starting Bot V3 acceptance data rollback from manifest ({manifest.get('seeded_at')})...")
        deleted_counts = {}

        # 1. Submissions
        sub_ids = manifest.get('submissions', [])
        if sub_ids:
            subs = Submission.query.filter(Submission.submission_id.in_(sub_ids)).all()
            for s in subs:
                db.session.delete(s)
            deleted_counts['submissions'] = len(subs)

        # 2. Assignments
        assign_ids = manifest.get('assignments', [])
        if assign_ids:
            assigns = Assignment.query.filter(Assignment.assignment_id.in_(assign_ids)).all()
            for a in assigns:
                db.session.delete(a)
            deleted_counts['assignments'] = len(assigns)

        # 3. Lessons
        lesson_ids = manifest.get('lessons', [])
        if lesson_ids:
            lessons = Lesson.query.filter(Lesson.lesson_id.in_(lesson_ids)).all()
            for l in lessons:
                db.session.delete(l)
            deleted_counts['lessons'] = len(lessons)

        # 4. Bug reports
        bug_ids = manifest.get('bug_reports', [])
        if bug_ids:
            bugs = BugReport.query.filter(BugReport.id.in_(bug_ids)).all()
            for b in bugs:
                db.session.delete(b)
            deleted_counts['bug_reports'] = len(bugs)

        # 5. Family ties
        ties = manifest.get('family_ties', [])
        tie_count = 0
        for tie_spec in ties:
            p_id = tie_spec.get('parent_id')
            s_id = tie_spec.get('student_id')
            if p_id and s_id:
                ft = FamilyTie.query.filter_by(parent_id=p_id, student_id=s_id).first()
                if ft:
                    db.session.delete(ft)
                    tie_count += 1
        deleted_counts['family_ties'] = tie_count

        # 6. Students created
        student_ids = manifest.get('students_created', [])
        if student_ids:
            students = Student.query.filter(Student.student_id.in_(student_ids)).all()
            for st in students:
                db.session.delete(st)
            deleted_counts['students'] = len(students)

        # 7. User roles added
        roles_added = manifest.get('user_roles_added', [])
        role_count = 0
        for r_spec in roles_added:
            u_id = r_spec.get('user_id')
            r_name = r_spec.get('role')
            if u_id and r_name:
                ur = UserRole.query.filter_by(user_id=u_id, role=r_name).first()
                if ur:
                    db.session.delete(ur)
                    role_count += 1
        deleted_counts['user_roles'] = role_count

        # Commit DB cleanup
        db.session.commit()
        print(f"[✓] Database records unseeded: {deleted_counts}")

        # Remove manifest file
        try:
            os.remove(manifest_path)
            print(f"[✓] Manifest file removed: {manifest_path}")
        except Exception as e:
            print(f"[!] Warning: failed to remove manifest file: {e}")

        print("[✓] Unseed complete.")


if __name__ == '__main__':
    unseed_acceptance_data()
