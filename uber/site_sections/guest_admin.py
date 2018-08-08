import cherrypy
from pockets import readable_join
from sqlalchemy.orm import subqueryload

from uber.config import c
from uber.decorators import ajax, all_renderable, csv_file, site_mappable
from uber.errors import HTTPRedirect
from uber.models import Event, Group, GuestGroup, GuestMerch
from uber.utils import check, convert_to_absolute_url


@all_renderable(c.BANDS)
class Root:

    def _required_message(self, params, fields):
        missing = [s for s in fields if not params.get(s, '').strip()]
        if missing:
            return '{} {} required'.format(
                readable_join([s.replace('_', ' ').title() for s in missing]),
                'is' if len(missing) == 1 else 'are')
        return ''

    def index(self, session, message='', filter='show-all'):
        return {
            'message': message,
            'groups': session.query(Group).order_by('name').all(),
            'groups_filter': filter
        }

    def add_group(self, session, message='', **params):
        group = session.group(params, checkgroups=Group.all_checkgroups, bools=Group.all_bools)
        if cherrypy.request.method == 'POST':
            message = self._required_message(
                params, ['name', 'first_name', 'last_name', 'email', 'group_type'])
            if not message:
                group.auto_recalc = False
                session.add(group)
                new_ribbon = c.BAND if params['group_type'] == str(c.BAND) else None
                message = session.assign_badges(
                    group,
                    params.get('badges', 1),
                    new_badge_type=c.GUEST_BADGE,
                    new_ribbon_type=new_ribbon,
                    paid=c.PAID_BY_GROUP)

            if not message:
                session.commit()
                leader = group.leader = group.attendees[0]
                leader.first_name = params.get('first_name')
                leader.last_name = params.get('last_name')
                leader.email = params.get('email')
                leader.placeholder = True
                message = check(leader)
                if not message:
                    group.guest = GuestGroup()
                    group.guest.group_type = params['group_type']
                    session.commit()
                    raise HTTPRedirect('index?message={} has been uploaded', group.name)
                else:
                    session.delete(group)

        return {
            'message': message,
            'group': group,
            'first_name': params.get('first_name', ''),
            'last_name': params.get('last_name', ''),
            'email': params.get('email', '')
        }

    @ajax
    def mark_as_guest(self, session, group_id, group_type=None):
        group = session.group(group_id)
        if not group.leader:
            return {'message': '{} does not have an assigned group leader'.format(group.name)}
        elif not group_type:
            return {'message': 'Please select a group type.'}

        if not group.guest:
            group.guest = GuestGroup()
            group.guest.group_type = group_type
            session.commit()

        return {
            'id': group.guest.id,
            'message': '{} has been marked as a {}'.format(group.name, group.guest.group_type_label)
        }

    @ajax
    def remove_as_guest(self, session, group_id):
        group = session.group(group_id)
        group_type_label = group.guest.group_type_label

        if group.guest:
            group.guest = None
            session.commit()

        return {
            'id': group.id,
            'message': '{} has been removed as a {}'.format(group.name, group_type_label)
        }

    def group_info(self, session, message='', event_id=None, **params):
        guest = session.guest_group(params)
        if cherrypy.request.method == 'POST':
            if event_id:
                guest.event_id = event_id
            if not message:
                raise HTTPRedirect('index?message={}{}', guest.group.name, ' data uploaded')

        events = session.query(Event).filter_by(location=c.CONCERTS).order_by(Event.start_time).all()
        return {
            'guest': guest,
            'message': message,
            'events': [(event.id, event.name) for event in events]
        }

    @csv_file
    def everything(self, out, session):
        out.writerow([
            'Group Name', 'Primary Contact Email',
            'Payment', 'Vehicles', 'Hotel Rooms',
            'Load-In', 'Performance Time',
            'PoC Cellphone', 'Performer Count',
            'Bringing Vehicle', 'Vehicle Info',
            'Arrival Time', 'Bio',
            'Website', 'Facebook',
            'Twitter', 'Other Social Media', 'Bio Pic',
            'Wants Panel', 'Panel Name',
            'Panel Length', 'Panel Description', 'Panel Tech Needs',
            'Completed W9', 'Stage Plot',
            'Selling Merchandise',
            'Charity Answer', 'Charity Donation'
        ])
        for guest in session.query(GuestGroup).all():
            absolute_pic_url = convert_to_absolute_url(getattr(guest.bio, 'pic_url', ''))
            absolute_w9_url = convert_to_absolute_url(getattr(guest.taxes, 'w9_url', ''))
            absolute_stageplot_url = convert_to_absolute_url(getattr(guest.stage_plot, 'url', ''))
            out.writerow([
                guest.group.name, guest.email,
                guest.payment, guest.vehicles, guest.num_hotel_rooms,
                guest.estimated_loadin_minutes, guest.estimated_performance_minutes,
                getattr(guest.info, 'poc_phone', ''), getattr(guest.info, 'performer_count', ''),
                getattr(guest.info, 'bringing_vehicle', ''), getattr(guest.info, 'vehicle_info', ''),
                getattr(guest.info, 'arrival_time', ''), getattr(guest.bio, 'desc', ''),
                getattr(guest.bio, 'website', ''), getattr(guest.bio, 'facebook', ''),
                getattr(guest.bio, 'twitter', ''), getattr(guest.bio, 'other_social_media', ''), absolute_pic_url,
                getattr(guest.panel, 'wants_panel', ''), getattr(guest.panel, 'name', ''),
                getattr(guest.panel, 'length', ''), getattr(guest.panel, 'desc', ''),
                ' / '.join(getattr(guest.panel, 'panel_tech_needs_labels', '')),
                absolute_w9_url, absolute_stageplot_url,
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
            'guest_groups': guest_groups,
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
                        convert_to_absolute_url(guest.merch.inventory_url(item['id'], 'image'))
                    ])
