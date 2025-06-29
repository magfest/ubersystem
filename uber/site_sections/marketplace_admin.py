import cherrypy

from sqlalchemy import or_, and_
from sqlalchemy.orm import joinedload

from uber.config import c
from uber.decorators import all_renderable, ajax, xlsx_file
from uber.errors import HTTPRedirect
from uber.forms import load_forms
from uber.models import Attendee, BadgeInfo, Tracking, ArtistMarketplaceApplication, Email, PageViewTracking, ReceiptTransaction
from uber.utils import check, remove_opt, validate_model


@all_renderable()
class Root:
    def index(self, session, message=''):
        return {
            'message': message,
            'applications': session.query(ArtistMarketplaceApplication).all()
        }
    
    def set_status(self, session, status=None, **params):
        if not status:
            raise HTTPRedirect('index?message={}', "Please select a status to set applications to.")
        
        ids = params.get('selected')
        if isinstance(ids, str):
            ids = str(ids).split(",")
        if not ids:
            raise HTTPRedirect('index?message={}', "Please select at least one application to change the status of.")

        apps = session.query(ArtistMarketplaceApplication).filter(ArtistMarketplaceApplication.id.in_(ids))
        if not apps.count():
            raise HTTPRedirect('index?message={}', "Could not find any of the selected applications.")
        for app in apps:
            app.status = int(status)
            session.add(app)
        session.commit()
        raise HTTPRedirect('index?message={}', "Applications' status updated!")

    def form(self, session, new_app='', message='', **params):
        if new_app and 'attendee_id' in params:
            app = session.artist_marketplace_application(params, ignore_csrf=True)
        else:
            app = session.artist_marketplace_application(params)
        attendee = None

        attendee_attrs = session.query(Attendee.id, Attendee.last_first, Attendee.badge_type, BadgeInfo.ident) \
            .outerjoin(Attendee.active_badge).filter(Attendee.first_name != '', Attendee.is_valid == True,  # noqa: E712
                                                     Attendee.badge_status != c.WATCHED_STATUS)

        attendees = [
            (id, '{} - {}{}'.format(name.title(), c.BADGES[badge_type], ' #{}'.format(badge_num) if badge_num else ''))
            for id, name, badge_type, badge_num in attendee_attrs]
        
        forms_list = ["AdminArtistMarketplaceForm"]
        forms = load_forms(params, app, forms_list)

        if cherrypy.request.method == 'POST':
            if new_app:
                attendee, message = session.attendee_from_marketplace_app(**params)
                if params.get('copy_email'):
                    app.email_address = attendee.email
            else:
                attendee = app.attendee
            for form in forms.values():
                form.populate_obj(app)

            message = message or check(app)
            if not message:
                if attendee:

                    session.add(attendee)
                    app.attendee = attendee

                if params.get('save_return_to_search', False):
                    return_to = 'index?'
                else:
                    return_to = 'form?id=' + app.id + '&'
                raise HTTPRedirect(
                    return_to + 'message={}', 'Application updated')
        return {
            'message': message,
            'app': app,
            'forms': forms,
            'attendee': attendee,
            'attendee_id': app.attendee_id or params.get('attendee_id', ''),
            'all_attendees': sorted(attendees, key=lambda tup: tup[1]),
            'new_app': new_app,
        }
    
    @ajax
    def validate_marketplace_app(self, session, form_list=[], **params):
        if params.get('id') in [None, '', 'None']:
            app = ArtistMarketplaceApplication()
        else:
            app = session.artist_marketplace_application(params.get('id'))

        if not form_list:
            form_list = ["AdminArtistMarketplaceForm"]
        elif isinstance(form_list, str):
            form_list = [form_list]
        forms = load_forms(params, app, form_list)

        all_errors = validate_model(forms, app, ArtistMarketplaceApplication(**app.to_dict()), is_admin=True)
        if all_errors:
            return {"error": all_errors}

        return {"success": True}

    def history(self, session, id):
        app = session.artist_marketplace_application(id)
        receipt = session.get_receipt_by_model(app.attendee)
        marketplace_items_and_txns = []
        for item_or_txn in receipt.all_sorted_items_and_txns:
            if isinstance(item_or_txn, ReceiptTransaction):
                if any([item.fk_model == 'ArtistMarketplaceApplication' for item in item_or_txn.receipt_items]):
                    marketplace_items_and_txns.append(item_or_txn)
            elif item_or_txn.fk_model == 'ArtistMarketplaceApplication':
                marketplace_items_and_txns.append(item_or_txn)
        return {
            'app': app,
            'processors': {
                c.STRIPE: "Authorize.net" if c.AUTHORIZENET_LOGIN_ID else "Stripe",
                c.SQUARE: "SPIn" if c.SPIN_TERMINAL_AUTH_KEY else "Square",
                c.MANUAL: "Stripe"},
            'emails': session.query(Email).filter(Email.fk_id == id).order_by(Email.when).all(),
            'changes': session.query(Tracking).filter(
                or_(Tracking.links.like('%artist_marketplace_application({})%'.format(id)),
                    and_(Tracking.model == 'ArtistMarketplaceApplication',
                         Tracking.fk_id == id))).order_by(Tracking.when).all(),
            'pageviews': session.query(PageViewTracking).filter(PageViewTracking.which == repr(app)),
            'receipt_items': marketplace_items_and_txns,
        }

    @xlsx_file
    def all_applications(self, out, session):
        header_row = [
            'App ID',
            'Status',
            'Business Name',
            'Display Name',
            'Email',
            'Website',
            'IBT Number',
            'Seating Requests',
            'Accessibility Requests',
            'Admin Notes'
            ]
        
        rows = []
        
        for app in session.query(ArtistMarketplaceApplication).all():
            rows.append([
                app.id,
                app.status_label,
                app.name,
                app.display_name,
                app.email_address,
                app.website,
                app.tax_number,
                app.seating_requests,
                app.accessibility_requests,
                app.admin_notes,
            ])

        out.writerows(header_row, rows)