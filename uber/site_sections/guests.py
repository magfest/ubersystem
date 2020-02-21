import os
import shutil

import cherrypy
from cherrypy.lib.static import serve_file

from uber.config import c
from uber.decorators import ajax, all_renderable
from uber.errors import HTTPRedirect
from uber.models import GuestMerch
from uber.utils import check


@all_renderable(public=True)
class Root:
    def index(self, session, id, message=''):
        guest = session.guest_group(id)

        return {
            'message': message,
            'guest': guest,
        }

    def agreement(self, session, guest_id, message='', **params):
        guest = session.guest_group(guest_id)
        guest_info = session.guest_info(params, restricted=True)
        if cherrypy.request.method == 'POST':
            if not guest_info.performer_count:
                message = 'You must tell us how many people are in your group'
            elif not guest_info.poc_phone:
                message = 'You must enter an on-site point-of-contact cellphone number'
            elif not guest_info.arrival_time and not guest.group_type == c.GUEST:
                message = 'You must enter your expected arrival time'
            elif guest_info.bringing_vehicle and not guest_info.vehicle_info:
                message = 'You must provide your vehicle information'
            else:
                guest.info = guest_info
                session.add(guest_info)
                raise HTTPRedirect('index?id={}&message={}', guest.id, 'Your group information has been uploaded')

        return {
            'guest': guest,
            'guest_info': guest.info or guest_info,
            'message': message
        }

    def bio(self, session, guest_id, message='', bio_pic=None, **params):
        guest = session.guest_group(guest_id)
        guest_bio = session.guest_bio(params, restricted=True)
        if cherrypy.request.method == 'POST':
            if not guest_bio.desc:
                message = 'Please provide a brief bio for our website'

            if not message and bio_pic.filename:
                guest_bio.pic_filename = bio_pic.filename
                guest_bio.pic_content_type = bio_pic.content_type.value
                if guest_bio.pic_extension not in c.ALLOWED_BIO_PIC_EXTENSIONS:
                    message = 'Bio pic must be one of ' + ', '.join(c.ALLOWED_BIO_PIC_EXTENSIONS)
                else:
                    with open(guest_bio.pic_fpath, 'wb') as f:
                        shutil.copyfileobj(bio_pic.file, f)

            if not message:
                guest.bio = guest_bio
                session.add(guest_bio)
                raise HTTPRedirect('index?id={}&message={}', guest.id, 'Your bio information has been updated')

        return {
            'guest': guest,
            'guest_bio': guest.bio or guest_bio,
            'message': message
        }

    @cherrypy.expose(['w9'])
    def taxes(self, session, guest_id=None, message='', w9=None, **params):
        if not guest_id:
            guest_id = params.pop('id', None)
        assert guest_id, 'Either a guest_id or id is required'
        guest = session.guest_group(guest_id)
        guest_taxes = session.guest_taxes(params, restricted=True)
        if cherrypy.request.method == 'POST':
            if not guest_taxes.w9_sent:
                message = 'You must confirm that you have uploaded your W9 at the secure document portal'
            else:
                guest.taxes = guest_taxes
                session.add(guest_taxes)
                raise HTTPRedirect('index?id={}&message={}', guest.id, 'Thank you for sending in your W9!')

        return {
            'guest': guest,
            'guest_taxes': guest.taxes or guest_taxes,
            'message': message
        }

    def stage_plot(self, session, guest_id, message='', plot=None, **params):
        guest = session.guest_group(guest_id)
        guest_stage_plot = session.guest_stage_plot(params, restricted=True)
        if cherrypy.request.method == 'POST':
            guest_stage_plot.filename = plot.filename
            guest_stage_plot.content_type = plot.content_type.value
            if guest_stage_plot.stage_plot_extension not in c.ALLOWED_STAGE_PLOT_EXTENSIONS:
                message = 'Uploaded file type must be one of ' + ', '.join(c.ALLOWED_STAGE_PLOT_EXTENSIONS)
            else:
                with open(guest_stage_plot.fpath, 'wb') as f:
                    shutil.copyfileobj(plot.file, f)
                guest.stage_plot = guest_stage_plot
                session.add(guest_stage_plot)
                raise HTTPRedirect('index?id={}&message={}', guest.id, 'Stage directions uploaded')

        return {
            'guest': guest,
            'guest_stage_plot': guest.stage_plot or guest_stage_plot,
            'message': message
        }

    def panel(self, session, guest_id, message='', **params):
        guest = session.guest_group(guest_id)
        guest_panel = session.guest_panel(params, checkgroups=['tech_needs'])
        if cherrypy.request.method == 'POST':
            if not guest_panel.wants_panel:
                message = 'You need to tell us whether you want to present a panel'
            elif guest_panel.wants_panel == c.NO_PANEL:
                guest_panel.name = guest_panel.length = guest_panel.desc = guest_panel.tech_needs = ''
            elif not guest_panel.name:
                message = 'Panel Name is a required field'
            elif not guest_panel.length:
                message = 'Panel Length is a required field'
            elif not guest_panel.desc:
                message = 'Panel Description is a required field'

            if not message:
                guest.panel = guest_panel
                session.add(guest_panel)
                raise HTTPRedirect('index?id={}&message={}', guest.id, 'Panel preferences updated')

        return {
            'guest': guest,
            'guest_panel': guest.panel or guest_panel,
            'message': message
        }

    def mc(self, session, guest_id, message='', **params):
        guest = session.guest_group(guest_id)
        if cherrypy.request.method == 'POST':
            guest.wants_mc = bool(params.get('wants_mc', False))
            raise HTTPRedirect('index?id={}&message={}', guest.id, 'MC preferences updated')

        return {
            'guest': guest,
            'message': message
        }

    def rehearsal(self, session, guest_id, message='', **params):
        guest = session.guest_group(guest_id)
        if cherrypy.request.method == 'POST':
            if not params.get('needs_rehearsal'):
                message = "Please select an option for your rehearsal needs."
            if not message:
                guest.needs_rehearsal = params.get('needs_rehearsal')
                raise HTTPRedirect('index?id={}&message={}', guest.id, 'Rehearsal needs updated')

        return {
            'guest': guest,
            'message': message
        }

    def merch(self, session, guest_id, message='', coverage=False, warning=False, **params):
        guest = session.guest_group(guest_id)
        guest_merch = session.guest_merch(params, checkgroups=GuestMerch.all_checkgroups, bools=GuestMerch.all_bools)
        guest_merch.handlers = guest_merch.extract_handlers(params)
        group_params = dict()
        if cherrypy.request.method == 'POST':
            message = check(guest_merch)
            if not message:
                if c.REQUIRE_DEDICATED_GUEST_TABLE_PRESENCE \
                        and guest_merch.selling_merch == c.OWN_TABLE \
                        and guest.group_type == c.BAND \
                        and not all([coverage, warning]):

                    message = 'You cannot staff your own table without checking the boxes to agree to our conditions'
                elif guest.group_type == c.GUEST and guest_merch.selling_merch == c.OWN_TABLE:
                    for field_name in ['country', 'region', 'zip_code', 'address1', 'address2', 'city']:
                        group_params[field_name] = params.get(field_name, '')

                    if not guest.info and not guest_merch.tax_phone:
                        message = 'You must provide a phone number for tax purposes.'
                    elif not (params.get('country')
                              and params.get('region')
                              and params.get('zip_code')
                              and params.get('address1')
                              and params.get('city')):

                        message = 'You must provide an address for tax purposes.'
                    else:
                        guest.group.apply(group_params, restricted=True)
            if not message:
                guest.merch = guest_merch
                session.add(guest_merch)
                raise HTTPRedirect('index?id={}&message={}', guest.id, 'Your merchandise preferences have been saved')
        else:
            guest_merch = guest.merch

        return {
            'guest': guest,
            'guest_merch': guest_merch,
            'group': group_params or guest.group,
            'message': message
        }

    @ajax
    def save_inventory_item(self, session, guest_id, **params):
        guest = session.guest_group(guest_id)
        if guest.merch:
            guest_merch = guest.merch
        else:
            guest_merch = GuestMerch()
            guest.merch = guest_merch

        inventory = GuestMerch.extract_inventory(params)
        message = GuestMerch.validate_inventory(inventory)
        if not message:
            guest_merch.update_inventory(inventory)
            guest_merch.selling_merch = c.ROCK_ISLAND
            session.add(guest_merch)
            session.commit()

        return {'error': message}

    @ajax
    def remove_inventory_item(self, session, guest_id, item_id):
        guest = session.guest_group(guest_id)
        if guest.merch:
            guest_merch = guest.merch
        else:
            guest_merch = GuestMerch()
            guest.merch = guest_merch

        message = ''
        if not guest_merch.remove_inventory_item(item_id):
            message = 'Item not found'
        else:
            session.add(guest_merch)
            session.commit()
        return {'error': message}

    def charity(self, session, guest_id, message='', **params):
        guest = session.guest_group(guest_id)
        guest_charity = session.guest_charity(params)
        if cherrypy.request.method == 'POST':
            if not guest_charity.donating:
                message = 'You need to tell us whether you are donating anything'
            elif guest_charity.donating == c.DONATING and not guest_charity.desc:
                message = 'You need to tell us what you intend to donate'
            else:
                guest.charity = guest_charity
                session.add(guest_charity)
                raise HTTPRedirect('index?id={}&message={}', guest.id, 'Your charity decisions have been saved')

        return {
            'guest': guest,
            'guest_charity': guest.charity or guest_charity,
            'message': message
        }

    def autograph(self, session, guest_id, message='', **params):
        guest = session.guest_group(guest_id)
        guest_autograph = session.guest_autograph(params)
        if cherrypy.request.method == 'POST':
            guest_autograph.length = 60 * int(params['length'])  # Convert hours to minutes
            guest.autograph = guest_autograph
            session.add(guest_autograph)
            raise HTTPRedirect('index?id={}&message={}', guest.id, 'Your autograph sessions have been saved')

        return {
            'guest': guest,
            'guest_autograph': guest.autograph or guest_autograph,
            'message': message
        }

    def interview(self, session, guest_id, message='', **params):
        guest = session.guest_group(guest_id)
        guest_interview = session.guest_interview(params, bools=['will_interview', 'direct_contact'])
        if cherrypy.request.method == 'POST':
            if guest_interview.will_interview and not guest_interview.email:
                message = 'Please provide an email for interview requests.'
            else:
                guest.interview = guest_interview
                session.add(guest_interview)
                raise HTTPRedirect('index?id={}&message={}', guest.id, 'Your interview preferences have been saved')

        return {
            'guest': guest,
            'guest_interview': guest.interview or guest_interview,
            'message': message
        }

    def travel_plans(self, session, guest_id, message='', **params):
        guest = session.guest_group(guest_id)
        guest_travel_plans = session.guest_travel_plans(params, checkgroups=['modes'])
        if cherrypy.request.method == 'POST':
            if not guest_travel_plans.modes:
                message = 'Please tell us how you will arrive at MAGFest.'
            elif c.OTHER in guest_travel_plans.modes_ints and not guest_travel_plans.modes_text:
                message = 'You need to tell us what "other" travel modes you are using.'
            elif not guest_travel_plans.details:
                message = 'Please provide details of your arrival and departure plans.'
            else:
                guest.travel_plans = guest_travel_plans
                session.add(guest_travel_plans)
                raise HTTPRedirect('index?id={}&message={}', guest.id, 'Your travel plans have been saved')

        return {
            'guest': guest,
            'guest_travel_plans': guest.travel_plans or guest_travel_plans,
            'message': message
        }

    def mivs_core_hours(self, session, guest_id, message='', **params):
        guest = session.guest_group(guest_id)
        if cherrypy.request.method == 'POST':
            if guest.group.studio:
                guest.group.studio.accepted_core_hours = True
                session.add(guest)
                raise HTTPRedirect('index?id={}&message={}', guest.id, 'You have accepted the MIVS core hours.')
            else:
                message = "Something is wrong with your group -- please contact us at {}.".format(c.MIVS_EMAIL)
        return {
            'guest': guest,
            'message': message,
        }

    def mivs_discussion(self, session, guest_id, message='', **params):
        guest = session.guest_group(guest_id)
        if cherrypy.request.method == 'POST':
            if guest.group.studio:
                guest.group.studio.completed_discussion = True
                guest.group.studio.discussion_emails = ','.join(params['discussion_emails'])
                session.add(guest)
                raise HTTPRedirect('index?id={}&message={}', guest.id, 'Discussion email addresses updated.')
            else:
                message = "Something is wrong with your group -- please contact us at {}.".format(c.MIVS_EMAIL)
        return {
            'guest': guest,
            'message': message,
        }

    def mivs_handbook(self, session, guest_id, message='', **params):
        guest = session.guest_group(guest_id)
        if cherrypy.request.method == 'POST':
            if guest.group.studio:
                guest.group.studio.read_handbook = True
                session.add(guest)
                raise HTTPRedirect('index?id={}&message={}', guest.id, 'You have confirmed that you read the handbook.')
            else:
                message = "Something is wrong with your group -- please contact us at {}.".format(c.MIVS_EMAIL)
        return {
            'guest': guest,
            'message': message,
        }

    def mivs_training(self, session, guest_id, message='', **params):
        guest = session.guest_group(guest_id)
        if cherrypy.request.method == 'POST':
            if guest.group.studio:
                if 'training_password' in params and params['training_password']:
                    guest.group.studio.training_password = params['training_password']
                    session.add(guest)
                    raise HTTPRedirect('index?id={}&message={}', guest.id, 'Secret phrase submitted.')
                else:
                    message = "Please enter the secret phrase!"
            else:
                message = "Something is wrong with your group -- please contact us at {}.".format(c.MIVS_EMAIL)
        return {
            'guest': guest,
            'message': message,
        }

    def mivs_hotel_space(self, session, guest_id, message='', **params):
        guest = session.guest_group(guest_id)
        if cherrypy.request.method == 'POST':
            if guest.group.studio:
                if not params.get('needs_hotel_space'):
                    message = "Please select if you need hotel space or not."
                elif 'confirm_checkbox' not in params:
                    message = "You must confirm that you have {}".format(
                        "filled out the hotel form." if params.get('needs_hotel_space') == '1'
                        else "taken care of your own accommodations for MAGFest."
                    )
                elif params.get('needs_hotel_space') == '1':
                    guest.group.studio.name_for_hotel = params.get('name_for_hotel')
                    guest.group.studio.email_for_hotel = params.get('email_for_hotel')
                    if not guest.group.studio.name_for_hotel:
                        message = "Please provide the first and last name you are using in your hotel booking."
                    elif not guest.group.studio.email_for_hotel:
                        message = "Please provide the email address you are using in your hotel booking."
                    elif not params.get('same_checkbox'):
                        message = "Please confirm you have filled out the same information here as on the hotel form"

                if not message:
                    guest.group.studio.needs_hotel_space = True if params.get('needs_hotel_space') == '1' else False
                    session.add(guest)
                    raise HTTPRedirect('index?id={}&message={}',
                                       guest.id,
                                       'Hotel needs updated.')
            else:
                message = "Something is wrong with your group -- please contact us at {}.".format(c.MIVS_EMAIL)
        return {
            'guest': guest,
            'message': message,
            'confirm_checkbox': True if 'confirm_checkbox' in params else False,
        }

    def mivs_selling_at_event(self, session, guest_id, message='', **params):
        guest = session.guest_group(guest_id)
        if cherrypy.request.method == 'POST':
            if guest.group.studio:
                if not params['selling_at_event']:
                    message = "Please select if you want to sell items at MAGFest or not."
                elif params['selling_at_event'] == '1':
                    if 'confirm_checkbox' not in params:
                        message = "You must confirm that you have filled out the Google form provided."

                if not message:
                    guest.group.studio.selling_at_event = True if params['selling_at_event'] == '1' else False
                    session.add(guest)
                    raise HTTPRedirect('index?id={}&message={}',
                                       guest.id,
                                       'Selling preferences updated.')
            else:
                message = "Something is wrong with your group -- please contact us at {}.".format(c.MIVS_EMAIL)
        return {
            'guest': guest,
            'message': message,
        }
        
    def mivs_show_info(self, session, guest_id, message='', **params):
        guest = session.guest_group(guest_id)
        if cherrypy.request.method == 'POST':
            if guest.group.studio:
                if not params.get('show_info_updated'):
                    message = "Please confirm you have updated your studio's and game's information."

                if not message:
                    guest.group.studio.show_info_updated = True
                    session.add(guest)
                    raise HTTPRedirect('index?id={}&message={}',
                                       guest.id,
                                       'Thanks for confirming your studio and game information is up-to-date!')
            else:
                message = "Something is wrong with your group -- please contact us at {}.".format(c.MIVS_EMAIL)
        return {
            'guest': guest,
            'message': message,
        }

    def view_inventory_file(self, session, id, item_id, name):
        guest_merch = session.guest_merch(id)
        if guest_merch:
            item = guest_merch.inventory.get(item_id)
            if item:
                filename = item.get('{}_filename'.format(name))
                download_filename = item.get('{}_download_filename'.format(name), filename)
                content_type = item.get('{}_content_type'.format(name))
                filepath = guest_merch.inventory_path(filename)
                if filename and download_filename and content_type and os.path.exists(filepath):
                    filesize = os.path.getsize(filepath)
                    cherrypy.response.headers['Accept-Ranges'] = 'bytes'
                    cherrypy.response.headers['Content-Length'] = filesize
                    cherrypy.response.headers['Content-Range'] = 'bytes 0-{}'.format(filesize)
                    return serve_file(filepath, disposition='inline', name=download_filename, content_type=content_type)
                else:
                    raise cherrypy.HTTPError(404, "File not found")

    def view_bio_pic(self, session, id):
        guest = session.guest_group(id)
        return serve_file(
            guest.bio.pic_fpath,
            disposition="attachment",
            name=guest.bio.download_filename,
            content_type=guest.bio.pic_content_type)

    def view_stage_plot(self, session, id):
        guest = session.guest_group(id)
        return serve_file(
            guest.stage_plot.fpath,
            disposition="attachment",
            name=guest.stage_plot.download_filename,
            content_type=guest.stage_plot.content_type)
