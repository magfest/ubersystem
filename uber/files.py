import bcrypt
import cherrypy
import contextlib
import math
import os
import phonenumbers
import unicodedata
import random
import re
import string
import textwrap
import traceback
import uber
import urllib
import logging
import warnings
import six
import shutil

from abc import ABC, abstractmethod
from PIL import Image
from cherrypy.lib.static import serve_file
from collections import defaultdict, OrderedDict
from collections.abc import Iterable, Mapping, Sized
from datetime import date, datetime, timedelta, timezone
from glob import glob
from os.path import basename
from rpctools.jsonrpc import ServerProxy
from urllib.parse import urlparse, urljoin
from uuid import uuid4
from phonenumbers import PhoneNumberFormat
from pytz import UTC
from sqlalchemy import func, or_, cast, literal, DateTime
from sqlalchemy.exc import InvalidRequestError

from uber.config import c
from uber.models import File, uncamel


log = logging.getLogger(__name__)


class FileHandler(ABC):
    @abstractmethod
    def __init__(self, session, file_or_parent_obj, *args, **kwargs):
        self.session = session

        if isinstance(file_or_parent_obj, File):
            self.file_obj = file_or_parent_obj
        else:
            self.file_obj = File(fk_model=file_or_parent_obj.__class__.__name__,
                                 fk_id=file_or_parent_obj.id)
        self.update_file_obj(**kwargs)

    @abstractmethod
    def update_file_obj(self, *args, **kwargs):
        if not kwargs.get('fk_id', True) or not kwargs.get('fk_model', True):
            raise ValueError("You cannot nullify a file's fk_id or fk_model. Use delete() instead.")

        for key, val in kwargs.items():
            if hasattr(self.file_obj, key):
                setattr(self.file_obj, key, val)

    @abstractmethod
    def delete(self):
        pass

    @abstractmethod
    def preview(self):
        pass


class ServerFileHandler(FileHandler):
    """
    Handles uploading and downloading files directly to the server.
    """
    def __init__(self, session, file_or_parent_obj, *args, **kwargs):
        super().__init__(session, file_or_parent_obj, *args, **kwargs)

        self.folderpath = os.path.join(c.UPLOADED_FILES_DIR, uncamel(self.file_obj.fk_model))
        if self.file_obj.filepath:
            filepath, ext = os.path.splitext(self.file_obj.filepath)
            self.thumbnail_path = f"{filepath}_thumbnail{ext}"
    
    def update_file_obj(self, *args, **kwargs):
        super().update_file_obj(*args, **kwargs)

    def delete(self):
        with contextlib.suppress(FileNotFoundError):
            os.remove(self.file_obj.filepath)
            os.remove(self.thumbnail_path)

        try:
            self.session.delete(self.file_obj)
        except InvalidRequestError:
            with contextlib.suppress(InvalidRequestError):
                self.session.expunge(self.file_obj)

    def process_file_upload(self, file_part, allowed_extensions=[],
                            delete_existing=True, update_model=None, run_validations=True):
        if run_validations:
            message = self.prevalidate_file(file_part, allowed_extensions=allowed_extensions)
        if not run_validations or not message:
            message = self.upload(file_part, run_validations=run_validations)
            if message:
                self.delete()
            else:
                if update_model:
                    update_model.last_updated = datetime.now(UTC)
                    self.session.add(update_model)
                if delete_existing:
                    FileService.delete_existing_files(self.session, self.file_obj, self.file_obj.true_flags)
        return message or ''

    def upload(self, file_part, allowed_extensions=[], run_validations=True):
        errors = self.prevalidate_file(file_part, allowed_extensions)
        if errors:
            return errors
        
        server_filename = f"{self.file_obj.fk_id}_{'_'.join(self.file_obj.true_flags)}_{self.file_obj.id}"
        extension = file_part.filename.split('.')[-1].lower()

        server_filepath = os.path.join(self.folderpath, server_filename)
        self.thumbnail_path = f"{server_filepath}_thumbnail.{extension}"
        self.file_obj.filepath = f"{server_filepath}.{extension}"

        os.makedirs(self.folderpath, mode=0o744, exist_ok=True)

        with open(self.file_obj.filepath, 'wb') as f:
            shutil.copyfileobj(file_part.file, f)

        if run_validations:
            errors = self.validate_file()
            if errors:
                with contextlib.suppress(FileNotFoundError):
                    os.remove(self.file_obj.filepath)
                return errors

        self.file_obj.filename = file_part.filename
        self.file_obj.content_type = file_part.content_type.value
        self.file_obj.extension = extension
        
        self.session.add(self.file_obj)
    
    def prevalidate_file(self, file_part, allowed_extensions=[]):
        if allowed_extensions:
            extension = file_part.filename.split('.')[-1].lower()
            if extension not in allowed_extensions:
                return f"Uploaded file type must be one of {', '.join(allowed_extensions)}."

    def validate_file(self):
        if self.file_obj.flags.get('guidebook_header', False):
            return self.check_image_dimensions(c.GUIDEBOOK_HEADER_SIZE)
        if self.file_obj.flags.get('guidebook_thumbnail', False):
            return self.check_image_dimensions(c.GUIDEBOOK_THUMBNAIL_SIZE)

    def check_image_dimensions(self, size_list):
        with contextlib.suppress(OSError):
            image_size = Image.open(self.file_obj.filepath).size
            image_label = "Image"
            if self.file_obj.flags.get('guidebook_header', False):
                image_label = "Header image"
            elif self.file_obj.flags.get('guidebook_thumbnail', False):
                image_label = "Thumbnail image"

            if image_size != tuple(map(int, size_list)):
                return f"{image_label} dimensions must be {size_list[0]}x{size_list[1]} pixels, \
                    not {str(image_size[0])}x{str(image_size[1])} pixels."

    def preview(self, max_pixels=500, filename=''):
        if not self.file_obj.filepath:
            return "This file has not been uploaded yet or we do not know where it is on the server."
        
        if filename:
            filename = filename + self.file_obj.extension
        else:
            filename = self.file_obj.filename

        if not os.path.exists(self.thumbnail_path):
            # TODO: Rerender if max pixels is smaller than file?
            max_pixels = int(max_pixels)
            try:
                with Image.open(self.file_obj.filepath) as image:
                    thumbnail = image.copy()
                    thumbnail.thumbnail((max_pixels, max_pixels))
                    thumbnail.save(self.thumbnail_path)
            except OSError:
                return "We can only render previews for images."

        cherrypy.response.headers['Cache-Control'] = 'no-store'
        return serve_file(self.thumbnail_path, name=filename, content_type=self.file_obj.content_type)

    def serve_file(self, filename=''):
        cherrypy.response.headers['Cache-Control'] = 'no-store'
        if filename:
            filename = filename + self.file_obj.extension
        else:
            filename = self.file_obj.filename

        return serve_file(
            self.file_obj.filepath,
            disposition="attachment",
            name=filename,
            content_type=self.file_obj.content_type)


class S3FileHandler(FileHandler):
    """
    Handles AWS S3 file uploads and downloads, if S3 bucket uploads are configured.
    """
    def __init__(self, session, file_or_parent_obj, description='', flags={}, *args, **kwargs):
        super().__init__(session, file_or_parent_obj, {'description': description, 'flags': flags}, *args, **kwargs)
    
    def update_file_obj(self, *args, **kwargs):
        super().update_file_object(*args, **kwargs)

    def delete(self):
        try:
            self.session.delete(self.file_obj)
        except InvalidRequestError:
            with contextlib.suppress(InvalidRequestError):
                self.session.expunge(self.file_obj)

    def upload(self, response):
        # Handle S3 upload response
        pass

    def preview(self):
        # serve preview file, if it exists
        pass


class FileService:
    @staticmethod
    def file_handler(session, file_or_parent_obj, *args, **kwargs):
        return ServerFileHandler(session, file_or_parent_obj, *args, **kwargs)
    
    @staticmethod
    def from_fk_model_id(session, fk_model, fk_id, *args, **kwargs):
        model_cls = session.resolve_model(fk_model)
        fk_object = session.query(model_cls).filter(model_cls.id == fk_id).one()
        return FileService.file_handler(session, fk_object, *args, **kwargs)

    @staticmethod
    def from_db_id(session, file_obj_id, *args, **kwargs):
        file_obj = session.query(File).filter(File.id == file_obj_id).one()
        return FileService.file_handler(session, file_obj, *args, **kwargs)

    @staticmethod
    def delete_existing_files(session, file_or_parent_obj, and_flags=[], or_flags=[]):
        existing_files = FileService.get_existing_files(session, file_or_parent_obj, and_flags, or_flags, uselist=True)
        for file in existing_files:
            file_handler = FileService.file_handler(session, file)
            file_handler.delete()

    @staticmethod
    def get_existing_files(session, file_or_parent_obj, and_flags=[], or_flags=[], uselist=False):
        if isinstance(file_or_parent_obj, File):
            fk_id, fk_model = file_or_parent_obj.fk_id, file_or_parent_obj.fk_model
        else:
            fk_id, fk_model = file_or_parent_obj.id, file_or_parent_obj.__class__.__name__

        existing_files = session.query(File).filter(File.fk_id == fk_id, File.fk_model == fk_model)

        and_filters = []
        for flag in and_flags:
            and_filters.append(File.flags[flag].astext == 'true')
        if and_filters:
            existing_files = existing_files.filter(*and_filters)

        or_filters = []
        for flag in or_flags:
            or_filters.append(File.flags[flag].astext == 'true')
        if or_filters:
            existing_files = existing_files.filter(or_(*or_filters))

        return existing_files.all() if uselist else existing_files.first()
    
    @staticmethod
    def files_by_fk_id(session, fk_ids, fk_models=[], and_flags=[], or_flags=[]):
        if not fk_ids:
            return {}

        filters = [File.fk_id.in_(fk_ids)]
        if fk_models:
            filters.append(File.fk_model.in_(fk_models))
        
        matching_files = session.query(File).filter(*filters)

        and_filters = []
        for flag in and_flags:
            and_filters.append(File.flags[flag].astext == 'true')
        if and_filters:
            matching_files = matching_files.filter(*and_filters)

        or_filters = []
        for flag in or_flags:
            or_filters.append(File.flags[flag].astext == 'true')
        if or_filters:
            matching_files = matching_files.filter(or_(*or_filters))

        matching_files = matching_files.order_by(File.fk_id)
        files_by_fk_id = defaultdict(list)
        for file in matching_files:
            files_by_fk_id[file.fk_id].append(file)

        return files_by_fk_id
