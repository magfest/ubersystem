from uber.tests import *


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
    attendee.apply({'ribbon': [c.DEALER_RIBBON, c.PANELIST_RIBBON], 'interests': [c.ARCADE]}, restricted=True)
    assert attendee.interests == str(c.ARCADE)
    assert attendee.ribbon == ''


def test_multilist_post(attendee, post):
    ribbons = [c.DEALER_RIBBON, c.PANELIST_RIBBON]
    ribbons_str = ','.join(map(str, ribbons))

    assert attendee.ribbon == attendee.interests == ''

    attendee.apply({'ribbon': ribbons, 'interests': [c.ARCADE]}, restricted=True)
    assert attendee.interests == str(c.ARCADE)
    assert attendee.ribbon == ''

    attendee.apply({}, restricted=True, checkgroups={'ribbon', 'interests'})
    assert attendee.ribbon == attendee.interests == ''

    attendee.apply({'ribbon': ribbons, 'interests': [c.ARCADE]}, restricted=False)
    assert attendee.interests == str(c.ARCADE)
    assert attendee.ribbon == ribbons_str

    attendee.apply({}, restricted=True, checkgroups={'ribbon', 'interests'})
    assert attendee.ribbon == ribbons_str
    assert attendee.interests == ''

    attendee.apply({}, restricted=False, checkgroups={'ribbon', 'interests'})
    assert attendee.ribbon == attendee.interests == ''


def test_bool(attendee):
    assert not attendee.international
    attendee.apply({'international': True})
    assert attendee.international


def test_string_stripping(attendee):
    attendee.apply({'first_name': ' Whitespaced  '})
    assert attendee.first_name == 'Whitespaced'


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
    attendee.apply({'international': '1', 'no_cellphone': '0'}, bools=['international', 'staffing', 'no_cellphone'])
    assert attendee.international and not attendee.staffing and not attendee.no_cellphone


def test_nonposted_bools(attendee):
    assert not attendee.international
    attendee.staffing = attendee.no_cellphone = True
    attendee.apply({'international': '1', 'no_cellphone': '0'}, bools=['international', 'staffing', 'no_cellphone'])
    assert attendee.international == '1' and attendee.no_cellphone == '0' and attendee.staffing == True


def test_posted_checkgroups(attendee, post):
    attendee.interests = str(c.CONSOLE)
    attendee.apply({}, checkgroups=['interests'])
    assert attendee.interests == ''


def test_nonposted_checkgroups(attendee):
    attendee.interests = str(c.CONSOLE)
    attendee.apply({}, checkgroups=['interests'])
    assert attendee.interests == str(c.CONSOLE)


def test_ignored_csrf(attendee, post, check_csrf):
    attendee.apply({})
    assert not check_csrf.called
    attendee.apply({'csrf_token': 'foo'}, ignore_csrf=False)
    check_csrf.assert_called_with('foo')


def test_ignored_csrf_nonposted(attendee, check_csrf):
    attendee.apply({'csrf_token': 'foo'}, ignore_csrf=False)
    assert not check_csrf.called
