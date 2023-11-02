# Form Guide for Ubersystem/RAMS
NOTE: this guide is currently being built in Notion, below is a rough draft.

Forms represent the vast majority of attendees' (and many admins'!) interaction with Ubersystem. As such, they are highly dependent on business logic and are often complex. A single field may be required under some conditions but not others, change its labeling in some contexts, show help text to attendees but not admins, etc. This guide is to help you understand, edit, and override forms without creating a giant mess. Hopefully.

## Forms Are a WIP
Up until the writing of this guide, all forms in Ubersystem were driven entirely by Jinja2 macros, jQuery, and HTML, with form handling done largely inside individual page handlers (with the exception of validations, which were all in **model_checks.py**). As of 2023, *attendee* and *group* forms are the only forms that use the technologies and conventions described below, unless otherwise noted. Conversion of other forms is ongoing, and help with those conversions is extremely welcome.

## How Forms Are Built
We rely on the following frameworks and modules for our forms:
- [WTForms](https://wtforms.readthedocs.io/en/3.0.x/) defines our forms as declarative data, along with many of their static properties. Each set of forms is organized in one file per type of entity, similar to our **models** folder, and they are found in **uber/forms/**. Inherited classes and other WTForms customizations are in **uber/forms/__init__.py**.
- [Jinja2](https://jinja.palletsprojects.com/en/3.1.x/templates/) provides *macros* that render the scaffolding for fields (these macros call WTForms to render the fields themselves) and *blocks* that define sections of forms for appending fields or overriding.
  - Form macros are found in **uber/template/forms/macros.html** -- always use these macros rather than writing your own scaffolding.
- [Bootstrap 5](https://getbootstrap.com/docs/5.0/) provides the styling and responsive layout for forms. Always use the grid layout ("col" divs contained inside "row" divs) when adding fields.

## Form Validations
There are three broad categories of validations:
- Field-level validations: simple data validations, often [WTForm built-in validations](https://wtforms.readthedocs.io/en/3.0.x/validators/), which are passed to field constructors. These validations only have access to their form's data. Additional field validations are implemented using the `CustomValidation()`
- Custom validations: validations that require knowledge of the model or use complex calculations, and in some cases don't even correspond to any fields. For example, we check and make sure attendees don't have so many badge extras that their total is above $9,999, as that is Stripe's limit.
- "New or changed" validations: these are custom validations that only run if a specific field's data changed or if a model has not been saved to the database yet. For example, we check that a selected preordered merch package is still available, but only if the preordered merch field changed or the attendee is new.

### Some caveats
WTForms has a way to add custom validations to any field by adding a `validate_fieldname` function to a form. We avoid using this because it can only return one error, which is poor UX, and because it is difficult to override these validations in event plugins.

Field-level validations have an added bonus of rendering matching clientside validations where possible. However, we actually skip running clientside validations on our forms, again because they only show only one error at a time. Since we use AJAX for server validations and display all errors at once, clientside validations are rendered moot.

### Field-Level Validations
Adding a field-level validation involves simply passing the validator class(es) in a list through the field constructor's `validators` parameter. Let's take this `email` field as an example:
```
email = EmailField('Email Address', validators=[
    validators.InputRequired("Please enter an email address."),
    validators.Length(max=255, message="Email addresses cannot be longer than 255 characters."),
    validators.Email(granular_message=True),
    ],
    render_kw={'placeholder': 'test@example.com'})
```
This field has three field validations: a validator that requires the field not be empty, a validator that limits the email address to 255 characters, and a validator that checks the email address using the [email_validator package](https://pypi.org/project/email-validator/) and passes through the exact error message if the email fails validation.

For more about what validators are available, see [WTForms' documentation on built-in validators](https://wtforms.readthedocs.io/en/3.0.x/validators/). We may also at some point add our own field-level validators -- if so, they should be in **forms/validations.py**.

### Selectively Required Fields and `get_optional_fields`
Almost all required fields should have the `InputRequired` validator passed to their constructor rather than a custom validator to check their data. However, many fields are optional in certain circumstances, usually based on the model's current state. The special function `get_optional_fields` bridges this gap.

Let's look at a simple example of this function for a group.
```
class TableInfo(GroupInfo):
    name = StringField('Table Name', validators=[
        validators.InputRequired("Please enter a table name."),
        validators.Length(max=40, message="Table names cannot be longer than 40 characters.")
        ])
    description = StringField('Description', validators=[
        validators.InputRequired("Please provide a brief description of your business.")
        ], description="Please keep to one sentence.")
    // other fields

    def get_optional_fields(self, group, is_admin=False):
        optional_list = super().get_optional_fields(group, is_admin)
        if not group.is_dealer:
            optional_list.extend(
                ['description', 'website', 'wares', 'categories', 'address1', 'city', 'region', 'zip_code', 'country'])
        return optional_list
```
This function gets any optional fields from its parent class. Then, if the group's `is_dealer` property is false, it adds all of the form's dealer-related fields to the list of optional fields. Finally, it returns the list of optional fields. Based on this, a non-dealer group would be required to have a `name` but not a `description`.

The parameters are:
- `group`: a model object, e.g., `Attendee` or `Group`. This model will always be a "preview model" that has already had any form updates applied to it. For this reason, do _not_ check `group.is_new`, as the preview model is always "new".
- `is_admin`: a boolean that is True if the model is being viewed in the admin area; you'll almost never need it, but there are a few cases where fields are optional for admins when they would not be optional for attendees.

**NOTE**: If a field is returned by `get_optional_fields`, _all_ validations are skipped _only if_ the field is empty.

### Custom and New-Or-Changed Validations


## Adding Fields
First, figure out if you want to add fields to an existing form or if you want to add a new form. Multiple forms can be combined and processed seamlessly on a single page, so it is good to group like fields together into their own 'forms.' Pay particular attention to which fields represent personal identifying information (PII) and group them separately from fields that don't.

To declare a new form, [TODO]. To add fields to an existing form, [TODO].

https://wtforms.readthedocs.io/en/3.0.x/fields/

### Field Labels and Descriptions
By default, labels and descriptions for fields are simple strings with automatic escaping for HTML/XML. Since this is not always desirable, here are a few ways to write more complex labels:

- To include basic HTML (e.g., bolding or italicizing text), wrap the string in a Markup() object from the **markupsafe** library, e.g., `field_name = StringField(Markup('<b>Bold text</b>'))`
- For complex display logic (e.g., building a label using multiple 'if' statements) add a function onto your form class named `field_name_label` or `field_name_desc`, e.g.:
  ```
  def pii_consent_label(self):
    label = ''
    # add complex display logic that modifies 'label'
    return label
  ```


### Field Types
Below is a map of what column types exist in Ubersystem models and what fields you might want to (or ought to) use when declaring the corresponding form fields.
| Column Type | Suggested Field Type(s) |
| --- | --- |
| UnicodeText | StringField, TextAreaField, EmailField, TelField, PasswordField, URLField | 
| Integer | IntegerField |
| Date | DateField |
| Choice | SelectField, RadioField |
| MultiChoice | MultiSelectField |
| Boolean | BooleanField |
| UTCDateTime | DateTimeField, DateTimeLocalField |
| UUID | [TODO] |
| MutableDict | [TODO] |


## Editing and Overriding Fields

### Blocks

### Change Field Name

### Change Field Help Text

### Troubleshooting/Dev Notes
Deleting or adding template files requires a restart of the server.

It is not currently possible to layer two plugins' block override. In other words, if you have a {% block consents %} in other_info.html in one plugin, and another {% block consents %} in other_info.html in another plugin, the last plugin loaded will override the first plugin's consents block. This is considered an edge case and fixing it is not currently a priority.

There are some weird behaviors if you apply the Markup() class to a description with a popup link inside it. If you're encountering this, try to apply Markup() to the rest of the text, then append the popup link -- that should work.