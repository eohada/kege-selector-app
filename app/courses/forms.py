from flask_wtf import FlaskForm
from wtforms import StringField, TextAreaField, SelectField, IntegerField, SubmitField, DateTimeLocalField, DateField
from wtforms.validators import DataRequired, Optional, Length, NumberRange


class CourseForm(FlaskForm):
    title = StringField('Название курса', validators=[DataRequired(), Length(max=200)])
    subject = StringField('Предмет (опционально)', validators=[Optional(), Length(max=100)])
    description = TextAreaField('Описание (опционально)', validators=[Optional()])
    learning_goal = TextAreaField('Цель курса', validators=[Optional(), Length(max=4000)])
    expected_result = TextAreaField('Ожидаемый результат ученика', validators=[Optional(), Length(max=4000)])
    target_score = IntegerField('Целевой балл', validators=[Optional(), NumberRange(min=1, max=100)])
    exam_date = DateField('Дата экзамена', validators=[Optional()])
    default_lesson_duration = IntegerField('Стандартная длительность урока, минут', default=60, validators=[DataRequired(), NumberRange(min=15, max=240)])
    status = SelectField('Статус', choices=[
        ('active', 'Активен'),
        ('archived', 'В архиве'),
    ], default='active', validators=[DataRequired()])
    submit = SubmitField('Сохранить')


class CourseModuleForm(FlaskForm):
    title = StringField('Название модуля', validators=[DataRequired(), Length(max=200)])
    description = TextAreaField('Описание (опционально)', validators=[Optional()])
    learning_result = TextAreaField('Результат модуля', validators=[Optional(), Length(max=3000)])
    order_index = IntegerField('Порядок (0..999)', default=0, validators=[DataRequired(), NumberRange(min=0, max=999)])
    submit = SubmitField('Сохранить')


class CourseLessonForm(FlaskForm):
    module_id = SelectField('Модуль', coerce=int, validators=[Optional()])
    topic = StringField('Тема урока', validators=[DataRequired(), Length(max=300)])
    course_order_index = IntegerField('Порядок урока в программе', default=10, validators=[DataRequired(), NumberRange(min=0, max=9999)])
    lesson_date = DateTimeLocalField('Дата и время', format='%Y-%m-%dT%H:%M', validators=[Optional()])
    duration = IntegerField('Длительность, минут', default=60, validators=[DataRequired(), NumberRange(min=15, max=240)])
    lesson_type = SelectField('Формат урока', choices=[
        ('regular', 'Практический урок'),
        ('exam', 'Проверочный урок'),
        ('introductory', 'Стартовый урок'),
    ], default='regular', validators=[DataRequired()])
    status = SelectField('Статус', choices=[
        ('draft', 'Черновик'),
        ('planned', 'В плане'),
        ('in_progress', 'Идёт сейчас'),
        ('completed', 'Проведён'),
        ('rescheduled', 'Перенесён'),
        ('skipped', 'Пропущен'),
        ('cancelled', 'Отменён'),
    ], default='planned', validators=[DataRequired()])
    scenario = TextAreaField('Сценарий урока', validators=[Optional(), Length(max=8000)])
    content = TextAreaField('Теория и материалы к уроку', validators=[Optional(), Length(max=12000)])
    homework = TextAreaField('Домашнее задание', validators=[Optional(), Length(max=8000)])
    teacher_note = TextAreaField('Заметка преподавателя', validators=[Optional(), Length(max=4000)])
    submit = SubmitField('Сохранить урок')
