import os
import json
import shlex
import time
import sys
import subprocess
import traceback
import csv
import random
import six
import pypsutil
import cherrypy
import threading
from datetime import datetime

from sqlalchemy.dialects.postgresql.json import JSONB
from pockets.autolog import log
from pytz import UTC
from sqlalchemy.types import Date, Boolean, Integer
from sqlalchemy import text

from uber.badge_funcs import badge_consistency_check
from uber.decorators import all_renderable, csv_file, public, site_mappable
from uber.models import Choice, MultiChoice, Session, DateTime
from uber.tasks.health import ping


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


def prepare_model_export(model, filtered_models=None):
    rows = []

    cols = [getattr(model, col.name) for col in model.__table__.columns]
    rows.append([col.name for col in cols])

    for model in filtered_models:
        row = []
        for col in cols:
            if isinstance(col.type, Choice):
                # Choice columns are integers with a single value with an automatic
                # _label property, e.g. the "shirt" column has a "shirt_label"
                # property, so we'll use that.
                row.append(getattr(model, col.name + '_label'))
            elif isinstance(col.type, MultiChoice):
                # MultiChoice columns are comma-separated integer lists with an
                # automatic _labels property which is a list of string labels.
                # So we'll get that and then separate the labels with slashes.
                row.append(' / '.join(getattr(model, col.name + '_labels')))
            elif isinstance(col.type, DateTime):
                # Use the empty string if this is null, otherwise use strftime.
                # Also you should fill in whatever actual format you want.
                val = getattr(model, col.name)
                row.append(val.strftime('%Y-%m-%d %H:%M:%S') if val else '')
            elif isinstance(col.type, JSONB):
                row.append(json.dumps(getattr(model, col.name)))
            else:
                # For everything else we'll just dump the value, although we might
                # consider adding more special cases for things like foreign keys.
                row.append(getattr(model, col.name))
        rows.append(row)
    return rows

def _get_thread_current_stacktrace(thread_stack, thread):
    out = []
    status = '[unknown]'
    if thread.native_id != -1:
        status = pypsutil.Process(thread.native_id).status().name
    out.append('\n--------------------------------------------------------------------------')
    out.append('# Thread name: "%s"\n# Python thread.ident: %d\n# Linux Thread PID (TID): %d\n# Run Status: %s'
                % (thread.name, thread.ident, thread.native_id, status))
    for filename, lineno, name, line in traceback.extract_stack(thread_stack):
        out.append('File: "%s", line %d, in %s' % (filename, lineno, name))
        if line:
            out.append('  %s' % (line.strip()))
    return out

def threading_information():
    out = []
    threads_by_id = dict([(thread.ident, thread) for thread in threading.enumerate()])
    for thread_id, thread_stack in sys._current_frames().items():
        thread = threads_by_id.get(thread_id, '')
        out += _get_thread_current_stacktrace(thread_stack, thread)
        if thread.native_id != -1:
            proc = pypsutil.Process(thread.native_id)
            out.append(f"Mem: {proc.memory_info().rss}")
            out.append(f"CPU: {proc.cpu_times().user}")
    return '\n'.join(out)

def general_system_info():
    """
    Print general system info
    TODO:
    - print memory nicer, convert mem to megabytes
    - disk partitions usage,
    - # of open file handles
    - # free inode count
    - # of cherrypy session files
    - # of cherrypy session locks (should be low)
    """
    out = []
    out += ['Mem: ' + repr(pypsutil.virtual_memory().used)]
    out += ['Swap: ' + repr(pypsutil.swap_memory().used)]
    return '\n'.join(out)

def database_pool_information():
    return Session.engine.pool.status()

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
        out = ''
        for func in [general_system_info, threading_information, database_pool_information]:
            out += '--------- {} ---------\n{}\n\n\n'.format(func.__name__.replace('_', ' ').upper(), func())
        return {
            'diagnostics_data': out,
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
            else:
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
                elif isinstance(col.type, DateTime):
                    # we'll need to make sure we use whatever format string we used to
                    # export this date in the first place
                    try:
                        val = UTC.localize(datetime.strptime(val, date_format + ' %H:%M:%S'))
                    except Exception:
                        val = UTC.localize(datetime.strptime(val, date_format))
                elif isinstance(col.type, Date):
                    val = datetime.strptime(val, date_format).date()
                elif isinstance(col.type, Choice):
                    val = col.type.convert_if_label(val)
                elif isinstance(col.type, MultiChoice):
                    val = col.type.convert_if_labels(val)
                elif isinstance(col.type, Integer):
                    val = int(val)
                elif isinstance(col.type, JSONB):
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
        rows = prepare_model_export(model, filtered_models=session.query(model).all())
        for row in rows:
            out.writerow(row)

    @public
    def health(self, session):
        cherrypy.response.headers["Access-Control-Allow-Origin"] = "*"
        cherrypy.session.load()

        read_count = cherrypy.session.get("read_count", default=0)
        read_count += 1
        cherrypy.session["read_count"] = read_count
        session_commit_time = -time.perf_counter()
        cherrypy.session.save()
        session_commit_time += time.perf_counter()

        db_read_time = -time.perf_counter()
        session.execute(text('SELECT 1'))
        db_read_time += time.perf_counter()

        if os.environ.get("ENABLE_CELERY", "true").lower() == "true":
            payload = random.randrange(1024)
            task_run_time = -time.perf_counter()
            response = ping.delay(payload).wait(timeout=2)
            task_run_time += time.perf_counter()
        else:
            task_run_time = 0
            payload = "Not Run, ENABLE_CELERY != true"
            response = "Not Run, ENABLE_CELERY != true"

        return json.dumps({
            'server_current_timestamp': int(datetime.utcnow().timestamp()),
            'session_read_count': read_count,
            'session_commit_time': session_commit_time,
            'db_read_time': db_read_time,
            'db_status': Session.engine.pool.status(),
            'task_run_time': task_run_time,
            'task_response_correct': payload == response,
            'task_payload': payload,
            'task_response': response,
        })
