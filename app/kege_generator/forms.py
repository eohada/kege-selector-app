"""
Формы для генератора КЕГЭ
"""
from flask_wtf import FlaskForm
from wtforms import SelectField, IntegerField, BooleanField, StringField, SubmitField
from wtforms.validators import DataRequired, NumberRange

class TaskSelectionForm(FlaskForm):
    """Форма выбора заданий для генерации"""
    task_type = SelectField('Номер задания', coerce=int, validators=[DataRequired()])
    limit_count = IntegerField('Количество заданий', validators=[DataRequired(), NumberRange(min=1, max=20, message="От 1 до 20")])
    use_skipped = BooleanField('Включить пропущенные задания', default=False)
    submit = SubmitField('Сгенерировать Набор')

class ResetForm(FlaskForm):
    """Форма сброса истории"""
    task_type_reset = SelectField('Сбросить историю для', coerce=str, validators=[DataRequired()])
    reset_type = SelectField('Тип сброса', coerce=str, choices=[
        ('accepted', 'Принятые'),
        ('skipped', 'Пропущенные'),
        ('blacklist', 'Черный список'),
        ('all', 'Все')
    ], validators=[DataRequired()])
    reset_submit = SubmitField('Сбросить')

class TaskSearchForm(FlaskForm):
    """Форма поиска задания по ID"""
    task_id = StringField('ID задания', validators=[DataRequired()], render_kw={'placeholder': 'Введите ID задания (например, 23715)'})
    search_submit = SubmitField('Найти и добавить')

