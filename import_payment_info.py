from common import *

import csv
import argparse

def parse_ids(item_num):
    ids = defaultdict(list)
    for id in item_num.strip().split(","):
        if re.match(r"a\d+", id):
            ids["attendees"].append( int(id[1:]) )
        elif re.match(r"g\d+", id):
            ids["groups"].append( int(id[1:]) )
        else:
            ids["unknown"].append(id)
    return ids

def mark_group_paid(id):
    group = Group.objects.get(id=id)
    paid = group.amount_unpaid
    group.amount_paid = group.amount_owed
    group.save()
    return paid

def mark_attendee_paid(id):
    attendee = Attendee.objects.get(id=id)
    if attendee.paid in [NOT_PAID, NEED_NOT_PAY]:
        attendee.paid = HAS_PAID
        attendee.amount_paid = attendee.total_cost
        if attendee.registered < datetime(2011, 11, 1):
            attendee.amount_paid -= 5
        set_badge_and_save(attendee)
    return attendee.total_cost

parser = argparse.ArgumentParser(description="Takes a Paypal CSV export and uses it to update Uber payments")
parser.add_argument("-f", "--file", required=True, help="the CSV file to import")
args = parser.parse_args()

reader = csv.DictReader(open(args.file), skipinitialspace=True)

groups, attendees = defaultdict(list), defaultdict(list)
for g in Group.objects.all():
    groups[g.name].append(g.id)
for a in Attendee.objects.all():
    attendees[a.full_name].append(a.id)

for payment in reader:
    amount = int(float(payment["Gross"].replace(",", "")))
    if amount > 0:
        ids = parse_ids(payment["Item ID"])
        if not ids or ids["unknown"]:
            subject = payment["Subject"]
            if subject.startswith("MAGFest Prereg:"):
                subject = subject.split(":", 1)[1]
            names = map(str.strip, subject.split(","))
            if names in ([""], ["You've Got Money!"]):
                print("Gotta do this one manually\n{}\n".format(payment))
                continue
            else:
                for name in names:
                    for key in ["groups","attendees"]:
                        matches = globals()[key][name]
                        if matches:
                            if len(matches) > 1:
                                print("Multiple {} named {}\n{}\n".format(key, name, payment))
                            else:
                                ids[key].append(matches[0])
        
        total_cost = 0
        for key,func in [("groups",mark_group_paid), ("attendees",mark_attendee_paid)]:
            for id in ids[key]:
                try:
                    total_cost += func(id)
                except Exception as e:
                    print("Error on {} {}: {}\n{}\n".format(key, id, e.message, payment))
        
        if total_cost and abs(total_cost - amount) > 5 * len(ids["attendees"] + ids["groups"]):
            print("Non-matching payment amount {} != {}\n{}\n".format(total_cost, amount, payment))
