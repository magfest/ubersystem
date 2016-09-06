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
            if c.AT_THE_CON and not password:
                message = 'You must enter a password'
            else:
                password = password if c.AT_THE_CON else genpasswd()
                account.hashed = bcrypt.hashpw(password, bcrypt.gensalt())

        message = message or check(account)
        if not message:
            message = 'Account settings uploaded'
            account.attendee = session.attendee(account.attendee_id)   # dumb temporary hack, will fix later with tests
            session.add(account)
            if account.is_new and not c.AT_THE_CON:
                body = render('emails/accounts/new_account.txt', {
                    'account': account,
                    'password': password
                })
                send_email(c.ADMIN_EMAIL, session.attendee(account.attendee_id).email, 'New ' + c.EVENT_NAME + ' Ubersystem Account', body)

        raise HTTPRedirect('index?message={}', message)

    def delete(self, session, id, **params):
        session.delete(session.admin_account(id))
        raise HTTPRedirect('index?message={}', 'Account deleted')

    def reset_password(self, session, password, id, **params):
        if password != '' and id != '':
            account = session.query(AdminAccount).filter(AdminAccount.id == id).first()
            if account is not None:
                account.hashed = bcrypt.hashpw(password, bcrypt.gensalt())

    @unrestricted
    def login(self, session, message='', original_location=None, **params):
        if not original_location or 'login' in original_location:
            original_location = 'homepage'

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

