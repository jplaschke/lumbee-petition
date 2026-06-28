from flask_wtf import FlaskForm
from flask_wtf.file import FileField, FileAllowed
from wtforms import StringField, PasswordField, SubmitField, TextAreaField, IntegerField, BooleanField
from wtforms.validators import DataRequired, Email, Optional, Length
# Change your WTForms imports at the top of app/forms.py to this:
from flask_wtf import FlaskForm

class SignatureForm(FlaskForm):
    full_name     = StringField('Full Legal Name', validators=[DataRequired()])
    enrollment_id = StringField('Enrollment ID', validators=[DataRequired()])
    email         = StringField('Email Address', validators=[DataRequired()])
    phone         = StringField('Phone Number')
    
    # 📜 THE LEGAL CONSENT CHECKBOX
    # Setting 'validators=[DataRequired()]' forces the box to be checked to pass validation
    legal_consent = BooleanField(
        'I certify under penalty of perjury that I am an enrolled member of the Lumbee Tribe of North Carolina, and by checking this box, I am providing my legally binding digital signature equivalent to a wet signature.',
        validators=[DataRequired(message="You must accept the legal certification to sign this petition.")]
    )
    
    submit = SubmitField('Sign Petition')

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
