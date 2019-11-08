loadAttendeeModal = function() {
form_link = window.location.hash
if (form_link && form_link.includes('attendee_form')) {
    form_link = form_link.substr(1);
    $('#attendee_modal').modal({show:true});
    $('#attendee_modal .modal-content').load('../registration/' + form_link, function(){
    if ($('#attendeeData').length) {
        $(window).trigger( 'runJavaScript' );
    } else {
        // We got redirected -- likely to the login page -- so load it properly
        toastr.error("Form loading failed.");
        window.location.hash = ""; // prevent refresh loops
        window.location.reload();
    }
    });
}
}
// Hide modal on Esc keydown
$(document).keydown(function(event) { 
if (event.keyCode == 27) { 
    $("#attendee_modal").modal('hide');
}
});
$(document).ready(function () {
loadAttendeeModal();
$(window).on('hashchange',function(){ loadAttendeeModal(); });
$('#attendee_modal').on('hidden.bs.modal', function () {
    var scrollV, scrollH, loc = window.location;
    if ("pushState" in history)
        history.pushState("", document.title, loc.pathname + loc.search);
    else {
        // Prevent scrolling by storing the page's current scroll offset
        scrollV = document.body.scrollTop;
        scrollH = document.body.scrollLeft;

        loc.hash = "";

        // Restore the scroll offset, should be flicker free
        document.body.scrollTop = scrollV;
        document.body.scrollLeft = scrollH;
    }
    })
}
);