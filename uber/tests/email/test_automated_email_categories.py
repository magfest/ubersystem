from uber.tests.email.email_fixtures import *


class FakeModel:
    pass


@pytest.mark.usefixtures("email_subsystem_sane_setup")
class TestAutomatedEmailCategory:
    def test_testing_environment(self, get_test_email_category):
        assert len(AutomatedEmail.instances) == 1
        assert len(AutomatedEmail.queries[Attendee](None)) == 3
        assert not get_test_email_category.unapproved_emails_not_sent

    def test_event_name(self, get_test_email_category):
        assert get_test_email_category.subject == E.SUBJECT_TO_FIND
        assert get_test_email_category.ident == E.IDENT_TO_FIND

    def test_approval_needed_and_we_have_it(self, monkeypatch, set_test_approved_idents, get_test_email_category, log_unsent_because_unapproved):
        job = SendAllAutomatedEmailsJob()
        assert get_test_email_category.approved
        assert job.log_unsent_because_unapproved.call_count == 0

    def test_approval_needed_and_we_dont_have_it(self, monkeypatch, get_test_email_category, log_unsent_because_unapproved):
        job = SendAllAutomatedEmailsJob()
        assert not get_test_email_category.approved
        assert job.log_unsent_because_unapproved.call_count == 1

        # attempt to send the same email and we should see the unapproved count go up because it's still unapproved
        assert not get_test_email_category.approved
        assert job.log_unsent_because_unapproved.call_count == 2

    def test_approval_not_needed(self, monkeypatch, get_test_email_category):
        assert not get_test_email_category.approved
        monkeypatch.setattr(get_test_email_category, 'needs_approval', False)
        assert get_test_email_category.approved

    # --------------  test should_send() -------------------

    def test_should_send_goes_through(self, get_test_email_category, set_test_approved_idents, attendee1):
        assert get_test_email_category._should_send(model_inst=attendee1)

    def test_should_send_incorrect_model_used(self, monkeypatch, get_test_email_category, attendee1):
        wrong_model = FakeModel()
        assert not get_test_email_category._should_send(model_inst=wrong_model)

    def test_should_send_no_email_present(self, monkeypatch, get_test_email_category, attendee1):
        delattr(attendee1, 'email')
        assert not get_test_email_category._should_send(model_inst=attendee1)

    def test_should_send_blank_email_present(self, monkeypatch, get_test_email_category, attendee1):
        attendee1.email = ''
        assert not get_test_email_category._should_send(model_inst=attendee1)

    def test_should_send_already_sent_this_email(self, get_test_email_category, set_test_approved_idents, set_previously_sent_emails_to_attendee1, attendee1):
        assert not get_test_email_category._should_send(model_inst=attendee1)

    def test_should_send_wrong_filter(self, get_test_email_category, set_test_approved_idents, attendee1):
        get_test_email_category.filter = lambda a: a.paid == c.HAS_PAID
        assert not get_test_email_category._should_send(model_inst=attendee1)

    def test_should_send_not_approved(self, get_test_email_category, attendee1):
        assert not get_test_email_category._should_send(model_inst=attendee1)

    def test_should_send_at_con(self, at_con, get_test_email_category, set_test_approved_idents, attendee1):
        assert not get_test_email_category._should_send(model_inst=attendee1)
        get_test_email_category.allow_during_con = True
        assert get_test_email_category._should_send(model_inst=attendee1)

    # -----------

    def test_send_doesnt_throw_exception(self, monkeypatch, get_test_email_category):
        get_test_email_category.send_if_should(None, raise_errors=False)

    def test_send_throws_exception(self, monkeypatch, get_test_email_category):
        monkeypatch.setattr(get_test_email_category, '_should_send', Mock(side_effect=Exception('Boom!')))
        with pytest.raises(Exception):
            get_test_email_category.send_if_should(None, raise_errors=True)

    def test_really_send_throws_exception(self, monkeypatch, get_test_email_category):
        monkeypatch.setattr(get_test_email_category, 'computed_subject', Mock(side_effect=Exception('Boom!')))
        with pytest.raises(Exception):
            get_test_email_category.really_send(None)

    valid_when = days_after(3, sept_15th - timedelta(days=5))
    invalid_when = days_after(3, sept_15th)

    @pytest.mark.parametrize("when, expected_result", [
        ([invalid_when], False),
        ([valid_when], True),
        ([invalid_when, valid_when], False),
        ([valid_when, invalid_when], False),
        ([invalid_when, invalid_when], False),
        ([valid_when, valid_when], True),
        ((), True)
    ])
    def test_when_function(self, monkeypatch, get_test_email_category, set_datebase_now_to_sept_15th, attendee1, when, expected_result):
        monkeypatch.setattr(get_test_email_category, 'when', when)
        monkeypatch.setattr(AutomatedEmail, 'approved', True)

        assert get_test_email_category.filters_run(attendee1) == expected_result
        assert get_test_email_category._run_date_filters() == expected_result
        assert get_test_email_category._should_send(model_inst=attendee1) == expected_result

    @pytest.mark.parametrize("when, expected_text", [
        ([
            days_after(3, sept_15th - timedelta(days=5)),
            before(sept_15th - timedelta(days=3)),
            days_before(3, sept_15th + timedelta(days=5), 1),
        ], [
            'after 09/13',
            'before 09/12',
            'between 09/17 and 09/19'
        ]),
        ([days_after(3, sept_15th - timedelta(days=5))], ['after 09/13']),
    ])
    def test_when_txt(self, monkeypatch, get_test_email_category, set_datebase_now_to_sept_15th, attendee1, when, expected_text):
        monkeypatch.setattr(get_test_email_category, 'when', when)
        assert get_test_email_category.when_txt == '\n'.join(expected_text)

    @pytest.mark.parametrize("filter, expected_result", [
        (lambda a: False, False),
        (lambda a: True, True),
        (lambda a: a.paid == c.NEED_NOT_PAY, True),
        (lambda a: a.paid != c.NEED_NOT_PAY, False),
    ])
    def test_filters(self, monkeypatch, get_test_email_category, attendee1, filter, expected_result):
        monkeypatch.setattr(get_test_email_category, 'filter', filter)
        monkeypatch.setattr(AutomatedEmail, 'approved', True)

        assert get_test_email_category.filters_run(attendee1) == expected_result
        assert get_test_email_category._should_send(model_inst=attendee1) == expected_result

    def test_none_filter(self):
        with pytest.raises(AssertionError):
            AutomatedEmail(Attendee, '', '', None, ident='test_none_filter')

    def test_no_filter(self):
        # this is slightly silly but, if this ever changes, we should be explicit about what the expected result is
        with pytest.raises(TypeError):
            AutomatedEmail(Attendee, '', '', ident='test_no_filter')

    def test_missing_ident_arg(self):
        with pytest.raises(TypeError):
            AutomatedEmail(Attendee, '', '', lambda a: False)

    def test_empty_ident_arg(self):
        with pytest.raises(AssertionError):
            AutomatedEmail(Attendee, '', '', lambda a: False, ident='')

        with pytest.raises(AssertionError):
            AutomatedEmail(Attendee, '', '', lambda a: False, ident=None)
