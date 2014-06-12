from uber.tests import *

@pytest.fixture
def attendee_id():
    with Session() as session:
        return session.query(Attendee).filter_by(first_name='Regular', last_name='Attendee').one().id

@pytest.fixture(autouse=True)
def mock_apply(monkeypatch):
    monkeypatch.setattr(Attendee, 'apply', Mock())
    return Attendee.apply

def test_invalid_gets():
    with Session() as session:
        pytest.raises(Exception, session.attendee)
        pytest.raises(Exception, session.attendee, '')
        pytest.raises(Exception, session.attendee, [])
        pytest.raises(Exception, session.attendee, None)
        pytest.raises(Exception, session.attendee, str(uuid4()))
        pytest.raises(Exception, session.attendee, {'id': str(uuid4())})

def test_basic_get(attendee_id, mock_apply):
    with Session() as session:
        assert session.attendee(attendee_id).first_name == 'Regular'
        assert not mock_apply.called
        assert session.attendee(id=attendee_id).first_name == 'Regular'
        assert not mock_apply.called
        assert session.attendee({'id': attendee_id}).first_name == 'Regular'
        assert mock_apply.called

def test_empty_get(mock_apply):
    with Session() as session:
        assert session.attendee({}).paid == NOT_PAID  # basic sanity check
        assert mock_apply.called

def test_ignore_csrf(request):
    with Session() as session:
        pytest.raises(Exception, session.attendee, {'paid': NEED_NOT_PAY})
        session.attendee({'paid': NEED_NOT_PAY}, ignore_csrf=True)
        session.attendee({'paid': NEED_NOT_PAY}, allowed=['paid'])
        request.addfinalizer(lambda: setattr(cherrypy, 'request', 'GET'))
        cherrypy.request.method = 'POST'
        session.attendee({'paid': NEED_NOT_PAY})
