"""Untrusted Python child execution inside one disposable hardened container."""
from __future__ import annotations

import base64
import json
import math
import os
import resource
import signal
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path


RESULT_MARKER = "__BOOSTUDY_CODE_JUDGE_RESULT__"


def _json_value(value, depth=0):
    if depth > 12:
        raise TypeError("Слишком глубокая структура результата")
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    if isinstance(value, tuple):
        return {"__type__": "tuple", "items": [_json_value(item, depth + 1) for item in value]}
    if isinstance(value, list) and len(value) <= 2_000:
        return [_json_value(item, depth + 1) for item in value]
    if isinstance(value, dict) and len(value) <= 2_000 and all(isinstance(key, str) for key in value):
        return {key: _json_value(item, depth + 1) for key, item in value.items()}
    raise TypeError("Функция вернула неподдерживаемый тип данных")


FUNCTION_DRIVER = r'''import json, sys, traceback
source_path, function_name, encoded_args = sys.argv[1:4]
try:
    namespace = {"__name__": "__main__"}
    with open(source_path, "r", encoding="utf-8") as source_file:
        source = source_file.read()
    exec(compile(source, "<решение>", "exec"), namespace, namespace)
    function = namespace.get(function_name)
    if not callable(function):
        raise NameError("Функция " + function_name + " не найдена")
    args = json.loads(encoded_args)
    def decode(value):
        if isinstance(value, dict) and value.get("__type__") == "tuple":
            return tuple(decode(item) for item in value.get("items", []))
        if isinstance(value, list):
            return [decode(item) for item in value]
        if isinstance(value, dict):
            return {key: decode(item) for key, item in value.items()}
        return value
    result = function(*[decode(value) for value in args])
    def encode(value, depth=0):
        if depth > 12:
            raise TypeError("Слишком глубокая структура результата")
        if value is None or isinstance(value, (str, bool, int)):
            return value
        if isinstance(value, float):
            import math
            if math.isfinite(value):
                return value
        if isinstance(value, tuple):
            return {"__type__": "tuple", "items": [encode(item, depth + 1) for item in value]}
        if isinstance(value, list) and len(value) <= 2000:
            return [encode(item, depth + 1) for item in value]
        if isinstance(value, dict) and len(value) <= 2000 and all(isinstance(key, str) for key in value):
            return {key: encode(item, depth + 1) for key, item in value.items()}
        raise TypeError("Функция вернула неподдерживаемый тип данных")
    sys.__stdout__.write("\n" + "__BOOSTUDY_CODE_JUDGE_RESULT__" + json.dumps(encode(result), ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n")
except BaseException as error:
    sys.__stderr__.write(type(error).__name__ + ": " + str(error) + "\n")
    raise
'''


def _set_child_limits(cpu_seconds: int, output_bytes: int) -> None:
    resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds + 1))
    resource.setrlimit(resource.RLIMIT_FSIZE, (output_bytes, output_bytes))
    resource.setrlimit(resource.RLIMIT_NOFILE, (32, 32))
    resource.setrlimit(resource.RLIMIT_NPROC, (24, 24))


def _read_capped(file_obj, limit: int) -> tuple[str, int]:
    file_obj.flush()
    size = os.fstat(file_obj.fileno()).st_size
    file_obj.seek(0)
    data = file_obj.read(limit + 1)
    return data[:limit].decode("utf-8", errors="replace"), size


def _safe_error(stderr: str) -> str:
    lines = [line.strip() for line in stderr.splitlines() if line.strip()]
    if not lines:
        return "Программа завершилась с ошибкой."
    last = lines[-1]
    return last[:500]


def main() -> int:
    try:
        payload = json.loads(base64.urlsafe_b64decode(sys.argv[1].encode("ascii")))
        code = payload["code"]
        mode = payload["mode"]
        limits = payload["limits"]
        if not isinstance(code, str) or mode not in {"program", "function"}:
            raise ValueError("Некорректный запрос")
        timeout = max(1, min(10, int(limits["test_timeout_seconds"])))
        output_limit = max(1_024, min(262_144, int(limits["max_output_bytes"])))
        memory_mb = max(32, min(512, int(limits["memory_mb"])))
        started = time.monotonic()
        case = payload["test_case"]
        try:
            compile(code, "<решение>", "exec")
        except SyntaxError as exc:
            result = {"status": "syntax_error", "error_message": f"Синтаксическая ошибка, строка {exc.lineno or '?'}: {exc.msg}", "execution_time_ms": 0, "stdout": "", "stderr": ""}
            print(json.dumps(result, ensure_ascii=False))
            return 0

        with tempfile.TemporaryDirectory(prefix="judge-", dir="/tmp") as workdir:
            os.chmod(workdir, 0o700)
            source_path = str(Path(workdir) / "solution.py")
            Path(source_path).write_text(code, encoding="utf-8")
            stdout_file = tempfile.TemporaryFile(dir=workdir)
            stderr_file = tempfile.TemporaryFile(dir=workdir)
            if mode == "program":
                command = [sys.executable, "-I", "-S", source_path]
                child_input = case.get("stdin", "")
            else:
                encoded_args = json.dumps(case.get("args", []), ensure_ascii=False, allow_nan=False, separators=(",", ":"))
                command = [sys.executable, "-I", "-S", "-c", FUNCTION_DRIVER, source_path, payload["function_name"], encoded_args]
                child_input = ""
            try:
                try:
                    completed = subprocess.run(
                        command,
                        input=child_input,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        stdout=stdout_file,
                        stderr=stderr_file,
                        cwd=workdir,
                        env={"PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1", "HOME": workdir},
                        timeout=timeout,
                        check=False,
                        preexec_fn=lambda: _set_child_limits(timeout, output_limit),
                    )
                except subprocess.TimeoutExpired:
                    result = {"status": "time_limit_exceeded", "error_message": f"Время выполнения превышено ({timeout} с).", "execution_time_ms": round((time.monotonic() - started) * 1000), "stdout": "", "stderr": ""}
                    print(json.dumps(result, ensure_ascii=False))
                    return 0
                stdout, stdout_size = _read_capped(stdout_file, output_limit)
                stderr, stderr_size = _read_capped(stderr_file, output_limit)
                if stdout_size + stderr_size > output_limit or completed.returncode == -signal.SIGXFSZ:
                    status = "output_limit_exceeded"
                    error_message = f"Общий вывод превысил {output_limit} байт."
                    actual = None
                    # Keep the structured Docker log result small even when the
                    # user process filled its entire output allowance.
                    stdout = stdout[:2_048]
                    stderr = stderr[:2_048]
                elif completed.returncode != 0:
                    status = "runtime_error"
                    error_message = _safe_error(stderr)
                    actual = None
                elif mode == "program":
                    status = "completed"
                    error_message = ""
                    actual = stdout
                else:
                    marker_lines = [line[len("__BOOSTUDY_CODE_JUDGE_RESULT__"):] for line in stdout.splitlines() if line.startswith("__BOOSTUDY_CODE_JUDGE_RESULT__")]
                    if not marker_lines:
                        status = "runtime_error"
                        error_message = _safe_error(stderr)
                        actual = None
                    else:
                        try:
                            actual = json.loads(marker_lines[-1])
                            status = "completed"
                            error_message = ""
                            stdout = "\n".join(line for line in stdout.splitlines() if not line.startswith("__BOOSTUDY_CODE_JUDGE_RESULT__"))
                        except (json.JSONDecodeError, ValueError):
                            status = "runtime_error"
                            error_message = "Функция вернула результат, который нельзя безопасно сериализовать."
                            actual = None
                result = {
                    "status": status,
                    "actual": actual,
                    "stdout": stdout,
                    "stderr": stderr,
                    "error_message": error_message,
                    "execution_time_ms": round((time.monotonic() - started) * 1000),
                    "memory_limit_mb": memory_mb,
                }
            finally:
                stdout_file.close()
                stderr_file.close()
        print(json.dumps(result, ensure_ascii=False, allow_nan=False, separators=(",", ":")))
        return 0
    except BaseException as exc:
        print(json.dumps({"status": "internal_error", "error_message": type(exc).__name__, "execution_time_ms": 0, "stdout": "", "stderr": ""}, ensure_ascii=False))
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
