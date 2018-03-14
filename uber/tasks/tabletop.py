from datetime import timedelta
from http.client import BadStatusLine
from pytz import UTC
from pockets.autolog import log

from uber.config import c
from uber.models import Session
from uber.models.tabletop import TabletopSmsReply, TabletopSmsReminder
from uber.tasks import celery
from uber.tasks.sms import get_twilio_client, send_sms_with_client


__all__ = ['tabletop_check_notification_replies', 'tabletop_send_notifications']


def tabletop_check_notification_replies():
    twilio_client = get_twilio_client(c.TABLETOP_TWILIO_SID, c.TABLETOP_TWILIO_TOKEN)
    if not twilio_client or not c.TABLETOP_TWILIO_NUMBER:
        log.warn('SMS notification replies disabled for tabletop')
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


def tabletop_send_notifications():
    twilio_client = get_twilio_client(c.TABLETOP_TWILIO_SID, c.TABLETOP_TWILIO_TOKEN)
    if not twilio_client or not c.TABLETOP_TWILIO_NUMBER:
        log.warn('SMS notification sending disabled for tabletop')
        return

    with Session() as session:
        for entrant in session.entrants():
            if entrant.should_send_reminder:
                body = c.TABLETOP_REMINDER_SMS.format(entrant=entrant)
                sid = send_sms_with_client(twilio_client, entrant.attendee.cellphone, body, c.TABLETOP_TWILIO_NUMBER)
                entrant.session.add(TabletopSmsReminder(entrant=entrant, text=body, sid=sid))
                entrant.session.commit()


if c.SEND_SMS and c.TABLETOP_TWILIO_NUMBER and c.TABLETOP_TWILIO_SID and c.TABLETOP_TWILIO_TOKEN:
    tabletop_check_notification_replies = celery.schedule(timedelta(minutes=3))(tabletop_check_notification_replies)
    tabletop_send_notifications = celery.schedule(timedelta(minutes=3))(tabletop_send_notifications)
