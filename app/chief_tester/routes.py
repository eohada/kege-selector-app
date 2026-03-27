from __future__ import annotations

import json
import os
from datetime import datetime, timedelta

from flask import abort, current_app, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import func, or_

from app.chief_tester import chief_tester_bp
from app.models import Student, User, UserRole, db
from core.db_models import QATask


def _is_allowed() -> bool:
    return bool(
        getattr(current_user, "is_authenticated", False)
        and (current_user.is_chief_tester() or current_user.is_creator())
    )


def _require_allowed():
    if not _is_allowed():
        abort(403)


def _get_testers():
    try:
        # Postgres may fail DISTINCT over full Users row because it contains JSON fields.
        # Fetch unique user IDs first, then load users by IDs.
        id_rows = (
            db.session.query(User.id)
            .join(UserRole, UserRole.user_id == User.id, isouter=True)
            .filter(or_(User.role.in_(["tester", "chief_tester"]), UserRole.role.in_(["tester", "chief_tester"])))
            .distinct()
            .all()
        )
        ids = [r[0] for r in id_rows if r and r[0]]
        if not ids:
            return []
        return User.query.filter(User.id.in_(ids)).order_by(User.username.asc()).all()
    except Exception:
        # Clear failed transaction state before any fallback query.
        try:
            db.session.rollback()
        except Exception:
            pass
        # Fallback for legacy DB states where user_roles table/data is inconsistent.
        current_app.logger.exception("chief_tester._get_testers failed, using role-only fallback")
        return (
            User.query.filter(User.role.in_(["tester", "chief_tester"]))
            .order_by(User.username.asc())
            .all()
        )


def _status_label(status: str | None) -> str:
    mapping = {
        "todo": "To Do",
        "in_progress": "In Progress",
        "review": "QA Review",
        "done": "Done",
    }
    return mapping.get((status or "").strip().lower(), status or "To Do")


def _priority_label(priority: str | None) -> str:
    mapping = {
        "low": "Low",
        "medium": "Medium",
        "high": "High",
        "critical": "Critical",
    }
    return mapping.get((priority or "").strip().lower(), priority or "Medium")


def _priority_badge(priority: str | None) -> tuple[str, str]:
    p = (priority or "medium").strip().lower()
    if p == "critical":
        return "bg-red-100 text-red-600", "Critical"
    if p == "high":
        return "bg-orange-100 text-orange-600", "High"
    if p == "low":
        return "bg-blue-100 text-blue-700", "Low"
    return "bg-slate-100 text-slate-600", "Medium"


def _read_log_tail(max_lines: int = 120) -> tuple[list[str], str]:
    max_lines = max(20, min(int(max_lines or 120), 500))
    try:
        root = os.path.abspath(current_app.root_path)
        log_path = os.path.abspath(os.path.join(root, "..", "logs", "app.log"))
        if not log_path.endswith(os.path.join("logs", "app.log")):
            return [], "invalid_path"
        if not os.path.exists(log_path):
            return [], "missing"

        chunk_size = 8192
        with open(log_path, "rb") as f:
            f.seek(0, os.SEEK_END)
            file_size = f.tell()
            data = b""
            pos = file_size
            while pos > 0 and data.count(b"\n") <= (max_lines + 2):
                read_size = min(chunk_size, pos)
                pos -= read_size
                f.seek(pos)
                data = f.read(read_size) + data
                if len(data) > (2 * 1024 * 1024):
                    break

        lines = data.decode("utf-8", errors="replace").splitlines()
        return lines[-max_lines:], "ok"
    except Exception:
        return [], "error"


def _status_text(value) -> str:
    if value is None:
        return "unknown"
    if isinstance(value, bool):
        return "success" if value else "failed"
    if isinstance(value, int):
        if 200 <= value < 400:
            return "success"
        if value >= 500:
            return "error"
        if value >= 400:
            return "failed"
        return str(value)
    s = str(value).strip()
    if not s:
        return "unknown"
    return s


def _action_text(event: str | None, method: str | None, url: str | None, message: str | None) -> str:
    e = (event or "").strip()
    if e == "http_request":
        return f"{(method or 'REQUEST').upper()} {(url or '/')}"
    if e:
        return e
    return (message or "action").strip()


def _parse_log_line(line: str) -> dict | None:
    try:
        obj = json.loads(line)
    except Exception:
        return None
    if not isinstance(obj, dict):
        return None

    actor = "system"
    user_id = obj.get("user_id")
    role = obj.get("role")
    if user_id:
        actor = f"user#{user_id}{f' ({role})' if role else ''}"
    elif role:
        actor = f"role:{role}"

    event = obj.get("event")
    method = obj.get("method")
    url = obj.get("url")
    message = obj.get("message")
    action = _action_text(event, method, url, message)
    status = _status_text(obj.get("status"))
    ts = obj.get("timestamp") or ""

    return {
        "ts": ts,
        "actor": actor,
        "action": action,
        "page": url or "-",
        "result": status,
        "request_id": obj.get("request_id"),
        "method": method,
        "url": url,
        "event": event,
        "message": message,
        "raw": line,
    }


def _iter_assignee_ids(task: QATask) -> list[int]:
    raw = getattr(task, "assignee_ids", None)
    ids: list[int] = []
    if isinstance(raw, list):
        for x in raw:
            if isinstance(x, int):
                ids.append(x)
            elif isinstance(x, str) and x.isdigit():
                ids.append(int(x))
    elif isinstance(raw, int):
        ids.append(raw)
    elif isinstance(raw, str) and raw.isdigit():
        ids.append(int(raw))

    single = getattr(task, "assignee_id", None)
    if isinstance(single, int):
        ids.append(single)
    elif isinstance(single, str) and single.isdigit():
        ids.append(int(single))

    return sorted(set(i for i in ids if i))


def _count_bugs_done_last_7d(bug_reports: list[QATask]) -> int:
    # Compare in Python with timezone-safe normalization to tolerate mixed legacy rows.
    cutoff = (datetime.utcnow() - timedelta(days=7)).replace(tzinfo=None)
    total = 0
    for b in bug_reports:
        if (b.status or "").strip().lower() != "done":
            continue
        created = getattr(b, "created_at", None)
        if not created:
            continue
        created_naive = created.replace(tzinfo=None) if getattr(created, "tzinfo", None) else created
        if created_naive >= cutoff:
            total += 1
    return total


@chief_tester_bp.route("/")
@chief_tester_bp.route("/dashboard")
@login_required
def dashboard():
    _require_allowed()
    requested_tab = (request.args.get("tab") or "dashboard").strip().lower()
    initial_tab = requested_tab if requested_tab in {"dashboard", "tasks", "team", "logs"} else "dashboard"
    try:
        tasks = (
            QATask.query.filter(QATask.task_type == "task")
            .order_by(QATask.created_at.desc())
            .limit(600)
            .all()
        )
        bug_reports = (
            QATask.query.filter(QATask.task_type == "bug_report")
            .order_by(QATask.created_at.desc())
            .limit(120)
            .all()
        )

        stats = {
            "todo": sum(1 for t in tasks if (t.status or "todo") == "todo"),
            "in_progress": sum(1 for t in tasks if (t.status or "") == "in_progress"),
            "review": sum(1 for t in tasks if (t.status or "") == "review"),
            "done": sum(1 for t in tasks if (t.status or "") == "done"),
            "total": len(tasks),
            "critical": sum(1 for t in tasks if (t.priority or "") == "critical"),
            "bugs_open": sum(1 for b in bug_reports if (b.status or "new") in ("new", "in_progress", "review")),
            "bugs_done_7d": _count_bugs_done_last_7d(bug_reports),
        }

        testers = _get_testers()
        assignee_ids = set()
        for t in tasks:
            assignee_ids.update(_iter_assignee_ids(t))
        assignee_map = {u.id: u for u in User.query.filter(User.id.in_(assignee_ids)).all()} if assignee_ids else {}

        task_cards = []
        columns = {"todo": [], "in_progress": [], "review": [], "done": []}
        for t in tasks[:240]:
            badge_cls, prio_text = _priority_badge(t.priority)
            item = {
                "id": t.id,
                "title": t.title,
                "status": (t.status or "todo"),
                "status_label": _status_label(t.status),
                "priority": (t.priority or "medium"),
                "priority_label": _priority_label(t.priority),
                "priority_badge_cls": badge_cls,
                "priority_badge_text": prio_text,
                "context_url": t.context_url,
                "created_at": t.created_at,
                "assignees": [assignee_map[aid] for aid in _iter_assignee_ids(t) if aid in assignee_map],
            }
            task_cards.append(item)
            if item["status"] in columns:
                columns[item["status"]].append(item)

        activity = []
        recent_bugs = (
            QATask.query.filter(QATask.task_type == "bug_report")
            .order_by(QATask.created_at.desc())
            .limit(12)
            .all()
        )
        for b in recent_bugs:
            reporter_name = getattr(getattr(b, "reporter", None), "username", None) or "Unknown"
            sev = _priority_label(b.priority)
            activity.append(
                {
                    "title": b.title or f"BUG #{b.id}",
                    "tag": sev,
                    "status": _status_label(b.status or "new"),
                    "reporter": reporter_name,
                    "created_at": b.created_at,
                    "code": f"#BUG-{b.id}",
                }
            )

        workloads = []
        for u in testers:
            in_work = sum(
                1
                for t in tasks
                if (t.status or "") in ("todo", "in_progress", "review")
                and (
                    u.id in _iter_assignee_ids(t)
                )
            )
            done = sum(
                1
                for t in tasks
                if (t.status or "") == "done"
                and (
                    u.id in _iter_assignee_ids(t)
                )
            )
            workloads.append(
                {
                    "user": u,
                    "in_work": in_work,
                    "done": done,
                    "efficiency": "Высокая" if done >= max(1, in_work) else ("Средняя" if done > 0 else "Низкая"),
                }
            )
    except Exception:
        current_app.logger.exception("chief_tester.dashboard failed")
        flash("Раздел QA временно недоступен: данные повреждены или не синхронизированы. Показываю безопасный режим.", "error")
        stats = {
            "todo": 0,
            "in_progress": 0,
            "review": 0,
            "done": 0,
            "total": 0,
            "critical": 0,
            "bugs_open": 0,
            "bugs_done_7d": 0,
        }
        task_cards = []
        columns = {"todo": [], "in_progress": [], "review": [], "done": []}
        activity = []
        testers = _get_testers()
        workloads = []

    return render_template(
        "chief_tester/main_tester_cabinet.html",
        stats=stats,
        task_cards=task_cards,
        task_columns=columns,
        activity=activity,
        testers=testers,
        workloads=workloads,
        initial_tab=initial_tab,
    )


@chief_tester_bp.route("/logs/tail")
@login_required
def logs_tail():
    _require_allowed()
    lines_limit = request.args.get("lines", type=int) or 120
    lines, state = _read_log_tail(max_lines=lines_limit)
    return jsonify({"ok": state == "ok", "state": state, "lines": lines, "line_count": len(lines)})


@chief_tester_bp.route("/logs/feed")
@login_required
def logs_feed():
    _require_allowed()
    lines_limit = request.args.get("lines", type=int) or 200
    lines, state = _read_log_tail(max_lines=lines_limit)
    entries = []
    for ln in lines:
        parsed = _parse_log_line(ln)
        if parsed:
            entries.append(parsed)
    return jsonify(
        {
            "ok": state == "ok",
            "state": state,
            "entries": entries[-lines_limit:],
            "entry_count": len(entries),
            "line_count": len(lines),
        }
    )


@chief_tester_bp.route("/users/search")
@login_required
def users_search():
    _require_allowed()
    q = (request.args.get("q") or "").strip()
    if len(q) < 1:
        return jsonify({"items": []})

    users_q = User.query
    if q.isdigit():
        users_q = users_q.filter(User.id == int(q))
    else:
        like = f"%{q}%"
        users_q = users_q.filter(or_(User.username.ilike(like), User.email.ilike(like)))

    users = users_q.order_by(User.id.desc()).limit(20).all()
    user_ids = [u.id for u in users]
    student_rows = Student.query.filter(Student.user_id.in_(user_ids)).all() if user_ids else []
    student_map = {s.user_id: s for s in student_rows}

    items = []
    for u in users:
        s = student_map.get(u.id)
        role = u.role or (u.roles()[0] if u.roles() else "unknown")
        items.append(
            {
                "id": u.id,
                "username": u.username,
                "email": u.email,
                "role": role,
                "student_id": getattr(s, "student_id", None),
                "student_name": getattr(s, "name", None),
            }
        )
    return jsonify({"items": items})


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

