from uber.common import *


def valid_password(password, account):
    pr = account.password_reset
    if pr and pr.is_expired:
        account.session.delete(pr)
        pr = None

    all_hashed = [account.hashed] + ([pr.hashed] if pr else [])
    return any(bcrypt.hashpw(password, hashed) == hashed for hashed in all_hashed)


@all_renderable(c.ACCOUNTS)
class Root:
    def index(self, session, message=''):
        return {
            'message':  message,
            'accounts': session.query(AdminAccount).join(Attendee)
                               .order_by(Attendee.last_first).all(),
            'all_attendees': sorted([
                (id, '{} - {}{}'.format(name.title(), c.BADGES[badge_type], ' #{}'.format(badge_num) if badge_num else ''))
                for id, name, badge_type, badge_num in session.query(Attendee.id, Attendee.last_first, Attendee.badge_type, Attendee.badge_num)
                                    .filter(Attendee.first_name != '').filter(Attendee.badge_status not in [c.INVALID_STATUS, c.WATCHED_STATUS]).all()
            ], key=lambda tup: tup[1])
        }

    def update(self, session, password='', message='', **params):
        account = session.admin_account(params, checkgroups=['access'])
        if account.is_new:
            if c.AT_OR_POST_CON and not password:
                message = 'You must enter a password'
            else:
                password = password if c.AT_OR_POST_CON else genpasswd()
                account.hashed = bcrypt.hashpw(password, bcrypt.gensalt())

        message = message or check(account)
        if not message:
            message = 'Account settings uploaded'
            account.attendee = session.attendee(account.attendee_id)   # dumb temporary hack, will fix later with tests
            session.add(account)
            if account.is_new and not c.AT_OR_POST_CON:
                body = render('emails/accounts/new_account.txt', {
                    'account': account,
                    'password': password
                })
                send_email(c.ADMIN_EMAIL, session.attendee(account.attendee_id).email, 'New ' + c.EVENT_NAME + ' Ubersystem Account', body)

        raise HTTPRedirect('index?message={}', message)

    def delete(self, session, id, **params):
        session.delete(session.admin_account(id))
        raise HTTPRedirect('index?message={}', 'Account deleted')

    def bulk(self, session, location=None, **params):
        location = None if location == 'All' else int(location or c.JOB_LOCATION_OPTS[0][0])
        attendees = session.staffers().filter(*[Attendee.assigned_depts.contains(str(location))] if location else []).all()
        for attendee in attendees:
            attendee.trusted_here = attendee.trusted_in(location) if location else attendee.trusted_somewhere
            attendee.hours_here = sum(shift.job.weighted_hours for shift in attendee.shifts if shift.job.location == location) if location else attendee.weighted_hours

        return {
            'location':  location,
            'attendees': attendees
        }

    @unrestricted
    def login(self, session, message='', original_location=None, **params):
        original_location = create_valid_user_supplied_redirect_url(original_location, default_url='homepage')

        if 'email' in params:
            try:
                account = session.get_account_by_email(params['email'])
                if not valid_password(params['password'], account):
                    message = 'Incorrect password'
            except NoResultFound:
                message = 'No account exists for that email address'

            if not message:
                cherrypy.session['account_id'] = account.id
                cherrypy.session['csrf_token'] = uuid4().hex
                raise HTTPRedirect(original_location)

        return {
            'message': message,
            'email':   params.get('email', ''),
            'original_location': original_location,
        }

    @unrestricted
    def homepage(self, message=''):
        if not cherrypy.session.get('account_id'):
            raise HTTPRedirect('login?message={}', 'You are not logged in')
        return {'message': message}

    @unrestricted
    def logout(self):
        for key in list(cherrypy.session.keys()):
            if key not in ['preregs', 'paid_preregs', 'job_defaults', 'prev_location']:
                cherrypy.session.pop(key)
        raise HTTPRedirect('login?message={}', 'You have been logged out')

    @unrestricted
    def reset(self, session, message='', email=None):
        if email is not None:
            try:
                account = session.get_account_by_email(email)
            except NoResultFound:
                message = 'No account exists for email address {!r}'.format(email)
            else:
                password = genpasswd()
                if account.password_reset:
                    session.delete(account.password_reset)
                    session.commit()
                session.add(PasswordReset(admin_account=account, hashed=bcrypt.hashpw(password, bcrypt.gensalt())))
                body = render('emails/accounts/password_reset.txt', {
                    'name': account.attendee.full_name,
                    'password':  password
                })
                send_email(c.ADMIN_EMAIL, account.attendee.email, c.EVENT_NAME + ' Admin Password Reset', body)
                raise HTTPRedirect('login?message={}', 'Your new password has been emailed to you')

        return {
            'email':   email,
            'message': message
        }

    def update_password_of_other(self, session, id, message='', updater_password=None, new_password=None, csrf_token=None, confirm_new_password=None):
        if updater_password is not None:
            new_password = new_password.strip()
            updater_account = session.admin_account(cherrypy.session['account_id'])
            if not new_password:
                message = 'New password is required'
            elif not valid_password(updater_password, updater_account):
                message = 'Your password is incorrect'
            elif new_password != confirm_new_password:
                message = 'Passwords do not match'
            else:
                check_csrf(csrf_token)
                account = session.admin_account(id)
                account.hashed = bcrypt.hashpw(new_password, bcrypt.gensalt())
                raise HTTPRedirect('index?message={}', 'Account Password Updated')

        return {
            'account': session.admin_account(id),
            'message': message
        }

    @unrestricted
    def change_password(self, session, message='', old_password=None, new_password=None, csrf_token=None, confirm_new_password=None):
        if not cherrypy.session.get('account_id'):
            raise HTTPRedirect('login?message={}', 'You are not logged in')

        if old_password is not None:
            new_password = new_password.strip()
            account = session.admin_account(cherrypy.session['account_id'])
            if not new_password:
                message = 'New password is required'
            elif not valid_password(old_password, account):
                message = 'Incorrect old password; please try again'
            elif new_password != confirm_new_password:
                message = 'Passwords do not match'
            else:
                check_csrf(csrf_token)
                account.hashed = bcrypt.hashpw(new_password, bcrypt.gensalt())
                raise HTTPRedirect('homepage?message={}', 'Your password has been updated')

        return {'message': message}

    # print out a CSV list of attendees that signed up for the newsletter for import into our bulk mailer
    @csv_file
    def can_spam(self, out, session):
        out.writerow(["fullname", "email", "zipcode"])
        for a in session.query(Attendee).filter_by(can_spam=True).order_by('email').all():
            out.writerow([a.full_name, a.email, a.zip_code])

    # print out a CSV list of staffers (ignore can_spam for this since it's for internal staff mailing)
    @csv_file
    def staff_emails(self, out, session):
        out.writerow(["fullname", "email", "zipcode"])
        for a in session.query(Attendee).filter_by(staffing=True, placeholder=False).order_by('email').all():
            out.writerow([a.full_name, a.email, a.zip_code])

    @unrestricted
    def insert_test_admin(self, session):
        if session.insert_test_admin_account():
            msg = "Test admin account created successfully"
        else:
            msg = "Not allowed to create admin account at this time"

        raise HTTPRedirect('login?message={}', msg)

    @unrestricted
    def sitemap(self):
        site_sections = cherrypy.tree.apps[c.PATH].root
        modules = {name: getattr(site_sections, name) for name in dir(site_sections) if not name.startswith('_')}
        pages = defaultdict(list)
        for module_name, module_root in modules.items():
            for name in dir(module_root):
                method = getattr(module_root, name)
                if getattr(method, 'exposed', False):
                    spec = inspect.getfullargspec(get_innermost(method))
                    if set(getattr(method, 'restricted', []) or []).intersection(AdminAccount.access_set()) \
                            and (getattr(method, 'site_mappable', False)
                              or len([arg for arg in spec.args[1:] if arg != 'session']) == len(spec.defaults or []) and not spec.varkw):
                        pages[module_name].append({
                            'name': name.replace('_', ' ').title(),
                            'path': '/{}/{}'.format(module_name, name)
                        })
        return {'pages': sorted(pages.items())}

    @ajax
    def add_bulk_admin_accounts(self, session, message='', **params):
        ids = params.get('ids')
        if isinstance(ids, str):
            ids = str(ids).split(",")
        success_count = 0
        for id in ids:
            try:
                uuid.UUID(id)
            except ValueError:
                pass
            else:
                match = session.query(Attendee).filter(Attendee.id == id).first()
                if match:
                    account = session.admin_account(params, checkgroups=['access'])
                    if account.is_new:
                        password = genpasswd()
                        account.hashed = bcrypt.hashpw(password, bcrypt.gensalt())
                        account.attendee = match
                        session.add(account)
                        body = render('emails/accounts/new_account.txt', {
                            'account': account,
                            'password': password
                        })
                        send_email(c.ADMIN_EMAIL, match.email, 'New ' + c.EVENT_NAME + ' RAMS Account', body)

                        success_count += 1
        if success_count == 0:
            message = 'No new accounts were created.'
        else:
            session.commit()
            message = '%d new accounts have been created, and emailed their passwords.' % success_count
        return message
