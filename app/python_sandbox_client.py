"""HTTP client for the isolated Python autograder service."""
from __future__ import annotations

import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class PythonSandboxUnavailable(RuntimeError):
    """Raised when isolated execution is not available or returned no grade."""


def grade_python_code(source: str, test_cases: list[dict]) -> tuple[bool, dict]:
    if not isinstance(source, str) or not source.strip():
        return False, {"passed": 0, "total": len(test_cases or [])}
    if len(source.encode("utf-8")) > 24_000:
        return False, {"passed": 0, "total": len(test_cases or [])}
    if not isinstance(test_cases, list) or not test_cases or len(test_cases) > 10:
        raise PythonSandboxUnavailable("Для задания не настроены закрытые автотесты")

    endpoint = os.getenv("PYTHON_TASK_SANDBOX_URL", "").strip().rstrip("/")
    if not endpoint:
        raise PythonSandboxUnavailable("Изолированный запуск Python пока не настроен")
    payload = json.dumps({"code": source, "test_cases": test_cases}, ensure_ascii=False).encode("utf-8")
    if len(payload) > 88 * 1024:
        raise PythonSandboxUnavailable("Набор тестов превышает допустимый размер")
    request = Request(
        endpoint + "/grade",
        data=payload,
        headers={"Content-Type": "application/json", "Content-Length": str(len(payload))},
        method="POST",
    )
    try:
        with urlopen(request, timeout=18) as response:
            result = json.loads(response.read(4096).decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
        raise PythonSandboxUnavailable("Сервис изолированной проверки кода недоступен") from exc
    if not isinstance(result, dict) or result.get("success") is not True:
        raise PythonSandboxUnavailable("Сервис изолированной проверки кода вернул ошибку")
    details = {
        "passed": max(0, int(result.get("passed", 0))),
        "total": max(0, int(result.get("total", len(test_cases)))),
    }
    return bool(result.get("correct")), details
