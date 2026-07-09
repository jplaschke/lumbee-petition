from flask_wtf import FlaskForm
from flask_wtf.file import FileField, FileAllowed
from wtforms import StringField, PasswordField, SubmitField, TextAreaField, IntegerField, BooleanField
from wtforms.validators import DataRequired, Email, Optional, Length
# Change your WTForms imports at the top of app/forms.py to this:
from flask_wtf import FlaskForm

from flask_wtf import FlaskForm
# 🚨 IMPORT BOTH FileField AND FileRequired FOR THE MANDATORY UPLOAD
from flask_wtf.file import FileField, FileRequired, FileAllowed
from wtforms import StringField, SubmitField, BooleanField
from wtforms.validators import DataRequired

class SignatureForm(FlaskForm):
    full_name     = StringField('Full Legal Name', validators=[DataRequired()])
    enrollment_id = StringField('Enrollment ID', validators=[DataRequired()])

    # This field remains mandatory, but we will change its frontend label text
    id_upload     = FileField('Lumbee Membership ID', validators=[
        FileRequired(message="You must upload a photo of your ID to verify your signature."),
        FileAllowed(['jpg', 'jpeg', 'png', 'pdf'], 'Only images (jpg, png) or PDFs are allowed.')
    ])

    # UPDATED: Added DataRequired and Email validators to make it mandatory
    email         = StringField('Email Address', validators=[
        DataRequired(message="Email address is required."),
        Email(message="Please enter a valid email address.")
    ])
    phone         = StringField('Phone Number')

    legal_consent = BooleanField('Legal Consent', validators=[DataRequired()])
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


class OrdinanceUploadForm(FlaskForm):
    pdf_file    = FileField('Ordinance PDF', validators=[
        FileRequired(message="Please choose the ordinance PDF to upload."),
        FileAllowed(['pdf'], 'Only PDF files are allowed.')
    ])
    change_note = StringField('Change Note (optional)')
    submit      = SubmitField('Upload & Generate Hash')

