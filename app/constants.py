"""
Application-wide constants and status enums.
"""


class SubmissionStatus:
    """
    Statuses for Submission.status (string field).

    Canonical lifecycle:
      ASSIGNED -> IN_PROGRESS -> SUBMITTED -> NEEDS_MANUAL_REVIEW -> GRADED
                                        └-------------------------> GRADED
      GRADED -> RETURNED (teacher sends back for revision)
      RETURNED -> SUBMITTED (student resubmits)

    Legacy (kept only for data migration compatibility):
      LATE, AUTO_GRADED
    """
    ASSIGNED = 'ASSIGNED'
    IN_PROGRESS = 'IN_PROGRESS'
    SUBMITTED = 'SUBMITTED'
    NEEDS_MANUAL_REVIEW = 'NEEDS_MANUAL_REVIEW'
    GRADED = 'GRADED'
    RETURNED = 'RETURNED'

    ALL = (
        ASSIGNED, IN_PROGRESS, SUBMITTED, NEEDS_MANUAL_REVIEW, GRADED, RETURNED,
    )

    # Legacy statuses that must be normalized by migration/service layer.
    LEGACY = ('LATE', 'AUTO_GRADED')

    ACTIVE = (ASSIGNED, IN_PROGRESS, RETURNED)
    ON_REVIEW = (SUBMITTED, NEEDS_MANUAL_REVIEW)
    COMPLETED = (GRADED,)

    ALLOWED_TRANSITIONS = {
        ASSIGNED: {IN_PROGRESS, SUBMITTED, GRADED, RETURNED},
        IN_PROGRESS: {SUBMITTED, GRADED, RETURNED},
        SUBMITTED: {NEEDS_MANUAL_REVIEW, GRADED, RETURNED},
        NEEDS_MANUAL_REVIEW: {GRADED, RETURNED},
        GRADED: {RETURNED},
        RETURNED: {IN_PROGRESS, SUBMITTED, GRADED},
    }
