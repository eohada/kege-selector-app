#!/usr/bin/env python3
"""
Скрипт автоматической разметки difficulty_level для задач в таблице Tasks.

Приоритет определения сложности:
  1. Статистика решений (correct_rate) — главный сигнал
  2. Если статистики нет — base_rating узла или base_elo из data/difficulty_rules.json (по task_number)
  3. По умолчанию — medium (5)

Источники статистики:
  - LessonTask.submission_correct  (задачи из уроков)
  - Answer.is_correct              (задачи из работ/assignments)
  - AnalyticsEvent.is_correct      (логи аналитики)

Пороги:
  correct_rate >= 0.80 → Easy  (difficulty_level = 1)
  0.40 <= correct_rate < 0.80 → Medium (difficulty_level = 2)
  correct_rate < 0.40 → Hard (difficulty_level = 3)

Запуск:
  python scripts/auto_label_difficulty.py [--dry-run] [--min-answers 3] [--force]

Флаги:
  --dry-run      Только показать, что будет изменено (без записи в БД)
  --min-answers  Минимум ответов для доверия статистике (по умолчанию 3)
  --force        Перезаписать уже проставленный difficulty_level
"""
import sys
import os
import json
import argparse
import logging

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from collections import defaultdict

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
DIFFICULTY_RULES_PATH = os.path.join(REPO_ROOT, 'data', 'difficulty_rules.json')

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


def load_rules_base_elo():
    """Загружает base_elo по номеру задания из data/difficulty_rules.json. Возвращает dict: task_number -> base_elo."""
    result = {}
    if not os.path.isfile(DIFFICULTY_RULES_PATH):
        return result
    try:
        with open(DIFFICULTY_RULES_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        tasks = data.get('tasks') or {}
        for k, v in tasks.items():
            if isinstance(v, dict) and 'base_elo' in v:
                try:
                    result[int(k)] = int(v['base_elo'])
                except (ValueError, TypeError):
                    pass
    except Exception as e:
        logger.warning(f"Не удалось загрузить difficulty_rules.json: {e}")
    return result


def create_app_context():
    """Создаём контекст Flask-приложения."""
    from app import create_app
    app = create_app()
    return app


def gather_statistics(db_session):
    """
    Собирает статистику правильности по task_id из всех источников.
    Возвращает dict: {task_id: {"correct": int, "total": int}}
    """
    from core.db_models import LessonTask, Answer, AnalyticsEvent, Tasks
    from sqlalchemy import func

    stats = defaultdict(lambda: {"correct": 0, "total": 0})

    # --- Источник 1: LessonTask ---
    logger.info("Сбор статистики из LessonTask...")
    lt_rows = (
        db_session.query(
            LessonTask.task_id,
            func.count().label('total'),
            func.sum(
                func.cast(LessonTask.submission_correct == True, db.Integer)
            ).label('correct'),
        )
        .filter(LessonTask.submission_correct.isnot(None))
        .group_by(LessonTask.task_id)
        .all()
    )
    for row in lt_rows:
        stats[row.task_id]["total"] += row.total or 0
        stats[row.task_id]["correct"] += row.correct or 0

    # --- Источник 2: Answer (работы/assignments) ---
    logger.info("Сбор статистики из Answer...")
    from core.db_models import AssignmentTask
    answer_rows = (
        db_session.query(
            AssignmentTask.task_id,
            func.count().label('total'),
            func.sum(
                func.cast(Answer.is_correct == True, db.Integer)
            ).label('correct'),
        )
        .join(Answer, Answer.assignment_task_id == AssignmentTask.assignment_task_id)
        .filter(Answer.is_correct.isnot(None))
        .group_by(AssignmentTask.task_id)
        .all()
    )
    for row in answer_rows:
        if row.task_id:
            stats[row.task_id]["total"] += row.total or 0
            stats[row.task_id]["correct"] += row.correct or 0

    # --- Источник 3: AnalyticsEvent ---
    logger.info("Сбор статистики из AnalyticsEvent...")
    ae_rows = (
        db_session.query(
            AnalyticsEvent.task_id,
            func.count().label('total'),
            func.sum(
                func.cast(AnalyticsEvent.is_correct == True, db.Integer)
            ).label('correct'),
        )
        .filter(AnalyticsEvent.task_id.isnot(None))
        .group_by(AnalyticsEvent.task_id)
        .all()
    )
    for row in ae_rows:
        stats[row.task_id]["total"] += row.total or 0
        stats[row.task_id]["correct"] += row.correct or 0

    return stats


def correct_rate_to_difficulty(rate: float) -> int:
    """Конвертирует процент правильных ответов в difficulty_level (1–3)."""
    if rate >= 0.80:
        return 1
    if rate >= 0.40:
        return 2
    return 3


def base_rating_to_difficulty(base_rating: float) -> int:
    """Эвристика: base_rating узла → difficulty_level 1–3."""
    if base_rating <= 900:
        return 1
    if base_rating <= 1050:
        return 2
    return 3


def main():
    parser = argparse.ArgumentParser(description="Автоматическая разметка difficulty_level для задач")
    parser.add_argument('--dry-run', action='store_true', help="Только показать изменения, не записывать в БД")
    parser.add_argument('--min-answers', type=int, default=3, help="Минимум ответов для использования статистики (default: 3)")
    parser.add_argument('--force', action='store_true', help="Перезаписать уже проставленный difficulty_level")
    args = parser.parse_args()

    app = create_app_context()

    with app.app_context():
        global db
        from app.models import db
        from core.db_models import Tasks, KnowledgeNode

        # --- Собираем статистику ---
        stats = gather_statistics(db.session)
        logger.info(f"Статистика собрана для {len(stats)} задач")

        # --- Правила сложности (фоллбэк по task_number) ---
        rules_base_elo = load_rules_base_elo()
        if rules_base_elo:
            logger.info(f"Загружены base_elo из difficulty_rules.json для типов: {len(rules_base_elo)}")

        # --- Загружаем все задачи ---
        query = Tasks.query
        if not args.force:
            query = query.filter(Tasks.difficulty_level.is_(None))
        tasks = query.all()
        logger.info(f"Задач для обработки: {len(tasks)} (force={args.force})")

        # --- Считаем ---
        labeled_by_stats = 0
        labeled_by_heuristic = 0
        skipped = 0
        changes = []

        for task in tasks:
            task_stat = stats.get(task.task_id)

            new_difficulty = None
            method = None

            if task_stat and task_stat["total"] >= args.min_answers:
                rate = task_stat["correct"] / task_stat["total"]
                new_difficulty = correct_rate_to_difficulty(rate)
                method = f"stats (rate={rate:.2f}, n={task_stat['total']})"
                labeled_by_stats += 1
            else:
                # Фоллбэк: base_rating узла → base_elo из difficulty_rules по task_number → default medium
                node = task.knowledge_node
                base_rating_val = None
                if node and getattr(node, 'base_rating', None) is not None:
                    base_rating_val = float(node.base_rating)
                    method = f"heuristic (base_rating={node.base_rating})"
                elif task.task_number and task.task_number in rules_base_elo:
                    base_rating_val = float(rules_base_elo[task.task_number])
                    method = f"rules (base_elo={rules_base_elo[task.task_number]}, task_number={task.task_number})"
                if base_rating_val is not None:
                    new_difficulty = base_rating_to_difficulty(base_rating_val)
                    labeled_by_heuristic += 1
                else:
                    new_difficulty = 5  # Medium по умолчанию
                    method = "default (no data)"
                    labeled_by_heuristic += 1

            old_difficulty = task.difficulty_level
            if old_difficulty == new_difficulty:
                skipped += 1
                continue

            changes.append({
                "task_id": task.task_id,
                "task_number": task.task_number,
                "old": old_difficulty,
                "new": new_difficulty,
                "method": method,
            })

            if not args.dry_run:
                task.difficulty_level = new_difficulty

        # --- Отчёт ---
        print("\n" + "=" * 70)
        print("ОТЧЁТ ПО РАЗМЕТКЕ СЛОЖНОСТИ")
        print("=" * 70)
        print(f"  Всего задач обработано:           {len(tasks)}")
        print(f"  Размечено по статистике решений:   {labeled_by_stats}")
        print(f"  Размечено по эвристике/умолчанию:  {labeled_by_heuristic}")
        print(f"  Пропущено (без изменений):         {skipped}")
        print(f"  Изменено:                          {len(changes)}")
        print()

        if changes:
            print("Изменения (первые 50):")
            print(f"  {'task_id':>8} | {'#':>3} | {'old':>5} → {'new':>5} | метод")
            print(f"  {'-'*8} | {'-'*3} | {'-'*5}   {'-'*5} | {'-'*30}")
            for ch in changes[:50]:
                old_str = str(ch['old']) if ch['old'] is not None else 'NULL'
                print(f"  {ch['task_id']:>8} | {ch['task_number']:>3} | {old_str:>5} → {ch['new']:>5} | {ch['method']}")
            if len(changes) > 50:
                print(f"  ... и ещё {len(changes) - 50} изменений")
            print()

        if args.dry_run:
            print("⚠️  DRY RUN — изменения НЕ записаны в БД.")
            print("  Уберите --dry-run для записи.")
        else:
            try:
                db.session.commit()
                print("✅ Изменения сохранены в БД.")
            except Exception as e:
                db.session.rollback()
                print(f"❌ Ошибка при сохранении: {e}")
                sys.exit(1)

        print()


if __name__ == '__main__':
    main()
