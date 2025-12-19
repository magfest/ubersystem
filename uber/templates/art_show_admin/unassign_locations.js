var unassignLocation = function(id, removeSpace, alertId="message-alert") {
    $.ajax({
        method: 'POST',
        url: 'unassign_location',
        dataType: 'json',
        data: {
            id: id,
            remove_space: removeSpace,
            csrf_token: csrf_token,
        },
        success: function (json) {
            hideMessageBox();
            var message = json.message;
            if (json.success) {
                $("#" + alertId).addClass("alert-info").show().children('span').html(message);
                window.scrollTo(0,0); setTimeout(() => { window.scrollTo(0, 0); }, 100);
            } else {
                showErrorMessage(message, alertId);
            }
        },
        error: function () {
            showErrorMessage('Unable to connect to server, please try again.', alertId);
        }
    });
}

var confirmUnassignLocation = function(id, label, alertId) {
bootbox.dialog({
    backdrop: true,
    title: 'Unassign Location?',
    message: 'Are you sure you want to unassign location ' + label + ' from this artist? ' +
            'You can also remove the requested table/panel space from the application.',
    buttons: {
    confirm: {
        label: 'Unassign',
        className: 'btn-outline-danger',
        callback: function (result) {
        if(result) {
            unassignLocation(id, '', alertId)
        }
        }
    },
    remove_space: { 
        label: 'Unassign and Remove Space',
        className: 'btn-danger',
        callback: function (result) {
        if(result) {
            unassignLocation(id, 'true', alertId)
        }
        }
    },
    cancel: { label: 'Nevermind', className: 'btn-outline-secondary' }
    }
});
}