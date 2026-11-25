import inspect

import pytest
from sqlalchemy import event

from uber.models import Attendee, PanelApplicant, Session
from uber.panelist_matching import MATCH_EMAIL, MATCH_EMAIL_AND_NAME, MATCH_NAME, badge_candidates, names_match
from uber.site_sections.panels_admin import Root


@pytest.mark.parametrize('a, b, expected', [
    (('Jim', 'Okafor'), ('Jim', 'Okafor'), True),
    ((' jim ', 'OKAFOR'), ('Jim', 'okafor '), True),
    (('Jim', 'Okafor'), ('Jimmy', 'Okafor'), True),
    (('Jimmy', 'Okafor'), ('Jim', 'Okafor'), True),
    (('Bob', 'Okafor'), ('Robert', 'Okafor'), False),
    (('Jim', 'Okafor'), ('Jim', 'Raman'), False),
    (('', 'Okafor'), ('Jim', 'Okafor'), False),
    (('Jim', ''), ('Jim', ''), False),
])
def test_names_match(a, b, expected):
    assert names_match(*a, *b) is expected


def _candidates(family):
    with Session() as session:
        applicant = session.get(PanelApplicant, family.ids['jim_row'])
        return [(cand.attendee.id, cand.reason, cand.conflict.id if cand.conflict else None, cand.conflict_same_panel)
                for cand in badge_candidates(session, applicant)]


def test_candidates_by_reason(family):
    ids = family.ids
    # The invalid badge shares the email and the exact name, and is still left out.
    assert _candidates(family) == [(ids['jimmy'], MATCH_EMAIL_AND_NAME, None, False),
                                   (ids['sarah'], MATCH_EMAIL, None, False),
                                   (ids['jim_work'], MATCH_NAME, None, False)]


def test_badge_linked_to_other_person_on_same_panel_is_flagged_and_last(family):
    ids = family.ids
    sarah_row = family.add_row('Sarah', 'app', 'sarah')

    assert _candidates(family) == [(ids['jimmy'], MATCH_EMAIL_AND_NAME, None, False),
                                   (ids['jim_work'], MATCH_NAME, None, False),
                                   (ids['sarah'], MATCH_EMAIL, sarah_row, True)]


def test_conflict_on_other_panel_is_flagged_not_same_panel(family):
    sarah_row = family.add_row('Sarah', 'other_app', 'sarah')

    assert _candidates(family)[-1] == (family.ids['sarah'], MATCH_EMAIL, sarah_row, False)


def test_own_nickname_row_on_other_panel_is_not_a_conflict(family):
    family.add_row('Jimmy', 'other_app', 'jimmy')

    assert _candidates(family)[0] == (family.ids['jimmy'], MATCH_EMAIL_AND_NAME, None, False)


def test_blank_email_matches_no_blank_email_badge(family):
    ids = family.ids
    with Session() as session:
        session.get(PanelApplicant, ids['jim_row']).email = ''
        session.get(Attendee, ids['sarah']).email = ''
        session.commit()

    assert _candidates(family) == [(ids['jim_work'], MATCH_NAME, None, False),
                                   (ids['jimmy'], MATCH_NAME, None, False)]


def test_badges_page_lists_candidates_with_reasons(family):
    with Session() as session:
        result = inspect.unwrap(Root.badges)(Root(), session)
        [candidates] = [cands for pa, cands in result['applicants'] if pa.id == family.ids['jim_row']]
        assert [cand.reason for cand in candidates] == [MATCH_EMAIL_AND_NAME, MATCH_EMAIL, MATCH_NAME]


def _badges_page_statements():
    statements = []

    def count(conn, cursor, statement, *args):
        statements.append(statement)
    event.listen(Session.engine, 'before_cursor_execute', count)
    try:
        with Session() as session:
            inspect.unwrap(Root.badges)(Root(), session)
    finally:
        event.remove(Session.engine, 'before_cursor_execute', count)
    return len(statements)


def test_badges_page_query_count_does_not_grow_per_panelist(family):
    before = _badges_page_statements()
    for first_name in ['Ann', 'Bo', 'Cy']:
        family.add_row(first_name, 'app')

    # Three more unlinked panelists, each with candidates, may not add a query apiece.
    assert _badges_page_statements() - before < 3
