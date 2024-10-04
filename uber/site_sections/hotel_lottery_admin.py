import base64
import uuid
import cherrypy
import math
from datetime import datetime, date
from pockets.autolog import log
from residue import CoerceUTF8 as UnicodeText
from sqlalchemy import and_, func, or_

from uber.config import c
from uber.custom_tags import datetime_local_filter
from uber.decorators import all_renderable, log_pageview, ajax, ajax_gettable, csv_file, requires_account, render
from uber.errors import HTTPRedirect
from uber.forms import load_forms
from uber.models import Attendee, LotteryApplication, Email, Tracking, PageViewTracking
from uber.tasks.email import send_email
from uber.utils import Order, get_page, RegistrationCode, validate_model, get_age_from_birthday, normalize_email_legacy


def _search(session, text):
    applications = session.query(LotteryApplication).outerjoin(LotteryApplication.attendee)

    terms = text.split()
    if len(terms) == 1 and terms[0].isdigit():
        if len(terms[0]) == 10:
            return applications.filter(or_(LotteryApplication.confirmation_num == terms[0])), ''
    
    check_list = []
    for attr in [col for col in LotteryApplication().__table__.columns if isinstance(col.type, UnicodeText)]:
        check_list.append(attr.ilike('%' + text + '%'))
    
    return applications.filter(or_(*check_list)), ''


@all_renderable()
class Root:
    def index(self, session, message='', page='0', search_text='', order='status'):
        if c.DEV_BOX and not int(page):
            page = 1

        total_count = session.query(LotteryApplication.id).count()
        complete_count = session.query(LotteryApplication.id).filter(LotteryApplication.status == c.COMPLETE).count()
        count = 0
        search_text = search_text.strip()
        if search_text:
            search_results, message = _search(session, search_text)
            if search_results and search_results.count():
                applications = search_results
                count = applications.count()
                if count == total_count:
                    message = 'Every lottery application matched this search.'
            elif not message:
                message = 'No matches found. Try searching the lottery tracking history instead.'
        if not count:
            applications = session.query(LotteryApplication).outerjoin(LotteryApplication.attendee)
            count = applications.count()

        applications = applications.order(order)

        page = int(page)
        if search_text:
            page = page or 1

        pages = range(1, int(math.ceil(count / 100)) + 1)
        applications = applications[-100 + 100*page: 100*page] if page else []

        return {
            'message':        message if isinstance(message, str) else message[-1],
            'page':           page,
            'pages':          pages,
            'search_text':    search_text,
            'search_results': bool(search_text),
            'applications':   applications,
            'order':          Order(order),
            'search_count':   count,
            'total_count':    total_count,
            'complete_count': complete_count,
        }  # noqa: E711

    def feed(self, session, message='', page='1', who='', what='', action=''):
        feed = session.query(Tracking).filter(Tracking.model == 'LotteryApplication').order_by(Tracking.when.desc())
        what = what.strip()
        if who:
            feed = feed.filter_by(who=who)
        if what:
            like = '%' + what + '%'
            or_filters = [Tracking.page.ilike(like),
                          Tracking.which.ilike(like),
                          Tracking.data.ilike(like)]
            feed = feed.filter(or_(*or_filters))
        if action:
            feed = feed.filter_by(action=action)
        return {
            'message': message,
            'who': who,
            'what': what,
            'page': page,
            'action': action,
            'count': feed.count(),
            'feed': get_page(page, feed),
            'action_opts': [opt for opt in c.TRACKING_OPTS if opt[0] != c.AUTO_BADGE_SHIFT],
            'who_opts': [
                who for [who] in session.query(Tracking).filter(
                    Tracking.model == 'LotteryApplication').distinct().order_by(Tracking.who).values(Tracking.who)]
        }
    
    def mark_staff_processed(self, session, **params):
        for app in session.query(LotteryApplication).filter(LotteryApplication.is_staff_entry,
                                                            LotteryApplication.status == c.COMPLETE):
            app.status = c.PROCESSED
            session.add(app)
            session.commit()

        raise HTTPRedirect('index?message={}',
                           "All complete staff entries marked as processed.")
    
    @ajax
    def validate_hotel_lottery(self, session, id=None, form_list=[], **params):
        application = session.lottery_application(id)

        if not form_list:
            form_list = ["LotteryAdminInfo"]
        elif isinstance(form_list, str):
            form_list = [form_list]
        forms = load_forms(params, application, form_list, get_optional=False)
        all_errors = validate_model(forms, application, LotteryApplication(**application.to_dict()))
        if all_errors:
            return {"error": all_errors}

        return {"success": True}

    @log_pageview
    def form(self, session, message='', return_to='', **params):
        id = params.get('id', None)

        if id in [None, '', 'None']:
            application = LotteryApplication()
        else:
            application = session.lottery_application(id)

        forms = load_forms(params, application, ['LotteryAdminInfo'])

        if cherrypy.request.method == 'POST':
            for form in forms.values():
                form.populate_obj(application, is_admin=True)
            
            message = '{}\'s entry (conf # {}) has been saved.'.format(application.attendee.full_name,
                                                                       application.confirmation_num)
            stay_on_form = params.get('save_return_to_search', False) is False
            session.add(application)
            session.commit()
            if stay_on_form:
                    raise HTTPRedirect('form?id={}&message={}&return_to={}', application.id, message, return_to)
            else:
                if return_to:
                    raise HTTPRedirect(return_to + '&message={}', 'Application updated.')
                else:
                    raise HTTPRedirect('index?message={}', message)

        return {
            'message':    message,
            'application':   application,
            'forms': forms,
            'return_to':  return_to,
        }

    def history(self, session, id):
        application = session.lottery_application(id)
        return {
            'application':  application,
            'emails': session.query(Email).filter(Email.model == 'LotteryApplication',
                                                  Email.fk_id == id
                                                  ).order_by(Email.when).all(),
            'changes': session.query(Tracking).filter(Tracking.model == 'LotteryApplication', Tracking.fk_id == id
                                                      ).order_by(Tracking.when).all(),
            'pageviews': session.query(PageViewTracking).filter(PageViewTracking.which == repr(application))
        }
    
    @csv_file
    def interchange_export(self, out, session, staff_lottery=False):
        def print_dt(dt):
            if not dt:
                return ""

            if isinstance(dt, datetime):
                return dt.astimezone(c.EVENT_TIMEZONE).strftime('%m/%d/%Y %H:%M:%S')
            else:
                return dt.strftime('%m/%d/%Y')
        
        def print_bool(bool):
            return "TRUE" if bool else "FALSE"

        header_row = []
        # Config data and IDs
        header_row.extend(["Lottery Close", "suite_cutoff", "year", "Response ID", "Confirmation Code",
                           "SessionID", "Survey ID", "entry_id", "dealer_group_id"])
        
        # Contact data
        header_row.extend(["is_staff", "email", "first_name:contact", "last_name:contact", "Title:contact",
                           "Company Name:contact", "street_address:contact", "apt_suite_office:contact",
                           "city:contact", "state:contact", "zip:contact", "country:contact", "phone:contact",
                           "Mobile Phone:contact"])

        # Entry metadata
        header_row.extend(["Time Started", "Date Submitted", "entry_confirmed", "Status", "edit_link", "I agree:agree",
                           "Comments", "payment_valid", "reg_conf_code", "entry_type", "Referer",
                           "User Agent", "IP Address", "Longitude", "Latitude", "Country", "City", "State/Region",
                           "Postal"])

        # Entry data
        header_row.extend(["group_conf", "group_email", "Yes:age_ack", "special_room", "ada_req_text",
                           "I agree, understand and will comply:suite_agree",
                           "desired_arrival", "latest_arrival", "desired_departure", "earliest_departure"])

        for key, val in c.HOTEL_LOTTERY_HOTELS_OPTS:
            header_row.append(f"{val['export_name'] or val['name']}:hotel_pref")

        for key, val in c.HOTEL_LOTTERY_ROOM_TYPES_OPTS:
            header_row.append(f"{val['export_name'] or val['name']}:room_pref")

        for key, val in c.HOTEL_LOTTERY_SUITE_ROOM_TYPES_OPTS:
            header_row.append(f"{val['export_name'] or val['name']}:suite_type")

        for key, val in c.HOTEL_LOTTERY_PRIORITIES_OPTS:
            header_row.append(f"{val['export_name'] or val['name']}:priority_pref")

        out.writerow(header_row)

        applications = session.query(LotteryApplication).join(LotteryApplication.attendee
                                                              ).filter(LotteryApplication.status != c.PROCESSED,
                                                                       Attendee.hotel_lottery_eligible == True)
        if staff_lottery:
            applications = applications.filter(LotteryApplication.is_staff_entry == True)
        else:
            applications = applications.filter(LotteryApplication.is_staff_entry == False)

        for app in applications:
            attendee = app.attendee
            row = []

            # Config data and IDs
            dealer_id = ''
            if app.attendee.is_dealer and app.attendee.group and app.attendee.group.status in [c.APPROVED, c.SHARED]:
                dealer_id = app.attendee.group.id
            row.extend([datetime_local_filter(app.current_lottery_deadline), datetime_local_filter(c.HOTEL_LOTTERY_SUITE_CUTOFF),
                        c.EVENT_YEAR, app.response_id, app.confirmation_num, app.id, "RAMS_1", app.id, dealer_id])

            # Contact data
            row.extend([print_bool(attendee.badge_type == c.STAFF_BADGE or c.STAFF_RIBBON in attendee.ribbon_ints),
                        attendee.email, app.legal_first_name or attendee.legal_first_name,
                        app.legal_last_name or attendee.legal_last_name, "", "", attendee.address1,
                        attendee.address2, attendee.city, attendee.region, attendee.zip_code, attendee.country,
                        ''.join(filter(str.isdigit, attendee.cellphone)) if attendee.cellphone else "", ""])

            # Entry metadata
            if app.entry_type:
                type_str = "I am entering as a roommate" if app.entry_type == c.GROUP_ENTRY else "I am requesting a room"
            else:
                type_str = "I am withdrawing from the lottery"
            row.extend([print_dt(app.entry_started), print_dt(app.last_submitted), print_bool(app.status == c.COMPLETE),
                        app.status_label, f"{c.URL_BASE}/hotel_lottery/index?attendee_id={app.attendee.id}",
                        print_bool(app.terms_accepted), app.admin_notes, "FALSE", attendee.id, type_str])
            if app.entry_metadata:
                row.extend([app.entry_metadata.get('referer'), app.entry_metadata.get('user_agent'), app.entry_metadata.get('ip_address')])
            else:
                row.extend(['', '', ''])
            row.extend(['', '', '', '', '', ''])

            # Entry data
            if app.parent_application:
                row.extend([app.parent_application.confirmation_num, app.parent_application.attendee.email,
                            '', '', '', '', '', '', '', ''])
            else:
                row.extend(['', '', print_bool(app.entry_form_completed)])

                entry_type_base = app.entry_type or c.ROOM_ENTRY
                if entry_type_base == c.ROOM_ENTRY:
                    if app.wants_ada:
                        row.extend(['ADA Room', app.ada_requests, ''])
                    else:
                        row.extend(['Standard Rooms with no Special Requests', '', ''])
                elif entry_type_base == c.SUITE_ENTRY:
                    row.extend(['Hyatt Regency O\'Hare Suites', '', print_bool(app.suite_terms_accepted)])
                
                row.extend([print_dt(app.earliest_checkin_date), print_dt(app.latest_checkin_date),
                            print_dt(app.latest_checkout_date), print_dt(app.earliest_checkout_date)])

            if app.parent_application or not app.hotel_preference or (
                    app.entry_type and app.entry_type == c.SUITE_ENTRY and app.room_opt_out):
                row.extend(['' for _ in range(len(c.HOTEL_LOTTERY_HOTELS_OPTS))])
            else:
                hotels_ranking = {}
                for index, item in enumerate(app.hotel_preference.split(','), start=1):
                    hotels_ranking[item] = index

                for key, val in c.HOTEL_LOTTERY_HOTELS_OPTS:
                    row.append(hotels_ranking.get(str(key), ''))

            if app.parent_application or not app.room_type_preference or (
                    app.entry_type and app.entry_type == c.SUITE_ENTRY and app.room_opt_out):
                row.extend(['' for _ in range(len(c.HOTEL_LOTTERY_ROOM_TYPES_OPTS))])
            else:
                room_types_ranking = {}
                for index, item in enumerate(app.room_type_preference.split(','), start=1):
                    room_types_ranking[item] = index

                for key, val in c.HOTEL_LOTTERY_ROOM_TYPES_OPTS:
                    row.append(room_types_ranking.get(str(key), ''))

            if app.parent_application or not app.suite_type_preference or (
                    app.entry_type and app.entry_type == c.ROOM_ENTRY):
                row.extend(['' for _ in range(len(c.HOTEL_LOTTERY_SUITE_ROOM_TYPES_OPTS))])
            else:
                suite_types_ranking = {}
                for index, item in enumerate(app.suite_type_preference.split(','), start=1):
                    suite_types_ranking[item] = index

                for key, val in c.HOTEL_LOTTERY_SUITE_ROOM_TYPES_OPTS:
                    row.append(suite_types_ranking.get(str(key), ''))

            if app.parent_application or not app.selection_priorities:
                row.extend(['' for _ in range(len(c.HOTEL_LOTTERY_PRIORITIES_OPTS))])
            else:
                priority_ranking = {}
                for index, item in enumerate(app.selection_priorities.split(','), start=1):
                    priority_ranking[item] = index

                for key, val in c.HOTEL_LOTTERY_PRIORITIES_OPTS:
                    row.append(priority_ranking.get(str(key), ''))
            
            out.writerow(row)
 