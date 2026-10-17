"""Минимальный серверный HTTP-адаптер GigaChat API."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
import uuid
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests
from flask import current_app, has_app_context

from app.ai_lab.config import ai_lab_limits, setting, setting_with_source
from app.ai_lab.schemas import RESPONSE_SCHEMA

logger = logging.getLogger(__name__)

API_BASE_URL = "https://api.giga.chat"
OAUTH_URL = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
CONNECT_TIMEOUT_SECONDS = 8
MAX_COMPLETION_TOKENS = 1600
_TOKEN_LOCK = threading.Lock()
_TOKEN_CACHE: dict[str, Any] = {"fingerprint": None, "value": None, "expires_at": 0.0}


class ProviderError(RuntimeError):
    def __init__(self, code: str, message: str, status_code: int | None = None):
        super().__init__(message)
        self.code = code
        self.status_code = status_code


@dataclass(frozen=True)
class CompletionResult:
    content: str
    model: str
    input_tokens: int | None
    output_tokens: int | None
    prompt_tokens: int | None = None
    precached_prompt_tokens: int | None = None
    total_tokens: int | None = None
    payload_id: str | None = None
    payload_sha256: str | None = None
    request_payload: dict[str, Any] | None = None
    generation_parameters: dict[str, Any] | None = None


def _setting(name: str, default: str = "") -> str:
    return setting(name, default)


def _truthy(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def is_local_ai_lab_enabled() -> bool:
    environment = (_setting("ENVIRONMENT", "local") or "local").lower()
    enabled = _truthy(_setting("AI_LAB_ENABLED", "false"))
    return enabled and environment in {"local", "development", "dev"}


def provider_settings() -> dict[str, str | bool]:
    ca_bundle, ca_source = setting_with_source("GIGACHAT_CA_BUNDLE_FILE")
    if not ca_bundle:
        ca_bundle, ca_source = setting_with_source("GIGACHAT_CA_BUNDLE")
    ca_bundle = os.path.expanduser(os.path.expandvars(ca_bundle))
    if ca_bundle and not os.path.isabs(ca_bundle):
        ca_bundle = str((Path(__file__).resolve().parents[2] / ca_bundle).resolve())
    return {
        "enabled": is_local_ai_lab_enabled(),
        "configured": bool(_setting("GIGACHAT_AUTH_KEY")),
        "auth_key": _setting("GIGACHAT_AUTH_KEY"),
        "scope": _setting("GIGACHAT_SCOPE", "GIGACHAT_API_PERS") or "GIGACHAT_API_PERS",
        "default_model": _setting("GIGACHAT_MODEL"),
        "ca_bundle": ca_bundle,
        "ca_bundle_source": ca_source,
        "ca_bundle_file_exists": bool(ca_bundle and os.path.isfile(ca_bundle)),
    }


def _ssl_verify() -> bool | str:
    path = str(provider_settings()["ca_bundle"])
    if not path:
        return True
    if not os.path.isfile(path):
        raise ProviderError(
            "tls_bundle_not_found",
            "Файл доверенного сертификата Минцифры не найден. Проверьте GIGACHAT_CA_BUNDLE_FILE или GIGACHAT_CA_BUNDLE.",
        )
    return path


def _config_fingerprint(settings: dict[str, str | bool]) -> str:
    source = "\0".join(
        [str(settings["auth_key"]), str(settings["scope"]), str(settings["ca_bundle"])]
    )
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def _raise_for_status(response: requests.Response) -> None:
    status = response.status_code
    if status < 400:
        return
    response_hint = response.text[:2_000].casefold()
    if status == 402 or (
        status == 429
        and any(marker in response_hint for marker in ("quota", "квот", "balance", "лимит токен", "insufficient"))
    ):
        raise ProviderError(
            "provider_quota_exhausted",
            "Исчерпана квота или баланс GigaChat. Проверьте лимит проекта и повторите после его восстановления.",
            status,
        )
    if status in {401, 403}:
        raise ProviderError(
            "authorization_failed",
            "GigaChat отклонил ключ или этот проект не имеет доступа к API.",
            status,
        )
    if status in {402, 429}:
        raise ProviderError(
            "provider_rate_limited",
            "GigaChat временно ограничил частоту запросов. Подождите перед следующим запуском.",
            status,
        )
    if status == 400:
        raise ProviderError(
            "provider_bad_request",
            "GigaChat отклонил запрос. Проверьте выбранную модель и формат данных.",
            status,
        )
    if status >= 500:
        raise ProviderError(
            "provider_unavailable",
            "Сервис GigaChat временно недоступен.",
            status,
        )
    raise ProviderError("provider_error", "GigaChat вернул ошибку запроса.", status)


def _send(
    method: str,
    url: str,
    *,
    headers: dict[str, str],
    data: Any = None,
    json_body: dict[str, Any] | None = None,
) -> requests.Response:
    started = time.monotonic()
    read_timeout = ai_lab_limits()["provider_read_timeout_seconds"]
    try:
        return requests.request(
            method,
            url,
            headers=headers,
            data=data,
            json=json_body,
            timeout=(CONNECT_TIMEOUT_SECONDS, read_timeout),
            verify=_ssl_verify(),
        )
    except requests.exceptions.SSLError as exc:
        raise ProviderError(
            "tls_verification_failed",
            "Не удалось проверить сертификат GigaChat. Проверьте доверенный сертификат Минцифры и GIGACHAT_CA_BUNDLE_FILE/GIGACHAT_CA_BUNDLE.",
        ) from exc
    except requests.exceptions.ConnectTimeout as exc:
        raise ProviderError("connection_timeout", "GigaChat не ответил вовремя.") from exc
    except requests.exceptions.ReadTimeout as exc:
        logger.warning(
            "AI Lab GigaChat read timeout: method=%s endpoint=%s elapsed_seconds=%.1f configured_seconds=%s detail=%s",
            method,
            url.split("/api/")[0].split("/v1/")[0],
            time.monotonic() - started,
            read_timeout,
            str(exc)[:300],
        )
        raise ProviderError("response_timeout", "GigaChat не завершил ответ за отведённое время.") from exc
    except requests.exceptions.ConnectionError as exc:
        raise ProviderError("connection_failed", "Не удалось соединиться с GigaChat API.") from exc
    except requests.exceptions.RequestException as exc:
        raise ProviderError("network_error", "Сетевой запрос к GigaChat завершился ошибкой.") from exc


@contextmanager
def _cross_process_gigachat_lock():
    if has_app_context():
        lock_path = Path(current_app.instance_path) / "ai_lab_gigachat.lock"
    else:
        lock_path = Path(__file__).resolve().parents[2] / "instance" / "ai_lab_gigachat.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as lock_file:
        lock_file.seek(0, os.SEEK_END)
        if lock_file.tell() == 0:
            lock_file.write(b"\0")
            lock_file.flush()
        lock_file.seek(0)
        if os.name == "nt":
            import msvcrt

            deadline = time.monotonic() + ai_lab_limits()["queue_wait_seconds"]
            while True:
                try:
                    msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise ProviderError("queue_timeout", "Ожидание очереди GigaChat превысило допустимое время.")
                    time.sleep(0.05)
            try:
                yield
            finally:
                lock_file.seek(0)
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


class GigaChatRequestQueue:
    """FIFO gate for GigaChat requests in this backend process."""

    def __init__(self):
        self._condition = threading.Condition()
        self._waiting: deque[tuple[str, str]] = deque()
        self._active: dict[str, str] = {}

    @contextmanager
    def request(self, label: str):
        limits = ai_lab_limits()
        concurrency = limits["gigachat_concurrency"]
        ticket = uuid.uuid4().hex
        deadline = time.monotonic() + limits["queue_wait_seconds"]
        with self._condition:
            if len(self._waiting) >= limits["max_queue_size"] and len(self._active) >= concurrency:
                raise ProviderError("queue_full", "Очередь GigaChat заполнена. Дождитесь завершения текущих запросов.")
            self._waiting.append((ticket, label))
            while True:
                ticket_index = next(
                    (index for index, (queued_ticket, _) in enumerate(self._waiting) if queued_ticket == ticket),
                    None,
                )
                if ticket_index is None:
                    raise ProviderError("queue_cancelled", "Запрос больше не находится в очереди GigaChat.")
                if ticket_index < max(0, concurrency - len(self._active)):
                    self._waiting.remove((ticket, label))
                    self._active[ticket] = label
                    break
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self._waiting.remove((ticket, label))
                    self._condition.notify_all()
                    raise ProviderError("queue_timeout", "Ожидание очереди GigaChat превысило допустимое время.")
                self._condition.wait(remaining)
        try:
            with _cross_process_gigachat_lock():
                yield
        finally:
            with self._condition:
                self._active.pop(ticket, None)
                self._condition.notify_all()

    def snapshot(self) -> dict[str, Any]:
        limits = ai_lab_limits()
        with self._condition:
            waiting = [label for _, label in self._waiting]
            active = list(self._active.values())
        return {
            "active_count": len(active),
            "active": active,
            "queued_count": len(waiting),
            "queued": waiting,
            "concurrency_limit": limits["gigachat_concurrency"],
            "queue_limit": limits["max_queue_size"],
            "queue_wait_seconds": limits["queue_wait_seconds"],
        }


gigachat_request_queue = GigaChatRequestQueue()


def queue_status() -> dict[str, Any]:
    return gigachat_request_queue.snapshot()


class GigaChatProvider:
    name = "gigachat"

    def __init__(self, settings: dict[str, str | bool] | None = None):
        self.settings = settings or provider_settings()
        self.auth_key = str(self.settings["auth_key"])
        self.scope = str(self.settings["scope"])
        if not self.auth_key:
            raise ProviderError("not_configured", "Ключ GigaChat не задан в серверном окружении.")

    def _access_token(self, force_refresh: bool = False) -> str:
        fingerprint = _config_fingerprint(self.settings)
        now = time.monotonic()
        with _TOKEN_LOCK:
            if (
                not force_refresh
                and _TOKEN_CACHE["fingerprint"] == fingerprint
                and _TOKEN_CACHE["value"]
                and float(_TOKEN_CACHE["expires_at"]) > now + 60
            ):
                return str(_TOKEN_CACHE["value"])

            response = _send(
                "POST",
                OAUTH_URL,
                headers={
                    "Authorization": f"Basic {self.auth_key}",
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Accept": "application/json",
                    "RqUID": str(uuid.uuid4()),
                },
                data={"scope": self.scope},
            )
            _raise_for_status(response)
            try:
                payload = response.json()
                token = payload["access_token"]
                expires_at = float(payload.get("expires_at", time.time() + 1800))
            except (ValueError, TypeError, KeyError) as exc:
                raise ProviderError("invalid_token_response", "GigaChat вернул некорректный ответ авторизации.") from exc
            if not isinstance(token, str) or not token.strip():
                raise ProviderError("invalid_token_response", "GigaChat не вернул токен доступа.")
            # OAuth responses may express the Unix timestamp in milliseconds.
            if expires_at > 10_000_000_000:
                expires_at /= 1000
            remaining = expires_at - time.time()
            if remaining <= 0:
                raise ProviderError("invalid_token_response", "Срок действия токена GigaChat уже истёк.")
            _TOKEN_CACHE.update(
                fingerprint=fingerprint,
                value=token,
                expires_at=now + remaining,
            )
            return token

    def _api_request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
    ) -> requests.Response:
        for auth_attempt in range(2):
            token = self._access_token(force_refresh=auth_attempt > 0)
            response = _send(
                method,
                f"{API_BASE_URL}{path}",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
                json_body=json_body,
            )
            if response.status_code == 401 and auth_attempt == 0:
                with _TOKEN_LOCK:
                    if _TOKEN_CACHE["value"] == token:
                        _TOKEN_CACHE.update(value=None, expires_at=0.0)
                continue
            _raise_for_status(response)
            return response
        raise ProviderError("authorization_failed", "GigaChat не принял обновлённый токен доступа.", 401)

    def list_models(self) -> list[str]:
        response = self._api_request("GET", "/v1/models")
        try:
            payload = response.json()
            entries = payload.get("data", payload.get("models", []))
        except (ValueError, AttributeError) as exc:
            raise ProviderError("invalid_provider_response", "GigaChat вернул некорректный список моделей.") from exc
        if not isinstance(entries, list):
            raise ProviderError("invalid_provider_response", "GigaChat вернул некорректный список моделей.")
        models = sorted(
            {
                str(item.get("id") or item.get("name") or "").strip()
                for item in entries
                if isinstance(item, dict) and (item.get("id") or item.get("name"))
                and (
                    not item.get("type")
                    or str(item.get("type")).strip().casefold() in {"chat", "completion"}
                )
            }
        )
        if not models:
            raise ProviderError("no_models_available", "Для этого ключа GigaChat не вернул доступных моделей.")
        return models

    def complete(
        self,
        model: str,
        system_prompt: str,
        user_payload: dict[str, Any],
        *,
        repair_issue: str | None = None,
    ) -> CompletionResult:
        if repair_issue:
            user_payload = {**user_payload, "semantic_repair_issue": repair_issue}
        generation_parameters = {
            "temperature": 0.1,
            "max_tokens": ai_lab_limits()["max_completion_tokens"],
            "top_p": None,
            "top_p_note": "not set; provider default",
            "response_format": "json_schema_strict",
        }
        body = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": json.dumps(user_payload, ensure_ascii=False, separators=(",", ":")),
                },
            ],
            "temperature": generation_parameters["temperature"],
            "max_tokens": generation_parameters["max_tokens"],
            "response_format": {
                "type": "json_schema",
                "schema": RESPONSE_SCHEMA,
                "strict": True,
            },
        }
        payload_id = str(uuid.uuid4())
        payload_json = json.dumps(body, ensure_ascii=False, separators=(",", ":"))
        payload_sha256 = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
        response = self._api_request("POST", "/v1/chat/completions", json_body=body)
        try:
            payload = response.json()
            content = payload["choices"][0]["message"]["content"]
            actual_model = str(payload.get("model") or model)
            usage = payload.get("usage") or {}
            input_tokens = usage.get("prompt_tokens")
            cached_input_tokens = usage.get("precached_prompt_tokens")
            output_tokens = usage.get("completion_tokens")
            billable_total_tokens = usage.get("total_tokens")
        except (ValueError, TypeError, KeyError, IndexError) as exc:
            raise ProviderError("invalid_provider_response", "GigaChat вернул неполный ответ модели.") from exc
        if not isinstance(content, str):
            raise ProviderError("invalid_provider_response", "Ответ GigaChat не содержит текстовый JSON.")
        return CompletionResult(
            content=content,
            model=actual_model,
            input_tokens=(
                _optional_nonnegative_int(input_tokens) + (_optional_nonnegative_int(cached_input_tokens) or 0)
                if _optional_nonnegative_int(input_tokens) is not None
                else None
            ),
            output_tokens=_optional_nonnegative_int(output_tokens),
            prompt_tokens=_optional_nonnegative_int(input_tokens),
            precached_prompt_tokens=_optional_nonnegative_int(cached_input_tokens),
            total_tokens=_optional_nonnegative_int(billable_total_tokens),
            payload_id=payload_id,
            payload_sha256=payload_sha256,
            request_payload=body,
            generation_parameters=generation_parameters,
        )

    def complete_structured(self, model: str, system_prompt: str, user_payload: dict[str, Any], schema: dict[str, Any]) -> CompletionResult:
        """Use the same authenticated, TLS-validated transport for a separate Lab schema."""
        parameters = {"temperature": 0.1, "max_tokens": ai_lab_limits()["max_completion_tokens"], "top_p": None, "response_format": "json_schema_strict"}
        body = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False, separators=(",", ":"))},
            ],
            "temperature": parameters["temperature"],
            "max_tokens": parameters["max_tokens"],
            "response_format": {"type": "json_schema", "schema": schema, "strict": True},
        }
        payload_json = json.dumps(body, ensure_ascii=False, separators=(",", ":"))
        response = self._api_request("POST", "/v1/chat/completions", json_body=body)
        try:
            payload = response.json()
            content = payload["choices"][0]["message"]["content"]
            usage = payload.get("usage") or {}
        except (ValueError, TypeError, KeyError, IndexError) as exc:
            raise ProviderError("invalid_provider_response", "GigaChat вернул неполное предложение рубрики.") from exc
        if not isinstance(content, str):
            raise ProviderError("invalid_provider_response", "GigaChat не вернул текст рубрики.")
        prompt_tokens = _optional_nonnegative_int(usage.get("prompt_tokens"))
        cached_tokens = _optional_nonnegative_int(usage.get("precached_prompt_tokens"))
        return CompletionResult(
            content=content,
            model=str(payload.get("model") or model),
            input_tokens=prompt_tokens + (cached_tokens or 0) if prompt_tokens is not None else None,
            output_tokens=_optional_nonnegative_int(usage.get("completion_tokens")),
            prompt_tokens=prompt_tokens,
            precached_prompt_tokens=cached_tokens,
            total_tokens=_optional_nonnegative_int(usage.get("total_tokens")),
            payload_id=str(uuid.uuid4()),
            payload_sha256=hashlib.sha256(payload_json.encode("utf-8")).hexdigest(),
            request_payload=body,
            generation_parameters=parameters,
        )


def _optional_nonnegative_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if number >= 0 else None
