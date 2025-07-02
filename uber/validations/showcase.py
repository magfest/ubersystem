from wtforms import validators
from wtforms.validators import ValidationError

from uber.config import c
from uber.forms.showcase import (StudioInfo, DeveloperInfo, MivsGameInfo, MivsDemoInfo, MivsConsents, MivsCode, MivsScreenshot,
                                 ArcadeGameInfo, ArcadeConsents, ArcadeLogistics)
from uber.model_checks import validation
from uber.utils import localized_now


StudioInfo.field_validation.required_fields = {
    'name': "Please enter a name for your studio.",
}


DeveloperInfo.field_validation.required_fields = {
    'first_name': "Please provide a first name.",
    'last_name': "Please provide a last name.",
    'email': "Please enter an email address.",
    'cellphone': ('Please provide a phone number.', 'gets_emails'),
    'agreed_coc': "You must agree to be bound by our Code of Conduct.",
    'agreed_data_policy': "You must agree for your information to be used for determining showcase selection.",
}


@DeveloperInfo.new_or_changed('gets_emails')
def at_least_one_contact(form, field):
    if not field.data and form.model.studio and len(form.model.studio.primary_contacts) == 1:
        raise ValidationError("Your studio must have at least one presenter who receives emails.")


MivsGameInfo.field_validation.required_fields = {
    'title': "Please enter this game's title.",
    'brief_description': "Please provide a brief description of this game.",
    'description': "Please provide a full description of this game.",
    'genres': "Please choose at least one genre, or describe a custom genre.",
    'platforms': "Please choose at least one platform for this game's demo, or enter a custom platform.",
    'player_count': ("Please describe how many players this game supports.", 'has_multiplayer'),
    'warning_desc': ("Please detail the content or trigger warning(s) for this game.", 'content_warning'),
}


MivsGameInfo.field_validation.validations['brief_description']['length'] = validators.Length(
    max=80, message="Your brief description cannot be more than 80 characters long.")
MivsGameInfo.field_validation.validations['description']['length'] = validators.Length(
    max=500, message="Your game's description cannot be more than 500 characters long.")


MivsDemoInfo.field_validation.required_fields = {
    'link_to_video': "Please provide a link to a video showing this game's gameplay.",
    'link_to_game': "Please provide a download link for this game.",
    'password_to_game': ("Please provide a password for downloading this game.", 'no_password', lambda x: not x),
    'code_instructions': ("Please include instructions for how the judges are to use the code(s) you provide.",
                          'code_type', lambda x: x in c.MIVS_CODES_REQUIRING_INSTRUCTIONS),
}


MivsDemoInfo.field_validation.validations['how_to_play']['length'] = validators.Length(
    max=1000, message="Your instructions on how to play cannot be more than 1000 characters long.")
MivsDemoInfo.field_validation.validations['build_notes']['length'] = validators.Length(
    max=500, message="Your build notes cannot be more than 500 characters long.")


MivsConsents.field_validation.required_fields = {
    'agreed_liability': "You must agree to the liability waiver.",
    'agreed_showtimes': "You must confirm the showtimes for running a MIVS booth.",
}


MivsCode.field_validation.required_fields = {
    'code': "Please enter the code to access the game."
}


MivsScreenshot.field_validation.required_fields = {
    'description': "Please enter a description of this screenshot."
}


@MivsScreenshot.new_or_changed('image')
def image_required(form, field):
    if not field.data or not field.data.file:
        raise ValidationError("Please choose a file to upload.")


@MivsScreenshot.new_or_changed('image')
def image_is_image(form, field):
    if field.data and field.data.file:
        content_type = field.data.content_type.value
        if not content_type.startswith('image'):
            raise ValidationError("Our server did not recognize your upload as a valid image.")


@MivsScreenshot.new_or_changed('image')
def image_size(form, field):
    if field.data and field.data.file:
        field.data.file.seek(0)
        file_size = len(field.data.file.read()) / (1024 * 1024)
        field.data.file.seek(0)
        if file_size > 5:
            raise ValidationError("Please make sure your screenshot is under 5MB.")


ArcadeGameInfo.field_validation.required_fields = {
    'title': "Please enter a name for this game.",
    'primary_contact_id': "Please select a primary contact for this game.",
    'description': "Please provide a brief description for this game.",
    'link_to_video': "Please provide a link to footage of people playing your game, and a password if required."
}


ArcadeConsents.field_validation.required_fields = {
    'agreed_showtimes': "You must verify that you will have someone onsite all weekend to set up and maintain this game.",
    'agreed_equipment': "You must verify that you will provide all necessary equipment for this game.",
    'agreed_liability': "You must verify that you will be responsible for the safety and security of your equipment."
}


ArcadeLogistics.field_validation.required_fields = {
    'game_hours': "Please let us know if this game can run for 72 consecutive hours.",
    'game_hours_text': ("Please explain your plan for keeping this game online during prime hours.",
                        'game_hours', lambda x: x == 'Other'),
    'game_end_time': "Please let us know if you can keep this game running until our standard end time.",
    'player_count': "Please select how many players this game is designed for.",
    'floorspace': "Please select your estimated required floorspace.",
    'floorspace_text': ("Please provide approximate width/depth measurements for your required floorspace.",
                        'floorspace', lambda x: x == c.OTHER),
    'cabinet_type': "Please select your cabinet/installation type.",
    'cabinet_type_text': ("Please describe your installation in detail, including exact measurements.",
                          'cabinet_type', lambda x: x == c.OTHER),
    'sanitation_requests': ("Please describe the special considerations this game has regarding sanitation.",
                            'sanitation'),
    'transit_needs': (f"Please describe what you need help with in transporting this game to {c.EVENT_NAME}.",
                      'needs_transit'),
    'read_faq': "Please prove that you read our FAQ.",
}