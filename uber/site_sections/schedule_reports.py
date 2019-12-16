from uber.config import c
from uber.decorators import all_renderable, multifile_zipfile, xlsx_file, _set_response_filename
from uber.models import Event, Session
from uber.reports import PersonalizedBadgeReport, PrintedBadgeReport
from uber.utils import filename_safe, localized_now


def _get_guidebook_models(session, selected_model=''):
    model = selected_model.split('_')[0] if '_' in selected_model else selected_model
    model_query = session.query(Session.resolve_model(model))

    if '_band' in selected_model:
        return model_query.filter_by(group_type=c.BAND)
    elif '_guest' in selected_model:
        return model_query.filter_by(group_type=c.GUEST)
    elif '_dealer' in selected_model:
        return model_query.filter_by(is_dealer=True)
    elif '_panels' in selected_model:
        return model_query.filter(Event.location.in_(c.PANEL_ROOMS))
    elif 'Game' in selected_model:
        return model_query.filter_by(has_been_accepted=True)
    else:
        return model_query


@all_renderable()
class Root:
    def index(self, session, message=''):
        return {
            'message': message,
            'tables': c.GUIDEBOOK_MODELS,
        }

    @xlsx_file
    def export_guidebook_xlsx(self, out, session, selected_model):
        model_list = _get_guidebook_models(session, selected_model).all()

        _set_response_filename('{}_guidebook_{}.xlsx'.format(
            filename_safe(dict(c.GUIDEBOOK_MODELS)[selected_model]).lower(),
            localized_now().strftime('%Y%m%d'),

        ))

        out.writerow([val for key, val in c.GUIDEBOOK_PROPERTIES])

        for model in model_list:
            row = []
            for key, val in c.GUIDEBOOK_PROPERTIES:
                row.append(getattr(model, key, '').replace('\n', '<br/>'))
            out.writerow(row)

    @multifile_zipfile
    def export_guidebook_zip(self, zip_file, session, selected_model):
        model_list = _get_guidebook_models(session, selected_model).all()

        for model in model_list:
            filenames, files = getattr(model, 'guidebook_images', ['', ''])

            for filename, file in zip(filenames, files):
                if filename:
                    zip_file.write(getattr(file, 'filepath', file.pic_fpath), filename)
