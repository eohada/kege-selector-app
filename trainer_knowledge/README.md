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

