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
