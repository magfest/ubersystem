import cherrypy
import re
from pockets import listify
from sqlalchemy import or_

from uber.config import c
from uber.decorators import ajax, all_renderable, credit_card, public, kiosk_login
from uber.errors import HTTPRedirect
from uber.models import ArbitraryCharge, Attendee, MerchDiscount, MerchPickup, \
    MPointsForCash, NoShirt, OldMPointExchange
from uber.utils import check, check_csrf
from uber.payments import TransactionRequest


def attendee_from_id_or_badge_num(session, badge_num_or_qr_code):
    attendee, id = None, None
    message = ''

    if not badge_num_or_qr_code:
        message = 'Please enter or scan a badge number or check-in QR code.'
    elif re.match('^[a-z0-9]{8}-[a-z0-9]{4}-[a-z0-9]{4}-[a-z0-9]{4}-[a-z0-9]{12}$', badge_num_or_qr_code):
        id = badge_num_or_qr_code
    elif badge_num_or_qr_code.startswith(c.EVENT_QR_ID):
        search_uuid = badge_num_or_qr_code[len(c.EVENT_QR_ID):]
        if re.match('^[a-z0-9]{8}-[a-z0-9]{4}-[a-z0-9]{4}-[a-z0-9]{4}-[a-z0-9]{12}$', search_uuid):
            id = badge_num_or_qr_code
    elif not badge_num_or_qr_code.isdigit():
        message = 'Invalid badge number.'

    if id:
        attendee = session.query(Attendee).filter(or_(Attendee.id == id, Attendee.public_id == id)).first()
        if not attendee:
            message = f"No attendee found with ID {id}."
    elif not message:
        attendee = session.query(Attendee).filter_by(badge_num=badge_num_or_qr_code).first()
        if not attendee:
            message = f'No attendee has badge number {badge_num_or_qr_code}.'
    
    if attendee:
        if not attendee.has_badge:
            message = f'{attendee.name_and_badge_info} has an invalid badge status: {attendee.badge_status_label}.'
        elif not attendee.checked_in and id:
            message = f'{attendee.name_and_badge_info} has not checked in!'

    return attendee, message


@all_renderable()
class Root:
    @kiosk_login()
    def index(self, session, message='', **params):
        if params.get('enter_kiosk'):
            supervisor = session.current_admin_account()
            if not supervisor:
                message = "Could not set kiosk mode. Please log in again or contact your developer."
            else:
                cherrypy.session['kiosk_supervisor_id'] = supervisor.id
                cherrypy.session.pop('account_id', None)
                cherrypy.session.pop('attendee_account_id', None)
        elif params.get('volunteer_logout'):
            cherrypy.session.pop('kiosk_operator_id', None)
        elif params.get('exit_kiosk'):
            cherrypy.session.pop('kiosk_supervisor_id', None)
            cherrypy.session.pop('kiosk_operator_id', None)
            raise HTTPRedirect('index?message={}', "Kiosk mode ended.")

        return {
            'message': message,
            'supervisor': session.current_supervisor_admin(),
            'logged_in_volunteer': cherrypy.session.get('kiosk_operator_id'),
        }

    @ajax
    def log_in_volunteer(self, session, message='', badge_num=''):
        attendee = None

        if not badge_num:
            message = "Please enter a badge number."
        elif not badge_num.isdigit():
            message = 'Invalid badge number.'
        else:
            attendee = session.query(Attendee).filter_by(badge_num=badge_num).first()
            if not attendee:
                message = f'No attendee has badge number {badge_num}.'
        
        if attendee:
            if not attendee.has_badge:
                message = f'This badge has an invalid status: {attendee.badge_status_label}.'
            elif not attendee.checked_in:
                message = 'This badge has not checked in!'

        if message:
            return {'success': False, 'message': message}

        cherrypy.session['kiosk_operator_id'] = attendee.id
        return {'success': True,
                'message': f"Logged in as {attendee.name_and_badge_info}!",
                'operator_name': attendee.full_name,
                }

    @public
    def arbitrary_charge_form(self, message='', amount=None, description='', email='', sale_id=None):
        charge = False
        if amount is not None:
            if not amount.isdigit() or not (1 <= int(amount) <= 999):
                message = 'Amount must be a dollar amount between $1 and $999'
            elif not description:
                message = "You must enter a brief description of what's being sold"
            else:
                charge = True

        return {
            'charge': charge,
            'message': message,
            'amount': amount,
            'email': email,
            'description': description,
            'sale_id': sale_id
        }

    @public
    @ajax
    def cancel_arbitrary_charge(self, session, stripe_id):
        # Arbitrary charges have no stripe ID yet and so can't actually be cancelled
        return {'message': 'Payment cancelled.'}

    @public
    @ajax
    @credit_card
    def arbitrary_charge(self, session, id, amount, description, email, return_to='arbitrary_charge_form'):
        charge = TransactionRequest(description=description, receipt_email=email, amount=100 * int(amount))
        message = charge.create_stripe_intent()
        if message:
            return {'error': message}
        else:
            session.add(ArbitraryCharge(
                amount=int(charge.dollar_amount),
                what=charge.description,
                reg_station=cherrypy.session.get('reg_station')
            ))
            return {'stripe_intent': charge.intent,
                    'success_url': '{}?message={}'.format(return_to, 'Charge successfully processed'),
                    'cancel_url': 'cancel_arbitrary_charge'}

    @kiosk_login()
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
                                    '{a.name_and_badge_info} already got their merch'.format(a=attendee))
                            else:
                                attendee.got_merch = True
                                shirt_key = 'shirt_{}'.format(attendee.badge_num)
                                if shirt_key in shirt_sizes:
                                    attendee.shirt = int(listify(shirt_sizes.get(shirt_key, c.SIZE_UNKNOWN))[0])
                                picked_up.append('{a.name_and_badge_info}: {a.merch}'.format(a=attendee))
                                session.add(MerchPickup(picked_up_by=picker_upper, picked_up_for=attendee))
                session.commit()

        return {
            'message': message,
            'picked_up': picked_up,
            'picker_upper': picker_upper
        }

    @ajax
    @kiosk_login()
    def check_merch(self, session, badge_num_or_qr_code, staff_merch=''):
        id = shirt = gets_swadge = None
        merch_items = []

        attendee, message = attendee_from_id_or_badge_num(session, badge_num_or_qr_code.strip())

        if not message:
            if staff_merch:
                merch = attendee.staff_merch
                got_merch = attendee.got_staff_merch
            else:
                merch, got_merch = attendee.merch, attendee.got_merch

            if staff_merch and c.STAFF_SHIRT_OPTS != c.SHIRT_OPTS:
                shirt_size = c.STAFF_SHIRTS[attendee.staff_shirt]
            else:
                shirt_size = c.SHIRTS[attendee.shirt]

            if not merch or merch == 'N/A':
                message = f'{attendee.name_and_badge_info} does not have any merch!'
            elif got_merch:
                if not (not staff_merch and attendee.gets_swadge and not attendee.got_swadge):
                    message = f'{attendee.name_and_badge_info} already got {merch}. Their shirt size is {shirt_size}.'
                else:
                    id = attendee.id
                    gets_swadge = True
                    shirt = c.NO_SHIRT
                    message = f'{attendee.name_and_badge_info} has received all of their merch except for their swadge. ' \
                        'Click the "Give Merch" button below to mark them as receiving it.'
            else:
                id = attendee.id

                if staff_merch:
                    merch_items = attendee.staff_merch_items
                else:
                    merch_items = attendee.merch_items
                    gets_swadge = attendee.gets_swadge

                if (staff_merch and attendee.num_staff_shirts_owed) or \
                        (not staff_merch and attendee.num_event_shirts_owed):
                    if staff_merch and c.STAFF_SHIRT_OPTS != c.SHIRT_OPTS:
                        shirt = attendee.staff_shirt or c.SIZE_UNKNOWN
                    else:
                        shirt = attendee.shirt or c.SIZE_UNKNOWN
                else:
                    shirt = c.NO_SHIRT

                message = f'{attendee.name_and_badge_info} has not yet received their merch.'
                if attendee.amount_unpaid and not staff_merch:
                    merch_items.insert(0,
                                        'WARNING: Attendee is not fully paid up and may not have paid for their '
                                        'merch. Please contact Registration.')

        return {
            'id': id,
            'shirt': shirt,
            'message': message,
            'display_name': '' if not attendee else attendee.name_and_badge_info,
            'merch_items': merch_items,
            'gets_swadge': gets_swadge,
        }

    @ajax
    @kiosk_login()
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
            message = '{} has no merch.'.format(attendee.name_and_badge_info)
        elif got and give_swadge and not attendee.got_swadge:
            message = '{a.name_and_badge_info} marked as receiving their swadge.'.format(
                a=attendee)
            success = True
            attendee.got_swadge = True
            session.commit()
        elif got:
            message = '{} already got {}.'.format(attendee.name_and_badge_info, merch)
        elif shirt_size in [c.NO_SHIRT, c.SIZE_UNKNOWN]:
            message = 'You must select a shirt size.'
        else:
            if no_shirt:
                message = '{} is now marked as having received all of the following (EXCEPT FOR THE SHIRT): {}.'
            else:
                message = '{} is now marked as having received {}.'
            message = message.format(attendee.name_and_badge_info, merch)
            setattr(attendee,
                    'got_staff_merch' if staff_merch else 'got_merch', True)
            if give_swadge:
                attendee.got_swadge = True
            if shirt_size:
                if staff_merch and c.STAFF_SHIRT_OPTS != c.SHIRT_OPTS:
                    attendee.staff_shirt = shirt_size
                else:
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
    @kiosk_login()
    def take_back_merch(self, session, id, staff_merch=None):
        attendee = session.attendee(id, allow_invalid=True)
        if staff_merch:
            attendee.got_staff_merch = False
        else:
            attendee.got_merch = attendee.got_swadge = False
        if attendee.no_shirt:
            session.delete(attendee.no_shirt)
        session.commit()
        return '{a.name_and_badge_info} merch handout cancelled.'.format(a=attendee)

    @ajax
    @kiosk_login()
    def redeem_merch_discount(self, session, badge_num_or_qr_code, apply=''):
        attendee, message = attendee_from_id_or_badge_num(session, badge_num_or_qr_code)
        if message:
            return {'error': message}

        if attendee.badge_type != c.STAFF_BADGE:
            return {'error': 'Only staff badges are eligible for discount.'}

        discount = session.query(MerchDiscount).filter_by(attendee_id=attendee.id).first()
        if not apply:
            if discount:
                return {
                    'warning': True,
                    'message': 'This staffer has already redeemed their discount {} time{}.'.format(
                        discount.uses, 's' if discount.uses > 1 else '')
                }
            else:
                return {'message': 'Tell staffer their discount is only usable one time '
                                   'and confirm that they want to redeem it.'}

        discount = discount or MerchDiscount(attendee_id=attendee.id, uses=0)
        discount.uses += 1
        session.add(discount)
        session.commit()
        return {'success': True, 'message': 'Discount for {} has been marked as redeemed.'.format(attendee.name_and_badge_info)}

    @ajax
    @kiosk_login()
    def record_mpoint_cashout(self, session, badge_num_or_qr_code, amount):
        attendee, message = attendee_from_id_or_badge_num(session, badge_num_or_qr_code)
        if message:
            return {'success': False, 'message': message}

        mfc = MPointsForCash(attendee=attendee, amount=amount)
        message = check(mfc)
        if message:
            return {'success': False, 'message': message}
        else:
            session.add(mfc)
            session.commit()
            message = '{mfc.attendee.name_and_badge_info} exchanged {mfc.amount} MPoints for cash.'.format(mfc=mfc)
            return {'id': mfc.id, 'success': True, 'message': message}

    @ajax
    @kiosk_login()
    def undo_mpoint_cashout(self, session, id):
        session.delete(session.mpoints_for_cash(id))
        return 'MPoint usage deleted'

    @ajax
    @kiosk_login()
    def record_old_mpoint_exchange(self, session, badge_num_or_qr_code, amount):
        attendee, message = attendee_from_id_or_badge_num(session, badge_num_or_qr_code)
        if message:
            return {'success': False, 'message': message}

        ome = OldMPointExchange(attendee=attendee, amount=amount)
        message = check(ome)
        if message:
            return {'success': False, 'message': message}
        else:
            session.add(ome)
            session.commit()
            message = "{ome.attendee.name_and_badge_info} marked as having exchanged {ome.amount} of last year's MPoints.".format(ome=ome)
            return {'id': ome.id, 'success': True, 'message': message}

    @ajax
    def undo_mpoint_exchange(self, session, id):
        session.delete(session.old_m_point_exchange(id))
        session.commit()
        return 'MPoint exchange deleted'

    @ajax
    @kiosk_login()
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
                              to=(' to ' + sale.attendee.name_and_badge_info) if sale.attendee else '',
                              mpoints=' and {} MPoints.'.format(sale.mpoints) if sale.mpoints else '')
            return {'id': sale.id, 'success': True, 'message': message}

    @ajax
    @kiosk_login()
    def undo_sale(self, session, id):
        session.delete(session.sale(id))
        return 'Sale deleted'
