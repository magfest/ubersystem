from time import sleep

from pockets import listify, readable_join
from pockets.autolog import log
from twilio.base.exceptions import TwilioRestException
from twilio.rest import Client as TwilioRestClient

import uber
from uber.amazon_ses import AmazonSES, EmailMessage  # TODO: replace this after boto adds Python 3 support
from uber.config import c
from uber.utils import normalize_phone


__all__ = ['send_email', 'get_twilio_client', 'send_sms']


# ============================================================================
# Email
# ============================================================================


def _record_email_sent(email):
    """
    Save in our database the contents of the Email model passed in.

    We'll use this for history tracking, and to know that we shouldn't
    re-send this email because it already exists

    Note:
        This is in a separate function so we can unit test it.

    """
    with uber.models.Session() as session:
        session.add(email)


def _is_dev_email(email):
    """
    Returns True if `email` is a development email address.

    Development email addresses either end in "mailinator.com" or exist
    in the `c.DEVELOPER_EMAIL` list.
    """
    return email.endswith('mailinator.com') or c.DEVELOPER_EMAIL in email


def send_email(sender, to, subject, body, format='text', cc=(), bcc=(), model=None, ident=None):
    subject = subject.format(EVENT_NAME=c.EVENT_NAME)
    to, cc, bcc = map(listify, [to, cc, bcc])
    ident = ident or subject
    if c.DEV_BOX:
        for xs in [to, cc, bcc]:
            xs[:] = [email for email in xs if _is_dev_email(email)]

    if c.SEND_EMAILS and to:
        msg_kwargs = {'bodyText' if format == 'text' else 'bodyHtml': body}
        message = EmailMessage(subject=subject, **msg_kwargs)
        AmazonSES(c.AWS_ACCESS_KEY, c.AWS_SECRET_KEY).sendEmail(
            source=sender,
            toAddresses=to,
            ccAddresses=cc,
            bccAddresses=bcc,
            message=message)
        sleep(0.1)  # Avoid hitting rate limit
    else:
        log.error('email sending turned off, so unable to send {}', locals())

    if model and to:
        body = body.decode('utf-8') if isinstance(body, bytes) else body
        if model == 'n/a':
            fk_kwargs = {'model': 'n/a'}
        else:
            fk_kwargs = {'fk_id': model.id, 'model': model.__class__.__name__}

        _record_email_sent(uber.models.email.Email(
            subject=subject,
            body=body,
            sender=sender,
            to=','.join(to),
            cc=','.join(cc),
            bcc=','.join(bcc),
            ident=ident,
            **fk_kwargs))


# ============================================================================
# SMS
# ============================================================================

def get_twilio_client(twilio_sid, twilio_token):
    if c.SEND_SMS:
        try:
            if twilio_sid and twilio_token:
                return TwilioRestClient(twilio_sid, twilio_token)
            else:
                log.info('Twilio: could not create twilio client. Missing twilio {}.'.format(
                    readable_join(['' if twilio_sid else 'SID', '' if twilio_token else 'TOKEN'])))
        except Exception:
            log.error('Twilio: could not create twilio client', exc_info=True)
    return None


def send_sms(twilio_client, to, body, from_):
    message = None
    sid = 'Unable to send SMS'
    try:
        to = normalize_phone(to)
        if not twilio_client:
            log.error('No twilio client configured')
        elif c.DEV_BOX and to not in c.TESTING_PHONE_NUMBERS:
            log.info('We are in DEV BOX mode, so we are not sending {!r} to {!r}', body, to)
        else:
            message = twilio_client.messages.create(to=to, body=body, from_=normalize_phone(from_))
            sleep(0.1)  # Avoid hitting rate limit.
        if message:
            sid = message.sid if not message.error_code else message.error_text
    except TwilioRestException as e:
        if e.code == 21211:  # https://www.twilio.com/docs/api/errors/21211
            log.error('Invalid cellphone number', exc_info=True)
        else:
            log.error('Unable to send SMS notification', exc_info=True)
            raise
    except Exception:
        log.error('Unexpected error sending SMS', exc_info=True)
        raise
    return sid
