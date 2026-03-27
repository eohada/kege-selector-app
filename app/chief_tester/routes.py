from __future__ import annotations

from datetime import datetime

from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import or_

from app.chief_tester import chief_tester_bp
from app.models import QATask, User, UserRole, db


def _is_allowed() -> bool:
    return bool(
        getattr(current_user, "is_authenticated", False)
        and (current_user.is_chief_tester() or current_user.is_creator())
    )


def _require_allowed():
    if not _is_allowed():
        abort(403)


def _get_testers():
    q = (
        User.query.join(UserRole, UserRole.user_id == User.id, isouter=True)
        .filter(or_(User.role.in_(["tester", "chief_tester"]), UserRole.role.in_(["tester", "chief_tester"])))
        .distinct()
        .order_by(User.username.asc())
    )
    return q.all()


@chief_tester_bp.route("/")
@chief_tester_bp.route("/dashboard")
@login_required
def dashboard():
    _require_allowed()

    tasks = (
        QATask.query.filter(QATask.task_type == "task")
        .order_by(QATask.created_at.desc())
        .limit(200)
        .all()
    )
    stats = {
        "todo": sum(1 for t in tasks if t.status == "todo"),
        "in_progress": sum(1 for t in tasks if t.status == "in_progress"),
        "review": sum(1 for t in tasks if t.status == "review"),
        "done": sum(1 for t in tasks if t.status == "done"),
        "total": len(tasks),
    }
    return render_template("chief_tester/dashboard.html", stats=stats)


@chief_tester_bp.route("/tasks")
@login_required
def tasks_list():
    _require_allowed()

    status = (request.args.get("status") or "").strip()
    q = (request.args.get("q") or "").strip()
    assignee_id = request.args.get("assignee_id", type=int)

    tasks_q = QATask.query.filter(QATask.task_type == "task")
    if status in ("todo", "in_progress", "review", "done"):
        tasks_q = tasks_q.filter(QATask.status == status)
    if q:
        tasks_q = tasks_q.filter(QATask.title.ilike(f"%{q}%"))
    tasks = tasks_q.order_by(QATask.created_at.desc()).limit(800).all()
    if assignee_id:
        tasks = [
            t
            for t in tasks
            if (t.assignee_id == assignee_id)
            or (isinstance(getattr(t, "assignee_ids", None), list) and assignee_id in (t.assignee_ids or []))
        ]

    testers = _get_testers()
    assignee_ids = set()
    for t in tasks:
        if getattr(t, "assignee_ids", None) and isinstance(t.assignee_ids, list):
            assignee_ids.update(x for x in t.assignee_ids if x)
        elif getattr(t, "assignee_id", None):
            assignee_ids.add(t.assignee_id)
    assignee_map = {u.id: u for u in User.query.filter(User.id.in_(assignee_ids)).all()} if assignee_ids else {}

    return render_template(
        "chief_tester/tasks.html",
        tasks=tasks,
        testers=testers,
        assignee_map=assignee_map,
        filters={"status": status, "q": q, "assignee_id": assignee_id},
    )


@chief_tester_bp.route("/tasks/new", methods=["GET", "POST"])
@login_required
def task_new():
    _require_allowed()
    testers = _get_testers()

    if request.method == "POST":
        title = (request.form.get("title") or "").strip()
        description = (request.form.get("description") or "").strip() or None
        priority = (request.form.get("priority") or "medium").strip()
        deadline_raw = (request.form.get("deadline") or "").strip()
        context_url = (request.form.get("context_url") or "").strip() or None

        assignee_ids = request.form.getlist("assignee_ids")
        assignee_ids_int = [int(x) for x in assignee_ids if str(x).isdigit()]

        deadline = None
        if deadline_raw:
            try:
                deadline = datetime.fromisoformat(deadline_raw)
            except Exception:
                deadline = None

        if not title:
            flash("Укажите заголовок задачи", "error")
            form = {
                "title": request.form.get("title") or "",
                "description": request.form.get("description") or "",
                "status": request.form.get("status") or "todo",
                "priority": request.form.get("priority") or "medium",
                "deadline": request.form.get("deadline") or "",
                "context_url": request.form.get("context_url") or "",
                "assignee_ids": assignee_ids_int,
            }
            return render_template("chief_tester/task_form.html", testers=testers, task=None, form=form)

        task = QATask(
            title=title,
            description=description,
            task_type="task",
            status="todo",
            priority=priority if priority in ("low", "medium", "high", "critical") else "medium",
            reporter_id=current_user.id,
            assignee_id=assignee_ids_int[0] if assignee_ids_int else None,
            assignee_ids=assignee_ids_int or [],
            deadline=deadline,
            context_url=context_url,
        )
        db.session.add(task)
        db.session.commit()
        flash("Задача создана", "success")
        return redirect(url_for("chief_tester.tasks_list"))

    return render_template("chief_tester/task_form.html", testers=testers, task=None, form={})


@chief_tester_bp.route("/tasks/<int:task_id>/edit", methods=["GET", "POST"])
@login_required
def task_edit(task_id: int):
    _require_allowed()
    testers = _get_testers()
    task = QATask.query.get_or_404(task_id)
    if task.task_type != "task":
        abort(404)

    if request.method == "POST":
        title = (request.form.get("title") or "").strip()
        description = (request.form.get("description") or "").strip() or None
        priority = (request.form.get("priority") or "medium").strip()
        status = (request.form.get("status") or task.status or "todo").strip()
        deadline_raw = (request.form.get("deadline") or "").strip()
        context_url = (request.form.get("context_url") or "").strip() or None

        assignee_ids = request.form.getlist("assignee_ids")
        assignee_ids_int = [int(x) for x in assignee_ids if str(x).isdigit()]

        deadline = None
        if deadline_raw:
            try:
                deadline = datetime.fromisoformat(deadline_raw)
            except Exception:
                deadline = None

        if not title:
            flash("Укажите заголовок задачи", "error")
            form = {
                "title": request.form.get("title") or "",
                "description": request.form.get("description") or "",
                "status": request.form.get("status") or (task.status or "todo"),
                "priority": request.form.get("priority") or (task.priority or "medium"),
                "deadline": request.form.get("deadline") or "",
                "context_url": request.form.get("context_url") or "",
                "assignee_ids": assignee_ids_int,
            }
            return render_template("chief_tester/task_form.html", testers=testers, task=task, form=form)

        task.title = title
        task.description = description
        task.priority = priority if priority in ("low", "medium", "high", "critical") else "medium"
        task.status = status if status in ("todo", "in_progress", "review", "done") else "todo"
        task.deadline = deadline
        task.context_url = context_url
        task.assignee_ids = assignee_ids_int or []
        task.assignee_id = assignee_ids_int[0] if assignee_ids_int else None

        db.session.commit()
        flash("Задача обновлена", "success")
        return redirect(url_for("chief_tester.tasks_list"))

    form = {
        "title": task.title,
        "description": task.description or "",
        "priority": task.priority or "medium",
        "status": task.status or "todo",
        "deadline": (task.deadline.isoformat(timespec="minutes") if task.deadline else ""),
        "context_url": task.context_url or "",
        "assignee_ids": task.assignee_ids or ([task.assignee_id] if task.assignee_id else []),
    }
    return render_template("chief_tester/task_form.html", testers=testers, task=task, form=form)


@chief_tester_bp.route("/tasks/<int:task_id>/delete", methods=["POST"])
@login_required
def task_delete(task_id: int):
    _require_allowed()
    task = QATask.query.get_or_404(task_id)
    if task.task_type != "task":
        abort(404)
    db.session.delete(task)
    db.session.commit()
    flash("Задача удалена", "success")
    return redirect(url_for("chief_tester.tasks_list"))


@chief_tester_bp.route("/testers")
@login_required
def testers():
    _require_allowed()
    testers_list = _get_testers()
    return render_template("chief_tester/testers.html", testers_list=testers_list)


@chief_tester_bp.route("/testers/<int:user_id>/toggle-active", methods=["POST"])
@login_required
def tester_toggle_active(user_id: int):
    _require_allowed()
    u = User.query.get_or_404(user_id)
    if not (u.is_tester() or u.is_chief_tester()):
        flash("Пользователь не является тестировщиком", "error")
        return redirect(url_for("chief_tester.testers"))
    u.is_active = not bool(u.is_active)
    db.session.commit()
    flash(f"Тестер {u.username}: {'активен' if u.is_active else 'отключён'}", "success")
    return redirect(url_for("chief_tester.testers"))

