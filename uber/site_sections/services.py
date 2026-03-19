import os
import shutil
import logging
import cherrypy
from cherrypy.lib.static import serve_file
from sqlalchemy.orm.exc import NoResultFound

from uber.config import c
from uber.decorators import ajax, all_renderable, render
from uber.errors import HTTPRedirect
from uber.models import GuestMerch, GuestDetailedTravelPlan, GuestTravelPlans, GuestPanel
from uber.model_checks import mivs_show_info_required_fields
from uber.utils import check, filename_extension
from uber.tasks.email import send_email
from uber.files import FileService


log = logging.getLogger(__name__)


@all_renderable(public=True)
class Root:
    def download_file(self, session, id, filename='', preview=False):
        file_handler = FileService.from_db_id(session, id)
        if preview:
            return file_handler.preview(filename=filename)
        else:
            return file_handler.serve_file(filename=filename)