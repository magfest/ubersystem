import cherrypy
from pockets import listify

from uber.config import c
from uber.decorators import ajax, all_renderable, credit_card, public
from uber.errors import HTTPRedirect
from uber.models import ArbitraryCharge, Attendee, MerchDiscount, MerchPickup, \
    MPointsForCash, NoShirt, OldMPointExchange, Sale, Session
from uber.utils import check, check_csrf, Charge, hour_day_format
    
@all_renderable()
class Root:
    def index(self, message=''):
        return {'message': message}
    
    @public
    def arbitrary_charge_form(self, message='', amount=None, description='', sale_id=None):
        charge = None
        if amount is not None:
            if not amount.isdigit() or not (1 <= int(amount) <= 999):
                message = 'Amount must be a dollar amount between $1 and $999'
            elif not description:
                message = "You must enter a brief description of what's being sold"
            else:
                charge = Charge(amount=100 * int(amount), description=description)

        return {
            'charge': charge,
            'message': message,
            'amount': amount,
            'description': description,
            'sale_id': sale_id
        }
        
    @public
    @credit_card
    def arbitrary_charge(self, session, payment_id, stripeToken, return_to='arbitrary_charge_form'):
        charge = Charge.get(payment_id)
        message = charge.charge_cc(session, stripeToken)
        if message:
            raise HTTPRedirect('arbitrary_charge_form?message={}', message)
        else:
            session.add(ArbitraryCharge(
                amount=charge.dollar_amount,
                what=charge.description,
                reg_station=cherrypy.session.get('reg_station')
            ))
            raise HTTPRedirect('{}?message={}', return_to, 'Charge successfully processed')

    def multi_merch_pickup(self, session, message="", csrf_token=None, picker_upper=None, badges=(), **shirt_sizes):
        picked_up = []
        if csrf_token:
            check_csrf(csrf_token)
            try:
                picker_upper = session.query(Attendee).filter_by(badge_num=int(picker_upper)).one()
            except Exception:
                message = 'Please enter a valid badge number for the person picking up the merch: ' \
                    '{} is not in the system'.format(picker_upper)
            else:
                for badge_num in set(badges):
                    if badge_num:
                        try:
                            attendee = session.query(Attendee).filter_by(badge_num=int(badge_num)).one()
                        except Exception:
                            picked_up.append('{!r} is not a valid badge number'.format(badge_num))
                        else:
                            if attendee.got_merch:
                                picked_up.append(
                                    '{a.full_name} (badge {a.badge_num}) already got their merch'.format(a=attendee))
                            else:
                                attendee.got_merch = True
                                shirt_key = 'shirt_{}'.format(attendee.badge_num)
                                if shirt_key in shirt_sizes:
                                    attendee.shirt = int(listify(shirt_sizes.get(shirt_key, c.SIZE_UNKNOWN))[0])
                                picked_up.append('{a.full_name} (badge {a.badge_num}): {a.merch}'.format(a=attendee))
                                session.add(MerchPickup(picked_up_by=picker_upper, picked_up_for=attendee))
                session.commit()

        return {
            'message': message,
            'picked_up': picked_up,
            'picker_upper': picker_upper
        }

    @ajax
    def check_merch(self, session, badge_num, staff_merch=''):
        id = shirt = gets_swadge = None
        merch_items = []
        if not (badge_num.isdigit() and 0 < int(badge_num) < 99999):
            message = 'Invalid badge number'
        else:
            attendee = session.query(Attendee).filter_by(badge_num=badge_num).first()
            if not attendee:
                message = 'No attendee has badge number {}'.format(badge_num)
            else:
                if staff_merch:
                    merch = attendee.staff_merch
                    got_merch = attendee.got_staff_merch
                else:
                    merch, got_merch = attendee.merch, attendee.got_merch

                if not merch:
                    message = '{a.full_name} ({a.badge}) has no merch'.format(a=attendee)
                elif got_merch:
                    if not (not staff_merch and attendee.gets_swadge
                            and not attendee.got_swadge):
                        message = '{a.full_name} ({a.badge}) already got {merch}. Their shirt size is {shirt}'.format(
                            a=attendee, merch=merch, shirt=c.SHIRTS[attendee.shirt])
                    else:
                        id = attendee.id
                        gets_swadge = True
                        shirt = c.NO_SHIRT
                        message = '{a.full_name} has received all of their merch except for their swadge. ' \
                            'Click the "Give Merch" button below to mark them as receiving that.'.format(a=attendee)
                else:
                    id = attendee.id

                    if staff_merch:
                        merch_items = attendee.staff_merch_items
                    else:
                        merch_items = attendee.merch_items
                        gets_swadge = attendee.gets_swadge

                    if (staff_merch and attendee.num_staff_shirts_owed) or \
                            (not staff_merch and attendee.num_event_shirts_owed):
                        shirt = attendee.shirt or c.SIZE_UNKNOWN
                    else:
                        shirt = c.NO_SHIRT

                    message = '{a.full_name} ({a.badge}) has not yet received their merch.'.format(a=attendee)
                    if attendee.amount_unpaid and not staff_merch:
                        merch_items.insert(0, 
                                           'WARNING: Attendee is not fully paid up and may not have paid for their merch. '
                                           'Please contact Registration.')

        return {
            'id': id,
            'shirt': shirt,
            'message': message,
            'merch_items': merch_items,
            'gets_swadge': gets_swadge,
            'swadges_available': c.SWADGES_AVAILABLE
        }

    @ajax
    def give_merch(self, session, id, shirt_size, no_shirt, staff_merch, give_swadge=None):
        try:
            shirt_size = int(shirt_size)
        except Exception:
            shirt_size = None

        success = False
        attendee = session.attendee(id, allow_invalid=True)
        merch = attendee.staff_merch if staff_merch else attendee.merch
        got = attendee.got_staff_merch if staff_merch else attendee.got_merch
        if not merch:
            message = '{} has no merch'.format(attendee.full_name)
        elif got and give_swadge and not attendee.got_swadge:
            message = '{a.full_name} marked as receiving their swadge'.format(
                a=attendee)
            success = True
            attendee.got_swadge = True
            session.commit()
        elif got:
            message = '{} already got {}'.format(attendee.full_name, merch)
        elif shirt_size == c.SIZE_UNKNOWN:
            message = 'You must select a shirt size'
        else:
            if no_shirt:
                message = '{} is now marked as having received all of the following (EXCEPT FOR THE SHIRT): {}'
            else:
                message = '{} is now marked as having received {}'
            message = message.format(attendee.full_name, merch)
            setattr(attendee,
                    'got_staff_merch' if staff_merch else 'got_merch', True)
            if give_swadge:
                attendee.got_swadge = True
            if shirt_size:
                attendee.shirt = shirt_size
            if no_shirt:
                session.add(NoShirt(attendee=attendee))
            success = True
            session.commit()

        return {
            'id': id,
            'success': success,
            'message': message
        }

    @ajax
    def take_back_merch(self, session, id, staff_merch=None):
        attendee = session.attendee(id, allow_invalid=True)
        if staff_merch:
            attendee.got_staff_merch = False
        else:
            attendee.got_merch = attendee.got_swadge = False
            c._swadges_available = False  # force db check next time
        if attendee.no_shirt:
            session.delete(attendee.no_shirt)
        session.commit()
        return '{a.full_name} ({a.badge}) merch handout canceled'.format(a=attendee)

    @ajax
    def redeem_merch_discount(self, session, badge_num, apply=''):
        try:
            attendee = session.query(Attendee).filter_by(badge_num=badge_num).one()
        except Exception:
            return {'error': 'No attendee exists with that badge number.'}

        if attendee.badge_type != c.STAFF_BADGE:
            return {'error': 'Only staff badges are eligible for discount.'}

        discount = session.query(MerchDiscount).filter_by(attendee_id=attendee.id).first()
        if not apply:
            if discount:
                return {
                    'warning': True,
                    'message': 'This staffer has already redeemed their discount {} time{}'.format(
                        discount.uses, 's' if discount.uses > 1 else '')
                }
            else:
                return {'message': 'Tell staffer their discount is only usable one time '
                                   'and confirm that they want to redeem it.'}

        discount = discount or MerchDiscount(attendee_id=attendee.id, uses=0)
        discount.uses += 1
        session.add(discount)
        session.commit()
        return {'success': True, 'message': 'Discount on badge #{} has been marked as redeemed.'.format(badge_num)}
    
    @ajax
    def record_mpoint_cashout(self, session, badge_num, amount):
        try:
            attendee = session.attendee(badge_num=badge_num)
        except Exception:
            return {'success': False, 'message': 'No one has badge number {}'.format(badge_num)}

        mfc = MPointsForCash(attendee=attendee, amount=amount)
        message = check(mfc)
        if message:
            return {'success': False, 'message': message}
        else:
            session.add(mfc)
            session.commit()
            message = '{mfc.attendee.full_name} exchanged {mfc.amount} MPoints for cash'.format(mfc=mfc)
            return {'id': mfc.id, 'success': True, 'message': message}

    @ajax
    def undo_mpoint_cashout(self, session, id):
        session.delete(session.mpoints_for_cash(id))
        return 'MPoint usage deleted'

    @ajax
    def record_old_mpoint_exchange(self, session, badge_num, amount):
        try:
            attendee = session.attendee(badge_num=badge_num)
        except Exception:
            return {'success': False, 'message': 'No one has badge number {}'.format(badge_num)}

        ome = OldMPointExchange(attendee=attendee, amount=amount)
        message = check(ome)
        if message:
            return {'success': False, 'message': message}
        else:
            session.add(ome)
            session.commit()
            message = "{ome.attendee.full_name} exchanged {ome.amount} of last year's MPoints".format(ome=ome)
            return {'id': ome.id, 'success': True, 'message': message}

    @ajax
    def undo_mpoint_exchange(self, session, id):
        session.delete(session.old_m_point_exchange(id))
        session.commit()
        return 'MPoint exchange deleted'

    @ajax
    def record_sale(self, session, badge_num=None, **params):
        params['reg_station'] = cherrypy.session.get('reg_station', 0)
        sale = session.sale(params)
        message = check(sale)
        if not message and badge_num is not None:
            try:
                sale.attendee = session.query(Attendee).filter_by(badge_num=badge_num).one()
            except Exception:
                message = 'No attendee has that badge number'

        if message:
            return {'success': False, 'message': message}
        else:
            session.add(sale)
            session.commit()
            message = '{sale.what} sold{to} for ${sale.cash}{mpoints}' \
                      .format(sale=sale,
                              to=(' to ' + sale.attendee.full_name) if sale.attendee else '',
                              mpoints=' and {} MPoints'.format(sale.mpoints) if sale.mpoints else '')
            return {'id': sale.id, 'success': True, 'message': message}

    @ajax
    def undo_sale(self, session, id):
        session.delete(session.sale(id))
        return 'Sale deleted'
