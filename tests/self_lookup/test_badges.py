import pytest
from cherrypy import HTTPError

from uber.config import c
from uber.models import AdminAccount, Group
from uber.self_lookup import badge_detail, list_badges
from tests.self_lookup.factories import account, attendee, dept, staffer


def test_lists_badges_managed_by_account(session):
    a, b = attendee(session), attendee(session)
    account(session, 'sub-1', a, b)
    result = list_badges(session, 'sub-1')
    assert result['linked'] is True
    assert {x['id'] for x in result['badges']} == {a.id, b.id}


def test_unlinked_sub(session):
    assert list_badges(session, 'nobody') == {'linked': False, 'badges': []}


def test_duplicate_accounts_merge(session):
    a, b = attendee(session), attendee(session)
    account(session, 'sub-2', a)
    account(session, 'sub-2', b)
    assert len(list_badges(session, 'sub-2')['badges']) == 2


def test_admin_account_badge_included(session):
    s = attendee(session, badge_type=c.STAFF_BADGE)
    session.add(AdminAccount(attendee=s, sso_id='sub-3', hashed=''))
    session.flush()
    assert [x['id'] for x in list_badges(session, 'sub-3')['badges']] == [s.id]


def test_invalid_badge_excluded(session):
    account(session, 'sub-4', attendee(session, badge_status=c.INVALID_STATUS))
    assert list_badges(session, 'sub-4')['badges'] == []


def test_list_omits_pii(session):
    account(session, 'sub-5', attendee(session))
    badge = list_badges(session, 'sub-5')['badges'][0]
    assert not {'email', 'birthdate', 'address1', 'ec_phone', 'cellphone', 'admin_notes'} & badge.keys()


def test_group_exposes_name_only(session):
    group = Group(name='Crew')
    session.add(group)
    session.flush()
    account(session, 'sub-5b', attendee(session, group_id=group.id))
    assert list_badges(session, 'sub-5b')['badges'][0]['group'] == {'name': 'Crew'}


def test_detail_includes_departments(session):
    techops = dept(session, 'TechOps')
    s = staffer(session, 'Head', techops, is_dept_head=True)
    account(session, 'sub-6', s)
    assert badge_detail(session, 'sub-6', s.id)['dept_head_depts'] == {techops.id: techops.name}


def test_detail_of_someone_elses_badge_is_404(session):
    account(session, 'sub-7', attendee(session))
    other = attendee(session)
    with pytest.raises(HTTPError) as e:
        badge_detail(session, 'sub-7', other.id)
    assert e.value.code == 404


def test_detail_with_malformed_id_is_404(session):
    account(session, 'sub-8', attendee(session))
    with pytest.raises(HTTPError) as e:
        badge_detail(session, 'sub-8', 'not-a-uuid')
    assert e.value.code == 404


def test_blank_sub_matches_nothing(session):
    a = attendee(session)
    account(session, '', a)
    for blank in ('', '   ', None):
        assert list_badges(session, blank) == {'linked': False, 'badges': []}
    with pytest.raises(HTTPError) as e:
        badge_detail(session, '', a.id)
    assert e.value.code == 404
