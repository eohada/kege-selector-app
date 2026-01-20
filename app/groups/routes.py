from __future__ import annotations

import logging

from flask import render_template, request, redirect, url_for, flash, abort
from flask_login import login_required, current_user

from app.groups import groups_bp
from app.models import db, SchoolGroup, GroupStudent, Student
from app.auth.rbac_utils import has_permission, get_user_scope

logger = logging.getLogger(__name__)


def _guard_groups_view():
    if not has_permission(current_user, 'groups.view'):
        abort(403)


def _guard_groups_manage():
    if not has_permission(current_user, 'groups.manage'):
        abort(403)


def _can_access_student_id(student_id: int) -> bool:
    scope = get_user_scope(current_user)
    if scope.get('can_see_all'):
        return True
    # scope.student_ids содержит User.id учеников, но у нас группы на Student.student_id.
    # Делаем мягкий fallback: разрешаем тьютору управлять только своими активными Students
    # по прямому совпадению student_id (в окружениях, где Student.student_id == User.id).
    try:
        return student_id in (scope.get('student_ids') or [])
    except Exception:
        return False


def _filter_students_query(q):
    scope = get_user_scope(current_user)
    if scope.get('can_see_all'):
        return q
    ids = scope.get('student_ids') or []
    if not ids:
        return q.filter(False)
    return q.filter(Student.student_id.in_(ids))


@groups_bp.route('/groups')
@login_required
def groups_list():
    _guard_groups_view()
    q = SchoolGroup.query.order_by(SchoolGroup.updated_at.desc(), SchoolGroup.created_at.desc())
    groups = q.all()
    return render_template('groups_list.html', groups=groups)


@groups_bp.route('/groups/new', methods=['GET', 'POST'])
@login_required
def group_new():
    _guard_groups_manage()
    if request.method == 'POST':
        title = (request.form.get('title') or '').strip()
        if not title:
            flash('Название группы обязательно.', 'danger')
            return redirect(url_for('groups.group_new'))

        group = SchoolGroup(
            title=title,
            subject=(request.form.get('subject') or '').strip() or None,
            description=(request.form.get('description') or '').strip() or None,
            status=(request.form.get('status') or 'active').strip().lower() or 'active',
            owner_user_id=current_user.id,
        )
        if group.status not in ('active', 'archived'):
            group.status = 'active'
        db.session.add(group)
        db.session.commit()
        flash('Группа создана.', 'success')
        return redirect(url_for('groups.group_view', group_id=group.group_id))

    return render_template('group_form.html', is_new=True, group=None)


@groups_bp.route('/groups/<int:group_id>')
@login_required
def group_view(group_id: int):
    _guard_groups_view()
    group = SchoolGroup.query.get_or_404(group_id)
    members = GroupStudent.query.filter_by(group_id=group.group_id).join(Student, Student.student_id == GroupStudent.student_id).order_by(Student.name.asc()).all()

    can_manage = has_permission(current_user, 'groups.manage')

    available_students = []
    if can_manage:
        q = Student.query.filter_by(is_active=True).order_by(Student.name.asc())
        q = _filter_students_query(q)
        available_students = q.all()

    return render_template('group_view.html', group=group, members=members, can_manage=can_manage, available_students=available_students)


@groups_bp.route('/groups/<int:group_id>/edit', methods=['GET', 'POST'])
@login_required
def group_edit(group_id: int):
    _guard_groups_manage()
    group = SchoolGroup.query.get_or_404(group_id)
    if request.method == 'POST':
        title = (request.form.get('title') or '').strip()
        if not title:
            flash('Название группы обязательно.', 'danger')
            return redirect(url_for('groups.group_edit', group_id=group.group_id))

        group.title = title
        group.subject = (request.form.get('subject') or '').strip() or None
        group.description = (request.form.get('description') or '').strip() or None
        status = (request.form.get('status') or 'active').strip().lower()
        group.status = status if status in ('active', 'archived') else 'active'
        db.session.commit()
        flash('Группа обновлена.', 'success')
        return redirect(url_for('groups.group_view', group_id=group.group_id))

    return render_template('group_form.html', is_new=False, group=group)


@groups_bp.route('/groups/<int:group_id>/members/add', methods=['POST'])
@login_required
def group_member_add(group_id: int):
    _guard_groups_manage()
    group = SchoolGroup.query.get_or_404(group_id)
    student_id = request.form.get('student_id', type=int)
    if not student_id:
        flash('Выберите ученика.', 'danger')
        return redirect(url_for('groups.group_view', group_id=group.group_id))

    if not _can_access_student_id(student_id):
        abort(403)

    exists = GroupStudent.query.filter_by(group_id=group.group_id, student_id=student_id).first()
    if exists:
        flash('Ученик уже в группе.', 'warning')
        return redirect(url_for('groups.group_view', group_id=group.group_id))

    gs = GroupStudent(group_id=group.group_id, student_id=student_id, added_by_user_id=current_user.id)
    db.session.add(gs)
    db.session.commit()
    flash('Ученик добавлен в группу.', 'success')
    return redirect(url_for('groups.group_view', group_id=group.group_id))


@groups_bp.route('/groups/<int:group_id>/members/<int:member_id>/remove', methods=['POST'])
@login_required
def group_member_remove(group_id: int, member_id: int):
    _guard_groups_manage()
    group = SchoolGroup.query.get_or_404(group_id)
    member = GroupStudent.query.filter_by(id=member_id, group_id=group.group_id).first_or_404()

    if not _can_access_student_id(member.student_id):
        abort(403)

    db.session.delete(member)
    db.session.commit()
    flash('Ученик удалён из группы.', 'success')
    return redirect(url_for('groups.group_view', group_id=group.group_id))

