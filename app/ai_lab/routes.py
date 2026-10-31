"""Административные маршруты отдельной AI Homework Lab."""
from __future__ import annotations

import time
import hashlib
import json
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
from app.ai_lab.course import (
    CourseAnalysisError,
    analyze_course,
    get_course_analysis,
    list_course_analyses,
    rollback_course_proposal,
    review_course_proposal,
    synthetic_course_samples,
)
from app.ai_lab.course_adapter import export_synthetic_learning_trajectory, list_synthetic_learning_trajectories
from app.ai_lab.lesson_adapter import list_synthetic_lesson_sources
from app.ai_lab.analytics import (
    all_analytics_evidence,
    build_analytics_snapshot,
    course_analysis_input,
    synthetic_profiles,
)
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
from app.ai_lab.platform_homework import (
    link_test_set_to_task,
    list_linkable_tasks,
    platform_homework_enabled,
)
from app.ai_lab.prompts import DEFAULT_PROMPT_TEXT, SEMANTIC_RELIABILITY_PROMPT_TEXT, TRUSTWORTHY_GRADING_PROMPT_TEXT
from app.ai_lab.quality_dashboard import quality_snapshot
from app.ai_lab.practice import recommend_practice
from app.ai_lab.quality_review import BENCHMARKS, RATING_FIELDS, load_review_bundle, save_human_review
from app.ai_lab.benchmark import BenchmarkDataError
from app.ai_lab.assignment_families import (
    AssignmentFamilyError,
    approve_family_version,
    compatible_families,
    create_family_version,
    family_storage_ready,
    list_family_versions,
    resolve_family_version,
    verify_family_version,
)
from app.ai_lab.family_templates import list_family_templates
from app.ai_lab.assignment_variants import (
    list_family_variants,
    materialize_family_variant,
    verify_family_variant,
)
from app.ai_lab.lesson_intelligence import (
    LessonAnalysisError,
    analyze_lesson,
    get_lesson_analysis,
    list_lesson_analyses,
    review_lesson_observation,
    review_lesson_observations,
    synthetic_transcript_samples,
)
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
from core.db_models import AiLabExperiment, AiLabPromptVersion, db

ai_lab_bp = Blueprint("ai_lab", __name__, url_prefix="/admin/ai-lab")


def _admin_required(view: Callable) -> Callable:
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if not (current_user.is_admin() or current_user.is_creator()):
            abort(403)
        return view(*args, **kwargs)

    return wrapped


def _quality_reviewer_required(view: Callable) -> Callable:
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if not current_user.is_admin():
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
        "proxy_mode": "system" if settings.get("use_system_proxy") else "direct_for_gigachat",
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
        "synthetic_subject_id": (experiment.scenario_snapshot or {}).get("synthetic_subject_id"),
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
        ensure_initial_prompt()
        versions = get_prompt_versions()
        for prompt_content in (SEMANTIC_RELIABILITY_PROMPT_TEXT, TRUSTWORTHY_GRADING_PROMPT_TEXT):
            if any(version.content == prompt_content for version in versions):
                continue
            try:
                create_prompt_version(prompt_content, int(current_user.id))
            except LabInputError:
                versions = get_prompt_versions()
                if not any(version.content == prompt_content for version in versions):
                    raise
            versions = get_prompt_versions()
        selected_prompt = versions[0]
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
    family_versions = list_family_versions(approved_only=True) if enabled else []
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
        assignment_family_versions=family_versions,
    )

@ai_lab_bp.get("/studio")
@_admin_required
def studio():
    return _render_studio()


@ai_lab_bp.get("/assignment-families")
@_admin_required
def assignment_families_page():
    if not is_local_ai_lab_enabled():
        return _code_judge_disabled()
    storage_ready = family_storage_ready()
    return render_template(
        "sandbox/ai_lab_assignment_families.html",
        families=list_family_versions() if storage_ready else [],
        assignments=list_python_assignments() if storage_ready else [],
        rubrics=list_rubrics(approved_only=True) if storage_ready else [],
        test_sets=ensure_seeded_test_sets() if storage_ready else [],
        history=list_code_judge_history(60) if storage_ready else [],
        family_templates=list_family_templates(),
        family_variants=list_family_variants() if storage_ready else [],
        family_storage_ready=storage_ready,
    )


def _family_storage_error():
    if family_storage_ready():
        return None
    return _json_error(
        "Схема семейств Sprint 9–10 отсутствует в выбранной БД. Миграцию можно проверять только на изолированной AI Lab базе.",
        503,
        "assignment_family_schema_missing",
    )


@ai_lab_bp.get("/api/assignment-families")
@_admin_required
def assignment_families_list():
    if not is_local_ai_lab_enabled():
        return _code_judge_disabled()
    storage_error = _family_storage_error()
    if storage_error:
        return storage_error
    assignment_id = request.args.get("assignment_id")
    assignment_version = request.args.get("assignment_version", type=int)
    families = (compatible_families(assignment_id, assignment_version)
                if assignment_id and assignment_version else list_family_versions())
    return jsonify({"ok": True, "families": families})


@ai_lab_bp.get("/api/assignment-families/templates")
@_admin_required
def assignment_family_templates():
    if not is_local_ai_lab_enabled():
        return _code_judge_disabled()
    return jsonify({"ok": True, "templates": list_family_templates()})


@ai_lab_bp.get("/api/assignment-families/<int:version_id>/variants")
@_admin_required
def assignment_family_variants(version_id: int):
    if not is_local_ai_lab_enabled():
        return _code_judge_disabled()
    storage_error = _family_storage_error()
    if storage_error:
        return storage_error
    return jsonify({"ok": True, "variants": list_family_variants(version_id)})


@ai_lab_bp.post("/api/assignment-families")
@_admin_required
def assignment_family_create():
    if not is_local_ai_lab_enabled():
        return _code_judge_disabled()
    storage_error = _family_storage_error()
    if storage_error:
        return storage_error
    try:
        item = create_family_version(request.get_json(silent=True), int(current_user.id))
    except AssignmentFamilyError as exc:
        return _json_error(str(exc), exc.status_code, "assignment_family_invalid")
    return jsonify({"ok": True, "family": item}), 201


@ai_lab_bp.post("/api/assignment-families/<int:version_id>/verify")
@_admin_required
def assignment_family_verify(version_id: int):
    if not is_local_ai_lab_enabled():
        return _code_judge_disabled()
    storage_error = _family_storage_error()
    if storage_error:
        return storage_error
    try:
        item = verify_family_version(version_id)
    except AssignmentFamilyError as exc:
        return _json_error(str(exc), exc.status_code, "assignment_family_invalid")
    return jsonify({"ok": True, "family": item})


@ai_lab_bp.post("/api/assignment-families/<int:version_id>/approve")
@_admin_required
def assignment_family_approve(version_id: int):
    if not is_local_ai_lab_enabled():
        return _code_judge_disabled()
    storage_error = _family_storage_error()
    if storage_error:
        return storage_error
    try:
        item = approve_family_version(version_id, int(current_user.id))
    except AssignmentFamilyError as exc:
        return _json_error(str(exc), exc.status_code, "assignment_family_invalid")
    return jsonify({"ok": True, "family": item})


@ai_lab_bp.post("/api/assignment-families/<int:version_id>/variants")
@_admin_required
def assignment_family_materialize(version_id: int):
    if not is_local_ai_lab_enabled():
        return _code_judge_disabled()
    storage_error = _family_storage_error()
    if storage_error:
        return storage_error
    payload = request.get_json(silent=True) or {}
    try:
        item = materialize_family_variant(version_id, payload.get("parameters", {}), int(current_user.id))
    except AssignmentFamilyError as exc:
        return _json_error(str(exc), exc.status_code, "assignment_variant_invalid")
    return jsonify({"ok": True, "variant": item}), 201


@ai_lab_bp.post("/api/assignment-family-variants/<int:variant_id>/verify")
@_admin_required
def assignment_family_variant_verify(variant_id: int):
    if not is_local_ai_lab_enabled():
        return _code_judge_disabled()
    storage_error = _family_storage_error()
    if storage_error:
        return storage_error
    try:
        item = verify_family_variant(variant_id, int(current_user.id))
    except AssignmentFamilyError as exc:
        return _json_error(str(exc), exc.status_code, "assignment_variant_invalid")
    return jsonify({"ok": True, "variant": item})


@ai_lab_bp.post("/api/assignment-families/resolve")
@_admin_required
def assignment_family_resolve():
    if not is_local_ai_lab_enabled():
        return _code_judge_disabled()
    storage_error = _family_storage_error()
    if storage_error:
        return storage_error
    payload = request.get_json(silent=True) or {}
    try:
        item = resolve_family_version(
            family_id=str(payload.get("family_id") or ""),
            version_no=int(payload.get("version_no")),
            assignment_id=str(payload.get("assignment_id") or ""),
            assignment_version=int(payload.get("assignment_version")),
            variant_parameters=payload.get("variant_parameters", {}),
        )
    except (AssignmentFamilyError, TypeError, ValueError, OverflowError) as exc:
        status = exc.status_code if isinstance(exc, AssignmentFamilyError) else 400
        return _json_error(str(exc), status, "assignment_family_incompatible")
    return jsonify({"ok": True, "family": item})


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
    from core.db_models import ExamSkill

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
        exam_skills=[{
            "skill_id": f"exam-skill:{skill.skill_id}", "title": skill.title,
            "task_number": skill.task_number, "topic": skill.topic,
        } for skill in ExamSkill.query.filter_by(is_active=True).order_by(
            ExamSkill.task_number.asc(), ExamSkill.skill_id.asc(),
        ).all()] if enabled else [],
        approved_rubrics=list_rubrics(approved_only=True) if enabled else [],
        platform_homework_enabled=platform_homework_enabled(int(current_user.id)),
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


@ai_lab_bp.route("/quality-review", methods=["GET", "POST"])
@_quality_reviewer_required
def quality_review_page():
    if not is_local_ai_lab_enabled():
        return _code_judge_disabled()
    source = request.form if request.method == "POST" else request.args
    benchmark_id = source.get("benchmark", "sprint6")
    if benchmark_id not in BENCHMARKS:
        abort(404)
    available = {
        key: definition for key, definition in BENCHMARKS.items()
        if definition["manifest"].is_file() and definition["results"].is_file()
    }
    if benchmark_id not in available:
        abort(404)
    try:
        bundle = load_review_bundle(benchmark_id)
    except (BenchmarkDataError, OSError) as exc:
        current_app.logger.error("AI Lab expert review data error: %s", exc)
        abort(503, description=str(exc))

    module = source.get("module", "")
    if module and module not in RATING_FIELDS:
        abort(400)
    pending_only = source.get("pending", "1") == "1"
    error = None
    if request.method == "POST":
        run_id = str(source.get("run_id") or "")
        case_id = str(source.get("case_id") or "")
        target = next((row for row in bundle["rows"] if row["run_id"] == run_id and row["case_id"] == case_id), None)
        if target is None:
            abort(404)
        ratings = {}
        for key, _ in RATING_FIELDS[target["module"]]:
            value = source.get(f"rating__{key}")
            if value is None:
                continue
            if value not in {"yes", "no", "na"}:
                abort(400)
            ratings[key] = "na" if value == "na" else value == "yes"
        try:
            save_human_review(benchmark_id, run_id=run_id, case_id=case_id,
                              reviewer_id=int(current_user.id), ratings=ratings,
                              comments=str(source.get("comments") or ""))
        except BenchmarkDataError as exc:
            error = str(exc)
        else:
            flash("Экспертная оценка сохранена отдельно от ответа модели.", "success")
            ordered_rows = [row for row in bundle["rows"] if not module or row["module"] == module]
            current_index = next((index for index, row in enumerate(ordered_rows)
                                  if row["run_id"] == run_id and row["case_id"] == case_id), -1)
            forward_rows = ordered_rows[current_index + 1:] + ordered_rows[:max(0, current_index)]
            target_next = next((row for row in forward_rows
                                if row["case_id"] != case_id
                                and (not pending_only or row["expert_review"]["status"] != "reviewed")), None)
            return redirect(url_for("ai_lab.quality_review_page", benchmark=benchmark_id,
                                    module=module, pending=int(pending_only),
                                    case_id=target_next["case_id"] if target_next else None))

    rows = [row for row in bundle["rows"] if not module or row["module"] == module]
    if pending_only:
        rows = [row for row in rows if row["expert_review"]["status"] != "reviewed"]
    if source.get("sort", "priority") != "priority":
        rows.sort(key=lambda row: row.get("case_id", ""))
    requested_case = source.get("case_id")
    selected_index = next((index for index, row in enumerate(rows) if row["case_id"] == requested_case), 0)
    selected = rows[selected_index] if rows else None
    next_row = rows[selected_index + 1] if selected and selected_index + 1 < len(rows) else None
    previous_row = rows[selected_index - 1] if selected and selected_index else None
    return render_template(
        "sandbox/ai_lab_quality_review.html", bundle=bundle,
        available_benchmarks=available, module=module, pending_only=pending_only,
        rows=rows, selected=selected, selected_index=selected_index + 1 if selected else 0,
        case=bundle["cases"].get(selected["case_id"]) if selected else None,
        case_view=selected.get("review_presentation") if selected else None,
        rating_fields=RATING_FIELDS.get(selected["module"], ()) if selected else (),
        rating_catalog=RATING_FIELDS,
        pretty_json=lambda value: json.dumps(value, ensure_ascii=False, indent=2),
        next_row=next_row, previous_row=previous_row, error=error,
    ), 400 if error else 200


def _analytics_context(subject_id: str | None = None):
    events = all_analytics_evidence(actor_user_id=int(current_user.id))
    profiles = synthetic_profiles(events)
    selected = next((profile["id"] for profile in profiles if profile["id"] == subject_id), None)
    selected = selected or (profiles[0]["id"] if profiles else None)
    selected_events = [event for event in events if event["subject_id"] == selected]
    return events, profiles, selected, selected_events, build_analytics_snapshot(selected_events, selected)


@ai_lab_bp.get("/analytics")
@_admin_required
def analytics_page():
    if not is_local_ai_lab_enabled():
        return _code_judge_disabled()
    events, profiles, selected, selected_events, snapshot = _analytics_context(request.args.get("subject_id"))
    return render_template(
        "sandbox/ai_lab_analytics.html",
        profiles=profiles,
        selected_subject_id=selected,
        snapshot=snapshot,
        evidence_events=selected_events,
        sample_event_count=len([item for item in events if item["event_id"].startswith("demo-")]),
        saved_event_count=len([item for item in events if item["event_id"].startswith(("ai-lab-experiment:", "ai-lab-lesson:", "platform-submission:"))]),
    )


@ai_lab_bp.get("/api/analytics")
@_admin_required
def analytics_data():
    if not is_local_ai_lab_enabled():
        return _code_judge_disabled()
    _, profiles, selected, selected_events, snapshot = _analytics_context(request.args.get("subject_id"))
    return jsonify({
        "ok": True,
        "profiles": profiles,
        "selected_subject_id": selected,
        "snapshot": snapshot,
        "course_analysis_input": course_analysis_input(selected_events, selected) if selected else None,
    })


def _practice_context(subject_id: str | None = None, course_analysis_id: int | None = None):
    events, profiles, selected, selected_events, snapshot = _analytics_context(subject_id)
    completed = [event["assignment"]["id"] for event in selected_events if event.get("assignment")]
    course_record = get_course_analysis(course_analysis_id, current_user.id) if course_analysis_id else None
    if course_analysis_id and (not course_record or course_record.status != "succeeded"):
        abort(404)
    course_outline = course_record.input_snapshot if course_record and course_record.status == "succeeded" else None
    if course_outline:
        topic_assignments: dict[str, list[str]] = {}
        for assignment in course_outline.get("assignments", []):
            if assignment.get("topic_id") and assignment.get("assignment_id"):
                topic_assignments.setdefault(assignment["topic_id"], []).append(assignment["assignment_id"])
        course_outline = {**course_outline, "topics": [
            {**topic, "assignment_ids": topic_assignments.get(topic.get("topic_id"), [])}
            for topic in course_outline.get("topics", [])
        ]}
    recommendations = recommend_practice(snapshot, list_python_assignments(), completed, course_outline)
    return profiles, selected, snapshot, recommendations, list_course_analyses(current_user.id), course_record


@ai_lab_bp.get("/practice")
@_admin_required
def practice_page():
    if not is_local_ai_lab_enabled():
        return _code_judge_disabled()
    course_id = request.args.get("course_analysis_id", type=int)
    profiles, selected, snapshot, recommendations, courses, selected_course = _practice_context(request.args.get("subject_id"), course_id)
    return render_template(
        "sandbox/ai_lab_practice.html",
        profiles=profiles,
        selected_subject_id=selected,
        snapshot=snapshot,
        recommendations=recommendations,
        course_analyses=[item for item in courses if item.status == "succeeded"],
        selected_course_analysis_id=selected_course.id if selected_course else None,
    )


@ai_lab_bp.get("/api/practice/recommendations")
@_admin_required
def practice_recommendations():
    if not is_local_ai_lab_enabled():
        return _code_judge_disabled()
    profiles, selected, snapshot, recommendations, _, _ = _practice_context(
        request.args.get("subject_id"), request.args.get("course_analysis_id", type=int)
    )
    return jsonify({"ok": True, "profiles": profiles, "selected_subject_id": selected,
                    "analytics": snapshot, **recommendations})


@ai_lab_bp.post("/api/practice/feedback")
@_admin_required
def practice_feedback():
    if not is_local_ai_lab_enabled():
        return _code_judge_disabled()
    payload = request.get_json(silent=True) or {}
    subject_id = str(payload.get("subject_id") or "")
    assignment_id = str(payload.get("assignment_id") or "")
    vote = str(payload.get("vote") or "")
    course_id = payload.get("course_analysis_id")
    synthetic_subject_ids = {
        profile["id"] for profile in synthetic_profiles(all_analytics_evidence(actor_user_id=int(current_user.id)))
    }
    if subject_id not in synthetic_subject_ids or not assignment_id or vote not in {"helpful", "unhelpful"}:
        return _json_error("Оценка должна относиться к синтетическому профилю и существующей рекомендации.", 400, "invalid_practice_feedback")
    if course_id is not None:
        try:
            course_id = int(course_id)
        except (TypeError, ValueError):
            return _json_error("Некорректная версия учебного курса.", 400, "invalid_course_analysis_id")
    profiles, selected, _, recommendations, _, _ = _practice_context(subject_id, course_id)
    recommendation = next((item for item in recommendations["recommendations"] if item["assignment_id"] == assignment_id), None)
    if not recommendation or selected != subject_id:
        return _json_error("Рекомендация больше не доступна для выбранного профиля и версии курса.", 409, "stale_practice_recommendation")
    source = {"subject_id": subject_id, "assignment_id": assignment_id, "course_analysis_id": course_id,
              "vote": vote, "basis": recommendation["basis"], "course_context": recommendation.get("course_context")}
    encoded = json.dumps(source, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    request_key = hashlib.sha256(f"practice-feedback:{current_user.id}:{encoded}".encode()).hexdigest()[:36]
    record = AiLabExperiment.query.filter_by(actor_user_id=current_user.id, request_key=request_key).first()
    if not record:
        record = AiLabExperiment(
            actor_user_id=current_user.id, request_key=request_key, scenario_id="ai-practice-feedback", status="succeeded",
            provider="local", prompt_snapshot="Сохранение оценки полезности рекомендации AI Practice.",
            scenario_snapshot={"module": "ai_practice", "subject_id": subject_id, "assignment_id": assignment_id},
            input_snapshot=source, expected_snapshot={},
            result_json={"vote": vote, "recommendation_basis": recommendation["basis"]},
            validation_status="valid", quality_json={"module": "ai_practice_feedback", "synthetic_only": True},
        )
        db.session.add(record)
        db.session.commit()
    return jsonify({"ok": True, "feedback_id": record.id, "vote": vote, "saved_at": record.created_at.isoformat() if record.created_at else None})


def _serialize_tutor_proposal(record) -> dict[str, Any]:
    from app.ai_lab.tutor_core import tutor_history
    return next((item for item in tutor_history(int(record.actor_user_id)) if item["id"] == record.id), {})


@ai_lab_bp.get("/tutor-core")
@_admin_required
def tutor_core_page():
    if not is_local_ai_lab_enabled():
        return _code_judge_disabled()
    from app.ai_lab.learning_evidence import EvidenceContractError
    from app.ai_lab.tutor_core31 import get_tutor_core31_state
    try:
        state = get_tutor_core31_state(int(current_user.id))
    except EvidenceContractError as exc:
        return render_template("sandbox/ai_lab_tutor_core31.html", state=None, page_error=str(exc)), 409
    except Exception:
        current_app.logger.exception("Tutor Core 3.1 failed to load its local synthetic evidence")
        return render_template(
            "sandbox/ai_lab_tutor_core31.html",
            state=None,
            page_error="Не удалось загрузить локальные учебные события. Подробности сохранены в журнале сервера.",
        ), 500
    from app.ai_lab.tutor_core import tutor_history
    proposal_history = {
        learner["subject_id"]: tutor_history(int(current_user.id), learner["subject_id"])
        for learner in state.get("learners", []) if learner.get("subject_id")
    }
    return render_template("sandbox/ai_lab_tutor_core31.html", state=state, page_error=None,
                           proposal_history=proposal_history)


@ai_lab_bp.get("/tutor-core/ege-2027")
@_admin_required
def tutor_core3_page():
    if not is_local_ai_lab_enabled():
        return _code_judge_disabled()
    from app.ai_lab.tutor_core3 import TutorCore3Error, get_tutor_core3_state
    try:
        state = get_tutor_core3_state()
    except TutorCore3Error as exc:
        return render_template(
            "sandbox/ai_lab_tutor_core3_demo.html",
            state=None,
            page_error=str(exc),
            legacy_note=None,
        ), exc.status_code
    return render_template(
        "sandbox/ai_lab_tutor_core3_demo.html",
        state=state,
        page_error=None,
        legacy_note=None,
    )


@ai_lab_bp.post("/api/tutor-core3/demo/seed")
@_admin_required
def tutor_core3_seed_demo():
    if not is_local_ai_lab_enabled():
        return _code_judge_disabled()
    from app.ai_lab.tutor_core3 import TutorCore3Error, seed_tutor_core3_demo
    try:
        result = seed_tutor_core3_demo(int(current_user.id))
    except TutorCore3Error as exc:
        return _json_error(str(exc), exc.status_code, exc.code)
    return jsonify({"ok": True, **result})


@ai_lab_bp.get("/knowledge")
@_admin_required
def knowledge_base_page():
    if not is_local_ai_lab_enabled():
        return _code_judge_disabled()
    from app.ai_lab.knowledge_base import KnowledgeBaseError, knowledge_snapshot
    try:
        state = knowledge_snapshot()
    except KnowledgeBaseError as exc:
        return render_template("sandbox/ai_lab_knowledge.html", state=None, page_error=str(exc)), exc.status_code
    return render_template("sandbox/ai_lab_knowledge.html", state=state, page_error=None)


@ai_lab_bp.get("/api/knowledge")
@_admin_required
def knowledge_base_data():
    if not is_local_ai_lab_enabled():
        return _code_judge_disabled()
    from app.ai_lab.knowledge_base import KnowledgeBaseError, knowledge_snapshot
    try:
        return jsonify({"ok": True, "knowledge_base": knowledge_snapshot()})
    except KnowledgeBaseError as exc:
        return _json_error(str(exc), exc.status_code, exc.code)


@ai_lab_bp.get("/api/knowledge/entries/<int:entry_id>")
@_admin_required
def knowledge_base_entry_history(entry_id: int):
    if not is_local_ai_lab_enabled():
        return _code_judge_disabled()
    from app.ai_lab.knowledge_base import KnowledgeBaseError, knowledge_entry_history
    try:
        return jsonify({"ok": True, "entry": knowledge_entry_history(entry_id)})
    except KnowledgeBaseError as exc:
        return _json_error(str(exc), exc.status_code, exc.code)


@ai_lab_bp.post("/api/knowledge/entries")
@_admin_required
def knowledge_base_create_version():
    if not is_local_ai_lab_enabled():
        return _code_judge_disabled()
    if request.content_length and request.content_length > 1_000_000:
        return _json_error("Материал превышает лимит 1 МБ.", 413, "knowledge_payload_too_large")
    from app.ai_lab.knowledge_base import KnowledgeBaseError, create_knowledge_version
    try:
        version = create_knowledge_version(int(current_user.id), request.get_json(silent=True))
    except KnowledgeBaseError as exc:
        return _json_error(str(exc), exc.status_code, exc.code)
    return jsonify({"ok": True, "version_id": version.id, "version_no": version.version_no})


@ai_lab_bp.post("/api/knowledge/versions/<int:version_id>/review")
@_admin_required
def knowledge_base_review_version(version_id: int):
    if not is_local_ai_lab_enabled():
        return _code_judge_disabled()
    if request.content_length and request.content_length > 32_000:
        return _json_error("Редакционная проверка превышает лимит 32 КБ.", 413, "knowledge_review_too_large")
    payload = request.get_json(silent=True) or {}
    from app.ai_lab.knowledge_base import KnowledgeBaseError, review_knowledge_version
    try:
        event = review_knowledge_version(
            int(current_user.id), version_id, str(payload.get("decision") or ""),
            str(payload.get("rationale") or ""),
            payload.get("review_details"),
        )
    except KnowledgeBaseError as exc:
        return _json_error(str(exc), exc.status_code, exc.code)
    return jsonify({"ok": True, "decision": event.decision, "saved_at": event.created_at.isoformat() if event.created_at else None})


@ai_lab_bp.get("/api/tutor-core/history")
@_admin_required
def tutor_core_history():
    if not is_local_ai_lab_enabled():
        return _code_judge_disabled()
    from app.ai_lab.tutor_core import tutor_history
    profile_id = request.args.get("profile_id")
    return jsonify({"ok": True, "history": tutor_history(int(current_user.id), profile_id)})


@ai_lab_bp.post("/api/tutor-core/proposals")
@_admin_required
def tutor_core_create_proposal():
    if not is_local_ai_lab_enabled():
        return _code_judge_disabled()
    from app.ai_lab.tutor_core import TutorCoreError, create_tutor_proposal
    payload = request.get_json(silent=True) or request.form
    include_model_value = payload.get("include_model")
    include_model = (True if include_model_value is None else
                     str(include_model_value).strip().lower() not in {"false", "0", "no", "off"})
    try:
        record = create_tutor_proposal(int(current_user.id), str(payload.get("profile_id") or ""),
                                       str(payload.get("model") or "") or None,
                                       include_model=include_model)
    except TutorCoreError as exc:
        return _json_error(str(exc), exc.status_code, exc.code)
    result = _serialize_tutor_proposal(record)
    if not request.is_json:
        flash("Локальный черновик Tutor Core сохранён; GigaChat не вызывался.", "success")
        return redirect(url_for("ai_lab.tutor_core_page"), code=303)
    return jsonify({"ok": record.status == "succeeded", "record": result,
                    "error": record.error_message if record.status != "succeeded" else None}), (
                        200 if record.status == "succeeded" else 502
                    )


@ai_lab_bp.post("/api/tutor-core/proposals/<int:proposal_id>/review")
@_admin_required
def tutor_core_review_proposal(proposal_id: int):
    if not is_local_ai_lab_enabled():
        return _code_judge_disabled()
    from app.ai_lab.tutor_core import TutorCoreError, review_tutor_proposal
    payload = request.get_json(silent=True) or request.form
    try:
        record = review_tutor_proposal(int(current_user.id), proposal_id, str(payload.get("decision") or ""))
    except TutorCoreError as exc:
        if not request.is_json:
            flash(f"Предложение не применено: {exc}", "warning")
            return redirect(url_for("ai_lab.tutor_core_page"), code=303)
        return _json_error(str(exc), exc.status_code, exc.code)
    if not request.is_json:
        decision = str((record.input_snapshot or {}).get("decision") or "")
        flash("Предложение принято: изменена только синтетическая копия курса." if decision == "accepted"
              else "Предложение отклонено; курс не изменён.", "success")
        return redirect(url_for("ai_lab.tutor_core_page"), code=303)
    return jsonify({"ok": True, "proposal_id": proposal_id,
                    "decision": (record.input_snapshot or {}).get("decision"),
                    "decision_at": record.created_at.isoformat() if record.created_at else None,
                    "master_course_mutated": False,
                    "course_copy_mutated": bool((record.result_json or {}).get("course_copy_mutated")),
                    "applied_change": (record.result_json or {}).get("applied_change")})


@ai_lab_bp.post("/api/tutor-core/proposals/<int:proposal_id>/assign-diagnostic")
@_admin_required
def tutor_core_assign_diagnostic(proposal_id: int):
    if not is_local_ai_lab_enabled():
        return _code_judge_disabled()
    from app.ai_lab.tutor_core import TutorCoreError, assign_tutor_diagnostic
    try:
        record = assign_tutor_diagnostic(int(current_user.id), proposal_id)
    except TutorCoreError as exc:
        if not request.is_json:
            flash(f"Диагностика не назначена: {exc}", "warning")
            return redirect(url_for("ai_lab.tutor_core_page"), code=303)
        return _json_error(str(exc), exc.status_code, exc.code)
    result = record.result_json or {}
    if not request.is_json:
        flash("Отдельная проверяемая диагностика назначена через домашние работы; учебный план не изменён.", "success")
        return redirect(url_for("ai_lab.tutor_core_page"), code=303)
    return jsonify({"ok": True, "proposal_id": proposal_id,
                    "assignment_id": result.get("assignment_id"),
                    "submission_id": result.get("submission_id"),
                    "task_id": result.get("task_id"),
                    "master_course_mutated": False, "course_copy_mutated": False})


@ai_lab_bp.post("/api/tutor-core/evidence-admissibility-review")
@_admin_required
def tutor_core_review_evidence_admissibility():
    if not is_local_ai_lab_enabled():
        return _code_judge_disabled()
    from app.ai_lab.tutor_core import TutorCoreError, review_tutor_evidence_admissibility
    payload = request.get_json(silent=True) or request.form
    try:
        record = review_tutor_evidence_admissibility(
            actor_id=int(current_user.id),
            profile_id=str(payload.get("profile_id") or ""),
            event_id=str(payload.get("event_id") or ""),
            decision=str(payload.get("decision") or ""),
            reason_code=str(payload.get("reason_code") or ""),
            reason_detail=str(payload.get("reason_detail") or ""),
        )
    except TutorCoreError as exc:
        if not request.is_json:
            flash(f"Пригодность попытки не изменена: {exc}", "warning")
            return redirect(url_for("ai_lab.tutor_core_page"), code=303)
        return _json_error(str(exc), exc.status_code, exc.code)
    result = record.result_json or {}
    if not request.is_json:
        flash("Решение о пригодности сохранено отдельно; исходный ответ и оценка не изменены.", "success")
        return redirect(url_for("ai_lab.tutor_core_page"), code=303)
    return jsonify({"ok": True, "review_id": record.id,
                    "pedagogically_eligible": result.get("pedagogically_eligible"),
                    "source_attempt_and_score_mutated": False,
                    "reviewed_at": record.created_at.isoformat() if record.created_at else None})


@ai_lab_bp.post("/api/tutor-core/decisions/<int:decision_id>/rollback")
@_admin_required
def tutor_core_rollback_decision(decision_id: int):
    if not is_local_ai_lab_enabled():
        return _code_judge_disabled()
    from app.ai_lab.tutor_core import TutorCoreError, rollback_tutor_copy_decision
    try:
        record = rollback_tutor_copy_decision(int(current_user.id), decision_id)
    except TutorCoreError as exc:
        return _json_error(str(exc), exc.status_code, exc.code)
    if not request.is_json:
        flash("Изменение синтетической копии курса восстановлено.", "success")
        return redirect(url_for("ai_lab.tutor_core_page"), code=303)
    return jsonify({"ok": True, "decision_id": decision_id,
                    "rollback_at": record.created_at.isoformat() if record.created_at else None,
                    "restoration": (record.result_json or {}).get("restoration"),
                    "master_course_mutated": False})


def _serialize_module_record(record) -> dict[str, Any]:
    return {
        "id": record.id,
        "status": record.status,
        "scenario_snapshot": record.scenario_snapshot or {},
        "input_snapshot": record.input_snapshot or {},
        "result": record.result_json or {},
        "quality": record.quality_json or {},
        "model": record.model,
        "input_tokens": record.input_tokens,
        "output_tokens": record.output_tokens,
        "duration_ms": record.duration_ms,
        "validation_status": record.validation_status,
        "error_code": record.error_code,
        "error_message": record.error_message,
        "created_at": record.created_at.isoformat() if record.created_at else None,
    }


def _course_source_is_stale(record) -> bool:
    identity = (record.input_snapshot or {}).get("source_identity") or {}
    if identity.get("source_table") != "Courses/LearningTrajectory":
        return False
    latest = export_synthetic_learning_trajectory(int(identity.get("source_course_id") or 0))
    return not latest or latest.get("source_identity", {}).get("content_sha256") != identity.get("content_sha256")


def _serialize_course_record(record) -> dict[str, Any]:
    serialized = _serialize_module_record(record)
    serialized["source_stale"] = _course_source_is_stale(record)
    return serialized


@ai_lab_bp.get("/course")
@_admin_required
def course_page():
    if not is_local_ai_lab_enabled():
        return _code_judge_disabled()
    records = list_course_analyses(current_user.id)
    course_samples = synthetic_course_samples()
    for choice in list_synthetic_learning_trajectories():
        adapted = export_synthetic_learning_trajectory(choice["course_id"])
        if adapted:
            course_samples.append(adapted)
    return render_template("sandbox/ai_lab_course.html", course_samples=course_samples,
                           analyses=records,
                           analysis_source_stale={record.id: _course_source_is_stale(record) for record in records},
                           default_model=provider_settings().get("default_model", "GigaChat-3-Pro"))


@ai_lab_bp.get("/api/course/analyses")
@_admin_required
def course_analyses():
    if not is_local_ai_lab_enabled():
        return _code_judge_disabled()
    return jsonify({"ok": True, "analyses": [_serialize_course_record(item) for item in list_course_analyses(current_user.id)]})


@ai_lab_bp.post("/api/course/analyze")
@_admin_required
def course_analyze():
    if not is_local_ai_lab_enabled():
        return _code_judge_disabled()
    payload = request.get_json(silent=True) or {}
    try:
        record = analyze_course(payload.get("course"), current_user.id)
    except CourseAnalysisError as exc:
        return _json_error(str(exc), exc.status_code, "invalid_course")
    result = _serialize_course_record(record)
    if record.status != "succeeded":
        return jsonify({"ok": False, "error": record.error_message or "AI Course не завершил анализ.",
                        "error_code": record.error_code, "record": result}), 502
    return jsonify({"ok": True, "record": result})


@ai_lab_bp.get("/api/course/analyses/<int:record_id>")
@_admin_required
def course_analysis_detail(record_id: int):
    if not is_local_ai_lab_enabled():
        return _code_judge_disabled()
    record = get_course_analysis(record_id, current_user.id)
    if not record:
        return _json_error("Версия анализа курса не найдена.", 404, "course_analysis_not_found")
    return jsonify({"ok": True, "record": _serialize_course_record(record)})


@ai_lab_bp.post("/api/course/analyses/<int:record_id>/proposals/<proposal_id>/review")
@_admin_required
def course_proposal_review(record_id: int, proposal_id: str):
    if not is_local_ai_lab_enabled():
        return _code_judge_disabled()
    record = get_course_analysis(record_id, current_user.id)
    if not record:
        return _json_error("Версия анализа курса не найдена.", 404, "course_analysis_not_found")
    if _course_source_is_stale(record):
        return _json_error("Источник курса изменился после анализа. Создайте новый анализ версии; старую ссылку нельзя принять как актуальную.",
                           409, "stale_course_source")
    payload = request.get_json(silent=True) or {}
    try:
        record = review_course_proposal(record, proposal_id, payload.get("decision"), current_user.id,
                                        str(payload.get("note") or ""),
                                        str(payload.get("proposed_text")) if payload.get("proposed_text") is not None else None)
    except CourseAnalysisError as exc:
        return _json_error(str(exc), exc.status_code, "invalid_proposal_review")
    return jsonify({"ok": True, "record": _serialize_course_record(record)})


@ai_lab_bp.post("/api/course/analyses/<int:record_id>/proposals/<proposal_id>/rollback")
@_admin_required
def course_proposal_rollback(record_id: int, proposal_id: str):
    if not is_local_ai_lab_enabled():
        return _code_judge_disabled()
    record = get_course_analysis(record_id, current_user.id)
    if not record:
        return _json_error("Версия анализа курса не найдена.", 404, "course_analysis_not_found")
    try:
        record = rollback_course_proposal(record, proposal_id, current_user.id)
    except CourseAnalysisError as exc:
        return _json_error(str(exc), exc.status_code, "course_proposal_rollback_failed")
    return jsonify({"ok": True, "record": _serialize_course_record(record)})


@ai_lab_bp.get("/lesson-intelligence")
@_admin_required
def lesson_intelligence_page():
    if not is_local_ai_lab_enabled():
        return _code_judge_disabled()
    return render_template("sandbox/ai_lab_lesson_intelligence.html", transcript_samples=synthetic_transcript_samples(),
                           lesson_sources=list_synthetic_lesson_sources(),
                           analyses=list_lesson_analyses(current_user.id),
                           default_model=provider_settings().get("default_model", "GigaChat-3-Pro"))


@ai_lab_bp.get("/api/lesson-intelligence/analyses")
@_admin_required
def lesson_intelligence_analyses():
    if not is_local_ai_lab_enabled():
        return _code_judge_disabled()
    return jsonify({"ok": True, "analyses": [_serialize_module_record(item) for item in list_lesson_analyses(current_user.id)]})


@ai_lab_bp.post("/api/lesson-intelligence/analyze")
@_admin_required
def lesson_intelligence_analyze():
    if not is_local_ai_lab_enabled():
        return _code_judge_disabled()
    try:
        record = analyze_lesson(request.get_json(silent=True) or {}, current_user.id)
    except LessonAnalysisError as exc:
        return _json_error(str(exc), exc.status_code, "invalid_lesson_transcript")
    result = _serialize_module_record(record)
    if record.status != "succeeded":
        return jsonify({"ok": False, "error": record.error_message or "AI Lesson Intelligence не завершил анализ.",
                        "error_code": record.error_code, "record": result}), 502
    return jsonify({"ok": True, "record": result})


@ai_lab_bp.post("/api/lesson-intelligence/analyses/<int:record_id>/resume")
@_admin_required
def lesson_intelligence_resume(record_id: int):
    if not is_local_ai_lab_enabled():
        return _code_judge_disabled()
    try:
        record = analyze_lesson({}, current_user.id, resume_record_id=record_id)
    except LessonAnalysisError as exc:
        return _json_error(str(exc), exc.status_code, "lesson_analysis_resume_failed")
    result = _serialize_module_record(record)
    if record.status != "succeeded":
        return jsonify({"ok": False, "error": record.error_message or "AI Lesson Intelligence не завершил анализ.",
                        "error_code": record.error_code, "record": result}), 502
    return jsonify({"ok": True, "record": result})


@ai_lab_bp.get("/api/lesson-intelligence/analyses/<int:record_id>")
@_admin_required
def lesson_intelligence_detail(record_id: int):
    if not is_local_ai_lab_enabled():
        return _code_judge_disabled()
    record = get_lesson_analysis(record_id, current_user.id)
    if not record:
        return _json_error("Версия анализа урока не найдена.", 404, "lesson_analysis_not_found")
    return jsonify({"ok": True, "record": _serialize_module_record(record)})


@ai_lab_bp.post("/api/lesson-intelligence/analyses/<int:record_id>/observations/<observation_id>/review")
@_admin_required
def lesson_observation_review(record_id: int, observation_id: str):
    if not is_local_ai_lab_enabled():
        return _code_judge_disabled()
    record = get_lesson_analysis(record_id, current_user.id)
    if not record:
        return _json_error("Версия анализа урока не найдена.", 404, "lesson_analysis_not_found")
    payload = request.get_json(silent=True) or {}
    try:
        record = review_lesson_observation(record, observation_id, payload.get("decision"), current_user.id,
                                           str(payload.get("note") or ""))
    except LessonAnalysisError as exc:
        return _json_error(str(exc), exc.status_code, "invalid_observation_review")
    return jsonify({"ok": True, "record": _serialize_module_record(record)})


@ai_lab_bp.post("/api/lesson-intelligence/analyses/<int:record_id>/observations/batch-review")
@_admin_required
def lesson_observations_batch_review(record_id: int):
    if not is_local_ai_lab_enabled():
        return _code_judge_disabled()
    record = get_lesson_analysis(record_id, current_user.id)
    if not record:
        return _json_error("Версия анализа урока не найдена.", 404, "lesson_analysis_not_found")
    payload = request.get_json(silent=True) or {}
    try:
        record = review_lesson_observations(record, payload.get("observation_ids"), payload.get("decision"),
                                            current_user.id, str(payload.get("note") or ""))
    except LessonAnalysisError as exc:
        return _json_error(str(exc), exc.status_code, "invalid_observation_review")
    return jsonify({"ok": True, "record": _serialize_module_record(record)})


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


@ai_lab_bp.get("/api/code-judge/platform-tasks")
@_admin_required
def code_judge_platform_tasks():
    if not is_local_ai_lab_enabled():
        return _code_judge_disabled()
    if not platform_homework_enabled(int(current_user.id)):
        return _json_error("Платформенная интеграция не включена для этого локального пилотного аккаунта.", 403, "platform_pilot_disabled")
    return jsonify({"ok": True, "tasks": list_linkable_tasks(int(current_user.id))})


@ai_lab_bp.post("/api/code-judge/test-sets/<int:test_set_id>/platform-task")
@_admin_required
def code_judge_link_platform_task(test_set_id: int):
    if not is_local_ai_lab_enabled():
        return _code_judge_disabled()
    payload = request.get_json(silent=True) or {}
    try:
        task_id = int(payload.get("task_id"))
        binding = link_test_set_to_task(int(current_user.id), task_id, test_set_id)
    except (TypeError, ValueError):
        return _json_error("Укажите корректный идентификатор задания BooStudy.", 400, "invalid_platform_task")
    except CodeJudgeError as exc:
        return _json_error(str(exc), exc.status, exc.code)
    except Exception:
        current_app.logger.exception("Code Judge test set could not be linked to a platform task")
        return _json_error("Не удалось сохранить связь с заданием BooStudy.", 500, "platform_task_link_failed")
    return jsonify({"ok": True, "binding": binding})


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
