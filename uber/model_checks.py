"""
When an admin submits a form to create/edit an attendee/group/job/etc we usually want to perform some basic validations
on the data that was entered.  We put those validations here.  To make a validation for the Attendee model, you can
just write a function decorated with the @validation.Attendee decorator.  That function should return None on success
and an error string on failure.

In addition, you can define a set of required fields by setting the .required field like the AdminAccount.required list
below.  This should be a list of tuples where the first tuple element is the name of the field, and the second is the
name that should be displayed in the "XXX is a required field" error message.

To perform these validations, call the "check" method on the instance you're validating.  That method returns None
on success and a string error message on validation failure.
"""
from uber.common import *


AdminAccount.required = [('attendee', 'Attendee'), ('hashed', 'Password')]


@validation.AdminAccount
def duplicate_admin(account):
    if account.is_new:
        with Session() as session:
            if session.query(AdminAccount).filter_by(attendee_id=account.attendee_id).all():
                return 'That attendee already has an admin account'


@validation.AdminAccount
def has_email_address(account):
    if account.is_new:
        with Session() as session:
            if session.query(Attendee).filter_by(id=account.attendee_id).first().email == '':
                return "Attendee doesn't have a valid email set"


Group.required = [('name', 'Group Name')]


@prereg_validation.Group
def dealer_wares(group):
    if group.tables and not group.wares:
        return "You must provide a detailed explanation of what you sell for us to evaluate your submission"


@prereg_validation.Group
def dealer_website(group):
    if group.tables and not group.website:
        return "Please enter your business' website address"


@prereg_validation.Group
def dealer_description(group):
    if group.tables and not group.description:
        return "Please provide a brief description of your business"


@prereg_validation.Group
def dealer_address(group):
    if group.tables and not group.address and not c.COLLECT_FULL_ADDRESS:
        "Please provide your full address for tax purposes"


@validation.Group
def group_paid(group):
    try:
        amount = int(float(group.amount_paid))
        if amount < 0 or amount > 2000:
            return 'Amount Paid must be a reasonable number'
    except:
        return "What you entered for Amount Paid ({}) isn't even a number".format(group.amount_paid)


def _invalid_phone_number(s):
    if not s.startswith('+'):
        return len(re.findall(r'\d', s)) != 10 or re.search(c.SAME_NUMBER_REPEATED, re.sub(r'[^0-9]', '', s))


def _invalid_zip_code(s):
    return len(re.findall(r'\d', s)) not in [5, 9]


def ignore_unassigned_and_placeholders(func):
    @wraps(func)
    def with_skipping(attendee):
        unassigned_group_reg = attendee.group_id and not attendee.first_name and not attendee.last_name
        valid_placeholder = attendee.placeholder and attendee.first_name and attendee.last_name
        if not unassigned_group_reg and not valid_placeholder:
            return func(attendee)
    return with_skipping


@prereg_validation.Attendee
def dealer_cellphone(attendee):
    if attendee.badge_type == c.PSEUDO_DEALER_BADGE and not attendee.cellphone:
        return 'Your phone number is required'


@prereg_validation.Attendee
def shirt_size(attendee):
    if attendee.amount_extra >= c.SHIRT_LEVEL and attendee.shirt == c.NO_SHIRT:
        return 'Your shirt size is required'


@prereg_validation.Attendee
def total_cost_over_paid(attendee):
    if attendee.total_cost < attendee.amount_paid:
        return 'You have already paid ${}, you cannot reduce your extras below that.'.format(attendee.amount_paid)


@validation.Attendee
@ignore_unassigned_and_placeholders
def full_name(attendee):
    if not attendee.first_name:
        return 'First Name is a required field'
    elif not attendee.last_name:
        return 'Last Name is a required field'


@validation.Attendee
@ignore_unassigned_and_placeholders
def age(attendee):
    if c.COLLECT_EXACT_BIRTHDATE:
        if not attendee.birthdate:
            return 'Enter your date of birth.'
        elif attendee.birthdate > date.today():
            return 'You cannot be born in the future.'
    elif not attendee.age_group:
        return 'Please enter your age group'


@validation.Attendee
@ignore_unassigned_and_placeholders
def address(attendee):
    if c.COLLECT_FULL_ADDRESS:
        if not attendee.address1:
            return 'Enter your street address.'
        if not attendee.city:
            return 'Enter your city.'
        if not attendee.region:
            return 'Enter your state, province, or region.'
        if not attendee.country:
            return 'Enter your country.'


@validation.Attendee
@ignore_unassigned_and_placeholders
def email(attendee):
    if len(attendee.email) > 255:
        return 'Email addresses cannot be longer than 255 characters.'

    if (c.AT_THE_CON and attendee.email and not re.match(c.EMAIL_RE, attendee.email)) or (not c.AT_THE_CON and not re.match(c.EMAIL_RE, attendee.email)):
        return 'Enter a valid email address'


@validation.Attendee
@ignore_unassigned_and_placeholders
def emergency_contact(attendee):
    if not attendee.international and _invalid_phone_number(attendee.ec_phone):
        if c.COLLECT_FULL_ADDRESS:
            return 'Enter a 10-digit US phone number or include a country code (e.g. +44).'
        else:
            return 'Enter a 10-digit emergency contact number'


@validation.Attendee
@ignore_unassigned_and_placeholders
def cellphone(attendee):
    if attendee.cellphone and _invalid_phone_number(attendee.cellphone):
        if c.COLLECT_FULL_ADDRESS:
            return 'Enter a 10-digit US phone number or include a country code (e.g. +44).'
        else:
            return 'Your cellphone number was not a valid 10-digit phone number'

    if not attendee.no_cellphone and attendee.staffing and not attendee.cellphone:
        return "Cellphone number is required for volunteers (unless you don't own a cellphone)"


@validation.Attendee
@ignore_unassigned_and_placeholders
def zip_code(attendee):
    if not attendee.international and not c.AT_THE_CON:
        if _invalid_zip_code(attendee.zip_code):
            return 'Enter a valid zip code'


@validation.Attendee
def allowed_to_volunteer(attendee):
    if attendee.staffing and not attendee.age_group_conf['can_volunteer'] and attendee.badge_type != c.STAFF_BADGE and c.PRE_CON:
        return 'Volunteers cannot be ' + attendee.age_group_conf['desc']


@validation.Attendee
def allowed_to_register(attendee):
    if not attendee.age_group_conf['can_register']:
        return 'Attendees ' + attendee.age_group_conf['desc'] + ' years of age do not need to register, but MUST be accompanied by a parent at all times!'


@validation.Attendee
def printed_badge_deadline(attendee):
    if attendee.is_new and attendee.has_personalized_badge and c.AFTER_PRINTED_BADGE_DEADLINE:
        return 'Custom badges have already been ordered so you cannot create new {} badges'.format(attendee.badge_type_label)


@validation.Attendee
def group_leadership(attendee):
    if attendee.session and not attendee.group_id:
        orig_group_id = attendee.orig_value_of('group_id')
        if orig_group_id and attendee.id == attendee.session.group(orig_group_id).leader_id:
            return 'You cannot remove the leader of a group from that group; make someone else the leader first'


@validation.Attendee
def banned_volunteer(attendee):
    if (attendee.ribbon == c.VOLUNTEER_RIBBON or attendee.staffing) and attendee.full_name in c.BANNED_STAFFERS:
        return "We've declined to invite {} back as a volunteer, ".format(attendee.full_name) + (
                    'talk to Stops to override if necessary' if c.AT_THE_CON else
                    'Please contact us via {} if you believe this is in error'.format(c.CONTACT_URL))


@validation.Attendee
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

    if attendee.overridden_price is not None:
        try:
            overridden_price = int(float(attendee.overridden_price))
            if overridden_price < 0:
                return 'Overridden price must be a positive integer'
        except:
            return 'Invalid overridden price ({})'.format(attendee.overridden_price)
        else:
            if attendee.overridden_price == 0:
                return 'Please set the payment type to "doesn\'t need to" instead of setting the badge price to 0.'

    try:
        amount_refunded = int(float(attendee.amount_refunded))
        if amount_refunded < 0:
            return 'Amount Refunded must be positive'
        elif amount_refunded > amount_paid:
            return 'Amount Refunded cannot be greater than Amount Paid'
        elif attendee.paid == c.REFUNDED and amount_refunded == 0:
            return 'Amount Refunded may not be 0 if the attendee is marked Paid and Refunded'
    except:
        return "What you entered for Amount Refunded ({}) wasn't even a number".format(attendee.amount_refunded)


@validation.Attendee
def badge_range(attendee):
    if c.AT_THE_CON:
        try:
            badge_num = int(attendee.badge_num)
        except:
            return '{!r} is not a valid badge number'.format(attendee.badge_num)
        else:
            min_num, max_num = c.BADGE_RANGES[attendee.badge_type]
            if attendee.badge_num != 0 and not (min_num <= badge_num <= max_num):
                return '{} badge numbers must fall within {} and {}'.format(attendee.badge_type_label, min_num, max_num)


@validation.MPointsForCash
@validation.OldMPointExchange
def money_amount(model):
    if not str(model.amount).isdigit():
        return 'Amount must be a positive number'


Job.required = [('name', 'Job Name')]


@validation.Job
def slots(job):
    if job.slots < len(job.shifts):
        return 'You cannot reduce the number of slots to below the number of staffers currently signed up for this job'


@validation.Job
def time_conflicts(job):
    if not job.is_new:
        original_hours = Job(start_time=job.orig_value_of('start_time'), duration=job.orig_value_of('duration')).hours
        for shift in job.shifts:
            if job.hours.intersection(shift.attendee.hours - original_hours):
                return 'You cannot change this job to this time, because {} is already working a shift then'.format(shift.attendee.full_name)


@validation.OldMPointExchange
def oldmpointexchange_numbers(mpe):
    if not str(mpe.amount).isdigit():
        return 'MPoints must be a positive integer'


Sale.required = [('what', "What's being sold")]


@validation.Sale
def cash_and_mpoints(sale):
    if not str(sale.cash).isdigit() or int(sale.cash) < 0:
        return 'Cash must be a positive integer'
    if not str(sale.mpoints).isdigit() or int(sale.mpoints) < 0:
        return 'MPoints must be a positive integer'
