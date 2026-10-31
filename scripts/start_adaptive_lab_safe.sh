#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
PYTHON="$ROOT/venv/bin/python"
DB_INPUT="${1:-}"
PORT="${2:-5185}"

if [[ -z "$DB_INPUT" ]]; then
  printf 'Usage: %s /absolute/path/BooStudy_Adaptive_Lab_Synthetic_Linux_*/adaptive_learning_synthetic.sqlite [port]\n' "$0" >&2
  exit 2
fi
if [[ ! -x "$PYTHON" ]]; then
  printf 'Не найден Python окружения проекта: %s\n' "$PYTHON" >&2
  exit 2
fi
if [[ -L "$DB_INPUT" ]]; then
  printf 'Запуск запрещён: SQLite не может быть symlink.\n' >&2
  exit 2
fi

DB_PATH="$(realpath -e -- "$DB_INPUT")"
if [[ "$(basename -- "$DB_PATH")" != 'adaptive_learning_synthetic.sqlite' ]]; then
  printf 'Запуск разрешён только для adaptive_learning_synthetic.sqlite.\n' >&2
  exit 2
fi

cd -- "$ROOT"
exec "$PYTHON" "$ROOT/scripts/ai_lab/adaptive_lab_linux.py" serve --db-path "$DB_PATH" --port "$PORT"
