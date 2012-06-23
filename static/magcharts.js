// Dominic Cerquetti, Magfest ubersystem, June 2012
// show some stats about our registration numbers in neato google charts form.
// This is all kind of a big mess, but, whatever, it works.

// tunable parameters (you can change these if you're just tweaking the look of the graphs)

// show income by day, starting on a certain date (because we don't need to see before a certain date since
// there aren't any registrations in, say, the month after the event.)
var g_start_day_for_income_by_day = 146;
var g_number_of_days_magfest_runs_for = 4;

// ----------------------------------------------
// REAL CODE BELOW, NO MORE TUNABLE PARAMETERS
// ----------------------------------------------

var g_num_cal_days = 365;
var g_num_milliseconds_in_one_day = 1000 * 60 * 60 * 24;

google.load("visualization", "1", {packages:["corechart", "table","annotatedtimeline"]});
google.setOnLoadCallback(drawChart);

// create useful registration data for charts from the info passed to us
// from ubersystem python code.  'graphs' is a global from the graphs3.html
// file that calls us.
//
// Google charts expects the data in a certain way, so we make it happy here.
function makeRegData()
{
    var reg_data = [];

    for (var i = 0; i < graphs.length; ++i)
    {
        // convert absolute dates to relative days til end of magfest

        var day_of_magfest = Date.parse(graphs[i][2]);
        var calendar_days = new Array(365);

        for (var _date in graphs[i][0])
        {
            var absolute_date = Date.parse(_date);
            var days_til_magfest = Math.round(Math.abs(day_of_magfest.getTime() - absolute_date.getTime()) / g_num_milliseconds_in_one_day);
            var cash_on_that_day = graphs[i][0][_date];
            var realday = 365 - days_til_magfest;

            calendar_days[realday] = [realday,cash_on_that_day];
        }

        reg_data.push(calendar_days);
    }

    return reg_data;
}

// get the FINAL DAY that Magfest ends.
// if it starts Jan 3, this will return Jan 6
function getDateForDayMagfestEnds()
{
    return Date.parse(graphs[graphs.length - 1][2]);
}

var g_last_day_of_current_magfest = getDateForDayMagfestEnds();

function getDateStringFromNumberDaysFromEndOfMagfest(days_til_magfest)
{
    var date_of_current_day = g_last_day_of_current_magfest.clone();
    var days_to_add = -(g_num_cal_days - days_til_magfest - 1);
    date_of_current_day.addDays(days_to_add);
    return date_of_current_day.toString("MMM dd yyyy");
}

// income by year, top graph
function generateGraph1(reg_data)
{
    var chart_data = new google.visualization.DataTable();
    // chart_data.addColumn('string', 'Days Til Mag');
    chart_data.addColumn('string', 'Date (mag10)');
    chart_data.addColumn('number', 'Magfest 6');
    chart_data.addColumn('number', 'Magfest 7');
    chart_data.addColumn('number', 'Magfest 8');
    chart_data.addColumn('number', 'Magfest 9');
    chart_data.addColumn('number', 'Magfest 10');
    chart_data.addColumn('number', 'Magfest 11');

    var num_years = reg_data.length;

    for (var days_til_magfest = 0; days_til_magfest < g_num_cal_days; ++days_til_magfest)
    {
        var row = new Array();

        row.push(getDateStringFromNumberDaysFromEndOfMagfest(days_til_magfest));

        var this_row_has_data = false;

        for (var year = 0; year < num_years; ++year)
        {
            var cash_on_hand = null;
            if (reg_data[year][days_til_magfest])
            {
                cash_on_hand = reg_data[year][days_til_magfest][1];
                if (cash_on_hand != 0)
                {
                    this_row_has_data = true;
                }
                else
                {
                    cash_on_hand = null;
                }
            }
            row.push(cash_on_hand);
        }

        if (this_row_has_data)
        {
            chart_data.addRow(row);
        }
    }

    var formatter = new google.visualization.NumberFormat({prefix: '$'});
    formatter.format(chart_data, 1);
    formatter.format(chart_data, 2);
    formatter.format(chart_data, 3);
    formatter.format(chart_data, 4);
    formatter.format(chart_data, 5);
    formatter.format(chart_data, 6);

    var chart = new google.visualization.LineChart(document.getElementById('graph'));
    chart.draw(chart_data, {height: 600, title: 'Magfest income by year [days til start of magfest]'});

    var table = new google.visualization.Table(document.getElementById('table_div'));
    table.draw(chart_data, {showRowNumber: false});
}

function generateGraph2(reg_data, start_day)
{
    var num_years = reg_data.length;

    var previous_cash = new Array(num_years);

    var start_year = 5;
    var end_year = 5;

    var chart_data2 = new google.visualization.DataTable();
    chart_data2.addColumn('string', 'Days Til Mag');

    //chart_data2.addColumn('number', 'Magfest 6');
    //chart_data2.addColumn('number', 'Magfest 7');
    //chart_data2.addColumn('number', 'Magfest 8');
    //chart_data2.addColumn('number', 'Magfest 9');
    //chart_data2.addColumn('number', 'Magfest 10');

    chart_data2.addColumn('number', 'Magfest 11');

    for (var year = 0; year < num_years; ++year)
    {
        previous_cash[year] = 0;

        for (var days_til_magfest = start_day; days_til_magfest < g_num_cal_days; ++days_til_magfest)
        {
            if (reg_data[year][days_til_magfest])
            {
                previous_cash[year] = reg_data[year][days_til_magfest][1];
                break;
            }
        }
    }

    for (var days_til_magfest = start_day; days_til_magfest < g_num_cal_days; ++days_til_magfest)
    {
        var row = new Array();

        row.push(getDateStringFromNumberDaysFromEndOfMagfest(days_til_magfest-1));

        for (var year = start_year; year < end_year+1; ++year)
        {
            var cash_on_hand = null;
            var new_cash = 0;
            if (reg_data[year][days_til_magfest])
            {
                cash_on_hand = reg_data[year][days_til_magfest][1];
                new_cash = cash_on_hand - previous_cash[year];
                previous_cash[year] = cash_on_hand;
            }
            row.push(new_cash);
        }
        chart_data2.addRow(row);
    }

    var formatter = new google.visualization.NumberFormat({prefix: '$'});
    formatter.format(chart_data2, 1);
    // formatter.format(chart_data2, 2);
    /*formatter.format(chart_data2, 3);
     formatter.format(chart_data2, 4);
     formatter.format(chart_data2, 5);*/

    var chart2 = new google.visualization.ColumnChart(document.getElementById('graph2'));
    chart2.draw(chart_data2, {height: 600, title: 'Magfest income by day'});
}

// table chart
function generateGraph3()
{

}

function drawChart()
{
    var reg_data = makeRegData();

    generateGraph1(reg_data);
    generateGraph2(reg_data, g_start_day_for_income_by_day);
}
