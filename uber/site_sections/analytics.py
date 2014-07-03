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

# NOTE: as of 8/27/13 everything changed again and we're reading hardcoded
# values from a file vs the database because we switched to postgres and
# I don't feel like converting.  Here be dragons. I am not proud.

from uber.common import *
import copy

# imports the actual hardcoded graph data for previous magfest years
# (yes, its hardcoded and not from the DB).
from uber.graph_data import *

def generate_attendance_by_day_graph_data(last_day_of_magfest):

    # doing a raw query instead of models because we're doing funky stuff.
    cursor = connection.cursor()

    # this is an EXTREMELY COMPLEX STORED PROCEDURE in mysql, you have to view
    # it in mysql query browser or something similar to keep your sanity.
    # it also requires all databases from m6 thru m11 to be present.
    query = """SELECT * FROM get_cumulative_attendance_by_year(%s)"""

    cursor.execute(query, [last_day_of_magfest])
    raw_results = cursor.fetchall()
    cursor.close()
    results = [];

    # compute cumulative sum of attendance per day.
    # we used to do this inside SQL, but it's no good with postgres
    # the stored proc creates the column, but it's zeroed out
    attendance_so_far = 0;
    for day_data in raw_results:
        attendance_so_far += day_data[2]
        results.append([day_data[0], day_data[1], day_data[2], attendance_so_far])

    #print results

    return results


@all_renderable(PEOPLE, STATS)
class Root:
    def index(self):
        return {}

    def analytics_graph_by_attendance(self):
        try:
            starting_magfest_year = 6
            ending_magfest_year = 12

            print("starting query")

            # if the previous databases worked, do this:
            # ------------
            # collect raw data for each year
            #raw_data = []
            #for which_magfest in range(
            #    starting_magfest_year, ending_magfest_year + 1):
            #    raw_data.append(
            #        generate_attendance_by_day_graph_data(which_magfest)
            #    )
            # -------------

            # for previous years, use cached data
            raw_data = copy.deepcopy(raw_data_mag6_thru_mag11)
            
            # for this year, run the query
            raw_data.append(generate_attendance_by_day_graph_data('2014-01-05'))

            print("done query, processing data")

            # make it be in a sane format that we can deal with in google charts
            graph_data = []
            graph_data.append(["Date", "Magfest 6",
                "Magfest 7", "Magfest 8", "Magfest 9", "Magfest 10", "Magfest 11", "Magfest 12"])

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
        except:
            connection.close()
            raise


    # display last 2 minutes worth of registrations, to be used by alerting services
    @ajax_public_callable
    @unrestricted
    def recent_regs_json(self):
        restrict_to = {'registered__gte': datetime.datetime.now() - timedelta(minutes=2)}
        attendees = Attendee.objects.order_by('registered').filter(**restrict_to)

        att = []
        for attendee in attendees:
            id_hash = hash(attendee.first_name + ' ' + str(attendee.id))
            unix_timestamp = int(attendee.registered.strftime('%s'))
            item = [unix_timestamp, id_hash]
            att.append(item)

        return att

    # display the page that calls the AJAX above
    @unrestricted
    def recent_regs_live(self):
        return {}