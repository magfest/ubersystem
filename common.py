# TODO: less repitition for attendees/groups and attendees/jobs/shifts
# TODO: method for sending a reminder but not after a deadline
# TODO: template tag or something for deadline formatting
# TODO: room ordering prioritizes groupings based on same nights
# TODO: MPointUse needs a better name, and is confusing with MPointExchange
# TODO: jsonify undo ajax methods
# TODO: make all payment reminders based on due date instead of registration date
# TODO: decorator for downloading attachments
# TODO: weighted hours which are NOT worked should be listed in red on the shifts page hour total
# TODO: badge number searches are exact and bring up the attendee form even at the con

import os
import re
import csv
import sys
import json
import math
import socket
import logging
import warnings
import traceback
from glob import glob
from uuid import uuid4
from io import StringIO
from pprint import pformat
from hashlib import sha512
from functools import wraps
from xml.dom import minidom
from random import randrange
from itertools import groupby
from time import sleep, mktime
from urllib.request import urlopen
from urllib.parse import quote, parse_qsl
from collections import defaultdict, OrderedDict
from datetime import date, time, datetime, timedelta
from logging import DEBUG, INFO, WARNING, ERROR, CRITICAL
from threading import Thread, RLock, local, current_thread


import logging_unterpolation
logging_unterpolation.patch_logging()

with warnings.catch_warnings():
    warnings.simplefilter("ignore", DeprecationWarning)
    import MySQLdb

import bcrypt
import cherrypy
import django.conf
from boto.ses.connection import SESConnection

import constants
from constants import *
from config import *

from django import template
from django.db import connection
from django.db.models import base
from django.dispatch import receiver
from django.utils.safestring import SafeString
from django.db.models.signals import pre_save, post_save, pre_delete
from django.template import loader, Context, Variable, TemplateSyntaxError
from django.db.models import Q, Avg, Sum, Count, Model, ForeignKey, OneToOneField, BooleanField, CharField, TextField, IntegerField, FloatField, DateField, DateTimeField, CommaSeparatedIntegerField


class HTTPRedirect(cherrypy.HTTPRedirect):
    def __init__(self, page, *args, **kwargs):
        args = [self.quote(s) for s in args]
        kwargs = {k:self.quote(v) for k,v in kwargs.items()}
        cherrypy.HTTPRedirect.__init__(self, page.format(*args, **kwargs))
    
    def quote(self, s):
        return quote(s) if isinstance(s, str) else str(s)


def listify(x):
    return x if isinstance(x, (list,tuple,set,frozenset)) else [x]


def get_model(klass, params, bools=[], checkgroups=[], allowed=[], restricted=False, ignore_csrf=False):
    params = params.copy()
    id = params.pop("id", "None")
    if id == "None":
        model = klass()
    elif str(id).isdigit():
        model = klass.objects.get(id = id)
    else:
        model = klass.objects.get(secret_id = id)
    
    assert not {k for k in params if k not in allowed} or cherrypy.request.method == "POST", "POST required"
    
    for field in klass._meta.fields:
        if restricted and field.name in klass.restricted:
            continue
        
        id_param = field.name + "_id"
        if isinstance(field, (ForeignKey, OneToOneField)) and id_param in params:
            setattr(model, id_param, params[id_param])
        
        elif field.name in params and field.name != "id":
            if isinstance(params[field.name], list):
                value = ",".join(params[field.name])
            elif isinstance(params[field.name], bool):
                value = params[field.name]
            else:
                value = str(params[field.name]).strip()
            
            try:
                if isinstance(field, IntegerField):
                    value = int(float(value))
                elif isinstance(field, DateTimeField):
                    value = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
            except:
                pass
            
            setattr(model, field.name, value)
    
    if cherrypy.request.method.upper() == "POST":
        for field in klass._meta.fields:
            if field.name in bools:
                setattr(model, field.name, field.name in params and bool(int(params[field.name])))
            elif field.name in checkgroups and field.name not in params:
                setattr(model, field.name, "")
        
        if not ignore_csrf:
            check_csrf(params.get("csrf_token"))
    
    return model

def check_csrf(csrf_token):
    assert csrf_token, "CSRF token missing"
    assert csrf_token == cherrypy.session["csrf_token"], "CSRF token does not match"

def check(model):
    prefix = model.__class__.__name__.lower() + "_"
    
    for field,name in getattr(model_checks, prefix + "required", []):
        if not str(getattr(model,field)).strip():
            return name + " is a required field"
    
    for name,attr in model_checks.__dict__.items():
        if name.startswith(prefix) and hasattr(attr, "__call__"):
            message = attr(model)
            if message:
                return message


class Order:
    def __init__(self, order):
        self.order = order
    
    def __getitem__(self, field):
        return ("-" + field) if field==self.order else field
    
    def __str__(self):
        return self.order


def assign(attendee_id, job_id):
    job = Job.objects.get(id=job_id)
    attendee = Attendee.objects.get(id = attendee_id)
    
    if job.restricted and not attendee.trusted:
        return "Not eligible (this message should never be seen)"
    
    if job.slots <= job.shift_set.count():
        return "All slots for this job have already been filled"
    
    if not job.no_overlap(attendee):
        return "Staffer is already signed up for a shift during that time"
    
    Shift.objects.create(attendee=attendee, job=job)


def hour_day_format(dt):
    return dt.strftime("%I%p ").strip("0").lower() + dt.strftime("%a")


def send_email(source, dest, subject, body, format = "text", cc = [], bcc = [], model = None):
    dest, cc, bcc = map(listify, [dest, cc, bcc])
    if DEV_BOX:
        for xs in [dest, cc, bcc]:
            xs[:] = [email for email in xs if email.endswith("mailinator.com")]
    
    if model:
        fk = {"fk_id": 0, "model": "n/a"} if model == "n/a" else {"fk_id": model.id, "model": model.__class__.__name__}
        Email.objects.create(subject = subject, dest = dest, body = body, **fk)
    
    if state.SEND_EMAILS and dest:
        SESConnection(AWS_ACCESS_KEY_ID, AWS_SECRET_KEY).send_email(
            subject = subject,
            body = body,
            source = source,
            to_addresses = dest,
            cc_addresses = cc,
            bcc_addresses = bcc,
            format = format,
            return_path = source
        )
    else:
        log.error("email sending turned off, so unable to send {}", locals())


# this is here instead of in badge_funcs.py for import simplicity
def check_range(badge_num, badge_type):
    try:
        badge_num = int(badge_num)
    except:
        return "'{}' is not a valid badge number (should be an integer)".format(badge_num)
    
    if badge_num:
        min_num, max_num = BADGE_RANGES[int(badge_type)]
        if not min_num <= badge_num <= max_num:
            return "{} badge numbers must fall within the range {} - {}".format(dict(BADGE_OPTS)[badge_type], min_num, max_num)



def affiliates(exclude={"paid":NOT_PAID}):
    db = Attendee.objects.exclude(**exclude).values_list("affiliate", flat=True).distinct()
    aff = DEFAULT_AFFILIATES + [a for a in db if a and a not in DEFAULT_AFFILIATES]
    return [(a,a) for a in aff]



def get_page(page, queryset):
    return queryset[(int(page) - 1) * 100 : int(page) * 100]



def daemonize(func, name="DaemonTask", interval=300, threads=1):
    def wrapped():
        while True:
            try:
                func()
            except:
                log.warning("ignoring unexpected error in background thread {!r}", current_thread().name, exc_info = True)
            
            if interval:
                sleep(interval)
    
    for i in range(threads):
        t = Thread(target = wrapped, name = name)
        t.daemon = True
        t.start()


# These imports are last so they can import everything from this module.  Don't move or reorder them.
from decorators import *
from models import *
from badge_funcs import *
import model_checks
import custom_tags
template.builtins.append(register)
from site_sections.emails import Reminder
import main
