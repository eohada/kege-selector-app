# Генерация решений на хосте (Timeweb)

## Порядок действий

1. **Скачать вложения** — `python scripts/download_all_task_attachments.py`
2. **Настроить GIGACHAT_CREDENTIALS**
3. **Запустить генерацию** — `python scripts/generate_solutions_for_all_tasks.py`

Скрипт `scripts/generate_solutions_for_all_tasks.py` проходится по всем заданиям в БД и генерирует решения через LLM (GigaChat). Решения включают: источник, условие задачи, пошаговое решение. Ответ сверяется с источником — при расхождении помечается «Ручная проверка».

## 1. Зависимости

Все нужные пакеты в `requirements.txt`:

- **GigaChat** — `gigachat>=0.1.38`

После деплоя на хост выполните:

```bash
pip install -r requirements.txt
```

## 2. Переменные окружения

Задайте credentials GigaChat:

```bash
export GIGACHAT_CREDENTIALS="ваш_authorization_key"
```

Опционально: `GIGACHAT_MODEL`, `GIGACHAT_SCOPE`, `GIGACHAT_VERIFY_SSL_CERTS`, `GIGACHAT_CA_BUNDLE_FILE`.

**Сертификат SSL (Timeweb/Docker):** если появляется `CERTIFICATE_VERIFY_FAILED`, отключите проверку сертификата:

```bash
export GIGACHAT_VERIFY_SSL_CERTS=false
```

**Vision (картинки в заданиях):** для заданий с графами/таблицами на изображениях скрипт автоматически извлекает URL картинок из `content_html`, скачивает их и передаёт в GigaChat. Рекомендуется модель с поддержкой vision:

```bash
export GIGACHAT_MODEL="GigaChat-Pro"
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

---

## 6. Вложения (файлы)

**Скрипт `scripts/download_all_task_attachments.py`** — скачивает все вложения с kompege.ru в `uploads/task_attachments/<task_id>/<filename>` и обновляет `attached_files` в БД: добавляет локальный путь `path`. Просмотр: используются локальные файлы вместо прокси.

**Следующий шаг (TODO):** научить решальщика открывать Excel, текстовые файлы — чтобы решения опирались на реальные входные данные.
