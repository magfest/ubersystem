import os
import re
import csv
import sys
import json
import math
import string
import socket
import logging
import inspect
import warnings
import threading
import traceback
from glob import glob
from uuid import uuid4
from io import StringIO
from pprint import pprint
from copy import deepcopy
from pprint import pformat
from hashlib import sha512
from functools import wraps
from xml.dom import minidom
from random import randrange
from time import sleep, mktime
from urllib.parse import quote
from os.path import abspath, dirname, join
from collections import defaultdict, OrderedDict
from datetime import date, time, datetime, timedelta
from threading import Thread, RLock, local, current_thread

import bcrypt
import cherrypy
import django.conf
from validate import Validator
from configobj import ConfigObj, ConfigObjError, flatten_errors

from uber.amazon_ses import AmazonSES, EmailMessage
from uber.config import *
from uber.constants import *
from uber import constants

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
        if URL_BASE.startswith('https'):
            self.urls[0] = self.urls[0].replace('http://', 'https://')
    
    def quote(self, s):
        return quote(s) if isinstance(s, str) else str(s)


def listify(x):
    return list(x) if isinstance(x, (list,tuple,set,frozenset)) else [x]


def comma_and(xs):
    if len(xs) > 1:
        xs[-1] = 'and ' + xs[-1]
    return (', ' if len(xs) > 2 else ' ').join(xs)


def check_csrf(csrf_token):
    if csrf_token is None:
        csrf_token = cherrypy.request.headers.get('CSRF-Token')
    assert csrf_token, 'CSRF token missing'
    if csrf_token != cherrypy.session['csrf_token']:
        log.error("csrf tokens don't match: {!r} != {!r}", csrf_token, cherrypy.session['csrf_token'])
        raise AssertionError('CSRF check failed')
    else:
        cherrypy.request.headers['CSRF-Token'] = csrf_token

def check(model):
    prefix = model.__class__.__name__.lower() + '_'
    
    for field,name in getattr(model_checks, prefix + 'required', []):
        if not str(getattr(model,field)).strip():
            return name + ' is a required field'
    
    for name,attr in model_checks.__dict__.items():
        if name.startswith(prefix) and hasattr(attr, '__call__'):
            message = attr(model)
            if message:
                return message


class Order:
    def __init__(self, order):
        self.order = order
    
    def __getitem__(self, field):
        return ('-' + field) if field==self.order else field
    
    def __str__(self):
        return self.order


class SeasonEvent:
    instances = []
    
    def __init__(self, slug, **kwargs):
        assert re.match('^[a-z0-9_]+$', slug), 'Season Event sections must have separated_by_underscore names'
        for opt in ['url', 'location']:
            assert kwargs.get(opt), '{!r} is a required option for Season Event subsections'.format(opt)
        
        self.slug = slug
        self.name = kwargs['name'] or slug.replace('_', ' ').title()
        self.day = datetime.strptime('%Y-%m-%d', kwargs['day'])
        self.url = kwargs['url']
        self.location = kwargs['location']
        if kwargs['deadline']:
            self.deadline = datetime.strptime('%Y-%m-%d', kwargs['day'])
        else:
            self.deadline = datetime.combine((self.day - timedelta(days = 7)).date(), time(23, 59))
    
    @classmethod
    def register(cls, slug, kwargs):
        cls.instances.append(cls(slug, **kwargs))

for _slug, _conf in conf['season_events'].items():
    SeasonEvent.register(_slug, _conf)


def assign(attendee_id, job_id):
    job = Job.objects.get(id=job_id)
    attendee = Attendee.objects.get(id = attendee_id)
    
    if job.restricted and not attendee.trusted:
        return 'You cannot assign an untrusted attendee to a restricted shift'
    
    if job.slots <= job.shift_set.count():
        return 'All slots for this job have already been filled'
    
    if not job.no_overlap(attendee):
        return 'This volunteer is already signed up for a shift during that time'
    
    Shift.objects.create(attendee=attendee, job=job)


def hour_day_format(dt):
    return dt.strftime('%I%p ').strip('0').lower() + dt.strftime('%a')


def send_email(source, dest, subject, body, format = 'text', cc = [], bcc = [], model = None):
    to, cc, bcc = map(listify, [dest, cc, bcc])
    if DEV_BOX:
        for xs in [to, cc, bcc]:
            xs[:] = [email for email in xs if email.endswith('mailinator.com') or 'eli@courtwright.org' in email]
    
    if SEND_EMAILS and to:
        message = EmailMessage(subject = subject, **{'bodyText' if format == 'text' else 'bodyHtml': body})
        AmazonSES(AWS_ACCESS_KEY_ID, AWS_SECRET_KEY).sendEmail(
            source = source,
            toAddresses = to,
            ccAddresses = cc,
            bccAddresses = bcc,
            message = message
        )
        sleep(0.1)  # avoid hitting rate limit
    else:
        log.error('email sending turned off, so unable to send {}', locals())
    
    if model and dest:
        fk = {'fk_id': 0, 'model': 'n/a'} if model == 'n/a' else {'fk_id': model.id, 'model': model.__class__.__name__}
        Email.objects.create(subject = subject, dest = ','.join(listify(dest)), body = body, **fk)


# this is here instead of in badge_funcs.py for import simplicity
def check_range(badge_num, badge_type):
    try:
        badge_num = int(badge_num)
    except:
        return '"{}" is not a valid badge number (should be an integer)'.format(badge_num)
    
    if badge_num:
        min_num, max_num = BADGE_RANGES[int(badge_type)]
        if not min_num <= badge_num <= max_num:
            return '{} badge numbers must fall within the range {} - {}'.format(dict(BADGE_OPTS)[badge_type], min_num, max_num)


class Charge:
    def __init__(self, targets=(), amount=None, description=None):
        self.targets = [self.serialize(m) for m in listify(targets)]
        self.amount = amount or self.total_cost
        self.description = description or self.names
    
    @staticmethod
    def get(payment_id):
        return Charge(**cherrypy.session.pop(payment_id))
    
    def to_dict(self):
        return {
            'targets': self.targets,
            'amount': self.amount,
            'description': self.description
        }
    
    def serialize(self, x):
        if isinstance(x, dict):
            return x
        if isinstance(x, Attendee):
            return {'attendee': x.id}
        elif isinstance(x, Group):
            return {'group': x.id}
        else:
            raise AssertionError('{} is not an attendee or group'.format(x))
    
    def parse(self, d):
        if 'attendee' in d:
            return Attendee.objects.get(id=d['attendee'])
        elif 'group' in d:
            return Attendee.objects.get(id=d['group'])
        else:
            raise AssertionError('{} is not an attendee or group'.format(d))
    
    @property
    def models(self):
        return [self.parse(d) for d in self.targets]
    
    @property
    def total_cost(self):
        return 100 * sum(m.amount_unpaid for m in self.models)
    
    @property
    def dollar_amount(self):
        return self.amount // 100
    
    @property
    def names(self):
        return ', '.join(repr(m).strip('<>') for m in self.models)
    
    @property
    def attendees(self):
        return [self.parse(d) for d in self.targets if 'attendee' in d]
    
    @property
    def groups(self):
        return [self.parse(d) for d in self.targets if 'group' in d]
    
    def charge_cc(self, token):
        try:
            self.response = stripe.Charge.create(
                card=token,
                currency='usd',
                amount=self.amount,
                description=self.description
            )
        except stripe.CardError as e:
            return 'Your card was declined with the following error from our processor: ' + str(e)
        except stripe.StripeError as e:
            log.error('unexpected stripe error', exc_info=True)
            return 'An unexpected problem occured while processing your card: ' + str(e)


def affiliates(exclude={'paid':NOT_PAID}):
    amounts = defaultdict(int, {a:-i for i,a in enumerate(DEFAULT_AFFILIATES)})
    for aff,amt in Attendee.objects.exclude(Q(amount_extra=0) | Q(affiliate='')).values_list('affiliate','amount_extra'):
        amounts[aff] += amt
    return [(aff,aff) for aff,amt in sorted(amounts.items(), key=lambda tup: -tup[1])]



def get_page(page, queryset):
    return queryset[(int(page) - 1) * 100 : int(page) * 100]


stopped = threading.Event()
cherrypy.engine.subscribe('start', stopped.clear)
cherrypy.engine.subscribe('stop', stopped.set, priority=98)

class DaemonTask:
    def __init__(self, func, name='DaemonTask', interval=300, threads=1):
        self.threads = []
        self.name, self.func, self.interval, self.thread_count = name, func, interval, threads
        cherrypy.engine.subscribe('start', self.start)
        cherrypy.engine.subscribe('stop', self.stop, priority=99)
    
    @property
    def running(self):
        return any(t.is_alive() for i in self.threads)
    
    def start(self):
        assert not self.threads, '{} was already started and has not yet stopped'.format(self.name)
        for i in range(self.thread_count):
            t = Thread(target = self.func, name = self.name)
            t.daemon = True
            t.start()
            self.threads.append(t)
    
    def stop(self):
        for i in range(20):
            if self.running:
                sleep(0.1)
            else:
                break
        else:
            log.warn('{} is still running, so it will just be killed when the Python interpreter exits', self.name)
        del self.threads[:]
    
    def run(self):
        while not stopped.is_set():
            try:
                self.func()
            except:
                log.warning('ignoring unexpected error in {}', self.name, exc_info=True)
            
            if self.interval:
                stopped.wait(self.interval)


# These imports are last so they can import everything from this module.  Don't move or reorder them.
from uber.decorators import *
from uber.models import *
from uber.badge_funcs import *
from uber import model_checks
from uber import custom_tags
from uber.server import *
