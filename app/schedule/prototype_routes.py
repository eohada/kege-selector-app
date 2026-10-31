"""
BooStudy — Student Schedule: Experience Rebirth (Phase 0)
Isolated Design Prototype Preview Routes & Security Gate.

SECURITY GUARANTEES:
- Strictly blocked in production environments (checks BOOSTUDY_ENV, FLASK_ENV, IS_PRODUCTION).
- Requires explicit dev/test enablement flag (BOOSTUDY_SCHEDULE_PREVIEWS_ENABLED, TESTING, etc.).
- Does NOT rely on single DEBUG flag alone.
- Isolated from production student schedule routes.
"""
import os
from flask import Blueprint, render_template, request, jsonify, abort, current_app
from flask_login import current_user
from app.schedule.prototype_data import get_prototype_data
from core.db_models import User

prototype_bp = Blueprint('schedule_prototype', __name__, url_prefix='/schedule/preview')


def is_preview_environment_allowed() -> bool:
    """
    Multi-layer environment security check to prevent prototype routes
    from ever running or being exposed in a production deployment.
    """
    # 1. Hard fail if explicitly marked production
    env_name = (os.environ.get('BOOSTUDY_ENV') or os.environ.get('FLASK_ENV') or '').strip().lower()
    if env_name in ('production', 'prod', 'live'):
        return False
    if current_app.config.get('IS_PRODUCTION') is True:
        return False

    # 2. Hard require explicit dev/test authorization flag
    explicit_enabled = os.environ.get('BOOSTUDY_SCHEDULE_PREVIEWS_ENABLED', '').strip().lower() in ('1', 'true', 'yes', 'on')
    testing_mode = bool(current_app.config.get('TESTING'))
    config_enabled = bool(current_app.config.get('SCHEDULE_PREVIEWS_ENABLED'))
    dev_mode = os.environ.get('BOOSTUDY_DEV_MODE', '').strip().lower() in ('1', 'true', 'yes', 'on')
    local_dev = os.environ.get('BOOSTUDY_LOCAL_DEV', '').strip().lower() in ('1', 'true', 'yes', 'on')

    return explicit_enabled or testing_mode or config_enabled or dev_mode or local_dev


def get_preview_context() -> dict:
    """
    Provides safe default context for layout_dashboard and layout_student
    so prototypes render reliably in browser sessions even without active login.
    """
    ctx = {
        'dashboard_profile_name': 'София (Ученик)',
        'dashboard_profile_meta': 'Ученик',
        'dashboard_admin_shell': False,
        'show_dev_tools': False
    }
    user_authenticated = getattr(current_user, 'is_authenticated', False)
    if not user_authenticated:
        ctx['current_user'] = User(
            id=999,
            username='preview_student',
            role='student',
            full_name='София (Ученик)',
            email='student@preview.test',
            avatar_url='/static/images/default-avatar.svg'
        )
    return ctx


@prototype_bp.before_request
def prototype_security_gate():
    """Abort with 404 if not running in authorized dev/test environment."""
    if not is_preview_environment_allowed():
        abort(404)


@prototype_bp.route('/')
def preview_hub():
    """
    Interactive Preview Hub:
    Allows platform owner to inspect all 3 concepts, compare viewports,
    and switch data scenarios on the fly.
    """
    scenario = request.args.get('scenario', 'standard')
    week_offset = int(request.args.get('week', 0))
    data = get_prototype_data(scenario=scenario, week_offset=week_offset)
    ctx = get_preview_context()
    return render_template(
        'sandbox/schedule_prototypes/preview_index.html',
        data=data,
        active_concept='hub',
        active_scenario=scenario,
        week_offset=week_offset,
        **ctx
    )


@prototype_bp.route('/concept-a')
def concept_a_command_center():
    """Concept A: Learning Command Center (Action & Mission First)."""
    scenario = request.args.get('scenario', 'standard')
    week_offset = int(request.args.get('week', 0))
    day_idx = request.args.get('day', type=int)
    data = get_prototype_data(scenario=scenario, week_offset=week_offset, selected_day_index=day_idx)
    ctx = get_preview_context()
    return render_template(
        'sandbox/schedule_prototypes/concept_a_command_center.html',
        data=data,
        active_concept='a',
        active_scenario=scenario,
        week_offset=week_offset,
        **ctx
    )


@prototype_bp.route('/concept-b')
def concept_b_fluid_week():
    """Concept B: Fluid Week (Content Density-Driven Architecture)."""
    scenario = request.args.get('scenario', 'standard')
    week_offset = int(request.args.get('week', 0))
    day_idx = request.args.get('day', type=int)
    data = get_prototype_data(scenario=scenario, week_offset=week_offset, selected_day_index=day_idx)
    ctx = get_preview_context()
    return render_template(
        'sandbox/schedule_prototypes/concept_b_fluid_week.html',
        data=data,
        active_concept='b',
        active_scenario=scenario,
        week_offset=week_offset,
        **ctx
    )


@prototype_bp.route('/concept-c')
def concept_c_personal_space():
    """Concept C: Personal Learning Space (Atmospheric & Emotional Companion)."""
    scenario = request.args.get('scenario', 'standard')
    week_offset = int(request.args.get('week', 0))
    day_idx = request.args.get('day', type=int)
    data = get_prototype_data(scenario=scenario, week_offset=week_offset, selected_day_index=day_idx)
    ctx = get_preview_context()
    return render_template(
        'sandbox/schedule_prototypes/concept_c_personal_space.html',
        data=data,
        active_concept='c',
        active_scenario=scenario,
        week_offset=week_offset,
        **ctx
    )


@prototype_bp.route('/concept-d')
def concept_d_unified():
    """Concept D: Unified Student Schedule (Phase 0.5 Integrated Architecture)."""
    scenario = request.args.get('scenario', 'standard')
    week_offset = int(request.args.get('week', 0))
    day_idx = request.args.get('day', type=int)
    data = get_prototype_data(scenario=scenario, week_offset=week_offset, selected_day_index=day_idx)
    ctx = get_preview_context()
    return render_template(
        'sandbox/schedule_prototypes/concept_d_unified.html',
        data=data,
        active_concept='d',
        active_scenario=scenario,
        week_offset=week_offset,
        **ctx
    )


@prototype_bp.route('/api/data')
def api_prototype_data():
    """API endpoint to get synthetic scenarios asynchronously for instant switcher."""
    scenario = request.args.get('scenario', 'standard')
    week_offset = int(request.args.get('week', 0))
    day_idx = request.args.get('day', type=int)
    data = get_prototype_data(scenario=scenario, week_offset=week_offset, selected_day_index=day_idx)
    return jsonify(data)
