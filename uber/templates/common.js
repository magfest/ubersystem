var csrf_token = '{{ c.CSRF_TOKEN }}';

var setVisible = function (selector, visible) {
    $(selector)[visible ? 'show' : 'hide']();
}

$.field = function (field) {
    var $field = $('[name=' + field + ']');
    return $field.size() ? $field : null;
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

var RATINGS = {
    {{ c.RATED_GOOD }}: {
        false: '../static/images/check_blank.png',
        true:  '../static/images/check_filled.png'
    },
    {{ c.RATED_BAD }}: {
        prompt: 'Please explain how this volunteer performed poorly:',
        false: '../static/images/lookofdisapproval.jpg',
        true:  '../static/images/lookofdisapproval_selected.jpg'
    },
    {{ c.RATED_GREAT }}: {
        prompt: 'Please explain how this volunteer went above and beyond:',
        false: '../static/images/aplus_blank.jpg',
        true:  '../static/images/aplus_filled.jpg'
    }
};
var renderRating = function (shift, $td) {
    shift = typeof shift === 'string' ? SHIFTS[shift] : shift;
    $td = ($td || $('#rating' + shift.id)).addClass('rating').data('shift', shift);
    $.each([{{ c.RATED_GOOD }}, {{ c.RATED_BAD }}, {{ c.RATED_GREAT }}], function (i, rating) {
        $td.append(
            $('<img/>').attr('src', RATINGS[rating][shift.rating === rating])
                       .attr('title', shift.comment)
                       .data('rating', rating));
    });
    return $td;
};
var setupRatingClickHandler = function () {
    $(document.body).on('click', 'td.rating img', function (event) {
        var $img = $(event.target);
        var shift = $img.parent().data('shift');
        var rating = $img.data('rating');
        var comment = '';
        while (comment === '' && RATINGS[rating].prompt) {
            comment = prompt(RATINGS[rating].prompt);
        }
        if (comment !== null ) {
            var params = {shift_id: shift.id, rating: rating, comment: comment, csrf_token: csrf_token};
            $.post('../jobs/rate', params, function (json) {
                $img.parent().find('img').each(function (){
                    var r = $(this).data('rating');
                    $(this).attr('title', comment)
                           .attr('src', RATINGS[r][r == rating]);
                });
            }, 'json');
        }
    });
};
var setStatus = function (shiftId, status) {
    var $status = $(status);
    var statusVal = parseInt($status.val());
    $.post('../jobs/set_worked', {id: shiftId, status: statusVal, csrf_token: csrf_token}, function (result) {
        if (result.error) {
            alert(result.error);
        } else {
            var statusLabel = _(result.shifts).filter({id: shiftId}).pluck('worked_label').first() || 'Unexpected Error';
            $status.parent().empty()
                .append('<i>' + statusLabel + '</i> &nbsp; ')
                .append($undoForm('../jobs/undo_worked', {id: shiftId}));
            if (statusVal === {{ c.SHIFT_WORKED }}) {
                renderRating(shiftId);
            }
        }
    });
};
var $undoForm = function (path, params, linkText) {
    var $form = $('<form method="POST"></form>').attr("action", path);
    $.each($.extend(params, {csrf_token: csrf_token}), function (name, value) {
        $('<input type="hidden" />').attr("name", name).attr("value", value).appendTo($form);
    });
    var $undoLink = $('<a href="#"></a>').text(linkText || "Undo").click(function (e) {
        e.preventDefault();
        $form.submit();
    });
    return $().add($undoLink).add($form);
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

var DISABLE_STRIPE_BUTTONS_ON_CLICK = true;
var MENU = [
    {% if c.HAS_ACCOUNTS_ACCESS %}
        {Accounts: '../accounts/'},
    {% endif %}
    {% if c.HAS_PEOPLE_ACCESS or c.HAS_REG_AT_CON_ACCESS %}
        {People: [
            {Attendees: '../registration/{% if c.AT_THE_CON %}?invalid=True{% endif %}'},
            {Groups: '../groups/'},
            {% if c.HAS_PEOPLE_ACCESS %}
                {'All Untaken Shifts': '../jobs/everywhere'},
                {Jobs: '../jobs/'},
            {% endif %}
            {% if c.HAS_WATCHLIST_ACCESS %}
                {Watchlist: '../registration/watchlist_entries'},
            {% endif %}
            {'Feed of Database Changes': '../registration/feed'}
        ]},
    {% endif %}
    {% if c.HAS_STUFF_ACCESS %}
        {Schedule: [
            {'View Schedule': '../schedule/'},
            {'Edit Schedule': '../schedule/edit'}
        ]},
    {% endif %}
    {% if c.HAS_STATS_ACCESS %}
        {Statistics: '../summary/'}
    {% endif %}
];
$(function() {
    $(window).load(function() {
        $(".loader").fadeOut("fast");
    });
    toastr.options = {
        closeButton: true,
        debug: false,
        positionClass: "toast-top-full-width",
        onclick: null,
        showDuration: "300",
        hideDuration: "1000",
        timeOut: "0",
        extendedTimeOut: "0",
        showEasing: "swing",
        hideEasing: "linear",
        showMethod: "fadeIn",
        hideMethod: "fadeOut"
    };
    var message = '{{ message }}';
    if (message.length) {
        toastr.info(message);
    }
    $('.datatable').dataTable({
        aLengthMenu: [
            [25, 50, 100, 200, -1],
            [25, 50, 100, 200, "All"]
            ],
        stateSave: true
    });
    $('.date').datetextentry({
        field_order: 'MDY',
        min_year : '1890',
        max_date : function() { return this.get_today(); },
        max_date_message : 'You cannot be born in the future.',
        show_tooltips : false,
        errorbox_x    : -135,
        errorbox_y    : 28
    });
    $('.geolocator').geocomplete({
        details: '.address_details',
        detailsAttribute: 'data-geo'
    });
    $('.focus:first').focus();
    if (window.DISABLE_STRIPE_BUTTONS_ON_CLICK) {
        // we can't intercept the Javascript form submit, so once someone has clicked the Stripe
        // submit button, listen for us leaving the page and disable the buttons then
        $(document).on('click', 'form > .stripe-button-el', function () {
            $(window).on('beforeunload', function () {
                $('a > .stripe-button-el').unwrap().prop('disabled', true).unwrap();
            });
        });
    }
    // prevent people from paying after prereg closes
    {% if c.PRE_CON %}
        if ($('form.stripe').size()) {
            var prevHour = new Date().getHours();
            var checkHour = function() {
                var currHour = new Date().getHours();
                if (currHour != prevHour) {
                    location.reload();
                } else {
                    prevHour = currHour;
                    setTimeout(checkHour, 1000);
                }
            };
            checkHour();
        }
    {% endif %}
    var $menu = $('#main-menu');
    $.each(MENU, function (i, section) {
        var name = _.keys(section)[0], links = _.values(section)[0];
        if (typeof links === 'string') {
            $menu.append(
                $('<li></li>').append(
                    $('<a></a>').attr('href', links).text(name)));
        } else {
            var $submenu = $('<ul class="dropdown-menu" role="menu"></ul>');
            $.each(links, function (i, link) {
                var label = _.keys(link)[0], href = _.values(link)[0];
                var $li = $('<li></li>');
                var $link = $('<a></a>').text(label);
                if (href) {
                    $link.attr('href', href);
                } else {
                    $li.addClass('disabled');
                }
                $submenu.append($li.append($link));
            });
            $('<li></li>')
                .addClass('dropdown')
                .append('<a href="#" class="dropdown-toggle" data-toggle="dropdown">' + name + '<span class="caret"></span></a>')
                .append($submenu)
                .appendTo($menu);
        }
    });
});
