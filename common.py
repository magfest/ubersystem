# TODO: room ordering prioritizes groupings based on same nights
# TODO: MPointUse needs a better name, and is confusing with MPointExchange
# TODO: weighted hours which are NOT worked should be listed in red on the shifts page hour total

import os
import re
import csv
import sys
import json
import math
import string
import socket
import logging
import warnings
import traceback
from glob import glob
from uuid import uuid4
from io import StringIO
from copy import deepcopy
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

import bcrypt
import cherrypy
import django.conf
from amazon_ses import AmazonSES, EmailMessage

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

import stripe
stripe.api_key = STRIPE_SECRET_KEY

import logging_unterpolation
logging_unterpolation.patch_logging()


class HTTPRedirect(cherrypy.HTTPRedirect):
    def __init__(self, page, *args, **kwargs):
        args = [self.quote(s) for s in args]
        kwargs = {k:self.quote(v) for k,v in kwargs.items()}
        cherrypy.HTTPRedirect.__init__(self, page.format(*args, **kwargs))
        if state.URL_BASE.startswith("https"):
            self.urls[0] = self.urls[0].replace("http://", "https://")
    
    def quote(self, s):
        return quote(s) if isinstance(s, str) else str(s)


def listify(x):
    return x if isinstance(x, (list,tuple,set,frozenset)) else [x]


def comma_and(xs):
    if len(xs) > 1:
        xs[-1] = "and " + xs[-1]
    return (", " if len(xs) > 2 else " ").join(xs)


def check_csrf(csrf_token):
    if csrf_token is None:
        csrf_token = cherrypy.request.headers.get("CSRF-Token")
    assert csrf_token, "CSRF token missing"
    if csrf_token != cherrypy.session["csrf_token"]:
        log.error("csrf tokens don't match: {!r} != {!r}", csrf_token, cherrypy.session["csrf_token"])
        raise AssertionError("CSRF check failed")
    else:
        cherrypy.request.headers["CSRF-Token"] = csrf_token

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


# TODO: insert email only if successful
# TODO: handle dest as a list more gracefully in the Email table
# TODO: insert into Email tables for all unsent emails on a dev box
def send_email(source, dest, subject, body, format = "text", cc = [], bcc = [], model = None):
    to, cc, bcc = map(listify, [dest, cc, bcc])
    if DEV_BOX:
        for xs in [to, cc, bcc]:
            xs[:] = [email for email in xs if email.endswith("mailinator.com") or "eli@courtwright.org" in email]
    
    if model and dest:
        fk = {"fk_id": 0, "model": "n/a"} if model == "n/a" else {"fk_id": model.id, "model": model.__class__.__name__}
        Email.objects.create(subject = subject, dest = dest, body = body, **fk)
    
    if state.SEND_EMAILS and to:
        message = EmailMessage(subject = subject, **{"bodyText" if format == "text" else "bodyHtml": body})
        AmazonSES(AWS_ACCESS_KEY_ID, AWS_SECRET_KEY).sendEmail(
            source = source,
            toAddresses = to,
            ccAddresses = cc,
            bccAddresses = bcc,
            message = message
        )
        sleep(0.1)  # avoid hitting rate limit
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


class Charge:
    def __init__(self, targets, amount=None, description=None):
        self.targets = listify(targets)
        self.amount = amount or self.total_cost
        self.description = description or self.names
    
    @staticmethod
    def get(payment_id):
        charge = cherrypy.session.pop(payment_id)
        charge.refresh()
        return charge
    
    def refresh(self):
        self.targets[:] = [t.__class__.objects.get(id=t.id) if t.id else t for t in self.targets]
    
    @property
    def total_cost(self):
        return 100 * sum(m.amount_unpaid for m in self.targets)
    
    @property
    def dollar_amount(self):
        return self.amount // 100
    
    @property
    def names(self):
        return ", ".join(repr(m).strip("<>") for m in self.targets)
    
    @property
    def attendees(self):
        return [m for m in self.targets if isinstance(m, Attendee)]
    
    @property
    def groups(self):
        return [m for m in self.targets if isinstance(m, Group)]
    
    def charge_cc(self, token):
        try:
            self.response = stripe.Charge.create(
                card=token,
                currency="usd",
                amount=self.amount,
                description=self.description
            )
        except stripe.CardError as e:
            return "Your card was declined with the following error from our processor: " + str(e)
        except stripe.StripeError as e:
            log.error("unexpected stripe error", exc_info=True)
            return "An unexpected problem occured while processing your card: " + str(e)


def affiliates(exclude={"paid":NOT_PAID}):
    amounts = defaultdict(int, {a:-i for i,a in enumerate(DEFAULT_AFFILIATES)})
    for aff,amt in Attendee.objects.exclude(Q(amount_extra=0) | Q(affiliate="")).values_list("affiliate","amount_extra"):
        amounts[aff] += amt
    return [(aff,aff) for aff,amt in sorted(amounts.items(), key=lambda tup: -tup[1])]


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
