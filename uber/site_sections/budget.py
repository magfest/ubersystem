from uber.common import *

def prereg_money(session):
    preregs = defaultdict(int)
    for attendee in session.query(Attendee).all():
        preregs['Attendee'] += attendee.amount_paid
        preregs['extra'] += attendee.amount_extra

    preregs['group_badges'] = sum(g.badge_cost for g in session.query(Group).filter(Group.tables == 0, Group.amount_paid > 0).all())

    dealers = session.query(Group).filter(Group.tables > 0, Group.amount_paid > 0).all()
    preregs['dealer_tables'] = sum(d.table_cost for d in dealers)
    preregs['dealer_badges'] = sum(d.badge_cost for d in dealers)

    return preregs

def sale_money(session):
    sales = defaultdict(int)
    for sale in session.query(Sale).all():
        sales[sale.what] += sale.cash
    return dict(sales)  # converted to a dict so we can say sales.items in our template


@all_renderable(MONEY)
class Root:
    def index(self, session):
        sales   = sale_money(session)
        preregs = prereg_money(session)
        total = sum(preregs.values()) + sum(sales.values())
        return {
            'total':   total,
            'preregs': preregs,
            'sales':   sales
        }

    # TODO: add joinedload options here for efficiency
    def mpoints(self, session):
        groups = defaultdict(list)
        for mpu in session.query(CashForMPoints).all():
            groups[mpu.attendee and mpu.attendee.group].append(mpu)
        all = [(sum(mpu.amount for mpu in mpus), group, mpus)
               for group,mpus in groups.items()]
        return {'all': sorted(all, reverse=True)}
