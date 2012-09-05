# -*- coding: utf-8 *-*
# Magfest ubersystem analytics
# Dominic Cerquetti, Aug 2012
#
# intended someday as a replacement for graphs module. for now
# works alongside it
#
# NOTE: code here still needs to be updated each year for this
# to work correctly. (mainly, dates and magfest event numbers
# need to be updated)

from common import *


def generate_attendance_by_day_graph_data(magfest_year_to_query):

    # doing a raw query instead of models because we're doing funky stuff.
    from django.db import connection
    cursor = connection.cursor()

    # this is an EXTREMELY COMPLEX STORED PROCEDURE in mysql, you have to view
    # it in mysql query browser or something similar to keep your sanity.
    # it also requires all databases from m6 thru m11 to be present.
    query = """CALL get_cumulative_attendance_by_year(%s)"""

    cursor.execute(query, [magfest_year_to_query])
    results = cursor.fetchall()

    return results

"""
    atts = list(Attendee.objects.values()) # TODO
    start = min(x["registered"].date() for x in atts)
    end = max(x["registered"].date() for x in atts)

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




data[which_day][0] = "Mar 14 2012"
data[which_day][1] = (mag6 data)
data[which_day][2] = (mag7 data)
data[which_day][3] = (mag8 data)
data[which_day][4] = (mag9 data)
data[which_day][5] = (mag10 data)
data[which_day][6] = (mag11 data)

day = data[day]

day[0] = date
day[1] = mag6 data
day[2] = mag7 data
"""


@all_renderable(PEOPLE)
class Root:
    def analytics_graph_by_attendance(self):
        starting_magfest_year = 6
        ending_magfest_year = 11

        print "starting query"

        # collect raw data for each year
        raw_data = []
        for which_magfest in range(
            starting_magfest_year, ending_magfest_year + 1):
            raw_data.append(
                generate_attendance_by_day_graph_data(which_magfest)
            )

        print "done query, processing data"

        # make it be in a sane format that we can deal with in google charts
        graph_data = []
        graph_data.append(["Date", "Magfest 6",
            "Magfest 7", "Magfest 8", "Magfest 9", "Magfest 10", "Magfest 11"])

        newest_magfest = ending_magfest_year - starting_magfest_year

        # combine all the different magfest year data into one big array
        for day in range(0, 365 + 1):
            row = []

            # only need the date from the newest magfest. ignore the others
            date = raw_data[newest_magfest][day][1]
            row.append(date.strftime("%Y-%m-%d"))

            for magfest_data in raw_data:
                # should be the same day offset
                assert magfest_data[day][0] == day

                total_attendance_that_day = magfest_data[day][3]
                row.append(total_attendance_that_day)

            graph_data.append(row)

        print "done processing, rendering..."

        return {
            "attendance_data": graph_data
        }










#        q = 0
"""
        # turn absolute date/times into relative days til magfest (0 thru 365)
        for magfest_data in attendance_data:




        # put it in a format that the graphing data wants to see
        chart_data = []
        index_of_cumulative_attendance = 2
        for day in range(0, 365):
            day_data = []

            day_data.append("jan 90th 2012") # TODO

            for magfest_data in attendance_data:
                # if q == 0:
                #    q = 1
                #    print attendance_data[year]
                # [[datetime.date(2007, 5, 14), 2L, 2L], ... ]

                for day in magfest_data:
                    date = day[0]
                    amount_that_day = day[1]
                    total_so_far = day[2]

                #day_data.append(
                #    attendance_data[year]
                #                   [index_of_cumulative_attendance][thisone])

            chart_data.append(day_data)

        return {
            "chart_data": chart_data
        }
        """
