from datetime import datetime

from uber.config import c
from uber.decorators import ajax, all_renderable
from uber.errors import HTTPRedirect
from uber.models import Attendee, Room, RoomAssignment, Shift, LotteryApplication
from uber.forms import load_forms
from uber.utils import validate_model


@all_renderable()
class Root:
    def index(self, session, **params):
        lottery_application = LotteryApplication()
        params['id'] = 'None'
        forms = load_forms(params, lottery_application, ['LotteryApplication'])
        return {
            "checkin_start": c.HOTEL_LOTTERY_CHECKIN_START,
            "checkin_end": c.HOTEL_LOTTERY_CHECKIN_END,
            "checkout_start": c.HOTEL_LOTTERY_CHECKOUT_START,
            "checkout_end": c.HOTEL_LOTTERY_CHECKOUT_END,
            "hotels": c.HOTEL_LOTTERY,
            "forms": forms
        }

    @ajax
    def validate_hotel_lottery(self, session, form_list=[], **params):
        if params.get('id') in [None, '', 'None']:
            application = LotteryApplication()
        else:
            application = LotteryApplication.get(id=params.get('id'))

        if not form_list:
            form_list = ["LotteryApplication"]
        elif isinstance(form_list, str):
            form_list = [form_list]
        forms = load_forms(params, application, form_list, get_optional=False)

        all_errors = validate_model(forms, application, LotteryApplication(**application.to_dict()))
        if all_errors:
            return {"error": all_errors}

        return {"success": True}
    
    def form(self, session, message="", **params):
        application = LotteryApplication()
        forms_list = ["LotteryApplication"]
        forms = load_forms(params, application, forms_list)
        for form in forms.values():
            form.populate_obj(application)
        return {
            'forms': forms,
            'message': message,
            'application': application
        }