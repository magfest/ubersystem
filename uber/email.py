import contextlib
import json
import logging
import pytz

from collections import defaultdict
from datetime import datetime
from sqlalchemy.orm import joinedload
from sqlalchemy import update, or_

from uber.amazon_ses import email_sender
from uber.automated_emails import AutomatedEmailFixture
from uber.config import c
from uber.custom_tags import email_only, readable_join
from uber.models import AutomatedEmail, Email
from uber.utils import listify, localized_now

log = logging.getLogger(__name__)


class EmailHandler:
    def __init__(self, fixture_obj=None, to_model=None, email_obj=None, **kwargs):
        if not AutomatedEmail.initialized:
            AutomatedEmail.reconcile_fixtures()
            AutomatedEmail.initialized = True

        if email_obj:
            self.email_obj = email_obj
        else:
            self.email_obj = self.create_email_obj(fixture_obj, to_model, **kwargs)

        self.fixture_obj = fixture_obj or email_obj.automated_email
        self.to_model = to_model

    def create_email_obj(self, fixture_obj=None, to_model=None, **kwargs):
        """
        Creates an email with properties based on any passed arguments, falling back to the email's fixture if there is one.
        We don't generate the subject or cc, bcc, or replyto based on the model as that's done at send time.
        """
        email_obj = Email(status=c.QUEUED)

        for attr in ['to', 'cc', 'bcc', 'replyto', 'sender', 'subject', 'body', 'shared_ident']:
            setattr(email_obj, attr, kwargs.get(attr, getattr(email_obj, attr, '')))

        render_data = kwargs.get('data', {})
        for key, val in render_data.items():
            try:
                json.dumps(val)
            except TypeError:
                render_data[key] = val.to_dict()

        email_obj.render_data = render_data or email_obj.render_data
        email_obj.fk_id = to_model.id if to_model else None
        email_obj.model = to_model.__class__.__name__ if to_model else ''

        if fixture_obj:
            email_obj.cc = email_obj.cc or fixture_obj.cc
            email_obj.bcc = email_obj.bcc or fixture_obj.bcc
            email_obj.replyto = email_obj.replyto or fixture_obj.replyto
            email_obj.sender = email_obj.sender or fixture_obj.sender
            email_obj.subject = email_obj.subject or fixture_obj.subject
            email_obj.shared_ident = email_obj.shared_ident or fixture_obj.shared_ident
        
        if to_model:
            # We want queued emails to have a 'to' address so admins can see + search by it
            # The 'to' address will always be re-generated on send and cannot be overridden with a custom value
            email_obj.to = to_model.email_to_address

        if fixture_obj and to_model:
            email_obj.body = email_obj.body or fixture_obj.render_body(to_model, email_obj.render_data)

        email_obj.sender = email_obj.sender or c.CONTACT_EMAIL
        email_obj.ident = kwargs.get('ident', '')
        email_obj.automated_email = fixture_obj

        email_obj.to, email_obj.cc, email_obj.bcc, email_obj.replyto = map(lambda x: ','.join(listify(x if x else [])),
                                                                           [email_obj.to, email_obj.cc, email_obj.bcc, email_obj.replyto])
        
        return email_obj

    def can_queue_email(self, session, limit_one=False, delete_existing=False):
        # Checks if we're allowed to queue our email object
        # This is not used for large operations as there are better ways to do these checks en masse

        if not self.fixture_obj:
            return True
        
        if self.fixture_obj.policy == c.DISABLED:
            return

        if self.to_model and (limit_one or delete_existing):
            if self.email_obj.shared_ident:
                ident_filter = or_(Email.ident == self.email_obj.ident, Email.shared_ident == self.email_obj.shared_ident)
            else:
                ident_filter = Email.ident == self.email_obj.ident
            other_emails = session.query(Email).filter(ident_filter,
                                                       Email.fk_id == self.email_obj.fk_id,
                                                       Email.model == self.email_obj.model)
            if limit_one and other_emails.filter(Email.status == c.SENT).count():
                return
            
            if delete_existing:
                for email in other_emails.filter(Email.status != c.SENT):
                    session.delete(email)

        return True
    
    def queue_email_obj(self, session):
        if not self.fixture_obj:
            self.email_obj.send_after = self.email_obj.new_send_after
            session.add(self.email_obj)
            return
        
        if not self.fixture_obj.policy or self.fixture_obj.policy == c.NEEDS_APPROVAL:
            self.email_obj.status = c.UNAPPROVED
        else:
            self.email_obj.send_after = self.email_obj.new_send_after
        
        session.add(self.email_obj)


class EmailService:
    @staticmethod
    def check_emails_for_fixture(session, fixture_obj):
        if not fixture_obj.fixture or not fixture_obj.fixture.filter or not fixture_obj.can_generate:
            return

        model_class = fixture_obj.model_class
        if fixture_obj.shared_ident:
            ident_filter = or_(Email.ident == fixture_obj.ident, Email.shared_ident == fixture_obj.shared_ident)
        else:
            ident_filter = Email.ident == fixture_obj.ident

        existing_fk_ids = [id for id, in session.query(Email.fk_id).filter(ident_filter)]

        to_models = session.query(model_class).filter(~model_class.id.in_(existing_fk_ids))
        if AutomatedEmailFixture.queries.get(model_class):
            to_models = to_models.options(*AutomatedEmailFixture.queries[model_class])

        model_count = 0
        for to_model in to_models:
            if fixture_obj.fixture.filter(to_model):
                model_count += 1

                email_handler = EmailHandler(fixture_obj, to_model, ident=fixture_obj.ident)
                email_handler.queue_email_obj(session)

        session.commit()
        return model_count

    @staticmethod
    def check_emails_for_model(session, to_model):
        if to_model.__class__ not in set([fixture.model for fixture in AutomatedEmail._fixtures.values()]):
            return
        
        if not AutomatedEmail.initialized:
            AutomatedEmail.reconcile_fixtures()
            AutomatedEmail.initialized = True

        model_str = to_model.__class__.__name__
        active_automated_emails = session.query(AutomatedEmail).filter(
            AutomatedEmail.model == model_str).filter(*AutomatedEmail.filters_for_allowed).all()
        active_idents = []
        active_shared_idents = set()
        for email in active_automated_emails:
            active_idents.append(email.ident)
            if email.shared_ident:
                active_shared_idents.add(email.shared_ident)

        existing_emails = session.query(Email).filter(Email.model == model_str,
                                                      Email.fk_id == to_model.id,
                                                      or_(Email.ident.in_(active_idents),
                                                          Email.shared_ident.in_(active_shared_idents)))
        existing_by_ident = defaultdict(list)
        existing_by_shared_ident = defaultdict(list)
        for email in existing_emails:
            existing_by_ident[email.ident].append(email)
            if email.shared_ident:
                existing_by_shared_ident[email.shared_ident].append(email)

        for fixture_obj in active_automated_emails:
            fixture = AutomatedEmail._fixtures[fixture_obj.ident]
            if fixture and fixture.filter:
                existing = existing_by_ident.get(fixture_obj.ident)
                if fixture_obj.shared_ident:
                    existing = existing_by_shared_ident.get(fixture_obj.shared_ident) or existing

                if not existing and fixture.filter(to_model):
                    email_handler = EmailHandler(fixture_obj, to_model, ident=fixture_obj.ident)
                    email_handler.queue_email_obj(session)
                elif existing and not fixture.filter(to_model):
                    for email in existing:
                        if email.status != c.SENT:
                            session.delete(email)

    @staticmethod
    def process_emails_by_class(session, model_class):
        model_str = model_class.__name__ if model_class else ''

        queued_emails = session.query(Email).filter(
            Email.status == c.QUEUED, Email.model == model_str,
            Email.send_after != None, Email.send_after < datetime.now(pytz.UTC)
            ).options(joinedload(Email.automated_email)).limit(5000)

        if not queued_emails.count():
            return 0

        if model_class:
            log.debug(f"Found {queued_emails.count()} queued emails for {model_str}.")
            
            fk_ids = set()
            for email in queued_emails:
                fk_ids.add(email.fk_id)
            fk_ids.discard(None)
            
            to_models = session.query(model_class).filter(model_class.id.in_(fk_ids))
            if AutomatedEmailFixture.queries.get(model_class):
                to_models = to_models.options(AutomatedEmailFixture.queries[model_class])
            models_by_id = {model.id: model for model in to_models}
        else:
            log.debug(f"Found {queued_emails.count()} classless queued emails.")
            models_by_id = {}

        sent_count = 0
        for email in queued_emails:
            sent_email = EmailService.send_email(session, email, email.automated_email, models_by_id.get(email.fk_id, None))
            if sent_email:
                session.add(sent_email)
                sent_count += 1
        session.commit()
        return sent_count
    
    @staticmethod
    def reconcile_policy(session, fixture_obj):
        emails = session.query(Email).filter(Email.automated_email_id == fixture_obj.id)
        if not fixture_obj.can_generate:
            emails = emails.filter(Email.status != c.SENT)
            new_status = None
        elif fixture_obj.policy == c.AUTOSEND:
            emails = emails.filter(Email.status == c.UNAPPROVED)
            new_status = c.QUEUED
        else:
            emails = emails.filter(Email.status == c.QUEUED)
            new_status = c.UNAPPROVED

        email_update_list = []
        for email in emails:
            if new_status is None:
                session.delete(email)
            else:
                update_dict = {'id': email.id, 'status': new_status}
                if new_status == c.QUEUED:
                    new_send_after = email.new_send_after
                    if new_send_after and new_send_after != email.send_after:
                        update_dict['send_after'] = new_send_after
                else:
                    update_dict['send_after'] = None
                email_update_list.append({'id': email.id, 'status': new_status})
        if email_update_list:
            session.execute(update(Email), email_update_list)
            session.commit()

    @staticmethod
    def send_email(session, email, fixture_obj=None, to_model=None):
        fixture_obj = fixture_obj or email.automated_email
        if not to_model and email.fk_id:
            model_class = email.model_class
            to_model = session.query(model_class).filter(model_class.id == email.fk_id).first()
        
        # Check that the object associated with this email still exists and is still eligible for emails
        if email.fk_id:
            if not to_model:
                email.error = f"Could not find a {email.model} model with ID {email.fk_id}."
                return
            if not to_model.email_to_address:
                email.error = f"Model {to_model} does not have an email address."
                return
            if not to_model.gets_emails:
                session.delete(email)
                return

        if fixture_obj and not fixture_obj.fixture:
            email.error = f"Fixture {email.ident} is no longer defined and cannot be sent."
            return
            
        #email_handler = EmailHandler(fixture_obj, to_model, email)
        # TODO: Move this code into EmailHandler
        fixture = fixture_obj.fixture if fixture_obj else None

        if to_model:
            def listify_if_exists(x): return ','.join(listify(x if x else []))
            email.to = listify_if_exists(to_model.email_to_address)
            email.cc = email.cc or listify_if_exists(to_model.cc_emails_for_ident(email.ident))
            email.bcc = email.bcc or listify_if_exists(to_model.bcc_emails_for_ident(email.ident))
            email.replyto = email.replyto or listify_if_exists(to_model.replyto_emails_for_ident(email.ident))

        if fixture and to_model:
            # Re-check the email filter to make sure this object still qualifies for this email,
            # then check if we can actually send it yet
            if fixture.filter is not None and not fixture.filter(to_model):
                session.delete(email)
                return

            if fixture.send_filter is not None and not fixture.send_filter(to_model):
                return
        
        if fixture_obj:
            with contextlib.suppress(Exception):
                # Generate body if possible, then check against stored body. If it's different, save the new body and requeue it
                render_data = fixture_obj.renderable_data(to_model, email.render_data)

                email.subject = (email.subject or fixture_obj.subject).format(render_data)
                current_body = fixture_obj.render_template(fixture_obj.body, render_data)
                if current_body != email.body:
                    email.body = current_body
                    email.generated = datetime.now(pytz.UTC)
                    return

        missing = []
        if not email.subject:
            missing.append('subject')
        if not email.body:
            missing.append('body')
        if not email.to:
            missing.append('to address')
        if not email.sender:
            missing.append('from address')

        if missing:
            email.error = f"Email {email.id} cannot be sent: missing {readable_join(missing)}."
            return
        
        try:
            error_msg = ''
            if not c.DEV_BOX and c.SEND_EMAILS:
                ses_payload = {
                    'bodyText' if email.format == 'text' else 'bodyHtml': email.body,
                    'subject': email.subject,
                    'charset': 'UTF-8',
                }
                error_msg = email_sender.sendEmail(
                    source=email.sender,
                    toAddresses=email.to.split(','),
                    replyToAddresses=email.replyto.split(',') if email.replyto else [],
                    ccAddresses=email.cc.split(',') if email.cc else [],
                    bccAddresses=email.bcc.split(',') if email.bcc else [],
                    message=ses_payload)

            if error_msg:
                email.error = f"Error while sending email: {str(error_msg)}."
            else:
                email.status = c.SENT
                email.sent = datetime.now(pytz.UTC)
                return email
        except Exception as error:
            email.error = f"Error while sending email: {str(error)}."


    @staticmethod
    def queue_email(session, ident='', to_model=None, to='', data={}, limit_one=False, replace_unsent=False, **kwargs):
        """
        Queues a single email, either by ident/fixture or with a custom subject and body passed.
        This would emit a lot of roundtrip DB calls for large operations, so functions like
        `check_emails_for_fixture` and `check_emails_for_model` reimplement this logic using database filters.
        """
        if not AutomatedEmail.initialized:
            AutomatedEmail.reconcile_fixtures()
            AutomatedEmail.initialized = True

        if not to_model and not to:
            log.error(f"Misconfigured email '{ident}': no recipient specified.")
            return
        
        if to_model and to:
            log.error(f"Misconfigured email '{ident}': emails cannot have both a to_model and a custom to address.")

        if ident:
            fixture_obj = session.query(AutomatedEmail).filter(AutomatedEmail.ident == ident).first()
            if not fixture_obj and (not kwargs.get('subject') or not kwargs.get('body')):
                log.error(f"Tried to look up email by ident '{ident}', but it doesn't exist.")
                return
        
        if not fixture_obj or not to_model:
            if limit_one:
                log.error(f"Misconfigured email '{ident}': emails cannot have limit_one set without both a valid fixture and a to_model.")
                return
            if replace_unsent:
                log.error(f"Misconfigured email '{ident}': emails cannot have replace_unset set without both a valid fixture and a to_model.")
                return

        email_handler = EmailHandler(fixture_obj, to_model, ident=ident, to=to, data=data, **kwargs)
        if not email_handler.can_queue_email(session, limit_one, delete_existing=replace_unsent):
            return

        email_handler.queue_email_obj(session)

    def emails_from_depts(session, dept_ids):
        """
        Takes a list of department IDs and returns a dictionary with email addresses as keys and Department objects as values.
        This lets us both filter emails by department and display which departments are associated with a particular email address.
        """
        from uber.models import Department

        depts_by_sender = defaultdict(set)
        departments = session.query(Department).filter(Department.from_email != '')
        if dept_ids:
            departments = departments.filter(Department.id.in_(dept_ids))

        for dept in departments:
            from_email = dept.from_email
            related_emails = c.RELATED_EMAILS.get(from_email, [])
            for email in [from_email] + related_emails:
                depts_by_sender[email].add(dept)
            
        return depts_by_sender
    
    def depts_from_email(session, email_sender):
        from uber.models import Department
        email_sender = email_only(email_sender)

        related_emails = c.RELATED_EMAILS.get(email_sender, [])
        department_ids = session.query(Department.id, Department.name).filter(Department.from_email.in_(related_emails + [email_sender]))
        return [(id, name) for id, name in department_ids]
