from .db_models import db, Tasks, UsageHistory, SkippedTasks, BlacklistTasks, moscow_now, Lesson, LessonTask, StudentTaskSeen
from sqlalchemy import text


def _tasks_active_sql_fragment():
    """Фрагмент AND ... для сырого SQL: только активные строки банка (is_active)."""
    try:
        dialect = db.engine.dialect.name
    except Exception:
        dialect = 'sqlite'
    if dialect == 'postgresql':
        return ' AND (T.is_active IS TRUE)'
    return ' AND (IFNULL(T.is_active, 1) != 0)'


# Импорт для подзапроса «уже в работах у учеников» (избегаем циклического импорта через text/SQL)
def get_task_ids_in_assignments_for_students(student_ids):
    """
    Возвращает множество task_id, которые уже встречаются в работах (Assignments),
    назначенных хотя бы одному из переданных учеников.
    Используется для фильтрации генератора и подсказок при ручном/шаблонном выборе.
    """
    if not student_ids:
        return set()
    try:
        ids = [int(x) for x in student_ids if x is not None]
    except (TypeError, ValueError):
        return set()
    if not ids:
        return set()
    q = text("""
        SELECT DISTINCT AT.task_id
        FROM "AssignmentTasks" AS AT
        JOIN "Submissions" AS S ON S.assignment_id = AT.assignment_id
        WHERE S.student_id = ANY(:student_ids)
    """)
    try:
        rows = db.session.execute(q, {'student_ids': ids}).fetchall()
        return {r[0] for r in rows}
    except Exception:
        return set() 

def _looks_like_pg_sequence_problem(error):  # Определяем по тексту ошибки, что это сбитая sequence в PostgreSQL
    msg = str(error)  # Приводим исключение к строке для простого анализа
    return (  # Возвращаем True, если похоже на дубликат PK из-за sequence
        'psycopg2.errors.UniqueViolation' in msg  # Типовая сигнатура psycopg2 для unique violation
        and 'duplicate key value violates unique constraint' in msg  # Текст PostgreSQL про дубликат ключа
        and '_pkey' in msg  # Указывает, что упали на primary key
    )  # Конец условия

def _fix_pg_serial_sequence(table_name, pk_column):  # Поднимаем sequence для SERIAL/IDENTITY, чтобы nextval не выдавал занятый id
    try:  # Пытаемся починить sequence без падения всего запроса
        db.session.execute(  # Выполняем SQL в рамках текущей транзакции
            text(  # Используем text() для корректного выполнения сырого SQL
                f"SELECT setval(pg_get_serial_sequence('{table_name}', '{pk_column}'), "  # Находим sequence по таблице+колонке
                f"COALESCE((SELECT MAX(\"{pk_column}\") FROM {table_name}), 0), "  # Ставим текущий max(pk) или 0
                f"true)"  # is_called=true => следующий nextval вернёт max+1
            )  # Конец SQL
        )  # Конец execute
        db.session.commit()  # Коммитим фиксацию sequence
        return True  # Сообщаем, что починили
    except Exception:  # Если не удалось (например, не Postgres), не ломаем логику
        db.session.rollback()  # Откатываем возможные изменения
        return False  # Сообщаем, что починить не удалось

def get_unique_tasks(task_type, limit_count, use_skipped=False, student_id=None, recipient_ids=None, course_id=None):
    """recipient_ids: исключать задания, уже в работах у этих учеников.
    course_id: фильтр по программе подготовки (ExamCourse)."""
    assign_excl = ""
    course_filter = ""
    params_extra = {}
    if recipient_ids:
        try:
            rids = [int(x) for x in recipient_ids if x is not None]
            if rids:
                params_extra['recipient_ids'] = rids
                assign_excl = ' AND T.task_id NOT IN (SELECT AT.task_id FROM "AssignmentTasks" AT JOIN "Submissions" S ON S.assignment_id = AT.assignment_id WHERE S.student_id = ANY(:recipient_ids))'
        except (TypeError, ValueError):
            pass
    if course_id:
        course_filter = ' AND T.course_id = :course_id'
        params_extra['course_id'] = course_id

    active_sql = _tasks_active_sql_fragment()
    if student_id:
        params = {'task_type': task_type, 'limit_count': limit_count, 'student_id': student_id, **params_extra}
        if use_skipped:
            sql_query = text("""
                SELECT T.task_id
                FROM "Tasks" AS T
                WHERE T.task_number = :task_type
                    """ + active_sql + """
                    AND T.task_id NOT IN (SELECT task_fk FROM "UsageHistory")
                    AND T.task_id NOT IN (SELECT task_fk FROM "BlacklistTasks")
                    AND T.task_id NOT IN (
                        SELECT STS.task_id
                        FROM "StudentTaskSeen" AS STS
                        WHERE STS.student_id = :student_id
                    )
                    AND T.task_id NOT IN (
                        SELECT LT.task_id 
                        FROM "LessonTasks" AS LT
                        JOIN "Lessons" AS L ON LT.lesson_id = L.lesson_id
                        WHERE L.student_id = :student_id
                    )
                    """ + assign_excl + course_filter + """
                ORDER BY RANDOM()
                LIMIT :limit_count
            """)
        else:
            sql_query = text("""
                SELECT T.task_id
                FROM "Tasks" AS T
                WHERE T.task_number = :task_type
                    """ + active_sql + """
                    AND T.task_id NOT IN (SELECT task_fk FROM "UsageHistory")
                    AND T.task_id NOT IN (SELECT task_fk FROM "SkippedTasks")
                    AND T.task_id NOT IN (SELECT task_fk FROM "BlacklistTasks")
                    AND T.task_id NOT IN (
                        SELECT STS.task_id
                        FROM "StudentTaskSeen" AS STS
                        WHERE STS.student_id = :student_id
                    )
                    AND T.task_id NOT IN (
                        SELECT LT.task_id 
                        FROM "LessonTasks" AS LT
                        JOIN "Lessons" AS L ON LT.lesson_id = L.lesson_id
                        WHERE L.student_id = :student_id
                    )
                    """ + assign_excl + course_filter + """
                ORDER BY RANDOM()
                LIMIT :limit_count
            """)
        result = db.session.execute(sql_query, params)
    else:
        params = {'task_type': task_type, 'limit_count': limit_count, **params_extra}
        if use_skipped:
            sql_query = text("""
                SELECT T.task_id
                FROM "Tasks" AS T
                WHERE T.task_number = :task_type
                    """ + active_sql + """
                    AND T.task_id NOT IN (SELECT task_fk FROM "UsageHistory")
                    AND T.task_id NOT IN (SELECT task_fk FROM "BlacklistTasks")
                    """ + assign_excl + course_filter + """
                ORDER BY RANDOM()
                LIMIT :limit_count
            """)
        else:
            sql_query = text("""
                SELECT T.task_id
                FROM "Tasks" AS T
                WHERE T.task_number = :task_type
                    """ + active_sql + """
                    AND T.task_id NOT IN (SELECT task_fk FROM "UsageHistory")
                    AND T.task_id NOT IN (SELECT task_fk FROM "SkippedTasks")
                    AND T.task_id NOT IN (SELECT task_fk FROM "BlacklistTasks")
                    """ + assign_excl + course_filter + """
                ORDER BY RANDOM()
                LIMIT :limit_count
            """)
        result = db.session.execute(sql_query, params)

    result_rows = list(result)
    if not result_rows:
        return []

    task_ids = [row.task_id for row in result_rows]
    tasks_dict = {task.task_id: task for task in Tasks.query.filter(Tasks.task_id.in_(task_ids)).all()}
    tasks = [tasks_dict[tid] for tid in task_ids if tid in tasks_dict]
    return tasks

def get_next_unique_task(task_type, use_skipped=False, student_id=None, lesson_tag=None, recipient_ids=None, course_id=None):
    """
    Возвращает одно следующее уникальное задание по условиям (или None).
    recipient_ids: список student_id — исключать задания, уже входящие в работы, назначенные этим ученикам.
    course_id: фильтр по программе подготовки (ExamCourse).
    """
    params = {'task_type': task_type}

    skip_where = ""
    if not use_skipped:
        if lesson_tag:
            skip_where = 'AND T.task_id NOT IN (SELECT task_fk FROM "SkippedTasks" WHERE session_tag IS NULL OR session_tag = :lesson_tag)'
            params['lesson_tag'] = lesson_tag
        else:
            skip_where = 'AND T.task_id NOT IN (SELECT task_fk FROM "SkippedTasks" WHERE session_tag IS NULL)'

    assign_excl = ""
    if recipient_ids:
        try:
            rids = [int(x) for x in recipient_ids if x is not None]
            if rids:
                params['recipient_ids'] = rids
                assign_excl = ' AND T.task_id NOT IN (SELECT AT.task_id FROM "AssignmentTasks" AT JOIN "Submissions" S ON S.assignment_id = AT.assignment_id WHERE S.student_id = ANY(:recipient_ids))'
        except (TypeError, ValueError):
            pass

    course_filter = ""
    if course_id:
        course_filter = " AND T.course_id = :course_id"
        params['course_id'] = course_id

    active_sql = _tasks_active_sql_fragment()
    if student_id:
        params['student_id'] = student_id
        sql_query = text(f"""
            SELECT T.task_id
            FROM "Tasks" AS T
            WHERE T.task_number = :task_type
                {active_sql}
                AND T.task_id NOT IN (SELECT task_fk FROM "UsageHistory")
                AND T.task_id NOT IN (SELECT task_fk FROM "BlacklistTasks")
                {skip_where}
                {assign_excl}
                {course_filter}
                AND T.task_id NOT IN (
                    SELECT STS.task_id
                    FROM "StudentTaskSeen" AS STS
                    WHERE STS.student_id = :student_id
                )
                AND T.task_id NOT IN (
                    SELECT LT.task_id
                    FROM "LessonTasks" AS LT
                    JOIN "Lessons" AS L ON LT.lesson_id = L.lesson_id
                    WHERE L.student_id = :student_id
                )
            ORDER BY RANDOM()
            LIMIT 1
        """)
    else:
        sql_query = text(f"""
            SELECT T.task_id
            FROM "Tasks" AS T
            WHERE T.task_number = :task_type
                {active_sql}
                AND T.task_id NOT IN (SELECT task_fk FROM "UsageHistory")
                AND T.task_id NOT IN (SELECT task_fk FROM "BlacklistTasks")
                {skip_where}
                {assign_excl}
                {course_filter}
            ORDER BY RANDOM()
            LIMIT 1
        """)

    row = db.session.execute(sql_query, params).fetchone()
    if not row:
        return None

    return Tasks.query.filter_by(task_id=row.task_id).first()

def record_usage(task_ids, session_tag=None, _retry=False):  # _retry нужен для одного безопасного повтора после фикса sequence
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
        if (not _retry) and _looks_like_pg_sequence_problem(e):  # Если это похоже на сбитую sequence и мы ещё не ретраили
            fixed = _fix_pg_serial_sequence('"UsageHistory"', 'usage_id')  # Чиним sequence для UsageHistory.usage_id
            if fixed:  # Если успешно починили
                return record_usage(task_ids, session_tag=session_tag, _retry=True)  # Повторяем вставку ровно один раз
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
    query = db.session.query(Tasks).join(SkippedTasks).filter(SkippedTasks.session_tag.is_(None))

    if task_type:
        query = query.filter(Tasks.task_number == task_type)

    return query.order_by(SkippedTasks.date_skipped.desc()).all()
