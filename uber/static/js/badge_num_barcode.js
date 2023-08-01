function barcodeScanned(barcode) {
    $.post("../registration/qrcode_reader", {csrf_token: csrf_token, qrcode: barcode})
        .success(function (json) {
            hideMessageBox();
            var message = json.message;
            if (json.success) {
                if ($("#search_bar").size()) { $("#search_bar").val(json.data).parents('form').submit() }
                else { offerBarcodeOpts(json.data, "Attendee UUID") }
            } else {
                $.post("../barcode/get_badge_num_from_barcode", {csrf_token: csrf_token, barcode: barcode})
                    .done(function (data) {
                        if (data['badge_num'] == -1) { showErrorMessage(data['message']); }
                        else if ($("#checkin-badge").size() && $("#checkin-badge").is(":visible")) { $("#checkin-badge").val(data['badge_num']); }
                        else if ($("#badge_num").size()) { $("#badge_num:focus").val(data['badge_num']); }
                        else if ($("#search_bar").size()) { $("#search_bar").val(data['badge_num']); }
                        else { offerBarcodeOpts(data['badge_num'], "Badge number"); }
                    })
                    .fail(function(message) {
                        showErrorMessage(message);
                    });
            }
        })
        .fail(function () {
            showErrorMessage('Unable to connect to server, please try again.');
        })
}

function offerBarcodeOpts(barcode, barcode_type) {
    bootbox.confirm({
    title: "Search for barcode?",
    message: "Would you like to search the database for this barcode? This will open in a new window." +
    "<br/><br/>Barcode type: " + barcode_type +
    "<br/>Barcode: " + barcode,
    buttons: {
        cancel: {
            label: '<i class="fa fa-times"></i> Cancel'
        },
        confirm: {
            label: '<i class="fa fa-check"></i> Confirm'
        }
    },
    callback: function (result) {
        if (result) {
            window.open("../registration/index?search_text=" + barcode)
        }
    }
});
}