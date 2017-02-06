// get the current server date and the current browser date
// if they out of sync by more than 2 days, show an error message.
// The reason this is useful is as a check to make sure the machine running the web browser has the correct time.
// If the time is incorrect, certain things involving SSL certificates won't work. i.e. Stripe, and other stuff
// Put this on any page that uses Stripe, especially any page that takes credit cards at the door on old laptops with
// broken batteries that can't save the right time (yes......   really.....   Magfest.......)
function showAlertIfServerAndClientDatesMismatched() {
    $.getJSON('../registration/stats', function (stats) {
        if (!stats.warn_if_server_browser_time_mismatch) {
            return;
        }

        var server_current_timestamp = new Date(stats.server_current_timestamp * 1000);
        var local_current_timestamp = new Date();

        var oneDay = 24 * 60 * 60 * 1000; // hours*minutes*seconds*milliseconds
        var diffDays = Math.round(Math.abs((server_current_timestamp.getTime() - local_current_timestamp.getTime()) / (oneDay)));

        if (diffDays > 3) {
            alert("WARNING: Server time and client time are grossly mismatched. " +
            "This will interfere with SSL which will cause errors with Stripe and other ubersystem functionality.  Please fix your clock!" +
            "(server time="+server_current_timestamp.toString()+"), (browser time="+local_current_timestamp.toString()+")");
        }
    });
}

showAlertIfServerAndClientDatesMismatched();
