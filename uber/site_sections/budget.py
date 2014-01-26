from uber.common import *

def prereg_money():
    preregs = defaultdict(int)
    for attendee in Attendee.objects.all():
        preregs['Attendee'] += attendee.amount_paid
        preregs['extra'] += attendee.amount_extra

    preregs["group_badges"] = sum(g.badge_cost for g in Group.objects.filter(tables=0).exclude(amount_paid=0))

    dealers = Group.objects.filter(tables__gt=0, amount_paid__gt=0)
    preregs["dealer_tables"] = sum(d.table_cost for d in dealers)
    preregs["dealer_badges"] = sum(d.badge_cost for d in dealers)

    return preregs

def sale_money():
    sales = defaultdict(int)
    for sale in Sale.objects.all():
        sales[sale.what] += sale.cash
    return dict(sales)  # converted to a dict so we can say sales.items in our template


@all_renderable(MONEY)
class Root:
    def index(self):
        sales   = sale_money()
        preregs = prereg_money()
        total = sum(preregs.values()) + sum(sales.values())
        return {
            "total":   total,
            "preregs": preregs,
            "sales":   sales
        }

    def mpoints(self):
        groups = defaultdict(list)
        for mpu in CashForMPoints.objects.select_related():
            groups[mpu.attendee and mpu.attendee.group].append(mpu)
        all = [(sum(mpu.amount for mpu in mpus), group, mpus)
               for group,mpus in groups.items()]
        return {"all": sorted(all, reverse=True)}
