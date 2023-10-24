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
from uber.decorators import presave_adjustment
from uber.models import MagModel
from uber.models.admin import AdminAccount
from uber.models.email import Email
from uber.models.types import Choice, DefaultColumn as Column, MultiChoice
from uber.utils import SignNowRequest

__all__ = ['SignedDocument']

class SignedDocument(MagModel):
    fk_id = Column(UUID, index=True)
    model = Column(UnicodeText)
    document_id = Column(UnicodeText)
    last_emailed = Column(UTCDateTime, nullable=True, default=None)
    link = Column(UnicodeText)
    ident = Column(UnicodeText)
    signed = Column(UTCDateTime, nullable=True, default=None)
    declined = Column(UTCDateTime, nullable=True, default=None)

    @presave_adjustment
    def null_to_strings(self):
        if not self.document_id:
            self.document_id = ""
        if not self.link:
            self.link = ''
