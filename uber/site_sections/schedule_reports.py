import json

from pockets.autolog import log
from datetime import datetime

from uber.config import c
from uber.decorators import all_renderable, ajax, multifile_zipfile, xlsx_file, _set_response_filename
from uber.models import Event
from uber.utils import filename_safe, localized_now, GuidebookUtils
from uber.tasks.panels import sync_guidebook_models


@all_renderable()
class Root:
    def index(self, session, message=''):
        cl_updates, schedule_updates = GuidebookUtils.get_changed_models(session)

        return {
            'message': message,
            'tables': c.GUIDEBOOK_MODELS,
            'schedule_updates': schedule_updates,
            'cl_updates': cl_updates,
        }

    @ajax
    def mark_item_synced(self, session, selected_model, id, sync_time, **params):
        sync_data = json.loads(params.get('sync_data', ''))
        if not sync_data:
            return {'success': False, 'message': "Form submission failed. Try refreshing the page or contact your developer."}

        if selected_model == 'schedule':
            model = Event
            query = session.query(Event)
        else:
            query, _ = GuidebookUtils.get_guidebook_models(session, selected_model)
            model = GuidebookUtils.parse_guidebook_model(selected_model)
        update_model = query.filter(model.id == id).first()

        if not update_model:
            return {'success': False,
                    'message': "Couldn't find a valid model for syncing. This item may no longer qualify for Guidebook export."}

        update_model.update_last_synced('guidebook', sync_time)
        if not update_model.last_synced.get('data', {}):
            update_model.last_synced['data'] = {}
        update_model.last_synced['data']['guidebook'] = sync_data
        update_model.skip_last_updated = True

        session.add(update_model)
        session.commit()

        return {'success': True, 'message': "Item marked as updated!", 'id': id, 'model': selected_model}

    @ajax
    def sync_all_items(self, session, selected_model, sync_time, **params):
        id_list = params.get('id_list').split(',')
        if not id_list:
            return {'success': False, 'message': "There seems to be nothing to update!"}

        sync_guidebook_models.delay(selected_model, sync_time, id_list)
        return {'success': True, 'message': "Syncing items started!", 'model': selected_model}

    @xlsx_file
    def schedule_guidebook_xlsx(self, out, session, new_only=False):
        header_row = ['Session Title', 'Date', 'Time Start', 'End Date (Optional)', 'Time End (Optional)',
                      'Room/Location', 'Schedule Track (Optional)', 'Description (Optional)',
                      'Allow adding to my schedule', 'Require Registration (Optional)',
                      'Registration Starts (Optional)', 'Registration Ends (Optional)', 'Limit Capacity (Optional)',
                      'Allow Waitlist (Optional)']

        _set_response_filename('sessions_guidebook_{}.xlsx'.format(
            localized_now().strftime('%Y%m%d_%H%M'),
        ))

        rows = []
        query = session.query(Event).order_by('start_time')
        if new_only:
            query = query.filter(Event.last_synced['guidebook'] == None)

        for event in query.all():
            guidebook_fields = event.guidebook_data
            rows.append([
                guidebook_fields['name'],
                guidebook_fields['start_date'],
                guidebook_fields['start_time'],
                guidebook_fields['end_date'],
                guidebook_fields['end_time'],
                guidebook_fields['location'],
                guidebook_fields['track'],
                guidebook_fields['description'],
                'TRUE'
                '', '', '', '', ''
            ])

        out.writerows(header_row, rows)

    @xlsx_file
    def export_guidebook_xlsx(self, out, session, selected_model, new_only=False):
        query, filters = GuidebookUtils.get_guidebook_models(session, selected_model)

        if new_only:
            query = query.filter(filters[0])

        _set_response_filename('{}_guidebook_{}.xlsx'.format(
            filename_safe(dict(c.GUIDEBOOK_MODELS)[selected_model]).lower(),
            localized_now().strftime('%Y%m%d_%H%M'),
        ))

        header_row = [val for key, val in c.GUIDEBOOK_PROPERTIES]
        header_row.extend(['External Import ID', 'Contact Email (Optional)', 'Meeting Link (Optional)'])

        rows = []
        id_list = []
        sync_time = str(datetime.now())

        for model in query:
            id_list.append(model.id)
            if not model.guidebook_data:
                log.error(f"Tried to export model {selected_model} for Guidebook, but it has no guidebook_data property!")
                break

            row = []
            for key, val in c.GUIDEBOOK_PROPERTIES:
                row.append(model.guidebook_data.get(key, '').replace('\n', '<br/>'))
            rows.append(row + ['', '', ''])

        sync_guidebook_models.delay(selected_model, sync_time, id_list)
        out.writerows(header_row, rows)

    @multifile_zipfile
    def export_guidebook_zip(self, zip_file, session, selected_model, new_only=False):
        query, filters = GuidebookUtils.get_guidebook_models(session, selected_model)

        if new_only:
            query = query.filter(filters[0])

        written_files = []

        for model in query:
            filenames, files = getattr(model, 'guidebook_images', ['', ''])

            for filename, file in zip(filenames, files):
                if filename and not filename in written_files:
                    written_files.append(filename)
                    zip_file.write(getattr(file, 'filepath', getattr(file, 'pic_fpath', None)), filename)
