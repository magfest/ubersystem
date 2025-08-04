from wtforms import validators
from wtforms.validators import ValidationError

from uber.config import c
from uber.forms.department import DepartmentInfo, BulkPrintingRequestInfo
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
