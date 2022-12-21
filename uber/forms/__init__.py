from wtforms import Form, BooleanField, DateField, EmailField, StringField, SelectField, validators

class MagForm(Form):
    class Meta:
        def render_field(self, field, render_kw):
            if isinstance(field, (StringField, EmailField)):
                render_kw['class'] = 'form-control'
            return super().render_field(field, render_kw)



from uber.forms.preregistration import *  # noqa: F401,E402,F403