#!/usr/bin/env python3
"""Force the production web service compose command to use eventlet."""

from __future__ import annotations

import argparse
from pathlib import Path


EVENTLET_COMMAND = (
    "gunicorn wsgi:app --bind 0.0.0.0:8000 "
    "--worker-class eventlet --workers 1 --timeout 120"
)


def line_indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def update_compose(path: Path) -> bool:
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    in_web_prod = False
    found_web_prod = False
    found_command = False
    web_prod_indent = 0
    changed = False

    for idx, line in enumerate(lines):
        stripped = line.strip()
        indent = line_indent(line)

        if stripped == "web_prod:":
            in_web_prod = True
            found_web_prod = True
            web_prod_indent = indent
            continue

        if in_web_prod and stripped and not stripped.startswith("#") and indent <= web_prod_indent:
            in_web_prod = False

        if in_web_prod and stripped.startswith("command:"):
            found_command = True
            prefix = line[:indent]
            replacement = f"{prefix}command: {EVENTLET_COMMAND}\n"
            if line != replacement:
                lines[idx] = replacement
                changed = True
            break

    if not found_web_prod:
        raise RuntimeError("Service web_prod was not found in compose file")
    if not found_command:
        raise RuntimeError("Service web_prod has no command line to update")

    if not changed:
        return False

    path.write_text("".join(lines), encoding="utf-8")
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("compose_file", nargs="?", default="docker-compose.yml")
    args = parser.parse_args()

    path = Path(args.compose_file)
    if not path.exists():
        raise SystemExit(f"Compose file not found: {path}")

    changed = update_compose(path)
    print("Updated web_prod command for eventlet" if changed else "web_prod command already uses eventlet")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
