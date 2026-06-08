import os
from glob import glob

import pytest
import sqlite3
from jinja2 import meta
from sqlalchemy.schema import CreateTable, MetaData

from uber.jinja import JinjaEnv
from uber.models import Session
from uber.sep_commands import alembic, drop_uber_db, reset_uber_db


def sort_lines(text, to_strip=' ', uniquify=True):
    lines = [s.strip(to_strip) for s in text.split('\n') if s.strip(to_strip)]
    if uniquify:
        lines = set(lines)
    return '\n'.join(sorted(lines))


def dump_schema(sort=True, uniquify=True):
    with Session.engine.connect() as connection:
        meta = MetaData()
        meta.reflect(bind=connection)
        tables = meta.sorted_tables if sort else meta.tables.values()
        table_statements = []
        for table in tables:
            table_statement = str(CreateTable(table))
            if sort:
                table_statement = sort_lines(table_statement, ', ', uniquify)
            table_statements.append(table_statement)
        return '\n'.join(table_statements)
    return ''


def dump_alembic_schema(sort=True, uniquify=True):
    if Session.engine.dialect.name == 'sqlite' and sqlite3.sqlite_version_info < (3, 8, 3):
        pytest.skip('requires recent version of sqlite')
    drop_uber_db()
    alembic('upgrade', 'heads')
    return dump_schema(sort, uniquify)


def dump_reset_uber_db_schema(sort=True, uniquify=True):
    reset_uber_db()
    return dump_schema(sort, uniquify)


def guess_template_dirs(file_path):
    if not file_path:
        return []

    current_path = os.path.abspath(os.path.expanduser(file_path))
    while current_path != '/':
        template_dir = os.path.join(current_path, 'templates')
        if os.path.exists(template_dir):
            return [template_dir]
        current_path = os.path.normpath(os.path.join(current_path, '..'))
    return []


def collect_template_paths(file_path):
    template_dirs = guess_template_dirs(file_path)
    template_paths = []
    for template_dir in template_dirs:
        for root, _, _ in os.walk(template_dir):
            for ext in ('html', 'htm', 'txt'):
                file_pattern = '*.{}'.format(ext)
                template_paths.extend(glob(os.path.join(root, file_pattern)))

    return template_paths


def is_valid_jinja_template(template_path):
    env = JinjaEnv.env()
    with open(template_path) as template_file:
        template = template_file.read()
        ast = env.parse(template)
        meta.find_undeclared_variables(ast)
