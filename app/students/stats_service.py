"""
Сервис для расчета аналитики по ученику
Собирает данные для графиков: GPA, динамика, навыки (радар), посещаемость
"""
import logging
from datetime import datetime, timedelta
from sqlalchemy import func, and_, case
from app.models import (
    db, Student, Lesson, LessonTask, Tasks, Topic, task_topics,
    StudentTaskStatistics, moscow_now, Submission, Answer, AssignmentTask, Assignment
)
from app.students.utils import get_sorted_assignments

logger = logging.getLogger(__name__)

class StatsService:
    """Сервис для расчета статистики ученика"""
    
    def __init__(self, student_id):
        """Инициализация сервиса для конкретного ученика"""
        self.student_id = student_id
        self.student = Student.query.get_or_404(student_id)
        self._lessons_cache = None
    
    def _get_lessons(self):
        """Кэшированная загрузка уроков с заданиями"""
        if self._lessons_cache is None:
            self._lessons_cache = Lesson.query.filter_by(student_id=self.student_id).options(
                db.joinedload(Lesson.homework_tasks).joinedload(LessonTask.task)
            ).all()
        return self._lessons_cache

    def _get_submissions(self):
        """Кэшированная загрузка работ (Assignments/Submissions) с ответами."""
        if getattr(self, '_submissions_cache', None) is None:
            self._submissions_cache = (
                Submission.query
                .filter(Submission.student_id == self.student_id)
                .options(
                    db.joinedload(Submission.assignment),
                    db.joinedload(Submission.answers)
                      .joinedload(Answer.assignment_task)
                      .joinedload(AssignmentTask.task)
                      .joinedload(Tasks.topics),
                )
                .all()
            )
        return self._submissions_cache

    def _iter_scored_items(self):
        """
        Унифицированный поток "проверенных" элементов для метрик/навыков:
        - LessonTask (классная комната)
        - Answer внутри Submission (работы)
        Yields: (is_correct: bool|None, score_ratio: float|None, weight: float, topics: list[Topic])
        """
        lessons = self._get_lessons()
        for lesson in lessons:
            for assignment_type in ['homework', 'classwork', 'exam']:
                assignments = get_sorted_assignments(lesson, assignment_type)
                weight = 2.0 if assignment_type == 'exam' else 1.0
                for lt in assignments:
                    st = (getattr(lt, 'status', None) or '').lower()
                    if lt.submission_correct is None:
                        continue
                    if st not in ['submitted', 'graded', 'returned', '']:
                        continue
                    topics = []
                    try:
                        topics = list(lt.task.topics) if (lt.task and hasattr(lt.task, 'topics') and lt.task.topics) else []
                    except Exception:
                        topics = []
                    yield (bool(lt.submission_correct), None, weight, topics)

        subs = self._get_submissions()
        for sub in subs:
            # Считаем только те ответы, где есть результат проверки
            try:
                atype = (sub.assignment.assignment_type if sub.assignment else None) or 'homework'
            except Exception:
                atype = 'homework'
            weight = 2.0 if atype == 'exam' else 1.0
            for ans in (sub.answers or []):
                if ans is None:
                    continue
                if ans.is_correct is None and ans.score is None:
                    continue
                topics = []
                try:
                    t = ans.assignment_task.task if ans.assignment_task else None
                    topics = list(t.topics) if (t and hasattr(t, 'topics') and t.topics) else []
                except Exception:
                    topics = []
                if ans.is_correct is not None:
                    yield (bool(ans.is_correct), None, weight, topics)
                else:
                    # если есть баллы — считаем "правильно" только при 100% на задачу
                    try:
                        mx = int(ans.max_score or 0)
                        sc = int(ans.score or 0)
                        ratio = (sc / mx) if mx > 0 else 0.0
                        yield (sc == mx and mx > 0, ratio, weight, topics)
                    except Exception:
                        yield (None, None, weight, topics)
    
    def get_gpa_trend(self, period_days=90):
        """
        Получить динамику среднего балла за период
        Возвращает: {'dates': [...], 'scores': [...]}
        """
        lessons = self._get_lessons()
        now = moscow_now()
        start_date = now - timedelta(days=period_days)
        
        # Группируем оценки по неделям
        weekly_scores = {}
        
        for lesson in lessons:
            if not lesson.lesson_date:
                continue
            
            lesson_date = lesson.lesson_date
            if lesson_date.tzinfo:
                lesson_date = lesson_date.replace(tzinfo=None)

            # Не берем будущие уроки в тренд
            now_naive = now.replace(tzinfo=None) if now.tzinfo else now
            if lesson_date > now_naive:
                continue
            
            if lesson_date < start_date.replace(tzinfo=None):
                continue
            
            # Группируем по неделям (начало недели как ключ)
            week_start = lesson_date - timedelta(days=lesson_date.weekday())
            week_key = week_start.strftime('%Y-%m-%d')
            
            # Собираем оценки из заданий урока
            lesson_scores = []
            for assignment_type in ['homework', 'classwork', 'exam']:
                assignments = get_sorted_assignments(lesson, assignment_type)
                for lt in assignments:
                    st = (getattr(lt, 'status', None) or '').lower()
                    # В тренде учитываем только реально сданные/проверенные/возвращенные задачи
                    if lt.submission_correct is not None and (st in ['submitted', 'graded', 'returned'] or st == ''):
                        # Оценка: 1 если правильно, 0 если неправильно
                        score = 1.0 if lt.submission_correct else 0.0
                        weight = 2.0 if assignment_type == 'exam' else 1.0
                        lesson_scores.append((score, weight))
            
            if lesson_scores:
                # Средний балл за урок (с учетом весов)
                total_weight = sum(w for _, w in lesson_scores)
                avg_score = sum(s * w for s, w in lesson_scores) / total_weight if total_weight > 0 else 0
                
                if week_key not in weekly_scores:
                    weekly_scores[week_key] = []
                weekly_scores[week_key].append(avg_score)
        
        # Вычисляем средний балл за каждую неделю
        dates = []
        scores = []
        
        for week_key in sorted(weekly_scores.keys()):
            week_avg = sum(weekly_scores[week_key]) / len(weekly_scores[week_key])
            dates.append(week_key)
            scores.append(round(week_avg * 100, 1))  # В процентах
        
        return {'dates': dates, 'scores': scores}
    
    def get_skills_map(self):
        """
        Получить карту навыков (радар-чарт)
        Возвращает: {'labels': [...], 'values': [...]}
        """
        # Собираем статистику по темам
        topic_stats = {}  # {topic_id: {'correct': 0, 'total': 0, 'name': ''}}

        for is_correct, _ratio, weight, topics in self._iter_scored_items():
            if not topics:
                continue
            for topic in topics:
                try:
                    topic_id = topic.topic_id
                    topic_name = topic.name
                except Exception:
                    continue
                if topic_id not in topic_stats:
                    topic_stats[topic_id] = {'name': topic_name, 'correct': 0, 'total': 0}
                topic_stats[topic_id]['total'] += weight
                if is_correct is True:
                    topic_stats[topic_id]['correct'] += weight
        
        # Вычисляем проценты
        labels = []
        values = []
        
        for topic_id, stats in sorted(topic_stats.items(), key=lambda x: x[1]['name']):
            if stats['total'] > 0:
                percent = round((stats['correct'] / stats['total']) * 100, 1)
                labels.append(stats['name'])
                values.append(percent)
        
        return {'labels': labels, 'values': values}
    
    def get_attendance_pie(self):
        """
        Получить данные для круговой диаграммы посещаемости
        Возвращает: {'labels': [...], 'values': [...]}
        """
        lessons = self._get_lessons()
        
        status_counts = {
            'completed': 0,
            'planned': 0,
            'canceled_student': 0,
            'missed': 0,
            'rescheduled': 0,
            'in_progress': 0,
            'cancelled': 0
        }
        
        for lesson in lessons:
            status = lesson.status or 'planned'
            # Нормализуем статусы
            if status == 'cancelled':
                status = 'canceled_student'
            status_counts[status] = status_counts.get(status, 0) + 1
        
        # Формируем данные для графика
        labels = []
        values = []
        
        label_map = {
            'completed': 'Проведено',
            'planned': 'Запланировано',
            'canceled_student': 'Отменено учеником',
            'missed': 'Пропущено',
            'rescheduled': 'Перенесено',
            'in_progress': 'В процессе',
            'cancelled': 'Отменено'
        }
        
        for status, count in status_counts.items():
            if count > 0:
                labels.append(label_map.get(status, status))
                values.append(count)
        
        return {'labels': labels, 'values': values}
    
    def get_gpa_by_type(self):
        """
        Получить GPA отдельно по типам работ (ДЗ vs Контрольные)
        Возвращает: {'homework': %, 'exam': %, 'overall': %}
        """
        lessons = self._get_lessons()
        
        hw_score = 0
        hw_weight = 0
        exam_score = 0
        exam_weight = 0
        total_score = 0
        total_weight = 0
        
        for lesson in lessons:
            # Домашние задания
            hw_assignments = get_sorted_assignments(lesson, 'homework')
            for lt in hw_assignments:
                if lt.submission_correct is not None:
                    hw_weight += 1
                    total_weight += 1
                    if lt.submission_correct:
                        hw_score += 1
                        total_score += 1
            
            # Контрольные работы
            exam_assignments = get_sorted_assignments(lesson, 'exam')
            for lt in exam_assignments:
                if lt.submission_correct is not None:
                    exam_weight += 2  # Контрольные с весом 2
                    total_weight += 2
                    if lt.submission_correct:
                        exam_score += 2
                        total_score += 2
        
        hw_gpa = round((hw_score / hw_weight * 100), 1) if hw_weight > 0 else 0
        exam_gpa = round((exam_score / exam_weight * 100), 1) if exam_weight > 0 else 0
        overall_gpa = round((total_score / total_weight * 100), 1) if total_weight > 0 else 0
        
        return {
            'homework': hw_gpa,
            'exam': exam_gpa,
            'overall': overall_gpa
        }
    
    def get_attendance_heatmap(self, weeks=52):
        """
        Получить данные для heatmap посещаемости (как на GitHub)
        Возвращает: {'dates': [...], 'values': [...], 'statuses': [...]}
        Формат: список дат и статусы уроков в этот день
        Статусы: 'completed' (проведен), 'canceled_teacher' (отменен учителем), 'canceled_student' (отменен учеником)
        """
        lessons = self._get_lessons()
        now = moscow_now()
        start_date = now - timedelta(weeks=weeks)
        
        # Группируем уроки по датам
        date_statuses = {}  # {date: 'completed' | 'canceled_teacher' | 'canceled_student' | None}
        
        for lesson in lessons:
            if not lesson.lesson_date:
                continue
            
            lesson_date = lesson.lesson_date
            if lesson_date.tzinfo:
                lesson_date = lesson_date.replace(tzinfo=None)
            
            if lesson_date < start_date.replace(tzinfo=None):
                continue
            
            # Используем дату без времени как ключ
            date_key = lesson_date.date().isoformat()
            
            # Определяем статус урока
            status = lesson.status or 'planned'
            if status == 'cancelled':
                status = 'canceled_student'
            
            # Маппинг статусов на три состояния
            status_map = {
                'completed': 'completed',  # Проведен
                'in_progress': 'completed',  # В процессе считаем как проведен
                'missed': 'canceled_student',  # Пропуск считаем как отменен учеником
                'canceled_student': 'canceled_student',  # Отменен учеником
                'rescheduled': None,  # Перенесенные не показываем
                'planned': None  # Запланированные не показываем
            }
            
            mapped_status = status_map.get(status)
            
            # Если для этой даты уже есть статус, приоритет: completed > canceled_student > canceled_teacher
            if date_key not in date_statuses or mapped_status == 'completed':
                date_statuses[date_key] = mapped_status
        
        # Формируем список дат и значений
        dates = []
        values = []  # Для совместимости, но не используется
        statuses = []  # Реальные статусы
        
        current_date = start_date.date()
        end_date = now.date()
        
        while current_date <= end_date:
            date_key = current_date.isoformat()
            dates.append(date_key)
            status = date_statuses.get(date_key)
            statuses.append(status)
            # Для совместимости со старым кодом
            values.append(1 if status == 'completed' else (-1 if status == 'canceled_student' else 0))
            current_date += timedelta(days=1)
        
        return {
            'dates': dates,
            'values': values,
            'statuses': statuses
        }
    
    def get_submission_punctuality(self):
        """
        Получить данные о пунктуальности сдачи ДЗ
        Анализ времени загрузки ДЗ относительно дедлайна
        Возвращает: {'early': N, 'on_time': N, 'late': N, 'total': N}
        """
        lessons = self._get_lessons()
        
        early_count = 0
        on_time_count = 0
        late_count = 0
        total_count = 0
        
        for lesson in lessons:
            hw_assignments = get_sorted_assignments(lesson, 'homework')
            
            for lt in hw_assignments:
                # Проверяем только задания с загруженными ответами
                if lt.submission_correct is None:
                    continue
                
                total_count += 1
                
                # Если есть дата загрузки, сравниваем с датой урока
                if lesson.lesson_date and hasattr(lt, 'submitted_at') and lt.submitted_at:
                    lesson_date = lesson.lesson_date
                    if lesson_date.tzinfo:
                        lesson_date = lesson_date.replace(tzinfo=None)
                    
                    submitted_at = lt.submitted_at
                    if submitted_at.tzinfo:
                        submitted_at = submitted_at.replace(tzinfo=None)
                    
                    # Считаем разницу в днях
                    days_diff = (submitted_at.date() - lesson_date.date()).days
                    
                    if days_diff < 0:
                        # Сдано заранее (до урока)
                        early_count += 1
                    elif days_diff <= 1:
                        # Сдано вовремя (в день урока или на следующий день)
                        on_time_count += 1
                    else:
                        # Сдано с опозданием
                        late_count += 1
                else:
                    # Если нет данных о времени загрузки, считаем "вовремя"
                    on_time_count += 1
        
        return {
            'early': early_count,
            'on_time': on_time_count,
            'late': late_count,
            'total': total_count
        }
    
    def get_summary_metrics(self):
        """
        Получить сводные метрики для карточек
        Возвращает словарь с метриками
        """
        lessons = self._get_lessons()

        # Общий GPA (процент выполнения работ) — учитываем и уроки, и "работы" (Submissions)
        total_score = 0.0
        total_weight = 0.0

        for is_correct, _ratio, weight, _topics in self._iter_scored_items():
            if is_correct is None:
                continue
            total_weight += float(weight or 1.0)
            if is_correct:
                total_score += float(weight or 1.0)
        
        current_gpa = round((total_score / total_weight * 100), 1) if total_weight > 0 else 0
        
        # Процент сданных ДЗ (классная комната)
        total_hw = 0
        submitted_hw = 0
        
        for lesson in lessons:
            hw_assignments = lesson.homework_assignments
            total_hw += len(hw_assignments)
            submitted_hw += sum(1 for lt in hw_assignments if lt.submission_correct is not None)
        
        hw_submit_rate = round((submitted_hw / total_hw * 100), 1) if total_hw > 0 else 0
        
        # Дельта за последний месяц
        now = moscow_now()
        month_ago = now - timedelta(days=30)
        
        recent_scores = []
        old_scores = []
        
        for lesson in lessons:
            if not lesson.lesson_date:
                continue
            
            lesson_date = lesson.lesson_date
            if lesson_date.tzinfo:
                lesson_date = lesson_date.replace(tzinfo=None)
            
            is_recent = lesson_date >= month_ago.replace(tzinfo=None)
            
            for assignment_type in ['homework', 'classwork', 'exam']:
                assignments = get_sorted_assignments(lesson, assignment_type)
                for lt in assignments:
                    if lt.submission_correct is not None:
                        score = 1.0 if lt.submission_correct else 0.0
                        if is_recent:
                            recent_scores.append(score)
                        else:
                            old_scores.append(score)
        
        recent_avg = sum(recent_scores) / len(recent_scores) * 100 if recent_scores else 0
        old_avg = sum(old_scores) / len(old_scores) * 100 if old_scores else 0
        delta = round(recent_avg - old_avg, 1)
        
        # GPA по типам работ
        gpa_by_type = self.get_gpa_by_type()
        
        return {
            'current_gpa': current_gpa,
            'gpa_homework': gpa_by_type['homework'],
            'gpa_exam': gpa_by_type['exam'],
            'hw_submit_rate': hw_submit_rate,
            'delta': delta,
            'total_lessons': len(lessons),
            'completed_lessons': sum(1 for l in lessons if l.status == 'completed'),
            'missed_lessons': sum(1 for l in lessons if l.status == 'missed')
        }
    
    def get_problem_topics(self, threshold=60):
        """
        Получить список проблемных тем (ниже порога)
        Возвращает список словарей с информацией о теме
        """
        skills = self.get_skills_map()
        problem_topics = []
        
        for i, (label, value) in enumerate(zip(skills['labels'], skills['values'])):
            if value < threshold:
                # Находим topic_id по имени
                topic = Topic.query.filter_by(name=label).first()
                if topic:
                    problem_topics.append({
                        'id': topic.topic_id,
                        'name': label,
                        'avg_score': value
                    })
        
        # Сортируем по проценту (от худшего к лучшему)
        problem_topics.sort(key=lambda x: x['avg_score'])
        
        return problem_topics
