"""Loopback-only client for the separate Code Judge Docker runner."""
from __future__ import annotations

import hmac
import json
import urllib.error
import urllib.parse
import urllib.request

from app.ai_lab.code_judge import RunnerUnavailable
from app.ai_lab.config import setting


_REQUIRED_PROFILE = {
    "network_disabled", "non_root", "not_privileged", "all_capabilities_dropped",
    "no_new_privileges", "read_only_root", "resource_limits", "tmpfs_only",
    "no_host_mounts", "no_injected_secrets", "default_seccomp",
}


def _base_url() -> str:
    raw = setting("AI_LAB_CODE_JUDGE_RUNNER_URL", "http://127.0.0.1:8778").strip().rstrip("/")
    try:
        parsed = urllib.parse.urlsplit(raw)
        host = (parsed.hostname or "").lower()
        port = parsed.port
    except ValueError as exc:
        raise RunnerUnavailable("URL локального runner настроен некорректно.") from exc
    if (
        parsed.scheme != "http"
        or host not in {"127.0.0.1", "localhost", "::1"}
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
        or (port is not None and not 1 <= port <= 65535)
    ):
        raise RunnerUnavailable("Code Judge принимает запросы только к локальному loopback runner.")
    return raw


def _request(path: str, *, body: dict | None = None, timeout: float = 3.0) -> dict:
    url = _base_url() + path
    data = None if body is None else json.dumps(body, ensure_ascii=False, allow_nan=False).encode("utf-8")
    headers = {"Accept": "application/json", "Cache-Control": "no-store"}
    if data is not None:
        headers["Content-Type"] = "application/json; charset=utf-8"
    token = setting("AI_LAB_CODE_JUDGE_RUNNER_TOKEN", "")
    if not token:
        raise RunnerUnavailable("Не задан локальный токен авторизации Code Judge runner.")
    headers["Authorization"] = "Bearer " + token
    request = urllib.request.Request(url, data=data, headers=headers, method="POST" if data is not None else "GET")
    try:
        # The URL has already been restricted to loopback. Bypass environment
        # HTTP proxies for this local-only hop; proxy settings may omit localhost
        # from their bypass list and reject the request before it reaches runner.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(request, timeout=timeout) as response:
            raw = response.read(2 * 1024 * 1024 + 1)
            if len(raw) > 2 * 1024 * 1024:
                raise RunnerUnavailable("Runner вернул слишком большой ответ.")
            result = json.loads(raw.decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            details = json.loads(exc.read(16_384).decode("utf-8"))
            message = str(details.get("error") or "Изолированный runner отклонил запрос.") if isinstance(details, dict) else "Изолированный runner отклонил запрос."
        except (UnicodeDecodeError, json.JSONDecodeError):
            message = "Изолированный runner отклонил запрос."
        raise RunnerUnavailable(message) from exc
    except (urllib.error.URLError, TimeoutError, OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RunnerUnavailable("Локальный изолированный runner не отвечает. Код не запускался.") from exc
    if not isinstance(result, dict):
        raise RunnerUnavailable("Runner вернул некорректный ответ.")
    return result


def runner_diagnostics() -> dict:
    try:
        result = _request("/health", timeout=2.0)
    except RunnerUnavailable as exc:
        return {
            "ready": False,
            "secure_profile_verified": False,
            "message": str(exc),
            "queue": {"active": 0, "waiting": 0},
        }
    profile = result.get("security_profile") if isinstance(result.get("security_profile"), dict) else {}
    verified = _REQUIRED_PROFILE.issubset({key for key, value in profile.items() if value is True})
    ready = result.get("ready") is True and verified
    return {
        "ready": ready,
        "secure_profile_verified": verified,
        "message": str(result.get("message") or ("Изолированный runner готов." if ready else "Runner не подтвердил полный профиль изоляции.")),
        "runner_version": result.get("runner_version"),
        "queue": result.get("queue") if isinstance(result.get("queue"), dict) else {"active": 0, "waiting": 0},
        "limits": result.get("limits") if isinstance(result.get("limits"), dict) else {},
        "security_profile": profile,
    }


def run_isolated(payload: dict) -> dict:
    diagnostics = runner_diagnostics()
    if not diagnostics["ready"] or diagnostics["secure_profile_verified"] is not True:
        raise RunnerUnavailable(diagnostics["message"])
    result = _request("/run", body=payload, timeout=900.0)
    if result.get("ok") is not True or not isinstance(result.get("result"), dict):
        raise RunnerUnavailable(str(result.get("error") or "Runner не завершил проверку."))
    return result["result"]
