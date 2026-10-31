"""Controlled historical backfill service for Multi-Teacher schedule architecture.

Sprint 2.2:
- 5-category classification.
- Default: dry-run mode (read-only, never mutates data without explicit --apply).
- Never falsifies history (ambiguous data retains teacher_id = NULL).
- Full auditability: produces structured record-by-record reports and summaries.
- Idempotent: repeated runs skip already resolved records.
"""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional

from app.models import (
    db,
    Enrollment,
    GradebookEntry,
    Lesson,
    LessonOutcome,
    LessonTeacherHomeworkNote,
    LessonWhiteboard,
    Student,
    User,
)

logger = logging.getLogger(__name__)


CATEGORY_SINGLE_TUTOR = "1_SINGLE_TUTOR_CONFIRMED"
CATEGORY_ARTIFACT_CONFIRMED = "2_ARTIFACT_CONFIRMED"
CATEGORY_MULTIPLE_CANDIDATES = "3_MULTIPLE_CANDIDATES"
CATEGORY_NO_TEACHER_FOUND = "4_NO_TEACHER_FOUND"
CATEGORY_CONTRADICTORY_DATA = "5_CONTRADICTORY_DATA"

STATUS_RESOLVED = "RESOLVED"
STATUS_UNRESOLVED_NULL = "UNRESOLVED_NULL"
STATUS_ALREADY_RESOLVED = "ALREADY_RESOLVED"


@dataclass
class LessonBackfillRecord:
    lesson_id: int
    category: str
    candidate_teacher_id: Optional[int]
    candidate_teacher_name: Optional[str]
    subject: Optional[str]
    evidence_source: str
    resolution_reason: str
    resolution_status: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class BackfillSummaryReport:
    total_examined: int
    already_resolved: int
    cat1_single_tutor_count: int
    cat2_artifact_confirmed_count: int
    cat3_multiple_candidates_count: int
    cat4_no_teacher_found_count: int
    cat5_contradictory_data_count: int
    total_confidently_resolved: int
    total_retained_null: int
    is_dry_run: bool
    records: List[LessonBackfillRecord]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "summary": {
                "total_examined": self.total_examined,
                "already_resolved": self.already_resolved,
                "cat1_single_tutor_count": self.cat1_single_tutor_count,
                "cat2_artifact_confirmed_count": self.cat2_artifact_confirmed_count,
                "cat3_multiple_candidates_count": self.cat3_multiple_candidates_count,
                "cat4_no_teacher_found_count": self.cat4_no_teacher_found_count,
                "cat5_contradictory_data_count": self.cat5_contradictory_data_count,
                "total_confidently_resolved": self.total_confidently_resolved,
                "total_retained_null": self.total_retained_null,
                "is_dry_run": self.is_dry_run,
            },
            "records": [r.to_dict() for r in self.records],
        }


def classify_lesson_ownership(lesson: Lesson) -> LessonBackfillRecord:
    """
    Classifies a single lesson into one of the 5 categories based on historical evidence.
    """
    if lesson.teacher_id is not None:
        teacher = db.session.get(User, lesson.teacher_id)
        return LessonBackfillRecord(
            lesson_id=lesson.lesson_id,
            category="0_ALREADY_RESOLVED",
            candidate_teacher_id=lesson.teacher_id,
            candidate_teacher_name=teacher.full_name or teacher.username if teacher else None,
            subject=lesson.subject or "Информатика",
            evidence_source="Lesson.teacher_id",
            resolution_reason="Урок уже имеет явно назначенного преподавателя в БД.",
            resolution_status=STATUS_ALREADY_RESOLVED,
        )

    student = db.session.get(Student, lesson.student_id) if lesson.student_id else None
    if not student:
        return LessonBackfillRecord(
            lesson_id=lesson.lesson_id,
            category=CATEGORY_NO_TEACHER_FOUND,
            candidate_teacher_id=None,
            candidate_teacher_name=None,
            subject=lesson.subject or "Информатика",
            evidence_source="None",
            resolution_reason="Запись урока не привязана к существующему ученику.",
            resolution_status=STATUS_UNRESOLVED_NULL,
        )

    # 1. Inspect direct artifacts linked to this lesson
    artifact_authors: Dict[str, int] = {}
    outcome = LessonOutcome.query.filter_by(lesson_id=lesson.lesson_id).first()
    if outcome and outcome.created_by_user_id:
        artifact_authors["LessonOutcome"] = outcome.created_by_user_id

    hw_note = LessonTeacherHomeworkNote.query.filter_by(lesson_id=lesson.lesson_id).first()
    if hw_note and hw_note.teacher_user_id:
        artifact_authors["LessonTeacherHomeworkNote"] = hw_note.teacher_user_id

    gradebook = GradebookEntry.query.filter_by(lesson_id=lesson.lesson_id).first()
    if gradebook and gradebook.created_by_user_id:
        artifact_authors["GradebookEntry"] = gradebook.created_by_user_id

    whiteboard = LessonWhiteboard.query.filter_by(lesson_id=lesson.lesson_id).first()
    if whiteboard and whiteboard.last_saved_by_user_id:
        artifact_authors["LessonWhiteboard"] = whiteboard.last_saved_by_user_id

    # 2. Inspect student's enrollments and mentor
    enrollments: List[Enrollment] = []
    if student.user_id:
        enrollments = (
            Enrollment.query.filter_by(student_id=student.user_id)
            .filter(Enrollment.status != "archived")
            .all()
        )
    tutor_ids_from_enrollments = list({e.tutor_id for e in enrollments if e.tutor_id})

    # Category 5 check: Contradictory artifacts pointing to different users
    unique_artifact_authors = set(artifact_authors.values())
    if len(unique_artifact_authors) > 1:
        details = ", ".join(f"{k}: User #{uid}" for k, uid in artifact_authors.items())
        return LessonBackfillRecord(
            lesson_id=lesson.lesson_id,
            category=CATEGORY_CONTRADICTORY_DATA,
            candidate_teacher_id=None,
            candidate_teacher_name=None,
            subject=lesson.subject or "Информатика",
            evidence_source=f"Contradictory artifacts: {details}",
            resolution_reason="Артефакты урока принадлежат разным преподавателям. Сохраняем NULL.",
            resolution_status=STATUS_UNRESOLVED_NULL,
        )

    # Category 2: Definitively confirmed by single artifact author
    if len(unique_artifact_authors) == 1:
        author_id = next(iter(unique_artifact_authors))
        author_user = db.session.get(User, author_id)
        matching_enr = next((e for e in enrollments if e.tutor_id == author_id), None)
        subject = (matching_enr.subject if matching_enr and matching_enr.subject else lesson.subject) or "Информатика"
        source_names = ", ".join(artifact_authors.keys())

        return LessonBackfillRecord(
            lesson_id=lesson.lesson_id,
            category=CATEGORY_ARTIFACT_CONFIRMED,
            candidate_teacher_id=author_id,
            candidate_teacher_name=author_user.full_name or author_user.username if author_user else None,
            subject=subject,
            evidence_source=f"Artifact ({source_names})",
            resolution_reason=f"Преподаватель однозначно подтвержден авторством артефактов урока ({source_names}).",
            resolution_status=STATUS_RESOLVED,
        )

    # Check student's overall tutors
    candidate_tutors = set(tutor_ids_from_enrollments)
    if student.mentor_id:
        candidate_tutors.add(student.mentor_id)

    # Category 1: Single tutor confirmed across all contracts
    if len(candidate_tutors) == 1:
        sole_tutor_id = next(iter(candidate_tutors))
        tutor_user = db.session.get(User, sole_tutor_id)
        matching_enr = next((e for e in enrollments if e.tutor_id == sole_tutor_id), None)
        subject = (matching_enr.subject if matching_enr and matching_enr.subject else lesson.subject) or "Информатика"

        return LessonBackfillRecord(
            lesson_id=lesson.lesson_id,
            category=CATEGORY_SINGLE_TUTOR,
            candidate_teacher_id=sole_tutor_id,
            candidate_teacher_name=tutor_user.full_name or tutor_user.username if tutor_user else None,
            subject=subject,
            evidence_source="Sole active Enrollment/Mentor",
            resolution_reason="Ученик имеет ровно одного преподавателя по всем учебным контрактам.",
            resolution_status=STATUS_RESOLVED,
        )

    # Category 3: Multiple candidate tutors, but no lesson-level artifacts to distinguish
    if len(candidate_tutors) > 1:
        candidates_str = ", ".join(f"#{tid}" for tid in sorted(candidate_tutors))
        return LessonBackfillRecord(
            lesson_id=lesson.lesson_id,
            category=CATEGORY_MULTIPLE_CANDIDATES,
            candidate_teacher_id=None,
            candidate_teacher_name=None,
            subject=lesson.subject or "Информатика",
            evidence_source=f"Multiple tutors ({candidates_str})",
            resolution_reason="Ученик обучается у нескольких преподавателей, урок не имеет однозначных артефактов привязки. Сохраняем NULL.",
            resolution_status=STATUS_UNRESOLVED_NULL,
        )

    # Category 4: No tutors or enrollments found
    return LessonBackfillRecord(
        lesson_id=lesson.lesson_id,
        category=CATEGORY_NO_TEACHER_FOUND,
        candidate_teacher_id=None,
        candidate_teacher_name=None,
        subject=lesson.subject or "Информатика",
        evidence_source="No tutor contracts or mentor",
        resolution_reason="Ученик не имеет активных учебных контрактов или ментора. Сохраняем NULL.",
        resolution_status=STATUS_UNRESOLVED_NULL,
    )


def execute_historical_backfill(
    dry_run: bool = True,
    batch_size: int = 500,
    lesson_id_filter: Optional[List[int]] = None,
) -> BackfillSummaryReport:
    """
    Executes the controlled historical backfill across Lesson records.
    By default operates in dry_run=True mode.
    """
    query = Lesson.query.order_by(Lesson.lesson_id.asc())
    if lesson_id_filter:
        query = query.filter(Lesson.lesson_id.in_(lesson_id_filter))

    all_lessons = query.all()
    records: List[LessonBackfillRecord] = []

    already_resolved_count = 0
    cat1_count = 0
    cat2_count = 0
    cat3_count = 0
    cat4_count = 0
    cat5_count = 0
    confidently_resolved = 0
    retained_null = 0

    updates_to_apply = []

    for lesson in all_lessons:
        record = classify_lesson_ownership(lesson)
        records.append(record)

        if record.resolution_status == STATUS_ALREADY_RESOLVED:
            already_resolved_count += 1
            continue

        if record.category == CATEGORY_SINGLE_TUTOR:
            cat1_count += 1
            confidently_resolved += 1
            updates_to_apply.append((lesson, record.candidate_teacher_id, record.subject))
        elif record.category == CATEGORY_ARTIFACT_CONFIRMED:
            cat2_count += 1
            confidently_resolved += 1
            updates_to_apply.append((lesson, record.candidate_teacher_id, record.subject))
        elif record.category == CATEGORY_MULTIPLE_CANDIDATES:
            cat3_count += 1
            retained_null += 1
        elif record.category == CATEGORY_NO_TEACHER_FOUND:
            cat4_count += 1
            retained_null += 1
        elif record.category == CATEGORY_CONTRADICTORY_DATA:
            cat5_count += 1
            retained_null += 1

    if not dry_run and updates_to_apply:
        for idx, (lesson_obj, tid, subj) in enumerate(updates_to_apply, start=1):
            lesson_obj.teacher_id = tid
            if subj and not lesson_obj.subject:
                lesson_obj.subject = subj

            if idx % batch_size == 0:
                db.session.commit()
        db.session.commit()
        logger.info(f"Backfill applied: {len(updates_to_apply)} lessons updated.")

    return BackfillSummaryReport(
        total_examined=len(all_lessons),
        already_resolved=already_resolved_count,
        cat1_single_tutor_count=cat1_count,
        cat2_artifact_confirmed_count=cat2_count,
        cat3_multiple_candidates_count=cat3_count,
        cat4_no_teacher_found_count=cat4_count,
        cat5_contradictory_data_count=cat5_count,
        total_confidently_resolved=confidently_resolved,
        total_retained_null=retained_null,
        is_dry_run=dry_run,
        records=records,
    )
