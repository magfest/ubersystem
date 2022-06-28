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

__all__ = ['SignedDocument']

class SignedDocument(MagModel):
    fk_id = Column(UUID, index=True)
    model = Column(UnicodeText)
    document_id = Column(UnicodeText)
    link = Column(UnicodeText)
    ident = Column(UnicodeText)
    signed = Column(UTCDateTime, nullable=True, default=None)
    declined = Column(UTCDateTime, nullable=True, default=None)