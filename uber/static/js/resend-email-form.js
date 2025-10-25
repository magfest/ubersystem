$("form[action='resend_email']").each(function(index) {
    $(this).submit(function (e) {
        // Prevent form submit.
        e.preventDefault();

        var data = $(this).serialize();
        var old_hash = window.location.hash;

        $.ajax({
            method: 'POST',
            url: '../email_admin/resend_email',
            dataType: 'json',
            data: data,
            success: function (json) {
                if(typeof loadForm != 'undefined') {
                    hideMessageBox('attendee-modal-alert');
                } else { hideMessageBox(); }
                var message = json.message;
                if (json.success) {
                    window.history.replaceState("", document.title, window.location.href.replace(location.hash, "") + old_hash);
                    if(typeof loadForm != 'undefined'){
                        loadForm("History").then(function(result) {
                            $("#attendee-modal-alert").addClass("alert-info").show().children('span').html(message);
                        });
                    } else { $("#message-alert").addClass("alert-info").show().children('span').html(message); };
                    window.scrollTo(0,0);
                } else {
                    if(typeof loadForm != 'undefined') {
                        showErrorMessage(message, 'attendee-modal-alert');
                    } else { showErrorMessage(message); }
                }
            },
            error: function () {
                showErrorMessage('Unable to connect to server, please try again.');
            }
        });
    });
});