#!/usr/bin/env python3
"""
Экспорт обучающих данных для LLM-тренажёра.

Формирует наборы данных для fine-tuning на основе:
  - Эталонных прототипов из data/reference_prototypes/
  - Задач из БД с difficulty_level и hints
  - Статистики решений

Выходные форматы:
  1. JSONL для fine-tuning (OpenAI-совместимый формат)
  2. CSV для анализа
  3. Отчёт о покрытии

Запуск:
  python scripts/export_training_data.py [--output-dir exports] [--format jsonl|csv|both]
"""
import sys
import os
import json
import csv
import glob
import argparse
import logging
from datetime import datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

PROTOTYPES_DIR = os.path.join(os.path.dirname(__file__), '..', 'data', 'reference_prototypes')
SCHEMA_PATH = os.path.join(PROTOTYPES_DIR, 'prototype_schema.json')

# Варианты формулировок запроса подсказки (для аугментации)
HINT_REQUEST_VARIANTS = [
    "Дай мне подсказку уровня {}.",
    "Подскажи, что делать (уровень {}).",
    "Мне нужна подсказка уровня {}.",
    "Можешь дать подсказку {} уровня?",
    "Помоги, подсказка уровня {}.",
]


def load_prototypes():
    """Загружает все .json прототипы из каталога (исключая schema и template)."""
    prototypes = []
    pattern = os.path.join(PROTOTYPES_DIR, '**', '*.json')
    for filepath in glob.glob(pattern, recursive=True):
        basename = os.path.basename(filepath)
        if basename.startswith('_') or basename == 'prototype_schema.json':
            continue
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
            data['_source_file'] = filepath
            prototypes.append(data)
        except Exception as e:
            logger.warning(f"Ошибка загрузки {filepath}: {e}")
    return prototypes


def validate_prototype(proto: dict, schema: dict) -> list:
    """Простая валидация прототипа (проверяем required поля)."""
    errors = []
    required = schema.get('required', [])
    for field in required:
        if field not in proto:
            errors.append(f"Отсутствует обязательное поле: {field}")
    # Проверка диапазонов
    dl = proto.get('difficulty_level')
    if dl is not None and not (1 <= dl <= 10):
        errors.append(f"difficulty_level={dl} вне диапазона 1–10")
    tn = proto.get('task_number')
    if tn is not None and not (1 <= tn <= 27):
        errors.append(f"task_number={tn} вне диапазона 1–27")
    return errors


def prototype_to_training_sample(proto: dict) -> dict:
    """
    Конвертирует прототип в обучающий пример для fine-tuning.
    Формат: {"messages": [{"role": "system", ...}, {"role": "user", ...}, {"role": "assistant", ...}]}
    """
    system_prompt = (
        "Ты — опытный репетитор по информатике для ЕГЭ. "
        "Помогай ученику решить задание, давай подсказки по нарастающей, "
        "объясняй каждый шаг решения доступным языком. "
        f"Задание #{proto.get('task_number', '?')}, тема: {proto.get('topic_name', '?')}, "
        f"сложность: {proto.get('difficulty_label', 'medium')}."
    )

    user_prompt = proto.get('prototype', {}).get('text', '')

    # Формируем ответ из пошагового решения
    solution = proto.get('solution', {})
    steps = solution.get('steps', [])
    answer_parts = []
    for step in steps:
        part = f"**Шаг {step.get('step', '?')}:** {step.get('explanation', '')}"
        if step.get('code'):
            part += f"\n```python\n{step['code']}\n```"
        if step.get('formula'):
            part += f"\n\\({step['formula']}\\)"
        answer_parts.append(part)

    answer_text = proto.get('answer', '')
    assistant_response = "\n\n".join(answer_parts)
    if answer_text:
        assistant_response += f"\n\n**Ответ: {answer_text}**"

    return {
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
            {"role": "assistant", "content": assistant_response},
        ]
    }


def _hint_system_prompt(proto: dict, level: int) -> str:
    """Системный промпт для подсказок с жёстким запретом на решение."""
    return (
        "Ты — репетитор ЕГЭ по информатике. Ученик попросил подсказку. "
        f"Дай подсказку уровня {level} (1 — идея, 2 — структура, 3 — наводка). "
        f"Задание #{proto.get('task_number', '?')}, тема: {proto.get('topic_name', '?')}. "
        "ЖЁСТКОЕ ПРАВИЛО: НЕЛЬЗЯ выдавать полное решение, итоговый код или ответ. "
        "Только подсказки: вопросы, аналогии, наводки — без готового кода."
    )


def prototype_to_hint_samples(proto: dict, augment: bool = True) -> list:
    """
    Генерирует обучающие примеры для модели подсказок.
    По одному примеру на каждый уровень hint_ladder.
    При augment=True — добавляет вариации формулировок запроса (аугментация).
    """
    hints = proto.get('hint_ladder', [])
    if not hints:
        return []

    samples = []
    task_text = proto.get('prototype', {}).get('text', '')

    for hint in hints:
        level = hint.get('level', 1)
        hint_text = hint.get('text', '')
        if not hint_text:
            continue

        system_prompt = _hint_system_prompt(proto, level)

        # Базовый вариант
        user_variants = [f"Задание: {task_text}\n\nДай мне подсказку уровня {level}."]

        # Аугментация: другие формулировки запроса
        if augment:
            for tpl in HINT_REQUEST_VARIANTS[1:]:  # первый уже есть в базовом
                user_variants.append(f"Задание: {task_text}\n\n{tpl.format(level)}")

        for user_msg in user_variants:
            samples.append({
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_msg},
                    {"role": "assistant", "content": hint_text},
                ]
            })
    return samples


def prototype_to_difficulty_sample(proto: dict) -> dict:
    """
    Обучающий пример для классификатора сложности.
    """
    system_prompt = (
        "Ты — эксперт по ЕГЭ. Определи уровень сложности задания (1–10, "
        "где 1–3 Easy, 4–7 Medium, 8–10 Hard). "
        "Ответь только числом."
    )
    task_text = proto.get('prototype', {}).get('text', '')
    return {
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Задание #{proto.get('task_number', '?')}:\n{task_text}"},
            {"role": "assistant", "content": str(proto.get('difficulty_level', 5))},
        ]
    }


def export_db_tasks(output_dir: str, fmt: str):
    """Экспортирует задачи из БД с difficulty и hints."""
    try:
        from app import create_app
        app = create_app()
        with app.app_context():
            from app.models import db
            from core.db_models import Tasks

            tasks = Tasks.query.filter(Tasks.difficulty_level.isnot(None)).all()
            logger.info(f"Задач с difficulty_level в БД: {len(tasks)}")

            if fmt in ('csv', 'both'):
                csv_path = os.path.join(output_dir, 'db_tasks_difficulty.csv')
                with open(csv_path, 'w', encoding='utf-8', newline='') as f:
                    writer = csv.writer(f)
                    writer.writerow(['task_id', 'task_number', 'difficulty_level', 'difficulty_label', 'has_hints', 'knowledge_node_id'])
                    for t in tasks:
                        writer.writerow([
                            t.task_id,
                            t.task_number,
                            t.difficulty_level,
                            t.difficulty_label,
                            bool(t.hints),
                            t.knowledge_node_id,
                        ])
                logger.info(f"CSV экспорт: {csv_path}")

            if fmt in ('jsonl', 'both'):
                jsonl_path = os.path.join(output_dir, 'db_tasks_with_hints.jsonl')
                count = 0
                with open(jsonl_path, 'w', encoding='utf-8') as f:
                    for t in tasks:
                        if t.hints:
                            record = {
                                "task_id": t.task_id,
                                "task_number": t.task_number,
                                "difficulty_level": t.difficulty_level,
                                "difficulty_label": t.difficulty_label,
                                "hints": t.hints,
                                "content_preview": (t.content_html or '')[:500],
                                "answer": t.answer,
                            }
                            f.write(json.dumps(record, ensure_ascii=False) + '\n')
                            count += 1
                logger.info(f"JSONL экспорт (задачи с hints): {jsonl_path} ({count} записей)")
    except Exception as e:
        logger.warning(f"Не удалось экспортировать из БД: {e}")


def _proto_split_key(proto: dict) -> tuple:
    """Ключ для разбиения по прототипу (train/val)."""
    return (
        proto.get('task_number', 0),
        proto.get('difficulty_label', ''),
        proto.get('_source_file', ''),
    )


def split_prototypes_train_val(prototypes: list, val_ratio: float = 0.15) -> tuple[list, list]:
    """
    Разбивает прототипы на train и val.
    Детерминированно: одни и те же прототипы всегда попадают в один и тот же набор.
    """
    keys = [_proto_split_key(p) for p in prototypes]
    unique_keys = sorted(set(keys))
    n_val = max(1, int(len(unique_keys) * val_ratio))
    val_keys = set(unique_keys[-n_val:])  # последние N ключей — val (стабильный порядок)

    train_protos = [p for p in prototypes if _proto_split_key(p) not in val_keys]
    val_protos = [p for p in prototypes if _proto_split_key(p) in val_keys]
    return train_protos, val_protos


def generate_coverage_report(prototypes: list, output_dir: str):
    """Отчёт о покрытии: какие задания/сложности представлены. Серия 19–21: один прототип учитывается для всех номеров из series_task_numbers."""
    coverage = {}
    for p in prototypes:
        dl = p.get('difficulty_label', 'unknown')
        task_numbers = p.get('series_task_numbers')
        if isinstance(task_numbers, list) and len(task_numbers) > 0:
            task_numbers = [t for t in task_numbers if isinstance(t, int) and 1 <= t <= 27]
        else:
            tn = p.get('task_number', 0)
            task_numbers = [tn] if isinstance(tn, int) and 1 <= tn <= 27 else []
        for tn in task_numbers:
            if tn not in coverage:
                coverage[tn] = {'easy': 0, 'medium': 0, 'hard': 0}
            if dl in coverage[tn]:
                coverage[tn][dl] += 1

    report_path = os.path.join(output_dir, 'coverage_report.txt')
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write("=" * 60 + "\n")
        f.write("ОТЧЁТ О ПОКРЫТИИ ЭТАЛОННЫХ ПРОТОТИПОВ\n")
        f.write(f"Дата: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
        f.write("=" * 60 + "\n\n")
        f.write(f"{'Задание':>10} | {'Easy':>6} | {'Medium':>8} | {'Hard':>6} | {'Всего':>6}\n")
        f.write(f"{'-'*10} | {'-'*6} | {'-'*8} | {'-'*6} | {'-'*6}\n")

        total_all = 0
        for tn in sorted(coverage.keys()):
            c = coverage[tn]
            total = c['easy'] + c['medium'] + c['hard']
            total_all += total
            f.write(f"     #{tn:<5} | {c['easy']:>6} | {c['medium']:>8} | {c['hard']:>6} | {total:>6}\n")

        # Пробелы для незанятых заданий
        missing = [i for i in range(1, 28) if i not in coverage]
        f.write(f"\nВсего прототипов: {total_all}\n")
        if missing:
            f.write(f"Задания без прототипов: {', '.join(f'#{m}' for m in missing)}\n")
        else:
            f.write("Все 27 заданий покрыты!\n")

    logger.info(f"Отчёт о покрытии: {report_path}")
    return report_path


def main():
    parser = argparse.ArgumentParser(description="Экспорт обучающих данных для LLM")
    parser.add_argument('--output-dir', default='exports', help="Каталог для экспорта (default: exports)")
    parser.add_argument('--format', choices=['jsonl', 'csv', 'both'], default='both', help="Формат экспорта")
    parser.add_argument('--include-db', action='store_true', help="Включить экспорт задач из БД")
    parser.add_argument('--val-ratio', type=float, default=0.15, help="Доля validation (0.15 = 15%%, default: 0.15)")
    parser.add_argument('--no-augment', action='store_true', help="Отключить аугментацию формулировок подсказок")
    args = parser.parse_args()

    output_dir = os.path.abspath(args.output_dir)
    os.makedirs(output_dir, exist_ok=True)

    # --- Загрузка и валидация прототипов ---
    prototypes = load_prototypes()
    logger.info(f"Загружено прототипов: {len(prototypes)}")

    schema = {}
    if os.path.exists(SCHEMA_PATH):
        with open(SCHEMA_PATH, 'r', encoding='utf-8') as f:
            schema = json.load(f)

    valid_protos = []
    for proto in prototypes:
        errors = validate_prototype(proto, schema)
        if errors:
            logger.warning(f"Прототип {proto.get('_source_file', '?')}: {errors}")
        else:
            valid_protos.append(proto)

    logger.info(f"Валидных прототипов: {len(valid_protos)}")

    # --- Train/Val split ---
    train_protos, val_protos = split_prototypes_train_val(valid_protos, val_ratio=args.val_ratio)
    logger.info(f"Split: train={len(train_protos)} прототипов, val={len(val_protos)} прототипов")

    augment = not args.no_augment

    # --- Генерация обучающих примеров ---
    solution_samples = []
    hint_samples_train = []
    hint_samples_val = []
    difficulty_samples = []

    for proto in valid_protos:
        solution_samples.append(prototype_to_training_sample(proto))
        difficulty_samples.append(prototype_to_difficulty_sample(proto))

    for proto in train_protos:
        hint_samples_train.extend(prototype_to_hint_samples(proto, augment=augment))
    for proto in val_protos:
        hint_samples_val.extend(prototype_to_hint_samples(proto, augment=augment))

    hint_samples_all = hint_samples_train + hint_samples_val

    # --- Экспорт JSONL ---
    if args.format in ('jsonl', 'both'):
        # Файлы для fine-tuning подсказок (главный датасет)
        for name, samples in [
            ('train_hints.jsonl', hint_samples_train),
            ('val_hints.jsonl', hint_samples_val),
        ]:
            path = os.path.join(output_dir, name)
            with open(path, 'w', encoding='utf-8') as f:
                for sample in samples:
                    f.write(json.dumps(sample, ensure_ascii=False) + '\n')
            logger.info(f"  {name}: {len(samples)} примеров")

        # Обратная совместимость: полный набор
        path = os.path.join(output_dir, 'training_hints.jsonl')
        with open(path, 'w', encoding='utf-8') as f:
            for sample in hint_samples_all:
                f.write(json.dumps(sample, ensure_ascii=False) + '\n')
        logger.info(f"  training_hints.jsonl: {len(hint_samples_all)} примеров (train+val)")

        # Остальные сэмплы (решения, классификация) — без split, для справки
        for name, samples in [
            ('training_solutions.jsonl', solution_samples),
            ('training_difficulty.jsonl', difficulty_samples),
        ]:
            path = os.path.join(output_dir, name)
            with open(path, 'w', encoding='utf-8') as f:
                for sample in samples:
                    f.write(json.dumps(sample, ensure_ascii=False) + '\n')
            logger.info(f"  {name}: {len(samples)} примеров")

    # --- Экспорт CSV ---
    if args.format in ('csv', 'both'):
        csv_path = os.path.join(output_dir, 'prototypes_summary.csv')
        with open(csv_path, 'w', encoding='utf-8', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['task_number', 'topic_code', 'topic_name', 'difficulty_level', 'difficulty_label', 'has_hints', 'num_steps', 'answer', 'source'])
            for proto in valid_protos:
                writer.writerow([
                    proto.get('task_number'),
                    proto.get('topic_code'),
                    proto.get('topic_name'),
                    proto.get('difficulty_level'),
                    proto.get('difficulty_label'),
                    bool(proto.get('hint_ladder')),
                    len(proto.get('solution', {}).get('steps', [])),
                    proto.get('answer'),
                    proto.get('source', ''),
                ])
        logger.info(f"  prototypes_summary.csv: {len(valid_protos)} записей")

    # --- Отчёт о покрытии ---
    generate_coverage_report(valid_protos, output_dir)

    # --- Экспорт из БД ---
    if args.include_db:
        export_db_tasks(output_dir, args.format)

    print(f"\n[OK] Экспорт завершён в: {output_dir}")
    print(f"   Подсказки (train): {len(hint_samples_train)} примеров")
    print(f"   Подсказки (val):   {len(hint_samples_val)} примеров")
    print(f"   Решения:          {len(solution_samples)} примеров")
    print(f"   Сложность:       {len(difficulty_samples)} примеров")


if __name__ == '__main__':
    main()
