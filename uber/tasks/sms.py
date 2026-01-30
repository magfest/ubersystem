import logging
from time import sleep

from pockets import readable_join
from twilio.base.exceptions import TwilioRestException
from twilio.rest import Client as TwilioRestClient

from uber.config import c
from uber.tasks import celery
from uber.utils import normalize_phone

log = logging.getLogger(__name__)

__all__ = ['get_twilio_client', 'send_sms', 'send_sms_with_client']


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


@celery.task
def send_sms(twilio_sid, twilio_token, to, body, from_):
    return send_sms_with_client(get_twilio_client(twilio_sid, twilio_token), to, body, from_)


def send_sms_with_client(twilio_client, to, body, from_):
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
