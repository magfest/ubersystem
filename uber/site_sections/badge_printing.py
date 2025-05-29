import cherrypy
import math

from datetime import datetime

from uber.config import c
from uber.custom_tags import time_day_local
from uber.decorators import ajax, ajax_gettable, all_renderable, not_site_mappable
from uber.errors import HTTPRedirect
from uber.models import AdminAccount, Attendee, PrintJob, ReceiptItem
from uber.utils import localized_now


def pre_print_check(session, attendee, printer_id, dry_run=False, **params):
    fee_amount = params.get('fee_amount', 0)
    free_reprint = params.get('free_reprint')
    reprint_reason = params.get('reprint_reason')

    if c.BADGE_REPRINT_FEE and attendee.times_printed > 0:
        if not fee_amount:
            return None, "This attendee has already had their badge printed."
        elif free_reprint and not reprint_reason:
            return None, "Please enter a reason for running a free badge reprint."
    
    fee_amount = 0 if free_reprint else fee_amount

    print_id, errors = session.add_to_print_queue(attendee,
                                                  printer_id,
                                                  params.get('reg_station', cherrypy.session.get('reg_station')),
                                                  fee_amount,
                                                  dry_run)
    if errors:
        return None, "<br>".join(errors)

    if not fee_amount:
        if c.BADGE_REPRINT_FEE and attendee.times_printed > 0:
            attendee.for_review += \
                "Automated message: " \
                "Badge marked for free reprint by {} on {}.{}"\
                .format(session.admin_attendee().full_name,
                        localized_now().strftime('%m/%d, %H:%M'),
                        " Reason: " + reprint_reason if reprint_reason else '')
            return print_id, '{}adge sent to printer.'.format("B" if not c.BADGE_REPRINT_FEE or attendee.times_printed == 0
                                                          else "Free reprint recorded and b")
    else:
        return print_id, 'To print this badge, please complete payment for the reprint fee of ${}.'.format(fee_amount)
    return print_id, 'Badge sent to printer.'


@all_renderable()
class Root:
    def index(self, session, page='1', message='', pending=''):
        base_query = session.query(Attendee).join(Attendee.print_requests)

        if pending:
            badges = base_query.filter(PrintJob.printed == None, PrintJob.ready == True,  # noqa: E711
                                       PrintJob.errors == '').order_by(PrintJob.queued.desc()).all()
        else:
            badges = base_query.filter(PrintJob.printed != None).order_by(PrintJob.printed.desc()).all()  # noqa: E711

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

    def print_jobs_list(self, session):
        return {}

    @not_site_mappable
    def print_jobs(self, session, flag):
        filters = []
        if flag == 'pending':
            filters += [PrintJob.queued == None, PrintJob.printed == None, PrintJob.errors == '']  # noqa: E711
        elif flag == 'not_printed':
            filters += [PrintJob.queued != None, PrintJob.printed == None, PrintJob.errors == '']  # noqa: E711
        elif flag == 'errors':
            filters += [PrintJob.errors != '']
        elif flag == 'created':
            filters += [PrintJob.admin_id == cherrypy.session.get('account_id')]
        elif flag == 'printed':
            filters += [PrintJob.printed != None]  # noqa: E711

        jobs = session.query(PrintJob).filter(*filters).order_by(PrintJob.created.desc()).all()

        return {
            'jobs': jobs,
            'flag': flag,
        }

    @ajax
    def add_job_to_queue(self, session, id, printer_id='', **params):
        attendee = session.attendee(id)
        reprint_fee = 0 if params.get('free_reprint') else int(params.get('fee_amount', 0))
        new_name = params.get('badge_printed_name', '')

        if new_name and new_name != attendee.badge_printed_name:
            attendee.badge_printed_name = new_name
            session.commit()
            session.refresh(attendee)

        print_id, message = pre_print_check(session, attendee, printer_id, dry_run=False, **params)

        if print_id:
            if reprint_fee:
                receipt = session.get_receipt_by_model(attendee, create_if_none="DEFAULT")
                session.add(ReceiptItem(purchaser_id=attendee.id,
                                        receipt_id=receipt.id,
                                        department=c.REG_RECEIPT_ITEM,
                                        category=c.BADGE_REPRINT,
                                        desc="Badge reprint fee (${})".format(reprint_fee),
                                        amount=reprint_fee * 100,
                                        fk_id=print_id,
                                        fk_model="PrintJob",
                                        count=1,
                                        who=AdminAccount.admin_name() or 'non-admin',
                                        )
                            )

            session.add(attendee)
            session.commit()

        return {'success': True if print_id else False, 'message': message}

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
            if job.print_fee and job.attendee:
                receipt = session.get_receipt_by_model(job.attendee)
                if receipt:
                    session.add(ReceiptItem(receipt_id=receipt.id,
                                            department=c.REG_RECEIPT_ITEM,
                                            category=c.BADGE_REPRINT,
                                            desc="Badge reprint cancelled (${})".format(job.print_fee),
                                            amount=job.print_fee * 100 * -1,
                                            count=1,
                                            who=AdminAccount.admin_name() or 'non-admin',
                                            )
                                )
            session.add(job)
            session.commit()

        return {
            'success': success,
            'message': message,
            'id': job.id,
            'errors': job.errors
        }
