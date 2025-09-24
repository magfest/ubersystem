from sqlalchemy import or_
from sqlalchemy.orm import subqueryload

from uber.config import c
from uber.custom_tags import time_day_local
from uber.decorators import all_renderable, csv_file, site_mappable, xlsx_file
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
            '# Panel Applications',
            '# of Autograph Sessions', 'Autograph Session Length (Minutes)',
            'Wants RI Meet & Greet', 'Meet & Greet Length (Minutes)',
            'Completed W9', 'Stage Plot',
            'Selling Merchandise',
            'Charity Answer', 'Charity Donation',
            'Travel Mode(s)', 'Travel Mode(s) Text', 'Travel Details',
            'Needs Rehearsal?',
        ])
        for guest in [guest for guest in session.query(GuestGroup).all() if session.admin_can_see_guest_group(guest)]:
            absolute_pic_url = convert_to_absolute_url(getattr(guest.bio_pic, 'url', ''))
            absolute_stageplot_url = convert_to_absolute_url(getattr(guest.stage_plot, 'url', ''))
            num_panels = 0 if not guest.group or not guest.group.leader or not guest.group.leader.submitted_panels \
                else len(guest.group.leader.submitted_panels)

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
                getattr(guest.bio, 'pic_filename', ''), absolute_pic_url, num_panels,
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
        for travel_plan in [plan for plan in session.query(GuestTravelPlans).all() if session.admin_can_see_guest_group(plan.guest)]:
            for plan in travel_plan.detailed_travel_plans:
                content_row = [travel_plan.guest.group_type_label, travel_plan.guest.group.name]
                content_row.extend([plan.mode_label, plan.mode_text, plan.traveller, plan.companions,
                                    plan.luggage_needs, plan.contact_email, plan.contact_phone,
                                    time_day_local(plan.arrival_time), plan.arrival_details,
                                    time_day_local(plan.departure_time), plan.departure_details,
                                    plan.extra_details])
                out.writerow(content_row)
    
    @csv_file
    def panel_info_csv(self, out, session):
        out.writerow(['Guest', 'App Status', 'Name', 'Description', 'Schedule Description', 'Length',
                      'Department', 'Type of Panel', 'Location', 'Date/Time'])
        for guest in [guest for guest in session.query(GuestGroup).all() if session.admin_can_see_guest_group(guest)]:
            if guest.group and guest.group.leader:
                for app in guest.group.leader.submitted_panels:
                    out.writerow([
                        guest.group.name, app.status_label,
                        getattr(app.event, 'name', app.name),
                        getattr(app.event, 'description', app.description),
                        getattr(app.event, 'public_description', app.public_description),
                        f"{app.event.duration} minutes" if app.event else f"{app.length_label} (expected)",
                        app.department_label,
                        app.other_presentation if app.presentation == c.OTHER else app.presentation_label,
                        getattr(app.event, 'location_label', '(not scheduled)'),
                        app.event.timespan() if app.event else '(not scheduled)',
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
    
    @site_mappable(download=True)
    @xlsx_file
    def rock_island_square_xlsx(self, out, session, id=None, **params):
        header_row = [
            'Token', 'Item Name', 'Variation Name', 'Unit and Precision', 'SKU', 'Description', 'Category',
            'SEO Title', 'SEO Description', 'Permalink', 'Square Online Item Visibility', 'Weight (lb)', 'Shipping Enabled',
            'Self-serve Ordering Enabled', 'Delivery Enabled', 'Pickup Enabled', 'Price', 'Sellable', 'Stockable',
            'Skip Detail Screen in POS', 'Option Name 1', 'Option Value 1', 'Current Quantity MAGFest Rock Island',
            'New Quantity MAGFest Rock Island'
            ]
        
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
        
        rows = []
        item_type_square_name = {
            c.CD: "MUSIC",
            c.TSHIRT: "APPAREL",
            c.APPAREL: "APPAREL",
            c.PIN: "PIN",
            c.STICKER: "STICKER",
            c.POSTER: "POSTER",
            c.BUTTON: "BUTTON",
            c.PATCH: "PATCH",
            c.MISCELLANEOUS: "MISC",
        }

        def _inventory_sort_key(item):
            return ' '.join([
                c.MERCH_TYPES[int(item['type'])],
                item['name']
            ])

        def _generate_row(item, guest, variation_name='Regular'):
            item_type = int(item['type'])
            item_name = f'{item_type_square_name[item_type]} {guest.group.name} {item['name']}'
            if item_type == c.CD:
                item_name = f'{item_name} {c.ALBUM_MEDIAS[int(item['media'])]}'
            elif item_type == c.TSHIRT:
                item_name = f'{item_name} T-shirt'

            return [
                '', item_name, variation_name, '', '', '', guest.group.name, '', '', '',
                'hidden', '', 'N', '', 'N', 'N', '{:.2f}'.format(float(item['price'])),
                '', '', 'N', '', '', '', ''
            ]

        for guest in guest_groups:
            for item in sorted(guest.merch.inventory.values(), key=_inventory_sort_key):
                merch_type = int(item['type'])
                if merch_type in (c.TSHIRT, c.APPAREL):
                    for line_item in guest.merch.line_items(item):
                        rows.append(_generate_row(item, guest, guest.merch.line_item_to_string(item, line_item)))
                else:
                    rows.append(_generate_row(item, guest))
        out.writerows(header_row, rows)

    @site_mappable(download=True)
    @csv_file
    def rock_island_csv(self, out, session, id=None, **params):
        out.writerow([
            'Group Name', 'Inventory Type', 'Inventory Name', 'Price', 'Quantity', 'Promo Picture URL',
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

        for guest in guest_groups:
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
                        convert_to_absolute_url(guest.merch.inventory_url(item['id'], 'image')),
                    ])

    @csv_file
    def rock_island_info_csv(self, out, session):
        guest_groups = session.query(GuestGroup).options(
                subqueryload(GuestGroup.group)).options(
                subqueryload(GuestGroup.merch)).filter(
                    GuestGroup.id == GuestMerch.guest_id,
                    GuestMerch.selling_merch == c.ROCK_ISLAND,
                    GuestGroup.group_id == Group.id).order_by(
                        Group.name).all()

        out.writerow(['Group Name', 'PoC Name', 'PoC Phone #', 'PoC Email', 'PoC Address 1', 'PoC Address 2',
                      'PoC City', 'PoC Region', 'PoC ZipCode', 'PoC Country', 'Meet N Greet', 'Delivery Method',
                      'Preferred Payout Method', 'Payout Info', 'Trusted Handlers', 'Check-In', 'Check-Out',
                      'Arrival/Departure Plans'])

        def attr_or_not_set(guest_merch, attr):
            if guest_merch.full_name:
                return getattr(guest_merch, attr, '')
            else:
                return "Not Set"

        for guest in guest_groups:
            if not guest.autograph:
                meet_greet = "Not Selected"
            else:
                meet_greet = "Yes" if guest.autograph.rock_island_autographs else "No"
            
            if guest.merch.payout_method == c.PAYPAL:
                payout_info = guest.merch.paypal_email
            elif guest.merch.payout_method == c.CHECK:
                payout_info = guest.merch.check_payable
            else:
                payout_info = "N/A"

            if guest.merch.handlers:
                trusted_handlers = [
                    f"{handler.get('first_name', '').strip()} {handler.get('last_name', '').strip()}".strip()
                    for handler in guest.merch.handlers]
            else:
                trusted_handlers = ["None"]

            out.writerow([guest.group.name, attr_or_not_set(guest.merch, 'full_name'),
                          attr_or_not_set(guest.merch, 'phone'), attr_or_not_set(guest.merch, 'email'),
                          attr_or_not_set(guest.merch, 'poc_address1'), attr_or_not_set(guest.merch, 'poc_address2'),
                          attr_or_not_set(guest.merch, 'poc_city'), attr_or_not_set(guest.merch, 'poc_region'),
                          attr_or_not_set(guest.merch, 'poc_zip_code'), attr_or_not_set(guest.merch, 'poc_country'),
                          meet_greet, guest.merch.delivery_method_label, guest.merch.payout_method_label, payout_info,
                          ', '.join(trusted_handlers), attr_or_not_set(guest.merch, 'checkin_time_label'),
                          attr_or_not_set(guest.merch, 'checkout_time_label'), attr_or_not_set(guest.merch, 'arrival_plans')
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
