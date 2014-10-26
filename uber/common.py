import os
import re
import csv
import sys
import json
import math
import string
import socket
import random
import inspect
import warnings
import mimetypes
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
from itertools import chain
from xml.dom import minidom
from random import randrange
from contextlib import closing
from time import sleep, mktime
from urllib.parse import quote
from urllib.parse import urlparse
from collections import defaultdict, OrderedDict
from os.path import abspath, dirname, exists, join
from datetime import date, time, datetime, timedelta
from threading import Thread, RLock, local, current_thread

import pytz
import bcrypt
import cherrypy
import django.conf
from pytz import UTC

from django import template
from django.utils.safestring import SafeString
from django.template import loader, Context, Variable, TemplateSyntaxError

import sqlalchemy
from sqlalchemy.sql import case
from sqlalchemy.event import listen
from sqlalchemy.ext import declarative
from sqlalchemy import func, or_, and_, not_
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm.exc import NoResultFound
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.sql.expression import FunctionElement
from sqlalchemy.orm.attributes import get_history, instance_state
from sqlalchemy.schema import Column, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Query, relationship, joinedload, backref
from sqlalchemy.types import UnicodeText, Boolean, Integer, Float, TypeDecorator

from sideboard.lib.sa import declarative_base, SessionManager, UTCDateTime, UUID
from sideboard.lib import log, parse_config, entry_point, listify, DaemonTask, serializer, cached_property

import uber
from uber.amazon_ses import AmazonSES, EmailMessage  # TODO: replace this after boto adds Python 3 support
from uber.config import *
from uber import config
from uber.utils import *
from uber.decorators import *
from uber.models import *
from uber.automated_emails import *
from uber.badge_funcs import *
from uber import model_checks
from uber import custom_tags
from uber.server import *
from uber import reset_db
from uber.tests import import_test_data

import stripe
stripe.api_key = STRIPE_SECRET_KEY

# kludgy hack because I love "from <module> import *" way too much
for _module in ['config', 'utils', 'models', 'custom_tags', 'decorators']:
    __import__('uber.' + _module, fromlist='*').__dict__.update(globals())
