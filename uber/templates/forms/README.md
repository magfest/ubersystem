# Form Guide for Ubersystem/RAMS
Forms represent the vast majority of attendees' (and many admins'!) interaction with Ubersystem. As such, they are highly dependent on business logic and are often complex. A single field may be required under some conditions but not others, change its labeling in some contexts, show help text to attendees but not admins, etc. This guide is to help you understand, edit, and override forms without creating a giant mess. Hopefully.

## Forms Are a WIP
Up until the writing of this guide, all forms in Ubersystem were driven entirely by Jinja2 macros, jQuery, and HTML, with form handling done largely inside individual page handlers (with the exception of validations -- more info on those below). As of early 2023, **attendee** and **group** forms are the only forms that use the technologies and conventions described below, unless otherwise noted. Attendee and group forms are by far the most complex forms in the app and were in the most need of an overhaul, but we do intend to update other forms in future years.

## How Forms Are Built
We rely on the following frameworks and modules for our forms:
- [WTForms](https://wtforms.readthedocs.io/en/3.0.x/) defines our forms as declarative data, along with many of their static properties. Each set of forms is organized in one file per type of entity, similar to our **models** folder, and they are found in **uber/forms/**. Inherited classes and other WTForms customizations are in **uber/forms/__init__.py**.
- [Jinja2](https://jinja.palletsprojects.com/en/3.1.x/templates/) provides **macros** that render the scaffolding for fields (these macros call WTForms to render the fields themselves) and **blocks** that define sections of forms for appending fields or overriding.
  - Form macros are found in **uber/template/forms/macros.html** -- always use these macros rather than writing your own scaffolding.
- [Bootstrap 5](https://getbootstrap.com/docs/5.0/) provides the styling and responsive layout for forms. Always use the grid layout ("col" divs contained inside "row g-sm-3" divs) when adding fields.

### Form Validations

### Form Fields and Permissions

## Adding Fields
First, figure out if you want to add fields to an existing form or if you want to add a new form. Multiple forms can be combined and processed seamlessly on a single page, so it is good to group like fields together into their own 'forms.' Pay particular attention to which fields represent personal identifying information (PII) and group them separately from fields that don't.

To declare a new form, [TODO]. To add fields to an existing form, [TODO].

https://wtforms.readthedocs.io/en/3.0.x/fields/

### Field Labels and Descriptions
By default, labels and descriptions for fields are simple strings with automatic escaping for HTML/XML. Since this is not always desirable, here are a few ways to write more complex labels:

- To include basic HTML (e.g., bolding or italicizing text), wrap the string in a Markup() object from the **markupsafe** library, e.g., `field_name = StringField(Markup('<b>Bold text</b>'))`
- Some common basic variables are processed automatically, such as the event name and year. These variables are defined as `text_vars` in **uber/forms/__init__.py**. To use these variables, include them using Python string formatting syntax, e.g., `field_name = StringField(Markup('I love {EVENT_NAME}!'))`
- To add additional variables to a form for auto-processing, add `extra_text_vars` under the form class definition, e.g., `extra_text_vars = {'ORGANIZATION_NAME': c.ORGANIZATION_NAME}`. You can of course always use `'Label text {}'.format(var)` to insert a variable into an individual label or description.
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