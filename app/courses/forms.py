from flask_wtf import FlaskForm
from wtforms import StringField, TextAreaField, SelectField, IntegerField, SubmitField
from wtforms.validators import DataRequired, Optional, Length, NumberRange


class CourseForm(FlaskForm):
    title = StringField('Название курса', validators=[DataRequired(), Length(max=200)])
    subject = StringField('Предмет (опционально)', validators=[Optional(), Length(max=100)])
    description = TextAreaField('Описание (опционально)', validators=[Optional()])
    status = SelectField('Статус', choices=[
        ('active', 'Активен'),
        ('archived', 'В архиве'),
    ], default='active', validators=[DataRequired()])
    submit = SubmitField('Сохранить')


class CourseModuleForm(FlaskForm):
    title = StringField('Название модуля', validators=[DataRequired(), Length(max=200)])
    description = TextAreaField('Описание (опционально)', validators=[Optional()])
    order_index = IntegerField('Порядок (0..999)', default=0, validators=[DataRequired(), NumberRange(min=0, max=999)])
    submit = SubmitField('Сохранить')

