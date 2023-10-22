warnBeforeLogout = function() {
    bootbox.confirm({
    backdrop: true,
    title: 'Log out?',
    message: '<p>Are you sure you want to log out?</p>' +
        '<p>This will <strong>delete the dealer application information</strong> you have entered so far' +
        ' and you will have to fill out the form again. It cannot be undone.</p>',
    buttons: {
        confirm: { label: 'Log out', className: 'btn-danger' },
        cancel: { label: 'Nevermind', className: 'btn-outline-secondary' }
    },
    callback: function (result) {
        if (result) {
            window.location = "../preregistration/logout";
        }
    }
    });
}