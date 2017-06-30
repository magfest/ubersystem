import pytest

from uber.common import *
from uber.tests.conftest import *


class TestIdRequired:

    @pytest.mark.parametrize('ModelClass', [Attendee, Group])
    @pytest.mark.parametrize('params', [
        {},
        {'not_an_id': 'not an id'},
        {'id': None},
        {'id': []},
        {'id': {}},
        {'id': ''},
        {'id': 'Invalid UUID'},
        {'id': 'd17fbcba-d5cc-44de-8cb1-83091211a829'}  # Non-existent id
    ])
    def test_model_id_invalid(self, ModelClass, params):

        @id_required(ModelClass)
        def _requires_model_id(**params):
            return True

        params['session'] = Session().session
        pytest.raises(HTTPRedirect, _requires_model_id, **params)

    @pytest.mark.parametrize('ModelClass', [Attendee, Group])
    def test_model_id_valid(self, ModelClass):

        @id_required(ModelClass)
        def _requires_model_id(**params):
            return True

        with Session() as session:
            model = ModelClass()
            session.add(model)
            session.flush()
            model_id = uuid.UUID(model.id)
            assert _requires_model_id(**{
                'session': session,
                'id': 'None'})  # We explicitly allow the string 'None'
            assert _requires_model_id(**{
                'session': session,
                'id': model_id})  # 'id' as a uuid.UUID() instance
            assert _requires_model_id(**{
                'session': session,
                'id': model_id.hex})  # 'id' as a str instance
