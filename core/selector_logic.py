from .db_models import db, Tasks, UsageHistory, SkippedTasks, BlacklistTasks, moscow_now, Lesson, LessonTask
from sqlalchemy import text  # Используем text() для сырого SQL (PostgreSQL setval/pg_get_serial_sequence и выборки) 

def _looks_like_pg_sequence_problem(error):  # Определяем по тексту ошибки, что это сбитая sequence в PostgreSQL
    msg = str(error)  # Приводим исключение к строке для простого анализа
    return (  # Возвращаем True, если похоже на дубликат PK из-за sequence
        'psycopg2.errors.UniqueViolation' in msg  # Типовая сигнатура psycopg2 для unique violation
        and 'duplicate key value violates unique constraint' in msg  # Текст PostgreSQL про дубликат ключа
        and '_pkey' in msg  # Указывает, что упали на primary key
    )  # Конец условия

def _fix_pg_serial_sequence(table_name, pk_column):  # Поднимаем sequence для SERIAL/IDENTITY, чтобы nextval не выдавал занятый id
    try:  # Пытаемся починить sequence без падения всего запроса
        # Важно: table_name должен быть с кавычками для case-sensitive таблиц, например '"UsageHistory"'
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

def get_unique_tasks(task_type, limit_count, use_skipped=False, student_id=None):
    if student_id:
        if use_skipped:
            sql_query = text("""
                SELECT T.task_id
                FROM "Tasks" AS T
                WHERE T.task_number = :task_type
                    AND T.task_id NOT IN (SELECT task_fk FROM "UsageHistory")
                    AND T.task_id NOT IN (SELECT task_fk FROM "BlacklistTasks")
                    AND T.task_id NOT IN (
                        SELECT LT.task_id 
                        FROM "LessonTasks" AS LT
                        JOIN "Lessons" AS L ON LT.lesson_id = L.lesson_id
                        WHERE L.student_id = :student_id
                    )
                ORDER BY RANDOM()
                LIMIT :limit_count
            """)
        else:
            sql_query = text("""
                SELECT T.task_id
                FROM "Tasks" AS T
                WHERE T.task_number = :task_type
                    AND T.task_id NOT IN (SELECT task_fk FROM "UsageHistory")
                    AND T.task_id NOT IN (SELECT task_fk FROM "SkippedTasks")
                    AND T.task_id NOT IN (SELECT task_fk FROM "BlacklistTasks")
                    AND T.task_id NOT IN (
                        SELECT LT.task_id 
                        FROM "LessonTasks" AS LT
                        JOIN "Lessons" AS L ON LT.lesson_id = L.lesson_id
                        WHERE L.student_id = :student_id
                    )
                ORDER BY RANDOM()
                LIMIT :limit_count
            """)
        result = db.session.execute(sql_query, {'task_type': task_type, 'limit_count': limit_count, 'student_id': student_id})
    else:
        if use_skipped:
            sql_query = text("""
                SELECT T.task_id
                FROM "Tasks" AS T
                WHERE T.task_number = :task_type
                    AND T.task_id NOT IN (SELECT task_fk FROM "UsageHistory")
                    AND T.task_id NOT IN (SELECT task_fk FROM "BlacklistTasks")
                ORDER BY RANDOM()
                LIMIT :limit_count
            """)
        else:
            sql_query = text("""
                SELECT T.task_id
                FROM "Tasks" AS T
                WHERE T.task_number = :task_type
                    AND T.task_id NOT IN (SELECT task_fk FROM "UsageHistory")
                    AND T.task_id NOT IN (SELECT task_fk FROM "SkippedTasks")
                    AND T.task_id NOT IN (SELECT task_fk FROM "BlacklistTasks")
                ORDER BY RANDOM()
                LIMIT :limit_count
            """)
        result = db.session.execute(sql_query, {'task_type': task_type, 'limit_count': limit_count})

    result_rows = list(result)
    if not result_rows:
        return []

    task_ids = [row.task_id for row in result_rows]
    tasks_dict = {task.task_id: task for task in Tasks.query.filter(Tasks.task_id.in_(task_ids)).all()}
    tasks = [tasks_dict[tid] for tid in task_ids if tid in tasks_dict]
    return tasks

def get_next_unique_task(task_type, use_skipped=False, student_id=None, lesson_tag=None):
    """
    Возвращает одно следующее уникальное задание по условиям (или None).

    Важно: состояние между шагами хранится не в cookie-session, а в БД через record_usage/record_skipped/record_blacklist.
    Для lesson-режима поддерживается "scoped skip" через session_tag (lesson_tag), чтобы пропуски не загрязняли общий skipped.
    """
    params = {'task_type': task_type}

    skip_where = ""
    if not use_skipped:
        if lesson_tag:
            skip_where = 'AND T.task_id NOT IN (SELECT task_fk FROM "SkippedTasks" WHERE session_tag IS NULL OR session_tag = :lesson_tag)'
            params['lesson_tag'] = lesson_tag
        else:
            skip_where = 'AND T.task_id NOT IN (SELECT task_fk FROM "SkippedTasks" WHERE session_tag IS NULL)'

    if student_id:
        params['student_id'] = student_id
        sql_query = text(f"""
            SELECT T.task_id
            FROM "Tasks" AS T
            WHERE T.task_number = :task_type
                AND T.task_id NOT IN (SELECT task_fk FROM "UsageHistory")
                AND T.task_id NOT IN (SELECT task_fk FROM "BlacklistTasks")
                {skip_where}
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
                AND T.task_id NOT IN (SELECT task_fk FROM "UsageHistory")
                AND T.task_id NOT IN (SELECT task_fk FROM "BlacklistTasks")
                {skip_where}
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
    # По умолчанию показываем только "глобальные" пропуски (session_tag IS NULL),
    # чтобы lesson-scoped пропуски не засоряли список.
    query = db.session.query(Tasks).join(SkippedTasks).filter(SkippedTasks.session_tag.is_(None))

    if task_type:
        query = query.filter(Tasks.task_number == task_type)

    return query.order_by(SkippedTasks.date_skipped.desc()).all()
