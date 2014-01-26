from uber.common import *

def check_everything(attendee):
    if AT_THE_CON and attendee.id is None:
        if isinstance(attendee.badge_num, str) or attendee.badge_num < 0:
            return 'Invalid badge number'
        elif attendee.id is None and attendee.badge_num != 0 and Attendee.objects.filter(badge_type=attendee.badge_type, badge_num=attendee.badge_num).count():
            return 'Another attendee already exists with that badge number'

    if attendee.is_dealer and not attendee.group:
        return 'Dealers must be associated with a group'

    message = check(attendee)
    if message:
        return message

    if AT_THE_CON and attendee.age_group == AGE_UNKNOWN and attendee.id is None:
        return "You must enter this attendee's age group"

def unassigned_counts():
    return {row['group_id']: row['unassigned']
            for row in Attendee.objects.exclude(group=None)
                                       .filter(first_name='')
                                       .values('group_id')
                                       .annotate(unassigned=Count('id'))}

@all_renderable(PEOPLE)
class Root:
    def index(self, message='', page='1', search_text='', uploaded_id='', order='last_name'):
        order_by = [order, 'first_name'] if order.endswith('last_name') else [order]
        total_count = Attendee.objects.count()
        count = 0
        if search_text:
            attendees = search(search_text)
            count = attendees.count()
        if not count:
            attendees = Attendee.objects.all()
            count = total_count
        attendees = attendees.select_related('group').order_by(*order_by)

        if search_text and count == total_count:
            message = 'No matches found'
        elif search_text and count == 1 and (not AT_THE_CON or search_text.isdigit()):
            raise HTTPRedirect('form?id={}&message={}', attendees[0].id, 'This attendee was the only search result')

        page = int(page)
        pages = range(1, int(math.ceil(count / 100)) + 1)
        attendees = attendees[-100 + 100*page : 100*page]

        return {
            'message':        message if isinstance(message, str) else message[-1],
            'page':           page,
            'pages':          pages,
            'search_text':    search_text,
            'search_results': bool(search_text),
            'attendees':      attendees,
            'order':          Order(order),
            'attendee_count': total_count,
            'checkin_count':  Attendee.objects.exclude(checked_in__isnull = True).count(),
            'attendee':       Attendee.objects.get(id = uploaded_id) if uploaded_id else None
        }

    def form(self, message='', return_to='', omit_badge='', **params):
        attendee = Attendee.get(params, checkgroups = ['interests','requested_depts','assigned_depts'],
                                bools = ['staffing','trusted','international','placeholder','got_merch','can_spam'])
        if 'first_name' in params:
            attendee.group = None if not params['group_opt'] else Group.objects.get(id = params['group_opt'])

            if AT_THE_CON and omit_badge:
                attendee.badge_num = 0
            message = check_everything(attendee)
            if not message:
                attendee.save()

                if return_to:
                    raise HTTPRedirect(return_to + '&message={}', 'Attendee data uploaded')
                else:
                    raise HTTPRedirect('index?uploaded_id={}&message={}&search_text={}', attendee.id, 'has been uploaded',
                        '{} {}'.format(attendee.first_name, attendee.last_name) if AT_THE_CON else '')

        return {
            'message':    message,
            'attendee':   attendee,
            'return_to':  return_to,
            'omit_badge': omit_badge,
            'group_opts': [(b.id, b.name) for b in Group.objects.order_by('name')],
            'unassigned': unassigned_counts()
        }

    def change_badge(self, message='', **params):
        attendee = Attendee.get(dict(params, badge_num = params.get('newnum') or 0), allowed = ['badge_num'])

        if 'badge_type' in params:
            preassigned = AT_THE_CON or attendee.badge_type in PREASSIGNED_BADGE_TYPES
            if preassigned:
                message = check(attendee)

            if not message:
                message = change_badge(attendee)
                raise HTTPRedirect('form?id={}&message={}', attendee.id, message)

        return {
            'message':  message,
            'attendee': attendee
        }

    def history(self, id):
        attendee = Attendee.objects.get(id = id)
        Tracking.objects.filter(links__contains = 'Attendee({})'.format(id))
        return {
            'attendee': attendee,
            'emails':   Email.objects.filter(Q(dest = attendee.email) 
                                           | Q(model = 'Attendee', fk_id = id))
                                     .order_by('when'),
            'changes':  Tracking.objects.filter(Q(model = 'Attendee', fk_id = id)
                                              | Q(links__contains = 'Attendee({})'.format(id)))
                                        .order_by('when')
        }

    @csrf_protected
    def delete(self, id, return_to = 'index?'):
        attendee = Attendee.objects.get(id=id)
        attendee.delete()
        message = 'Attendee deleted'
        if attendee.group:
            Attendee.objects.create(group = attendee.group, paid = attendee.paid,
                                    badge_type = attendee.badge_type, badge_num = attendee.badge_num)
            message = 'Attendee deleted, but badge ' + attendee.badge + ' is still available to be assigned to someone else'

        raise HTTPRedirect(return_to + ('' if return_to[-1] == '?' else '&') + 'message={}', message)

    def goto_volunteer_checklist(self, id):
        cherrypy.session['staffer_id'] = id
        raise HTTPRedirect('../signups/index')

    @ajax
    def record_mpoint_usage(self, badge_num, amount):
        try:
            attendee = Attendee.objects.get(badge_num = badge_num)
        except:
            return {'success':False, 'message':'No one has badge number {}'.format(badge_num)}

        mpu = CashForMPoints(attendee = attendee, amount = amount)
        message = check(mpu)
        if message:
            return {'success':False, 'message':message}
        else:
            mpu.save()
            message = '{mpu.attendee.full_name} exchanged {mpu.amount} MPoints for cash'.format(mpu = mpu)
            return {'id':mpu.id, 'success':True, 'message':message}

    @ajax
    def undo_mpoint_usage(self, id):
        CashForMPoints.objects.get(id=id).delete()
        return 'MPoint usage deleted'

    @ajax
    def record_mpoint_exchange(self, badge_num, mpoints):
        try:
            attendee = Attendee.objects.get(badge_num = badge_num)
        except:
            return {'success':False, 'message':'No one has badge number {}'.format(badge_num)}

        mpe = OldMPointExchange(attendee = attendee, mpoints = mpoints)
        message = check(mpe)
        if message:
            return {'success':False, 'message':message}
        else:
            mpe.save()
            message = "{mpe.attendee.full_name} exchanged {mpe.mpoints} of last year's MPoints".format(mpe = mpe)
            return {'id':mpe.id, 'success':True, 'message':message}

    @ajax
    def undo_mpoint_exchange(self, id):
        OldMPointExchange.objects.get(id=id).delete()
        return 'MPoint exchange deleted'

    @ajax
    def record_sale(self, badge_num=None, **params):
        params['reg_station'] = cherrypy.session.get('reg_station')
        sale = Sale.get(params)
        message = check(sale)
        if not message and badge_num is not None:
            try:
                sale.attendee = Attendee.objects.get(badge_num = badge_num)
            except:
                message = 'No attendee has that badge number'

        if message:
            return {'success':False, 'message':message}
        else:
            sale.save()
            message = '{sale.what} sold{to} for ${sale.cash}{mpoints}'.format(sale = sale,
                to = (' to ' + sale.attendee.full_name) if sale.attendee else '',
                mpoints = ' and {} MPoints'.format(sale.mpoints) if sale.mpoints else '')
            return {'id':sale.id, 'success':True, 'message':message}

    @ajax
    def undo_sale(self, id):
        Sale.objects.get(id=id).delete()
        return 'Sale deleted'

    @ajax
    def check_in(self, id, badge_num, age_group):
        attendee = Attendee.objects.get(id=id)
        pre_paid = attendee.paid
        pre_amount = attendee.amount_paid
        pre_badge = attendee.badge_num
        success, increment = True, False

        if not attendee.badge_num:
            message = check_range(badge_num, attendee.badge_type)
            if not message:
                maybe_dupe = Attendee.objects.filter(badge_num=badge_num, badge_type=attendee.badge_type)
                if maybe_dupe:
                    message = 'That badge number already belongs to ' + maybe_dupe[0].full_name
            success = not message

        if success and attendee.checked_in:
            message = attendee.full_name + ' was already checked in!'
        elif success:
            message = ''
            attendee.checked_in = datetime.now()
            attendee.age_group = int(age_group)
            if not attendee.badge_num:
                attendee.badge_num = int(badge_num)
            if attendee.paid == NOT_PAID:
                attendee.paid = HAS_PAID
                attendee.amount_paid = attendee.total_cost
                message += '<b>This attendee has not paid for their badge; make them pay ${0}!</b> <br/>'.format(attendee.total_cost)
            attendee.save()
            increment = True

            message += '{0.full_name} checked in as {0.badge} with {0.accoutrements}'.format(attendee)

        return {
            'success':    success,
            'message':    message,
            'increment':  increment,
            'badge':      attendee.badge,
            'paid':       attendee.get_paid_display(),
            'age_group':  attendee.get_age_group_display(),
            'pre_paid':   pre_paid,    # TODO: this is no longer necessary
            'pre_amount': pre_amount,  # TODO: this is no longer necessary
            'pre_badge':  pre_badge,
            'checked_in': attendee.checked_in and hour_day_format(attendee.checked_in)
        }

    @csrf_protected
    def undo_checkin(self, id, pre_paid, pre_amount, pre_badge):
        # TODO: this no longer needs to take the pre_paid and pre_amount parameters
        a = Attendee.objects.get(id = id)
        a.checked_in, a.badge_num = None, pre_badge
        a.save()
        return 'Attendee successfully un-checked-in'

    def recent(self):
        return {'attendees': Attendee.objects.order_by('-registered')}

    def merch(self, message=''):
        return {'message': message}

    @ajax
    def check_merch(self, badge_num):
        id = shirt = None
        if not (badge_num.isdigit() and 0 < int(badge_num) < 99999):
            message = 'Invalid badge number'
        else:
            results = Attendee.objects.filter(badge_num = badge_num)
            if results.count() != 1:
                message = 'No attendee has badge number {}'.format(badge_num)
            else:
                attendee = results[0]
                if not attendee.merch:
                    message = '{a.full_name} ({a.badge}) has no merch'.format(a = attendee)
                elif attendee.got_merch:
                    message = '{a.full_name} ({a.badge}) already got {a.merch}'.format(a = attendee)
                else:
                    id = attendee.id
                    shirt = (attendee.shirt or SIZE_UNKNOWN) if attendee.gets_shirt else NO_SHIRT
                    message = '{a.full_name} ({a.badge}) has not yet received {a.merch}'.format(a = attendee)
        return {
            'id': id,
            'shirt': shirt,
            'message': message
        }

    @ajax
    def give_merch(self, id, shirt_size, no_shirt):
        try:
            shirt_size = int(shirt_size)
        except:
            shirt_size = None

        success = False
        attendee = Attendee.objects.get(id = id)
        if not attendee.merch:
            message = '{} has no merch'.format(attendee.full_name)
        elif attendee.got_merch:
            message = '{} already got {}'.format(attendee.full_name, attendee.merch)
        elif shirt_size == SIZE_UNKNOWN:
            message = 'You must select a shirt size'
        else:
            if no_shirt:
                message = '{} is now marked as having received all of the following (EXCEPT FOR THE SHIRT): {}'
            else:
                message = '{} is now marked as having received {}'
            message = message.format(attendee.full_name, attendee.merch)
            attendee.got_merch = True
            if shirt_size:
                attendee.shirt = shirt_size
            attendee.save()
            if no_shirt:
                NoShirt.objects.create(attendee = attendee)
            success = True

        return {
            'id': id,
            'success': success,
            'message': message
        }

    @ajax
    def take_back_merch(self, id):
        attendee = Attendee.objects.get(id = id)
        attendee.got_merch = False
        attendee.save()
        for ns in attendee.noshirt_set.all():
            ns.delete()
        return '{a.full_name} ({a.badge}) merch handout canceled'.format(a = attendee)

    if AT_THE_CON or DEV_BOX:
        @unrestricted
        def register(self, message='', **params):
            params['id'] = 'None'
            attendee = Attendee.get(params, bools=['international'], checkgroups=['interests'], restricted=True, ignore_csrf=True)
            if 'first_name' in params:
                if not attendee.payment_method:
                    message = 'Please select a payment type'
                elif not attendee.first_name or not attendee.last_name:
                    message = 'First and Last Name are required fields'
                elif attendee.ec_phone[:1] != '+' and len(re.compile('[0-9]').findall(attendee.ec_phone)) != 10:
                    message = 'Enter a 10-digit emergency contact number'
                elif attendee.age_group == AGE_UNKNOWN:
                    message = 'Please select an age category'
                elif attendee.payment_method == MANUAL and not attendee.email:
                    message = 'Email address is required to pay with a credit card at our registration desk'
                elif attendee.badge_type not in [ATTENDEE_BADGE, ONE_DAY_BADGE]:
                    message = 'No hacking allowed!'
                else:
                    attendee.badge_num = 0
                    if not attendee.zip_code:
                        attendee.zip_code = '00000'
                    attendee.save()
                    message = 'Thanks!  Please queue in the {} line and have your photo ID and {} ready.'
                    if attendee.payment_method == STRIPE:
                        raise HTTPRedirect('pay?id={}', attendee.secret_id)
                    elif attendee.payment_method == GROUP:
                        message = 'Please proceed to the preregistration line to pick up your badge.'
                    elif attendee.payment_method == CASH:
                        message = message.format('cash', '${}'.format(attendee.total_cost))
                    elif attendee.payment_method == MANUAL:
                        message = message.format('credit card', 'credit card')
                    raise HTTPRedirect('register?message={}', message)

            return {
                'message':  message,
                'attendee': attendee
            }

        @unrestricted
        def pay(self, id, message=''):
            attendee = Attendee.objects.get(secret_id = id)
            if attendee.paid == HAS_PAID:
                raise HTTPRedirect('register?message={}', 'You are already paid and should proceed to the preregistration desk to pick up your badge')
            else:
                return {
                    'message': message,
                    'attendee': attendee,
                    'charge': Charge(attendee, description = attendee.full_name)
                }

        @unrestricted
        @credit_card
        def take_payment(self, payment_id, stripeToken):
            charge = Charge.get(payment_id)
            [attendee] = charge.attendees
            message = charge.charge_cc(stripeToken)
            if message:
                raise HTTPRedirect('pay?id={}&message={}', attendee.secret_id, message)
            else:
                attendee.paid = HAS_PAID
                attendee.amount_paid = attendee.total_cost
                attendee.save()
                raise HTTPRedirect('register?message={}', 'Your payment has been accepted, please proceed to the Preregistration desk to pick up your badge')

    def comments(self, order = 'last_name'):
        return {
            'order': Order(order),
            'attendees': Attendee.objects.exclude(comments = '').order_by(order)
        }

    def new(self, show_all='', message='', checked_in=''):
        if 'reg_station' not in cherrypy.session:
            raise HTTPRedirect('new_reg_station')

        groups = set()
        for a in Attendee.objects.filter(first_name='', group__isnull=False).select_related('group'):
            groups.add((a.group.id, a.group.name or 'BLANK'))

        if show_all:
            restrict_to = {'paid': NOT_PAID, 'placeholder': False}
        if not show_all:
            restrict_to = {'registered__gte': datetime.now() - timedelta(minutes=90)}

        return {
            'message':    message,
            'show_all':   show_all,
            'checked_in': checked_in,
            'groups':     sorted(groups, key = lambda tup: tup[1]),
            'recent':     Attendee.objects.filter(badge_num=0, **restrict_to).exclude(first_name='').order_by('registered')
        }

    def new_reg_station(self, reg_station='', message=''):
        if reg_station:
            if not reg_station.isdigit() or not (0 <= int(reg_station) < 100):
                message = 'Reg station must be a positive integer between 0 and 100'

            if not message:
                cherrypy.session['reg_station'] = int(reg_station)
                raise HTTPRedirect('new?message={}', 'Reg station number recorded')

        return {
            'message': message,
            'reg_station': reg_station
        }

    @csrf_protected
    def mark_as_paid(self, id, payment_method):
        if cherrypy.session['reg_station'] == 0:
            raise HTTPRedirect('new_reg_station?message={}', 'Reg station 0 is for prereg only and may not accept payments')
        elif int(payment_method) == MANUAL:
            raise HTTPRedirect('manual_reg_charge_form?id={}', id)

        attendee = Attendee.objects.get(id = id)
        attendee.paid = HAS_PAID
        attendee.payment_method = payment_method
        attendee.amount_paid = attendee.total_cost
        attendee.reg_station = cherrypy.session['reg_station']
        attendee.save()
        raise HTTPRedirect('new?message={}', 'Attendee marked as paid')

    def manual_reg_charge_form(self, id):
        attendee = Attendee.objects.get(id=id)
        if attendee.paid != NOT_PAID:
            raise HTTPRedirect('new?message={}{}', attendee.full_name, ' is already marked as paid')

        return {
            'attendee': attendee,
            'charge': Charge(attendee)
        }

    @credit_card
    def manual_reg_charge(self, payment_id, stripeToken):
        charge = Charge.get(payment_id)
        [attendee] = charge.attendees
        message = charge.charge_cc(stripeToken)
        if message:
            raise HTTPRedirect('new_credit_form?id={}&message={}', attendee.id, message)
        else:
            attendee.paid = HAS_PAID
            attendee.amount_paid = attendee.total_cost
            attendee.save()
            raise HTTPRedirect('new?message={}', 'Payment accepted')

    @csrf_protected
    def new_checkin(self, id, badge_num, ec_phone='', message='', group=''):
        checked_in = ''
        badge_num = int(badge_num) if badge_num.isdigit() else 0
        attendee = Attendee.objects.get(id=id)
        existing = list(Attendee.objects.filter(badge_num = badge_num))
        if 'reg_station' not in cherrypy.session:
            raise HTTPRedirect('new_reg_station')
        elif not badge_num:
            message = "You didn't enter a valid badge number"
        elif existing:
            message = '{0.badge} already belongs to {0.full_name}'.format(existing[0])
        else:
            badge_type, message = get_badge_type(badge_num)
            attendee.badge_type = badge_type
            attendee.badge_num = badge_num
            if not message:
                if group:
                    group = Group.objects.get(id = group)
                    with BADGE_LOCK:
                        available = [a for a in group.attendee_set.filter(first_name = '')]
                        matching = [a for a in available if a.badge_type == badge_type]
                        if not available:
                            message = 'The last badge for that group has already been assigned by another station'
                        elif not matching:
                            message = 'Badge #{} is a {} badge, but {} has no badges of that type'.format(badge_num, attendee.get_badge_type_display(), group.name)
                        else:
                            for attr in ['group','paid','amount_paid','ribbon']:
                                setattr(attendee, attr, getattr(matching[0], attr))
                            matching[0].delete()
                elif attendee.paid != HAS_PAID:
                    message = 'You must mark this attendee as paid before you can check them in'

        if not message:
            attendee.ec_phone = ec_phone
            attendee.checked_in = datetime.now()
            attendee.reg_station = cherrypy.session['reg_station']
            attendee.save()
            message = '{a.full_name} checked in as {a.badge} with {a.accoutrements}'.format(a = attendee)
            checked_in = attendee.id

        raise HTTPRedirect('new?message={}&checked_in={}', message, checked_in)

    def arbitrary_charge_form(self, message='', amount=None, description=''):
        charge = None
        if amount is not None:
            if not amount.isdigit() or not (1 <= int(amount) <= 999):
                message = 'Amount must be a dollar amount between $1 and $999'
            elif not description:
                message = "You must enter a brief description of what's being sold"
            else:
                charge = Charge(amount = 100 * int(amount), description = description)

        return {
            'charge': charge,
            'message': message,
            'amount': amount,
            'description': description
        }

    @credit_card
    def arbitrary_charge(self, payment_id, stripeToken):
        charge = Charge.get(payment_id)
        message = charge.charge_cc(stripeToken)
        if message:
            raise HTTPRedirect('arbitrary_charge_form?message={}', message)
        else:
            ArbitraryCharge.objects.create(
                amount = charge.dollar_amount,
                what = charge.description,
                reg_station = cherrypy.session.get('reg_station'))
            raise HTTPRedirect('arbitrary_charge_form?message={}', 'Charge successfully processed')

    def reg_take_report(self, **params):
        if params:
            start = datetime.strptime('{startday} {starthour}:{startminute}'.format(**params), '%Y-%m-%d %H:%M')
            end = datetime.strptime('{endday} {endhour}:{endminute}'.format(**params), '%Y-%m-%d %H:%M')
            sales = Sale.objects.filter(reg_station=params['reg_station'], when__gt=start, when__lte=end)
            attendees = Attendee.objects.filter(reg_station=params['reg_station'], amount_paid__gt=0,
                                                registered__gt=start, registered__lte=end)
            params['sales'] = sales
            params['attendees'] = attendees
            params['total_cash'] = sum(a.amount_paid for a in attendees if a.payment_method == CASH) \
                                 + sum(s.cash for s in sales if s.payment_method == CASH)
            params['total_credit'] = sum(a.amount_paid for a in attendees if a.payment_method in [STRIPE, SQUARE, MANUAL]) \
                                   + sum(s.cash for s in sales if s.payment_method == CREDIT)
        else:
            params['endday'] = datetime.now().strftime('%Y-%m-%d')
            params['endhour'] = datetime.now().strftime('%H')
            params['endminute'] = datetime.now().strftime('%M')

        stations = sorted(filter(bool, Attendee.objects.values_list('reg_station', flat=True).distinct()))
        params['reg_stations'] = stations
        params.setdefault('reg_station', stations[0] if stations else 0)
        return params

    def undo_new_checkin(self, id):
        attendee = Attendee.objects.get(id = id)
        if attendee.group:
            unassigned = Attendee.objects.create(group = attendee.group, paid = PAID_BY_GROUP, badge_type = attendee.badge_type, ribbon = attendee.ribbon)
            unassigned.registered = datetime(EPOCH.year, 1, 1)
            unassigned.save()
        attendee.badge_num = 0
        attendee.checked_in = attendee.group = None
        attendee.save()
        raise HTTPRedirect('new?message={}', 'Attendee un-checked-in')

    def shifts(self, id, shift_id='', message=''):
        jobs, shifts, attendees = Job.everything()
        [attendee] = [a for a in attendees if a.id == int(id)]
        if AT_THE_CON:
            attendee._possible = [job for job in jobs if datetime.now() < job.start_time
                                                     and job.slots > len(job.shifts)
                                                     and (not job.restricted or attendee.trusted)
                                                     and job.location != MOPS]
        return {
            'message':  message,
            'shift_id': shift_id,
            'attendee': attendee,
            'possible': attendee.possible_opts,
            'shifts':   Shift.serialize(attendee.shift_set.all())
        }

    @csrf_protected
    def update_nonshift(self, id, nonshift_hours):
        attendee = Attendee.objects.get(id = id)
        if not re.match('^[0-9]+$', nonshift_hours):
            raise HTTPRedirect('shifts?id={}&message={}', attendee.id, 'Invalid integer')

        attendee.nonshift_hours = nonshift_hours
        attendee.save()
        raise HTTPRedirect('shifts?id={}&message={}', attendee.id, 'Non-shift hours updated')

    @csrf_protected
    def update_notes(self, id, admin_notes, for_review=None):
        attendee = Attendee.objects.get(id = id)
        attendee.admin_notes = admin_notes
        if for_review is not None:
            attendee.for_review = for_review
        attendee.save()
        raise HTTPRedirect('shifts?id={}&message={}', id, 'Admin notes updated')

    @csrf_protected
    def assign(self, staffer_id, job_id):
        message = assign(staffer_id, job_id) or 'Shift added'
        raise HTTPRedirect('shifts?id={}&message={}', staffer_id, message)

    @csrf_protected
    def unassign(self, shift_id):
        shift = Shift.objects.get(id=shift_id)
        shift.delete()
        raise HTTPRedirect('shifts?id={}&message={}', shift.attendee.id, 'Staffer unassigned from shift')

    def feed(self, page = '1', who = '', what = ''):
        feed = Tracking.objects.exclude(action = AUTO_BADGE_SHIFT).order_by('-id')
        if who:
            feed = feed.filter(who = who)
        if what:
            feed = feed.filter(Q(data__icontains = what) | Q(which__icontains = what))
        return {
            'who': who,
            'what': what,
            'page': page,
            'count': feed.count(),
            'feed': get_page(page, feed),
            'who_opts': Tracking.objects.values_list('who', flat=True).order_by('who').distinct(),
        }

    def staffers(self, message='', order='first_name'):
        shifts = defaultdict(list)
        for shift in Shift.objects.select_related():
            shifts[shift.attendee].append(shift)

        staffers = list(Attendee.objects.filter(staffing = True))
        for staffer in staffers:
            staffer._shifts = shifts[staffer]

        return {
            'order': Order(order),
            'message': message,
            'staffer_count': len(staffers),
            'total_hours': sum(j.weighted_hours * j.slots for j in Job.objects.all()),
            'taken_hours': sum(s.job.weighted_hours for s in Shift.objects.select_related()),
            'staffers': sorted(staffers, key = lambda a: getattr(a, order.lstrip('-')), reverse = order.startswith('-'))
        }

    def review(self):
        return {'attendees': Attendee.objects.exclude(for_review = '').order_by('first_name','last_name')}

    def season_pass_tickets(self):
        events = defaultdict(list)
        for spt in SeasonPassTicket.objects.select_related().order_by('attendee__first_name'):
            events[spt.slug].append(spt.attendee)
        return {'events': dict(events)}

    @site_mappable
    def discount(self, message='', **params):
        attendee = Attendee.get(params)
        if 'first_name' in params:
            if not attendee.first_name or not attendee.last_name:
                message = 'First and Last Name are required'
            elif not attendee.overridden_price:
                message = 'Discounted Price is required'
            elif attendee.overridden_price > state.BADGE_PRICE:
                message = 'You cannot create a discounted badge that costs more than the regular price!'

            if not message:
                attendee.placeholder = True
                attendee.badge_type = ATTENDEE_BADGE
                attendee.save()
                raise HTTPRedirect('../preregistration/confirm?id={}', attendee.secret_id)

        return {'message': message}
