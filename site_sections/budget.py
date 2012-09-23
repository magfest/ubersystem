from common import *

def prereg_money():
    preregs = defaultdict(int)
    for attendee in Attendee.objects.all():
        if attendee.amount_paid:
            preregs[attendee.get_badge_type_display().replace("-","").replace(" ","")] += attendee.amount_paid

        if attendee.paid == REFUNDED:
            preregs["refunded"] += attendee.amount_refunded

    preregs["group_badges"] = sum(g.badge_cost for g in Group.objects.filter(tables=0).exclude(amount_paid=0))

    dealers = Group.objects.filter(tables__gt=0, amount_paid__gt=0)
    preregs["dealer_tables"] = sum(d.table_cost for d in dealers)
    preregs["dealer_badges"] = sum(d.badge_cost for d in dealers)

    return preregs

def source_money():
    debits = Money.objects.filter(type=DEBIT)
    sources = list(set(m.paid_by for m in debits if m.paid_by.id != MAGFEST_FUNDS))
    return sorted((sum(m.amount for m in debits if m.paid_by==source), source)
            for source in sources)

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
        debits  = Money.objects.filter(type=DEBIT)
        credits = Money.objects.filter(type=CREDIT)
        spent = sum(m.amount for m in debits if not m.pledged)
        budget_total = sum(d.amount for d in MoneyDept.objects.all())
        debit_total  = preregs["refunded"] + sum(m.amount for m in debits)
        credit_total = (sum(preregs.values()) - preregs["refunded"]
                      + sum(sales.values())
                      + sum(m.amount for m in credits)
                      + sum(m.amount for m in debits if m.paid_by.id != MAGFEST_FUNDS))
        net = credit_total - max(budget_total, debit_total)
        return {
            "spent":          spent,
            "preregs":        preregs,
            "sales":          sales,
            "sources":        source_money(),
            "cash_on_hand":   credit_total - sum(m.amount for m in debits if not m.pledged),
            "alloc_refunded": sum(d.amount for d in MoneyDept.objects.filter(name="Refunds")),
            "net":            ("${0} still needed" if net<0 else "${0} left over").format(abs(net)),
            "debit_total":    debit_total,
            "credit_total":   credit_total,
            "budget_total":   budget_total,
            "depts":          MoneyDept.objects.exclude(name="Refunds").order_by("-amount"),
            "credits":        credits,
            "pre_con":        sum(d.amount for d in debits if d.pre_con)
        }

    def form(self, message="", **params):
        if "." in params.get("amount", ""):
            params["amount"] = params["amount"][:params["amount"].index(".")]

        money = get_model(Money, params, bools=["pledged","estimate","pre_con"])
        if "name" in params:
            message = check(money)
            if not message:
                if money.type == CREDIT:
                    money.paid_by = money.dept = None
                if not money.pledged:
                    money.estimate = money.pre_con = False

                money.save()
                raise HTTPRedirect("index")

        return {
            "message":     message,
            "money":       money,
            "payments":    money.payment_set.order_by("-day"),
            "dept_opts":   [(d.id,d.name) for d in MoneyDept.objects.order_by("name")],
            "paidby_opts": [(ms.id,ms.name) for ms in MoneySource.objects.all()]
        }

    def add_source(self, return_id, name=""):
        if name.strip():
            source = MoneySource.objects.create(name=name.strip())
            raise HTTPRedirect("form?id={}&paid_by_id={}&message={}", return_id, source.id, "Donor added")

        return {"return_id": return_id}

    def donor(self, id):
        return {
            "donor":  MoneySource.objects.get(id=id),
            "debits": Money.objects.filter(paid_by=id).order_by("-amount")
        }

    def add_payment(self, **params):
        payment = get_model(Payment, params)
        message = check(payment)
        if message:
            raise HTTPRedirect("form?id={}&message={}", payment.money_id, message)
        else:
            payment.save()
            raise HTTPRedirect("form?id={}#payments", payment.money_id)

    def delete_payment(self, id):
        payment = Payment.objects.get(id=id)
        payment.delete()
        raise HTTPRedirect("form?id={}#payments", payment.money_id)

    def delete(self, id):
        Money.objects.filter(id=id).delete()
        raise HTTPRedirect("index")

    def depts(self, message=""):
        return {
            "depts":   MoneyDept.objects.order_by("-amount"),
            "message": message
        }

    def upload_dept(self, **params):
        dept = get_model(MoneyDept, params)
        message = check(dept)
        if message:
            raise HTTPRedirect("depts?message={}", message)
        else:
            dept.save()
            raise HTTPRedirect("depts?message={}", "Department uploaded")

    def delete_dept(self, id):
        dept = MoneyDept.objects.get(id=id)
        if dept.money_set.count():
            raise HTTPRedirect("depts?message={}", "You must delete this department's allocations before you can remove it")
        else:
            dept.delete()
            raise HTTPRedirect("depts?message={}", "Department deleted")

    def mpoints(self):
        groups = defaultdict(list)
        for mpu in MPointUse.objects.select_related():
            groups[mpu.attendee and mpu.attendee.group].append(mpu)
        all = [(sum(mpu.amount for mpu in mpus), group, mpus)
               for group,mpus in groups.items()]
        return {"all": sorted(all, reverse=True)}


