"""Remove local development accounts outside the manual impersonation pool.

Run without arguments to review the cleanup plan. Pass ``--apply`` to create a
SQLite backup and remove non-pool profiles plus dependent rows required to keep
the local database referentially consistent.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import tempfile
from collections import defaultdict, deque
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DB_PATH = (ROOT / 'instance' / 'boostudy_dev.db').resolve()


def quote_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def connect_readonly(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f'file:{path}?mode=ro', uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def table_primary_key(connection: sqlite3.Connection, table: str) -> tuple[str, ...]:
    columns = connection.execute(f'PRAGMA table_info({quote_identifier(table)})').fetchall()
    keys = tuple(row['name'] for row in sorted(columns, key=lambda item: item['pk']) if row['pk'])
    return keys or ('rowid',)


def table_is_nullable(connection: sqlite3.Connection, table: str, column: str) -> bool:
    info = connection.execute(f'PRAGMA table_info({quote_identifier(table)})').fetchall()
    match = next((row for row in info if row['name'] == column), None)
    return bool(match and not match['notnull'])


def select_child_keys(
    connection: sqlite3.Connection,
    child_table: str,
    child_keys: tuple[str, ...],
    child_column: str,
    parent_values: set[object],
) -> set[tuple[object, ...]]:
    found: set[tuple[object, ...]] = set()
    key_sql = ', '.join(quote_identifier(key) for key in child_keys)
    values = list(parent_values)
    for start in range(0, len(values), 400):
        batch = values[start:start + 400]
        placeholders = ', '.join('?' for _ in batch)
        rows = connection.execute(
            f'SELECT DISTINCT {key_sql} FROM {quote_identifier(child_table)} '
            f'WHERE {quote_identifier(child_column)} IN ({placeholders})',
            batch,
        ).fetchall()
        found.update(tuple(row[key] for key in child_keys) for row in rows)
    return found


def plan_cleanup(
    connection: sqlite3.Connection,
    allowed_usernames: set[str],
) -> tuple[dict[str, set[tuple[object, ...]]], dict[tuple[str, str], set[tuple[object, ...]]]]:
    users = connection.execute('SELECT id FROM Users WHERE username NOT IN ({})'.format(
        ', '.join('?' for _ in allowed_usernames)
    ), sorted(allowed_usernames)).fetchall()
    if not users:
        return {}, {}

    user_ids = {row['id'] for row in users}
    placeholders = ', '.join('?' for _ in allowed_usernames)
    non_pool_students = connection.execute(
        f'SELECT student_id FROM Students WHERE user_id IS NULL '
        f'OR user_id NOT IN (SELECT id FROM Users WHERE username IN ({placeholders}))',
        sorted(allowed_usernames),
    ).fetchall()

    table_rows = connection.execute('SELECT name FROM sqlite_master WHERE type = ? AND name NOT LIKE ?', ('table', 'sqlite_%')).fetchall()
    tables = {row['name'] for row in table_rows}
    primary_keys = {table: table_primary_key(connection, table) for table in tables}
    foreign_keys: dict[str, list[sqlite3.Row]] = {
        table: connection.execute(f'PRAGMA foreign_key_list({quote_identifier(table)})').fetchall()
        for table in tables
    }

    deleting: dict[str, set[tuple[object, ...]]] = defaultdict(set)
    pending = deque()
    if user_ids:
        roots = {(user_id,) for user_id in user_ids}
        deleting['Users'].update(roots)
        pending.append(('Users', roots))
    student_ids = {row['student_id'] for row in non_pool_students}
    if student_ids:
        roots = {(student_id,) for student_id in student_ids}
        deleting['Students'].update(roots)
        pending.append(('Students', roots))

    nulling: dict[tuple[str, str], set[tuple[object, ...]]] = defaultdict(set)
    processed: dict[str, set[tuple[object, ...]]] = defaultdict(set)
    while pending:
        parent_table, queued_keys = pending.popleft()
        new_keys = queued_keys - processed[parent_table]
        if not new_keys:
            continue
        processed[parent_table].update(new_keys)
        parent_key = primary_keys[parent_table][0]
        parent_values = {key[0] for key in new_keys}

        for child_table, child_fks in foreign_keys.items():
            child_keys = primary_keys[child_table]
            for fk in child_fks:
                if fk['table'] != parent_table or (fk['to'] and fk['to'] != parent_key):
                    continue
                child_column = fk['from']
                matches = select_child_keys(connection, child_table, child_keys, child_column, parent_values)
                if not matches:
                    continue
                if fk['on_delete'].upper() == 'CASCADE' or not table_is_nullable(connection, child_table, child_column):
                    new_matches = matches - deleting[child_table]
                    if new_matches:
                        deleting[child_table].update(new_matches)
                        pending.append((child_table, new_matches))
                else:
                    nulling[(child_table, child_column)].update(matches)

    return dict(deleting), dict(nulling)


def _where_keys(keys: tuple[str, ...], values: set[tuple[object, ...]]) -> tuple[str, list[object]]:
    clauses = []
    parameters: list[object] = []
    key_sql = ', '.join(quote_identifier(key) for key in keys)
    for row in values:
        clauses.append('(' + ' AND '.join(f'{quote_identifier(key)} = ?' for key in keys) + ')')
        parameters.extend(row)
    return ' OR '.join(clauses), parameters


def batched(values: set[tuple[object, ...]], size: int = 300):
    ordered = list(values)
    for start in range(0, len(ordered), size):
        yield set(ordered[start:start + size])


def apply_cleanup(
    connection: sqlite3.Connection,
    deleting: dict[str, set[tuple[object, ...]]],
    nulling: dict[tuple[str, str], set[tuple[object, ...]]],
) -> None:
    tables = {row['name'] for row in connection.execute('SELECT name FROM sqlite_master WHERE type = ? AND name NOT LIKE ?', ('table', 'sqlite_%')).fetchall()}
    primary_keys = {table: table_primary_key(connection, table) for table in tables}
    existing_violations = {tuple(row) for row in connection.execute('PRAGMA foreign_key_check').fetchall()}
    connection.execute('PRAGMA foreign_keys = OFF')
    connection.execute('BEGIN IMMEDIATE')
    try:
        for (table, column), keys_to_null in nulling.items():
            remaining = keys_to_null - deleting.get(table, set())
            if not remaining:
                continue
            for batch in batched(remaining):
                where, parameters = _where_keys(primary_keys[table], batch)
                connection.execute(
                    f'UPDATE {quote_identifier(table)} SET {quote_identifier(column)} = NULL WHERE {where}',
                    parameters,
                )

        for table, keys_to_delete in deleting.items():
            if not keys_to_delete:
                continue
            for batch in batched(keys_to_delete):
                where, parameters = _where_keys(primary_keys[table], batch)
                connection.execute(f'DELETE FROM {quote_identifier(table)} WHERE {where}', parameters)

        violations = {tuple(row) for row in connection.execute('PRAGMA foreign_key_check').fetchall()}
        new_violations = violations - existing_violations
        if new_violations:
            raise RuntimeError(f'Cleanup would introduce {len(new_violations)} new foreign-key violations; transaction rolled back.')
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.execute('PRAGMA foreign_keys = ON')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true', help='Back up the local database and apply the cleanup.')
    args = parser.parse_args()

    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / '.env', override=True)
    except ImportError:
        pass

    environment = (os.environ.get('ENVIRONMENT') or 'local').strip().lower()
    external_database = any(os.environ.get(name) for name in ('DATABASE_URL', 'DATABASE_EXTERNAL_URL', 'POSTGRES_URL', 'DEMO_DATABASE_URL'))
    if environment not in {'local', 'development', 'dev'} or external_database or os.environ.get('DEMO_MODE', '').strip().lower() in {'1', 'true', 'yes', 'on'}:
        raise RuntimeError('Отказ: очистка разрешена только для локальной SQLite instance/boostudy_dev.db.')
    if not DB_PATH.is_file():
        raise RuntimeError(f'Локальная база не найдена: {DB_PATH}')

    sys.path.insert(0, str(ROOT))
    from app.utils.local_dev_profile_pool import LOCAL_PROFILE_POOL
    allowed_usernames = {entry[0] for entry in LOCAL_PROFILE_POOL}

    connection = connect_readonly(DB_PATH)
    try:
        present = {row['username'] for row in connection.execute('SELECT username FROM Users WHERE username IN ({})'.format(
            ', '.join('?' for _ in allowed_usernames)
        ), sorted(allowed_usernames)).fetchall()}
        if present != allowed_usernames:
            missing = sorted(allowed_usernames - present)
            raise RuntimeError(f'Пул неполон ({len(present)}/{len(allowed_usernames)} профилей); очистка остановлена. Не найдены: {", ".join(missing)}')
        deleting, nulling = plan_cleanup(connection, allowed_usernames)
    finally:
        connection.close()

    deletions = sorted((table, len(rows)) for table, rows in deleting.items() if rows)
    print(f'База: {DB_PATH}')
    print(f'Профилей пула останется: {len(allowed_usernames)}')
    print('Будут удалены связанные строки:')
    for table, count in deletions:
        print(f'  {table}: {count}')
    print(f'Будут отвязаны nullable-ссылки: {sum(len(rows) for rows in nulling.values())}')

    if not args.apply:
        print('Режим просмотра: база не изменена. Для применения используйте --apply.')
        return 0

    backup_path = Path(tempfile.gettempdir()) / f'boostudy_dev_before_pool_cleanup_{datetime.now().strftime("%Y%m%d_%H%M%S")}.db'
    source = connect_readonly(DB_PATH)
    backup = sqlite3.connect(backup_path)
    try:
        source.backup(backup)
    finally:
        backup.close()
        source.close()

    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    try:
        apply_cleanup(connection, deleting, nulling)
        remaining_users = connection.execute('SELECT COUNT(*) FROM Users').fetchone()[0]
        remaining_students = connection.execute('''
            SELECT COUNT(*) FROM Students s
            LEFT JOIN Users u ON u.id = s.user_id
            WHERE u.username IS NULL OR u.username NOT IN ({})
        '''.format(', '.join('?' for _ in allowed_usernames)), sorted(allowed_usernames)).fetchone()[0]
        if remaining_users != len(allowed_usernames) or remaining_students:
            raise RuntimeError(f'Непредвиденный остаток профилей: Users={remaining_users}, студентов вне пула={remaining_students}; восстановите backup {backup_path}.')
    finally:
        connection.close()

    print(f'Осталось пользователей: {remaining_users}; учеников вне пула: {remaining_students}.')
    print(f'Резервная копия: {backup_path}')
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f'Ошибка: {exc}', file=sys.stderr)
        raise SystemExit(1)
