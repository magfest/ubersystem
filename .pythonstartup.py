import readline
import traceback

readline.parse_and_bind('tab: complete')

try:
    import cherrypy
    from uber.config import c
    from uber.models import AdminAccount, Attendee, initialize_db, Session

    initialize_db()

    # Make it easier to do session stuff at the command line
    session = Session()

    if c.DEV_BOX:
        admin = session.query(AdminAccount).filter(
            AdminAccount.attendee_id == Attendee.id,
            Attendee.email == 'magfest@example.com'
        ).order_by(AdminAccount.id).first()

        if admin:
            # Make it easier to do site section testing at the command line
            cherrypy.session = {'account_id': admin.id}
            print('Logged in as {} <{}>'.format(admin.attendee.full_name, admin.attendee.email))
        else:
            print('INFO: Could not find Test Developer admin account')

except Exception as ex:
    print('ERROR: Could not initialize ubersystem environment')
    traceback.print_exc()