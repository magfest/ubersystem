import cherrypy
import treepoem
import os
import re
import math

from decimal import Decimal
from sqlalchemy import or_, and_
from sqlalchemy.orm import backref, joinedload
from io import BytesIO

from uber.config import c
from uber.decorators import ajax, all_renderable, credit_card
from uber.errors import HTTPRedirect
from uber.models import Attendee, Tracking, ArbitraryCharge, MarketplaceApplication
from uber.utils import Charge, check, localized_now, Order, remove_opt


@all_renderable()
class Root:
    def index(self, session, message=''):
        return {
            'message': message,
            'applications': session.query(MarketplaceApplication).options(joinedload('attendee')).all()
        }

    def form(self, session, new_app='', message='', **params):
        if new_app and 'attendee_id' in params:
            app = session.marketplace_application(params, ignore_csrf=True)
        else:
            app = session.marketplace_application(params)
        attendee = None

        attendee_attrs = session.query(Attendee.id, Attendee.last_first, Attendee.badge_type, Attendee.badge_num) \
            .filter(Attendee.first_name != '', Attendee.badge_status not in [c.INVALID_STATUS, c.WATCHED_STATUS])

        attendees = [
            (id, '{} - {}{}'.format(name.title(), c.BADGES[badge_type], ' #{}'.format(badge_num) if badge_num else ''))
            for id, name, badge_type, badge_num in attendee_attrs]

        if cherrypy.request.method == 'POST':
            if new_app:
                attendee, message = session.attendee_from_marketplace_app(**params)
            else:
                attendee = app.attendee
            message = message or check(app)
            if not message:
                if attendee:
                    if params.get('badge_status', ''):
                        attendee.badge_status = params['badge_status']

                    session.add(attendee)
                    app.attendee = attendee

                    if app.status == c.APPROVED and attendee.group:
                        attendee.group.status = c.CANCELLED
                        attendee.group = None
                        attendee.paid = c.NOT_PAID
                        session.commit()  # Lets us remove the dealer ribbon
                        attendee.ribbon = remove_opt(attendee.ribbon_ints, c.DEALER_RIBBON)

                if params.get('save') == 'save_return_to_search':
                    return_to = 'index?'
                else:
                    return_to = 'form?id=' + app.id + '&'
                raise HTTPRedirect(
                    return_to + 'message={}', 'Application updated')
        return {
            'message': message,
            'app': app,
            'attendee': attendee,
            'attendee_id': app.attendee_id or params.get('attendee_id', ''),
            'all_attendees': sorted(attendees, key=lambda tup: tup[1]),
            'new_app': new_app,
        }

    def history(self, session, id):
        app = session.marketplace_application(id)
        return {
            'app': app,
            'changes': session.query(Tracking).filter(
                or_(Tracking.links.like('%marketplace_application({})%'
                                        .format(id)),
                and_(Tracking.model == 'MarketplaceApplication',
                     Tracking.fk_id == id)))
                .order_by(Tracking.when).all()
        }
