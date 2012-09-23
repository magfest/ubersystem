// Dominic Cerquetti, Magfest ubersystem, Aug 2012
// show some stats about our registration numbers in neato google charts form.

google.load("visualization", "1", {packages:["corechart", "table"]});
google.setOnLoadCallback(drawChart);

function drawChart() {

    // -------------------------------------
    // scrub the data
    // -------------------------------------

    // the database returns values in the future of the current magfest
    // as the same attendance. we need to remove those values or else
    // we'll get a straight line to the right from today's date onwards

    // loop over it backwards, stop when we hit an attendance number that is
    // not zero
    var newest_magfest_index = attendance_data[0].length - 1;
    var current_total = -1;
    for (var day = attendance_data.length-1; day >= 1; day--)
    {
        var total_attendance = attendance_data[day][newest_magfest_index]

        if (total_attendance != attendance_data[day-1][newest_magfest_index])
            break;

        // it's unchanged, so remove this value and keep searching backwards
        attendance_data[day][newest_magfest_index] = null; // total_attendance
    }

    // remove any zero attendance days at the start of the data for
    // each year. starting from 1 on each of these to skip non-numeric data
    for (var year = 1; year < attendance_data[day].length; ++year)
    {
        for (var day = 1; day < attendance_data.length; ++day)
        {
            if (attendance_data[day][year] != 0)
                break;
            
            attendance_data[day][year] = null;
        }
    }

    // -------------------------------------
    // looking good. now, render the data
    // -------------------------------------

    var data = google.visualization.arrayToDataTable(attendance_data);
	
	// draw the graph
    var chart = new google.visualization.LineChart(document.getElementById('graph'));
    chart.draw(
        data,
        {
            height: 600,
            title: 'Magfest attendance by year [days til start of magfest]'
        }
    );

    // add the % change to the data for the second table
    attendance_data[0].push("% change last year -> this");
    for (var day = 1; day < attendance_data.length; ++day)
    {
        // Percent change = [(Vpresent-Vpast)/Vpast] * 100
        var len = attendance_data[day].length;
        var presentyear = attendance_data[day][len-1];
        var lastyear = attendance_data[day][len-2];

        if (presentyear == null || lastyear == null)
        {
            attendance_data[day].push(null);
            continue;
        }

        var pctchange = (presentyear - lastyear) / lastyear * 100;

        // the first couple entries are CRAZY. just ignore.
        if (pctchange >= 100)
        {
            attendance_data[day].push(null);
            continue;
        }

        attendance_data[day].push(pctchange.toFixed(2) + "%");
    }

    var data2 = google.visualization.arrayToDataTable(attendance_data);
	
	// draw the table breakdown below it
	var table = new google.visualization.Table(document.getElementById('table_div'));
    table.draw(
		data2, 
		{
			showRowNumber: false,
            width: 1000
		}
	);
}

