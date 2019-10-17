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
                toastr.clear();
                var message = json.message;
                if (json.success) {
                    toastr.info(message);
                    window.location.hash = old_hash;
                } else {
                    toastr.error(message);
                }
            },
            error: function () {
                toastr.error('Unable to connect to server, please try again.');
            }
        });
    });
});