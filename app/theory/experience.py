"""Read-only view models for the theory library and course screens.

Learning identity remains (student_id, course_id, task_number). Enrolment
indicates 'my courses'; it does not replace the existing default-allow policy.
Article bodies are deliberately not loaded by the catalogue queries.
"""
from collections import defaultdict

from sqlalchemy import func

from app.models import (
    Course, Student, StudentCourseEnrollment, StudentTheoryAccess, StudentTheoryState,
    TheoryBlock, TheoryGroup,
)


PALETTES = ('lavender', 'blue', 'peach', 'mint', 'rose', 'sky')


def published_expression():
    content = func.trim(func.coalesce(TheoryBlock.content, ''))
    return (content != '') & ~content.startswith('<!--status:draft-->')


def format_study_time(minutes):
    if not minutes:
        return '0 мин'
    h, m = divmod(int(minutes), 60)
    if h and m:
        return f'{h} ч {m} мин'
    if h:
        return f'{h} ч'
    return f'{m} мин'


def build_experience(student_id=None, *, staff=False):
    """Build all visible courses with a bounded number of metadata queries.

    No GET-side grouping repairs, writes or fabricated study-time aggregates.
    Teacher-locked topics expose only a lock marker, never their descriptions
    or material URLs. Draft metadata is excluded for non-managers.
    """
    courses = Course.query.filter_by(is_active=True).order_by(Course.id).all()
    course_ids = [course.id for course in courses]
    if not course_ids:
        return {'courses': [], 'continue_topic': None, 'total': 0,
                'completed': 0, 'progress': 0, 'bookmarks': 0,
                'in_progress': 0, 'study_minutes': None,
                'study_time_display': '0 мин'}

    query = TheoryBlock.query.with_entities(
        TheoryBlock.id, TheoryBlock.course_id, TheoryBlock.group_id,
        TheoryBlock.task_number, TheoryBlock.title, TheoryBlock.description,
        TheoryBlock.read_minutes, TheoryBlock.position, TheoryBlock.pdf_path,
    ).filter(TheoryBlock.course_id.in_(course_ids))
    if not staff:
        query = query.filter(published_expression())
    blocks = query.all()
    groups = TheoryGroup.query.filter(TheoryGroup.course_id.in_(course_ids)).order_by(
        TheoryGroup.position, TheoryGroup.id,
    ).all()
    states, denied, enrolled = {}, set(), set()
    student_study_sec = 0
    if student_id is not None:
        student_obj = Student.query.filter_by(student_id=student_id).first()
        student_study_sec = getattr(student_obj, 'study_time_seconds', 0) or 0
        states = {
            (row.course_id, row.task_number): row
            for row in StudentTheoryState.query.filter_by(student_id=student_id).filter(
                StudentTheoryState.course_id.in_(course_ids),
            ).all()
        }
        denied = {
            (row.course_id, row.task_number)
            for row in StudentTheoryAccess.query.filter_by(
                student_id=student_id, can_view=False,
            ).filter(StudentTheoryAccess.course_id.in_(course_ids)).all()
        }
        enrolled = {
            row.course_id for row in StudentCourseEnrollment.query.filter_by(
                student_id=student_id, is_active=True,
            ).all()
        }
        enrollment_map = {
            row.course_id: bool(row.is_active)
            for row in StudentCourseEnrollment.query.filter_by(
                student_id=student_id
            ).all()
        }
    else:
        enrollment_map = {}

    blocks_by_course = defaultdict(lambda: defaultdict(list))
    groups_by_course = defaultdict(list)
    for block in blocks:
        blocks_by_course[block.course_id][block.group_id].append(block)
    for group in groups:
        groups_by_course[group.course_id].append(group)

    cards, recent_candidates = [], []
    for course in courses:
        ordered_groups = groups_by_course[course.id]
        course_groups = []
        topics = []

        for g in ordered_groups:
            g_dict = dict(id=g.id, name=g.name, description=g.description, topics=[])
            g_blocks = list(blocks_by_course[course.id].get(g.id, []))
            g_blocks.sort(key=lambda b: (b.position if b.position is not None else 999999, b.task_number or 0, b.id))
            for block in g_blocks:
                key = (course.id, block.task_number)
                row = states.get(key)
                locked = not staff and key in denied
                read = bool(row and row.is_read)
                progress = min(100, max(0, int(row.reading_progress or 0))) if row else 0
                previous = topics[-1] if topics else None
                sequence_locked = bool(student_id is not None and not staff and previous
                                       and not previous['completed'])
                topic = dict(
                    id=block.id, course_id=course.id, course_title=course.title,
                    task_number=block.task_number,
                    group_id=g.id, group_name=g.name,
                    title=block.title or f'Тема {block.task_number}',
                    description=None if locked else block.description,
                    read_minutes=None if locked else block.read_minutes,
                    pdf_path=None if locked else block.pdf_path,
                    progress=100 if read else progress, completed=read,
                    bookmarked=bool(row and row.is_bookmarked),
                    last_opened_at=row.last_opened_at if row else None,
                    status='locked' if locked or sequence_locked else ('completed' if read else
                           ('in_progress' if progress > 0 else 'not_started')),
                    locked=locked or sequence_locked,
                    lock_reason='Доступ закрыт преподавателем' if locked else
                                ('Откроется после предыдущей темы' if sequence_locked else ''),
                    teacher_locked=locked,
                )
                g_dict['topics'].append(topic)
                topics.append(topic)
            if g_dict['topics']:
                course_groups.append(g_dict)

        ungrouped_blocks = list(blocks_by_course[course.id].get(None, []))
        known_group_ids = {g.id for g in ordered_groups}
        for gid, extra_blocks in blocks_by_course[course.id].items():
            if gid not in known_group_ids and gid is not None:
                ungrouped_blocks.extend(extra_blocks)
        if ungrouped_blocks:
            ungrouped_blocks.sort(key=lambda b: (b.position if b.position is not None else 999999, b.task_number or 0, b.id))
            ungrouped = dict(id=None, name='Темы курса', description=None, topics=[])
            for block in ungrouped_blocks:
                key = (course.id, block.task_number)
                row = states.get(key)
                locked = not staff and key in denied
                read = bool(row and row.is_read)
                progress = min(100, max(0, int(row.reading_progress or 0))) if row else 0
                previous = topics[-1] if topics else None
                sequence_locked = bool(student_id is not None and not staff and previous
                                       and not previous['completed'])
                topic = dict(
                    id=block.id, course_id=course.id, course_title=course.title,
                    task_number=block.task_number,
                    group_id=None, group_name='Темы курса',
                    title=block.title or f'Тема {block.task_number}',
                    description=None if locked else block.description,
                    read_minutes=None if locked else block.read_minutes,
                    pdf_path=None if locked else block.pdf_path,
                    progress=100 if read else progress, completed=read,
                    bookmarked=bool(row and row.is_bookmarked),
                    last_opened_at=row.last_opened_at if row else None,
                    status='locked' if locked or sequence_locked else ('completed' if read else
                           ('in_progress' if progress > 0 else 'not_started')),
                    locked=locked or sequence_locked,
                    lock_reason='Доступ закрыт преподавателем' if locked else
                                ('Откроется после предыдущей темы' if sequence_locked else ''),
                    teacher_locked=locked,
                )
                ungrouped['topics'].append(topic)
                topics.append(topic)
            course_groups.append(ungrouped)

        # An empty active course is a valid empty state; an entirely denied
        # course is not advertised as available to a student.
        if topics and all(topic['teacher_locked'] for topic in topics) and not staff:
            continue
        for group in course_groups:
            group['total'] = len(group['topics'])
            group['completed'] = sum(t['completed'] for t in group['topics'])
            group['progress'] = round(100 * group['completed'] / group['total']) if group['total'] else 0
        accessible = [t for t in topics if not t['locked']]
        active = [t for t in accessible if not t['completed'] and t['last_opened_at']]
        active.sort(key=lambda t: t['last_opened_at'], reverse=True)
        next_topic = active[0] if active else next(
            (t for t in accessible if not t['completed']), None,
        )
        completed = sum(t['completed'] for t in topics)
        has_final_test = any(marker in (course.title or '').casefold() for marker in ('программ', 'python')) or any(
            g['topics'] and any(marker in g['name'].casefold() for marker in ('программ', 'python'))
            for g in course_groups
        )
        if student_id is not None:
            if course.id in enrollment_map:
                enrollment_status = 'active' if enrollment_map[course.id] else 'assigned'
            else:
                enrollment_status = 'none'
        else:
            enrollment_status = 'active' if staff else 'none'

        # Ученикам показываются только курсы, назначенные преподавателем (активные или неинициализированные).
        # Неназначенные курсы и курсы без тем не загромождают библиотеку ученика.
        if not staff and student_id is not None:
            if enrollment_status == 'none' or len(topics) == 0:
                continue

        is_initialized = bool(staff or enrollment_status == 'active')

        final_test_passed = False
        final_test_score = 0
        if has_final_test and student_id is not None:
            st_user_id = student_obj.user_id if student_obj and student_obj.user_id else None
            from sqlalchemy import or_
            from app.models import TheoryFinalTestAttempt
            user_attempt = TheoryFinalTestAttempt.query.filter(
                TheoryFinalTestAttempt.course_id == course.id,
                or_(
                    TheoryFinalTestAttempt.student_id == student_id,
                    TheoryFinalTestAttempt.user_id == (st_user_id or -1)
                )
            ).order_by(TheoryFinalTestAttempt.score.desc(), TheoryFinalTestAttempt.created_at.desc()).first()
            if user_attempt:
                final_test_passed = bool(user_attempt.passed)
                final_test_score = user_attempt.score or 0

        cards.append(dict(
            id=course.id, title=course.title, slug=course.slug,
            palette=PALETTES[(course.id - 1) % len(PALETTES)],
            enrolled=course.id in enrolled,
            enrollment_status=enrollment_status,
            is_initialized=is_initialized,
            groups=course_groups, topics=topics,
            total=len(topics), completed=completed,
            progress=round(100 * completed / len(topics)) if topics else 0,
            material_count=len(accessible) + sum(bool(t['pdf_path']) for t in accessible),
            continue_topic=next_topic if is_initialized else None,
            study_minutes=0,
            study_time_display='0 мин',
            has_final_test=has_final_test,
            final_test_unlocked=staff or (completed >= len(topics) and len(topics) > 0),
            final_test_passed=final_test_passed,
            final_test_score=final_test_score,
        ))
        if is_initialized:
            opened = [t for t in accessible if t['last_opened_at']]
            if opened and next_topic:
                recent_candidates.append((max(t['last_opened_at'] for t in opened), next_topic))

    total = sum(c['total'] for c in cards)
    completed = sum(c['completed'] for c in cards)
    recent_candidates.sort(key=lambda pair: pair[0], reverse=True)
    all_topics = [t for c in cards for t in c['topics'] if not t['locked']]
    completed_read_mins = sum(t.get('read_minutes') or 5 for c in cards for t in c['topics'] if t['completed'])
    total_study_minutes = int(student_study_sec // 60) if student_study_sec > 0 else completed_read_mins
    total_completed = sum(c['completed'] for c in cards)
    for c in cards:
        c_read_mins = sum(t.get('read_minutes') or 5 for t in c['topics'] if t['completed'])
        if total_completed > 0 and c['completed'] > 0 and total_study_minutes > 0:
            c['study_minutes'] = max(1, int(round(total_study_minutes * (c['completed'] / total_completed))))
        elif total_study_minutes > 0 and len(cards) == 1:
            c['study_minutes'] = total_study_minutes
        elif c_read_mins > 0:
            c['study_minutes'] = c_read_mins
        else:
            c['study_minutes'] = 0 if total_study_minutes == 0 else None
        c['study_time_display'] = format_study_time(c['study_minutes'] or 0)

    return dict(
        courses=cards,
        continue_topic=recent_candidates[0][1] if recent_candidates else None,
        total=total, completed=completed,
        progress=round(100 * completed / total) if total else 0,
        bookmarks=sum(t['bookmarked'] for t in all_topics),
        in_progress=sum(t['status'] == 'in_progress' for t in all_topics),
        study_minutes=total_study_minutes if total_study_minutes > 0 else None,
        study_time_display=format_study_time(total_study_minutes),
    )
