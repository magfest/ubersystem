import os
import re
import shutil
import uuid
from collections import defaultdict

from pockets import uniquify
from residue import JSON, CoerceUTF8 as UnicodeText, UUID
from sqlalchemy.orm import backref
from sqlalchemy.schema import ForeignKey
from sqlalchemy.types import Boolean, Integer

from uber.config import c
from uber.custom_tags import yesno
from uber.decorators import presave_adjustment
from uber.models import MagModel
from uber.models.types import default_relationship as relationship, Choice, DefaultColumn as Column, MultiChoice
from uber.utils import filename_extension


__all__ = [
    'GuestGroup', 'GuestInfo', 'GuestBio', 'GuestTaxes', 'GuestStagePlot',
    'GuestPanel', 'GuestMerch', 'GuestCharity', 'GuestAutograph',
    'GuestInterview', 'GuestTravelPlans']


class GuestGroup(MagModel):
    group_id = Column(UUID, ForeignKey('group.id'))
    event_id = Column(UUID, ForeignKey('event.id', ondelete='SET NULL'), nullable=True)
    group_type = Column(Choice(c.GROUP_TYPE_OPTS), default=c.BAND)
    num_hotel_rooms = Column(Integer, default=1, admin_only=True)
    payment = Column(Integer, default=0, admin_only=True)
    vehicles = Column(Integer, default=1, admin_only=True)
    estimated_loadin_minutes = Column(Integer, default=c.DEFAULT_LOADIN_MINUTES, admin_only=True)
    estimated_performance_minutes = Column(Integer, default=c.DEFAULT_PERFORMANCE_MINUTES, admin_only=True)

    wants_mc = Column(Boolean, nullable=True)
    needs_rehearsal = Column(Choice(c.GUEST_REHEARSAL_OPTS), nullable=True)
    info = relationship('GuestInfo', backref=backref('guest', load_on_pending=True), uselist=False)
    bio = relationship('GuestBio', backref=backref('guest', load_on_pending=True), uselist=False)
    taxes = relationship('GuestTaxes', backref=backref('guest', load_on_pending=True), uselist=False)
    stage_plot = relationship('GuestStagePlot', backref=backref('guest', load_on_pending=True), uselist=False)
    panel = relationship('GuestPanel', backref=backref('guest', load_on_pending=True), uselist=False)
    merch = relationship('GuestMerch', backref=backref('guest', load_on_pending=True), uselist=False)
    charity = relationship('GuestCharity', backref=backref('guest', load_on_pending=True), uselist=False)
    autograph = relationship('GuestAutograph', backref=backref('guest', load_on_pending=True), uselist=False)
    interview = relationship('GuestInterview', backref=backref('guest', load_on_pending=True), uselist=False)
    travel_plans = relationship('GuestTravelPlans', backref=backref('guest', load_on_pending=True), uselist=False)

    email_model_name = 'guest'

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
        name = str(self.group_type_label).upper() + "_" + str(model).upper() + "_DEADLINE"
        return getattr(c, name, None)
    
    @property
    def sorted_checklist_items(self):
        checklist_items = []
        for item in c.GUEST_CHECKLIST_ITEMS:
            if self.deadline_from_model(item['name']):
                checklist_items.append(item)
                
        return sorted(checklist_items, key= lambda i: self.deadline_from_model(i['name']))

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
    def panel_status(self):
        application_count = len(self.group.leader.panel_applications)
        return '{} Panel Application(s)'.format(application_count) \
            if self.group.leader.panel_applications else self.status('panel')

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

    @property
    def guidebook_name(self):
        return self.group.name if self.group else ''

    @property
    def guidebook_subtitle(self):
        return self.group_type_label

    @property
    def guidebook_desc(self):
        return self.bio.desc if self.bio else ''

    @property
    def guidebook_image(self):
        return self.bio.pic_filename if self.bio else ''

    @property
    def guidebook_thumbnail(self):
        return self.bio.pic_filename if self.bio else ''

    @property
    def guidebook_images(self):
        if not self.bio:
            return ['', '']

        return [self.bio.pic_filename], [self.bio]


class GuestInfo(MagModel):
    guest_id = Column(UUID, ForeignKey('guest_group.id'), unique=True)
    poc_phone = Column(UnicodeText)
    performer_count = Column(Integer, default=0)
    bringing_vehicle = Column(Boolean, default=False)
    vehicle_info = Column(UnicodeText)
    arrival_time = Column(UnicodeText)

    @property
    def status(self):
        return "Yes" if self.poc_phone else ""


class GuestBio(MagModel):
    guest_id = Column(UUID, ForeignKey('guest_group.id'), unique=True)
    desc = Column(UnicodeText)
    website = Column(UnicodeText)
    facebook = Column(UnicodeText)
    twitter = Column(UnicodeText)
    other_social_media = Column(UnicodeText)
    teaser_song_url = Column(UnicodeText)

    pic_filename = Column(UnicodeText)
    pic_content_type = Column(UnicodeText)

    @property
    def pic_url(self):
        if self.uploaded_pic:
            return '../guests/view_bio_pic?id={}'.format(self.guest.id)
        return ''

    @property
    def pic_fpath(self):
        return os.path.join(c.GUESTS_BIO_PICS_DIR, self.id)

    @property
    def uploaded_pic(self):
        return os.path.exists(self.pic_fpath)

    @property
    def pic_extension(self):
        return filename_extension(self.pic_filename)

    @property
    def download_filename(self):
        name = self.guest.normalized_group_name
        return name + '_bio_pic.' + self.pic_extension

    @property
    def status(self):
        return 'Yes' if self.desc else ''


class GuestTaxes(MagModel):
    guest_id = Column(UUID, ForeignKey('guest_group.id'), unique=True)
    w9_sent = Column(Boolean, default=False)

    @property
    def status(self):
        return str(self.w9_sent)


class GuestStagePlot(MagModel):
    guest_id = Column(UUID, ForeignKey('guest_group.id'), unique=True)
    filename = Column(UnicodeText)
    content_type = Column(UnicodeText)

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
        return self.url if self.url else ''


class GuestPanel(MagModel):
    guest_id = Column(UUID, ForeignKey('guest_group.id'), unique=True)
    wants_panel = Column(Choice(c.GUEST_PANEL_OPTS), nullable=True)
    name = Column(UnicodeText)
    length = Column(UnicodeText)
    desc = Column(UnicodeText)
    tech_needs = Column(MultiChoice(c.TECH_NEED_OPTS))
    other_tech_needs = Column(UnicodeText)

    @property
    def status(self):
        return self.wants_panel_label


class GuestMerch(MagModel):
    _inventory_file_regex = re.compile(r'^(audio|image)(|\-\d+)$')
    _inventory_filename_regex = re.compile(r'^(audio|image)(|\-\d+)_filename$')

    guest_id = Column(UUID, ForeignKey('guest_group.id'), unique=True)
    selling_merch = Column(Choice(c.GUEST_MERCH_OPTS), nullable=True)
    inventory = Column(JSON, default={}, server_default='{}')
    bringing_boxes = Column(UnicodeText)
    extra_info = Column(UnicodeText)
    tax_phone = Column(UnicodeText)

    poc_is_group_leader = Column(Boolean, default=False)
    poc_first_name = Column(UnicodeText)
    poc_last_name = Column(UnicodeText)
    poc_phone = Column(UnicodeText)
    poc_email = Column(UnicodeText)
    poc_zip_code = Column(UnicodeText)
    poc_address1 = Column(UnicodeText)
    poc_address2 = Column(UnicodeText)
    poc_city = Column(UnicodeText)
    poc_region = Column(UnicodeText)
    poc_country = Column(UnicodeText)

    handlers = Column(JSON, default=[], server_default='[]')

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
        return '../guest_admin/rock_island?id={}'.format(self.guest_id)

    @property
    def rock_island_csv_url(self):
        return '../guest_admin/rock_island_csv?id={}'.format(self.guest_id)

    @property
    def status(self):
        if self.selling_merch == c.ROCK_ISLAND:
            return self.selling_merch_label + ('' if self.inventory else ' (No Merch)')
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
            quantity = int(item.get('quantity') or 0)
            if quantity <= 0 and cls.total_quantity(item) <= 0:
                messages.append('You must specify some quantity')
            for name, file in [(n, f) for (n, f) in item.items() if f]:
                match = cls._inventory_file_regex.match(name)
                if match and getattr(file, 'filename', None):
                    file_type = match.group(1).upper()
                    config_name = 'ALLOWED_INVENTORY_{}_EXTENSIONS'.format(file_type)
                    extensions = getattr(c, config_name, [])
                    ext = filename_extension(file.filename)
                    if extensions and ext not in extensions:
                        messages.append('{} files must be one of {}'.format(file_type.title(), ', '.join(extensions)))

        return '. '.join(uniquify([s.strip() for s in messages if s.strip()]))

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
    def total_quantity(cls, item):
        total_quantity = 0
        for attr in filter(lambda s: s.startswith('quantity'), item.keys()):
            total_quantity += int(item[attr] if item[attr] else 0)
        return total_quantity

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
            if int(item[attr] if item[attr] else 0) > 0:
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

    def inventory_url(self, item_id, name):
        return '../guests/view_inventory_file?id={}&item_id={}&name={}'.format(self.id, item_id, name)

    def remove_inventory_item(self, item_id, *, persist_files=True):
        item = None
        if item_id in self.inventory:
            inventory = dict(self.inventory)
            item = inventory[item_id]
            del inventory[item_id]
            if persist_files:
                self._prune_inventory_file(item, inventory, prune_missing=True)
            self.inventory = inventory
        return item

    def set_inventory(self, inventory, *, persist_files=True):
        if persist_files:
            self._save_inventory_files(inventory)
            self._prune_inventory_files(inventory, prune_missing=True)
        self.inventory = inventory

    def update_inventory(self, inventory, *, persist_files=True):
        if persist_files:
            self._save_inventory_files(inventory)
            self._prune_inventory_files(inventory, prune_missing=False)
        self.inventory = dict(self.inventory, **inventory)


class GuestCharity(MagModel):
    guest_id = Column(UUID, ForeignKey('guest_group.id'), unique=True)
    donating = Column(Choice(c.GUEST_CHARITY_OPTS), nullable=True)
    desc = Column(UnicodeText)

    @property
    def status(self):
        return self.donating_label

    @presave_adjustment
    def no_desc_if_not_donating(self):
        if self.donating == c.NOT_DONATING:
            self.desc = ''


class GuestAutograph(MagModel):
    guest_id = Column(UUID, ForeignKey('guest_group.id'), unique=True)
    num = Column(Integer, default=0)
    length = Column(Integer, default=60)  # session length in minutes

    @presave_adjustment
    def no_length_if_zero_autographs(self):
        if not self.num:
            self.length = 0


class GuestInterview(MagModel):
    guest_id = Column(UUID, ForeignKey('guest_group.id'), unique=True)
    will_interview = Column(Boolean, default=False)
    email = Column(UnicodeText)
    direct_contact = Column(Boolean, default=False)

    @presave_adjustment
    def no_details_if_no_interview(self):
        if not self.will_interview:
            self.email = ''
            self.direct_contact = False


class GuestTravelPlans(MagModel):
    guest_id = Column(UUID, ForeignKey('guest_group.id'), unique=True)
    modes = Column(MultiChoice(c.GUEST_TRAVEL_OPTS))
    modes_text = Column(UnicodeText)
    details = Column(UnicodeText)
