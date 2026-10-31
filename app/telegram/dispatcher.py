"""Durable Telegram Outbox Dispatcher.

Processes pending deliveries, assignment notifications, lesson reminders,
and recovers stale claims for Windows + SQLite local development.
Includes inter-process locking to prevent duplicate concurrent dispatchers.
"""
from __future__ import annotations

import argparse
import logging
import os
import threading
import time
from typing import Any

from core.db_models import db
from app.telegram.delivery import (
    claim_due_deliveries,
    deliver_one,
    recover_stale_processing,
)
from app.notifications.service import process_pending_assignment_notifications

logger = logging.getLogger(__name__)


class DispatcherLock:
    """Inter-process file lock ensuring only one dispatcher loop runs at a time."""

    def __init__(self, lockfile_path: str | None = None):
        if not lockfile_path:
            from flask import current_app, has_app_context
            instance_dir = current_app.instance_path if has_app_context() else os.path.join(os.getcwd(), 'instance')
            lockfile_path = os.path.join(instance_dir, 'dispatcher.lock')
        self.lockfile_path = lockfile_path
        self._file = None
        self._acquired = False

    def acquire(self) -> bool:
        try:
            os.makedirs(os.path.dirname(self.lockfile_path), exist_ok=True)
            self._file = open(self.lockfile_path, 'a+')
            if os.name == 'nt':
                import msvcrt
                self._file.seek(0)
                msvcrt.locking(self._file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self._file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            self._file.seek(0)
            self._file.truncate(0)
            self._file.write(f'{os.getpid()}\n')
            self._file.flush()
            self._acquired = True
            return True
        except (IOError, OSError):
            if self._file:
                try:
                    self._file.close()
                except Exception:
                    pass
                self._file = None
            self._acquired = False
            return False

    def release(self) -> None:
        if self._acquired and self._file:
            try:
                if os.name == 'nt':
                    import msvcrt
                    self._file.seek(0)
                    msvcrt.locking(self._file.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(self._file.fileno(), fcntl.LOCK_UN)
            except Exception:
                pass
            try:
                self._file.close()
            except Exception:
                pass
            self._acquired = False
            self._file = None


def run_dispatch_cycle() -> dict[str, Any]:
    """Execute one complete pass of the outbox delivery pipeline."""
    stats = {
        'recovered': 0,
        'assignments': 0,
        'reminders': 0,
        'claimed': 0,
        'sent': 0,
        'simulated': 0,
        'failed': 0,
        'retry': 0,
        'cancelled': 0,
        'skipped': 0,
    }

    # 1. Recover stale in-flight claims
    try:
        stats['recovered'] = recover_stale_processing(timeout_minutes=10)
    except Exception as e:
        logger.warning('dispatcher recover_stale_processing error: %s', e)

    # 2. Debounced assignment notifications
    try:
        stats['assignments'] = process_pending_assignment_notifications()
    except Exception as e:
        logger.warning('dispatcher process_pending_assignment_notifications error: %s', e)

    # 3. 30-minute lesson reminders
    try:
        from app.tasks.telegram_lesson_reminders import telegram_lesson_reminders_task
        res = telegram_lesson_reminders_task()
        stats['reminders'] = res.get('sent', 0) if isinstance(res, dict) else 0
    except Exception as e:
        logger.warning('dispatcher telegram_lesson_reminders_task error: %s', e)

    # 4. Claim and deliver due outbox records
    try:
        due_ids = claim_due_deliveries(limit=50)
        stats['claimed'] = len(due_ids)
        for did in due_ids:
            try:
                res = deliver_one(did)
                status = res.get('status', 'unknown')
                if status == 'sent':
                    stats['sent'] += 1
                elif status == 'simulated':
                    stats['simulated'] += 1
                elif status == 'failed':
                    stats['failed'] += 1
                elif status in {'retry', 'deferred_quiet_hours'}:
                    stats['retry'] += 1
                elif status == 'cancelled':
                    stats['cancelled'] += 1
                else:
                    stats['skipped'] += 1
            except Exception as e:
                logger.error('dispatcher deliver_one failed did=%s: %s', did, e)
                stats['failed'] += 1
    except Exception as e:
        logger.error('dispatcher claim_due_deliveries error: %s', e)

    return stats


def _dispatcher_worker(interval: int, stop_event: threading.Event) -> None:
    from wsgi import app
    lock = DispatcherLock()
    if not lock.acquire():
        logger.warning('Another Telegram outbox dispatcher is already active. Skipping duplicate dispatcher loop.')
        return

    logger.info('Telegram outbox dispatcher thread started (interval=%ss, PID=%s)', interval, os.getpid())
    try:
        with app.app_context():
            while not stop_event.is_set():
                try:
                    stats = run_dispatch_cycle()
                    if (stats['claimed'] > 0 or stats['assignments'] > 0
                            or stats['reminders'] > 0 or stats['simulated'] > 0):
                        logger.info('Telegram outbox dispatch cycle: %s', stats)
                except Exception as e:
                    logger.error('Unhandled error in dispatcher cycle: %s', e)
                stop_event.wait(interval)
    finally:
        lock.release()
        logger.info('Telegram outbox dispatcher thread stopped')


_dispatcher_thread: threading.Thread | None = None
_stop_event = threading.Event()


def start_dispatcher_thread(interval: int = 5) -> threading.Thread | None:
    """Start background dispatcher thread if not already running."""
    global _dispatcher_thread, _stop_event
    if _dispatcher_thread is not None and _dispatcher_thread.is_alive():
        return _dispatcher_thread

    _stop_event.clear()
    _dispatcher_thread = threading.Thread(
        target=_dispatcher_worker,
        args=(interval, _stop_event),
        name='TelegramOutboxDispatcher',
        daemon=True,
    )
    _dispatcher_thread.start()
    return _dispatcher_thread


def stop_dispatcher_thread(timeout: float = 5.0) -> None:
    global _dispatcher_thread, _stop_event
    if _dispatcher_thread is not None and _dispatcher_thread.is_alive():
        _stop_event.set()
        _dispatcher_thread.join(timeout=timeout)
        _dispatcher_thread = None


def main():
    parser = argparse.ArgumentParser(description="BooStudy Telegram Outbox Dispatcher")
    parser.add_argument('--once', action='store_true', help="Run single dispatch pass and exit")
    parser.add_argument('--interval', type=int, default=5, help="Loop interval in seconds (default: 5)")
    args = parser.parse_args()

    from wsgi import app
    with app.app_context():
        if args.once:
            print("Running single dispatch pass...")
            stats = run_dispatch_cycle()
            print("Dispatch results:", stats)
        else:
            lock = DispatcherLock()
            if not lock.acquire():
                print(f"[WARN] Another dispatcher process is already running (locked at {lock.lockfile_path}). Exiting.")
                return
            print(f"Starting dispatcher loop every {args.interval}s (Ctrl+C to stop)...")
            try:
                while True:
                    stats = run_dispatch_cycle()
                    if (stats['claimed'] > 0 or stats['assignments'] > 0
                            or stats['reminders'] > 0 or stats['simulated'] > 0):
                        print("Dispatch stats:", stats)
                    time.sleep(args.interval)
            except KeyboardInterrupt:
                print("\nDispatcher stopped.")
            finally:
                lock.release()


if __name__ == '__main__':
    main()
