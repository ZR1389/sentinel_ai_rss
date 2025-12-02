from marshmallow import Schema, fields, validate, ValidationError, INCLUDE

# You can import your password strength checker
from utils.password_strength_utils import is_strong_password

def validate_password(password):
    if not is_strong_password(password):
        raise ValidationError("Password does not meet strength requirements.")

class RegisterSchema(Schema):
    email = fields.Email(required=True)
    password = fields.String(required=True, validate=validate_password)

class ResetPasswordSchema(Schema):
    email = fields.Email(required=True)
    code = fields.String(required=True, validate=validate.Length(equal=6))
    new_password = fields.String(required=True, validate=validate_password)

class ProfileSchema(Schema):
    profession = fields.String()
    employer = fields.String()
    destination = fields.String()
    travel_start = fields.Date()
    travel_end = fields.Date()
    means_of_transportation = fields.String()
    reason_for_travel = fields.String()
    custom_fields = fields.Dict()

class ChatSchema(Schema):
    query = fields.String(required=True, validate=validate.Length(min=1, max=500))
    region = fields.String(allow_none=True)
    type = fields.String(allow_none=True)
    user_email = fields.String(allow_none=True)
    lang = fields.String(allow_none=True)
    plan = fields.String(allow_none=True)
    session_id = fields.String(allow_none=True)

    class Meta:
        unknown = INCLUDE  # Accept any additional fields gracefully