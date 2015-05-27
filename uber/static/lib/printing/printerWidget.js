/**
* This file is a jQuery plugin which drives our printer.
*/


/**
* Our main function to call.
*
* @param string base_path The base path to our module installation.
*/
jQuery.fn.printerWidget = function(base_path, base_url) {

	if (!jQuery.fn.printerWidget.debugNoMSIE) {
		if (!jQuery.fn.printerWidget.isMsie()) {
			$("#edit-current").val("Sorry, but printing can only be done from MSIE.");
			return(false);
		}
	}


	//
	// At this point, we're in MSIE.
	//

	jQuery.fn.printerWidget.base_path = base_path;
	jQuery.fn.printerWidget.base_url = base_url;

	//
	// Initialize our messages array and start scanning.
	//
	jQuery.fn.printerWidget.messages = [];
	jQuery.fn.printerWidget.messageScan();

	//
	// Set our button handlers.
	//
	jQuery.fn.printerWidget.isPrinting = false;
	jQuery.fn.printerWidget.setHandlers();

} // End of printerWidget()


/**
* Are we debugging in a non-MSIE browser?  Set this to true if we are.
*/
//jQuery.fn.printerWidget.debugNoMSIE = false;
//jQuery.fn.printerWidget.debugNoMSIE = true;


/**
* Return true if we're in MSIE, false otherwise.
*/
jQuery.fn.printerWidget.isMsie = function() {

	if ($.browser.msie) {
		return(true);
	}

	return(false);

} // End of isMsie()


/**
* Set handlers for our button to stop and start the printing.
*/
jQuery.fn.printerWidget.setHandlers = function() {

	$("#edit-button").click(function() {

		if (jQuery.fn.printerWidget.isPrinting) {
			//
			// Stop printing
			//
			jQuery.fn.printerWidget.isPrinting = false;
			jQuery.fn.printerWidget.setStatus("Printer client is currently stopped.");
			$("#edit-button").val("Start Printing Badges");
			jQuery.fn.printerWidget.printStop();

			//
			// Settings can be edited again
			//
			$("#edit-interval").attr("disabled", false);
			$("#edit-type").attr("disabled", false);

		} else {
			//
			// Start printing
			//
			jQuery.fn.printerWidget.isPrinting = true;
			jQuery.fn.printerWidget.setStatus("Printer client started.");
			$("#edit-button").val("Stop Printing Badges");
			jQuery.fn.printerWidget.printStart();

			//
			// Don't allow settings to be edited while printing.
			//
			$("#edit-interval").attr("disabled", true);
			$("#edit-type").attr("disabled", true);

		}

		//
		// Don't submit this form, ever.
		//
		return(false);

		});

	//
	// Enable the button, now that we have our handler in place.
	//
	$("#edit-button").attr("disabled", "");

	jQuery.fn.printerWidget.setStatus("Printer client is currently stopped.");

} // End of setHandlers()


/**
* Update our status field.
*
* @param string message The message to display in the status field.
*/
jQuery.fn.printerWidget.setStatus = function(message) {

	if (jQuery.fn.printerWidget.debugNoMSIE) {
		message = "(Debug No MSIE) " + message;
	}

	jQuery.fn.printerWidget.messages.push(message);


} // End of setStatus()


/**
* Function to scan for our messages array for messages.  It is started once
*	at the beginning of this plugin, and repeatedly calls itself afer
*	a delay.  It checks to see if there is an outstanding message to
*	display, and does so.
*/
jQuery.fn.printerWidget.messageScan = function() {

	if (jQuery.fn.printerWidget.messages.length > 0) {

		var message = jQuery.fn.printerWidget.messages.shift();
		//$("#edit-interval").parent().append("Message: " + message); // Debugging
		$("#edit-current").val(message);

	}

	var interval = 1000;
	var interval = 500;
	setTimeout(jQuery.fn.printerWidget.messageScan, interval);

}


/**
* Wrapper to start Word.
*/
jQuery.fn.printerWidget.startWord = function() {

	//	
	//	Debging while not in MSIE?
	//	
	if (jQuery.fn.printerWidget.debugNoMSIE) {
		return(true);
	}	

	jQuery.fn.printerWidget.app = new ActiveXObject("word.application");
	jQuery.fn.printerWidget.app.visible = true;

	var file = jQuery.fn.printerWidget.base_path + "/files/badge.doc";
	//$("#edit-interval").parent().append(file); // Debugging
	jQuery.fn.printerWidget.doc = jQuery.fn.printerWidget.app.Documents.Open(file);

} // End of startWord()


/**
* Wrapper to print a single conbadge.
*
* @param integer $id 
*/
jQuery.fn.printerWidget.printBadge = function(id, badge_name, badge_num, 
	membership_type) {

	if (badge_num == undefined) {
		var message = "Badge number is undefined. Aborting!<br/>";
		$("#edit-interval").parent().append(message); // Debugging
		return(null);
	}

	//	
	//	Debging while not in MSIE?
	//	
	if (jQuery.fn.printerWidget.debugNoMSIE) {
		jQuery.fn.printerWidget.setStatus("Sending badge '" + badge_name 
			+ "' (" + badge_num + ") to the printer...");
		jQuery.fn.printerWidget.setStatus("Badge '" + badge_name 
			+ "' (" + badge_num + ") sent to the printer!");

	} else {
		//
		// We're in MSIE.  Talk to Word.
		//

		//
		// Do bookmark substitution.
		//
		jQuery.fn.printerWidget.doc.BookMarks("badge_name").range.Text = 
			badge_name;
		jQuery.fn.printerWidget.doc.BookMarks("badge_number").range.Text = 
			badge_num;
		jQuery.fn.printerWidget.doc.BookMarks("membership_type").range.Text = 
			membership_type;

		//
		// Print out this badge.
		//
		jQuery.fn.printerWidget.setStatus("Sending badge '" + badge_name 
			+ "' (" + badge_num + ") to the printer...");
		jQuery.fn.printerWidget.app.ActiveDocument.PrintOut();
		jQuery.fn.printerWidget.setStatus("Badge '" + badge_name 
			+ "' (" + badge_num + ") sent to the printer!");

		//
		// Under the changes, so that the bookmarks come back. (silly, I know...)
		//
		jQuery.fn.printerWidget.doc.Undo(3);

	}

	//
	// If we still made it here, assume that the printing went 
	// successfully (since there's no way to really check that I know of...)
	// and mark the job as printed.
	//
	//$("#edit-interval").parent().append(id); // Debugging
	var url = jQuery.fn.printerWidget.base_url 
		+ "/admin/reg/utils/print/client/ajax/update/" + id + "/printed";
	//$("#edit-interval").parent().append(url); // Debugging

	//
	// No callback because nothing is returned.
	//
	$.get(url);


} // End of printBadge()


/**
* Wrapper to quit Word.
*/
jQuery.fn.printerWidget.stopWord = function() {

	//	
	//	Debging while not in MSIE?
	//	
	if (jQuery.fn.printerWidget.debugNoMSIE) {
		return(true);
	}	

	jQuery.fn.printerWidget.app.ActiveDocument.close(false);
	jQuery.fn.printerWidget.app.quit();
}


/**
* Return our current interval, in milliseconds.
*/
jQuery.fn.printerWidget.getInterval = function() {

	//
	// First make sure we have an integer
	//
	var retval = $("#edit-interval").val();
	retval = parseInt(retval);

	//
	// Convert to milliseconds
	//
	retval *= 1000;

	//
	// Enforce a 2 second minimum
	//
	if (retval < 2000) {
		retval = 2000;
	}

	return(retval);

} // End of getInterval()


/**
* Our main printing loop.  This will ask the server for a badge to print,
*	print up that badge, and then loop.
*/
jQuery.fn.printerWidget.printLoop = function() {

	//
	// If we're not printing anymore, stop here.
	//
	if (!jQuery.fn.printerWidget.isPrinting) {
		return(false);
	}

	var printer = $("#edit-type").val();

	//
	// Sanity check
	//
	if (printer == "") {
		var message = "Printer type value is empty!";
		jQuery.fn.printerWidget.setStatus(message);
		return(false);
	}

	jQuery.fn.printerWidget.setStatus(
		"Querying for badges in queue for printer '" + printer + "'...");

	//$("#edit-interval").parent().append(""); // Debugging

	var url = jQuery.fn.printerWidget.base_url 
		+ "/admin/reg/utils/print/client/ajax/fetch/" + printer;
	//$("#edit-interval").parent().append(url); // Debugging

	$.get(url, {}, jQuery.fn.printerWidget.fetchCallback);

} // End of printLoop()



/**
* This function called when an AJAX request to our webserver is successful.
*/
jQuery.fn.printerWidget.fetchCallback = function(data) {

	//data = "foobar"; // Set to force undefined badges

	if (data) {
		//
		// Parse our values
		// 
		var values = jQuery.fn.printerWidget.parseGetData(data);

		badge = {};
		badge["name"] = values["badge_name"];
		badge["num"] = values["badge_num_full"];
		badge["type"] = values["member_type"];

		jQuery.fn.printerWidget.printBadge(values["id"], 
			values["badge_name"], values["badge_num_full"], values["member_type"]);

	} else {
		jQuery.fn.printerWidget.setStatus("No print jobs found!");

	}

	//
	// Schedule our next run
	//
	var interval = jQuery.fn.printerWidget.getInterval();

	jQuery.fn.printerWidget.setStatus("Sleeping for " + interval 
		+ " milliseconds...");
	setTimeout(jQuery.fn.printerWidget.printLoop, interval);

} // End of fetchCallback()


/**
* Parse a string of GET method data and turn it into a Javascript hash table.
* 
* Yeah, I would rather use JSON too, but I'm not sure if WAMP as the latest 
*	version of PHP...
*
* @param string data The GET method data
*/
jQuery.fn.printerWidget.parseGetData = function(data) {

	var retval = {};

	var items = data.split("&");
	for (key in items) {
		var item = items[key];
		var tmp = item.split("=");
		var key2 = tmp[0];
		//
		// Decode the value.  Helpful for folks use used unicode in their
		// badge names, such as Davin Wärter ;-)
		//
		var value2 = decodeURIComponent(tmp[1]);

		//
		// No, I don't know why the plus signs aren't being turned back 
		// into spaces.  I'll just do it here...
		//
		value2 = value2.replace(/\+/g, " ");

		retval[key2] = value2;
	}

	return(retval);

} // End of parseGetData()


/**
* Start printing, set up our event loop.
*/
jQuery.fn.printerWidget.printStart = function() {

	jQuery.fn.printerWidget.startWord();

	//
	// Start our loop
	//
	jQuery.fn.printerWidget.printLoop();

} // End of printStart()


/**
* Stop printing.
*/
jQuery.fn.printerWidget.printStop = function() {

	jQuery.fn.printerWidget.stopWord();

} // End of printStop()


