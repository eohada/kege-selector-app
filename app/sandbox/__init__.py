"""Изолированные среды выполнения (песочницы)."""

from app.sandbox.python_runner import (
    PYTHON_RUNNER,
    normalize_leading_tabs_to_spaces,
    run_python_sandbox,
)

__all__ = [
    'PYTHON_RUNNER',
    'normalize_leading_tabs_to_spaces',
    'run_python_sandbox',
]
