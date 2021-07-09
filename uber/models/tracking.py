import json
import sys
from datetime import datetime
from threading import current_thread
from urllib.parse import parse_qsl

import cherrypy
from pytz import UTC
from sqlalchemy.ext import associationproxy

from pockets.autolog import log
from residue import CoerceUTF8 as UnicodeText, UTCDateTime, UUID
from sideboard.lib import serializer

from uber.config import c
from uber.models import MagModel
from uber.models.admin import AdminAccount
from uber.models.email import Email
from uber.models.types import Choice, DefaultColumn as Column, MultiChoice

__all__ = ['PageViewTracking', 'Tracking']

serializer.register(associationproxy._AssociationList, list)


class PageViewTracking(MagModel):
    when = Column(UTCDateTime, default=lambda: datetime.now(UTC))
    who = Column(UnicodeText)
    page = Column(UnicodeText)
    what = Column(UnicodeText)

    @classmethod
    def track_pageview(cls):
        url, query = cherrypy.request.path_info, cherrypy.request.query_string
        # Track any views of the budget pages
        if "budget" in url:
            what = "Budget page"
        else:
            # Only log the page view if there's a valid attendee ID
            params = dict(parse_qsl(query))
            if 'id' not in params or params['id'] == 'None':
                return

            # Looking at an attendee's details
            if "registration" in url or "attendee" in url:
                what = "Attendee id={}".format(params['id'])
            # Looking at a group's details
            elif "dealer_admin" in url or "group" in url:
                what = "Group id={}".format(params['id'])

        from uber.models import Session
        with Session() as session:
            session.add(PageViewTracking(who=AdminAccount.admin_name(), page=c.PAGE_PATH, what=what))


class Tracking(MagModel):
    fk_id = Column(UUID, index=True)
    model = Column(UnicodeText)
    when = Column(UTCDateTime, default=lambda: datetime.now(UTC))
    who = Column(UnicodeText)
    page = Column(UnicodeText)
    which = Column(UnicodeText)
    links = Column(UnicodeText)
    action = Column(Choice(c.TRACKING_OPTS))
    data = Column(UnicodeText)
    snapshot = Column(UnicodeText)

    @classmethod
    def format(cls, values):
        return ', '.join('{}={}'.format(k, v) for k, v in values.items())

    @classmethod
    def repr(cls, column, value):
        try:
            if column.name == 'hashed':
                return '<bcrypted>'
            elif getattr(column, 'private', None):
                return '<private>'
            elif isinstance(column.type, MultiChoice):
                if not value:
                    return ''
                opts = dict(column.type.choices)
                value_opts = map(lambda s: int(s or 0), str(value).split(','))
                return repr(','.join(opts[i] for i in value_opts if i in opts))
            elif isinstance(column.type, Choice) and value not in [None, '']:
                opts = dict(column.type.choices)
                return repr(opts.get(int(value), '<nonstandard>'))
            else:
                return repr(value)
        except Exception as e:
            raise ValueError('Error formatting {} ({!r})'.format(column.name, value)) from e

    @classmethod
    def differences(cls, instance):
        diff = {}
        for attr, column in instance.__table__.columns.items():
            new_val = getattr(instance, attr)
            old_val = instance.orig_value_of(attr)
            if old_val != new_val:
                """
                Important note: here we try and show the old vs new value for
                something that has been changed so that we can report it in the
                tracking page.

                Sometimes, however, if we changed the type of the value in the
                database (via a database migration) the old value might not be
                able to be shown as the new type (i.e. it used to be a string,
                now it's int).

                In that case, we won't be able to show a representation of the
                old value and instead we'll log it as '<ERROR>'. In theory the
                database migration SHOULD be the thing handling this, but if it
                doesn't, it becomes our problem to deal with.

                We are overly paranoid with exception handling here because the
                tracking code should be made to never, ever, ever crash, even
                if it encounters insane/old data that really shouldn't be our
                problem.
                """
                try:
                    old_val_repr = cls.repr(column, old_val)
                except Exception:
                    log.error('Tracking repr({}) failed on old value'.format(attr), exc_info=True)
                    old_val_repr = '<ERROR>'

                try:
                    new_val_repr = cls.repr(column, new_val)
                except Exception:
                    log.error('Tracking repr({}) failed on new value'.format(attr), exc_info=True)
                    new_val_repr = '<ERROR>'

                diff[attr] = "'{} -> {}'".format(old_val_repr, new_val_repr)
        return diff

    @classmethod
    def track(cls, action, instance):
        if action in [c.CREATED, c.UNPAID_PREREG, c.EDITED_PREREG]:
            vals = {
                attr: cls.repr(column, getattr(instance, attr))
                for attr, column in instance.__table__.columns.items()}
            data = cls.format(vals)
        elif action == c.UPDATED:
            diff = cls.differences(instance)
            data = cls.format(diff)
            if len(diff) == 1 and 'badge_num' in diff:
                action = c.AUTO_BADGE_SHIFT
            elif not data:
                return
        else:
            data = 'id={}'.format(instance.id)

        links = ', '.join(
            '{}({})'.format(list(column.foreign_keys)[0].column.table.name, getattr(instance, name))
            for name, column in instance.__table__.columns.items() if column.foreign_keys and getattr(instance, name))

        if sys.argv == ['']:
            who = 'server admin'
        else:
            who = AdminAccount.admin_name() or (current_thread().name if current_thread().daemon else 'non-admin')
            
        try:
            snapshot = json.dumps(instance.to_dict(), cls=serializer)
        except TypeError as e:
            snapshot = "(Could not save JSON dump due to error: {}".format(e)

        def _insert(session):
            session.add(Tracking(
                model=instance.__class__.__name__,
                fk_id=instance.id,
                which=repr(instance),
                who=who,
                page=c.PAGE_PATH,
                links=links,
                action=action,
                data=data,
                snapshot=snapshot,
            ))
        if instance.session:
            _insert(instance.session)
        else:
            from uber.models import Session
            with Session() as session:
                _insert(session)


Tracking.UNTRACKED = [Tracking, Email, PageViewTracking]
