from uber.tests import *

@pytest.fixture
def attendee():
    return Attendee()

@pytest.fixture
def job():
    return Job()

@pytest.fixture
def post(request):
    request.addfinalizer(lambda: setattr(cherrypy.request, 'method', 'GET'))
    cherrypy.request.method = 'POST'

@pytest.fixture
def check_csrf(monkeypatch):
    monkeypatch.setattr(uber.models, 'check_csrf', Mock())
    return uber.models.check_csrf

def test_restricted(attendee):
    assert attendee.paid == NOT_PAID
    attendee.apply({'paid': HAS_PAID})
    assert attendee.paid == NOT_PAID

def test_not_restricted(attendee):
    assert attendee.paid == NOT_PAID
    attendee.apply({'paid': HAS_PAID}, restricted=False)
    assert attendee.paid == HAS_PAID

def test_id(attendee):
    old_id = attendee.id
    attendee.apply({'id': Attendee().id}, restricted=False)
    assert attendee.id == old_id

def test_multilist(attendee):
    assert attendee.requested_depts == attendee.interests == ''
    attendee.apply({'requested_depts': [ARCADE, FOOD_PREP], 'interests': [ARCADE]})
    assert attendee.interests == str(ARCADE)
    assert attendee.requested_depts == str(ARCADE) + ',' + str(FOOD_PREP)

def test_bool(attendee):
    assert not attendee.international
    attendee.apply({'international': True})
    assert attendee.international

def test_string_stripping(attendee):
    attendee.apply({'first_name': ' Whitespaced  '})
    assert attendee.first_name == 'Whitespaced'

def test_integer_vals(attendee):
    assert attendee.amount_paid == 0
    assert attendee.paid == NOT_PAID
    attendee.apply({'paid': str(HAS_PAID), 'amount_paid': '123.45'}, restricted=False)
    assert attendee.amount_paid == 123
    assert attendee.paid == HAS_PAID

def test_float_val(job):
    assert job.weight is None
    job.apply({'weight': '1.5'}, restricted=False)
    assert job.weight == 1.5

def test_datetime_val(job):
    format = '%Y-%m-%d %H:%M:%S'
    assert job.start_time is None
    now = datetime.now(EVENT_TIMEZONE)
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
    attendee.interests = str(CONSOLE)
    attendee.apply({}, checkgroups=['interests'])
    assert attendee.interests == ''

def test_nonposted_checkgroups(attendee):
    attendee.interests = str(CONSOLE)
    attendee.apply({}, checkgroups=['interests'])
    assert attendee.interests == str(CONSOLE)

def test_ignored_csrf(attendee, post, check_csrf):
    attendee.apply({})
    assert not check_csrf.called
    attendee.apply({'csrf_token': 'foo'}, ignore_csrf=False)
    check_csrf.assert_called_with('foo')

def test_ignored_csrf_nonposted(attendee, check_csrf):
    attendee.apply({'csrf_token': 'foo'}, ignore_csrf=False)
    assert not check_csrf.called
