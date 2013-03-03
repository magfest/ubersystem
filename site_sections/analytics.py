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

# NOTE: when upgrading years, you will need to double check all the
# databases VIEWs to make sure they are pointing at the right 
# tables.

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


@all_renderable(PEOPLE)
class Root:
    def index(self):
        return {
            "test": "test"
        }

    def analytics_graph_by_attendance(self):
        starting_magfest_year = 6
        ending_magfest_year = 11

        print("starting query")

        # collect raw data for each year
        raw_data = []
        for which_magfest in range(
            starting_magfest_year, ending_magfest_year + 1):
            raw_data.append(
                generate_attendance_by_day_graph_data(which_magfest)
            )

        print("done query, processing data")

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

            # magfestubersystem.com likes this one better
            row.append(date.strftime("%Y-%m-%d"))
            
            # courtwright.org likes this one better
            #row.append(date)

            for magfest_data in raw_data:
                # should be the same day offset
                assert magfest_data[day][0] == day

                total_attendance_that_day = magfest_data[day][3]
                row.append(total_attendance_that_day)

            graph_data.append(row)

        print("done processing, rendering...")

        return {
            "attendance_data": graph_data
        }

