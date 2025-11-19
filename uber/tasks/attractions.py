from datetime import datetime, timedelta

import pytz
from pockets import groupify
from pockets.autolog import log
from sqlalchemy.orm import subqueryload

from uber.custom_tags import humanize_timedelta
from uber.config import c
from uber.decorators import render
from uber.models import Session
from uber.models.attendee import Attendee
from uber.models.attraction import Attraction, AttractionEvent, AttractionNotification, \
    AttractionNotificationReply, AttractionSignup
from uber.tasks import celery
from uber.tasks.email import send_email
from uber.tasks.sms import get_twilio_client, send_sms_with_client
from uber.utils import normalize_phone


__all__ = ['attractions_check_notification_replies', 'send_waitlist_notification', 'attractions_send_notifications']


def attractions_check_notification_replies():
    twilio_client = get_twilio_client(c.PANELS_TWILIO_SID, c.PANELS_TWILIO_TOKEN)
    if not twilio_client or not c.PANELS_TWILIO_NUMBER:
        log.warn('SMS notification replies disabled for attractions')
        return

    with Session() as session:
        messages = twilio_client.messages.list(to=c.PANELS_TWILIO_NUMBER)
        sids = set(m.sid for m in messages)
        existing_sids = set(
            sid for [sid] in
            session.query(AttractionNotificationReply.sid).filter(AttractionNotificationReply.sid.in_(sids)))

        attendees = session.query(Attendee).filter(Attendee.cellphone != '', Attendee.attraction_notifications.any())
        attendees_by_phone = groupify(attendees, lambda a: normalize_phone(a.cellphone))

        for message in filter(lambda m: m.sid not in existing_sids, messages):
            attraction_event_id = None
            attraction_id = None
            attendee_id = None
            attendees = attendees_by_phone.get(normalize_phone(message.from_), [])
            for attendee in attendees:
                notifications = sorted(filter(
                    lambda s: s.notification_type == Attendee._NOTIFICATION_TEXT,
                    attendee.attraction_notifications),
                    key=lambda s: s.sent_time)
                if notifications:
                    notification = notifications[-1]
                    attraction_event_id = notification.attraction_event_id
                    attraction_id = notification.attraction_id
                    attendee_id = notification.attendee_id
                    if 'N' in message.body.upper() and notification.signup:
                        session.delete(notification.signup)
                    break

            session.add(AttractionNotificationReply(
                attraction_event_id=attraction_event_id,
                attraction_id=attraction_id,
                attendee_id=attendee_id,
                notification_type=Attendee._NOTIFICATION_TEXT,
                from_phonenumber=message.from_,
                to_phonenumber=message.to,
                sid=message.sid,
                received_time=datetime.now(pytz.UTC),
                sent_time=message.date_sent.replace(tzinfo=pytz.UTC),
                body=message.body))
            session.commit()

@celery.task
def send_waitlist_notification(signup_id):
    twilio_client = get_twilio_client(c.PANELS_TWILIO_SID, c.PANELS_TWILIO_TOKEN)
    text_template = "You've been signed up from the waitlist for {signup.event.name} in {signup.event.location_room_name}, {signup.event.time_span_label}! Reply N to drop out"

    with Session() as session:
        signup = session.attraction_signup(signup_id)
        attendee = signup.attendee
        event = signup.event
        if attendee.notification_pref == Attendee._NOTIFICATION_NONE or event.no_notifications:
            return

        ident = event.id + "_waitlist"
        use_text = twilio_client \
                    and c.PANELS_TWILIO_NUMBER \
                    and attendee.cellphone \
                    and attendee.notification_pref == Attendee._NOTIFICATION_TEXT
        try:
            if use_text:
                type_ = Attendee._NOTIFICATION_TEXT
                type_str = 'TEXT'
                from_ = c.PANELS_TWILIO_NUMBER
                to_ = attendee.cellphone
                body = text_template.format(signup=signup)
                subject = ''
                sid = send_sms_with_client(twilio_client, to_, body, from_)
            else:
                type_ = Attendee._NOTIFICATION_EMAIL
                type_str = 'EMAIL'
                from_ = c.ATTRACTIONS_EMAIL
                to_ = attendee.email_to_address
                send_email.delay(
                    c.ATTRACTIONS_EMAIL,
                    to_,
                    'Signed up from waitlist',
                    render('emails/panels/attractions_waitlist.html', {'signup': signup}, encoding=None),
                    model=signup.to_dict('id'), ident=ident)
        except Exception:
            log.error(
                'Error sending notification\n'
                '\tfrom: {}\n'
                '\tto: {}\n'
                '\tsubject: {}\n'
                '\tbody: {}\n'
                '\ttype: {}\n'
                '\tattendee: {}\n'
                '\tident: {}\n'.format(
                    from_,
                    to_,
                    subject,
                    body,
                    type_str,
                    attendee.id,
                    ident), exc_info=True)
        else:
            session.add(AttractionNotification(
                attraction_event_id=event.id,
                attraction_id=event.attraction_id,
                attendee_id=attendee.id,
                notification_type=type_,
                ident=ident,
                sid=sid,
                sent_time=datetime.now(pytz.UTC),
                subject=subject,
                body=body))
            session.commit()

def attractions_send_notifications():
    twilio_client = get_twilio_client(c.PANELS_TWILIO_SID, c.PANELS_TWILIO_TOKEN)
    text_template = 'Check-in for {signup.event.name} {checkin}, {signup.event.location_room_name}. Reply N to drop out'

    with Session() as session:
        for attraction in session.query(Attraction):
            now = datetime.now(pytz.UTC)
            from_time = now - timedelta(seconds=300)
            to_time = now + timedelta(seconds=300)
            signups = attraction.signups_requiring_notification(session, from_time, to_time, [
                subqueryload(
                    AttractionSignup.attendee).subqueryload(
                        Attendee.attraction_notifications),
                subqueryload(
                    AttractionSignup.event).subqueryload(
                        AttractionEvent.feature)])

            for signup, advance_notices in signups.items():
                attendee = signup.attendee
                if not attendee.first_name or not attendee.email:
                    try:
                        log.error(
                            'ERROR: Unassigned attendee signed up for an attraction, deleting signup:\n'
                            '\tAttendee.id: {}\n'
                            '\tAttraction.id: {}\n'
                            '\tAttractionEvent.id: {}\n'
                            '\tAttractionSignup.id: {}'.format(
                                attendee.id,
                                signup.attraction_id,
                                signup.attraction_event_id,
                                signup.id))

                        session.delete(signup)
                        session.commit()
                    except Exception:
                        log.error('ERROR: Failed to delete signup with unassigned attendee', exc_info=True)
                    continue

                # The first time someone signs up for an attractions, they always
                # receive the welcome email (even if they've chosen SMS or None
                # for their notification prefs). If they've chosen to receive SMS
                # notifications, they'll also get a text message.
                is_first_signup = not (attendee.attraction_notifications)

                if not is_first_signup and attendee.notification_pref == Attendee._NOTIFICATION_NONE:
                    continue

                use_text = twilio_client \
                    and c.PANELS_TWILIO_NUMBER \
                    and attendee.cellphone \
                    and attendee.notification_pref == Attendee._NOTIFICATION_TEXT

                event = signup.event

                # If we overlap multiple notices, we only want to send a single
                # notification. So if we have both "5 minutes before checkin" and
                # "when checkin starts", we only want to send the notification
                # for "when checkin starts".
                advance_notice = min(advance_notices)
                if advance_notice == -1 or advance_notice > 30:
                    checkin = 'is at {}'.format(event.checkin_start_time_label)
                else:
                    checkin = humanize_timedelta(
                        event.time_remaining_to_checkin,
                        granularity='minutes',
                        separator=' ',
                        prefix='is in ',
                        now='is right now',
                        past_prefix='was ',
                        past_suffix=' ago')

                ident = AttractionEvent.get_ident(event.id, advance_notice)
                try:
                    if use_text:
                        type_ = Attendee._NOTIFICATION_TEXT
                        type_str = 'TEXT'
                        from_ = c.PANELS_TWILIO_NUMBER
                        to_ = attendee.cellphone
                        body = text_template.format(signup=signup, checkin=checkin)
                        subject = ''
                        sid = send_sms_with_client(twilio_client, to_, body, from_)

                    if not use_text or is_first_signup:
                        type_ = Attendee._NOTIFICATION_EMAIL
                        type_str = 'EMAIL'
                        from_ = c.ATTRACTIONS_EMAIL
                        to_ = attendee.email_to_address
                        if is_first_signup:
                            template = 'emails/panels/attractions_welcome.html'
                            subject = 'Welcome to {} Attractions'.format(c.EVENT_NAME)
                        else:
                            template = 'emails/panels/attractions_notification.html'
                            subject = 'Checkin for {} is at {}'.format(event.name, event.checkin_start_time_label)

                        body = render(template, {
                            'signup': signup,
                            'checkin': checkin,
                            'c': c}, encoding=None)
                        sid = ident
                        send_email.delay(from_, to_, subject=subject, body=body, format='html',
                                         model=attendee.to_dict(), ident=ident)
                except Exception:
                    log.error(
                        'Error sending notification\n'
                        '\tfrom: {}\n'
                        '\tto: {}\n'
                        '\tsubject: {}\n'
                        '\tbody: {}\n'
                        '\ttype: {}\n'
                        '\tattendee: {}\n'
                        '\tident: {}\n'.format(
                            from_,
                            to_,
                            subject,
                            body,
                            type_str,
                            attendee.id,
                            ident), exc_info=True)
                else:
                    session.add(AttractionNotification(
                        attraction_event_id=event.id,
                        attraction_id=event.attraction_id,
                        attendee_id=attendee.id,
                        notification_type=type_,
                        ident=ident,
                        sid=sid,
                        sent_time=datetime.now(pytz.UTC),
                        subject=subject,
                        body=body))
                    session.commit()


if c.ATTRACTIONS_ENABLED:
    attractions_send_notifications = celery.schedule(timedelta(minutes=3))(attractions_send_notifications)
    if c.SEND_SMS and c.PANELS_TWILIO_NUMBER and c.PANELS_TWILIO_SID and c.PANELS_TWILIO_TOKEN:
        attractions_check_notification_replies = celery.schedule(
            timedelta(minutes=3))(attractions_check_notification_replies)
