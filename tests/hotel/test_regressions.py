"""Phase-0 regression pins:

1. LotteryInfo.populate_obj accepts dry_run and performs no attendee
   writes in that mode (the AttendeeHotelNameMixin routes hotel_first/
   last_name onto the attendee only on a real save).
2. The room_expired email template renders from queue-shaped data (scalar
   strings + the application model) - the expiry cron dict-serializes
   anything richer, so the template must work with exactly this shape.
"""

from tests.hotel.factories import make_application, make_attendee


def test_lottery_info_populate_obj_dry_run_no_attendee_writes(session):
    import uber.forms.hotel_lottery  # noqa: F401 - registers the form class
    from uber.forms import load_forms

    attendee = make_attendee(session, first='Original', last='Name')
    attendee.hotel_first_name = 'Original'
    attendee.hotel_last_name = 'Name'
    session.flush()
    app = make_application(session, attendee, cellphone='')

    params = {
        'cellphone': '5555550123',
        'hotel_first_name': 'Changed',
        'hotel_last_name': 'Person',
        'terms_accepted': True,
        'data_policy_accepted': True,
    }
    forms = load_forms(params, app, ['LotteryInfo'])
    form = forms['lottery_info']

    # The regression: this call must accept dry_run as a keyword...
    form.populate_obj(app, is_admin=True, dry_run=True)

    # ...and must not write through to the attendee in dry-run mode.
    assert attendee.hotel_first_name == 'Original'
    assert attendee.hotel_last_name == 'Name'

    # A real (non-dry-run) save does write the attendee-backed fields.
    form.populate_obj(app, is_admin=True, dry_run=False)
    assert attendee.hotel_first_name == 'Changed'
    assert attendee.hotel_last_name == 'Person'
    assert app.cellphone == '5555550123'


def test_room_expired_template_renders_from_queue_shaped_data(session):
    from uber.decorators import render

    attendee = make_attendee(session, first='Expiry', last='Tester')
    app = make_application(session, attendee)

    # Exactly the shape expire_unsecured_assignments queues: the app model
    # as to_model plus pre-formatted scalar strings.
    html = render('emails/hotel/room_expired.html', {
        'app': app,
        'hotel_name': 'Regression Test Hotel',
        'deadline_display': 'Sunday, October 11, 2026',
        'check_in_display': '01/08/2026',
        'check_out_display': '01/10/2026',
    })
    text = html.decode('utf-8') if isinstance(html, bytes) else html

    assert text.strip(), 'template must produce non-empty output'
    assert 'Regression Test Hotel' in text
    assert 'Expiry' in text
    assert 'Sunday, October 11, 2026' in text
    assert '01/08/2026' in text

    # The no-application variant (manual / partition grants) renders too.
    html2 = render('emails/hotel/room_expired.html', {
        'attendee': attendee,
        'hotel_name': '',
        'deadline_display': '',
        'check_in_display': '',
        'check_out_display': '',
    })
    text2 = html2.decode('utf-8') if isinstance(html2, bytes) else html2
    assert 'Expiry' in text2
    assert 'Regression Test Hotel' not in text2
