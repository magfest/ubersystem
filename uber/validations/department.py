from wtforms import validators
from wtforms.validators import ValidationError, StopValidation

from uber.config import c
from uber.forms.department import DepartmentInfo, BulkPrintingRequestInfo, BaseJobInfo, JobInfo, JobTemplateInfo
from uber.models import Session, Department
from uber.model_checks import validation
from uber.utils import localized_now


DepartmentInfo.field_validation.required_fields = {
    'name': "Please provide a department name.",
    'description': "Please provide a description of this department.",
}


DepartmentInfo.field_validation.validations['from_email']['optional'] = validators.Optional()


@DepartmentInfo.new_or_changed('name')
def unique_name(form, field):
    if field.data:
        with Session() as session:
            dupe_dept_name = session.query(Department).filter(Department.name == field.data).first()
            if dupe_dept_name:
                raise ValidationError("There is already another department with this name.")


BaseJobInfo.field_validation.required_fields = {
    'name': "Please provide a job name.",
    'description': "Please provide a job description.",
}


JobInfo.field_validation.required_fields = {
    'start_time': "Please select a start time.",
    'duration': "Please enter a duration.",
    'slots': ("Please enter the number of signup slots, or confirm that this job should not be available for signups.",
              'no_slots', lambda x: not x),
}


JobTemplateInfo.field_validation.required_fields = {
    'template_name': "Please enter a name for this template.",
    'days': ("Please select at least one day to create jobs for.", 'type', lambda x: x != c.CUSTOM),
    'open_time': ("Please specify an opening time.", 'type', lambda x: x != c.CUSTOM),
    'close_time': ("Please specify a closing time.", 'type', lambda x: x != c.CUSTOM),
    'duration': ("Please specify a duration.", 'type', lambda x: x != c.CUSTOM),
    'interval': ("Please enter an interval for creating new job, or select another template type.",
                 'type', lambda x: x == c.INTERVAL)
}


JobTemplateInfo.field_validation.validations['min_slots']['optional'] = validators.Optional()
JobTemplateInfo.field_validation.validations['open_time']['optional'] = validators.Optional()
JobTemplateInfo.field_validation.validations['close_time']['optional'] = validators.Optional()


@JobTemplateInfo.field_validation('close_time')
def close_after_open(form, field):
    open_time = getattr(form, 'open_time').data

    if not field.data or not open_time:
        return

    if field.data == open_time:
        raise StopValidation(f"The opening and closing time cannot be the same.")
    if field.data < open_time:
        raise StopValidation(f"The opening time must be before the closing time.")


BulkPrintingRequestInfo.field_validation.required_fields = {
    'link': "Please provide a link to the document.",
    'copies': "Please enter how many copies of the document should be printed.",
    'print_orientation': "Please select which orientation to print this document.",
    'cut_orientation': "Please specify how this document should be cut, or if it should not be cut.",
    'color': "Please select what color mode to print this document in.",
    'paper_type': "Please select the type of paper to print this document on.",
    'paper_type_text': ("Please describe the type of custom paper to use for this document.",
                        'paper_type', lambda x: x == c.CUSTOM),
    'size': "Please select the size of paper to print this document on.",
    'size_text': ("Please enter the width and height of paper to print this document on.",
                  'size', lambda x: x == c.CUSTOM),
    'link_is_shared': "Please verify that you have made sure the link to this document is publically viewable.",
}
