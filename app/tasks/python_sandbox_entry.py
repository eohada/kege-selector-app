"""Entrypoint inside the short-lived, networkless code-execution container."""
from __future__ import annotations

import base64
import json
import os
import resource
import subprocess
import sys
import tempfile


def _drop_privileges():
    os.setgroups([])
    os.setgid(65534)
    os.setuid(65534)
    resource.setrlimit(resource.RLIMIT_CPU, (1, 1))
    resource.setrlimit(resource.RLIMIT_FSIZE, (1_048_576, 1_048_576))
    resource.setrlimit(resource.RLIMIT_NOFILE, (32, 32))
    resource.setrlimit(resource.RLIMIT_NPROC, (8, 8))


def main():
    try:
        payload = json.loads(base64.urlsafe_b64decode(sys.argv[1].encode("ascii")))
        source = payload["code"]
        test_cases = payload["test_cases"]
        if not isinstance(source, str) or not isinstance(test_cases, list) or not 1 <= len(test_cases) <= 10:
            raise ValueError("invalid payload")
        passed = 0
        for case in test_cases:
            if not isinstance(case, dict):
                continue
            input_text = str(case.get("input", ""))
            expected = str(case.get("output", ""))
            if len(input_text) > 8192 or len(expected) > 8192:
                continue
            try:
                with tempfile.TemporaryDirectory(dir="/tmp") as workdir:
                    os.chmod(workdir, 0o777)
                    result = subprocess.run(
                        [sys.executable, "-I", "-S", "-c", source],
                        input=input_text,
                        text=True,
                        capture_output=True,
                        cwd=workdir,
                        env={"PYTHONIOENCODING": "utf-8", "HOME": workdir},
                        timeout=1.25,
                        check=False,
                        preexec_fn=_drop_privileges,
                    )
                actual = result.stdout.rstrip("\r\n")
                if result.returncode == 0 and len(result.stdout) <= 65_536 and actual == expected:
                    passed += 1
            except (subprocess.TimeoutExpired, OSError, ValueError):
                continue
        print(json.dumps({"passed": passed, "total": len(test_cases), "correct": passed == len(test_cases)}))
    except BaseException:
        # Only the coarse grade leaves this container; never expose source or hidden tests.
        print(json.dumps({"passed": 0, "total": 0, "correct": False}))


if __name__ == "__main__":
    main()
