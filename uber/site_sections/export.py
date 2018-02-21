from uber.config import c
from uber.decorators import all_renderable, csv_file, set_csv_filename
from uber.models import Choice, Session, UTCDateTime, MultiChoice


@all_renderable(c.PEOPLE)
class Root:
    def index(self, message='', **params):
        if 'model' in params:
            self.export_model(selected_model=params['model'])

        return {
            'message': message,
            'tables': sorted(model.__name__ for model in Session.all_models())
        }
    index.restricted = [c.ACCOUNTS and c.STATS and c.PEOPLE and c.MONEY]

    @csv_file
    def export_model(self, out, session, selected_model=''):
        model = Session.resolve_model(selected_model)

        cols = [getattr(model, col.name) for col in model.__table__.columns]
        out.writerow([col.name for col in cols])

        for attendee in session.query(model).all():
            row = []
            for col in cols:
                if isinstance(col.type, Choice):
                    # Choice columns are integers with a single value with an automatic
                    # _label property, e.g. the "shirt" column has a "shirt_label"
                    # property, so we'll use that.
                    row.append(getattr(attendee, col.name + '_label'))
                elif isinstance(col.type, MultiChoice):
                    # MultiChoice columns are comma-separated integer lists with an
                    # automatic _labels property which is a list of string labels.
                    # So we'll get that and then separate the labels with slashes.
                    row.append(' / '.join(getattr(attendee, col.name + '_labels')))
                elif isinstance(col.type, UTCDateTime):
                    # Use the empty string if this is null, otherwise use strftime.
                    # Also you should fill in whatever actual format you want.
                    val = getattr(attendee, col.name)
                    row.append(val.strftime('%Y-%m-%d %H:%M:%S') if val else '')
                else:
                    # For everything else we'll just dump the value, although we might
                    # consider adding more special cases for things like foreign keys.
                    row.append(getattr(attendee, col.name))
            out.writerow(row)
    export_model.restricted = [c.ACCOUNTS and c.STATS and c.PEOPLE and c.MONEY]

    @set_csv_filename
    def valid_attendees(self):
        return self.export_model(selected_model='attendee')
    valid_attendees.restricted = [c.ACCOUNTS and c.STATS and c.PEOPLE and c.MONEY]
