var PREREG_CHECK_INTERVAL = 15 * 60 * 1000;
var checkCap = function () {
    $.getJSON('../preregistration/check_prereg', function (check) {
        if (check.force_refresh) {
            location.reload();  // Reload the page to prevent registering after reg is closed
        } else {
            setTimeout(checkCap, PREREG_CHECK_INTERVAL);
        }
    });
};
setTimeout(checkCap, PREREG_CHECK_INTERVAL);

{% if c.COLLECT_FULL_ADDRESS %}
    var setInternational = function () {
        countryName = $('input[name="country"]').val();
        if(countryName == 'USA' || countryName == 'US' || countryName == 'United States') {
            $('input[name="international"]').prop('checked', false);
        } else {
            $('input[name="international"]').prop('checked', true);
        }
    };
    $(function() {
        $('#international').hide();
        setInternational()
    });
{% endif %}

var togglePrices = function () {
    var showTotalPrices = {% if c.PAGE_PATH == '/preregistration/form' and not c.DONATION_SLIDER_DISPLAY %}($.val('badge_type') === {{ c.ATTENDEE_BADGE }}){% else %}false{% endif %};
    $.each(BADGE_TYPES.options, function (i, type) {
        var $price = $(BADGE_TYPES.selector).slice(i, i + 1).find('.price').empty();
        var $price_notice = $(BADGE_TYPES.selector).slice(i, i + 1).find('.price_notice').empty();
        if (showTotalPrices) {
            $price.append(': $').append(type.extra + {{ c.BADGE_PRICE }});
            {% for amount_extra, val in c.PREREG_DONATION_OPTS %}
                if (type.extra == {{ amount_extra }} && type.extra >= {{ c.SUPPORTER_LEVEL }}) {
                    $price_notice.append('{{ price_notice("Supporter registration", c.SUPPORTER_DEADLINE, c.SUPPORTER_LEVEL) }}')
                } else if (type.extra == {{ amount_extra }}) {
                    $price_notice.append('{{ price_notice("Preregistration", c.PREREG_TAKEDOWN, amount_extra) }}')
                }
            {% endfor %}
        } else if (type.extra) {
            $price.append(': +$').append(type.extra);
        }
    });
    $.each(REG_TYPES.options, function (i, type) {
        var $price = $(REG_TYPES.selector).slice(i, i + 1).find('.price').empty();
        var $price_notice = $(REG_TYPES.selector).slice(i, i + 1).find('.price_notice').empty();
        if (!showTotalPrices) {
            if (type.title == 'Single Attendee') {
                $price.append(': $').append({{ c.BADGE_PRICE }});
                $price_notice.append('{{ price_notice("Preregistration", c.PREREG_TAKEDOWN) }}')
            } else if (type.title == 'Group Leader') {
                $price.append(': $').append({{ c.GROUP_PRICE }}).append(' per badge');
                $price_notice.append('{{ price_notice("Group registration", c.GROUP_PREREG_TAKEDOWN, 0, c.GROUP_DISCOUNT) }}')
            }
        }
    });
};
var setBadge = function (types, index) {
    var type = types.options[index];
    $(types.selector)
        .removeClass('active')
        .slice(index, 1 + index)
        .addClass('active');
    (type.onClick || $.noop)();
};
var setKickinFromBadge = function (types, index) {
    var type = types.options[index];
    if (type.extra !== undefined && type.extra !== null && $.field('amount_extra')) {
        {% if c.DONATION_SLIDER_DISPLAY %}
            $('input:radio[name=amount_extra][value='+ type.extra +']').prop('checked', true).trigger('change');
        {% else %}
            $.field('amount_extra').val(type.extra).trigger('change');
        {% endif %}
    }
};
var makeBadgeMatchExtra = function () {
    if (_(BADGE_TYPES.options).size()) {
        var target = 0;
        $.each(BADGE_TYPES.options, function (i, badgeType) {
            if (badgeType.extra && $.field('amount_extra') && badgeType.extra == $.val('amount_extra')) {
                target = i;
            }
        });
        if (!$(BADGE_TYPES.selector).slice(target, 1 + target).is('.active')) {
            setBadge(BADGE_TYPES, target);
        }
    }
};
$(function () {
    if ($(BADGE_TYPES.row).size()) {
        $.each([REG_TYPES, BADGE_TYPES], function (i, types) {
            $.each(types.options, function (index, type) {
                $(types.row).append(
                    $('<div class="col-sm-3"></div>').append(
                        $('<a class="list-group-item"></a>').addClass(types.selector.substring(1)).click(function () {
                            setBadge(types, index);
                            setKickinFromBadge(types, index);
                        }).append(
                            $('<h4 class="list-group-item-heading"></h4>')
                                .append(type.title)
                                .append('<span class="price"></span>')
                        ).append(
                            $('<p class="list-group-item-text"></p>').html(type.description).append('<span class="price_notice"></span>'))));
            });
            $(types.row).append('<div style="clear:both">&nbsp;</div>');
        });
        if (window.REG_TYPES && $(REG_TYPES.row).size()) {
            setBadge(REG_TYPES, $.field('name') && $.val('name') ? 1 : 0);  // default to attendee or group
        }
        makeBadgeMatchExtra();
        if ($.field('amount_extra')) {
            {% if not c.DONATION_SLIDER_DISPLAY %}
                $.field('amount_extra').parents('.form-group').hide();
            {% else %}
                $.field('amount_extra').on('change', makeBadgeMatchExtra);
            {% endif %}
        }
    }
});
