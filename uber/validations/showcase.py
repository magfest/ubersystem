from wtforms import validators
from wtforms.validators import ValidationError

from uber.config import c
from uber.forms.showcase import (StudioInfo, DeveloperInfo, MivsGameInfo, MivsDemoInfo, MivsConsents, MivsCode, MivsScreenshot,
                                 ArcadeGameInfo, ArcadeConsents, ArcadeLogistics, ArcadePhoto, RetroGameInfo, RetroGameDetails,
                                 RetroLogistics, RetroScreenshot, MivsJudgeInfo, JudgeShowcaseInfo, NewJudgeInfo, GameReview)
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
    'genres': ("Please choose at least one genre, or describe a custom genre.", 'genres_text', lambda x: not x.data),
    'platforms': ("Please choose at least one platform for this game's demo, or enter a custom platform.", 'platforms_text', lambda x: not x.data),
    'player_count': ("Please describe how many players this game supports.", 'has_multiplayer'),
    'warning_desc': ("Please detail the content or trigger warning(s) for this game.", 'content_warning'),
}


MivsGameInfo.field_validation.validations['genres']['optional'] = validators.Optional()
MivsGameInfo.field_validation.validations['platforms']['optional'] = validators.Optional()


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
    'game_end_time': ("Please let us know if you can keep this game running until our standard end time.",
                      'game_end_time', lambda x: x.data is None),
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


@ArcadePhoto.new_or_changed('image')
def image_required(form, field):
    if not field.data or not field.data.file:
        raise ValidationError("Please choose a file to upload.")


@ArcadePhoto.new_or_changed('image')
def image_is_image(form, field):
    if field.data and field.data.file:
        content_type = field.data.content_type.value
        if not content_type.startswith('image'):
            raise ValidationError("Our server did not recognize your upload as a valid image.")


@ArcadePhoto.new_or_changed('image')
def image_size(form, field):
    if field.data and field.data.file:
        field.data.file.seek(0)
        file_size = len(field.data.file.read()) / (1024 * 1024)
        field.data.file.seek(0)
        if file_size > 5:
            raise ValidationError("Please make sure your screenshot is under 5MB.")


RetroGameInfo.field_validation.required_fields = {
    'title': "Please enter a name for this game.",
    'primary_contact_id': "Please select a primary contact for this game.",
    'publisher_name': "Please enter the name of the publisher for this game, or N/A.",
    'brief_description': "Please provide a short description for this game.",
}


RetroGameDetails.field_validation.required_fields = {
    'genres': ("Please choose at least one genre, or describe a custom genre.", 'genres_text', lambda x: not x.data),
    'platforms': ("Please choose at least one release platform for this game, or enter a custom platform.", 'platforms_text', lambda x: not x.data),
    'release_date': "Please let us know if your game is available or approximately when it will release.",
    'description': "Please enter a full description for this game.",
    'link_to_video': "Please link to a gameplay video or trailer with at least 2-5 minutes of gameplay.",
    'link_to_game': "Please provide a link to the game Rom for our judges to review.",
    'how_to_play': "Please provide instructions for playing your game, include setup instructions and a list of controls.",
}


RetroGameDetails.field_validation.validations['genres']['optional'] = validators.Optional()
RetroGameDetails.field_validation.validations['platforms']['optional'] = validators.Optional()


@RetroGameDetails.new_or_changed('game_logo')
def game_logo_required(form, field):
    if not field.data or not field.data.file and not form.model.game_logo:
        raise ValidationError("Please upload a transparent PNG for your game logo.")


@RetroGameDetails.new_or_changed('game_logo')
def game_logo_is_image(form, field):
    if field.data and field.data.file:
        content_type = field.data.content_type.value
        if not content_type.startswith('image'):
            raise ValidationError(f"Your game logo ({field.data.filename}) is not a valid image.")


@RetroGameDetails.new_or_changed('game_logo')
def game_logo_size(form, field):
    if field.data and field.data.file:
        field.data.file.seek(0)
        file_size = len(field.data.file.read()) / (1024 * 1024)
        field.data.file.seek(0)
        if file_size > 5:
            raise ValidationError("Please make sure your game logo is under 5MB.")


RetroLogistics.field_validation.required_fields = {
    'in_person': (f"Please select whether you will be able to come to {c.EVENT_NAME_AND_YEAR} in person.",
                  'in_person', lambda x: x.data is None),
    'delivery_method': "Please tell us how you will get your game to the event.",
    'found_how': "Please let us know how you found out about the Indie Retro.",
}


@RetroScreenshot.new_or_changed('image')
def image_required(form, field):
    if not field.data or not field.data.file:
        raise ValidationError("Please choose a file to upload.")


@RetroScreenshot.new_or_changed('image')
def image_is_image(form, field):
    if field.data and field.data.file:
        content_type = field.data.content_type.value
        if not content_type.startswith('image'):
            raise ValidationError("Our server did not recognize your upload as a valid image.")


@RetroScreenshot.new_or_changed('image')
def image_size(form, field):
    if field.data and field.data.file:
        field.data.file.seek(0)
        file_size = len(field.data.file.read()) / (1024 * 1024)
        field.data.file.seek(0)
        if file_size > 5:
            raise ValidationError("Please make sure your screenshot is under 5MB.")

def is_mivs_judge(form):
    if form.is_admin and form.model.is_new:
        return
    return c.MIVS in form.model.showcases_ints


MivsJudgeInfo.field_validation.required_fields = {
    'platforms': ("Please select what platforms you own.", 'platforms', lambda x: is_mivs_judge(x.form)),
    'genres': ("Please select what genres you are familiar with.", 'genres', lambda x: is_mivs_judge(x.form)),
    'vr_text': ("Please tell us what VR/AR platforms you own.", 'platforms', lambda x: x.data and c.VR in x.data)
}


@MivsJudgeInfo.field_validation('platforms')
def must_have_pc(form, field):
    if not field.data:
        return

    if c.PC not in field.data and c.PCGAMEPAD not in field.data and is_mivs_judge(form):
        raise ValidationError("You must have a PC to judge for MIVS.")


JudgeShowcaseInfo.field_validation.required_fields = {
    'assignable_showcases': (
        "Please select at least one showcase for this judge, either for assigned games or all games.",
        'all_games_showcases', lambda x: not x)
}


NewJudgeInfo.field_validation.required_fields = {
    'first_name': "Please enter this judge's first name.",
    'last_name': "Please enter this judge's last name.",
    'email': "Please enter this judge's email address.",
}


def game_or_video_playable(form):
    if form.model.game.showcase_type == c.INDIE_ARCADE:
        return form.video_status.data == c.VIDEO_REVIEWED
    return form.game_status.data == c.PLAYABLE


GameReview.field_validation.required_fields = {
    'read_how_to_play': ("Please confirm you've read the instructions for how to play.", 
                         'game_status', lambda x: x.data == c.PLAYABLE and x.form.model.game.how_to_play),
    'readiness_score': ("Please rate the game's show readiness from 1-10.", 'readiness_score',
                        lambda x: game_or_video_playable(x.form)),
    'design_score': ("Please rate the game's design from 1-10.", 'design_score',
                        lambda x: game_or_video_playable(x.form)),
    'enjoyment_score': ("Please rate the game's enjoyment from 1-10.", 'enjoyment_score',
                        lambda x: game_or_video_playable(x.form)),
}


@GameReview.field_validation('video_status')
def must_review_video_or_game(form, field):
    if field.data == c.PENDING and (form.model.game.showcase_type == c.INDIE_ARCADE or form.game_status.data == c.PENDING):
        raise ValidationError("Please tell us if you were able to view the video or download and play the game.")


@GameReview.field_validation('video_status')
def cant_review_broken_video(form, field):
    if form.model.game.showcase_type != c.INDIE_ARCADE or field.data == c.PENDING:
        return
    has_scores = form.readiness_score.data or form.design_score.data or form.enjoyment_score.data

    if field.data != c.VIDEO_REVIEWED and has_scores:
        raise ValidationError("If the video is not playable, please leave the score fields blank.")


@GameReview.field_validation('game_status')
def cant_review_broken_or_pending_game(form, field):
    if form.model.game.showcase_type == c.INDIE_ARCADE:
        return
    has_scores = form.readiness_score.data or form.design_score.data or form.enjoyment_score.data

    if field.data != c.PLAYABLE and has_scores:
        if field.data == c.PENDING:
            raise ValidationError("Please leave the score fields blank until you have played the game.")
        raise ValidationError("If the game is not playable, please leave the score fields blank.")

