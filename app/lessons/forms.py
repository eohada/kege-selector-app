"""
Формы для управления уроками
"""
from flask_wtf import FlaskForm
from wtforms import SelectField, IntegerField, TextAreaField, StringField, SubmitField, DateTimeLocalField, BooleanField
from wtforms.validators import DataRequired, Optional, NumberRange

def ensure_introductory_without_homework(lesson_form):
    """Гарантируем, что вводный урок остается без ДЗ"""
    if getattr(lesson_form, 'lesson_type', None) and lesson_form.lesson_type.data == 'introductory':
        lesson_form.homework.data = ''
        lesson_form.homework_status.data = 'not_assigned'

class LessonForm(FlaskForm):
    """Форма для создания и редактирования урока"""
    exam_course_id = SelectField('Программа подготовки', coerce=int, validators=[Optional()])
    lesson_type = SelectField('Тип урока', choices=[
        ('regular', '📚 Обычный урок'),
        ('exam', '✅ Проверочный урок'),
        ('introductory', '👋 Вводный урок')
    ], default='regular', validators=[DataRequired()])
    timezone = SelectField('Часовой пояс', choices=[
        ('moscow', '🕐 Московское время (МСК)'),
        ('tomsk', '🕐 Томское время (ТОМСК)')
    ], default='moscow', validators=[DataRequired()])
    lesson_date = DateTimeLocalField('Дата и время урока', format='%Y-%m-%dT%H:%M', validators=[DataRequired()])
    duration = IntegerField('Длительность (минуты)', default=60, validators=[DataRequired(), NumberRange(min=15, max=240)])
    status = SelectField('Статус', choices=[
        ('planned', 'Запланирован'),
        ('in_progress', 'Идет сейчас'),
        ('completed', 'Проведен'),
        ('cancelled', 'Отменен')
    ], validators=[DataRequired()])
    topic = StringField('Тема урока', validators=[Optional()])
    notes = TextAreaField('Заметки о уроке', validators=[Optional()])
    homework = TextAreaField('Домашнее задание', validators=[Optional()])
    homework_status = SelectField('Статус ДЗ', choices=[
        ('assigned_done', 'Задано, выполнено'),
        ('assigned_not_done', 'Задано, не выполнено'),
        ('not_assigned', 'Не задано')
    ], default='assigned_not_done', validators=[DataRequired()])
    student_late = BooleanField('Ученик опоздал на урок', default=False, validators=[Optional()])
    submit = SubmitField('Сохранить')

