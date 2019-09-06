from uber.decorators import all_renderable, public


@public
@all_renderable(public=True)
class Root:
    def index(self):
        return {}

    def invalid(self, **params):
        return {'message': params.get('message')}
