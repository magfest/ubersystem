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
from uber.utils import SignNowDocument

__all__ = ['SignedDocument']

class SignedDocument(MagModel):
    fk_id = Column(UUID, index=True)
    model = Column(UnicodeText)
    document_id = Column(UnicodeText)
    link = Column(UnicodeText)
    ident = Column(UnicodeText)
    signed = Column(UTCDateTime, nullable=True, default=None)
    declined = Column(UTCDateTime, nullable=True, default=None)

    def get_doc_signed_timestamp(self, document_id=""):
        d = SignNowDocument()
        document_id = document_id or self.document_id

        if not document_id:
            return
        
        document = d.get_document_details(document_id)
        if document.get('signatures'):
            return document['signatures'][0].get('created')

    def get_dealer_signing_link(self, group):
        d = SignNowDocument()
        
        if not self.document_id:
            self.document_id = d.create_document(template_id=c.SIGNNOW_DEALER_TEMPLATE_ID,
                                                 doc_title="Dealer T&C for {}".format(group.name),
                                                 folder_id=c.SIGNNOW_DEALER_FOLDER_ID)
        if not self.signed:
            return d.get_signing_link(self.document_id,
                                      group.leader.first_name,
                                      group.leader.last_name,
                                      (c.REDIRECT_URL_BASE or c.URL_BASE) + '/preregistration/dealer_confirmation?id={}'
                                      .format(group.id))