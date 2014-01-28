from uber.common import *


account_required = [('name','Full Name'), ('email','Email Address'), ('hashed','Password')]

def account_misc(account):
    if account.id is None and Account.objects.filter(email__iexact=account.email).count():
        return 'That email address is already being used by another account'
    
    if not re.match(EMAIL_RE, account.email):
        return "That's not a valid email address"
    
    return ''


event_required = [('name','Event Name')]

def event_overlaps(event, other_event_id = None):
    existing = {}
    for e in Event.objects.filter(location = event.location).exclude(id = event.id).exclude(id = other_event_id):
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
    if attendee.group and not attendee.first_name.strip() and not attendee.last_name.strip():
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
        
        if attendee.phone and _invalid_phone_number(attendee.phone):
            return 'Invalid 10-digit cellphone number'
    
    if not attendee.no_cellphone and attendee.staffing and _invalid_phone_number(attendee.phone):
        return "10-digit cellphone number is required for volunteers (unless you don't own a cellphone)"

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
            return '{} badge numbers must fall within {} and {}'.format(attendee.get_badge_type_display(), min_num, max_num)


def money_amount(money):
    if not str(money.amount).isdigit():
        return 'Amount must be a positive number'


job_required = [('name','Job Name')]

def job_slots(job):
    if job.slots < job.shift_set.count():
        return 'You cannot reduce the number of slots to below the number of staffers currently signed up for this job'

def job_conflicts(job):
    original_hours = set() if job.id is None else Job.objects.get(id=job.id).hours
    
    for shift in job.shift_set.select_related():
        if job.hours.intersection( shift.attendee.hours - original_hours ):
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
