import cherrypy
import math

from datetime import datetime

from uber.config import c
from uber.custom_tags import time_day_local
from uber.decorators import ajax, ajax_gettable, all_renderable
from uber.errors import HTTPRedirect
from uber.models import Attendee, PrintJob
from uber.utils import localized_now


@all_renderable()
class Root:
    def index(self, session, page='1', message='', id=None, pending='',
              reprint_reason=''):
        if id:
            attendee = session.attendee(id)
            attendee.badge_status = c.COMPLETED_STATUS
            attendee.for_review += \
                "Automated message: " \
                "Badge marked for free reprint by {} on {}. Reason: {}"\
                .format(session.admin_attendee().full_name, localized_now()
                        .strftime('%m/%d, %H:%M'), reprint_reason)
            session.add(attendee)
            session.commit()
            message = "Badge marked for re-print!"

        if pending:
            badges = session.query(Attendee)\
                .filter(Attendee.print_pending)\
                .filter(Attendee.badge_status == c.COMPLETED_STATUS)\
                .order_by(Attendee.badge_num).all()
        else:
            badges = session.query(Attendee)\
                .filter(not Attendee.print_pending)\
                .order_by(Attendee.badge_num).all()

        page = int(page)
        count = len(badges)
        pages = range(1, int(math.ceil(count / 100)) + 1)
        badges = badges[-100 + 100*page: 100*page] if page else []

        return {
            'page':     page,
            'pages':    pages,
            'message':  message,
            'badges':   badges,
            'pending':  pending
        }

    def print_next_badge(self, session, minor='', printerNumber='', numberOfPrinters=''):
        attendee = session.get_next_badge_to_print(minor=minor, printerNumber=printerNumber, numberOfPrinters=numberOfPrinters)
        if not attendee:
            raise HTTPRedirect('badge_waiting?minor={}&printerNumber={}&numberOfPrinters={}'.format(minor, printerNumber, numberOfPrinters))

        badge_type = attendee.badge_type_label

        # Allows events to add custom print overrides
        try:
            badge_type += attendee.extra_print_label
        except Exception:
            pass

        ribbon = ' / '.join(attendee.ribbon_labels) if attendee.ribbon else ''

        attendee.times_printed += 1
        attendee.print_pending = False
        session.add(attendee)
        session.commit()

        return {
            'badge_type': badge_type,
            'ribbon': ribbon,
            'badge_num': attendee.badge_num,
            'badge_name': attendee.badge_printed_name,
            'badge': True,
            'minor': minor,
            'printerNumber': printerNumber,
            'numberOfPrinters': numberOfPrinters
        }

    def badge_waiting(self, message='', minor='', printerNumber='', numberOfPrinters=''):
        return {
            'message': message,
            'minor': minor,
            'printerNumber': printerNumber,
            'numberOfPrinters': numberOfPrinters
        }

    def reprint_fee(self, session, attendee_id=None, message='',
                    fee_amount=0, reprint_reason='', refund=''):
        attendee = session.attendee(attendee_id)
        fee_amount = int(fee_amount)
        if not fee_amount and not reprint_reason:
            message = "You must charge a fee " \
                      "or enter a reason for a free reprint!"
        if not fee_amount and refund:
            message = "You can't refund a fee of $0!"

        if not message:
            if not fee_amount:
                attendee.for_review += \
                    "Automated message: " \
                    "Badge marked for free reprint by {} on {}.{}"\
                    .format(session.admin_attendee().full_name,
                            localized_now().strftime('%m/%d, %H:%M'),
                            " Reason: " + reprint_reason if reprint_reason else '')
                message = 'Free reprint recorded and badge sent to printer.'
                attendee.print_pending = True
            elif refund:
                attendee.paid = c.REFUNDED
                session.add(session.create_receipt_item(attendee, 
                    fee_amount * 100,
                    "Badge reprint fee refund",
                    txn_type=c.REFUND,
                    payment_method=c.CASH))
                attendee.for_review += \
                    "Automated message: " \
                    "Reprint fee of ${} refunded by {} on {}.{}"\
                    .format(fee_amount,
                            session.admin_attendee().full_name,
                            localized_now().strftime('%m/%d, %H:%M'),
                            " Reason: " + reprint_reason if reprint_reason else '')
                message = 'Reprint fee of ${} refunded.'.format(fee_amount)
            else:
                session.add(session.create_receipt_item(
                    attendee, 
                    fee_amount * 100, 
                    "Badge reprint fee", 
                    txn_type=c.PAYMENT, 
                    payment_method=c.CASH))
                attendee.for_review += \
                    "Automated message: " \
                    "Reprint fee of ${} charged by {} on {}.{}"\
                    .format(fee_amount,
                            session.admin_attendee().full_name,
                            localized_now().strftime('%m/%d, %H:%M'),
                            " Reason: " + reprint_reason if reprint_reason else '')
                message = 'Reprint fee of ${} charged. Badge sent to printer.'\
                    .format(fee_amount)
                attendee.print_pending = True

        raise HTTPRedirect('../registration/form?id={}&message={}',
                           attendee_id, message)

    def queued_badges(self, session):
        return {
            'badges': session.query(PrintJob).all(),
        }

    @ajax
    def add_job_to_queue(self, session, id, printer_id=0):
        print_id, errors = session.add_to_print_queue(session.attendee(id), printer_id, cherrypy.session.get('reg_station'))
        if errors:
            return {'success': False, 'message': "<br>".join(errors)}

        return {'success': True, 'message': 'Print job created!'}

    @ajax_gettable
    def mark_as_unsent(self, session, id):
        job = session.print_job(id)
        if not job.queued:
            success = False
            message = "Job hasn't yet been sent to printer."
        else:
            success = True
            message = "Job marked as unsent to printer."
            job.queued = None
            session.add(job)
            session.commit()
        
        return {
            'success': success,
            'message': message,
            'id': job.id,
            'queued': "No"
        }

    @ajax_gettable
    def mark_as_printed(self, session, id):
        job = session.print_job(id)
        if job.printed:
            success = False
            message = "Job already marked as printed."
        else:
            success = True
            message = "Job marked as printed."
            job.printed = datetime.utcnow()
            session.add(job)
            session.commit()
        
        return {
            'success': success,
            'message': message,
            'id': job.id,
            'printed': time_day_local(job.printed)
        }
    
    @ajax_gettable
    def mark_as_invalid(self, session, id):
        job = session.print_job(id)
        if job.errors:
            success = False
            message = "Job is already invalid."
        else:
            success = True
            message = "Job marked as invalid."
            job.errors = "Marked invalid by {}".format(session.admin_attendee().full_name)
            session.add(job)
            session.commit()
        
        return {
            'success': success,
            'message': message,
            'id': job.id,
            'errors': job.errors
        }