from uber.common import *


@all_renderable(c.PEOPLE)
class Root:

    def index(self, session, message=''):

        departments = session.query(Department).order_by(Department.name).all()

        return {
            'message': message,
            'departments': departments
        }

    def form(self, session, message='', **params):
        if not params.get('id'):
            raise HTTPRedirect('index')

        if cherrypy.request.method == 'POST':
            department = session.department(
                params,
                bools=Department.all_bools,
                checkgroups=Department.all_checkgroups)
            session.add(department)
            raise HTTPRedirect('form?id={}', department.id)

        department = session.department(params.get('id'))

        return {
            'admin': session.admin_attendee(),
            'message': message,
            'department': department
        }
