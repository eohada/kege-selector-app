from copy import deepcopy
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.ai_lab.analytics import (
    _evidence_timestamp,
    _planned_activity_time_status,
    _timestamp_context,
    synthetic_demo_events,
)
from app.ai_lab.learning_evidence import (
    EvidenceContractError,
    merge_evidence_events,
    validate_evidence_event,
)


def test_synthetic_evidence_bridge_merges_sources_without_inference():
    homework = synthetic_demo_events()[0]
    homework["subject_id"] = "synthetic-evidence-bridge"
    practice = deepcopy(homework)
    practice.update({
        "event_id": "practice-run:synthetic-1",
        "source_module": "ai_practice",
        "source_record_id": "practice-run:synthetic-1",
        "source_ref": "practice-run:synthetic-1",
        "occurred_at": "2026-10-19T12:00:00+07:00",
    })
    practice["provenance"] = {"source_ref": "practice-run:synthetic-1", "method": "синтетическая практика"}

    result = merge_evidence_events(
        [[homework], [practice, deepcopy(practice)]],
        allowed_subject_ids={"synthetic-evidence-bridge"},
    )

    assert result["event_count"] == 2
    assert result["duplicate_count"] == 1
    assert result["source_counts"] == {"ai_homework": 1, "ai_practice": 1}
    assert [event["source_module"] for event in result["events"]] == ["ai_homework", "ai_practice"]
    assert result["events"][1]["outcome"]["score"] == 2


def test_synthetic_evidence_bridge_rejects_identity_and_payload_conflicts():
    homework = synthetic_demo_events()[0]
    with pytest.raises(EvidenceContractError, match="allowlist"):
        merge_evidence_events([[homework]], allowed_subject_ids={"synthetic-other"})

    conflicting = deepcopy(homework)
    conflicting["outcome"]["score"] = 0
    with pytest.raises(EvidenceContractError, match="противоречащими данными"):
        merge_evidence_events([[homework], [conflicting]])


def test_classwork_naive_timestamps_use_moscow_and_inherited_dates_are_not_activity():
    moscow = ZoneInfo("Europe/Moscow")
    actual = datetime(2026, 10, 27, 12, 30)
    normalized = _evidence_timestamp(actual, naive_timezone=moscow)
    assert normalized.isoformat() == "2026-10-27T12:30:00+03:00"

    planned = datetime(2026, 10, 26, 9, 0, tzinfo=moscow)
    assert _planned_activity_time_status(planned, normalized, inherited=True) == "inherited_template"
    assert _planned_activity_time_status(planned, normalized) == "source_record"
    assert _planned_activity_time_status(None, normalized) == "missing"
    assert _planned_activity_time_status(
        datetime(2026, 10, 28, 9, 0, tzinfo=moscow), normalized,
    ) == "conflicting"


def test_timestamp_context_records_actual_submission_separately_from_planning_date():
    event = deepcopy(synthetic_demo_events()[0])
    actual = datetime(2026, 10, 27, 12, 30, tzinfo=ZoneInfo("Europe/Moscow"))
    planned = datetime(2026, 10, 26, 9, 0, tzinfo=ZoneInfo("Europe/Moscow"))
    event["occurred_at"] = actual.isoformat()
    event["provenance"]["timestamp_context"] = _timestamp_context(
        "lesson_task_attempt.submitted_at", actual,
        timestamps={
            "lesson_task_attempt_submitted_at": actual,
            "lesson_task_planned_at": planned,
            "lesson_created_at": None,
        },
        context_only=("lesson_task_planned_at", "lesson_created_at"),
        field_interpretations={"lesson_task_planned_at": "inherited_template"},
    )

    normalized = validate_evidence_event(event)
    timing = normalized["provenance"]["timestamp_context"]
    assert normalized["occurred_at"] == actual.isoformat()
    assert timing["event_time_source"] == "lesson_task_attempt.submitted_at"
    assert timing["timestamps"]["lesson_task_planned_at"] == planned.isoformat()
    assert timing["field_interpretations"]["lesson_task_planned_at"] == "inherited_template"

    conflicting = deepcopy(event)
    conflicting["provenance"]["timestamp_context"]["timestamps"]["lesson_task_attempt_submitted_at"] = planned.isoformat()
    with pytest.raises(EvidenceContractError, match="не совпадает"):
        validate_evidence_event(conflicting)
