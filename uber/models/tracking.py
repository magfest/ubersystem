import json
import sys
import logging
from datetime import datetime
from markupsafe import Markup
from threading import current_thread
from urllib.parse import parse_qsl

import cherrypy
from pytz import UTC
from sqlalchemy.ext import associationproxy

from sqlalchemy import Sequence
from sqlalchemy.types import Boolean, Integer, DateTime, String, Uuid
from sqlalchemy.dialects.postgresql.json import JSONB
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.orm.exc import NoResultFound
from sqlmodel import Field, Relationship
from typing import Any, ClassVar

from uber.serializer import serializer
from uber.config import c
from uber.decorators import presave_adjustment
from uber.models import MagModel
from uber.models.admin import AdminAccount
from uber.models.email import Email
from uber.models.types import Choice, DefaultColumn as Column, MultiChoice, utcnow

log = logging.getLogger(__name__)

__all__ = ['PageViewTracking', 'ReportTracking', 'Tracking', 'TxnRequestTracking']

serializer.register(associationproxy._AssociationList, list)


class ReportTracking(MagModel, table=True):
    when: datetime = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    who: str = Column(String)
    supervisor: str = Column(String)
    page: str = Column(String)
    params: dict[str, Any] = Field(sa_type=MutableDict.as_mutable(JSONB), default_factory=dict)

    @property
    def who_repr(self):
        if self.supervisor:
            return Markup(f'{self.who};<br/>{self.supervisor} (Supervisor)')
        return self.who

    @classmethod
    def track_report(cls, params):
        from uber.models import Session
        with Session() as session:
            session.add(ReportTracking(who=AdminAccount.admin_or_volunteer_name(),
                                       supervisor=AdminAccount.supervisor_name() or '',
                                       page=c.PAGE_PATH,
                                       params={key: val for key, val in params.items()
                                               if key not in ['self', 'out', 'session']}))
            session.commit()


class PageViewTracking(MagModel, table=True):
    when: datetime = Field(default_factory=lambda: datetime.now(UTC), sa_column=Column(DateTime(timezone=True)))
    who: str = ''
    supervisor: str = ''
    page: str = ''
    which: str = ''

    @property
    def who_repr(self):
        if self.supervisor:
            return Markup(f'{self.who};<br/>{self.supervisor} (Supervisor)')
        return self.who

    @classmethod
    def track_pageview(cls):
        url, query = cherrypy.request.path_info, cherrypy.request.query_string
        params = dict(parse_qsl(query))
        # Track any views of the budget pages
        if "budget" in url:
            which = "Budget page"
        else:
            # Only log the page view if there's a valid model ID
            if 'id' not in params or params['id'] in [None, '', 'None']:
                return

            from uber.models import Session
            with Session() as session:
                # Get instance repr
                model = None
                id = params.get('id')
                try:
                    model = session.attendee(id)
                except NoResultFound:
                    try:
                        model = session.group(id)
                    except NoResultFound:
                        try:
                            model = session.art_show_application(id)
                        except NoResultFound:
                            pass
                if model:
                    which = repr(model)
                else:
                    return

            session.add(PageViewTracking(
                who=AdminAccount.admin_or_volunteer_name(),
                supervisor=AdminAccount.supervisor_name() or '',
                page=c.PAGE_PATH, which=which))
            session.commit()


class Tracking(MagModel, table=True):
    fk_id: str = Column(Uuid(as_uuid=False), index=True)
    model: str = Column(String)
    when: datetime = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), index=True)
    who: str = Column(String, index=True)
    supervisor: str = Column(String)
    page: str = Column(String)
    which: str = Column(String)
    links: str = Column(String)
    action: int = Column(Choice(c.TRACKING_OPTS))
    data: str = Column(String)
    snapshot: str = Column(String)

    @property
    def who_repr(self):
        if self.supervisor:
            return Markup(f'{self.who};<br/>{self.supervisor} (Supervisor)')
        return self.who

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
                return repr(','.join(str(opts.get(i, opts.get(str(i), f"Unknown ({i})"))) for i in value_opts))
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
            if attr in ['last_updated', 'last_synced', 'inventory_updated', 'unapproved_count']:
                continue

            if attr in ['currently_sending', 'last_send_time']:
                return {}

            new_val = getattr(instance, attr)
            if new_val:
                new_val = instance.coerce_column_data(column, new_val)
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
    def track_collection_change(cls, action, target, instance):
        from uber.models import Session
        if sys.argv == ['']:
            who = 'server admin'
        else:
            who = AdminAccount.admin_or_volunteer_name() or (current_thread().name if current_thread().daemon else 'non-admin')

        with Session() as session:
            session.add(Tracking(
                model=target.__class__.__name__,
                fk_id=target.id,
                which=repr(target),
                who=who,
                supervisor=AdminAccount.supervisor_name() or '',
                page=c.PAGE_PATH,
                action=action,
                data=repr(instance),
            ))

    @classmethod
    def track(cls, action, instance):
        from uber.models import ApiJob

        if action in [c.CREATED, c.UNPAID_PREREG, c.EDITED_PREREG]:
            vals = {
                attr: cls.repr(column, getattr(instance, attr))
                for attr, column in instance.__table__.columns.items()}
            data = cls.format(vals)
        elif action == c.UPDATED:
            diff = cls.differences(instance)
            data = cls.format(diff)
            if not data:
                return
        else:
            data = 'id={}'.format(instance.id)

        links = ', '.join(
            '{}({})'.format(list(column.foreign_keys)[0].column.table.name, getattr(instance, name))
            for name, column in instance.__table__.columns.items() if column.foreign_keys
            and 'creator' not in str(column)
            and getattr(instance, name))

        if sys.argv == ['']:
            who = 'server admin'
        else:
            who = AdminAccount.admin_or_volunteer_name() or (current_thread().name if current_thread().daemon else 'non-admin')
        
        if isinstance(instance, ApiJob) and who == 'non-admin':
            # Automated processing of API jobs is tracked in the jobs themselves
            # Skipping these logs saves us tens of thousands of extra rows
            return

        try:
            dict = instance.to_dict()
            dict.pop('receipt_changes', None)
            snapshot = json.dumps(dict, cls=serializer)
        except TypeError as e:
            snapshot = "Could not save JSON dump due to error: {}".format(e)

        def _insert(session):
            session.add(Tracking(
                model=instance.__class__.__name__,
                fk_id=instance.id,
                which=repr(instance),
                who=who,
                supervisor=AdminAccount.supervisor_name() or '',
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


class TxnRequestTracking(MagModel, table=True):
    incr_id_seq: ClassVar = Sequence('txn_request_tracking_incr_id_seq')
    incr_id: int = Column(Integer, incr_id_seq, server_default=incr_id_seq.next_value(), unique=True)
    fk_id: str | None = Column(Uuid(as_uuid=False), nullable=True)
    workstation_num: int = Column(Integer, default=0)
    terminal_id: str = Column(String)
    who: str = Column(String)
    requested: datetime = Column(DateTime(timezone=True), server_default=utcnow(), default=lambda: datetime.now(UTC))
    resolved: datetime | None = Column(DateTime(timezone=True), nullable=True)
    success: bool = Column(Boolean, default=False)
    response: dict[Any, Any] = Field(sa_type=MutableDict.as_mutable(JSONB), default_factory=dict)
    internal_error: str = Column(String)

    @presave_adjustment
    def log_internal_error(self):
        if self.internal_error and not self.orig_value_of('internal_error'):
            c.REDIS_STORE.hset(c.REDIS_PREFIX + 'spin_terminal_txns:' + self.terminal_id,
                               'last_error',
                               self.internal_error)


Tracking.UNTRACKED = [Tracking, Email, PageViewTracking, ReportTracking, TxnRequestTracking]
