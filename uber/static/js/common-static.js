// STATIC CONTENT ONLY, included in EVERY PAGE

var setVisible = function (selector, visible) {
    $(selector)[visible ? 'show' : 'hide']();
}

$.field = function (field) {
    var $field = $('[name=' + field + ']');
    return $field.length ? $field : null;
};

$.val = function (field) {
    var val = $.field(field).val();
    if ($.field(field).is(':radio')) {
        val = $.field(field).filter(':checked').val();
    }
    return val.match(/^\W*\d+\W*$/) ? parseInt(val) : val;
};

$.focus = function (field) {
    $.field(field).focus();
};

$(function () {
    $('.datepicker').datepicker({
        changeMonth: true,
        changeYear: true,
        yearRange: '-100:+0',
        defaultDate: '-20y',
        dateFormat: 'yy-mm-dd'
    });
});
