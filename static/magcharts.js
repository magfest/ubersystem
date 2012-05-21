google.load("visualization", "1", {packages:["corechart", "table","annotatedtimeline"]});
google.setOnLoadCallback(drawChart);

function drawChart() {

    // The number of milliseconds in one day
    var ONE_DAY = 1000 * 60 * 60 * 24

    var data = [];

    for (var i = 0; i < graphs.length; ++i)
    {
        // convert absolute dates to relative days til end of magfest

        var day_of_magfest = Date.parse(graphs[i][2]);
        var calendar_days = new Array(365);

        for (var _date in graphs[i][0])
        {
           var absolute_date = Date.parse(_date);
           var days_til_magfest = Math.round(Math.abs(day_of_magfest.getTime() - absolute_date.getTime()) / ONE_DAY);
           var cash_on_that_day = graphs[i][0][_date];
           var realday = 365 - days_til_magfest;

           calendar_days[realday] = [realday,cash_on_that_day];
        }

        data.push(calendar_days);
    }
        
    var chart_data = new google.visualization.DataTable();
    chart_data.addColumn('string', 'Days Til Mag');
    chart_data.addColumn('number', 'Magfest 6');
    chart_data.addColumn('number', 'Magfest 7');
    chart_data.addColumn('number', 'Magfest 8');
    chart_data.addColumn('number', 'Magfest 9');
    chart_data.addColumn('number', 'Magfest 10');

    var start_year = 4; // 0
    var end_year = 4; // num_years
    var chart_data2 = new google.visualization.DataTable();
    chart_data2.addColumn('string', 'Days Til Mag');
    //chart_data2.addColumn('number', 'Magfest 6');
    //chart_data2.addColumn('number', 'Magfest 7');
    //chart_data2.addColumn('number', 'Magfest 8');
    // chart_data2.addColumn('number', 'Magfest 9');
    chart_data2.addColumn('number', 'Magfest 10');
    
    var num_cal_days = 365;
    var num_years = data.length;
    
    // graph 1
    for (var days_til_magfest = 0; days_til_magfest < num_cal_days; ++days_til_magfest)
    {
        var row = new Array();
        row.push(days_til_magfest.toString());

        for (var year = 0; year < num_years; ++year)
        {
            var cash_on_hand = null;
            if (data[year][days_til_magfest]) 
            {
                cash_on_hand = data[year][days_til_magfest][1];
            }
            row.push(cash_on_hand);
        }

        chart_data.addRow(row);
    }

    // graph 2
    var previous_cash = new Array(num_years);    
    var start_day = 180;

    for (var year = 0; year < num_years; ++year) 
    {
        previous_cash[year] = 0;

        for (var days_til_magfest = start_day; days_til_magfest < num_cal_days; ++days_til_magfest)
        {
            if (data[year][days_til_magfest])
            {
                previous_cash[year] = data[year][days_til_magfest][1];
                break;
            }
        }
    }

    //var magfest10_date=new Date("January 5, 2012 00:00:00");
  //  var ms_per_day = 1000 * 60 * 60 * 24;

    for (var days_til_magfest = start_day; days_til_magfest < num_cal_days; ++days_til_magfest)
    {
        var row = new Array();
//        var date1 = new Date(magfest10_date.getTime() - ms_per_day * (days_til_magfest - 365) );

        row.push(days_til_magfest.toString());
        // row.push(date1.toString());

        for (var year = start_year; year < end_year+1; ++year) 
        {
            var cash_on_hand = null;
            var new_cash = 0;
            if (data[year][days_til_magfest]) 
            {
                cash_on_hand = data[year][days_til_magfest][1];
                new_cash = cash_on_hand - previous_cash[year];
                previous_cash[year] = cash_on_hand;
            }
            row.push(new_cash);
        }
        chart_data2.addRow(row);
    }

    var formatter = new google.visualization.NumberFormat({prefix: '$'});
    formatter.format(chart_data, 1);
    formatter.format(chart_data, 2);
    formatter.format(chart_data, 3);
    formatter.format(chart_data, 4);
    formatter.format(chart_data, 5);

    formatter.format(chart_data2, 1);
    // formatter.format(chart_data2, 2);
    /*formatter.format(chart_data2, 3);
    formatter.format(chart_data2, 4);
    formatter.format(chart_data2, 5);*/

    var chart = new google.visualization.LineChart(document.getElementById('graph'));
    chart.draw(chart_data, {height: 600, title: 'Magfest income by year [days til start of magfest]'});

    var chart2 = new google.visualization.ColumnChart(document.getElementById('graph2'));
    chart2.draw(chart_data2, {height: 600, title: 'Magfest income by day'});
    
    var table = new google.visualization.Table(document.getElementById('table_div'));
    table.draw(chart_data, {showRowNumber: true});
};
