import inspect

from uber.config import c
from uber.models import Attendee, PanelApplicant, PanelApplication, Session
from uber.site_sections.panels_admin import Root

# The undecorated handler body; the ajax and access decorators need a live request.
link_badge = inspect.unwrap(Root.link_badge)


def _link(applicant_id, attendee_id, **params):
    with Session() as session:
        return link_badge(Root(), session, applicant_id=applicant_id, attendee_id=attendee_id, **params)


def _linked_badge(applicant_id):
    with Session() as session:
        return session.get(PanelApplicant, applicant_id).attendee_id


def test_flagged_link_asks_and_changes_nothing(family):
    family.add_row('Sarah', 'app', 'sarah')
    with Session() as session:
        before = session.get(Attendee, family.ids['sarah']).transferable

    result = _link(family.ids['jim_row'], family.ids['sarah'])

    assert 'Sarah' in result['confirm'] and 'this panel' in result['confirm']
    assert _linked_badge(family.ids['jim_row']) is None
    with Session() as session:
        badge = session.get(Attendee, family.ids['sarah'])
        assert c.PANELIST_RIBBON not in badge.ribbon_ints
        assert badge.transferable == before


def test_flagged_link_names_the_other_panel(family):
    family.add_row('Sarah', 'other_app', 'sarah')
    with Session() as session:
        other_name = session.get(PanelApplication, family.ids['other_app']).name

    result = _link(family.ids['jim_row'], family.ids['sarah'])

    assert f'"{other_name}"' in result['confirm']


def test_confirmed_flagged_link_links(family):
    family.add_row('Sarah', 'app', 'sarah')

    assert 'linked' in _link(family.ids['jim_row'], family.ids['sarah'], confirmed='1')

    assert _linked_badge(family.ids['jim_row']) == family.ids['sarah']


def test_unflagged_link_needs_no_confirm(family):
    assert 'linked' in _link(family.ids['jim_row'], family.ids['jimmy'])

    assert _linked_badge(family.ids['jim_row']) == family.ids['jimmy']


def test_conflict_row_without_panels_still_asks(family):
    sarah_row = family.add_row('Sarah', 'other_app', 'sarah')
    with Session() as session:
        session.get(PanelApplicant, sarah_row).applications = []
        session.commit()

    result = _link(family.ids['jim_row'], family.ids['sarah'])

    assert 'another panel' in result['confirm']
