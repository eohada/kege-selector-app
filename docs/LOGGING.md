# Logging

## Current architecture

The platform now uses a unified structured logging pipeline:

- Core config: `app/logging_core.py`
- Bootstrap: `app/__init__.py` via `configure_logging(...)`
- Audit stream: `core/audit_logger.py` (now includes request correlation id in metadata)

## Log format

All application logs are JSON with a common schema. Main fields:

- `timestamp`
- `level`
- `service`
- `module`
- `event`
- `message`
- `request_id`
- `trace_id`
- `user_id`
- `role`
- `url`
- `method`
- `remote_addr`
- `entity`
- `entity_id`
- `status`
- `duration_ms`
- `error` (for exceptions)

## Correlation

- `X-Request-ID` is accepted from incoming requests.
- If absent, a new id is generated per request.
- Response returns the same id in `X-Request-ID`.
- Request lifecycle logs are emitted by `http.request` logger.

## Storage

- Console: structured JSON
- File: `logs/app.log` (rotating, 10 MB, 5 backups)

## Operational notes

- Use `request_id` to trace a request end-to-end.
- Use `user_id` + `event` for actor-centric analysis.
- Use `status >= 400` in `http.request` events to monitor failures.
- Audit records additionally store `request_id` in `metadata`.

