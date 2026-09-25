"""CLI command for Homework AI Review health and readiness check."""
from __future__ import annotations

import os
import sys
import time
import click
from flask import current_app
from flask.cli import with_appcontext

from app.assignments.ai_review_service import (
    get_ai_review_config,
    GeminiReviewProvider,
    OpenRouterReviewProvider,
    BaseAiReviewProvider,
)


def _check_celery_broker() -> tuple[bool, str]:
    try:
        from celery_app import celery
        conn = celery.connection_for_write()
        conn.connect()
        uri = conn.as_uri()
        conn.release()
        return True, uri
    except Exception as e:
        return False, str(e)


@click.command('ai-review-check')
@click.option('--live', is_flag=True, default=False, help='Send a minimal synthetic check request to the active provider.')
@with_appcontext
def ai_review_check_command(live: bool):
    """Check AI pre-review configuration, queue health, and optional live provider connectivity."""
    cfg = get_ai_review_config()
    enabled = cfg.get('enabled', False)
    primary = cfg.get('primary_provider') or 'gemini'
    fallback = cfg.get('fallback_provider') or 'none'

    gemini_key = cfg.get('gemini_api_key') or ''
    gemini_model = cfg.get('gemini_model') or ''
    openrouter_key = cfg.get('openrouter_api_key') or ''
    openrouter_model = cfg.get('openrouter_model') or ''

    broker_ok, broker_info = _check_celery_broker()

    click.echo("=== BooStudy AI Review: Readiness Check ===")
    click.echo(f"Feature Enabled: {'YES' if enabled else 'NO'}")
    click.echo(f"Cascade Order: {primary} -> {fallback}")
    click.echo(f"Queue/Broker: {'Available (' + broker_info + ')' if broker_ok else 'Unavailable (' + broker_info + ')'}")

    gemini_status = f"Configured (model={gemini_model})" if (gemini_key and gemini_model) else (
        "Incomplete: missing API key" if not gemini_key and gemini_model else (
            "Incomplete: missing model ID" if gemini_key and not gemini_model else "Not configured"
        )
    )
    click.echo(f"Gemini Provider: {gemini_status}")

    openrouter_status = f"Configured (model={openrouter_model})" if (openrouter_key and openrouter_model) else (
        "Incomplete: missing API key" if not openrouter_key and openrouter_model else (
            "Incomplete: missing model ID" if openrouter_key and not openrouter_model else "Not configured"
        )
    )
    click.echo(f"OpenRouter Provider: {openrouter_status}")

    if not live:
        click.echo("\n[Dry-run check completed successfully. Use --live to verify provider API connectivity.]")
        return

    click.echo("\n--- Live Connectivity Check ---")
    if not enabled:
        raise click.ClickException("AI Review is disabled (AI_REVIEW_ENABLED=false). Live test aborted.")

    provider_obj: BaseAiReviewProvider | None = None
    active_prov_name = ""
    active_model_name = ""

    if primary == 'gemini':
        if not gemini_key or not gemini_model:
            raise click.ClickException("Primary provider 'gemini' is enabled, but GEMINI_API_KEY or GEMINI_MODEL is missing.")
        provider_obj = GeminiReviewProvider(gemini_key, gemini_model)
        active_prov_name = "gemini"
        active_model_name = gemini_model
    elif primary == 'openrouter':
        if not openrouter_key or not openrouter_model:
            raise click.ClickException("Primary provider 'openrouter' is enabled, but OPENROUTER_API_KEY or OPENROUTER_MODEL is missing.")
        provider_obj = OpenRouterReviewProvider(openrouter_key, openrouter_model)
        active_prov_name = "openrouter"
        active_model_name = openrouter_model
    else:
        raise click.ClickException(f"Unsupported primary provider: {primary}")

    # Synthetic minimal probe payload (no real student answers, no attachments)
    minimal_payload = {
        "assignment": {"title": "Readiness Probe", "type": "homework", "max_score": 1},
        "tasks": [
            {
                "task_id": 99999,
                "task_number": 1,
                "type": "short_answer",
                "max_score": 1,
                "condition": "Тестовый проверочный запрос.",
                "untrusted_student_answer": "Тест",
                "auto_checked": False,
            }
        ]
    }

    t0 = time.monotonic()
    raw_result, err, is_retryable = provider_obj.review(minimal_payload, timeout_sec=cfg.get('timeout_sec', 25))
    duration_ms = round((time.monotonic() - t0) * 1000)

    if err:
        click.echo(f"Status: FAILED")
        click.echo(f"Active Provider: {active_prov_name} ({active_model_name})")
        click.echo(f"Latency: {duration_ms}ms")
        raise click.ClickException(f"Live request failed: {err}")

    valid_json = isinstance(raw_result, dict) and "status" in raw_result
    click.echo(f"Status: OK (HTTP 200)")
    click.echo(f"Active Provider: {active_prov_name}")
    click.echo(f"Active Model: {active_model_name}")
    click.echo(f"Valid Structured JSON: {'YES' if valid_json else 'NO'}")
    click.echo(f"Latency: {duration_ms}ms")
    click.echo("✓ AI Review provider live check passed!")
