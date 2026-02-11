# Генерация решений на хосте (Timeweb)

Скрипт `scripts/generate_solutions_for_all_tasks.py` проходится по всем заданиям в БД и генерирует решения через LLM.

## 1. Зависимости

Все нужные пакеты в `requirements.txt`:

- **Groq** — только `requests` (уже есть)
- **GigaChat** — `gigachat>=0.1.38` (добавлен в requirements)
- **Gemini** — только `requests`

После деплоя на хост выполните:

```bash
pip install -r requirements.txt
```

## 2. Переменные окружения

Выберите один провайдер и задайте ключи:

| Провайдер | Переменные | Приоритет |
|-----------|------------|-----------|
| Groq | `GROQ_API_KEY` | 1 (по умолчанию) |
| Gemini | `GEMINI_API_KEY` | 2 |
| GigaChat | `GIGACHAT_CREDENTIALS` | 3 |

Чтобы явно выбрать провайдер:

```bash
export TRAINER_LLM_PROVIDER=groq   # или gemini, gigachat
```

## 3. Запуск на хосте

```bash
# Перейти в корень проекта
cd /path/to/kege_selector_app

# Активировать venv (если есть)
source .venv/bin/activate   # Linux
# или: .venv\Scripts\activate   # Windows

# Тест без сохранения (5 заданий)
python scripts/generate_solutions_for_all_tasks.py --limit 5 --dry-run

# Реальная генерация (5 заданий для проверки)
python scripts/generate_solutions_for_all_tasks.py --limit 5

# Полная генерация (все задания, лучше в screen/tmux)
python scripts/generate_solutions_for_all_tasks.py
```

### Параметры

| Параметр | Описание |
|----------|----------|
| `--limit N` | Обработать только N заданий (0 = все) |
| `--task-number N` | Только задания с номером N (1–27) |
| `--force` | Перезаписать существующие решения |
| `--dry-run` | Не сохранять в БД |
| `--batch-size N` | Коммитить каждые N заданий (по умолчанию 10) |

## 4. Долгий запуск (screen/tmux)

Для нескольких тысяч заданий запуск займёт часы. Рекомендуется:

```bash
# screen
screen -S solutions
python scripts/generate_solutions_for_all_tasks.py
# Ctrl+A, D — отключиться
# screen -r solutions — вернуться

# или tmux
tmux new -s solutions
python scripts/generate_solutions_for_all_tasks.py
# Ctrl+B, D — отключиться
# tmux attach -t solutions — вернуться
```

## 5. Результат

Решения сохраняются в таблицу `TaskSolutions`. Просмотр: **Remote Admin → Решения заданий**.
