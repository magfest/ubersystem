import os
import json
import shlex
import subprocess
import csv
import urllib
import six
from datetime import datetime

from sideboard.debugging import register_diagnostics_status_function, gather_diagnostics_status_information
from sqlalchemy.dialects.postgresql.json import JSONB
from pockets.autolog import log
from pytz import UTC
from sqlalchemy.types import Date, Boolean, Integer

from uber.badge_funcs import badge_consistency_check
from uber.config import c, _config
from uber.decorators import all_renderable, csv_file, set_csv_filename, site_mappable
from uber.models import Choice, MultiChoice, Session, UTCDateTime


# admin utilities.  should not be used during normal ubersystem operations except by developers / sysadmins


# quick n dirty. don't use for anything real.
def run_shell_cmd(command_line, working_dir=None):
    args = shlex.split(command_line)
    p = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=working_dir)
    out, err = p.communicate()
    return out


def run_git_cmd(cmd):
    git = "/usr/bin/git"
    uber_base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
    return run_shell_cmd(git + " " + cmd, working_dir=uber_base_dir)


@all_renderable()
class Root:
    def index(self):
        return {}

    # this is quick and dirty.
    # print out some info relevant to developers such as what the current version of ubersystem this is,
    # which branch it is, etc.
    def gitinfo(self):
        git_branch_name = run_git_cmd("rev-parse --abbrev-ref HEAD")
        git_current_sha = run_git_cmd("rev-parse --verify HEAD")
        last_commit_log = run_git_cmd("show --name-status")
        git_status = run_git_cmd("status")

        return {
            'git_branch_name': git_branch_name,
            'git_current_sha': git_current_sha,
            'last_commit_log': last_commit_log,
            'git_status': git_status
        }

    def dump_diagnostics(self):
        return {
            'diagnostics_data': gather_diagnostics_status_information(),
        }

    def badge_number_consistency_check(self, session, run_check=None):
        errors = []

        if run_check:
            errors = badge_consistency_check(session)

        return {
            'errors_found': len(errors) > 0,
            'errors': errors,
            'ran_check': run_check,
        }

    def csv_import(self, message='', all_instances=None):
        return {
            'message': message,
            'tables': sorted(model.__name__ for model in Session.all_models()),
            'attendees': all_instances
        }

    def import_model(self, session, model_import, selected_model='', date_format="%Y-%m-%d"):
        model = Session.resolve_model(selected_model)
        message = ''

        cols = {col.name: getattr(model, col.name) for col in model.__table__.columns}
        result = csv.DictReader(model_import.file.read().decode('utf-8').split('\n'))
        id_list = []

        for row in result:
            if 'id' in row:
                id = row.pop('id')  # id needs special treatment

                try:
                    # get the instance if it already exists
                    model_instance = getattr(session, selected_model)(id, allow_invalid=True)
                except Exception:
                    session.rollback()
                    # otherwise, make a new one and add it to the session for when we commit
                    model_instance = model()
                    session.add(model_instance)

            for colname, val in row.items():
                col = cols[colname]
                if not val:
                    # in a lot of cases we'll just have the empty string, so we'll just
                    # do nothing for those cases
                    continue
                if isinstance(col.type, Boolean):
                    if isinstance(val, six.string_types):
                        val = val.strip().lower() not in ('f', 'false', 'n', 'no', '0')
                    else:
                        val = bool(val)
                elif isinstance(col.type, UTCDateTime):
                    # we'll need to make sure we use whatever format string we used to
                    # export this date in the first place
                    try:
                        val = UTC.localize(datetime.strptime(val, date_format + ' %H:%M:%S'))
                    except Exception:
                        val = UTC.localize(datetime.strptime(val, date_format))
                elif isinstance(col.type, Date):
                    val = datetime.strptime(val, date_format).date()
                elif isinstance(col.type, Integer):
                    val = int(val)
                elif isinstance(col.type, JSONB):
                    val = val.replace("'", '"') # Temporary fix for Access Groups -- remove after SuperMAG 2021
                    val = json.loads(val)

                # now that we've converted val to whatever it actually needs to be, we
                # can just set it on the model
                setattr(model_instance, colname, val)

            try:
                session.commit()
            except Exception:
                log.error('ImportError', exc_info=True)
                session.rollback()
                message = 'Import unsuccessful'

            id_list.append(model_instance.id)

        all_instances = session.query(model).filter(model.id.in_(id_list)).all() if id_list else None

        return self.csv_import(message, all_instances)

    @site_mappable
    def csv_export(self, message='', **params):
        if 'model' in params:
            self.export_model(selected_model=params['model'])

        return {
            'message': message,
            'tables': sorted(model.__name__ for model in Session.all_models())
        }

    @csv_file
    def export_model(self, out, session, selected_model=''):
        model = Session.resolve_model(selected_model)

        cols = [getattr(model, col.name) for col in model.__table__.columns]
        out.writerow([col.name for col in cols])

        for attendee in session.query(model).all():
            row = []
            for col in cols:
                if isinstance(col.type, Choice):
                    # Choice columns are integers with a single value with an automatic
                    # _label property, e.g. the "shirt" column has a "shirt_label"
                    # property, so we'll use that.
                    row.append(getattr(attendee, col.name + '_label'))
                elif isinstance(col.type, MultiChoice):
                    # MultiChoice columns are comma-separated integer lists with an
                    # automatic _labels property which is a list of string labels.
                    # So we'll get that and then separate the labels with slashes.
                    row.append(' / '.join(getattr(attendee, col.name + '_labels')))
                elif isinstance(col.type, UTCDateTime):
                    # Use the empty string if this is null, otherwise use strftime.
                    # Also you should fill in whatever actual format you want.
                    val = getattr(attendee, col.name)
                    row.append(val.strftime('%Y-%m-%d %H:%M:%S') if val else '')
                elif isinstance(col.type, JSONB):
                    row.append(json.dumps(getattr(attendee, col.name)))
                else:
                    # For everything else we'll just dump the value, although we might
                    # consider adding more special cases for things like foreign keys.
                    row.append(getattr(attendee, col.name))
            out.writerow(row)


@register_diagnostics_status_function
def database_pool_information():
    return Session.engine.pool.status()
