# Экспорт для fine-tuning LLM

Датасет для дообучения модели подсказок.

## Файлы

| Файл | Описание |
|------|----------|
| `train_hints.jsonl` | Обучающая выборка подсказок (~85% прототипов) |
| `val_hints.jsonl` | Валидационная выборка (~15% прототипов) |
| `training_hints.jsonl` | Вся выборка (train + val) |
| `training_solutions.jsonl` | Примеры полных решений (для справки, не для fine-tuning подсказок) |
| `training_difficulty.jsonl` | Примеры классификации сложности |
| `prototypes_summary.csv` | Сводка по прототипам |
| `coverage_report.txt` | Отчёт о покрытии заданий |

## Формат JSONL

Каждая строка — JSON с полем `messages` (OpenAI-совместимый):

```json
{
  "messages": [
    {"role": "system", "content": "Ты — репетитор... ЖЁСТКОЕ ПРАВИЛО: НЕЛЬЗЯ выдавать полное решение..."},
    {"role": "user", "content": "Задание: <текст>\n\nДай подсказку уровня 1."},
    {"role": "assistant", "content": "Посчитай степень вершины..."}
  ]
}
```

## Пересборка

```bash
python scripts/export_training_data.py --output-dir exports
```

Флаги:
- `--val-ratio 0.15` — доля validation (по умолчанию 15%)
- `--no-augment` — отключить аугментацию формулировок

## Fine-tuning

Для дообучения модели подсказок используйте **только** `train_hints.jsonl` и `val_hints.jsonl`.

- **OpenAI:** загрузить через Fine-tuning API
- **GigaChat:** проверить документацию на fine-tuning
- **Другие:** формат messages совместим с OpenAI Chat Completions
