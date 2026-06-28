from flask_wtf import FlaskForm
from flask_wtf.file import FileField, FileAllowed
from wtforms import StringField, PasswordField, SubmitField, TextAreaField, IntegerField
from wtforms.validators import DataRequired, Email, Optional, Length

class SignatureForm(FlaskForm):
    full_name     = StringField('Full Name', validators=[DataRequired(), Length(max=200)])
    enrollment_id = StringField('Enrollment ID', validators=[DataRequired(), Length(max=100)])
    email         = StringField('Email', validators=[DataRequired(), Email()])
    phone         = StringField('Phone', validators=[Optional()])
    id_upload     = FileField('Upload Lumbee Member ID', validators=[FileAllowed(['jpg','jpeg','png','pdf'])])
    submit        = SubmitField('Sign Petition')

class LoginForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired()])
    password = PasswordField('Password', validators=[DataRequired()])
    submit   = SubmitField('Login')

class SettingsForm(FlaskForm):
    petition_title    = StringField('Petition Title', validators=[DataRequired()])
    petition_text     = TextAreaField('Petition Text', validators=[DataRequired()])
    target_signatures = IntegerField('Target Signatures', validators=[DataRequired()])
    background_color  = StringField('Background Color')
    header_image      = FileField('Header Image', validators=[FileAllowed(['jpg','jpeg','png','gif'])])
    background_image  = FileField('Background Image', validators=[FileAllowed(['jpg','jpeg','png','gif'])])
    submit            = SubmitField('Save Settings')
