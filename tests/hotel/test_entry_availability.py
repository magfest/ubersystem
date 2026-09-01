"""Room-type availability on the entry form: the hotel-to-type map and the
config the pricing section renders from."""

from datetime import date
from decimal import Decimal

from uber.hotel.pricing import entry_pricing_config
from uber.hotel.queries import active_inventory_type_map
from uber.models.hotel import InventoryPrice

from tests.hotel.factories import make_hotel, make_inventory, make_room_type


N1 = date(2027, 1, 7)


# ---------------------------------------------------------------------------
# active_inventory_type_map
# ---------------------------------------------------------------------------

def test_map_groups_types_by_hotel(session):
    hotel_a, hotel_b = make_hotel(session), make_hotel(session)
    std = make_room_type(session)
    other = make_room_type(session)

    make_inventory(session, hotel_a, room_type=std)
    make_inventory(session, hotel_b, room_type=other)
    session.flush()

    result = active_inventory_type_map(session, is_suite=False)
    assert str(std.id) in result[str(hotel_a.id)]
    assert str(std.id) not in result.get(str(hotel_b.id), [])
    assert str(other.id) in result[str(hotel_b.id)]


def test_map_excludes_inactive_blocks(session):
    hotel = make_hotel(session)
    room_type = make_room_type(session)
    inv = make_inventory(session, hotel, room_type=room_type)
    inv.active = False
    session.flush()

    assert active_inventory_type_map(session, is_suite=False).get(str(hotel.id)) is None


def test_map_separates_suites_from_rooms(session):
    hotel = make_hotel(session)
    std = make_room_type(session)
    suite = make_room_type(session, is_suite=True)
    make_inventory(session, hotel, room_type=std)
    suite_block = make_inventory(session, hotel)
    suite_block.is_suite = True
    suite_block.room_type_id = None
    suite_block.suite_type_id = suite.id
    session.flush()

    rooms = active_inventory_type_map(session, is_suite=False)
    suites = active_inventory_type_map(session, is_suite=True)
    assert str(std.id) in rooms[str(hotel.id)]
    assert str(suite.id) in suites[str(hotel.id)]
    assert str(suite.id) not in rooms[str(hotel.id)]


# ---------------------------------------------------------------------------
# entry_pricing_config
# ---------------------------------------------------------------------------

def test_config_carries_rates_and_occupancy_range(session):
    hotel = make_hotel(session)
    inv = make_inventory(session, hotel, capacity=4, min_capacity=2)
    inv.base_price = Decimal('199.00')
    session.flush()

    config = entry_pricing_config(session, include_rooms=True)
    assert config['occupancy'] == {'min': 2, 'max': 4}
    block = config['hotels'][0]['blocks'][0]
    assert block['rates']['public']['base'] == '199.00'
    assert 'staff' not in block['rates']


def test_config_hides_staff_rates_unless_requested(session):
    hotel = make_hotel(session)
    inv = make_inventory(session, hotel)
    inv.base_price = Decimal('199.00')
    inv.base_staff_price = Decimal('149.00')
    session.flush()

    without = entry_pricing_config(session, include_rooms=True)
    assert 'staff' not in without['hotels'][0]['blocks'][0]['rates']

    with_staff = entry_pricing_config(session, include_rooms=True, show_staff_rates=True)
    assert with_staff['hotels'][0]['blocks'][0]['rates']['staff']['base'] == '149.00'


def test_config_scopes_to_requested_kinds(session):
    hotel = make_hotel(session)
    suite_block = make_inventory(session, hotel)
    suite_block.is_suite = True
    session.flush()

    rooms_only = entry_pricing_config(session, include_rooms=True, include_suites=False)
    assert rooms_only['hotels'] == []

    with_suites = entry_pricing_config(session, include_rooms=False, include_suites=True)
    assert len(with_suites['hotels']) == 1


def test_config_is_json_safe(session):
    import json

    hotel = make_hotel(session)
    inv = make_inventory(session, hotel, capacity=2, min_capacity=1)
    inv.base_price = Decimal('199.00')
    inv.price_per_night = True
    session.add(InventoryPrice(inventory_id=inv.id, night_date=N1,
                               occupancy=None, is_staff=False, price=Decimal('249.00')))
    session.flush()

    config = entry_pricing_config(session, include_rooms=True)
    json.dumps(config)
    rates = config['hotels'][0]['blocks'][0]['rates']['public']
    assert rates['nights'] == [N1.isoformat()]
    assert rates['cells'][N1.isoformat()][''] == '249.00'


# ---------------------------------------------------------------------------
# blocking validator
# ---------------------------------------------------------------------------

class _Field:
    """Minimal stand-in for the WTForms field the validator receives."""
    def __init__(self, name, data, form):
        self.name = name
        self.data = data
        self.form = form


class _Form:
    def __init__(self, hotel_ids, model):
        self.hotel_preference = _Field('hotel_preference', hotel_ids, self)
        self.model = model


def _check(model, hotel_ids, type_ids, is_suite=False):
    from uber.validations.hotel_lottery import _check_types_available
    form = _Form(hotel_ids, model)
    field = _Field('room_type_preference', type_ids, form)
    _check_types_available(form, field, is_suite=is_suite, step_label='Step')


def test_validator_blocks_when_every_type_is_unavailable(session):
    from wtforms.validators import ValidationError
    import pytest

    hotel_a, hotel_b = make_hotel(session), make_hotel(session)
    at_a, at_b = make_room_type(session), make_room_type(session)
    make_inventory(session, hotel_a, room_type=at_a)
    make_inventory(session, hotel_b, room_type=at_b)
    session.flush()

    with pytest.raises(ValidationError) as exc:
        _check(hotel_a, [str(hotel_a.id)], [str(at_b.id)])
    assert at_b.name in str(exc.value)


def test_validator_allows_a_partial_overlap(session):
    """Ranking one reachable type is enough; the rest is a client-side
    advisory, not an error."""
    hotel_a, hotel_b = make_hotel(session), make_hotel(session)
    at_a, at_b = make_room_type(session), make_room_type(session)
    make_inventory(session, hotel_a, room_type=at_a)
    make_inventory(session, hotel_b, room_type=at_b)
    session.flush()

    _check(hotel_a, [str(hotel_a.id)], [str(at_a.id), str(at_b.id)])


def test_validator_ignores_empty_selections(session):
    hotel = make_hotel(session)
    room_type = make_room_type(session)
    make_inventory(session, hotel, room_type=room_type)
    session.flush()

    _check(hotel, [], [str(room_type.id)])
    _check(hotel, [str(hotel.id)], [])


def test_ranking_widget_price_element_starts_hidden_and_empty():
    """The pricing script fills these with stay totals, so the class is a
    contract between the widget and the JS. No nightly rate is rendered:
    with no calculable total the element stays hidden."""
    from uber.forms.widgets import Ranking

    html = ' '.join(Ranking().extra_info_list({'name': 'Deluxe', 'price': '$199'}))
    assert 'ranking-price' in html
    assert 'hidden' in html
    assert '$199' not in html


def test_ranking_widget_unpriced_choice_has_no_price_element():
    from uber.forms.widgets import Ranking

    html = ' '.join(Ranking().extra_info_list({'name': 'Deluxe'}))
    assert 'ranking-price' not in html


# ---------------------------------------------------------------------------
# room_pricing block survival under plugin overrides
# ---------------------------------------------------------------------------

MAGPRIME_STYLE_OVERRIDE = """
{% extends 'forms/hotel/room_lottery.html' %}
{% block check_in_out_dates_form %}<div class="dates-replaced"></div>{% endblock %}
"""

PRICING_SUPPRESSED_OVERRIDE = """
{% extends 'forms/hotel/room_lottery.html' %}
{% block check_in_out_dates_form %}<div class="dates-replaced"></div>
{% block room_pricing %}{% endblock %}{% endblock %}
"""


def _entry_form_html(session, template_source=None):
    import uber.forms.hotel_lottery  # noqa: F401 - registers the form class
    from uber.config import c
    from uber.forms import load_forms
    from uber.jinja import JinjaEnv

    from tests.hotel.factories import make_application, make_attendee

    hotel = make_hotel(session)
    inv = make_inventory(session, hotel, room_type=make_room_type(session))
    inv.base_price = Decimal('199.00')
    session.flush()

    attendee = make_attendee(session)
    app = make_application(session, attendee)
    forms = load_forms({}, app, ['RoomLottery'])
    context = {
        'c': c,
        'forms': forms,
        'application': app,
        'read_only': False,
        'pricing_config': entry_pricing_config(session),
        'availability_config': {
            'room': active_inventory_type_map(session, is_suite=False),
            'suite': active_inventory_type_map(session, is_suite=True),
            'type_names': {},
        },
    }
    env = JinjaEnv.env()
    if template_source:
        template = env.from_string(template_source)
    else:
        template = env.get_template('forms/hotel/room_lottery.html')
    return template.render(context)


def test_pricing_renders_before_the_save_button(session, no_cherrypy_session):
    html = _entry_form_html(session)
    assert html.count('hotelPricingConfig') == 1
    assert html.index('hotelPricingConfig') < html.index('step-1-submit')


def test_pricing_survives_a_dates_form_override(session, no_cherrypy_session):
    """A plugin replacing check_in_out_dates_form without touching
    room_pricing must not lose the pricing section."""
    html = _entry_form_html(session, MAGPRIME_STYLE_OVERRIDE)
    assert 'dates-replaced' in html
    assert html.count('hotelPricingConfig') == 1


def test_pricing_can_still_be_suppressed_explicitly(session, no_cherrypy_session):
    html = _entry_form_html(session, PRICING_SUPPRESSED_OVERRIDE)
    assert 'dates-replaced' in html
    assert 'hotelPricingConfig' not in html
