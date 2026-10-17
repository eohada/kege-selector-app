"""Loopback service that runs Code Judge cases in disposable Docker containers."""
from __future__ import annotations

import base64
import difflib
import hmac
import io
import ipaddress
import json
import logging
import math
import os
import tarfile
import threading
import time
import uuid
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from app.ai_lab.config import code_judge_limits, setting


logger = logging.getLogger("boostudy.code_judge_runner")
RUNNER_VERSION = "boostudy-code-judge-runner/0.1"
IMAGE = os.getenv("AI_LAB_CODE_JUDGE_IMAGE", "boostudy-code-judge:2026-10-v2")
MAX_REQUEST_BYTES = 256 * 1024
MAX_RESULT_TEXT_BYTES = 65_536


class RunnerFailure(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _typed(value: Any, depth: int = 0) -> Any:
    if depth > 12:
        raise ValueError("too_deep")
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    if isinstance(value, list) and len(value) <= 2_000:
        return [_typed(item, depth + 1) for item in value]
    if isinstance(value, dict) and value.get("__type__") == "tuple" and isinstance(value.get("items"), list):
        return {"__type__": "tuple", "items": [_typed(item, depth + 1) for item in value["items"]]}
    if isinstance(value, dict) and len(value) <= 2_000 and all(isinstance(key, str) for key in value):
        return {key: _typed(item, depth + 1) for key, item in value.items()}
    raise ValueError("unsupported_type")


def _normalize_newlines(value: str) -> str:
    return value.replace("\r\n", "\n").replace("\r", "\n")


def _equal_program(actual: str, expected: str, comparator: str, tolerance: float) -> bool:
    if comparator == "normalize_newlines":
        return _normalize_newlines(actual) == _normalize_newlines(expected)
    if comparator == "trim_whitespace":
        return _normalize_newlines(actual).strip() == _normalize_newlines(expected).strip()
    if comparator == "ignore_whitespace":
        return "".join(_normalize_newlines(actual).split()) == "".join(_normalize_newlines(expected).split())
    if comparator == "numeric_tolerance":
        try:
            actual_number = float(actual.strip())
            expected_number = float(expected.strip())
        except (TypeError, ValueError, OverflowError):
            return False
        return math.isfinite(actual_number) and math.isfinite(expected_number) and abs(actual_number - expected_number) <= tolerance
    return actual == expected


def _typed_equal(actual: Any, expected: Any) -> bool:
    if isinstance(actual, dict) and actual.get("__type__") == "tuple":
        if not isinstance(expected, dict) or expected.get("__type__") != "tuple":
            return False
        return _typed_equal(actual.get("items"), expected.get("items"))
    if isinstance(actual, bool) != isinstance(expected, bool):
        return False
    if type(actual) is not type(expected):
        return False
    if isinstance(actual, list):
        return len(actual) == len(expected) and all(_typed_equal(a, b) for a, b in zip(actual, expected))
    if isinstance(actual, dict):
        return actual.keys() == expected.keys() and all(_typed_equal(actual[key], expected[key]) for key in actual)
    return actual == expected


def _result_diff(actual: Any, expected: Any) -> str:
    before = json.dumps(expected, ensure_ascii=False, indent=2, sort_keys=True).splitlines()
    after = json.dumps(actual, ensure_ascii=False, indent=2, sort_keys=True).splitlines()
    return "\n".join(list(difflib.unified_diff(before, after, fromfile="Ожидалось", tofile="Получено", lineterm=""))[:80])[:4_000]


class DockerExecutor:
    def __init__(self):
        self.client = None
        self.ready = False
        self.message = "Docker runner ещё не проверен."
        self.security_profile = {key: False for key in (
            "network_disabled", "non_root", "not_privileged", "all_capabilities_dropped",
            "no_new_privileges", "read_only_root", "resource_limits", "tmpfs_only",
            "no_host_mounts", "no_injected_secrets", "default_seccomp",
        )}
        try:
            import docker
            self.client = docker.from_env(timeout=8)
            self.client.ping()
            self._ensure_image()
            self._verify_isolation_profile()
        except Exception as exc:
            self.message = "Docker Engine или профиль изоляции недоступен. Произвольный код заблокирован."
            logger.warning("Code Judge runner unavailable: exception_type=%s", type(exc).__name__)

    def _ensure_image(self):
        from docker.errors import ImageNotFound

        try:
            self.client.images.get(IMAGE)
            return
        except ImageNotFound:
            pass
        entrypoint = Path(__file__).with_name("code_judge_container_entry.py").read_bytes()
        dockerfile = (
            "FROM python:3.12-alpine\n"
            "COPY code_judge_container_entry.py /opt/code_judge_container_entry.py\n"
            "USER 65534:65534\n"
            "ENTRYPOINT [\"python\", \"-I\", \"-S\", \"/opt/code_judge_container_entry.py\"]\n"
        ).encode("utf-8")
        archive = io.BytesIO()
        with tarfile.open(fileobj=archive, mode="w") as bundle:
            for filename, content in (("Dockerfile", dockerfile), ("code_judge_container_entry.py", entrypoint)):
                member = tarfile.TarInfo(filename)
                member.size = len(content)
                member.mode = 0o644
                bundle.addfile(member, io.BytesIO(content))
        archive.seek(0)
        self.client.images.build(fileobj=archive, custom_context=True, tag=IMAGE, rm=True, forcerm=True)

    def _container_options(self, limits: dict, *, entrypoint=None) -> dict:
        cores = int(limits["cpu_cores"])
        mem = f"{int(limits['memory_mb'])}m"
        options = {
            "image": IMAGE,
            "detach": True,
            "network_mode": "none",
            "read_only": True,
            "user": "65534:65534",
            "privileged": False,
            "cap_drop": ["ALL"],
            "security_opt": ["no-new-privileges:true"],
            "mem_limit": mem,
            "memswap_limit": mem,
            "cpu_period": 100_000,
            "cpu_quota": 100_000 * cores,
            "pids_limit": int(limits["pids_limit"]),
            "tmpfs": {"/tmp": "rw,noexec,nosuid,nodev,size=8m"},
            "auto_remove": False,
            "labels": {"boostudy.role": "local-ai-lab-code-judge"},
            "log_config": {"type": "json-file", "config": {"max-size": "128k", "max-file": "1"}},
        }
        if entrypoint is not None:
            options["entrypoint"] = entrypoint
        return options

    def _verify_isolation_profile(self):
        from docker.errors import APIError

        info = self.client.info()
        seccomp_active = any("seccomp" in str(value).lower() for value in info.get("SecurityOptions", []))
        limits = code_judge_limits()
        probe = None
        try:
            probe = self.client.containers.run(
                command=["import os; print(os.geteuid())"],
                **self._container_options(limits, entrypoint=["python", "-I", "-S", "-c"]),
            )
            state = probe.wait(timeout=5)
            probe.reload()
            attrs = probe.attrs
            host = attrs.get("HostConfig", {})
            mounts = attrs.get("Mounts", [])
            config = attrs.get("Config", {})
            image_config = self.client.images.get(IMAGE).attrs.get("Config", {})
            memory_bytes = int(limits["memory_mb"]) * 1024 * 1024
            self.security_profile = {
                "network_disabled": host.get("NetworkMode") == "none"
                and all(not net.get("Gateway") and not net.get("IPAddress") for net in (attrs.get("NetworkSettings", {}).get("Networks") or {}).values()),
                "non_root": config.get("User") == "65534:65534" and probe.logs(stdout=True, stderr=False).decode("utf-8", "replace").strip() == "65534",
                "not_privileged": host.get("Privileged") is not True,
                "all_capabilities_dropped": "ALL" in (host.get("CapDrop") or []) and not (host.get("CapAdd") or []),
                "no_new_privileges": any("no-new-privileges:true" in str(value) for value in (host.get("SecurityOpt") or [])),
                "read_only_root": host.get("ReadonlyRootfs") is True,
                "resource_limits": host.get("Memory") == memory_bytes
                and host.get("MemorySwap") == memory_bytes
                and host.get("CpuPeriod") == 100_000
                and host.get("CpuQuota") == 100_000 * int(limits["cpu_cores"])
                and host.get("PidsLimit") == int(limits["pids_limit"]),
                "tmpfs_only": (host.get("Tmpfs") or {}) == {"/tmp": "rw,noexec,nosuid,nodev,size=8m"},
                "no_host_mounts": not mounts and not host.get("Binds") and not host.get("Mounts") and not host.get("VolumesFrom"),
                "no_injected_secrets": (config.get("Env") or []) == (image_config.get("Env") or []),
                "default_seccomp": seccomp_active,
            }
            if int(state.get("StatusCode", 1)) != 0 or not all(self.security_profile.values()):
                self.message = "Docker не подтвердил все обязательные настройки изоляции. Запуск кода заблокирован."
                return
            self.ready = True
            self.message = "Изолированный Docker runner готов; профиль безопасности проверен."
        except (APIError, Exception) as exc:
            self.message = "Не удалось подтвердить профиль изоляции Docker. Запуск кода заблокирован."
            logger.warning("Code Judge isolation probe failed: exception_type=%s", type(exc).__name__)
        finally:
            if probe is not None:
                try:
                    probe.remove(force=True)
                except Exception:
                    pass

    def run_case(self, request: dict, test_case: dict, limits: dict) -> dict:
        if not self.ready:
            raise RunnerFailure("sandbox_unavailable", self.message)
        from docker.errors import APIError

        case_input = {key: test_case[key] for key in ("id", "name", "stdin", "args") if key in test_case}
        payload = {
            "code": request["code"],
            "mode": request["mode"],
            "function_name": request.get("function_name"),
            "test_case": case_input,
            "limits": limits,
        }
        encoded = base64.urlsafe_b64encode(json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")).decode("ascii")
        if len(encoded) > 110_000:
            return {"status": "internal_error", "error_message": "Вход одного теста слишком велик для изолированного runner."}
        container = None
        timeout = int(limits["test_timeout_seconds"]) + 4
        try:
            options = self._container_options(limits)
            options["command"] = [encoded]
            container = self.client.containers.run(**options)
            try:
                state = container.wait(timeout=timeout)
            except Exception:
                container.kill()
                return {"status": "time_limit_exceeded", "error_message": "Время работы изолированного контейнера превышено."}
            container.reload()
            if container.attrs.get("State", {}).get("OOMKilled"):
                return {"status": "memory_limit_exceeded", "error_message": f"Превышен лимит памяти {limits['memory_mb']} МБ."}
            logs = container.logs(stdout=True, stderr=False, tail=3)
            if int(state.get("StatusCode", 1)) != 0:
                return {"status": "internal_error", "error_message": "Изолированный контейнер завершился с внутренней ошибкой."}
            lines = logs.decode("utf-8", "replace").splitlines()
            raw = json.loads(lines[-1]) if lines else None
            if not isinstance(raw, dict):
                return {"status": "internal_error", "error_message": "Runner вернул пустой результат."}
            return raw
        except APIError as exc:
            logger.warning("Code Judge container failed: exception_type=%s", type(exc).__name__)
            raise RunnerFailure("sandbox_unavailable", "Docker не смог создать безопасный контейнер.") from exc
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            logger.warning("Code Judge container response invalid: exception_type=%s", type(exc).__name__)
            return {"status": "internal_error", "error_message": "Не удалось прочитать структурированный результат контейнера."}
        finally:
            if container is not None:
                try:
                    container.remove(force=True)
                except Exception:
                    pass


def _validate_request(payload: Any, limits: dict) -> dict:
    if not isinstance(payload, dict):
        raise RunnerFailure("invalid_payload", "Ожидался JSON-запрос.")
    code = payload.get("code")
    mode = payload.get("mode")
    cases = payload.get("test_cases")
    function_name = payload.get("function_name")
    if not isinstance(code, str) or not code.strip() or "\x00" in code:
        raise RunnerFailure("invalid_code", "Исходный код пуст или некорректен.")
    if len(code.encode("utf-8")) > limits["max_source_bytes"]:
        raise RunnerFailure("invalid_code", "Исходный код превышает настроенный лимит.")
    if mode not in {"program", "function"}:
        raise RunnerFailure("invalid_mode", "Неизвестный режим проверки.")
    if mode == "function" and (not isinstance(function_name, str) or not function_name.isidentifier()):
        raise RunnerFailure("invalid_function", "Не указано корректное имя функции.")
    if not isinstance(cases, list) or not cases or len(cases) > limits["max_test_cases"]:
        raise RunnerFailure("invalid_tests", "Количество тестов выходит за настроенные границы.")
    checked_cases = []
    for case in cases:
        if not isinstance(case, dict) or case.get("visibility") not in {"public", "hidden"}:
            raise RunnerFailure("invalid_tests", "Структура тестового случая некорректна.")
        if mode == "program":
            if not isinstance(case.get("stdin"), str) or not isinstance(case.get("expected_output"), str):
                raise RunnerFailure("invalid_tests", "Вход и ожидаемый вывод должны быть строками.")
        else:
            if not isinstance(case.get("args"), list):
                raise RunnerFailure("invalid_tests", "Аргументы функции должны быть списком.")
            try:
                case["args"] = [_typed(value) for value in case["args"]]
                case["expected"] = _typed(case.get("expected"))
            except ValueError as exc:
                raise RunnerFailure("invalid_tests", "В тесте есть неподдерживаемый тип данных.") from exc
        checked_cases.append(case)
    comparator = payload.get("comparator", "exact")
    if comparator not in {"exact", "normalize_newlines", "trim_whitespace", "ignore_whitespace", "numeric_tolerance"}:
        raise RunnerFailure("invalid_comparator", "Неизвестная стратегия сравнения.")
    try:
        tolerance = float(payload.get("tolerance", 1e-6))
    except (TypeError, ValueError, OverflowError) as exc:
        raise RunnerFailure("invalid_comparator", "Допуск числового сравнения некорректен.") from exc
    if not math.isfinite(tolerance) or not 0 <= tolerance <= 1:
        raise RunnerFailure("invalid_comparator", "Допуск числового сравнения выходит за допустимые границы.")
    return {"code": code, "mode": mode, "function_name": function_name, "test_cases": checked_cases, "comparator": comparator, "tolerance": tolerance}


class QueuedExecutor:
    def __init__(self):
        self.condition = threading.Condition()
        self.waiting = deque()
        self.active = 0
        self.executor = DockerExecutor()

    def diagnostics(self) -> dict:
        limits = code_judge_limits()
        with self.condition:
            queue = {"active": self.active, "waiting": len(self.waiting), "concurrency_limit": limits["concurrency"], "max_queue_size": limits["max_queue_size"]}
        return {
            "ready": self.executor.ready,
            "message": self.executor.message,
            "runner_version": RUNNER_VERSION,
            "security_profile": self.executor.security_profile,
            "queue": queue,
            "limits": limits,
        }

    def run(self, payload: Any) -> dict:
        limits = code_judge_limits()
        request = _validate_request(payload, limits)
        ticket = object()
        deadline = time.monotonic() + limits["queue_wait_seconds"]
        with self.condition:
            if self.active >= limits["concurrency"] and len(self.waiting) >= limits["max_queue_size"]:
                raise RunnerFailure("queue_full", "Очередь Code Judge заполнена. Дождитесь завершения текущих запусков.")
            self.waiting.append(ticket)
            while self.waiting[0] is not ticket or self.active >= limits["concurrency"]:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self.waiting.remove(ticket)
                    self.condition.notify_all()
                    raise RunnerFailure("queue_timeout", "Истекло время ожидания в очереди Code Judge.")
                self.condition.wait(timeout=min(remaining, 1.0))
            self.waiting.popleft()
            self.active += 1
            self.condition.notify_all()
        try:
            started = time.monotonic()
            results = []
            for case in request["test_cases"]:
                try:
                    raw = self.executor.run_case(request, case, limits)
                except RunnerFailure as exc:
                    results.append({"id": case.get("id"), "name": case.get("name"), "visibility": case.get("visibility"), "status": exc.code, "error_message": str(exc), "execution_time_ms": 0})
                    break
                status = raw.get("status")
                base = {"id": case.get("id"), "name": case.get("name"), "visibility": case.get("visibility"), "execution_time_ms": max(0, int(raw.get("execution_time_ms") or 0))}
                for key in ("stdout", "stderr", "error_message"):
                    value = raw.get(key)
                    if isinstance(value, str):
                        base[key] = value[:MAX_RESULT_TEXT_BYTES]
                if status != "completed":
                    base["status"] = status if status in {"syntax_error", "runtime_error", "time_limit_exceeded", "memory_limit_exceeded", "output_limit_exceeded", "internal_error"} else "internal_error"
                    if "error_message" not in base:
                        base["error_message"] = "Тест завершился без результата."
                else:
                    actual = raw.get("actual")
                    expected = case["expected_output"] if request["mode"] == "program" else case["expected"]
                    matches = _equal_program(actual or "", expected, request["comparator"], request["tolerance"]) if request["mode"] == "program" else _typed_equal(actual, expected)
                    base.update({"status": "passed" if matches else "wrong_answer", "actual": actual, "expected": expected})
                    if not matches:
                        base["diff"] = _result_diff(actual, expected)
                results.append(base)
            elapsed = max(0, round((time.monotonic() - started) * 1000))
            return {"runner_version": RUNNER_VERSION, "summary": {"execution_time_ms": elapsed}, "tests": results}
        finally:
            with self.condition:
                self.active = max(0, self.active - 1)
                self.condition.notify_all()


class RunnerHandler(BaseHTTPRequestHandler):
    server_version = "BooStudyCodeJudgeRunner/1"

    def log_message(self, _format, *_args):
        return

    def _authorized(self) -> bool:
        configured = setting("AI_LAB_CODE_JUDGE_RUNNER_TOKEN", "")
        if not configured:
            return False
        supplied = self.headers.get("Authorization", "")
        expected = "Bearer " + configured
        return hmac.compare_digest(supplied, expected)

    def _reply(self, status: int, payload: dict):
        raw = json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if not self._authorized():
            self._reply(401, {"ok": False, "error": "Требуется локальная авторизация runner."})
            return
        if self.path != "/health":
            self._reply(404, {"ok": False, "error": "Маршрут runner не найден."})
            return
        self._reply(200, {"ok": True, **self.server.queued_executor.diagnostics()})

    def do_POST(self):
        if not self._authorized():
            self._reply(401, {"ok": False, "error": "Требуется локальная авторизация runner."})
            return
        if self.path != "/run":
            self._reply(404, {"ok": False, "error": "Маршрут runner не найден."})
            return
        diagnostics = self.server.queued_executor.diagnostics()
        if not diagnostics["ready"]:
            self._reply(503, {"ok": False, "error": diagnostics["message"]})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > MAX_REQUEST_BYTES:
                self._reply(413, {"ok": False, "error": "Размер запроса превышает лимит runner."})
                return
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            result = self.server.queued_executor.run(payload)
        except RunnerFailure as exc:
            code = 429 if exc.code == "queue_full" else 408 if exc.code == "queue_timeout" else 400
            self._reply(code, {"ok": False, "code": exc.code, "error": str(exc)})
            return
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
            self._reply(400, {"ok": False, "error": "Запрос runner должен содержать корректный JSON."})
            return
        except Exception as exc:
            logger.exception("Code Judge request failed: exception_type=%s", type(exc).__name__)
            self._reply(500, {"ok": False, "error": "Внутренняя ошибка изолированного runner."})
            return
        self._reply(200, {"ok": True, "result": result})


def main():
    if not setting("AI_LAB_CODE_JUDGE_RUNNER_TOKEN", ""):
        raise SystemExit("Задайте AI_LAB_CODE_JUDGE_RUNNER_TOKEN для локального runner и backend.")
    host = setting("AI_LAB_CODE_JUDGE_RUNNER_HOST", "127.0.0.1")
    try:
        if not ipaddress.ip_address(host).is_loopback:
            raise ValueError("runner must bind to loopback")
        port = int(setting("AI_LAB_CODE_JUDGE_RUNNER_PORT", "8778"))
        if not 1 <= port <= 65535:
            raise ValueError("invalid runner port")
    except ValueError:
        raise SystemExit("Code Judge runner должен слушать только loopback и корректный порт.")
    server = ThreadingHTTPServer((host, port), RunnerHandler)
    server.daemon_threads = True
    server.queued_executor = QueuedExecutor()
    logger.info("Code Judge runner listening on %s:%s; ready=%s", host, port, server.queued_executor.executor.ready)
    server.serve_forever()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
