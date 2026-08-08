#!/usr/bin/env python3
"""Fast HTTP smoke check for BooStudy release readiness.

This is not a browser replacement. It catches the big failures quickly:
login regressions, 500 responses, broken role redirects, and rendered error pages.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from urllib.parse import urljoin

import requests


ERROR_TEXT_RE = re.compile(
    r'(страница не загрузилась|ошибка!!|internal server error|traceback|werkzeug debugger)',
    re.IGNORECASE,
)
CSRF_RE = re.compile(r'name="csrf_token"\s+type="hidden"\s+value="([^"]+)"|value="([^"]+)"\s+type="hidden"\s+name="csrf_token"')


@dataclass(frozen=True)
class Account:
    label: str
    username: str
    urls: tuple[str, ...]


ACCOUNTS = (
    Account('student', 'qa_pool_student_1', ('/dashboard', '/submissions', '/trainer/v2')),
    Account('tutor', 'qa_pool_tutor_1', ('/dashboard', '/assignments', '/submissions', '/trainer/v2')),
    Account('parent', 'qa_pool_parent_1', ('/parent/dashboard',)),
    Account('admin', 'qa_pool_admin_1', ('/dashboard', '/qa/pool')),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Run release HTTP smoke checks.')
    parser.add_argument('--base-url', default='http://127.0.0.1:5000', help='Base URL, default: http://127.0.0.1:5000')
    parser.add_argument('--password', default='123456', help='QA account password, default: 123456')
    return parser.parse_args()


def extract_csrf(html: str) -> str:
    match = CSRF_RE.search(html)
    if not match:
        raise RuntimeError('csrf_token not found on login page')
    return match.group(1) or match.group(2)


def check_response(label: str, url: str, response: requests.Response) -> list[str]:
    errors: list[str] = []
    if response.status_code >= 500:
        errors.append(f'{label}: {url} returned HTTP {response.status_code}')
    if ERROR_TEXT_RE.search(response.text or ''):
        errors.append(f'{label}: {url} rendered a known error marker')
    return errors


def login(session: requests.Session, base_url: str, username: str, password: str) -> None:
    login_url = urljoin(base_url, '/login')
    page = session.get(login_url, timeout=15)
    page.raise_for_status()
    csrf = extract_csrf(page.text)
    response = session.post(
        login_url,
        data={'username': username, 'password': password, 'csrf_token': csrf, 'submit': 'Войти'},
        allow_redirects=True,
        timeout=20,
    )
    response.raise_for_status()
    if '/login' in response.url:
        raise RuntimeError(f'login failed for {username}: still on /login')


def main() -> int:
    args = parse_args()
    base_url = args.base_url.rstrip('/') + '/'
    failures: list[str] = []

    for account in ACCOUNTS:
        session = requests.Session()
        try:
            login(session, base_url, account.username, args.password)
        except Exception as exc:
            failures.append(f'{account.label}: login failed for {account.username}: {exc}')
            continue

        for path in account.urls:
            full_url = urljoin(base_url, path.lstrip('/'))
            try:
                response = session.get(full_url, timeout=20)
            except Exception as exc:
                failures.append(f'{account.label}: {path} request failed: {exc}')
                continue
            failures.extend(check_response(account.label, path, response))
            if not failures:
                print(f'OK {account.label} {path} -> {response.status_code}')

    if failures:
        print('\nRelease HTTP smoke failed:', file=sys.stderr)
        for failure in failures:
            print(f'- {failure}', file=sys.stderr)
        return 1

    print('\nRelease HTTP smoke passed.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
