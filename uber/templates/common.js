var csrf_token = '{% if CSRF_TOKEN %}{{ CSRF_TOKEN }}{% endif %}';

var setVisible = function(selector, visible) {
    $(selector)[visible ? 'show' : 'hide']();
}

$.field = function(field) {
    var $field = $('[name=' + field + ']');
    return $field.size() ? $field : null;
};

$.val = function(field) {
    var val = $.field(field).val();
    if ($.field(field).is(':radio')) {
        val = $.field(field).filter(':checked').val();
    }
    return val.match(/^\W*\d+\W*$/) ? parseInt(val) : val;
};

$.focus = function(field) {
    $.field(field).focus();
};

var RATINGS = {
    {{ RATED_GOOD }}: {
        false: '../static/images/check_blank.png',
        true:  '../static/images/check_filled.png'
    },
    {{ RATED_BAD }}: {
        prompt: 'Please explain how this volunteer performed poorly:',
        false: '../static/images/lookofdisapproval.jpg',
        true:  '../static/images/lookofdisapproval_selected.jpg'
    },
    {{ RATED_GREAT }}: {
        prompt: 'Please explain how this volunteer went above and beyond:',
        false: '../static/images/aplus_blank.jpg',
        true:  '../static/images/aplus_filled.jpg'
    }
};
var renderRating = function(shift, $td) {
    shift = typeof shift === 'string' ? SHIFTS[shift] : shift;
    $td = ($td || $('#rating' + shift.id)).addClass('rating').data('shift', shift);
    $.each([{{ RATED_GOOD }}, {{ RATED_BAD }}, {{ RATED_GREAT }}], function(i, rating) {
        $td.append(
            $('<img/>').attr('src', RATINGS[rating][shift.rating === rating])
                       .attr('title', shift.comment)
                       .data('rating', rating));
    });
    return $td;
};
var setupRatingClickHandler = function() {
    $(document.body).on('click', 'td.rating img', function(event) {
        var $img = $(event.target);
        var shift = $img.parent().data('shift');
        var rating = $img.data('rating');
        var comment = '';
        while (comment === '' && RATINGS[rating].prompt) {
            comment = prompt(RATINGS[rating].prompt);
        }
        if (comment !== null ) {
            var params = {shift_id: shift.id, rating: rating, comment: comment, csrf_token: csrf_token};
            $.post('../jobs/rate', params, function(json) {
                $img.parent().find('img').each(function(){
                    var r = $(this).data('rating');
                    $(this).attr('title', comment)
                           .attr('src', RATINGS[r][r == rating]);
                });
            }, 'json');
        }
    });
};
var setStatus = function(shiftId, status) {
    var $status = $(status);
    $.post('../jobs/set_worked', {id: shiftId, worked: $status.val(), csrf_token: csrf_token}, function(result) {
        if (result.error) {
            alert(result.error);
        } else {
            $status.parent().empty()
                .append('<i>' + result.status_label + '</i> &nbsp; ')
                .append($undoForm('../jobs/undo_worked', {id: shiftId}));
            if ($status.val() == {{ SHIFT_WORKED }}) {
                renderRating(shiftId);
            }
        }
    });
};
var $undoForm = function(path, params, linkText) {
    var $form = $('<form method="POST"></form>').attr("action", path);
    $.each($.extend(params, {csrf_token: csrf_token}), function(name, value) {
        $('<input type="hidden" />').attr("name", name).attr("value", value).appendTo($form);
    });
    var $undoLink = $('<a href="#"></a>').text(linkText || "Undo").click(function(e) {
        e.preventDefault();
        $form.submit();
    });
    return $().add($undoLink).add($form);
};

function showTop(message) {
    $("#top").show("fast").find("td:first").html(message);
}
function hideTop() {
    $("#top").hide("fast");
}
