
function setVisible(selector, visible) {
    $(selector)[visible ? "show" : "hide"]();
}

$.field = function(field) {
    var $field = $("[name=" + field + "]");
    return $field.size() ? $field : null;
};

$.val = function(field) {
    var val = $.field(field).val();
    if ($.field(field).is(":radio")) {
        val = $.field(field).filter(":checked").val();
    }
    return val.match(/^\W*\d+\W*$/) ? parseInt(val) : val;
};

$.focus = function(field) {
    $.field(field).focus();
};
