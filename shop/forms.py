from flask_wtf import FlaskForm
from wtforms import BooleanField, EmailField, PasswordField, StringField
from wtforms.validators import DataRequired, Email, EqualTo, Length

MIN_PASSWORD_LENGTH = 8


def _strip(value: str | None) -> str | None:
    return value.strip() if isinstance(value, str) else value


class RegisterForm(FlaskForm):
    name = StringField("Name", filters=[_strip], validators=[DataRequired(), Length(max=100)])
    email = EmailField("Email", filters=[_strip], validators=[DataRequired(), Email(), Length(max=255)])
    password = PasswordField(
        "Password", validators=[DataRequired(), Length(min=MIN_PASSWORD_LENGTH, max=128)]
    )
    confirm = PasswordField(
        "Confirm password",
        validators=[DataRequired(), EqualTo("password", message="Passwords must match.")],
    )


class LoginForm(FlaskForm):
    email = EmailField("Email", filters=[_strip], validators=[DataRequired(), Email(), Length(max=255)])
    password = PasswordField("Password", validators=[DataRequired(), Length(max=128)])
    remember = BooleanField("Keep me signed in")
