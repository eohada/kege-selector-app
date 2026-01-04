"""
Сервис для расчета аналитики по ученику
Собирает данные для графиков: GPA, динамика, навыки (радар), посещаемость
"""
import logging
from datetime import datetime, timedelta
from sqlalchemy import func, and_, case
from app.models import (
    db, Student, Lesson, LessonTask, Tasks, Topic, task_topics,
    StudentTaskStatistics, moscow_now
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
            # Берем только завершенные уроки за период
            if lesson.status != 'completed' or not lesson.lesson_date:
                continue
            
            lesson_date = lesson.lesson_date
            if lesson_date.tzinfo:
                lesson_date = lesson_date.replace(tzinfo=None)
            
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
                    if lt.submission_correct is not None:
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
        lessons = self._get_lessons()
        
        # Собираем статистику по темам
        topic_stats = {}  # {topic_id: {'correct': 0, 'total': 0, 'name': ''}}
        
        for lesson in lessons:
            # Обрабатываем все типы заданий
            for assignment_type in ['homework', 'classwork', 'exam']:
                assignments = get_sorted_assignments(lesson, assignment_type)
                weight = 2 if assignment_type == 'exam' else 1
                
                for lt in assignments:
                    if not lt.task or lt.submission_correct is None:
                        continue
                    
                    # Получаем темы задания
                    task_topics_list = lt.task.topics if hasattr(lt.task, 'topics') else []
                    
                    if not task_topics_list:
                        # Если у задания нет тем, пропускаем
                        continue
                    
                    for topic in task_topics_list:
                        topic_id = topic.topic_id
                        topic_name = topic.name
                        
                        if topic_id not in topic_stats:
                            topic_stats[topic_id] = {
                                'name': topic_name,
                                'correct': 0,
                                'total': 0
                            }
                        
                        topic_stats[topic_id]['total'] += weight
                        if lt.submission_correct:
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
    
    def get_summary_metrics(self):
        """
        Получить сводные метрики для карточек
        Возвращает словарь с метриками
        """
        lessons = self._get_lessons()
        
        # Общий GPA (средний балл)
        total_score = 0
        total_weight = 0
        
        for lesson in lessons:
            for assignment_type in ['homework', 'classwork', 'exam']:
                assignments = get_sorted_assignments(lesson, assignment_type)
                weight = 2 if assignment_type == 'exam' else 1
                
                for lt in assignments:
                    if lt.submission_correct is not None:
                        total_weight += weight
                        if lt.submission_correct:
                            total_score += weight
        
        current_gpa = round((total_score / total_weight * 100), 1) if total_weight > 0 else 0
        
        # Процент сданных ДЗ
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
        
        return {
            'current_gpa': current_gpa,
            'hw_submit_rate': hw_submit_rate,
            'delta': delta,
            'total_lessons': len(lessons),
            'completed_lessons': sum(1 for l in lessons if l.status == 'completed')
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
