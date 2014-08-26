"""
When an admin submits a form to create/edit an attendee/group/job/etc we usually want to perform some basic validations
on the data that was entered.  We put those validations here.  To make a validation for the Attendee model, you can
just write a function prefixed with "attendee_" like the "attendee_money" function below, which checks the values for
things like amount_paid and amount_extra.  That function should return None on success and an error string on failure.

In addition, you can define a set of required fields by suffixing the lower-cased model name with "_required", like
the "adminaccount_required" list below.  This should be a list of tuples where the first tuple element is the name of
the field, and the second is the name that should be displayed in the "XXX is a required field" error message.

To perform these validations, call the "check" method on the instance you're validating.  That method returns None
on success and a string error message on validation failure.
"""
from uber.common import *

# TODO: there are no unit tests for any of this :(


adminaccount_required = [('attendee', 'Attendee'), ('hashed','Password')]

def adminaccount_misc(account):
    if account.is_new:
        with Session() as session:
            if session.query(AdminAccount).filter_by(attendee_id=account.attendee_id).all():
                return 'That attendee already has an admin account'


event_required = [('name', 'Event Name')]

def event_overlaps(event, other_event_id=None):
    existing = {}
    for e in event.session.query(Event).filter(Event.location == event.location,
                                               Event.id != event.id,
                                               Event.id != other_event_id).all():
        for hh in e.half_hours:
            existing[hh] = e.name

    for hh in event.half_hours:
        if hh in existing:
            return '"{}" overlaps with the time/duration you specified for "{}"'.format(existing[hh], event.name)


group_required = [('name','Group Name')]

def group_paid(group):
    try:
        amount = int(float(group.amount_paid))
        if amount < 0 or amount > 2000:
            return 'Amount Paid must be a reasonable number'
    except:
        return "What you entered for Amount Paid ({}) isn't even a number".format(group.amount_paid)


def _invalid_phone_number(s):
    return s.startswith('+') or len(re.findall(r'\d', s)) != 10

def attendee_misc(attendee):
    if attendee.group_id and not attendee.first_name.strip() and not attendee.last_name.strip():
        return

    if not attendee.first_name or not attendee.last_name:
        return 'First Name and Last Name are required'
    elif attendee.placeholder:
        return

    if (AT_THE_CON and attendee.email and not re.match(EMAIL_RE, attendee.email)) or (not AT_THE_CON and not re.match(EMAIL_RE, attendee.email)):
        return 'Enter a valid email address'

    if not attendee.international and not AT_THE_CON:
        if not re.match(r'^\d{5}$', attendee.zip_code):
            return 'Enter a valid zip code'

        if _invalid_phone_number(attendee.ec_phone):
            return 'Enter a 10-digit emergency contact number'

        if attendee.cellphone and _invalid_phone_number(attendee.cellphone):
            return 'Invalid 10-digit cellphone number'

    if not attendee.no_cellphone and attendee.staffing and _invalid_phone_number(attendee.cellphone):
        return "10-digit cellphone number is required for volunteers (unless you don't own a cellphone)"
    if attendee.age_group == UNDER_18 and attendee.staffing and attendee.badge_type != STAFF_BADGE and PRE_CON:
        return "Volunteers must be or older than 18 years of age to volunteer"

def attendee_leadership(attendee):
    if attendee.session and not attendee.group_id:
        orig_group_id = attendee.orig_value_of('group_id')
        if orig_group_id and attendee.id == attendee.session.group(orig_group_id).leader_id:
            return 'You cannot remove the leader of a group from that group; make someone else the leader first'

def attendee_banned_volunteer(attendee):
    if (attendee.ribbon == VOLUNTEER_RIBBON or attendee.staffing) and attendee.full_name in BANNED_STAFFERS:
        return "We've declined to invite {} back as a volunteer, {}".format(attendee.full_name,
                'talk to Stops to override if necessary' if AT_THE_CON
            else 'email stops@magfest.org if you believe this is in error')

def attendee_money(attendee):
    try:
        amount_paid = int(float(attendee.amount_paid))
        if amount_paid < 0:
            return 'Amount Paid cannot be less than zero'
    except:
        return "What you entered for Amount Paid ({}) wasn't even a number".format(attendee.amount_paid)

    try:
        amount_extra = int(float(attendee.amount_extra or 0))
        if amount_extra < 0:
            return 'Amount extra must be a positive integer'
    except:
        return 'Invalid amount extra ({})'.format(attendee.amount_extra)

    try:
        amount_refunded = int(float(attendee.amount_refunded))
        if amount_refunded < 0:
            return 'Amount Refunded must be positive'
        elif amount_refunded > amount_paid:
            return 'Amount Refunded cannot be greater than Amount Paid'
        elif attendee.paid == REFUNDED and amount_refunded == 0:
            return 'Amount Refunded may not be 0 if the attendee is marked Paid and Refunded'
    except:
        return "What you entered for Amount Refunded ({}) wasn't even a number".format(attendee.amount_refunded)

def attendee_badge_range(attendee):
    if AT_THE_CON:
        min_num, max_num = BADGE_RANGES[attendee.badge_type]
        if attendee.badge_num != 0 and not (min_num <= attendee.badge_num <= max_num):
            return '{} badge numbers must fall within {} and {}'.format(attendee.badge_type_label, min_num, max_num)


def money_amount(money):
    if not str(money.amount).isdigit():
        return 'Amount must be a positive number'


job_required = [('name','Job Name')]

def job_slots(job):
    if job.slots < len(job.shifts):
        return 'You cannot reduce the number of slots to below the number of staffers currently signed up for this job'

def job_conflicts(job):
    if not job.is_new:
        original_hours = Job(start_time=job.orig_value_of('start_time'), duration=job.orig_value_of('duration')).hours
        for shift in job.shifts:
            if job.hours.intersection(shift.attendee.hours - original_hours):
                return 'You cannot change this job to this time, because {} is already working a shift then'.format(shift.attendee.full_name)


cashformpoints_amount = money_amount

def oldmpointexchange_numbers(mpe):
    if not str(mpe.mpoints).isdigit():
        return 'MPoints must be a positive integer'

sale_required = [('what',"What's being sold")]
def sale_amounts(sale):
    if not str(sale.cash).isdigit() or int(sale.cash) < 0:
        return 'Cash must be a positive integer'
    if not str(sale.mpoints).isdigit() or int(sale.mpoints) < 0:
        return 'MPoints must be a positive integer'
