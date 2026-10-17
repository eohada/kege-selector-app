"""Административные маршруты отдельной AI Homework Lab."""
from __future__ import annotations

import time
from functools import wraps
from typing import Any, Callable

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required

from app.ai_lab.config import ai_lab_limits
from app.ai_lab.config import code_judge_limits
from app.ai_lab.code_judge import (
    CodeJudgeError,
    delete_test_set,
    ensure_seeded_test_sets,
    get_run as get_code_judge_run,
    list_history as list_code_judge_history,
    run_request as run_code_judge_request,
    save_test_set,
)
from app.ai_lab.code_judge_runner_client import runner_diagnostics
from app.ai_lab.prompts import DEFAULT_PROMPT_TEXT
from app.ai_lab.quality_dashboard import quality_snapshot
from app.ai_lab.provider import (
    GigaChatProvider,
    ProviderError,
    gigachat_request_queue,
    is_local_ai_lab_enabled,
    provider_settings,
)
from app.ai_lab.rubric_builder import (
    RubricError, approve_rubric, generate_rubric, get_rubric, latest_test_verification,
    list_rubrics, repair_rubric, review_rubric, revise_rubric, verify_proposed_tests,
)
from app.ai_lab.scenarios import list_python_assignments, list_scenarios
from app.ai_lab.service import (
    LabDisabledError,
    LabInputError,
    LabRateLimitError,
    create_prompt_version,
    ensure_initial_prompt,
    get_experiment,
    get_prompt_versions,
    get_provider_card,
    run_experiment,
    save_manual_review,
)
from core.db_models import AiLabPromptVersion

ai_lab_bp = Blueprint("ai_lab", __name__, url_prefix="/admin/ai-lab")


def _admin_required(view: Callable) -> Callable:
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if not (current_user.is_admin() or current_user.is_creator()):
            abort(403)
        return view(*args, **kwargs)

    return wrapped


def _json_error(message: str, status: int, error_code: str | None = None, **details):
    return jsonify({"ok": False, "error": message, "error_code": error_code, **details}), status


def _tls_diagnostics(settings: dict[str, Any]) -> dict[str, Any]:
    ca_bundle = str(settings.get("ca_bundle") or "")
    return {
        "tls_validation": "enabled",
        "ca_bundle_configured": bool(ca_bundle),
        "ca_bundle_source": settings.get("ca_bundle_source"),
        "ca_bundle_file_exists": bool(settings.get("ca_bundle_file_exists")),
        "ca_bundle_path": ca_bundle or None,
        "transport": "requests verify=ca_bundle_file" if ca_bundle else "requests verify=system trust store",
        "official_sdk_used": False,
    }


def serialize_experiment(experiment) -> dict[str, Any]:
    quality = experiment.quality_json or {}
    return {
        "id": experiment.id,
        "status": experiment.status,
        "status_label": {
            "queued": "В очереди",
            "running": "Обработка",
            "succeeded": "Проверка завершена",
            "failed": "Ошибка",
            "invalid_response": "Некорректный ответ модели",
        }.get(experiment.status, experiment.status),
        "provider": experiment.provider,
        "model": experiment.model,
        "scenario_id": experiment.scenario_id,
        "input_snapshot": experiment.input_snapshot or {},
        "expected": quality.get("expected") or experiment.expected_snapshot or {},
        "result": experiment.result_json,
        "quality": {
            key: value
            for key, value in quality.items()
            if key != "expected"
        },
        "validation_status": experiment.validation_status,
        "error_code": experiment.error_code,
        "error_message": experiment.error_message,
        "raw_response": experiment.raw_response,
        "prompt_version_no": experiment.prompt_version_no,
        "input_tokens": experiment.input_tokens,
        "output_tokens": experiment.output_tokens,
        "duration_ms": experiment.duration_ms,
        "manual_rating": experiment.manual_rating,
        "manual_comment": experiment.manual_comment,
        "created_at": experiment.created_at.isoformat() if experiment.created_at else None,
        "experiment_url": url_for("ai_lab.experiment", experiment_id=experiment.id),
        "review_url": url_for("ai_lab.review_experiment", experiment_id=experiment.id),
    }


def _render_studio(experiment=None):
    enabled = is_local_ai_lab_enabled()
    versions: list[AiLabPromptVersion] = []
    selected_prompt = None
    if enabled:
        selected_prompt = ensure_initial_prompt()
        versions = get_prompt_versions()
    elif experiment and experiment.prompt_version_no:
        selected_prompt = None

    scenarios = list_scenarios()
    selected_scenario = scenarios[0]
    input_snapshot = None
    saved_result = None
    if experiment:
        input_snapshot = experiment.input_snapshot or {}
        selected_scenario = next(
            (item for item in scenarios if item["id"] == experiment.scenario_id),
            selected_scenario,
        )
        saved_result = serialize_experiment(experiment)

    prompt_text = (
        experiment.prompt_snapshot
        if experiment and experiment.prompt_snapshot
        else selected_prompt.content
        if selected_prompt
        else DEFAULT_PROMPT_TEXT
    )
    return render_template(
        "sandbox/ai_homework_studio.html",
        ai_lab_enabled=enabled,
        provider_card=get_provider_card(),
        scenarios=scenarios,
        selected_scenario=selected_scenario,
        input_snapshot=input_snapshot,
        saved_result=saved_result,
        prompt_versions=versions,
        selected_prompt=selected_prompt,
        prompt_text=prompt_text,
        ai_lab_limits=ai_lab_limits(),
        code_judge_test_sets=ensure_seeded_test_sets() if enabled else [],
    )

@ai_lab_bp.get("/studio")
@_admin_required
def studio():
    return _render_studio()


@ai_lab_bp.get("/studio/<int:experiment_id>")
@_admin_required
def experiment(experiment_id: int):
    item = get_experiment(experiment_id)
    if not item:
        abort(404)
    return _render_studio(item)


@ai_lab_bp.get("/api/models")
@_admin_required
def models():
    if not is_local_ai_lab_enabled():
        return _json_error("AI Lab выключена. Включите её только для локального режима.", 423, "lab_disabled")
    settings = provider_settings()
    if not settings["configured"]:
        return _json_error("Ключ GigaChat не задан в серверном окружении или локальном .env.", 503, "not_configured")
    try:
        with gigachat_request_queue.request("Загрузка моделей"):
            available = GigaChatProvider(settings).list_models()
    except ProviderError as exc:
        return _json_error(str(exc), 503, exc.code, tls=_tls_diagnostics(settings))
    return jsonify(
        {
            "ok": True,
            "provider": "GigaChat",
            "state": "Подключено",
            "models": available,
            "default_model": settings["default_model"],
            "tls": _tls_diagnostics(settings),
        }
    )


@ai_lab_bp.get("/api/queue")
@_admin_required
def queue():
    limits = ai_lab_limits()
    return jsonify({"ok": True, "queue": gigachat_request_queue.snapshot(), "limits": limits})


@ai_lab_bp.post("/api/diagnostics")
@_admin_required
def diagnostics():
    if not is_local_ai_lab_enabled():
        return _json_error("AI Lab выключена. Включите её только для локального режима.", 423, "lab_disabled")
    settings = provider_settings()
    if not settings["configured"]:
        return _json_error("Ключ GigaChat не задан в серверном окружении или локальном .env.", 503, "not_configured")
    started = time.monotonic()
    try:
        with gigachat_request_queue.request("Диагностика подключения"):
            available = GigaChatProvider(settings).list_models()
    except ProviderError as exc:
        current_app.logger.warning(
            "AI Lab GigaChat diagnostic failed: code=%s status=%s",
            exc.code,
            exc.status_code,
        )
        return _json_error(str(exc), 503, exc.code, tls=_tls_diagnostics(settings))
    elapsed = max(0, round((time.monotonic() - started) * 1000))
    default_model = str(settings["default_model"])
    selected_model = default_model if default_model in available else ""
    return jsonify(
        {
            "ok": True,
            "provider": "GigaChat",
            "state": "Подключено",
            "scope": settings["scope"],
            "selected_model": selected_model,
            "available": True,
            "duration_ms": elapsed,
            "models": available,
            "tls": _tls_diagnostics(settings),
        }
    )


@ai_lab_bp.post("/api/experiments")
@_admin_required
def start_experiment():
    if not request.is_json:
        return _json_error("Ожидался JSON-запрос.", 400)
    try:
        item = run_experiment(
            actor_user_id=int(current_user.id),
            payload=request.get_json(silent=True),
        )
    except LabDisabledError as exc:
        return _json_error(str(exc), 423, "lab_disabled")
    except LabRateLimitError as exc:
        return _json_error(str(exc), 429, "lab_rate_limited")
    except LabInputError as exc:
        return _json_error(str(exc), 400, "invalid_input")
    except ProviderError as exc:
        return _json_error(str(exc), 503, exc.code)
    except Exception:
        current_app.logger.exception("AI Lab request could not be recorded")
        return _json_error("Не удалось сохранить запуск. Обновите страницу и попробуйте снова.", 500)
    return jsonify({"ok": item.status == "succeeded", **serialize_experiment(item)})


@ai_lab_bp.post("/api/experiments/<int:experiment_id>/review")
@_admin_required
def review_experiment(experiment_id: int):
    item = get_experiment(experiment_id)
    if not item:
        current_app.logger.warning(
            "AI Lab manual review experiment not found: experiment_id=%s",
            experiment_id,
        )
        return _json_error(
            f"Эксперимент #{experiment_id} не найден в базе AI Lab этого backend.",
            404,
            "experiment_not_found",
        )
    if item.status != "succeeded" or not item.result_json:
        return _json_error("Оценивать можно только завершённые проверки с валидным результатом.", 409)
    payload = request.get_json(silent=True) if request.is_json else request.form
    try:
        save_manual_review(
            item,
            actor_user_id=int(current_user.id),
            rating=str(payload.get("rating") or ""),
            comment=str(payload.get("comment") or ""),
        )
    except LabInputError as exc:
        return _json_error(str(exc), 400)
    return jsonify({"ok": True, "experiment": serialize_experiment(item)})


def _code_judge_disabled():
    return _json_error(
        "BooStudy Code Judge доступен только в локальной AI Lab при AI_LAB_ENABLED=true.",
        423,
        "lab_disabled",
    )


@ai_lab_bp.get("/code-judge")
@_admin_required
def code_judge_page():
    enabled = is_local_ai_lab_enabled()
    test_sets = ensure_seeded_test_sets() if enabled else []
    selected = test_sets[0] if test_sets else None
    return render_template(
        "sandbox/code_judge.html",
        code_judge_enabled=enabled,
        code_judge_test_sets=test_sets,
        code_judge_selected=selected,
        code_judge_history=list_code_judge_history(20) if enabled else [],
        code_judge_runner=runner_diagnostics() if enabled else {"ready": False, "message": "Локальная AI Lab выключена."},
        code_judge_limits=code_judge_limits(),
        code_judge_assignments=list_python_assignments(),
        approved_rubrics=list_rubrics(approved_only=True) if enabled else [],
    )


@ai_lab_bp.get("/rubric-builder")
@_admin_required
def rubric_builder_page():
    return render_template(
        "sandbox/ai_rubric_builder.html",
        ai_lab_enabled=is_local_ai_lab_enabled(),
        rubrics=list_rubrics() if is_local_ai_lab_enabled() else [],
        default_model=provider_settings()["default_model"],
    )


@ai_lab_bp.get("/quality")
@_admin_required
def quality_dashboard_page():
    if not is_local_ai_lab_enabled():
        return _code_judge_disabled()
    return render_template("sandbox/ai_lab_quality.html", snapshot=quality_snapshot())


@ai_lab_bp.get("/api/rubrics")
@_admin_required
def rubrics_list():
    if not is_local_ai_lab_enabled():
        return _code_judge_disabled()
    return jsonify({"ok": True, "rubrics": list_rubrics(approved_only=request.args.get("approved") == "1")})


@ai_lab_bp.get("/api/rubrics/<int:version_id>")
@_admin_required
def rubric_detail(version_id: int):
    if not is_local_ai_lab_enabled():
        return _code_judge_disabled()
    item = get_rubric(version_id)
    return jsonify({"ok": True, "rubric": item}) if item else _json_error("Версия рубрики не найдена.", 404, "rubric_not_found")


@ai_lab_bp.post("/api/rubrics/generate")
@_admin_required
def rubric_generate():
    if not is_local_ai_lab_enabled():
        return _code_judge_disabled()
    payload = request.get_json(silent=True) or {}
    try:
        item = generate_rubric(payload.get("task"), str(payload.get("model") or ""), int(current_user.id), payload.get("request_key"))
    except RubricError as exc:
        return _json_error(str(exc), exc.status, "rubric_invalid")
    except ProviderError as exc:
        return _json_error(str(exc), 503, exc.code)
    return jsonify({"ok": True, "rubric": item})


@ai_lab_bp.post("/api/rubrics/<int:version_id>/revise")
@_admin_required
def rubric_revise(version_id: int):
    if not is_local_ai_lab_enabled():
        return _code_judge_disabled()
    try:
        item = revise_rubric(version_id, request.get_json(silent=True), int(current_user.id))
    except RubricError as exc:
        return _json_error(str(exc), exc.status, "rubric_invalid")
    return jsonify({"ok": True, "rubric": item})


@ai_lab_bp.post("/api/rubrics/<int:version_id>/repair")
@_admin_required
def rubric_repair(version_id: int):
    if not is_local_ai_lab_enabled():
        return _code_judge_disabled()
    try:
        item = repair_rubric(version_id, request.get_json(silent=True), int(current_user.id))
    except RubricError as exc:
        return _json_error(str(exc), exc.status, "rubric_repair_invalid")
    except ProviderError as exc:
        return _json_error(str(exc), 503, exc.code)
    return jsonify({"ok": True, "rubric": item})


@ai_lab_bp.post("/api/rubrics/<int:version_id>/review")
@_admin_required
def rubric_review(version_id: int):
    if not is_local_ai_lab_enabled():
        return _code_judge_disabled()
    try:
        item = review_rubric(version_id, request.get_json(silent=True), int(current_user.id))
    except RubricError as exc:
        return _json_error(str(exc), exc.status, "rubric_review_invalid")
    return jsonify({"ok": True, "rubric": item})


@ai_lab_bp.post("/api/rubrics/<int:version_id>/approve")
@_admin_required
def rubric_approve(version_id: int):
    if not is_local_ai_lab_enabled():
        return _code_judge_disabled()
    try:
        item = approve_rubric(version_id, int(current_user.id), acknowledge_warnings=(request.get_json(silent=True) or {}).get("acknowledge_warnings") is True)
    except RubricError as exc:
        return _json_error(str(exc), exc.status, "rubric_invalid")
    return jsonify({"ok": True, "rubric": item})


@ai_lab_bp.get("/api/rubrics/<int:version_id>/test-verification")
@_admin_required
def rubric_test_verification(version_id: int):
    if not is_local_ai_lab_enabled():
        return _code_judge_disabled()
    if not get_rubric(version_id):
        return _json_error("Версия рубрики не найдена.", 404, "rubric_not_found")
    return jsonify({"ok": True, "verification": latest_test_verification(version_id)})


@ai_lab_bp.post("/api/rubrics/<int:version_id>/verify-tests")
@_admin_required
def rubric_verify_tests(version_id: int):
    if not is_local_ai_lab_enabled():
        return _code_judge_disabled()
    try:
        report = verify_proposed_tests(version_id, request.get_json(silent=True), int(current_user.id))
    except RubricError as exc:
        return _json_error(str(exc), exc.status, "rubric_tests_invalid")
    return jsonify({"ok": True, "verification": report})


@ai_lab_bp.get("/api/code-judge")
@_admin_required
def code_judge_data():
    if not is_local_ai_lab_enabled():
        return _code_judge_disabled()
    return jsonify({
        "ok": True,
        "test_sets": ensure_seeded_test_sets(),
        "history": list_code_judge_history(40),
        "runner": runner_diagnostics(),
        "limits": code_judge_limits(),
    })


@ai_lab_bp.post("/api/code-judge/test-sets")
@_admin_required
def save_code_judge_test_set():
    if not is_local_ai_lab_enabled():
        return _code_judge_disabled()
    try:
        item = save_test_set(request.get_json(silent=True), int(current_user.id))
    except CodeJudgeError as exc:
        return _json_error(str(exc), exc.status, exc.code)
    except Exception:
        current_app.logger.exception("Code Judge test set could not be saved")
        return _json_error("Не удалось сохранить набор тестов. Повторите попытку.", 500, "test_set_save_failed")
    return jsonify({"ok": True, "test_set": item})


@ai_lab_bp.delete("/api/code-judge/test-sets/<int:test_set_id>")
@_admin_required
def delete_code_judge_test_set(test_set_id: int):
    if not is_local_ai_lab_enabled():
        return _code_judge_disabled()
    try:
        delete_test_set(test_set_id)
    except CodeJudgeError as exc:
        return _json_error(str(exc), exc.status, exc.code)
    return jsonify({"ok": True})


@ai_lab_bp.get("/api/code-judge/queue")
@_admin_required
def code_judge_queue():
    if not is_local_ai_lab_enabled():
        return _code_judge_disabled()
    return jsonify({"ok": True, "runner": runner_diagnostics(), "limits": code_judge_limits()})


@ai_lab_bp.post("/api/code-judge/run")
@_admin_required
def run_code_judge():
    if not is_local_ai_lab_enabled():
        return _code_judge_disabled()
    try:
        run, created = run_code_judge_request(int(current_user.id), request.get_json(silent=True))
    except CodeJudgeError as exc:
        return _json_error(str(exc), exc.status, exc.code)
    except Exception:
        current_app.logger.exception("Code Judge request could not be recorded")
        return _json_error("Не удалось записать запуск Code Judge. Обновите страницу и повторите.", 500, "run_record_failed")
    result = {"ok": run["status"] not in {"sandbox_unavailable", "internal_error", "incomplete"}, "created": created, "run": run}
    status = 503 if run["status"] == "sandbox_unavailable" else 500 if run["status"] == "internal_error" else 200
    return jsonify(result), status


@ai_lab_bp.get("/api/code-judge/runs/<int:run_id>")
@_admin_required
def get_code_judge_run_route(run_id: int):
    if not is_local_ai_lab_enabled():
        return _code_judge_disabled()
    run = get_code_judge_run(run_id)
    if not run:
        return _json_error(f"Запуск Code Judge #{run_id} не найден.", 404, "run_not_found")
    return jsonify({"ok": True, "run": run})


@ai_lab_bp.post("/instructions/save")
@_admin_required
def save_instruction():
    if not is_local_ai_lab_enabled():
        flash("AI Lab выключена. Сохранение доступно только в локальном режиме.", "warning")
        return redirect(url_for("admin.admin_ai_lab", section="instructions"))
    try:
        version = create_prompt_version(
            request.form.get("content", ""),
            actor_user_id=int(current_user.id),
        )
    except LabInputError as exc:
        flash(str(exc), "danger")
    else:
        flash(f"Сохранена новая неизменяемая версия v0.{version.version_no}.", "success")
    return redirect(url_for("admin.admin_ai_lab", section="instructions"))


@ai_lab_bp.post("/instructions/<int:version_no>/restore")
@_admin_required
def restore_instruction(version_no: int):
    if not is_local_ai_lab_enabled():
        flash("AI Lab выключена. Восстановление доступно только в локальном режиме.", "warning")
        return redirect(url_for("admin.admin_ai_lab", section="instructions"))
    source = AiLabPromptVersion.query.filter_by(version_no=version_no).first_or_404()
    try:
        restored = create_prompt_version(
            source.content,
            actor_user_id=int(current_user.id),
            restored_from_version_no=source.version_no,
        )
    except LabInputError as exc:
        flash(str(exc), "danger")
    else:
        flash(f"Создана версия v0.{restored.version_no} на основе v0.{source.version_no}.", "success")
    return redirect(url_for("admin.admin_ai_lab", section="instructions"))

