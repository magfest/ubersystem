from uber.tests import *

def test_hours():
    assert Job(start_time=EPOCH, duration=1).hours == {EPOCH}
    assert Job(start_time=EPOCH, duration=2).hours == {EPOCH, EPOCH + timedelta(hours=1)}

def test_real_duration():
    assert Job(duration=2).real_duration == 2
    assert Job(duration=2, extra15=True).real_duration == 2.25

def test_weighted_hours(monkeypatch):
    monkeypatch.setattr(Job, 'real_duration', 2)
    assert Job(weight=1).weighted_hours == 2
    assert Job(weight=1.5).weighted_hours == 3
    assert Job(weight=2).weighted_hours == 4

def test_total_hours(monkeypatch):
    monkeypatch.setattr(Job, 'weighted_hours', 3)
    assert Job(slots=1).total_hours == 3
    assert Job(slots=2).total_hours == 6


@pytest.fixture
def dept1():
    return JOB_LOC_OPTS[0][0]

@pytest.fixture
def dept2():
    return JOB_LOC_OPTS[1][0]

@pytest.fixture
def session(request, dept1, dept2):
    session = Session().session
    session.job_one = Job(
        name='Job One',
        start_time=EPOCH,
        slots=1,
        weight=1,
        duration=2,
        location=dept1,
        extra15=True
    )
    session.job_two = Job(
        name='Job Two',
        start_time=EPOCH + timedelta(hours=1),
        slots=1,
        weight=1,
        duration=2,
        location=dept1
    )
    session.job_three = Job(
        name='Job Three',
        start_time=EPOCH + timedelta(hours=2),
        slots=1,
        weight=1,
        duration=2,
        location=dept1
    )
    session.job_four = Job(
        name='Job Four',
        start_time=EPOCH,
        slots=2,
        weight=1,
        duration=2,
        location=dept2,
        extra15=True
    )
    session.job_five = Job(
        name='Job Five',
        start_time=EPOCH + timedelta(hours=2),
        slots=1,
        weight=1,
        duration=2,
        location=dept2
    )
    session.job_six = Job(
        name='Job Six',
        start_time=EPOCH,
        slots=1,
        weight=1,
        duration=2,
        location=dept2,
        restricted=True
    )
    session.add_all([getattr(session, 'job_' + num) for num in {'one', 'two', 'three', 'four', 'five', 'six'}])
    session.commit()
    for number in ['One', 'Two', 'Three', 'Four', 'Five']:
        setattr(session, 'staff_{}'.format(number).lower(), session.attendee(badge_type=STAFF_BADGE, first_name=number))
    request.addfinalizer(session.close)
    return session


class TestAssign:
    @pytest.fixture(autouse=True)
    def default_assignment(self, session):
        assert not session.assign(session.staff_one.id, session.job_one.id)

    def test_non_volunteer(self, session):
        attendee = session.query(Attendee).filter_by(staffing=False).first()
        assert session.assign(attendee.id, session.job_one.id)

    def test_restricted(self, session):
        assert session.assign(session.staff_two.id, session.job_six.id)
        session.staff_two.trusted = True
        session.commit()
        assert not session.assign(session.staff_two.id, session.job_six.id)

    def test_full(self, session):
        assert session.assign(session.staff_two.id, session.job_one.id)

        assert not session.assign(session.staff_three.id, session.job_four.id)
        assert not session.assign(session.staff_four.id, session.job_four.id)
        assert session.assign(session.staff_four.id, session.job_four.id)

    # this indirectly tests the .no_overlap() method, though a more direct test would be good as well
    def test_overlap(self, session):
        assert session.assign(session.staff_one.id, session.job_one.id)
        assert session.assign(session.staff_one.id, session.job_two.id)
        assert session.assign(session.staff_one.id, session.job_five.id)
        assert not session.assign(session.staff_one.id, session.job_three.id)


class TestAvailableStaffers:
    @pytest.fixture(autouse=True)
    def extra_setup(self, session, monkeypatch, dept1, dept2):
        monkeypatch.setattr(Job, 'all_staffers', [session.staff_one, session.staff_two, session.staff_three, session.staff_four])
        monkeypatch.setattr(Job, 'no_overlap', lambda self, a: True)

        session.staff_one.trusted = session.staff_four.trusted = True

        session.staff_one.assigned_depts = str(dept1)
        session.staff_two.assigned_depts = str(dept2)
        session.staff_three.assigned_depts = '{},{}'.format(dept1, dept2)
        session.staff_four.assigned_depts = '{},{}'.format(dept1, dept2)

    def test_by_department(self, session):
        assert session.job_one.available_staffers == [session.staff_one, session.staff_three, session.staff_four]
        assert session.job_four.available_staffers == [session.staff_two, session.staff_three, session.staff_four]

    def test_by_trust(self, session):
        assert session.job_six.available_staffers == [session.staff_four]

    def test_by_overlap(self, session, monkeypatch):
        monkeypatch.setattr(Job, 'no_overlap', lambda self, a: a in [session.staff_one, session.staff_two])
        assert session.job_one.available_staffers == [session.staff_one]
        assert session.job_four.available_staffers == [session.staff_two]
