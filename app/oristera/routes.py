"""
Маршруты Project Oristera Next Generation.
"""
from __future__ import annotations

import logging
from flask import (
    Blueprint,
    render_template,
    redirect,
    url_for,
    request,
    session,
    jsonify,
    make_response,
    abort,
)
from flask_login import login_required, current_user

from app.models import db, User, Lesson, Student, Assignment
from app.auth.rbac_utils import get_active_role
from app.limiter import limiter
from app.oristera.config import is_oristera_enabled, get_ui_mode, set_ui_mode
from app.oristera.adapters.student_adapter import get_student_nexus_data
from app.oristera.adapters.teacher_adapter import get_teacher_studio_data
from app.oristera.adapters.parent_adapter import get_parent_nexus_data
from app.oristera.adapters.tutor_core_adapter import get_student_skills_atlas
from app.sandbox.python_runner import run_python_sandbox

logger = logging.getLogger(__name__)

oristera_bp = Blueprint("oristera", __name__, url_prefix="/oristera")


@oristera_bp.before_request
def _check_oristera_access():
    if not is_oristera_enabled():
        # Если Oristera выключена флагом, безопасно возвращаем в Classic
        return redirect(url_for("main.dashboard"))


@oristera_bp.route("/toggle", methods=["GET", "POST"])
def toggle_mode():
    """Безопасный переключатель между Classic и Oristera Next."""
    current_mode = get_ui_mode()
    target_mode = request.args.get("to")
    if not target_mode:
        target_mode = "classic" if current_mode == "oristera" else "oristera"

    set_ui_mode(target_mode)

    return_to = request.args.get("return_to")
    if target_mode == "oristera":
        dest = return_to if (return_to and return_to.startswith("/oristera")) else url_for("oristera.nexus")
    else:
        dest = return_to if (return_to and not return_to.startswith("/oristera")) else url_for("main.dashboard")

    response = make_response(redirect(dest))
    response.set_cookie(
        "boostudy_ui_mode",
        target_mode,
        max_age=30 * 86400,
        samesite="Lax",
        path="/"
    )
    return response


@oristera_bp.route("/")
@oristera_bp.route("/nexus")
@login_required
def nexus():
    """Живой Nexus — гравитационный центр вселенной обучения."""
    set_ui_mode("oristera")
    active_role = get_active_role()

    if active_role in ("teacher", "tutor"):
        data = get_teacher_studio_data(current_user)
        return render_template("oristera/teacher_studio.html", active_space="studio", **data)

    if active_role == "parent":
        data = get_parent_nexus_data(current_user)
        return render_template("oristera/parent_nexus.html", active_space="parent", **data)

    # По умолчанию и для роли student — Student Nexus
    data = get_student_nexus_data(current_user)
    return render_template("oristera/nexus.html", active_space="nexus", **data)


@oristera_bp.route("/atlas")
@login_required
def atlas():
    """Atlas — живая карта созвездий знаний и подтверждённых навыков."""
    set_ui_mode("oristera")
    constellations = get_student_skills_atlas(current_user.id)
    return render_template(
        "oristera/atlas.html",
        active_space="atlas",
        user=current_user,
        constellations=constellations,
    )


@oristera_bp.route("/practice")
@login_required
def practice():
    """Practice Space — пространство самостоятельной работы и кода."""
    set_ui_mode("oristera")
    student_data = get_student_nexus_data(current_user)
    return render_template(
        "oristera/practice.html",
        active_space="practice",
        **student_data
    )


@oristera_bp.route("/api/practice/run", methods=["POST"])
@login_required
@limiter.limit("40/minute")
def practice_run_code():
    """Run standalone student practice in BooStudy's isolated Python sandbox."""
    if not current_user.is_student():
        abort(403)

    data = request.get_json(silent=True) or {}
    code = data.get("code")
    if not isinstance(code, str) or not code.strip():
        return jsonify({"success": False, "error": "Введите Python-код для выполнения."}), 400
    if len(code) > 100_000:
        return jsonify({"success": False, "error": "Код превышает допустимый размер."}), 413

    stdout, stderr, turtle_image = run_python_sandbox(code, timeout_sec=5)
    return jsonify({
        "success": True,
        "stdout": stdout,
        "stderr": stderr,
        "turtle_image_b64": turtle_image,
    })


@oristera_bp.route("/lessons")
@login_required
def lessons_space():
    """Learning Space — образовательный маршрут и расписание."""
    set_ui_mode("oristera")
    student_data = get_student_nexus_data(current_user)
    return render_template(
        "oristera/lessons_space.html",
        active_space="lessons",
        **student_data
    )


@oristera_bp.route("/lesson/<int:lesson_id>/prep")
@login_required
def lesson_prep(lesson_id: int):
    """
    Lesson Prep Space — пространство подготовки и погружения в занятие.
    Служит мостом в существующую BooStudy OS.
    """
    set_ui_mode("oristera")
    lesson = Lesson.query.options(
        db.joinedload(Lesson.student),
    ).get_or_404(lesson_id)

    student = lesson.student
    teacher = None
    if student and getattr(student, "mentor_id", None):
        teacher = db.session.get(User, student.mentor_id)

    # Проверяем материалы
    materials = lesson.materials or []
    if isinstance(materials, str):
        try:
            import json
            materials = json.loads(materials)
        except Exception:
            materials = []

    return render_template(
        "oristera/lesson_prep.html",
        active_space="lessons",
        lesson=lesson,
        student=student,
        teacher=teacher,
        materials=materials,
        user=current_user,
    )


@oristera_bp.route("/teacher")
@login_required
def teacher_studio():
    """Прямой доступ к Teacher Studio для преподавателей и администраторов."""
    set_ui_mode("oristera")
    data = get_teacher_studio_data(current_user)
    return render_template("oristera/teacher_studio.html", active_space="studio", **data)


@oristera_bp.route("/parent")
@login_required
def parent_nexus():
    """Прямой доступ к Parent Nexus."""
    set_ui_mode("oristera")
    data = get_parent_nexus_data(current_user)
    return render_template("oristera/parent_nexus.html", active_space="parent", **data)


@oristera_bp.route("/api/state")
@login_required
def api_state():
    """Реактивное состояние Continuum для интерфейса."""
    active_role = get_active_role()
    return jsonify({
        "ok": True,
        "mode": get_ui_mode(),
        "user_id": current_user.id,
        "username": current_user.username,
        "role": active_role,
        "is_impersonated": bool(session.get("impersonator_id")),
    })
