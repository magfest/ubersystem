import cherrypy
import math

from datetime import datetime

from uber.config import c
from uber.custom_tags import time_day_local
from uber.decorators import ajax, ajax_gettable, all_renderable, not_site_mappable
from uber.errors import HTTPRedirect
from uber.models import Attendee, PrintJob
from uber.utils import localized_now


@all_renderable()
class Root:
    def index(self, session, page='1', message='', pending=''):
        base_query = session.query(Attendee).join(Attendee.print_requests)

        if pending:
            badges = base_query.filter(PrintJob.printed == None, PrintJob.errors == '').order_by(PrintJob.queued.desc()).all()
        else:
            badges = base_query.filter(PrintJob.printed != None).order_by(PrintJob.printed.desc()).all()

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

    def print_next_badge(self, session, printer_id=''):
        badge = session.get_next_badge_to_print(printer_id=printer_id)
        if not badge:
            raise HTTPRedirect('badge_waiting?printer_id={}'.format(printer_id))

        attendee = badge.attendee

        badge_type = attendee.badge_type_label

        # Allows events to add custom print overrides
        try:
            badge_type += attendee.extra_print_label
        except Exception:
            pass

        ribbon = ' / '.join(attendee.ribbon_labels) if attendee.ribbon else ''

        badge.queued = datetime.utcnow()
        badge.printed = datetime.utcnow()
        session.add(attendee)
        session.commit()

        return {
            'badge_type': badge_type,
            'ribbon': ribbon,
            'badge_num': attendee.badge_num,
            'badge_name': attendee.badge_printed_name,
            'badge': True,
            'printer_id': printer_id,
        }

    def badge_waiting(self, message='', printer_id=''):
        return {
            'message': message,
            'printer_id': printer_id,
        }

    def attendee_print_jobs(self, session, id):
        attendee = session.attendee(id)

        return {
            'attendee': attendee,
            'jobs': attendee.print_requests,
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

        raise HTTPRedirect('../registration/form?id={}&message={}',
                           attendee_id, message)

    def print_jobs_list(self, session):
        return {}

    @not_site_mappable
    def print_jobs(self, session, flag):
        from uber.models import Tracking

        filters = [Tracking.action == c.CREATED]
        if flag == 'pending':
            filters = [PrintJob.queued == None, PrintJob.printed == None]
        elif flag == 'not_printed':
            filters = [PrintJob.queued != None, PrintJob.printed == None]
        elif flag == 'errors':
            filters = [PrintJob.errors != '']
        elif flag == 'created':
            filters = [PrintJob.admin_id == cherrypy.session.get('account_id')]
        elif flag == 'printed':
            filters = [PrintJob.printed != None]

        jobs = session.query(PrintJob).join(Tracking, PrintJob.id == Tracking.fk_id).filter(
                 *filters).order_by(Tracking.when.desc()).limit(c.ROW_LOAD_LIMIT).all()

        return {
            'jobs': jobs,
        }

    @ajax
    def add_job_to_queue(self, session, id, printer_id='', **params):
        attendee = session.attendee(id)
        fee_amount = params.get('fee_amount', 0)
        reprint_reason = params.get('reprint_reason')

        try:
            fee_amount = int(fee_amount)
        except Exception:
            return {'success': False, 'message': "What you entered for Reprint Fee ({}) isn't even a number".format(fee_amount)}
        
        if not fee_amount and not reprint_reason and c.BADGE_REPRINT_FEE:
            return {'success': False, 'message': "You must set a fee or enter a reason for a free reprint!"}
        
        print_id, errors = session.add_to_print_queue(attendee, printer_id, params.get('reg_station'), fee_amount)
        if errors:
            return {'success': False, 'message': "<br>".join(errors)}

        if not fee_amount:
            if c.BADGE_REPRINT_FEE:
                attendee.for_review += \
                    "Automated message: " \
                    "Badge marked for free reprint by {} on {}.{}"\
                    .format(session.admin_attendee().full_name,
                            localized_now().strftime('%m/%d, %H:%M'),
                            " Reason: " + reprint_reason if reprint_reason else '')
            message = '{}adge sent to printer.'.format("B" if not c.BADGE_REPRINT_FEE else "Free reprint recorded and b")
        else:
            message = 'Badge sent to printer with reprint fee of ${}.'.format(fee_amount)

        session.add(attendee)
        session.commit()

        return {'success': True, 'message': message}

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