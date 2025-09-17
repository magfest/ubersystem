import base64
import pycountry
import cherrypy
import random
import math
from copy import deepcopy
from collections import defaultdict
from datetime import datetime, timedelta
from dateutil import parser as dateparser
from pockets.autolog import log
from residue import CoerceUTF8 as UnicodeText
from sqlalchemy import and_, func, or_
from ortools.linear_solver import pywraplp

from uber.config import c
from uber.custom_tags import datetime_local_filter
from uber.decorators import all_renderable, log_pageview, ajax, ajax_gettable, csv_file, requires_account, render
from uber.errors import HTTPRedirect
from uber.forms import load_forms
from uber.models import Attendee, Group, LotteryApplication, Email, Tracking, PageViewTracking
from uber.tasks.email import send_email
from uber.utils import Order, get_page, localized_now, validate_model, get_age_from_birthday, normalize_email_legacy

def beep_on_start():
    print("Beeping!\a", flush=True)
cherrypy.engine.subscribe('start', beep_on_start)

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

def weight_entry(entry, hotel_room):
    """Takes a lottery entry and a hotel room and returns an arbitrary score for how likely that applicant
        should be to get that particular room.
    """
    # Higher weight increases the odds of them getting this room.
    weight = 1.0
    
    # Give 10 points for being the first choice hotel, 9 points for the second, etc
    hotel_choice_rank = 10 - entry["hotels"].index(hotel_room["id"])
    weight += hotel_choice_rank
    
    # Give 10 points for being the first choice room type, 9 points for the second, etc
    try:
        room_type_rank = 10 - entry["room_types"].index(hotel_room["room_type"])
        assert room_type_rank >= 0
        weight += room_type_rank
    except ValueError:
        # room types are optional, so we need to figure out how much weight to give people who don't choose any
        weight += 9 # Probably fine?

    # Give one point for each group member
    weight += len(entry["members"])
    
    return weight
    
def solve_lottery(applications, hotel_rooms, lottery_type=c.ROOM_ENTRY):
    """Takes a set of hotel_rooms and applications and assigns the hotel_rooms mostly randomly.
        Parameters:
        applications List[Application]: Iterable set of Application objects to assign
        hotel_rooms  List[hotels]: Iterable set of hotel rooms, represented as dictionaries with the following keys:
        * id: c.HOTEL_LOTTERY_HOTELS_OPTS
        * capacity: int
        * room_type: c.HOTEL_LOTTERY_ROOM_TYPE_OPTS
        * quantity: int
        
        Returns Dict[Applications -> hotel, room_type]: A mapping of Application.id -> (id, room_type) or None if it failed
    """
    random.shuffle(applications)
    solver = pywraplp.Solver.CreateSolver("SAT")
    
    # Set up our data structures
    for hotel_room in hotel_rooms:
        hotel_room["constraints"] = []
    entries = {}
    for app in applications:
        if app.entry_type == lottery_type:
            if lottery_type == c.ROOM_ENTRY:
                entry = {
                    "members": [app],
                    "hotels": app.hotel_preference.split(","),
                    "room_types": app.room_type_preference.split(","),
                    "constraints": []
                }
            elif lottery_type == c.SUITE_ENTRY:
                entry = {
                    "members": [app],
                    "hotels": app.hotel_preference.split(","),
                    "room_types": app.suite_type_preference.split(","),
                    "constraints": []
                }
            entries[app.id] = entry
            for hotel_room in hotel_rooms:
                if hotel_room["id"] in entry["hotels"] and hotel_room["room_type"] in entry["room_types"]:
                    weight = weight_entry(entry, hotel_room)                 
                    
                    # Each constraint is a tuple of (BoolVar(), weight, hotel_room)
                    constraint = solver.BoolVar(f'{app.id}_assigned_to_{hotel_room["id"]}')
                    entry["constraints"].append((constraint, weight, hotel_room))
                    hotel_room["constraints"].append(constraint)
                    
    for app in applications:
        if app.entry_type == lottery_type and app.parent_application in entries:
            entries[app.parent_application]["members"].append(app)
                    
    # Set up constraints
    
    ## Limit capacity of each room to fit the groups
    for app, entry in entries.items():
        num_entrants = len(entry["members"])
        for is_assigned, weight, hotel_room in entry["constraints"]:
            solver.Add(is_assigned * num_entrants <= hotel_room["capacity"])
    
    ## Only allow each group to have one room
        solver.Add(sum([x[0] for x in entry["constraints"]]) <= 1)
    
    ## Only allow each room type to fit only the quantity available
    for hotel_room in hotel_rooms:
        if hotel_room["constraints"]:
            solver.Add(sum(hotel_room["constraints"]) <= hotel_room["quantity"])
            
    # Set up Objective function
    objective = solver.Objective()
    
    for app, entry in entries.items():
        for is_assigned, weight, hotel_room in entry["constraints"]:
            objective.SetCoefficient(is_assigned, weight)
    
    objective.SetMaximization()
    
    # Run the solver
    status = solver.Solve()
    if status in [pywraplp.Solver.OPTIMAL, pywraplp.Solver.FEASIBLE]:
        # If it's optimal we know we got an ideal solution
        # If it's feasible then we may have been on the way to an ideal solution,
        # but we gave up searching because we ran out of time or something
        assignments = {}
        for app, entry in entries.items():
            for is_assigned, weight, hotel_room in entry["constraints"]:
                if is_assigned.solution_value() > 0.5:
                    assert not app in assignments
                    assignments[app] = (hotel_room["id"], hotel_room["room_type"])
        return assignments
    else:
        log.error(f"Error solving room lottery: {status}")
        return None

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
            'action_opts': c.TRACKING_OPTS,
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
        forms = load_forms(params, application, form_list)
        all_errors = validate_model(forms, application, is_admin=True)
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
            
            message = '{}\'s entry (conf # {}) has been saved.'.format(application.attendee_name,
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
        
    def reset_lottery(self, session, **params):
        lottery_type_val = params.get("lottery_type", "room")
        if lottery_type_val == "room":
            lottery_type = c.ROOM_ENTRY
        elif lottery_type_val == "suite":
            lottery_type_val = c.SUITE_ENTRY
        else:
            raise ValueError(f"Unknown lottery_type {lottery_type_val}")
        
        applications = session.query(LotteryApplication).filter(LotteryApplication.status == c.PROCESSED,
                                                            Attendee.hotel_lottery_eligible == True)
        applications = applications.filter(LotteryApplication.entry_type == lottery_type)
        lottery_group_val = params.get("lottery_group", "attendee")
        if lottery_group_val == "attendee":
            applications = applications.filter(LotteryApplication.is_staff_entry == False)
        elif lottery_group_val == "staff":
            applications = applications.filter(LotteryApplication.is_staff_entry == True)
        
        applications = applications.all()
        
        for app in applications:
            app.status = c.COMPLETE
            app.assigned_hotel = None
            app.assigned_room_type = None
            app.assigned_suite_type = None
            session.add(app)
        session.commit()
        raise HTTPRedirect('index?message={}',
                           "All processed lottery entries are reset to completed.")
        
    def award_lottery(self, session, **params):
        lottery_type_val = params.get("lottery_type", "room")
        if lottery_type_val == "room":
            lottery_type = c.ROOM_ENTRY
        elif lottery_type_val == "suite":
            lottery_type_val = c.SUITE_ENTRY
        else:
            raise ValueError(f"Unknown lottery_type {lottery_type_val}")
        
        applications = session.query(LotteryApplication).filter(LotteryApplication.status == c.PROCESSED,
                                                            Attendee.hotel_lottery_eligible == True)
        applications = applications.filter(LotteryApplication.entry_type == lottery_type)
        lottery_group_val = params.get("lottery_group", "attendee")
        if lottery_group_val == "attendee":
            applications = applications.filter(LotteryApplication.is_staff_entry == False)
        elif lottery_group_val == "staff":
            applications = applications.filter(LotteryApplication.is_staff_entry == True)
        
        applications = applications.all()
        
        for app in applications:
            app.status = c.AWARDED
            if c.HOTEL_LOTTERY_GUARANTEE_HOURS:
                dt = datetime.now() + timedelta(hours=c.HOTEL_LOTTERY_GUARANTEE_HOURS).date()
                app.deposit_cutoff_date = c.EVENT_TIMEZONE.localize(datetime.strptime(dt + ' 23:59', '%Y-%m-%d %H:%M'))
            session.add(app)
        session.commit()
        raise HTTPRedirect('index?message={}',
                           "All processed lottery entries have been awarded.")
        
    def run_lottery(self, session, lottery_group="attendee", lottery_type="room", **params):
        if lottery_type == "room":
            lottery_type = c.ROOM_ENTRY
        if lottery_type == "suite":
            lottery_type = c.SUITE_ENTRY
        applications = session.query(LotteryApplication).join(LotteryApplication.attendee
                                                              ).filter(LotteryApplication.status == c.COMPLETE,
                                                                       Attendee.hotel_lottery_eligible == True)

        if 'cutoff' in params:
            last_time = dateparser.parse(params['cutoff']).replace(tzinfo=c.EVENT_TIMEZONE)
            applications = applications.filter(LotteryApplication.entry_started < last_time)

        # We always grab all roommate entries, but the solver only looks at those that have a matching parent
        # in the lottery batch.
        applications = applications.filter(LotteryApplication.entry_type.in_([lottery_type, c.GROUP_ENTRY]))

        # If lottery_group is "both" don't filter either way
        if lottery_group == "staff":
            applications = applications.filter(LotteryApplication.is_staff_entry == True)
        elif lottery_group == "attendee":
            applications = applications.filter(LotteryApplication.is_staff_entry == False)
            
        applications = applications.all()
        assigned_applications = session.query(LotteryApplication.assigned_hotel,
                                              LotteryApplication.assigned_room_type,
                                              func.count(LotteryApplication.id)).join(LotteryApplication.attendee).filter(
                                                  LotteryApplication.status.in_(c.HOTEL_LOTTERY_AWARD_STATUSES)
                                                  ).group_by(LotteryApplication.assigned_hotel).group_by(
                                                      LotteryApplication.assigned_room_type).all()
        
        assigned_applications_dict = {(hotel, room_type): count for hotel, room_type, count in assigned_applications}

        if lottery_type == c.SUITE_ENTRY:
            room_or_suite_lookup = dict(c.HOTEL_LOTTERY_SUITE_ROOM_TYPES_OPTS)
            inventory_table = c.HOTEL_LOTTERY_SUITE_INVENTORY
        else:
            room_or_suite_lookup = dict(c.HOTEL_LOTTERY_ROOM_TYPES_OPTS)
            inventory_table = c.HOTEL_LOTTERY_ROOM_INVENTORY

        available_rooms = deepcopy(inventory_table)
        for hotel_and_room in available_rooms:
            hotel, room_type = int(hotel_and_room['id']), int(hotel_and_room['room_type'])
            if assigned_applications_dict.get((hotel, room_type)):
                hotel_and_room['quantity'] -= assigned_applications_dict[(hotel, room_type)]

        assignments = solve_lottery(applications, available_rooms, lottery_type=lottery_type)

        for application in applications:
            if application.id in assignments:
                hotel, room_type = assignments[application.id]
                application.assigned_hotel = hotel
                if lottery_type == c.SUITE_ENTRY:
                    application.assigned_suite_type = room_type
                elif lottery_type == c.ROOM_ENTRY:
                    application.assigned_room_type = room_type
                else:
                    raise NotImplementedError(f"Unknown lottery type {lottery_type}")
                # For now, everyone gets the dates they picked
                application.assigned_check_in_date = application.earliest_checkin_date
                application.assigned_check_out_date = application.latest_checkout_date
                application.status = c.PROCESSED
                session.add(application)
        session.commit()
        application_lookup = {x.id: x for x in applications}
        
        return {
            'lottery_type': lottery_type,
            'num_rooms_available_before': sum([x['quantity'] for x in available_rooms]),
            'num_rooms_available_after': sum([x['quantity'] for x in available_rooms]) - len(assignments),
            'num_entries': len([x for x in applications if x.entry_type == lottery_type]),
            'assignments': [(application_lookup[x], y[0], y[1]) for x, y in assignments.items()],
            'hotel_lookup': dict(c.HOTEL_LOTTERY_HOTELS_OPTS),
            'room_or_suite_lookup': room_or_suite_lookup,
        }
    
    def hotel_inventory(self, session, message=''):
        assigned_applications = session.query(
            LotteryApplication.assigned_hotel, LotteryApplication.assigned_room_type, LotteryApplication.status,
            func.count(LotteryApplication.id)).join(LotteryApplication.attendee).filter(
                LotteryApplication.status.in_(c.HOTEL_LOTTERY_AWARD_STATUSES)
                ).group_by(LotteryApplication.assigned_hotel).group_by(
                    LotteryApplication.assigned_room_type).group_by(LotteryApplication.status).all()
        
        assigned_applications_dict = defaultdict(list)
        for hotel, room_type, status, count in assigned_applications:
            assigned_applications_dict[(hotel, room_type)].append((status, count))

        room_inventory = defaultdict(list)
        for inventory_info in c.HOTEL_LOTTERY_ROOM_INVENTORY:
            hotel, room_type = int(inventory_info['id']), int(inventory_info['room_type'])
            info_for_room = {'room_type': room_type, 'quantity': inventory_info['quantity']}
            if assigned_applications_dict.get((hotel, room_type)):
                for status, count in assigned_applications_dict[(hotel, room_type)]:
                    info_for_room[status] = count
            room_inventory[hotel].append(info_for_room)

        suite_inventory = defaultdict(list)
        for inventory_info in c.HOTEL_LOTTERY_SUITE_INVENTORY:
            hotel, room_type = int(inventory_info['id']), int(inventory_info['room_type'])
            info_for_room = {'room_type': room_type, 'quantity': inventory_info['quantity']}
            if assigned_applications_dict.get((hotel, room_type)):
                for status, count in assigned_applications_dict[(hotel, room_type)]:
                    info_for_room[status] = count
            suite_inventory[hotel].append(info_for_room)

        return {
            'room_inventory': room_inventory,
            'suite_inventory': suite_inventory,
            'hotel_lookup': dict(c.HOTEL_LOTTERY_HOTELS_OPTS),
            'room_lookup': dict(c.HOTEL_LOTTERY_ROOM_TYPES_OPTS),
            'suite_lookup': dict(c.HOTEL_LOTTERY_SUITE_ROOM_TYPES_OPTS),
            'now': localized_now(),
        }

    @csv_file
    def accepted_dealers(self, out, session):
        out.writerow(['Group Name', 'Group ID', 'Reg ID'])

        for dealer in session.query(Attendee).join(Group, Attendee.group_id == Group.id).filter(
            Group.is_dealer, Group.status.in_(c.DEALER_ACCEPTED_STATUSES)):
            out.writerow([dealer.group.name, dealer.group.id, dealer.id])

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

        country_codes = {}
        for country in list(pycountry.countries):
            value = country.name if "Taiwan" not in country.name else "Taiwan"
            country_codes[value] = f"{country.alpha_2};{country.name}"

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
            if app.attendee.is_dealer and app.attendee.group and app.attendee.group.status in c.DEALER_ACCEPTED_STATUSES:
                dealer_id = app.attendee.group.id
            current_lottery_deadline = c.HOTEL_LOTTERY_STAFF_DEADLINE if app.is_staff_entry else c.HOTEL_LOTTERY_FORM_DEADLINE
            row.extend([datetime_local_filter(current_lottery_deadline), datetime_local_filter(c.HOTEL_LOTTERY_SUITE_CUTOFF),
                        c.EVENT_YEAR, app.response_id, app.confirmation_num, app.id, "RAMS_1", app.id, dealer_id])

            # Contact data
            base_cellphone = app.cellphone or app.attendee.cellphone
            row.extend([print_bool(attendee.badge_type == c.STAFF_BADGE or c.STAFF_RIBBON in attendee.ribbon_ints),
                        attendee.email, app.legal_first_name or attendee.legal_first_name,
                        app.legal_last_name or attendee.legal_last_name, "", "", attendee.address1,
                        attendee.address2, attendee.city, attendee.region, attendee.zip_code,
                        country_codes.get(attendee.country, attendee.country),
                        ''.join(filter(str.isdigit, base_cellphone)) if base_cellphone else "", ""])

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
                row.extend([app.parent_application.confirmation_num, app.parent_application.email,
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
 