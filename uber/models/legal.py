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
from uber.utils import SignNowDocument

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
    def null_doc_id(self):
        if not self.document_id:
            self.document_id = ""

    def get_doc_signed_timestamp(self, document_id=""):
        d = SignNowDocument()
        document_id = document_id or self.document_id

        if not document_id:
            return
        
        document = d.get_document_details(document_id)
        if document and document.get('signatures'):
            return document['signatures'][0].get('created')
        
    def send_dealer_signing_invite(self, group):
        d = SignNowDocument()

        first_name = group.leader.first_name if group.leader else ''
        last_name = group.leader.last_name if group.leader else ''
        
        if not self.document_id:
            self.document_id = d.create_document(template_id=c.SIGNNOW_DEALER_TEMPLATE_ID,
                                                 doc_title="MFF {} Dealer Terms - {}".format(c.EVENT_YEAR, group.name),
                                                 folder_id=c.SIGNNOW_DEALER_FOLDER_ID,
                                                 uneditable_texts_list=group.signnow_texts_list,
                                                 fields={} if c.SIGNNOW_ENV == 'eval' else {'printed_name': first_name + " " + last_name})
            if d.error_message:
                self.document_id = None
                log.error(d.error_message)

        if self.document_id and not self.signed:
            log.debug(d.send_signing_invite(self.document_id, group, first_name + " " + last_name))

    def create_dealer_signing_link(self, group):
        d = SignNowDocument()

        first_name = group.leader.first_name if group.leader else ''
        last_name = group.leader.last_name if group.leader else ''
        
        if not self.document_id:
            self.document_id = d.create_document(template_id=c.SIGNNOW_DEALER_TEMPLATE_ID,
                                                 doc_title="MFF {} Dealer Terms - {}".format(c.EVENT_YEAR, group.name),
                                                 folder_id=c.SIGNNOW_DEALER_FOLDER_ID,
                                                 uneditable_texts_list=group.signnow_texts_list,
                                                 fields={} if c.SIGNNOW_ENV == 'eval' else {'printed_name': first_name + " " + last_name})
            if d.error_message:
                self.document_id = None
                log.error(d.error_message)

        if self.document_id and not self.signed:
            return d.get_signing_link(self.document_id,
                                      first_name,
                                      last_name,
                                      (c.REDIRECT_URL_BASE or c.URL_BASE) + '/preregistration/group_members?id={}'
                                      .format(group.id))
