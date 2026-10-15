"""Small internal controller that runs Python submissions in disposable containers."""
from __future__ import annotations

import base64
import io
import json
import os
import tarfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import docker
from docker.errors import APIError, ImageNotFound


IMAGE = os.getenv("PYTHON_TASK_SANDBOX_IMAGE", "boostudy-python-task-sandbox:2026-10-v1")
MAX_BODY = 88 * 1024
SLOTS = threading.BoundedSemaphore(4)
DOCKER = None


def _build_sandbox_image(client):
    try:
        client.images.get(IMAGE)
        return
    except ImageNotFound:
        pass
    entrypoint = Path(__file__).with_name("python_sandbox_entry.py").read_bytes()
    dockerfile = (
        "FROM python:3.12-alpine\n"
        "COPY python_sandbox_entry.py /opt/python_sandbox_entry.py\n"
        "ENTRYPOINT [\"python\", \"-I\", \"-S\", \"/opt/python_sandbox_entry.py\"]\n"
    ).encode("utf-8")
    archive = io.BytesIO()
    with tarfile.open(fileobj=archive, mode="w") as bundle:
        for filename, content in (("Dockerfile", dockerfile), ("python_sandbox_entry.py", entrypoint)):
            member = tarfile.TarInfo(filename)
            member.size = len(content)
            member.mode = 0o644
            bundle.addfile(member, io.BytesIO(content))
    archive.seek(0)
    client.images.build(fileobj=archive, custom_context=True, tag=IMAGE, rm=True, forcerm=True)


def _grade(source, cases):
    payload = base64.urlsafe_b64encode(json.dumps({"code": source, "test_cases": cases}, ensure_ascii=False).encode("utf-8")).decode("ascii")
    if len(payload) > 120_000:
        raise ValueError("test payload exceeds argument limit")
    container = DOCKER.containers.run(
        IMAGE,
        command=[payload],
        detach=True,
        network_disabled=True,
        read_only=True,
        user="0:0",
        cap_drop=["ALL"],
        cap_add=["SETUID", "SETGID"],
        security_opt=["no-new-privileges:true"],
        mem_limit="160m",
        memswap_limit="160m",
        cpu_quota=50000,
        cpu_period=100000,
        pids_limit=16,
        tmpfs={"/tmp": "rw,noexec,nosuid,size=16m"},
        auto_remove=False,
        labels={"boostudy.role": "python-task-sandbox"},
    )
    try:
        exit_state = container.wait(timeout=16)
        if int(exit_state.get("StatusCode", 1)) != 0:
            return {"success": True, "passed": 0, "total": len(cases), "correct": False}
        logs = container.logs(stdout=True, stderr=False, tail=1)
        try:
            result = json.loads(logs.decode("utf-8").strip().splitlines()[-1])
        except (UnicodeDecodeError, IndexError, json.JSONDecodeError):
            return {"success": True, "passed": 0, "total": len(cases), "correct": False}
        passed = max(0, min(len(cases), int(result.get("passed", 0))))
        return {"success": True, "passed": passed, "total": len(cases), "correct": passed == len(cases)}
    finally:
        try:
            container.remove(force=True)
        except APIError:
            pass


class Handler(BaseHTTPRequestHandler):
    server_version = "BooStudyPythonSandbox/1"

    def log_message(self, _format, *_args):
        # Do not log student source, hidden tests, or program output.
        return

    def _reply(self, status, payload):
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path != "/health":
            self._reply(404, {"success": False})
            return
        self._reply(200, {"success": True, "ready": DOCKER is not None})

    def do_POST(self):
        if self.path != "/grade":
            self._reply(404, {"success": False})
            return
        if not SLOTS.acquire(blocking=False):
            self._reply(429, {"success": False})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > MAX_BODY:
                self._reply(413, {"success": False})
                return
            try:
                data = json.loads(self.rfile.read(length))
                source = data.get("code")
                raw_cases = data.get("test_cases")
                if not isinstance(source, str) or not source.strip() or len(source.encode("utf-8")) > 24_000 or "\x00" in source:
                    raise ValueError("invalid code")
                if not isinstance(raw_cases, list) or not 1 <= len(raw_cases) <= 10:
                    raise ValueError("invalid tests")
                cases = []
                for case in raw_cases:
                    if not isinstance(case, dict):
                        raise ValueError("invalid test case")
                    input_text = str(case.get("input", ""))
                    expected = str(case.get("output", ""))
                    if len(input_text.encode("utf-8")) > 8192 or len(expected.encode("utf-8")) > 8192:
                        raise ValueError("test case too large")
                    cases.append({"input": input_text, "output": expected})
            except (ValueError, TypeError, AttributeError, json.JSONDecodeError):
                self._reply(400, {"success": False})
                return
            try:
                self._reply(200, _grade(source, cases))
            except Exception:
                # The public response deliberately contains no host/container diagnostics.
                self._reply(503, {"success": False})
        finally:
            SLOTS.release()


def main():
    global DOCKER
    DOCKER = docker.from_env(timeout=8)
    DOCKER.ping()
    _build_sandbox_image(DOCKER)
    host = os.getenv("PYTHON_TASK_SANDBOX_HOST", "0.0.0.0")
    port = int(os.getenv("PYTHON_TASK_SANDBOX_PORT", "8777"))
    ThreadingHTTPServer((host, port), Handler).serve_forever()


if __name__ == "__main__":
    main()
