import cherrypy
import pytest
from mock import Mock

import uber
from uber.config import c
from uber.models import Job, Attendee
from uber.utils import localized_now


@pytest.fixture
def attendee(): return Attendee()


@pytest.fixture
def job(): return Job()


@pytest.fixture
def post(request):
    request.addfinalizer(lambda: setattr(cherrypy.request, 'method', 'GET'))
    cherrypy.request.method = 'POST'


@pytest.fixture
def check_csrf(monkeypatch):
    monkeypatch.setattr(uber.models, 'check_csrf', Mock())
    return uber.models.check_csrf


def test_restricted(attendee):
    assert attendee.paid == c.NOT_PAID
    attendee.apply({'paid': c.HAS_PAID})
    assert attendee.paid == c.NOT_PAID


def test_not_restricted(attendee):
    assert attendee.paid == c.NOT_PAID
    attendee.apply({'paid': c.HAS_PAID}, restricted=False)
    assert attendee.paid == c.HAS_PAID


def test_unassign_all_interests(attendee, post):
    assert attendee.interests == ''

    # set this up by assigning arcade as an interest
    attendee.apply({'interests': c.ARCADE}, restricted=False, checkgroups={'interests'})
    assert attendee.interests == str(c.ARCADE)

    # make sure if we remove all interests by leaving params blank that it sticks
    # note: this only works when submitting data via POST
    attendee.apply({}, restricted=False, checkgroups={'interests'})
    assert attendee.interests == ''


def test_unassign_all_ribbons(attendee, post):
    assert attendee.ribbon == ''

    # set this up by assigning shopkeep as an ribbon
    attendee.apply({'ribbon': c.DEALER_RIBBON}, restricted=False, checkgroups={'ribbon'})
    assert attendee.ribbon == str(c.DEALER_RIBBON)

    # make sure if we remove all assigned_depts by leaving params blank that it sticks
    # note: this only works when submitting data via POST
    attendee.apply({}, restricted=False, checkgroups={'ribbon'})
    assert attendee.ribbon == ''


def test_dont_let_restricted_unassign_all_ribbons(attendee, post):
    assert attendee.ribbon == ''

    # set this up by trying to assign arcade as an assigned dept, which should fail
    attendee.apply({'ribbon': c.DEALER_RIBBON}, restricted=True, checkgroups={'ribbon'})
    assert attendee.ribbon == ''

    attendee.ribbon = str(c.DEALER_RIBBON)

    # make sure if we attempt to remove all ribbon by leaving params blank that it doens't let us
    attendee.apply({}, restricted=True, checkgroups={'ribbon'})
    assert attendee.ribbon == str(c.DEALER_RIBBON)


def test_id(attendee):
    old_id = attendee.id
    attendee.apply({'id': Attendee().id}, restricted=False)
    assert attendee.id == old_id


def test_multilist(attendee):
    assert attendee.ribbon == attendee.interests == ''
    # interests and ribbon are both admin-only; neither changes with restricted=True
    attendee.apply({'ribbon': [c.DEALER_RIBBON, c.PANELIST_RIBBON], 'interests': [c.ARCADE]}, restricted=True)
    assert attendee.interests == ''
    assert attendee.ribbon == ''
    # with restricted=False both change
    attendee.apply({'ribbon': [c.DEALER_RIBBON, c.PANELIST_RIBBON], 'interests': [c.ARCADE]}, restricted=False)
    assert attendee.interests == str(c.ARCADE)
    assert attendee.ribbon != ''


def test_multilist_post(attendee, post):
    ribbons = [c.DEALER_RIBBON, c.PANELIST_RIBBON]
    ribbons_str = ','.join(map(str, ribbons))

    assert attendee.ribbon == attendee.interests == ''

    # interests and ribbon are both admin-only; neither changes with restricted=True
    attendee.apply({'ribbon': ribbons, 'interests': [c.ARCADE]}, restricted=True)
    assert attendee.interests == ''
    assert attendee.ribbon == ''

    # With restricted=False both fields are set
    attendee.apply({'ribbon': ribbons, 'interests': [c.ARCADE]}, restricted=False)
    assert attendee.interests == str(c.ARCADE)
    assert attendee.ribbon == ribbons_str

    # With restricted=True and checkgroups, the checkgroups param is ignored (replaced by regform_checkgroups which is empty)
    # so ribbon and interests retain their values
    attendee.apply({}, restricted=True, checkgroups={'ribbon', 'interests'})
    assert attendee.ribbon == ribbons_str
    assert attendee.interests == str(c.ARCADE)

    # With restricted=False and checkgroups on POST, both fields are cleared
    attendee.apply({}, restricted=False, checkgroups={'ribbon', 'interests'})
    assert attendee.ribbon == attendee.interests == ''


def test_bool(attendee):
    assert not attendee.international
    attendee.apply({'international': True}, restricted=False)
    assert attendee.international


def test_string_stripping(attendee):
    attendee.apply({'first_name': ' Whitespaced  '}, restricted=False)
    assert attendee.first_name == 'Whitespaced'


@pytest.mark.skip(reason="amount_paid is now receipt-based (not a DB column) and cannot be set via apply()")
def test_integer_vals(attendee):
    assert attendee.amount_paid == 0
    assert attendee.paid == c.NOT_PAID
    attendee.apply({'paid': str(c.HAS_PAID), 'amount_paid': '123.45'}, restricted=False)
    assert attendee.amount_paid == 123
    assert attendee.paid == c.HAS_PAID


def test_float_val(job):
    assert job.weight == 1.0
    job.apply({'weight': '1.5'}, restricted=False)
    assert job.weight == 1.5


def test_datetime_val(job):
    format = '%Y-%m-%d %H:%M:%S'
    assert job.start_time is None
    now = localized_now()
    job.apply({'start_time': now.strftime(format)}, restricted=False)
    assert job.start_time.strftime(format) == now.strftime(format)


def test_posted_bools(attendee, post):
    assert not attendee.international
    attendee.staffing = attendee.no_cellphone = True
    attendee.apply({'international': '1', 'no_cellphone': '0'}, bools=['international', 'staffing', 'no_cellphone'],
                   restricted=False)
    assert attendee.international and not attendee.staffing and not attendee.no_cellphone


def test_nonposted_bools(attendee):
    assert not attendee.international
    attendee.staffing = attendee.no_cellphone = True
    # Not a POST: bools param is used only during POST; columns are set via normal coerce_column_data
    # restricted=False needed since international/no_cellphone are admin-only fields
    attendee.apply({'international': '1', 'no_cellphone': '0'}, bools=['international', 'staffing', 'no_cellphone'],
                   restricted=False)
    # coerce_column_data converts '1' -> True and '0' -> False for Boolean columns
    assert attendee.international == True and attendee.no_cellphone == False and attendee.staffing


def test_posted_checkgroups(attendee, post):
    # c.CONSOLE no longer exists; use c.ARCADE instead
    # interests is admin-only so restricted=False is required for checkgroups to apply
    attendee.interests = str(c.ARCADE)
    attendee.apply({}, checkgroups=['interests'], restricted=False)
    assert attendee.interests == ''


def test_nonposted_checkgroups(attendee):
    # c.CONSOLE no longer exists; use c.ARCADE instead
    # interests is admin-only so restricted=False is required
    attendee.interests = str(c.ARCADE)
    attendee.apply({}, checkgroups=['interests'], restricted=False)
    assert attendee.interests == str(c.ARCADE)


def test_ignored_csrf(attendee, post, check_csrf):
    attendee.apply({})
    assert not check_csrf.called
    attendee.apply({'csrf_token': 'foo'}, ignore_csrf=False)
    check_csrf.assert_called_with('foo')


def test_ignored_csrf_nonposted(attendee, check_csrf):
    attendee.apply({'csrf_token': 'foo'}, ignore_csrf=False)
    assert not check_csrf.called
