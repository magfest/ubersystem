from sqlalchemy import or_
from sqlalchemy.orm import subqueryload

from uber.config import c
from uber.custom_tags import time_day_local
from uber.decorators import all_renderable, csv_file, site_mappable
from uber.errors import HTTPRedirect
from uber.models import Group, GuestAutograph, GuestGroup, GuestMerch, GuestTravelPlans
from uber.utils import convert_to_absolute_url


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
            'Twitter', 'Instagram', 'Twitch', 'Bandcamp', 'Discord', 'Other Social Media', 'Bio Pic', 'Bio Pic Link',
            'Wants Panel', 'Panel Name',
            'Panel Length', 'Panel Description', 'Panel Tech Needs',
            '# of Autograph Sessions', 'Autograph Session Length (Minutes)',
            'Wants RI Meet & Greet', 'Meet & Greet Length (Minutes)',
            'Completed W9', 'Stage Plot',
            'Selling Merchandise',
            'Charity Answer', 'Charity Donation',
            'Travel Mode(s)', 'Travel Mode(s) Text', 'Travel Details',
            'Needs Rehearsal?',
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
                getattr(guest.bio, 'twitter', ''), getattr(guest.bio, 'instagram', ''),
                getattr(guest.bio, 'twitch', ''), getattr(guest.bio, 'bandcamp', ''),
                getattr(guest.bio, 'discord', ''), getattr(guest.bio, 'other_social_media', ''),
                getattr(guest.bio, 'pic_filename', ''), absolute_pic_url,
                getattr(guest.panel, 'wants_panel', ''), getattr(guest.panel, 'name', ''),
                getattr(guest.panel, 'length', ''), getattr(guest.panel, 'desc', ''),
                ' / '.join(getattr(guest.panel, 'panel_tech_needs_labels', '')),
                getattr(guest.autograph, 'num', ''), getattr(guest.autograph, 'length', ''),
                getattr(guest.autograph, 'rock_island_autographs', ''), getattr(guest.autograph,
                                                                                'rock_island_length', ''),
                getattr(guest.taxes, 'w9_sent', ''), absolute_stageplot_url,
                getattr(guest.merch, 'selling_merch_label', ''),
                getattr(guest.charity, 'donating_label', ''), getattr(guest.charity, 'desc', ''),
                ' / '.join(getattr(guest.travel_plans, 'modes_labels', '')), getattr(guest.travel_plans,
                                                                                     'modes_text', ''),
                getattr(guest.travel_plans, 'details', ''), guest.rehearsal_status or 'N/A',
            ])

    @csv_file
    def detailed_travel_info_csv(self, out, session):
        out.writerow(['Guest Type', 'Group Name', 'Travel Mode', 'Travel Mode Text', 'Traveller', 'Companions',
                      'Luggage Needs', 'Contact Email', 'Contact Phone', 'Arrival Time',
                      'Arrival Details', 'Departure Time', 'Departure Details', 'Extra Details'])
        for travel_plan in session.query(GuestTravelPlans):
            for plan in travel_plan.detailed_travel_plans:
                content_row = [travel_plan.guest.group_type_label, travel_plan.guest.group.name]
                content_row.extend([plan.mode_label, plan.mode_text, plan.traveller, plan.companions,
                                    plan.luggage_needs, plan.contact_email, plan.contact_phone,
                                    time_day_local(plan.arrival_time), plan.arrival_details,
                                    time_day_local(plan.departure_time), plan.departure_details,
                                    plan.extra_details])
                out.writerow(content_row)

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

    @site_mappable(download=True)
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

    @csv_file
    def autograph_requests(self, out, session):
        out.writerow([
            'Group Name', '# of Sessions', 'Session Length (Minutes)', 'Wants RI Meet & Greet',
            'Meet & Greet Length (Minutes)'
        ])

        autograph_sessions = session.query(GuestAutograph
                                           ).filter(or_(GuestAutograph.num > 0,
                                                        GuestAutograph.rock_island_autographs == True))  # noqa: E712
        for request in autograph_sessions:
            out.writerow([request.guest.group.name,
                          request.num,
                          request.length,
                          request.rock_island_autographs,
                          request.rock_island_length])
