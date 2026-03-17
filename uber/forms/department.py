import cherrypy
from datetime import date

from markupsafe import Markup
from wtforms import (BooleanField, DateField, EmailField,
                     HiddenField, SelectField, SelectMultipleField, IntegerField,
                     StringField, TimeField, validators, TextAreaField)
from wtforms.validators import ValidationError, StopValidation

from uber.config import c
from uber.forms import (MultiCheckbox, MagForm, SelectBooleanField, DateTimePicker, HourMinuteDuration,
                        SelectDynamicChoices, HiddenIntField, CustomValidation, Ranking)
from uber.custom_tags import popup_link
from uber.badge_funcs import get_real_badge_type
from uber.models import Job
from uber.model_checks import invalid_phone_number
from uber.utils import get_age_conf_from_birthday


__all__ = ['DepartmentInfo', 'JobInfo', 'JobTemplateInfo', 'BulkPrintingRequestInfo']


class DepartmentInfo(MagForm):
    admin_desc = True

    name = StringField('Name')
    description = StringField(
        'Description', description="Displayed to potential volunteers during registration.")
    solicits_volunteers = BooleanField("This department publically asks volunteers for help.")
    max_consecutive_minutes = IntegerField(
        "Max Consecutive Hours",
        description="The maximum number of consecutive hours a staffer may work. Enter 0 for no limit.")
    from_email = EmailField("Department Email")
    manages_panels = BooleanField("This department accepts panel applications.")
    handles_cash = BooleanField("Volunteers in this department handle cash and/or electronic payments.")
    panels_desc = TextAreaField(
        "Panel Application Description",
        description="What text, if any, should be shown when applying for a panel for this department?")
    parent_id = HiddenField()

    def populate_obj(self, obj, is_admin=False):
        max_minutes = self._fields.get('max_consecutive_minutes', None)
        if max_minutes and max_minutes.data:
            max_minutes.data = max_minutes.data * 60
        super().populate_obj(obj, is_admin)


class BaseJobInfo(MagForm):
    admin_desc = True

    name = StringField('Job Name')
    description = TextAreaField('Description')
    duration = IntegerField('Duration', widget=HourMinuteDuration())
    no_slots = BooleanField('This job is not available for signups.',
                            description="You will still be able to assign members of your department to this job.")
    extra15 = BooleanField("This job's shifts should last an extra 15 minutes unless being worked back-to-back.",
                           description="This can help ensure coverage in case the next shift arrives late.")
    weight = SelectField('Weight', coerce=str, choices=c.WEIGHT_OPTS, default='1.0',
                         description="A multiplier for how many hours volunteers are credited with when they work this job.")
    visibility = SelectField('Visibility', coerce=int, choices=Job._VISIBILITY_OPTS,
                             description="Controls who can see this job on their shift signups page.")
    required_roles_ids = SelectMultipleField('Required Roles', widget=MultiCheckbox(), validate_choice=False,
                                             description="Only volunteers assigned these roles can sign up OR be assigned to this job.")
    all_roles_required = SelectBooleanField(
        f'Role Requirement Type',
        yes_label='ALL of the roles above', no_label='ANY of the roles above')


class JobInfo(BaseJobInfo):
    job_template_id = SelectField('Template', widget=SelectDynamicChoices(), validate_choice=False)
    start_time = StringField('Start Time', widget=DateTimePicker())
    slots = IntegerField('Slots')


class JobTemplateInfo(BaseJobInfo):
    template_name = StringField('Template Name')
    type = SelectField('Template Type', coerce=int, choices=c.JOB_TEMPLATE_TYPE_OPTS)
    min_slots = IntegerField(
        'Minimum # Slots',
        description="This will not affect any jobs that are not available for signups.")
    days = SelectMultipleField('Working Days', coerce=int, choices=c.JOB_DAY_OPTS, widget=MultiCheckbox())
    open_time = TimeField('Daily Opening Time',
                          description="To start at midnight, enter 00:00am.")
    close_time = TimeField('Daily Closing Time',
                           description="To end at midnight, enter 11:59pm (or 23:59).")
    interval = IntegerField(
        'Interval', widget=HourMinuteDuration(),
        description="Creates a job at specified intervals until closing time. Jobs may go past closing time and may overlap."
    )

    def no_slots_label(self):
        return 'These jobs are not available to sign up for.'
    
    def no_slots_desc(self):
        return "This can only be set when creating a new template."
    
    def extra15_label(self):
        return "These jobs' shifts should last an extra 15 minutes unless being worked back-to-back."


class BulkPrintingRequestInfo(MagForm):
    admin_desc = True

    link = StringField("Link to Document")
    copies = IntegerField("Number of Copies")
    print_orientation = SelectField("Print Orientation", coerce=int, default=0,
                                    choices=[(0, "Please select an option")] + c.PRINT_ORIENTATION_OPTS)
    cut_orientation = SelectField("Cut Horizontally/Vertically?", coerce=int, default=0,
                                  choices=[(0, "Please select an option")] + c.CUT_ORIENTATION_OPTS)
    color = SelectField("Document Color", coerce=int, default=0,
                        choices=[(0, "Please select an option")] + c.PRINT_REQUEST_COLOR_OPTS)
    paper_type = SelectField("Paper Type", coerce=int, default=0,
                             choices=[(0, "Please select an option")] + c.PRINT_REQUEST_PAPER_TYPE_OPTS,
                             description="Select 'custom request' if you need, e.g., cardstock.")
    paper_type_text = StringField("Paper Type Description")
    size = SelectField("Print Size", coerce=int, default=0,
                       choices=[(0, "Please select an option")] + c.PRINT_REQUEST_SIZE_OPTS,
                       description="Select 'custom request' if you need anything besides 8.5x11\" sheets.")
    size_text = StringField("Width x Height", description="Please enter an exact size, e.g., '8.5x11 inches'.")
    double_sided = BooleanField("This document should be printed double-sided.",
                                description="If you want the same content on the front and back, please make sure your document has each page duplicated.")
    stapled = BooleanField("Please staple the pages of this document together.")
    notes = TextAreaField("Additional Information")
    important = BooleanField(
        "This document is vital to my department.",
        description="We will do our best to print all submitted documents, but this will help us prioritize the most important documents to print.")
    link_is_shared = BooleanField(
        Markup("<strong>I verify that I have checked the permissions of the link provided and made sure it is publicly accessible.</strong>"))