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
                hideMessageBox();
                var message = json.message;
                if (json.success) {
                    $("#message-alert").addClass("alert-info").show().children('span').html(message);
                    window.history.replaceState("", document.title, window.location.href.replace(location.hash, "") + old_hash);
                    if(loadForm){loadForm("History");}
                } else {
                    showErrorMessage(message);
                }
            },
            error: function () {
                showErrorMessage('Unable to connect to server, please try again.');
            }
        });
    });
});