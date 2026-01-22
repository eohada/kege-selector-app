# База знаний для ИИ‑тренажёра

Файлы лежат в `trainer_knowledge/tasks/*.json`.

Один файл = знания по одной задаче из таблицы `Tasks` (по `task_id`).

## Зачем это нужно
- Давать **ступенчатые** подсказки (hint ladder), а не «готовое решение».
- Учитывать **типовые ошибки** и подбирать вопросы ученику.
- (Опционально) использовать `tests` для локальной проверки (на сервере раннер может быть выключен).

## Формат файла
См. шаблон: `trainer_knowledge/tasks/_TEMPLATE.json`

Ключевые поля:
- `task_id` (int) — ID задачи из `Tasks.task_id`
- `task_number` (int) — номер задания ЕГЭ (1..27)
- `language` (str) — например `"python"`
- `title` (str) — короткое название
- `hint_ladder` — список подсказок по уровням (1..3 обычно)
- `common_mistakes` — список строк
- `reference_solution` — **для ориентира**, нельзя выдавать ученику целиком
- `tests` — простые тесты вида `{name,input,expected}` (строки)

## Проверка формата
При загрузке knowledge‑файла выполняется валидация (см. `trainer_app/knowledge.py`).
Если хотите «падать» при любой ошибке формата, задайте переменную окружения:
- `TRAINER_STRICT_KNOWLEDGE=1`

## trainer_knowledge

Эта папка — база примеров/эталонных решений для AI-помощника тренажёра.

### Структура
- `trainer_knowledge/tasks/<task_id>.json` — знание по конкретной задаче из банка (`Tasks.task_id`).

### Формат `tasks/<task_id>.json`
- **task_id**: int
- **task_number**: int (номер задания КЕГЭ)
- **language**: string (пока: `python`)
- **reference_solution**: string (эталон/пример решения)
- **common_mistakes**: array of strings
- **hint_ladder**: array of objects `{ "level": int, "hint": string }` (подсказки по уровням, от мягких к более прямым)
- **tests**: array of objects `{ "name": string, "input": string, "expected": string }`

Примечание: тесты здесь — **синтетические** (для тренировки/проверки логики), они не обязаны совпадать с реальным файлом из условия.

