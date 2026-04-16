from app.assignments.submission_lifecycle_service import (
    SubmissionLifecycleError,
    can_transition,
    ensure_canonical_status,
    normalize_legacy_status,
)


def test_normalize_legacy_statuses():
    assert normalize_legacy_status('late') == 'SUBMITTED'
    assert normalize_legacy_status('AUTO_GRADED') == 'GRADED'
    assert normalize_legacy_status('SUBMITTED') == 'SUBMITTED'


def test_ensure_canonical_status_rejects_unknown():
    try:
        ensure_canonical_status('UNKNOWN')
        assert False, 'Expected SubmissionLifecycleError'
    except SubmissionLifecycleError:
        assert True


def test_transition_matrix_happy_path():
    assert can_transition('ASSIGNED', 'IN_PROGRESS')
    assert can_transition('IN_PROGRESS', 'SUBMITTED')
    assert can_transition('SUBMITTED', 'NEEDS_MANUAL_REVIEW')
    assert can_transition('NEEDS_MANUAL_REVIEW', 'GRADED')
    assert can_transition('GRADED', 'RETURNED')
    assert can_transition('RETURNED', 'SUBMITTED')


def test_transition_matrix_blocks_invalid_edges():
    assert not can_transition('ASSIGNED', 'NEEDS_MANUAL_REVIEW')
    assert not can_transition('GRADED', 'IN_PROGRESS')
    assert not can_transition('RETURNED', 'ASSIGNED')
