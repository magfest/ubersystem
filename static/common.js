
function setVisible(selector, visible) {
    $(selector)[visible ? "show" : "hide"]();
}

$.field = function(field) {
    return $("[name=" + field + "]");
};

$.val = function(field) {
    var val = $.field(field).val();
    try {
        return val == "" ? val : parseInt(val);
    } catch(ex) {
        return val;
    }
};

$.focus = function(field) {
    $.field(field).focus();
};
