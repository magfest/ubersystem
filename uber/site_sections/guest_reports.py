import cherrypy
from pockets import readable_join
from sqlalchemy import and_, or_
from sqlalchemy.orm import subqueryload

from uber.config import c
from uber.decorators import ajax, all_renderable, csv_file, log_pageview, site_mappable
from uber.errors import HTTPRedirect
from uber.models import Email, Event, Group, GuestGroup, GuestMerch, PageViewTracking, Tracking
from uber.utils import check, convert_to_absolute_url


@all_renderable()
class Root:
    def index(self, session, message=''):
        HTTPRedirect('../group_admin/index')

    @csv_file
    def checklist_info_csv(self, out, session):
        out.writerow([
            'Guest Type', 'Group Name', 'Primary Contact Email',
            'Payment', 'Vehicles', 'Hotel Rooms',
            'Load-In', 'Performance Time',
            'PoC Cellphone', 'Performer Count',
            'Bringing Vehicle', 'Vehicle Info',
            'Arrival Time', 'Bio',
            'Website', 'Facebook',
            'Twitter', 'Other Social Media', 'Bio Pic', 'Bio Pic Link',
            'Wants Panel', 'Panel Name',
            'Panel Length', 'Panel Description', 'Panel Tech Needs',
            'Completed W9', 'Stage Plot',
            'Selling Merchandise',
            'Charity Answer', 'Charity Donation'
        ])
        for guest in [guest for guest in session.query(GuestGroup).all() if session.admin_can_see_guest_group(guest)]:
            absolute_pic_url = convert_to_absolute_url(getattr(guest.bio, 'pic_url', ''))
            absolute_stageplot_url = convert_to_absolute_url(getattr(guest.stage_plot, 'url', ''))
            out.writerow([
                guest.group_type_label, guest.group.name, guest.email,
                guest.payment, guest.vehicles, guest.num_hotel_rooms,
                guest.estimated_loadin_minutes, guest.estimated_performance_minutes,
                getattr(guest.info, 'poc_phone', ''), getattr(guest.info, 'performer_count', ''),
                getattr(guest.info, 'bringing_vehicle', ''), getattr(guest.info, 'vehicle_info', ''),
                getattr(guest.info, 'arrival_time', ''), getattr(guest.bio, 'desc', ''),
                getattr(guest.bio, 'website', ''), getattr(guest.bio, 'facebook', ''),
                getattr(guest.bio, 'twitter', ''), getattr(guest.bio, 'other_social_media', ''),
                getattr(guest.bio, 'pic_filename', ''), absolute_pic_url,
                getattr(guest.panel, 'wants_panel', ''), getattr(guest.panel, 'name', ''),
                getattr(guest.panel, 'length', ''), getattr(guest.panel, 'desc', ''),
                ' / '.join(getattr(guest.panel, 'panel_tech_needs_labels', '')),
                getattr(guest.taxes, 'w9_sent', ''), absolute_stageplot_url,
                getattr(guest.merch, 'selling_merch_label', ''),
                getattr(guest.charity, 'donating_label', ''), getattr(guest.charity, 'desc', '')
            ])
            
    @site_mappable
    def rock_island(self, session, message='', only_empty=None, id=None, **params):
        query = session.query(GuestGroup).options(
                subqueryload(GuestGroup.group)).options(
                subqueryload(GuestGroup.merch))
        if id:
            guest_groups = [query.get(id)]
        else:
            if only_empty:
                empty_filter = [GuestMerch.inventory == '{}']
            else:
                empty_filter = []
            guest_groups = query.filter(
                GuestGroup.id == GuestMerch.guest_id,
                GuestMerch.selling_merch == c.ROCK_ISLAND,
                GuestGroup.group_id == Group.id).filter(
                *empty_filter).order_by(Group.name).all()

        return {
            'guest_groups': [guest for guest in guest_groups if session.admin_can_see_guest_group(guest)],
            'only_empty': only_empty
        }

    @site_mappable
    @csv_file
    def rock_island_csv(self, out, session, id=None, **params):
        out.writerow([
            'Group Name', 'Inventory Type', 'Inventory Name', 'Price', 'Quantity', 'Promo Picture URL'
        ])
        query = session.query(GuestGroup).options(
                subqueryload(GuestGroup.group)).options(
                subqueryload(GuestGroup.merch))
        if id:
            guest_groups = [query.get(id)]
        else:
            guest_groups = query.filter(
                GuestGroup.id == GuestMerch.guest_id,
                GuestMerch.selling_merch == c.ROCK_ISLAND,
                GuestGroup.group_id == Group.id).order_by(
                Group.name).all()

        def _inventory_sort_key(item):
            return ' '.join([
                c.MERCH_TYPES[int(item['type'])],
                item['name'],
                item['price']
            ])

        for guest in [guest for guest in guest_groups if session.admin_can_see_guest_group(guest)]:
            for item in sorted(guest.merch.inventory.values(), key=_inventory_sort_key):
                merch_type = int(item['type'])
                if merch_type in (c.TSHIRT, c.APPAREL):
                    for line_item in guest.merch.line_items(item):
                        out.writerow([
                            guest.group.name,
                            c.MERCH_TYPES[merch_type],
                            '{} - {}'.format(item['name'], guest.merch.line_item_to_string(item, line_item)),
                            '${:.2f}'.format(float(item['price'])),
                            item[line_item],
                            convert_to_absolute_url(guest.merch.inventory_url(item['id'], 'image'))
                        ])
                else:
                    out.writerow([
                        guest.group.name,
                        c.MERCH_TYPES[merch_type],
                        item['name'],
                        '${:.2f}'.format(float(item['price'])),
                        guest.merch.total_quantity(item),
                        convert_to_absolute_url(guest.merch.inventory_url(item['id'], 'image'))
                    ])
