import os
import re
import shutil
import uuid
import logging
from collections import defaultdict
from datetime import datetime, timedelta
from markupsafe import Markup

from sqlalchemy.orm import backref
from sqlalchemy.schema import ForeignKey
from sqlalchemy.types import Boolean, Integer, String, DateTime, Uuid, JSON
from sqlmodel import Field, Relationship
from typing import Any, ClassVar

from uber.config import c
from uber.custom_tags import yesno
from uber.decorators import presave_adjustment, classproperty
from uber.models import MagModel
from uber.models.types import (default_relationship as relationship, Choice, DefaultColumn as Column,
                               MultiChoice, GuidebookImageMixin)
from uber.utils import filename_extension, slugify

log = logging.getLogger(__name__)


__all__ = [
    'GuestGroup', 'GuestInfo', 'GuestBio', 'GuestTaxes', 'GuestStagePlot',
    'GuestPanel', 'GuestMerch', 'GuestCharity', 'GuestAutograph', 'GuestImage', 'GuestMediaRequest',
    'GuestInterview', 'GuestTravelPlans', 'GuestDetailedTravelPlan', 'GuestHospitality', 'GuestTrack']


class GuestGroup(MagModel, table=True):
    """
    Group: joined
    """
    
    group_id: str | None = Column(Uuid(as_uuid=False), ForeignKey('group.id'))
    event_id: str | None = Column(Uuid(as_uuid=False), ForeignKey('event.id', ondelete='SET NULL'), nullable=True)
    group_type: int = Column(Choice(c.GROUP_TYPE_OPTS), default=c.BAND)
    num_hotel_rooms: int = Column(Integer, default=1, admin_only=True)
    payment: int = Column(Integer, default=0, admin_only=True)
    vehicles: int = Column(Integer, default=1, admin_only=True)
    estimated_loadin_minutes: int = Column(Integer, default=c.DEFAULT_LOADIN_MINUTES, admin_only=True)
    estimated_performance_minutes: int = Column(Integer, default=c.DEFAULT_PERFORMANCE_MINUTES, admin_only=True)

    wants_mc: bool | None = Column(Boolean, nullable=True)
    needs_rehearsal: int | None = Column(Choice(c.GUEST_REHEARSAL_OPTS), nullable=True)
    badges_assigned: bool = Column(Boolean, default=False)
    info: 'GuestInfo' = Relationship(sa_relationship=relationship('GuestInfo', backref=backref('guest', lazy='joined'), uselist=False))
    images: list['GuestImage'] = Relationship(sa_relationship=relationship(
        'GuestImage', backref=backref('guest'), order_by='GuestImage.id'))
    bio: 'GuestBio' = Relationship(sa_relationship=relationship('GuestBio', backref=backref('guest', lazy='joined'), uselist=False))
    taxes: 'GuestTaxes' = Relationship(sa_relationship=relationship('GuestTaxes', backref=backref('guest', lazy='joined'), uselist=False))
    stage_plot: 'GuestStagePlot' = Relationship(sa_relationship=relationship('GuestStagePlot', backref=backref('guest', lazy='joined'), uselist=False))
    panel: 'GuestPanel' = Relationship(sa_relationship=relationship('GuestPanel', backref=backref('guest', lazy='joined'), uselist=False))
    merch: 'GuestMerch' = Relationship(sa_relationship=relationship('GuestMerch', backref=backref('guest', lazy='joined'), uselist=False))
    tracks: list['GuestTrack'] = Relationship(sa_relationship=relationship('GuestTrack', backref=backref('guest', lazy='joined')))
    charity: 'GuestCharity' = Relationship(sa_relationship=relationship('GuestCharity', backref=backref('guest', lazy='joined'), uselist=False))
    autograph: 'GuestAutograph' = Relationship(sa_relationship=relationship('GuestAutograph', backref=backref('guest', lazy='joined'), uselist=False))
    interview: 'GuestInterview' = Relationship(sa_relationship=relationship('GuestInterview', backref=backref('guest', lazy='joined'), uselist=False))
    travel_plans: 'GuestTravelPlans' = Relationship(sa_relationship=relationship('GuestTravelPlans', backref=backref('guest', lazy='joined'), uselist=False))
    hospitality: 'GuestHospitality' = Relationship(sa_relationship=relationship('GuestHospitality', backref=backref('guest', lazy='joined'), uselist=False))
    media_request: 'GuestMediaRequest' = Relationship(sa_relationship=relationship('GuestMediaRequest', backref=backref('guest', lazy='joined'), uselist=False))

    email_model_name: ClassVar = 'guest'

    def __getattr__(self, name):
        """
        If someone tries to access a property called, e.g., info_status,
        and the named property doesn't exist, we instead call
        self.status. This allows us to refer to status config options
        indirectly, which in turn allows us to override certain status
        options on a case-by-case basis. This is helpful for a couple of
        properties here, but it's vital to allow events to control group
        checklists with granularity.
        """
        if name.endswith('_status'):
            return self.status(name.rsplit('_', 1)[0])
        else:
            return super(GuestGroup, self).__getattr__(name)

    @presave_adjustment
    def empty_strings_to_zero(self):
        if not self.payment:
            self.payment = 0

        if not self.vehicles:
            self.vehicles = 0

        if not self.num_hotel_rooms:
            self.num_hotel_rooms = 0

    def deadline_from_model(self, model):
        name = str(self.group_type_label).upper().replace(' ', '_') + "_" + str(model).upper() + "_DEADLINE"
        return getattr(c, name, None)

    @property
    def sorted_checklist_items(self):
        checklist_items = []
        for item in c.GUEST_CHECKLIST_ITEMS:
            if self.deadline_from_model(item['name']):
                checklist_items.append(item)

        return sorted(checklist_items, key=lambda i: self.deadline_from_model(i['name']))

    def matches_showcases(self, showcases):
        if self.group_type != c.MIVS or not self.group or not self.group.studio:
            return
        for game in self.group.studio.confirmed_games:
            if game.showcase_type in showcases:
                return True
        return False

    @property
    def uses_detailed_travel_plans(self):
        return  # Disabled for now

    @property
    def all_badges_claimed(self):
        return not any(a.is_unassigned or a.placeholder for a in self.group.attendees)

    @property
    def estimated_performer_count(self):
        return len([a for a in self.group.attendees if a.badge_type == c.GUEST_BADGE])

    @property
    def performance_minutes(self):
        return self.estimated_performance_minutes

    @property
    def email(self):
        return self.group.email

    @property
    def gets_emails(self):
        return self.group.gets_emails

    @property
    def normalized_group_name(self):
        # Lowercase
        name = self.group.name.strip().lower()

        # Remove all special characters
        name = ''.join(s for s in name if s.isalnum() or s == ' ')

        # Remove extra whitespace & replace spaces with underscores
        return ' '.join(name.split()).replace(' ', '_')

    @property
    def badges_status(self):
        if self.group.unregistered_badges:
            return str(self.group.unregistered_badges) + " Unclaimed"
        return "Yes"

    @property
    def taxes_status(self):
        return "Not Needed" if not self.payment else self.status('taxes')

    @property
    def merch_status(self):
        if self.merch and self.merch.selling_merch == c.ROCK_ISLAND and not self.merch.poc_address1:
            return None
        return self.status('merch')

    @property
    def panel_status(self):
        application_count = len(self.group.leader.submitted_panels)
        return '{} Panel Application(s)'.format(application_count) \
            if self.group.leader.submitted_panels else self.status('panel')

    @property
    def mc_status(self):
        return None if self.wants_mc is None else yesno(self.wants_mc, 'Yes,No')

    @property
    def rehearsal_status(self):
        if self.needs_rehearsal == c.NO:
            return "do not"
        elif self.needs_rehearsal == c.MAYBE:
            return "might"
        elif self.needs_rehearsal == c.YES:
            return "do"

    @property
    def checklist_completed(self):
        for list_item in c.GUEST_CHECKLIST_ITEMS:
            item_status = getattr(self, list_item['name'] + '_status', None)
            if self.deadline_from_model(list_item['name']) and not item_status:
                return False
            elif item_status and 'Unclaimed' in item_status:
                return False
        return True

    def status(self, model):
        """
        This is a safe way to check if a step has been completed and
        what its status is for a particular group. It checks for a
        custom 'status' property for the step; if that doesn't exist, it
        will attempt to return True if an ID of the step exists or an
        empty string if not. If there's no corresponding deadline for
        the model we're checking, we return "N/A".

        Args:
         model: This should match one of the relationship columns in the
             GuestGroup class, e.g., 'bio' or 'taxes'.

        Returns:
            Returns either the 'status' property of the model, "N/A,"
            True, or an empty string.
        """

        if not self.deadline_from_model(model):
            return "N/A"

        subclass = getattr(self, model, None)
        if subclass:
            return getattr(subclass, 'status', getattr(subclass, 'id'))
        return ''
    
    def handle_images_from_params(self, session, **params):
        # Designed to let us add required header/thumbnail images for Super MAGFest
        # Ideally this will be refactored out when this is converted to WTForms
        message = ''
        bio_pic = params.get('bio_pic')
        if bio_pic and bio_pic.filename:
            new_pic = GuestImage.upload_image(bio_pic, guest_id=self.id)
            if new_pic.extension not in c.ALLOWED_BIO_PIC_EXTENSIONS:
                message = 'Bio pic must be one of ' + ', '.join(c.ALLOWED_BIO_PIC_EXTENSIONS)
            else:
                if self.bio_pic:
                    session.delete(self.bio_pic)
                session.add(new_pic)
        return message

    @property
    def sample_tracks(self):
        html = []
        for track in self.tracks:
            html.append(track.file)
        return Markup('<br/>'.join(html))
    
    @property
    def bio_pic(self):
        for image in self.images:
            if not image.is_header and not image.is_thumbnail:
                return image
        return ''

    @property
    def guidebook_header(self):
        for image in self.images:
            if image.is_header:
                return image
        return ''

    @property
    def guidebook_thumbnail(self):
        for image in self.images:
            if image.is_thumbnail:
                return image
        return ''
    
    @property
    def guidebook_edit_link(self):
        return f"../guests/bio?guest_id={self.id}"
    
    @property
    def guidebook_data(self):
        name = self.group.name if self.group else ''
        brackets = re.match(r'^\[.*\] ', name)
        if brackets:
            name = name[len(brackets[0]):]

        return {
            'guidebook_name': name,
            'guidebook_subtitle': self.group_type_label,
            'guidebook_desc': self.bio.desc if self.bio else '',
            'guidebook_location': '',
            'guidebook_header': self.guidebook_images[0][0],
            'guidebook_thumbnail': self.guidebook_images[0][1],
        }

    @property
    def guidebook_images(self):
        if not self.images:
            return ['', ''], ['', '']

        header = self.guidebook_header
        thumbnail = self.guidebook_thumbnail
        prepend = slugify(self.group.name if self.group else self.id) + '_'

        header_name = (prepend + header.filename) if header else ''
        thumbnail_name = (prepend + thumbnail.filename) if thumbnail else ''
        
        return [header_name, thumbnail_name], [header, thumbnail]


class GuestInfo(MagModel, table=True):
    """
    GuestGroup: joined
    """

    guest_id: str | None = Column(Uuid(as_uuid=False), ForeignKey('guest_group.id'), unique=True)
    poc_phone: str = Column(String)
    performer_count: int = Column(Integer, default=0)
    bringing_vehicle: bool = Column(Boolean, default=False)
    vehicle_info: str = Column(String)
    arrival_time: str = Column(String)

    @property
    def status(self):
        return "Yes" if self.poc_phone else ""


class GuestImage(MagModel, GuidebookImageMixin, table=True):
    guest_id: str | None = Column(Uuid(as_uuid=False), ForeignKey('guest_group.id'))

    @property
    def url(self):
        return '../guests/view_image?id={}'.format(self.id)

    @property
    def filepath(self):
        return os.path.join(c.GUESTS_BIO_PICS_DIR, str(self.id))

    @property
    def download_filename(self):
        name = self.guest.normalized_group_name
        return name + '.' + self.pic_extension


class GuestBio(MagModel, table=True):
    """
    GuestGroup: joined
    """

    guest_id: str | None = Column(Uuid(as_uuid=False), ForeignKey('guest_group.id'), unique=True)
    desc: str = Column(String)
    member_info: str = Column(String)
    website: str = Column(String)
    facebook: str = Column(String)
    twitter: str = Column(String)
    instagram: str = Column(String)
    twitch: str = Column(String)
    bandcamp: str = Column(String)
    discord: str = Column(String)
    spotify: str = Column(String)
    other_social_media: str = Column(String)
    teaser_song_url: str = Column(String)

    @property
    def status(self):
        return 'Yes' if self.desc else ''


class GuestTaxes(MagModel, table=True):
    """
    GuestGroup: joined
    """

    guest_id: str | None = Column(Uuid(as_uuid=False), ForeignKey('guest_group.id'), unique=True)
    w9_sent: bool = Column(Boolean, default=False)

    @property
    def status(self):
        return str(self.w9_sent)


class GuestStagePlot(MagModel, table=True):
    """
    GuestGroup: joined
    """

    guest_id: str | None = Column(Uuid(as_uuid=False), ForeignKey('guest_group.id'), unique=True)
    filename: str = Column(String)
    content_type: str = Column(String)
    notes: str = Column(String)

    @property
    def url(self):
        if self.uploaded_file:
            return '../guests/view_stage_plot?id={}'.format(self.guest.id)
        return ''

    @property
    def fpath(self):
        return os.path.join(c.GUESTS_STAGE_PLOTS_DIR, self.id)

    @property
    def uploaded_file(self):
        return os.path.exists(self.fpath)

    @property
    def stage_plot_extension(self):
        return filename_extension(self.filename)

    @property
    def download_filename(self):
        name = self.guest.normalized_group_name
        return name + '_stage_plot.' + self.stage_plot_extension

    @property
    def status(self):
        if self.url:
            return self.url
        return self.notes


class GuestPanel(MagModel, table=True):
    """
    GuestGroup: joined
    """

    guest_id: str | None = Column(Uuid(as_uuid=False), ForeignKey('guest_group.id'), unique=True)
    wants_panel: int | None = Column(Choice(c.GUEST_PANEL_OPTS), nullable=True)
    name: str = Column(String)
    length: str = Column(String)
    desc: str = Column(String)
    tech_needs: str = Column(MultiChoice(c.TECH_NEED_OPTS))
    other_tech_needs: str = Column(String)

    @property
    def status(self):
        return self.wants_panel_label


class GuestTrack(MagModel, table=True):
    """
    GuestGroup: joined
    """

    guest_id: str | None = Column(Uuid(as_uuid=False), ForeignKey('guest_group.id'))
    filename: str = Column(String)
    content_type: str = Column(String)
    extension: str = Column(String)

    @property
    def file(self):
        if not self.filename:
            return ''
        return Markup(
            f"""<a href="{self.url}" target="_blank">{self.filename}</a>""")

    @file.setter
    def file(self, value):
        import shutil
        import cherrypy

        if not isinstance(value, cherrypy._cpreqbody.Part):
            log.error(f"Tried to set music track for guest {self.guest.id} with invalid value type: {type(value)}")
            return

        self.filename = value.filename
        self.content_type = value.content_type.value
        self.extension = value.filename.split('.')[-1].lower()

        with open(self.filepath, 'wb') as f:
            shutil.copyfileobj(value.file, f)

    @property
    def url(self):
        return f"../guests/view_track?id={self.id}"

    @property
    def filepath(self):
        return os.path.join(c.GUESTS_INVENTORY_DIR, str('track_' + self.id))


class GuestMerch(MagModel, table=True):
    """
    GuestGroup: joined
    """

    _inventory_file_regex: ClassVar = re.compile(r'^(audio|image)(|\-\d+)$')
    _inventory_filename_regex: ClassVar = re.compile(r'^(audio|image)(|\-\d+)_filename$')

    guest_id: str | None = Column(Uuid(as_uuid=False), ForeignKey('guest_group.id'), unique=True)
    selling_merch: int | None = Column(Choice(c.GUEST_MERCH_OPTS), nullable=True)
    delivery_method: int | None = Column(Choice(c.GUEST_MERCH_DELIVERY_OPTS), nullable=True)
    payout_method: int | None = Column(Choice(c.GUEST_MERCH_PAYOUT_METHOD_OPTS), nullable=True)
    paypal_email: str = Column(String)
    check_payable: str = Column(String)
    check_zip_code: str = Column(String)
    check_address1: str = Column(String)
    check_address2: str = Column(String)
    check_city: str = Column(String)
    check_region: str = Column(String)
    check_country: str = Column(String)

    arrival_plans: str = Column(String)
    checkin_time: int | None = Column(Choice(c.GUEST_MERCH_CHECKIN_TIMES), nullable=True)
    checkout_time: int | None = Column(Choice(c.GUEST_MERCH_CHECKOUT_TIMES), nullable=True)
    merch_events: str = Column(String)
    inventory: dict[Any, Any] = Column(JSON, default={}, server_default='{}')
    inventory_updated: datetime | None = Column(DateTime(timezone=True), nullable=True)
    extra_info: str = Column(String)
    tax_phone: str = Column(String)

    poc_is_group_leader: bool = Column(Boolean, default=False)
    poc_first_name: str = Column(String)
    poc_last_name: str = Column(String)
    poc_phone: str = Column(String)
    poc_email: str = Column(String)
    poc_zip_code: str = Column(String)
    poc_address1: str = Column(String)
    poc_address2: str = Column(String)
    poc_city: str = Column(String)
    poc_region: str = Column(String)
    poc_country: str = Column(String)

    handlers: dict[str, Any] = Column(JSON, default=[], server_default='[]')

    @property
    def full_name(self):
        if self.poc_is_group_leader:
            return self.guest.group.leader.full_name
        elif self.poc_first_name or self.poc_last_name:
            return ' '.join([self.poc_first_name, self.poc_last_name])
        else:
            return ''

    @property
    def first_name(self):
        if self.poc_is_group_leader:
            return self.guest.group.leader.first_name
        return self.poc_first_name

    @property
    def last_name(self):
        if self.poc_is_group_leader:
            return self.guest.group.leader.last_name
        return self.poc_last_name

    @property
    def phone(self):
        if self.poc_is_group_leader:
            return self.guest.group.leader.cellphone or self.tax_phone or self.guest.info.poc_phone
        return self.poc_phone

    @property
    def email(self):
        if self.poc_is_group_leader:
            return self.guest.group.leader.email
        return self.poc_email

    @property
    def rock_island_url(self):
        return '../guest_reports/rock_island?id={}'.format(self.guest_id)

    @property
    def rock_island_csv_url(self):
        return '../guest_reports/rock_island_csv?id={}'.format(self.guest_id)
    
    @property
    def rock_island_square_export_url(self):
        return f'../guest_reports/rock_island_square_xlsx?id={self.guest_id}'
    
    @property
    def rock_island_image_zip_url(self):
        return f'../guest_reports/rock_island_image_zip?id={self.guest_id}'

    @property
    def status(self):
        if self.selling_merch == c.ROCK_ISLAND:
            notes = []
            if not self.inventory:
                notes.append("No Merch")
            if not self.checkin_time:
                notes.append("No Arrival Details")
            return self.selling_merch_label + ('' if not notes else f' ({', '.join(notes)})')
        return self.selling_merch_label

    @presave_adjustment
    def tax_phone_from_poc_phone(self):
        if self.selling_merch == c.OWN_TABLE and not self.tax_phone and self.guest and self.guest.info:
            self.tax_phone = self.guest.info.poc_phone

    @classmethod
    def extract_json_params(cls, params, field):
        multi_param_regex = re.compile(''.join(['^', field, r'_([\w_\-]+?)_(\d+)$']))
        single_param_regex = re.compile(''.join(['^', field, r'_([\w_\-]+?)$']))

        items = defaultdict(dict)
        single_item = dict()
        for param_name, value in filter(lambda i: i[1], params.items()):
            match = multi_param_regex.match(param_name)
            if match:
                name = match.group(1)
                item_number = int(match.group(2))
                items[item_number][name] = value
            else:
                match = single_param_regex.match(param_name)
                if match:
                    name = match.group(1)
                    single_item[name] = value

        if single_item:
            items[len(items)] = single_item

        return [item for item_number, item in sorted(items.items())]

    @classmethod
    def extract_inventory(cls, params):
        inventory = {}
        for item in cls.extract_json_params(params, 'inventory'):
            if not item.get('id'):
                item['id'] = str(uuid.uuid4())
            inventory[item['id']] = item
        return inventory

    @classmethod
    def extract_handlers(cls, params):
        return cls.extract_json_params(params, 'handlers')

    @classmethod
    def validate_inventory(cls, inventory):
        if not inventory:
            return 'You must add some merch to your inventory!'
        messages = []
        for item_id, item in inventory.items():
            for name, file in [(n, f) for (n, f) in item.items() if f]:
                match = cls._inventory_file_regex.match(name)
                if match and getattr(file, 'filename', None):
                    file_type = match.group(1).upper()
                    config_name = 'ALLOWED_INVENTORY_{}_EXTENSIONS'.format(file_type)
                    extensions = getattr(c, config_name, [])
                    ext = filename_extension(file.filename)
                    if extensions and ext not in extensions:
                        messages.append('{} files must be one of {}'.format(file_type.title(), ', '.join(extensions)))

        return '. '.join(dict.fromkeys([s.strip() for s in messages if s.strip()]))

    def _prune_inventory_file(self, item, new_inventory, *, prune_missing=False):

        for name, filename in list(item.items()):
            match = self._inventory_filename_regex.match(name)
            if match and filename:
                new_item = new_inventory.get(item['id'])
                if (prune_missing and not new_item) or (new_item and new_item.get(name) != filename):
                    filepath = self.inventory_path(filename)
                    if os.path.exists(filepath):
                        os.remove(filepath)

    def _prune_inventory_files(self, new_inventory, *, prune_missing=False):
        for item_id, item in self.inventory.items():
            self._prune_inventory_file(item, new_inventory, prune_missing=prune_missing)

    def _save_inventory_files(self, inventory):
        for item_id, item in inventory.items():
            for name, file in [(n, f) for (n, f) in item.items() if f]:
                match = self._inventory_file_regex.match(name)
                if match:
                    download_file_attr = '{}_download_filename'.format(name)
                    file_attr = '{}_filename'.format(name)
                    content_type_attr = '{}_content_type'.format(name)
                    del item[name]
                    if getattr(file, 'filename', None):
                        item[download_file_attr] = file.filename
                        item[file_attr] = str(uuid.uuid4())
                        item[content_type_attr] = file.content_type.value
                        item_path = self.inventory_path(item[file_attr])
                        with open(item_path, 'wb') as f:
                            shutil.copyfileobj(file.file, f)

                    attrs = [download_file_attr, file_attr, content_type_attr]

                    for attr in attrs:
                        if attr in item and not item[attr]:
                            del item[attr]

    @classmethod
    def item_subcategories(cls, item_type):
        s = {getattr(c, s): s for s in c.MERCH_TYPES_VARS}[int(item_type)]
        return (
            getattr(c, '{}_VARIETIES'.format(s), defaultdict(lambda: {})),
            getattr(c, '{}_CUTS'.format(s), defaultdict(lambda: {})),
            getattr(c, '{}_SIZES'.format(s), defaultdict(lambda: {})))

    @classmethod
    def item_subcategories_opts(cls, item_type):
        s = {getattr(c, s): s for s in c.MERCH_TYPES_VARS}[int(item_type)]
        return (
            getattr(c, '{}_VARIETIES_OPTS'.format(s), defaultdict(lambda: [])),
            getattr(c, '{}_CUTS_OPTS'.format(s), defaultdict(lambda: [])),
            getattr(c, '{}_SIZES_OPTS'.format(s), defaultdict(lambda: [])))

    @classmethod
    def line_items(cls, item):
        line_items = []

        for attr in filter(lambda s: s.startswith('quantity-'), item.keys()):
            qty = item[attr] if item[attr] else 0
            log.error(qty)
            if qty == 'on':
                qty = 1
            if int(qty) > 0:
                line_items.append(attr)

        varieties, cuts, sizes = [
            [v for (v, _) in x]
            for x in cls.item_subcategories_opts(item['type'])]

        def _line_item_sort_key(line_item):
            variety, cut, size = cls.line_item_to_types(line_item)
            return (
                varieties.index(variety) if variety else 0,
                cuts.index(cut) if cut else 0,
                sizes.index(size) if size else 0)

        return sorted(line_items, key=_line_item_sort_key)

    @classmethod
    def line_item_to_types(cls, line_item):
        return [int(s) for s in line_item.split('-')[1:]]

    @classmethod
    def line_item_to_string(cls, item, line_item):
        variety_val, cut_val, size_val = cls.line_item_to_types(line_item)

        varieties, cuts, sizes = cls.item_subcategories(item['type'])
        variety_label = varieties.get(variety_val, '').strip()
        if not size_val and not cut_val:
            return variety_label + ' - One size only'

        size_label = sizes.get(size_val, '').strip()
        cut_label = cuts.get(cut_val, '').strip()

        parts = [variety_label]
        if cut_label:
            parts.append(cut_label)
        if size_label:
            parts.extend(['-', size_label])
        return ' '.join(parts)

    @classmethod
    def inventory_path(cls, file):
        return os.path.join(c.GUESTS_INVENTORY_DIR, file)

    def inventory_url(self, item_id, name, download=False):
        disposition = 'inline' if not download else 'attachment'
        return '../guests/view_inventory_file?id={}&item_id={}&name={}&disposition={}'.format(
            self.id, item_id, name, disposition)

    def remove_inventory_item(self, item_id, *, persist_files=True):
        item = None
        if item_id in self.inventory:
            inventory = dict(self.inventory)
            item = inventory[item_id]
            del inventory[item_id]
            if persist_files:
                self._prune_inventory_file(item, inventory, prune_missing=True)
            self.inventory = inventory
            self.inventory_updated = datetime.now()
        return item

    def set_inventory(self, inventory, *, persist_files=True):
        if persist_files:
            self._save_inventory_files(inventory)
            self._prune_inventory_files(inventory, prune_missing=True)
        self.inventory = inventory
        self.inventory_updated = datetime.now()

    def update_inventory(self, inventory, *, persist_files=True):
        if persist_files:
            self._save_inventory_files(inventory)
            self._prune_inventory_files(inventory, prune_missing=False)
        self.inventory = dict(self.inventory, **inventory)
        self.inventory_updated = datetime.now()


class GuestCharity(MagModel, table=True):
    """
    GuestGroup: joined
    """

    guest_id: str | None = Column(Uuid(as_uuid=False), ForeignKey('guest_group.id'), unique=True)
    donating: int | None = Column(Choice(c.GUEST_CHARITY_OPTS), nullable=True)
    desc: str = Column(String)

    @property
    def status(self):
        return self.donating_label

    @presave_adjustment
    def no_desc_if_not_donating(self):
        if self.donating == c.NOT_DONATING:
            self.desc = ''


class GuestAutograph(MagModel, table=True):
    """
    GuestGroup: joined
    """

    guest_id: str | None = Column(Uuid(as_uuid=False), ForeignKey('guest_group.id'), unique=True)
    num: int = Column(Integer, default=0)
    length: int = Column(Integer, default=60)  # session length in minutes
    rock_island_autographs: bool | None = Column(Boolean, nullable=True)
    rock_island_length: int = Column(Integer, default=60)  # session length in minutes

    @presave_adjustment
    def no_length_if_zero_autographs(self):
        if not self.num:
            self.length = 0


class GuestInterview(MagModel, table=True):
    """
    GuestGroup: joined
    """

    guest_id: str | None = Column(Uuid(as_uuid=False), ForeignKey('guest_group.id'), unique=True)
    will_interview: bool = Column(Boolean, default=False)
    email: str = Column(String)
    direct_contact: bool = Column(Boolean, default=False)

    @presave_adjustment
    def no_details_if_no_interview(self):
        if not self.will_interview:
            self.email = ''
            self.direct_contact = False


class GuestTravelPlans(MagModel, table=True):
    """
    GuestGroup: joined
    GuestDetailedTravelPlan: selectin
    """

    guest_id: str | None = Column(Uuid(as_uuid=False), ForeignKey('guest_group.id'), unique=True)
    modes: str = Column(MultiChoice(c.GUEST_TRAVEL_OPTS), default=c.OTHER)
    modes_text: str = Column(String)
    details: str = Column(String)
    completed: bool = Column(Boolean, default=False)

    @property
    def num_detailed_travel_plans(self):
        return len(self.detailed_travel_plans)


class GuestHospitality(MagModel, table=True):
    """
    GuestGroup: joined
    """

    guest_id: str | None = Column(Uuid(as_uuid=False), ForeignKey('guest_group.id'), unique=True)
    completed: bool = Column(Boolean, default=False)


class GuestMediaRequest(MagModel, table=True):
    """
    GuestGroup: joined
    """

    guest_id: str | None = Column(Uuid(as_uuid=False), ForeignKey('guest_group.id'), unique=True)
    completed: bool = Column(Boolean, default=False)


class GuestDetailedTravelPlan(MagModel, table=True):
    """
    GuestTravelPlans: joined
    """

    travel_plans_id: str | None = Column(Uuid(as_uuid=False), ForeignKey('guest_travel_plans.id'), nullable=True)
    travel_plans: 'GuestTravelPlans' = Relationship(sa_relationship=relationship('GuestTravelPlans', foreign_keys=travel_plans_id, single_parent=True,
                                backref=backref('detailed_travel_plans', lazy='selectin'), lazy='joined',
                                cascade='save-update,merge,refresh-expire,expunge'))
    mode: int = Column(Choice(c.GUEST_TRAVEL_OPTS))
    mode_text: str = Column(String)
    traveller: str = Column(String)
    companions: str = Column(String)
    luggage_needs: str = Column(String)
    contact_email: str = Column(String)
    contact_phone: str = Column(String)
    arrival_time: datetime = Column(DateTime(timezone=True))
    arrival_details: str = Column(String)
    departure_time: datetime = Column(DateTime(timezone=True))
    departure_details: str = Column(String)
    extra_details: str = Column(String)

    @classproperty
    def min_arrival_time(self):
        return c.EPOCH - timedelta(days=7)

    @classproperty
    def max_arrival_time(self):
        return c.ESCHATON

    @classproperty
    def min_departure_time(self):
        return c.EPOCH

    @classproperty
    def max_departure_time(self):
        return c.ESCHATON + timedelta(days=7)
