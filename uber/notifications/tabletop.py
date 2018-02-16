from http.client import BadStatusLine
from pytz import UTC
from pockets.autolog import log
from sideboard.lib import DaemonTask
from twilio.base.exceptions import TwilioRestException
from twilio.rest import Client as TwilioRestClient

from uber.config import c
from uber.models import Session
from uber.models.tabletop import TabletopSmsReply, TabletopSmsReminder
from uber.utils import normalize_phone


__all__ = [
    'tabletop_check_notification_replies', 'tabletop_send_notifications']


TASK_INTERVAL = 180  # Check every three minutes


twilio_client = None
if c.SEND_SMS:
    try:
        twilio_sid = c.TABLETOP_TWILIO_SID
        twilio_token = c.TABLETOP_TWILIO_TOKEN

        if twilio_sid and twilio_token:
            twilio_client = TwilioRestClient(twilio_sid, twilio_token)
        else:
            log.debug(
                'Tabletop twilio SID and/or TOKEN is not in INI, not going to '
                'try to start twilio for tabletop SMS messaging')
    except Exception:
        log.error(
            'twilio: unable to initialize twilio REST client', exc_info=True)
        twilio_client = None
else:
    log.info('SMS DISABLED for tabletop')


def send_sms(to, body, from_=c.TABLETOP_TWILIO_NUMBER):
    to = normalize_phone(to, c.TABLETOP_PHONE_COUNTRY or 'US')
    if not twilio_client:
        log.error('no twilio client configured')
    elif c.DEV_BOX and to not in c.TESTING_PHONE_NUMBERS:
        log.info(
            'We are in dev box mode, so we are not sending {!r} to {!r}',
            body, to)
    else:
        return twilio_client.messages.create(
            to=to,
            body=body,
            from_=normalize_phone(from_, c.TABLETOP_PHONE_COUNTRY or 'US'))


def send_reminder(entrant):
    sid = 'unable to send sms'
    try:
        body = c.TABLETOP_REMINDER_SMS.format(entrant=entrant)
        message = send_sms(entrant.attendee.cellphone, body)
        if message:
            sid = message.sid if not message.error_code else message.error_text
    except TwilioRestException as e:
        if e.code == 21211:  # https://www.twilio.com/docs/api/errors/21211
            log.error('invalid cellphone number for entrant', exc_info=True)
        else:
            log.error('unable to send reminder SMS', exc_info=True)
            raise
    except Exception:
        log.error('Unexpected error sending SMS', exc_info=True)
        raise

    entrant.session.add(
        TabletopSmsReminder(entrant=entrant, text=body, sid=sid))
    entrant.session.commit()


def send_reminder_texts():
    if not twilio_client:
        return

    with Session() as session:
        for entrant in session.entrants():
            if entrant.should_send_reminder:
                send_reminder(entrant)


def check_replies():
    if not twilio_client:
        return

    with Session() as session:
        entrants = session.entrants_by_phone()
        existing_sids = {sid for [sid] in session.query(TabletopSmsReply.sid)}
        messages = []

        # Pull all the messages down before attempting to act on them. The new
        # twilio client uses a streaming mode, so the stream might be timing
        # out while it waits for us to act on each message inside our loop.
        try:
            stream = twilio_client.messages.list(to=c.TABLETOP_TWILIO_NUMBER)
            messages = [message for message in stream]
        except ConnectionError as ex:
            if ex.errno == 'Connection aborted.' \
                    and isinstance(ex.strerror, BadStatusLine) \
                    and ex.strerror.line == "''":
                log.warning('Twilio connection closed unexpectedly')
            else:
                raise ex

        for message in messages:
            if message.sid in existing_sids:
                continue

            for entrant in entrants[message.from_]:
                if entrant.matches(message):
                    session.add(TabletopSmsReply(
                        entrant=entrant,
                        sid=message.sid,
                        text=message.body,
                        when=message.date_sent.replace(tzinfo=UTC)
                    ))
                    entrant.confirmed = 'Y' in message.body.upper()
                    session.commit()


if c.SEND_SMS:
    tabletop_check_notification_replies = DaemonTask(
        check_replies,
        interval=TASK_INTERVAL,
        name='tabletop_check_notification_replies')

    tabletop_send_notifications = DaemonTask(
        send_reminder_texts,
        interval=TASK_INTERVAL,
        name='tabletop_send_notifications')
else:
    tabletop_check_notification_replies = None
    tabletop_send_notifications = None
