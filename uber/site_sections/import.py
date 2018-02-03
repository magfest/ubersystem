from uber.common import *


@all_renderable(c.PEOPLE)
class Root:
    def index(self, message='', all_instances=None):
        return {
            'message': message,
            'tables': sorted(model.__name__ for model in Session.all_models()),
            'attendees': all_instances
        }
    index.restricted = [c.ACCOUNTS and c.STATS and c.PEOPLE and c.MONEY]

    def import_model(self, session, model_import, selected_model='', date_format="%Y-%m-%d"):
        model = Session.resolve_model(selected_model)
        message = ''

        cols = {col.name: getattr(model, col.name) for col in model.__table__.columns}
        result = csv.DictReader(model_import.file.read().decode('utf-8').split('\n'))
        id_list = []

        for row in result:
            if 'id' in row:
                id = row.pop('id')  # id needs special treatment

                try:
                    # get the instance if it already exists
                    model_instance = getattr(session, selected_model)(id, allow_invalid=True)
                except:
                    session.rollback()
                    # otherwise, make a new one and add it to the session for when we commit
                    model_instance = model()
                    session.add(model_instance)

            for colname, val in row.items():
                col = cols[colname]
                if not val:
                    # in a lot of cases we'll just have the empty string, so we'll just
                    # do nothing for those cases
                    continue
                if isinstance(col.type, Choice):
                    # the export has labels, and we want to convert those back into their
                    # integer values, so let's look that up (note: we could theoretically
                    # modify the Choice class to do this automatically in the future)
                    label_lookup = {val: key for key, val in col.type.choices.items()}
                    val = label_lookup[val]
                elif isinstance(col.type, MultiChoice):
                    # the export has labels separated by ' / ' and we want to convert that
                    # back into a comma-separate list of integers
                    label_lookup = {val: key for key, val in col.type.choices}
                    vals = [label_lookup[label] for label in val.split(' / ')]
                    val = ','.join(map(str, vals))
                elif isinstance(col.type, UTCDateTime):
                    # we'll need to make sure we use whatever format string we used to
                    # export this date in the first place
                    try:
                        val = UTC.localize(datetime.strptime(val, date_format + ' %H:%M:%S'))
                    except:
                        val = UTC.localize(datetime.strptime(val, date_format))
                elif isinstance(col.type, Date):
                    val = datetime.strptime(val, date_format).date()
                elif isinstance(col.type, Integer):
                    val = int(val)

                # now that we've converted val to whatever it actually needs to be, we
                # can just set it on the model
                setattr(model_instance, colname, val)

            try:
                session.commit()
            except:
                log.error('ImportError', exc_info=True)
                session.rollback()
                message = 'Import unsuccessful'

            id_list.append(model_instance.id)

        all_instances = session.query(model).filter(model.id.in_(id_list)).all() if id_list else None

        return self.index(message, all_instances)
    import_model.restricted = [c.ACCOUNTS and c.STATS and c.PEOPLE and c.MONEY]
