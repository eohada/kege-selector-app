"""
Application-wide constants and status enums.
"""


class SubmissionStatus:
    """
    Statuses for Submission.status (string field).

    Lifecycle:
      ASSIGNED -> IN_PROGRESS -> SUBMITTED -> NEEDS_MANUAL_REVIEW -> GRADED
                                           -> AUTO_GRADED (fully auto-checked)
      GRADED -> RETURNED (teacher sends back for revision)
      RETURNED -> SUBMITTED (student resubmits)
    """
    ASSIGNED = 'ASSIGNED'
    IN_PROGRESS = 'IN_PROGRESS'
    SUBMITTED = 'SUBMITTED'
    NEEDS_MANUAL_REVIEW = 'NEEDS_MANUAL_REVIEW'
    AUTO_GRADED = 'AUTO_GRADED'
    GRADED = 'GRADED'
    RETURNED = 'RETURNED'
    LATE = 'LATE'

    ALL = (
        ASSIGNED, IN_PROGRESS, SUBMITTED, NEEDS_MANUAL_REVIEW,
        AUTO_GRADED, GRADED, RETURNED, LATE,
    )
