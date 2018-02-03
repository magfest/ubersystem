// ----------------------------------------------------------------------------
// process attendance data from uber and create cool looking graphs of it
// ----------------------------------------------------------------------------

var date_format = "DD-MM-YYYY";
var extra_attendance_data = [];

function get_first_useful_datapoint_index(raw_data) {
  var first_datapoint_index = Number.MAX_VALUE;

  for (var i = 0; i < raw_data.years.length; ++i) {
    var year = raw_data.years[i];

    for (var j = 0; j < year.registrations_per_day.length; ++j) {
      regs_this_day = year.registrations_per_day[j];
      if (regs_this_day == 0) {
        continue;
      }

      if (first_datapoint_index > j) {
        first_datapoint_index = j;
      }

      break;
    }
  }

  // grab that first zero datapoint to make it look nice.
  if (first_datapoint_index > 0) {
    first_datapoint_index--;
  }

  return first_datapoint_index;
}

function get_last_useful_datapoint_index(raw_data) {
  var last_datapoint_index = 0;

  for (var i = 0; i < raw_data.years.length; ++i) {
    var year = raw_data.years[i];

    for (var j = year.registrations_per_day.length-1; j >= 0; --j) {
      regs_this_day = year.registrations_per_day[j];
      if (regs_this_day == 0) {
        continue;
      }

      if (last_datapoint_index < j) {
        last_datapoint_index = j;
      }

      break;
    }
  }

  return last_datapoint_index;
}

function generate_date_labels(year, end_date_to_use, start_index, end_index) {
  // if end date is jan 8th, num_days = 3, then this should generate:
  // ['jan6', 'jan7', 'jan8']

  var total_num_days = year.registrations_per_day_cumulative_sum.length;

  if (start_index < 0 || end_index >= total_num_days) {
    throw "Error: invalid range specified for label data";
  }

  var end_date = moment(end_date_to_use, date_format);

  var labels = [];
  for (var i = start_index; i <= end_index; ++i) {
    var days_before_end_date = total_num_days - (i + 1);
    var current_date = end_date.clone().subtract(days_before_end_date, 'days');
    labels.push(current_date.format("MMM Do YYYY"));
  }

  return labels;
}

function generate_dataset(year_data, start_index, end_index, current_year) {
  var dataset = new Object();

  dataset.label = year_data.event_name;

  var data = year_data.registrations_per_day_cumulative_sum;
  if (start_index != 0 || end_index+1 != data.length) {
    data = data.slice(start_index, end_index+1);
  }

  dataset.data = data;

  if (!current_year) {
    dataset.fillColor = "rgba(220,220,220,0.2)";
    dataset.strokeColor = "rgba(220,220,220,1)";
    dataset.pointColor = "rgba(220,220,220,1)";
  } else {
    dataset.fillColor = "rgba(100,220,256,0.2)";
    dataset.strokeColor = "rgba(100,220,256,1)";
    dataset.pointColor = "rgba(80,256,256,1)";
  }

  dataset.pointStrokeColor = "#fff";
  dataset.pointHighlightFill = "#fff";
  dataset.pointHighlightStroke = "rgba(80,256,256,1)";

  return dataset;
}

// convert our raw data to chart.js's format
// assumes all years are the same # of datapoints
function convert_raw_attendance_data(raw_data)
{
  var chart_data = new Object();

  var first_useful_datapoint_index = get_first_useful_datapoint_index(raw_data);
  var last_useful_datapoint_index = get_last_useful_datapoint_index(raw_data);

  chart_data.labels = generate_date_labels(
    raw_data.years[0],
    raw_data.end_date_to_use,
    first_useful_datapoint_index,
    last_useful_datapoint_index
  );

  chart_data.datasets = [];

  for (var i = 0; i < raw_data.years.length; ++i) {
    var current_year = raw_data.years[i];

    var current_year_dataset = generate_dataset(
      current_year,
      first_useful_datapoint_index,
      last_useful_datapoint_index,
      i == raw_data.years.length-1
    );
    chart_data.datasets.push(current_year_dataset);
  }

  return chart_data;
}

function draw_attendance_chart(raw_data)
{
  var chart_data = convert_raw_attendance_data(raw_data);

  var ctx = $("#attendanceGraph").get(0).getContext("2d");

  var options = {
    animation: false,
    bezierCurve: true,
    pointDot: false,
    pointHitDetectionRadius: 1,
    scaleShowLabels: true,
    multiTooltipTemplate: "<%= datasetLabel %>: <%= value %>",
    showXLabels: 20
  };

  var attendanceChart = new Chart(ctx).Line(chart_data, options);
}

// read from the following GLOBAL VARIABLES and compile a combined data source from them:
// current_attendance_data - from THIS YEAR's live reg data
// extra_attendance_data - all OTHER YEARs' historical, non-live registration data.  this may not exist.
function collect_all_attendance_data()
{
  var all_attendance_data = new Object();

  // use this year's registration data as the base date for all other years
  all_attendance_data.end_date_to_use = moment(current_attendance_data.event_end_date, date_format);

  // start with the earlier years
  all_attendance_data.years = extra_attendance_data;

  // add the current year information (which is live from the data)
  all_attendance_data.years.push(current_attendance_data);

  return all_attendance_data;
}

function verify_data_has_same_amount_of_datapoints_each_year(all_attendance_data) {
  var previous_length = 0;
  var years = all_attendance_data.years;

  if (years.length == 0) {
    alert("No data was present to graph.");
    return false;
  }

  for (var i = 0; i < years.length; ++i) {
    var csum_length = years[i].registrations_per_day_cumulative_sum.length;
    var normal_length = years[i].registrations_per_day.length;

    if (csum_length != normal_length) {
      alert("ERROR: length of datapoints in a particular year doesn't match.");
      return false;
    }

    if (previous_length != 0 && normal_length != previous_length) {
      alert("ERROR: not all years' datapoint lengths match.  please fix.");
      return false;
    }

    previous_length = normal_length;
  }

  return true;
}

$( document ).ready(function() {

  // try and load optional data from previous comparison years.
  // it's OK for this to fail and it probably will unless the admin installs this file on the server
  $.getJSON( "../static/analytics/extra-attendance-data.json", function( data ) {
    extra_attendance_data = data;
  }).fail(function() {
    // couldn't load the extra data.  not a big deal, it may legitimately not be present
  }).always(function() {
    var all_attendance_data = collect_all_attendance_data();

    if (!verify_data_has_same_amount_of_datapoints_each_year(all_attendance_data)) {
      return;
    }

    draw_attendance_chart(all_attendance_data);
  });
});