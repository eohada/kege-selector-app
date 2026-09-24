"""
CourseAdaptiveEngine — интеллектуальный алгоритмический сервис адаптации
образовательной траектории ученика по результатам проведенных уроков.

Принципы работы:
1. Непрерывная калибровка навыков (StudentSkill) с учетом самостоятельности и понимания.
2. Проактивная фиксация ошибок (LearningError) с планированием интервального закрепления.
3. Динамическая перестройка очереди программы (LearningItem):
   - При затруднениях (poor/needs_repeat): автоматическое внедрение урока/блока повторения;
   - При уверенном опережении (mastered + high): разгрузка программы от тривиальных шагов;
   - Перебалансировка дедлайнов и приоритетов в еженедельном плане.
4. Автоматическая подготовка умного сценария следующего занятия:
   - Включение в разминку разбора свежих ошибок;
   - Формирование актуальной темы и рекомендаций.
5. Актуализация прогноза первичных и вторичных баллов ЕГЭ (current_forecast, forecast_range).
"""

from __future__ import annotations

import logging
from datetime import datetime, date, timedelta
from typing import Any, Dict, List, Optional, Tuple

from app.models import (
    db,
    Student,
    Lesson,
    LessonTask,
    Tasks,
    LearningTrajectory,
    TrajectoryModule,
    LearningItem,
    LessonOutcome,
    ExamSkill,
    StudentSkill,
    LearningError,
)
from core.db_models import utc_now, moscow_now

logger = logging.getLogger(__name__)


class CourseAdaptiveEngine:
    """Алгоритмический координатор адаптивного курса BooStudy."""

    @classmethod
    def apply_lesson_adaptation(
        cls,
        course: LearningTrajectory,
        lesson: Lesson,
        outcome: LessonOutcome,
        trigger_replan: bool = True,
    ) -> Dict[str, Any]:
        """
        Главная точка входа: применяет результат урока к курсу и перестраивает будущую траекторию.
        """
        diff_summary: Dict[str, Any] = {
            'comprehension_score': outcome.comprehension_score,
            'independence_level': outcome.independence_level,
            'pacing': outcome.pacing,
            'skills_updated': [],
            'errors_recorded': [],
            'items_inserted': [],
            'items_skipped': [],
            'rebalance_stats': {'injected_review_items': 0, 'skipped_practice_items': 0},
            'forecast_diff': None,
            'next_lesson_prepared': False,
            'next_lesson': None,
            'applied_at': utc_now().isoformat(),
        }

        if course.is_template or not course.student_id:
            outcome.adaptive_diff_summary = diff_summary
            db.session.commit()
            return diff_summary

        # 1. Считываем метрики итога
        covered_ids = [int(sid) for sid in (outcome.covered or []) if str(sid).isdigit()]
        mastery_eval = (outcome.mastery or 'good').strip().lower()  # good | medium | poor | needs_repeat
        independence = (outcome.independence_level or 'medium').strip().lower()  # high | medium | low
        pacing = (outcome.pacing or 'optimal').strip().lower()  # too_fast | optimal | needs_slowdown
        comprehension = outcome.comprehension_score or (5 if mastery_eval == 'good' else (3 if mastery_eval == 'medium' else 2))
        next_action = (outcome.next_action or 'continue').strip().lower()  # continue | repeat | mastered | advance

        # 2. Калибровка навыков (StudentSkill)
        diff_summary['skills_updated'] = cls._calibrate_skills(
            student_id=course.student_id,
            covered_skill_ids=covered_ids,
            mastery_eval=mastery_eval,
            independence=independence,
            comprehension=comprehension,
        )

        # 3. Фиксация выявленных ошибок (LearningError)
        diff_summary['errors_recorded'] = cls._record_errors(
            course=course,
            lesson=lesson,
            errors_data=outcome.identified_errors or [],
        )

        # 4. Адаптивная перестройка очереди программы (LearningItem)
        if trigger_replan:
            inserted, skipped = cls._rebalance_learning_items(
                course=course,
                lesson=lesson,
                covered_skill_ids=covered_ids,
                mastery_eval=mastery_eval,
                next_action=next_action,
                pacing=pacing,
            )
            diff_summary['items_inserted'] = inserted
            diff_summary['items_skipped'] = skipped
            diff_summary['rebalance_stats'] = {
                'injected_review_items': len(inserted),
                'skipped_practice_items': len(skipped),
            }

            # 5. Умный черновик следующего урока
            next_lesson = cls._ensure_smart_next_lesson(
                course=course,
                last_lesson=lesson,
                outcome=outcome,
            )
            if next_lesson:
                diff_summary['next_lesson_prepared'] = True
                diff_summary['next_lesson_id'] = next_lesson.lesson_id
                diff_summary['next_lesson'] = {
                    'lesson_id': next_lesson.lesson_id,
                    'topic': next_lesson.topic,
                    'agenda': next_lesson.content or '',
                }

            # 6. Пересчет прогноза
            diff_summary['forecast_diff'] = cls._recalculate_forecast(course)

            outcome.auto_replan_triggered = True

        outcome.adaptive_diff_summary = diff_summary
        db.session.commit()
        return diff_summary

    @classmethod
    def _calibrate_skills(
        cls,
        student_id: int,
        covered_skill_ids: List[int],
        mastery_eval: str,
        independence: str,
        comprehension: int,
    ) -> List[Dict[str, Any]]:
        """Дифференцированный пересчет освоения навыков."""
        results = []
        if not covered_skill_ids:
            return results

        # Базовый прирост в зависимости от понимания и самостоятельности
        comp_mult = {1: 0.3, 2: 0.5, 3: 0.75, 4: 0.9, 5: 1.0}.get(comprehension, 0.7)
        indep_bonus = {'high': 15, 'medium': 5, 'low': -10}.get(independence, 0)

        for skill_id in covered_skill_ids:
            skill = ExamSkill.query.get(skill_id)
            if not skill:
                continue

            row = StudentSkill.query.filter_by(student_id=student_id, skill_id=skill_id).first()
            if not row:
                row = StudentSkill(student_id=student_id, skill_id=skill_id, mastery_percent=0, state='learning')
                db.session.add(row)

            prev_mastery = row.mastery_percent or 0
            if mastery_eval in ('good', 'mastered'):
                target_gain = 35 * comp_mult + indep_bonus
                new_mastery = min(100, max(prev_mastery, int(prev_mastery + target_gain)))
            elif mastery_eval == 'medium':
                target_gain = 20 * comp_mult + indep_bonus
                new_mastery = min(85, max(prev_mastery + 5, int(prev_mastery + target_gain)))
            else:  # poor / needs_repeat
                new_mastery = max(15, min(prev_mastery, int(prev_mastery * 0.85)))

            row.mastery_percent = new_mastery
            row.state = 'mastered' if new_mastery >= 85 else ('reinforcing' if new_mastery >= 50 else 'learning')
            row.practice_done = True
            row.last_checked_at = moscow_now()
            row.updated_at = moscow_now()

            results.append({
                'skill_id': skill_id,
                'skill_title': skill.title,
                'prev_mastery': prev_mastery,
                'new_mastery': new_mastery,
                'state': row.state,
            })

        return results

    @classmethod
    def _record_errors(
        cls,
        course: LearningTrajectory,
        lesson: Lesson,
        errors_data: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Регистрирует или обновляет ошибки ученика."""
        recorded = []
        if not isinstance(errors_data, list):
            return recorded

        for item in errors_data:
            if not isinstance(item, dict):
                continue
            err_type = str(item.get('error_type') or item.get('type') or 'Концептуальная ошибка').strip()[:120]
            desc = str(item.get('description') or '').strip()[:2000]
            skill_id = item.get('skill_id')
            if skill_id:
                try:
                    skill_id = int(skill_id)
                except (ValueError, TypeError):
                    skill_id = None

            q = LearningError.query.filter_by(student_id=course.student_id, error_type=err_type)
            if skill_id:
                q = q.filter_by(skill_id=skill_id)
            err_obj = q.filter(LearningError.resolved_at.is_(None)).first()

            if err_obj:
                err_obj.occurrences = (err_obj.occurrences or 1) + 1
                err_obj.last_seen_at = utc_now()
                if desc:
                    err_obj.description = desc
            else:
                err_obj = LearningError(
                    student_id=course.student_id,
                    skill_id=skill_id,
                    lesson_id=lesson.lesson_id,
                    error_type=err_type,
                    description=desc or None,
                    occurrences=1,
                    last_seen_at=utc_now(),
                    next_review_at=utc_now() + timedelta(days=3),
                )
                db.session.add(err_obj)

            recorded.append({
                'error_type': err_type,
                'occurrences': err_obj.occurrences,
                'skill_id': skill_id,
            })

        return recorded

    @classmethod
    def _rebalance_learning_items(
        cls,
        course: LearningTrajectory,
        lesson: Lesson,
        covered_skill_ids: List[int],
        mastery_eval: str,
        next_action: str,
        pacing: str,
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Адаптивная балансировка очереди элементов программы."""
        inserted = []
        skipped = []

        if next_action == 'repeat' or mastery_eval in ('poor', 'needs_repeat') or pacing == 'needs_slowdown':
            for skill_id in covered_skill_ids:
                skill = ExamSkill.query.get(skill_id)
                if not skill:
                    continue

                existing_rev = LearningItem.query.filter_by(
                    course_id=course.course_id,
                    skill_id=skill_id,
                    item_type='review',
                    status='planned',
                ).first()

                if not existing_rev:
                    current_max_order = (
                        db.session.query(db.func.min(LearningItem.order_index))
                        .filter(LearningItem.course_id == course.course_id, LearningItem.status == 'planned')
                        .scalar()
                        or 10
                    )
                    rev_item = LearningItem(
                        course_id=course.course_id,
                        skill_id=skill_id,
                        module_id=lesson.course_module_id,
                        item_type='review',
                        title=f'Отработка и повторение: {skill.title}'[:300],
                        status='planned',
                        due_at=utc_now() + timedelta(days=2),
                        why_now='Автоматически назначено для устранения пробелов после предыдущего занятия',
                        order_index=max(1, int(current_max_order) - 5),
                    )
                    db.session.add(rev_item)
                    inserted.append({
                        'title': rev_item.title,
                        'type': rev_item.item_type,
                        'skill_id': skill_id,
                        'reason': 'Закрепление слабого места',
                    })

        elif next_action in ('mastered', 'advance') or mastery_eval == 'good':
            for skill_id in covered_skill_ids:
                redundant_items = LearningItem.query.filter_by(
                    course_id=course.course_id,
                    skill_id=skill_id,
                    status='planned',
                ).all()

                for item in redundant_items:
                    if item.item_type in ('review', 'practice') and item.lesson_id != lesson.lesson_id:
                        item.status = 'skipped'
                        item.why_now = 'Пропущено алгоритмом: тема успешно освоена на предыдущем уроке'
                        skipped.append({
                            'item_id': item.item_id,
                            'title': item.title,
                            'reason': 'Тема освоена досрочно',
                        })

        return inserted, skipped

    @classmethod
    def _ensure_smart_next_lesson(
        cls,
        course: LearningTrajectory,
        last_lesson: Lesson,
        outcome: LessonOutcome,
    ) -> Optional[Lesson]:
        """
        Формирует или обновляет черновик следующего урока с актуальной адаптивной структурой.
        """
        draft = Lesson.query.filter_by(
            learning_trajectory_id=course.course_id,
            status='draft',
        ).first()

        recent_errors = (
            LearningError.query.filter_by(student_id=course.student_id)
            .filter(LearningError.resolved_at.is_(None))
            .order_by(LearningError.occurrences.desc(), LearningError.last_seen_at.desc())
            .limit(3)
            .all()
        )

        next_item = (
            LearningItem.query.filter_by(course_id=course.course_id, status='planned')
            .order_by(LearningItem.order_index.asc(), LearningItem.item_id.asc())
            .first()
        )

        focus_title = next_item.title if next_item else 'Комплексная практика'
        error_notes = [f'{e.error_type} ({e.description or "типовой разбор"})' for e in recent_errors]

        agenda = ['Разминка и проверка понимания материала']
        if error_notes:
            agenda.append('Анализ ошибок: ' + '; '.join(error_notes))
        agenda.append(f'Основная часть: {focus_title}')
        agenda.append('Самостоятельное решение и закрепление')

        content_markdown = '\n'.join(f'- {item}' for item in agenda)

        if not draft:
            draft = Lesson(
                student_id=course.student_id,
                learning_trajectory_id=course.course_id,
                course_module_id=next_item.module_id if next_item else last_lesson.course_module_id,
                topic=f'Занятие: {focus_title}'[:300],
                status='draft',
                duration=course.default_lesson_duration or 60,
                lesson_type='regular',
                content=content_markdown,
                notes='Черновик адаптирован алгоритмом на основе итогов предыдущего урока.',
            )
            db.session.add(draft)
            db.session.flush()
        else:
            draft.topic = f'Занятие: {focus_title}'[:300]
            draft.content = content_markdown
            if next_item and next_item.module_id:
                draft.course_module_id = next_item.module_id

        draft.review_summaries = {
            '_studio': {
                'agenda': [{'title': line} for line in agenda],
                'generated_from': {
                    'last_lesson_id': last_lesson.lesson_id,
                    'outcome_id': outcome.outcome_id,
                    'active_error_ids': [e.error_id for e in recent_errors],
                    'target_item_id': next_item.item_id if next_item else None,
                },
            }
        }

        return draft

    @classmethod
    def _recalculate_forecast(cls, course: LearningTrajectory) -> Dict[str, Any]:
        """Пересчитывает прогноз баллов на основе актуального освоения навыков."""
        items = LearningItem.query.filter_by(course_id=course.course_id).all()
        skill_ids = [item.skill_id for item in items if item.skill_id]

        prev_forecast = course.current_forecast or 0

        if not skill_ids:
            return {'prev': prev_forecast, 'new': prev_forecast}

        skills_rows = StudentSkill.query.filter(
            StudentSkill.student_id == course.student_id,
            StudentSkill.skill_id.in_(skill_ids),
        ).all()

        if not skills_rows:
            return {'prev': prev_forecast, 'new': prev_forecast}

        avg_mastery = sum(int(r.mastery_percent or 0) for r in skills_rows) / max(len(skills_rows), 1)

        target = course.target_score or 80
        start = course.starting_forecast or 40

        calc_forecast = int(round(start + (target - start) * (avg_mastery / 100.0)))
        new_forecast = max(start, min(100, calc_forecast))

        course.current_forecast = new_forecast
        course.forecast_low = max(0, new_forecast - 6)
        course.forecast_high = min(100, new_forecast + 5)

        return {
            'prev': prev_forecast,
            'new': new_forecast,
            'low': course.forecast_low,
            'high': course.forecast_high,
            'avg_mastery': round(avg_mastery, 1),
        }
