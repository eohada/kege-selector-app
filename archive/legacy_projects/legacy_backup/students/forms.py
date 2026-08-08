"""
Формы для управления студентами
"""
from flask_wtf import FlaskForm
from wtforms import StringField, TextAreaField, SelectField, IntegerField, SubmitField
from wtforms.validators import DataRequired, Optional, NumberRange, ValidationError
from app.models import Student

# Вспомогательные функции
def normalize_school_class(raw_value):
    """Приводит входное значение класса к целому или None"""
    try:
        if raw_value in (None, '', '0', 0):
            return None
        class_int = int(raw_value)
        if 1 <= class_int <= 11:
            return class_int
    except (ValueError, TypeError):
        return None
    return None

def validate_platform_id_unique(form, field):
    """Валидатор для проверки уникальности platform_id"""
    if field.data:
        platform_id = field.data.strip()
        if platform_id:
            # При создании нового студента form._student_id не существует
            # При редактировании form._student_id содержит ID редактируемого студента
            student_id = getattr(form, '_student_id', None)
            existing_student = Student.query.filter_by(platform_id=platform_id).first()
            if existing_student and (student_id is None or existing_student.student_id != student_id):
                raise ValidationError(f'Ученик с ID "{platform_id}" уже существует! (Ученик: {existing_student.name})')

SCHOOL_CLASS_CHOICES = [(0, 'Не указан')]
SCHOOL_CLASS_CHOICES += [(i, f'{i} класс') for i in range(1, 12)]

class StudentForm(FlaskForm):
    """Форма для создания и редактирования студента"""
    name = StringField('Имя ученика', validators=[DataRequired()])
    platform_id = StringField('ID на платформе', validators=[Optional(), validate_platform_id_unique])

    target_score = IntegerField('Целевой балл', validators=[Optional(), NumberRange(min=0, max=100)])
    deadline = StringField('Сроки', validators=[Optional()])
    goal_text = TextAreaField('Цель (текст)', validators=[Optional()])
    programming_language = StringField('Язык программирования', validators=[Optional()])

    diagnostic_level = StringField('Уровень знаний (диагностика)', validators=[Optional()])
    preferences = TextAreaField('Предпочтения в решении', validators=[Optional()])
    strengths = TextAreaField('Сильные стороны', validators=[Optional()])
    weaknesses = TextAreaField('Слабые стороны', validators=[Optional()])
    overall_rating = StringField('Общая оценка', validators=[Optional()])

    description = TextAreaField('Краткое описание', validators=[Optional()])
    notes = TextAreaField('Дополнительные заметки', validators=[Optional()])
    category = SelectField('Категория', choices=[
        ('', 'Не выбрано'),
        ('ЕГЭ', 'ЕГЭ'),
        ('ОГЭ', 'ОГЭ'),
        ('ЛЕВЕЛАП', 'ЛЕВЕЛАП'),
        ('ПРОГРАММИРОВАНИЕ', 'ПРОГРАММИРОВАНИЕ')
    ], default='', validators=[Optional()])
    school_class = SelectField('Класс', choices=SCHOOL_CLASS_CHOICES, default=0, coerce=int, validators=[Optional()])

    submit = SubmitField('Сохранить')

