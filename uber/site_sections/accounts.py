from uber.common import *

def valid_password(password, account):
    pr = account.password_reset
    if pr and pr.is_expired:
        account.session.delete(pr)
        pr = None

    all_hashed = [account.hashed] + ([pr.hashed] if pr else [])
    return any(bcrypt.hashpw(password, hashed) == hashed for hashed in all_hashed)

@all_renderable(ACCOUNTS)
class Root:
    def index(self, session, message=''):
        return {
            'message':  message,
            'accounts': session.query(AdminAccount).join(Attendee)
                               .order_by(Attendee.first_name, Attendee.last_name).all(),
            'all_attendees': [{
                'id': a.id,
                'text': '{a.full_name} - {a.badge}'.format(a=a)
            } for a in session.query(Attendee).filter(Attendee.email != '').all()]
        }

    def update(self, session, password='', **params):
        account = session.admin_account(params, checkgroups=['access'])
        if account.is_new:
            password = password if AT_THE_CON else genpasswd()
            account.hashed = bcrypt.hashpw(password, bcrypt.gensalt())

        message = check(account)
        if not message:
            message = 'Account settings uploaded'
            if account.is_new and not AT_THE_CON:
                body = render('accounts/new_email.txt', {
                    'account': account,
                    'password': password
                })
                send_email(ADMIN_EMAIL, account.attendee.email, 'New MAGFest Ubersystem Account', body)
                session.add(account)

        raise HTTPRedirect('index?message={}', message)

    def delete(self, session, id):
        session.delete(session.admin_account(id))
        raise HTTPRedirect('index?message={}', 'Account deleted')

    @unrestricted
    def login(self, session, message='', **params):
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
                raise HTTPRedirect('homepage')

        return {
            'message': message,
            'email':   params.get('email', '')
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
                session.add(PasswordReset(account=account, hashed=bcrypt.hashpw(password, bcrypt.gensalt())))
                body = render('accounts/reset_email.txt', {
                    'name': account.attendee.full_name,
                    'password':  password
                })
                send_email(ADMIN_EMAIL, account.attendee.email, 'MAGFest Admin Password Reset', body)
                raise HTTPRedirect('login?message={}', 'Your new password has been emailed to you')

        return {
            'email':   email,
            'message': message
        }

    @unrestricted
    def change_password(self, session, message='', old_password=None, new_password=None, csrf_token=None):
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

    @unrestricted
    def sitemap(self):
        from uber import site_sections
        modules = {name: getattr(site_sections, name) for name in dir(site_sections) if not name.startswith('_')}
        pages = defaultdict(list)
        for module_name, module in modules.items():
            for name in dir(module.Root):
                method = getattr(module.Root, name)
                if getattr(method, 'exposed', False):
                    spec = inspect.getfullargspec(method._orig)
                    if set(method.restricted or []).intersection(AdminAccount.access_set()) \
                            and (getattr(method, 'site_mappable', False)
                              or len([arg for arg in spec.args[1:] if arg != 'session']) == len(spec.defaults or []) and not spec.varkw):
                        pages[module_name].append({
                            'name': name.replace('_', ' ').title(),
                            'path': '/{}/{}'.format(module_name, name)
                        })

        if PEOPLE in AdminAccount.access_set():
            for dept,desc in JOB_LOC_OPTS:
                pages['hotel assignments'].append({
                    'name': desc,
                    'path': '/hotel/assignments?department={}'.format(dept)
                })

        return {'pages': sorted(pages.items())}
