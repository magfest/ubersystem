from uber.config import c
from uber.errors import HTTPRedirect
from uber.decorators import all_renderable, ajax
from uber.models import GuestGroup
from uber.site_sections.registration import create_new_account


@all_renderable()
class Root:
    def index(self, session, message=''):
        HTTPRedirect('../group_admin/index#guests?message={}', message)

    @ajax
    def open_checklist(self, session, group_type):
        group_type = int(group_type)
        guest_groups = session.query(GuestGroup).filter(GuestGroup.group_type == group_type)
        for guest in guest_groups:
            if guest.group and guest.group.leader:
                attendee = guest.group.leader
                session.add(attendee)
                if not attendee.managers and attendee.email and (not attendee.has_sso_email or c.LOCAL_ACCOUNTS_DISABLED):
                    create_new_account(session, attendee)
        session.commit()
        return {'success': True, 'message': f"Badge claim and checklist email sent for the {c.GROUP_TYPES[group_type]} checklist."}
