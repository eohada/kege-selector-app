"""Async submission processing."""
from celery_app import celery


@celery.task(bind=True, max_retries=2)
def process_submission_task(self, submission_id: int):
    """Process and auto-grade a submission."""
    try:
        from app.models import db, Submission

        submission = Submission.query.get(submission_id)
        if submission is None:
            return {'status': 'error', 'message': f'Submission {submission_id} not found'}

        submission.status = 'processing'
        db.session.commit()

        correct = 0
        total = 0
        if submission.answers and submission.task and submission.task.correct_answers:
            student_answers = submission.answers
            correct_answers = submission.task.correct_answers
            for key, expected in correct_answers.items():
                total += 1
                if student_answers.get(key) == expected:
                    correct += 1

        score = round((correct / total) * 100) if total > 0 else 0
        submission.score = score
        submission.status = 'graded'
        db.session.commit()

        return {
            'status': 'graded',
            'submission_id': submission_id,
            'score': score,
            'correct': correct,
            'total': total,
        }
    except Exception as exc:
        self.retry(exc=exc)


@celery.task(bind=True, max_retries=2, default_retry_delay=5)
def review_submission_ai_task(self, submission_id: int, is_manual_rerun: bool = False):
    """Фоновая Celery-задача безопасной ИИ-предпроверки сдачи."""
    try:
        from core.db_models import db, Submission
        from app.assignments.ai_review_service import execute_review_pipeline

        submission = db.session.get(Submission, submission_id)
        if submission is None:
            return {'status': 'error', 'message': f'Submission {submission_id} not found'}

        ai_review = execute_review_pipeline(submission, is_manual_rerun=is_manual_rerun)
        return {
            'status': ai_review.status if ai_review else 'unknown',
            'submission_id': submission_id,
            'review_id': ai_review.id if ai_review else None,
            'ai_review_id': ai_review.id if ai_review else None,
        }
    except Exception as exc:
        if self.request.retries < self.max_retries:
            self.retry(exc=exc, countdown=5 * (self.request.retries + 1))
        raise
