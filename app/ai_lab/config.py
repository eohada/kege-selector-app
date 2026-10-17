"""Local-only configuration for the isolated AI Lab."""
from __future__ import annotations

import logging
import os
import shlex
from functools import lru_cache
from pathlib import Path

from flask import current_app, has_app_context

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DOTENV_PATH = PROJECT_ROOT / ".env"

AI_LAB_DEFAULTS: dict[str, int] = {
    "AI_LAB_RUNS_PER_ADMIN_PER_HOUR": 120,
    "AI_LAB_RUNS_PER_HOUR": 300,
    "AI_LAB_MAX_INPUT_BYTES": 128 * 1024,
    "AI_LAB_GIGACHAT_CONCURRENCY": 1,
    "AI_LAB_MAX_QUEUE_SIZE": 20,
    "AI_LAB_MAX_COMPLETION_TOKENS": 1600,
    "AI_LAB_QUEUE_WAIT_SECONDS": 600,
    "AI_LAB_PROVIDER_READ_TIMEOUT_SECONDS": 120,
    "AI_LAB_CODE_JUDGE_MAX_SOURCE_BYTES": 65_536,
    "AI_LAB_CODE_JUDGE_MAX_TEST_SET_BYTES": 131_072,
    "AI_LAB_CODE_JUDGE_MAX_TEST_CASES": 30,
    "AI_LAB_CODE_JUDGE_TEST_TIMEOUT_SECONDS": 2,
    "AI_LAB_CODE_JUDGE_MEMORY_MB": 128,
    "AI_LAB_CODE_JUDGE_CPU_CORES": 1,
    "AI_LAB_CODE_JUDGE_MAX_OUTPUT_BYTES": 65_536,
    "AI_LAB_CODE_JUDGE_PIDS_LIMIT": 32,
    "AI_LAB_CODE_JUDGE_CONCURRENCY": 1,
    "AI_LAB_CODE_JUDGE_MAX_QUEUE_SIZE": 20,
    "AI_LAB_CODE_JUDGE_QUEUE_WAIT_SECONDS": 120,
}

_ALLOWED_DOTENV_KEYS = {
    "AI_LAB_ENABLED",
    "ENVIRONMENT",
    "GIGACHAT_AUTH_KEY",
    "GIGACHAT_SCOPE",
    "GIGACHAT_MODEL",
    "GIGACHAT_CA_BUNDLE",
    "GIGACHAT_CA_BUNDLE_FILE",
    "AI_LAB_CODE_JUDGE_RUNNER_URL",
    "AI_LAB_CODE_JUDGE_RUNNER_HOST",
    "AI_LAB_CODE_JUDGE_RUNNER_PORT",
    "AI_LAB_CODE_JUDGE_RUNNER_TOKEN",
    "AI_LAB_GIGACHAT_INPUT_PRICE_PER_MILLION",
    "AI_LAB_GIGACHAT_OUTPUT_PRICE_PER_MILLION",
    *AI_LAB_DEFAULTS,
}


@lru_cache(maxsize=4)
def _read_dotenv(path: str, modified_ns: int) -> dict[str, str]:
    del modified_ns  # The mtime is part of the cache key so edits take effect immediately.
    values: dict[str, str] = {}
    dotenv_path = Path(path)
    if not dotenv_path.is_file():
        return values

    for line in dotenv_path.read_text(encoding="utf-8-sig").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("export "):
            stripped = stripped[7:].lstrip()
        key, separator, raw_value = stripped.partition("=")
        key = key.strip()
        if not separator or key not in _ALLOWED_DOTENV_KEYS:
            continue
        raw_value = raw_value.strip()
        if raw_value[:1] in {"'", '"'}:
            try:
                parts = shlex.split(raw_value, comments=True, posix=True)
                value = parts[0] if parts else ""
            except ValueError as exc:
                raise ValueError(f"Некорректное значение {key} в локальном .env") from exc
        else:
            value = raw_value.split("#", 1)[0].strip()
        values[key] = value
    return values


def local_dotenv_values() -> dict[str, str]:
    try:
        modified_ns = DOTENV_PATH.stat().st_mtime_ns
    except FileNotFoundError:
        return {}
    return _read_dotenv(str(DOTENV_PATH), modified_ns)


def setting_with_source(name: str, default: str = "") -> tuple[str, str]:
    if has_app_context():
        configured = current_app.config.get(name)
        if configured is not None:
            return str(configured).strip(), "настройки приложения"

    environment_value = os.environ.get(name)
    if environment_value is not None and environment_value.strip():
        return environment_value.strip(), "окружение backend"

    dotenv_value = local_dotenv_values().get(name)
    if dotenv_value is not None:
        return dotenv_value.strip(), "локальный .env"
    return default, "значение по умолчанию"


def setting(name: str, default: str = "") -> str:
    return setting_with_source(name, default)[0]


def integer_setting(name: str, default: int, *, minimum: int = 1, maximum: int = 1_000_000) -> int:
    raw, source = setting_with_source(name, str(default))
    try:
        value = int(raw)
    except (TypeError, ValueError, OverflowError):
        logger.warning("AI Lab setting %s is not an integer; using default=%s", name, default)
        value = default
    if value < minimum or value > maximum:
        logger.warning(
            "AI Lab setting %s is outside the supported range; using default=%s",
            name,
            default,
        )
        value = default
    return value


def ai_lab_limits() -> dict[str, int]:
    return {
        "runs_per_admin_per_hour": integer_setting(
            "AI_LAB_RUNS_PER_ADMIN_PER_HOUR", AI_LAB_DEFAULTS["AI_LAB_RUNS_PER_ADMIN_PER_HOUR"], maximum=100_000
        ),
        "runs_per_lab_per_hour": integer_setting(
            "AI_LAB_RUNS_PER_HOUR", AI_LAB_DEFAULTS["AI_LAB_RUNS_PER_HOUR"], maximum=100_000
        ),
        "max_input_bytes": integer_setting(
            "AI_LAB_MAX_INPUT_BYTES", AI_LAB_DEFAULTS["AI_LAB_MAX_INPUT_BYTES"], maximum=10 * 1024 * 1024
        ),
        "gigachat_concurrency": integer_setting(
            "AI_LAB_GIGACHAT_CONCURRENCY", AI_LAB_DEFAULTS["AI_LAB_GIGACHAT_CONCURRENCY"], maximum=8
        ),
        "max_queue_size": integer_setting(
            "AI_LAB_MAX_QUEUE_SIZE", AI_LAB_DEFAULTS["AI_LAB_MAX_QUEUE_SIZE"], minimum=0, maximum=1_000
        ),
        "max_completion_tokens": integer_setting(
            "AI_LAB_MAX_COMPLETION_TOKENS", AI_LAB_DEFAULTS["AI_LAB_MAX_COMPLETION_TOKENS"], maximum=4_096
        ),
        "queue_wait_seconds": integer_setting(
            "AI_LAB_QUEUE_WAIT_SECONDS", AI_LAB_DEFAULTS["AI_LAB_QUEUE_WAIT_SECONDS"], maximum=3_600
        ),
        "provider_read_timeout_seconds": integer_setting(
            "AI_LAB_PROVIDER_READ_TIMEOUT_SECONDS",
            AI_LAB_DEFAULTS["AI_LAB_PROVIDER_READ_TIMEOUT_SECONDS"],
            maximum=300,
        ),
    }


def code_judge_limits() -> dict[str, int]:
    limits = {
        "max_source_bytes": ("AI_LAB_CODE_JUDGE_MAX_SOURCE_BYTES", 65_536, 4_096, 262_144),
        "max_test_set_bytes": ("AI_LAB_CODE_JUDGE_MAX_TEST_SET_BYTES", 131_072, 4_096, 1_048_576),
        "max_test_cases": ("AI_LAB_CODE_JUDGE_MAX_TEST_CASES", 30, 1, 200),
        "test_timeout_seconds": ("AI_LAB_CODE_JUDGE_TEST_TIMEOUT_SECONDS", 2, 1, 10),
        "memory_mb": ("AI_LAB_CODE_JUDGE_MEMORY_MB", 128, 32, 512),
        "cpu_cores": ("AI_LAB_CODE_JUDGE_CPU_CORES", 1, 1, 2),
        "max_output_bytes": ("AI_LAB_CODE_JUDGE_MAX_OUTPUT_BYTES", 65_536, 1_024, 262_144),
        "pids_limit": ("AI_LAB_CODE_JUDGE_PIDS_LIMIT", 32, 4, 128),
        "concurrency": ("AI_LAB_CODE_JUDGE_CONCURRENCY", 1, 1, 4),
        "max_queue_size": ("AI_LAB_CODE_JUDGE_MAX_QUEUE_SIZE", 20, 0, 200),
        "queue_wait_seconds": ("AI_LAB_CODE_JUDGE_QUEUE_WAIT_SECONDS", 120, 1, 900),
    }
    return {
        key: integer_setting(name, default, minimum=minimum, maximum=maximum)
        for key, (name, default, minimum, maximum) in limits.items()
    }
