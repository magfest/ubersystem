from uber.common import *

class GraphData:
    def __init__(self):
        self.event_name = "magfest 13"
        self.registrations = [{'dec 18th': 37}, {'dec 20th': 40}]
        self.event_end_date = "01/23/14"

    # test
    def to_JSON(self):
        return json.dumps(self, default=lambda o: o.__dict__, sort_keys=True, indent=4)

@all_renderable(PEOPLE, STATS)
class Root:
    def index(self, session):
        # attendees, groups = session.everyone()

        graph_data = GraphData()
        graph_data.junk = "sup"

        return {'graph_data': graph_data.to_JSON()}

