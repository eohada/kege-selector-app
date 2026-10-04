from types import SimpleNamespace
import hashlib
import hmac
import time
from urllib.parse import quote

from app.telegram.application import available_contexts, resolve_active_context
from app.telegram.user_notify import normalize_notification_kind
from app.telegram.mini_app import validate_init_data


class FakeUser:
    def __init__(self, roles, mode="ADMIN"):
        self.id = 7
        self.role = roles[0]
        self.creator_bot_mode = mode
        self._roles = roles

    def roles(self):
        return self._roles


def test_creator_teacher_context_is_role_checked():
    user = FakeUser(["creator"], mode="TEACHER")

    assert resolve_active_context(user) == "teacher"
    assert resolve_active_context(user, "teacher") == "teacher"
    assert resolve_active_context(user, "student") == "teacher"
    assert available_contexts(user) == ("teacher", "creator")


def test_requested_context_cannot_escalate_student():
    user = FakeUser(["student"])

    assert resolve_active_context(user, "admin") == "student"
    assert resolve_active_context(user, "creator") == "student"
    assert available_contexts(user) == ("student",)


def test_parent_context_does_not_fall_back_to_teacher():
    user = FakeUser(["parent"])

    assert resolve_active_context(user, "teacher") == "parent"
    assert available_contexts(user) == ("parent",)


def test_notification_taxonomy_normalizes_unknown_producers():
    assert normalize_notification_kind("review_queue") == "review_queue"
    assert normalize_notification_kind(" CHILD_DIGEST ") == "child_digest"
    assert normalize_notification_kind("future_unregistered_kind") == "generic"
    assert normalize_notification_kind(None) is None


def test_new_notification_kinds_use_existing_preferences():
    from app.telegram.user_notify import _KIND_TO_ATTR

    assert _KIND_TO_ATTR['review_queue'] == 'tg_notify_homework_submitted'
    assert _KIND_TO_ATTR['child_digest'] == 'tg_notify_daily_digest'
    assert _KIND_TO_ATTR['operational_alert'] == 'tg_notify_system_errors'


def test_operational_summary_has_delivery_health_fields():
    from app.telegram.application import OperationalSummary

    summary = OperationalSummary(1, 2, 3, 4, 5, 6, 7, 8)
    assert summary.pending_deliveries == 6
    assert summary.retry_deliveries == 7
    assert summary.failed_deliveries == 8


def test_action_item_priority_order_is_explicit():
    from app.telegram.application import ActionItem

    # The ordering contract is encoded in the service's rank; this guards the
    # public priority vocabulary used by renderers.
    items = [ActionItem('a', 'normal', 'normal'), ActionItem('b', 'critical', 'critical')]
    assert sorted(items, key=lambda item: {'critical': 0, 'high': 1, 'normal': 2, 'low': 3}[item.priority])[0].type == 'b'


def test_mini_app_init_data_rejects_expired_auth_date():
    token = 'test-bot-token'
    auth_date = int(time.time()) - 90000
    user_json = '{"id":7}'
    raw = f'auth_date={auth_date}&user={quote(user_json)}'
    secret = hmac.new(b'WebAppData', token.encode(), hashlib.sha256).digest()
    signature = hmac.new(secret, f'auth_date={auth_date}\nuser={{"id":7}}'.encode(), hashlib.sha256).hexdigest()
    assert validate_init_data(raw + f'&hash={signature}', token) is None


def test_new_mini_app_endpoints_require_verified_init_data(app):
    client = app.test_client()
    paths = (
        '/tg-app/api/context',
        '/tg-app/api/context/switch',
        '/tg-app/api/home',
        '/tg-app/api/action-center',
        '/tg-app/api/teacher/review-queue',
        '/tg-app/api/teacher/students',
        '/tg-app/api/parent/children-summary',
        '/tg-app/api/parent/digest',
        '/tg-app/api/parent/context/switch',
        '/tg-app/api/operations/summary',
        '/tg-app/api/operations/problems',
        '/tg-app/api/operations/users/search',
        '/tg-app/api/student/assignments',
    )
    assert {client.post(path, json={}).status_code for path in paths} == {403}
