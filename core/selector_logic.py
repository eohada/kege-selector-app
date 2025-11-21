from .db_models import db, Tasks, UsageHistory, SkippedTasks, BlacklistTasks, moscow_now, Lesson, LessonTask
from sqlalchemy import text

def get_unique_tasks(task_type, limit_count, use_skipped=False, student_id=None):
    if student_id:
        if use_skipped:
            sql_query = text()
        else:
            sql_query = text()
        result = db.session.execute(sql_query, {'task_type': task_type, 'limit_count': limit_count, 'student_id': student_id})
    else:
        if use_skipped:
            sql_query = text()
        else:
            sql_query = text()
        result = db.session.execute(sql_query, {'task_type': task_type, 'limit_count': limit_count})

    result_rows = list(result)
    if not result_rows:
        return []

    task_ids = [row.task_id for row in result_rows]
    tasks_dict = {task.task_id: task for task in Tasks.query.filter(Tasks.task_id.in_(task_ids)).all()}
    tasks = [tasks_dict[tid] for tid in task_ids if tid in tasks_dict]
    return tasks

def record_usage(task_ids, session_tag=None):
    if not task_ids:
        return
    try:
        existing_ids = {row.task_fk for row in UsageHistory.query.filter(UsageHistory.task_fk.in_(task_ids)).all()}
        new_records = [UsageHistory(task_fk=task_id, date_issued=moscow_now(), session_tag=session_tag) for task_id in task_ids if task_id not in existing_ids]
        if new_records:
            db.session.add_all(new_records)
            db.session.commit()
    except Exception as e:
        db.session.rollback()
        raise

def record_skipped(task_ids, session_tag=None):
    if not task_ids:
        return
    try:
        existing_ids = {row.task_fk for row in SkippedTasks.query.filter(SkippedTasks.task_fk.in_(task_ids)).all()}
        new_records = [SkippedTasks(task_fk=task_id, date_skipped=moscow_now(), session_tag=session_tag) for task_id in task_ids if task_id not in existing_ids]
        if new_records:
            db.session.add_all(new_records)
            db.session.commit()
    except Exception as e:
        db.session.rollback()
        raise

def record_blacklist(task_ids, reason=None):
    if not task_ids:
        return
    try:
        existing_ids = {row.task_fk for row in BlacklistTasks.query.filter(BlacklistTasks.task_fk.in_(task_ids)).all()}
        new_records = [BlacklistTasks(task_fk=task_id, date_added=moscow_now(), reason=reason) for task_id in task_ids if task_id not in existing_ids]
        if new_records:
            db.session.add_all(new_records)
            db.session.commit()
    except Exception as e:
        db.session.rollback()
        raise

def reset_history(task_type=None):
    query = UsageHistory.query

    if task_type:
        query = query.join(Tasks).filter(Tasks.task_number == task_type)

    query.delete(synchronize_session=False)
    db.session.commit()

def reset_skipped(task_type=None):
    query = SkippedTasks.query

    if task_type:
        query = query.join(Tasks).filter(Tasks.task_number == task_type)

    query.delete(synchronize_session=False)
    db.session.commit()

def reset_blacklist(task_type=None):
    query = BlacklistTasks.query

    if task_type:
        query = query.join(Tasks).filter(Tasks.task_number == task_type)

    query.delete(synchronize_session=False)
    db.session.commit()

def get_accepted_tasks(task_type=None):
    query = db.session.query(Tasks).join(UsageHistory)

    if task_type:
        query = query.filter(Tasks.task_number == task_type)

    return query.order_by(UsageHistory.date_issued.desc()).all()

def get_skipped_tasks(task_type=None):
    query = db.session.query(Tasks).join(SkippedTasks)

    if task_type:
        query = query.filter(Tasks.task_number == task_type)

    return query.order_by(SkippedTasks.date_skipped.desc()).all()
