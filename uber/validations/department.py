from wtforms import validators
from wtforms.validators import ValidationError

from uber.config import c
from uber.forms.department import DepartmentInfo
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
