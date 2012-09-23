from common import *

# TODO: DOM: this whole thing needs a major overhaul, it's a nightmare
# this spits out data in the wrong format needed for the javascript,
# and the javascript does a ton of unneeded processing to work around it.

# imports the actual hardcoded graph data for previous magfest years
# (yes, its hardcoded and not from the DB).  only used for money graph,
# newer graphs read directly from DB
from graph_data import *


def graphable():
    atts = list(Attendee.objects.values())
    groups = list(Group.objects.values())
    start = min(x["registered"].date() for x in atts + groups)
    end = max(x["registered"].date() for x in atts + groups)

    days, regs = defaultdict(int), defaultdict(int)
    for x in atts + groups:
        days[x["registered"].date()] += x["amount_paid"]

    total = 0
    sums = {}
    day = start
    while day <= end:
        total += days[day]
        sums[day.strftime("%Y-%m-%d")] = total
        day += timedelta(days=1)
    return sums


def get_graphs_data():

    # warning: this code is horrifying. holy shit.

    m11_regs = [
        Attendee.objects.filter(
            Q(paid=HAS_PAID) |
            Q(paid=PAID_BY_GROUP, group__amount_paid__gt=0)).count(),
        Attendee.objects.filter(paid=NOT_PAID).count()
    ]
    curr = graphable()
    until = (state.EPOCH.date() - date.today()).days

    # TODO: replace hardcoded dates below with these
    # these are END DATES
    m6_date = date(2008, 1, 6)  # date magfest ENDS
    m7_date = date(2009, 1, 4)  # date magfest ENDS
    m8_date = date(2010, 1, 4)  # date magfest ENDS
    m9_date = date(2011, 1, 16)  # date magfest ENDS
    m10_date = date(2012, 1, 8)  # date magfest ENDS
    m11_date = date(2013, 1, 6)  # date magfest ENDS

    return {
        "m6_date": m6_date.isoformat(),
        "m7_date": m7_date.isoformat(),
        "m8_date": m8_date.isoformat(),
        "m9_date": m9_date.isoformat(),
        "m10_date": m10_date.isoformat(),
        "m11_date": m11_date.isoformat(),
        "until": until,
        "needed": Money.objects.filter(Q(pledged=False) | Q(pre_con=True),
            paid_by=MAGFEST_FUNDS, type=DEBIT)
            .aggregate(Sum('amount')).values()[0],
        "curr_total": max(curr.values()),
        "m6_by_now": m6[(date(2008, 1, 3) - timedelta(days=until)).strftime("%Y-%m-%d")],
        "m7_by_now": m7[(date(2009, 1, 1) - timedelta(days=until)).strftime("%Y-%m-%d")],
        "m8_by_now": m8[(date(2010, 1, 1) - timedelta(days=until)).strftime("%Y-%m-%d")],
        "m9_by_now": m9[(date(2011, 1, 13) - timedelta(days=until)).strftime("%Y-%m-%d")],
        "m10_by_now": m10[(date(2012, 1, 5) - timedelta(days=until)).strftime("%Y-%m-%d")],
        "m6_pre_con": m6["2008-01-02"],
        "m7_pre_con": m7["2008-12-31"],
        "m8_pre_con": m8["2009-12-30"],
        "m9_pre_con": m9["2011-01-12"],
        "m10_pre_con": m10["2012-01-04"],
        "m6_coords": sorted(m6.items()),
        "m6_lookup": m6,
        "m7_coords": sorted(m7.items()),
        "m7_lookup": m7,
        "m8_coords": sorted(m8.items()),
        "m8_lookup": m8,
        "m9_coords": sorted(m9.items()),
        "m9_lookup": m9,
        "m10_coords": sorted(m10.items()),
        "m10_lookup": m10,
        "m11_coords": sorted(curr.items()),
        "m11_lookup": curr,
        "m6_regs": m6_regs.get((date(2008, 1, 3) - timedelta(days=until)).strftime("%Y-%m-%d"), [0,0]),
        "m7_regs": m7_regs.get((date(2009, 1, 1) - timedelta(days=until)).strftime("%Y-%m-%d"), [0,0]),
        "m8_regs": m8_regs.get((date(2010, 1, 1) - timedelta(days=until)).strftime("%Y-%m-%d"), [0,0]),
        "m9_regs": m9_regs.get((date(2011, 1, 13) - timedelta(days=until)).strftime("%Y-%m-%d"), [0,0]),
        "m10_regs": m10_regs.get((date(2012, 1, 5) - timedelta(days=until)).strftime("%Y-%m-%d"), [0,0]),
        "m11_regs": m11_regs
    }


@all_renderable(PEOPLE)
class Root:
    def index(self):
        return {
            "test": "test423"
        }

    def graphs(self):
        m10_regs = [
            Attendee.objects.filter(
                Q(paid=HAS_PAID) |
                Q(paid=PAID_BY_GROUP, group__amount_paid__gt=0)).count(),
            Attendee.objects.filter(paid=NOT_PAID).count()
        ]
        curr = graphable()
        until = (state.EPOCH.date() - date.today()).days
        return {
            "until": until,
            "needed": Money.objects.filter(
                Q(pledged=False) |
                Q(pre_con=True),
                paid_by=MAGFEST_FUNDS,
                type=DEBIT).aggregate(Sum('amount')).values()[0],

            "curr_total": max(curr.values()),
            "m6_by_now":  m6[(date(2008, 1, 3) - timedelta(days=until)).strftime("%Y-%m-%d")],
            "m7_by_now":  m7[(date(2009, 1, 1) - timedelta(days=until)).strftime("%Y-%m-%d")],
            "m8_by_now":  m8[(date(2010, 1, 1) - timedelta(days=until)).strftime("%Y-%m-%d")],
            "m9_by_now":  m9[(date(2011, 1, 13) - timedelta(days=until)).strftime("%Y-%m-%d")],
            "m6_pre_con": m6["2008-01-02"],
            "m7_pre_con": m7["2008-12-31"],
            "m8_pre_con": m8["2009-12-30"],
            "m9_pre_con": m9["2011-01-12"],
            "m6_coords": sorted(m6.items()),
            "m6_lookup": m6,
            "m7_coords": sorted(m7.items()),
            "m7_lookup": m7,
            "m8_coords": sorted(m8.items()),
            "m8_lookup": m8,
            "m9_coords": sorted(m9.items()),
            "m9_lookup": m9,
            "m10_coords": sorted(curr.items()),
            "m10_lookup": curr,
            "m6_regs": m6_regs.get((date(2008,1,3) - timedelta(days=until)).strftime("%Y-%m-%d"), [0,0]),
            "m7_regs": m7_regs.get((date(2009,1,1) - timedelta(days=until)).strftime("%Y-%m-%d"), [0,0]),
            "m8_regs": m8_regs.get((date(2010,1,1) - timedelta(days=until)).strftime("%Y-%m-%d"), [0,0]),
	    "m9_regs": m9_regs.get((date(2011,1,13) - timedelta(days=until)).strftime("%Y-%m-%d"), [0,0]),
            "m10_regs": m10_regs
        }

    def graphs2(self):
        return get_graphs_data()

    def graphs3(self):
        return get_graphs_data()

    graphs.restricted = (PEOPLE, MONEY)
    graphs2.restricted = (PEOPLE, MONEY)
    graphs3.restricted = (PEOPLE, MONEY)
