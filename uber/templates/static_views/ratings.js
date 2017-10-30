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

var $id = function(id, el) {
    var $el = $('#' + id);
    if (!$el.length) {
       $el = $(el).attr('id', id);
    }
    return $el;
};

var setupShiftRatingClickHandler = function () {
    $(document.body).on('click', '.rating img', function (event) {
        var $img = $(event.target),
            shift = $img.parent().data('shift'),
            rating = $img.data('rating'),
            comment = '';

        while (comment === '' && RATINGS[rating].prompt) {
            comment = prompt(RATINGS[rating].prompt);
        }

        if (comment !== null ) {
            var params = {shift_id: shift.id, rating: rating, comment: comment, csrf_token: csrf_token};
            $.post('../jobs/rate', params, function (json) {
                $img.parent().find('img').each(function () {
                    var r = $(this).data('rating');
                    $(this)
                        .attr('title', comment)
                        .attr('src', RATINGS[r][r == rating]);
                });
            }, 'json');
        }
    });
};

var renderShiftRating = function(shift) {
    shift = typeof shift === 'string' ? SHIFTS[shift] : shift;
    if (shift.worked !== {{ c.SHIFT_WORKED }}) {
        return '';
    }

    return $id('rating_' + shift.id, '<span class="rating"></span>')
        .data('shift', shift)
        .append(
            $.map([{{ c.RATED_GOOD }}, {{ c.RATED_BAD }}, {{ c.RATED_GREAT }}], function(rating, i) {
                return $('<img/>')
                    .attr('src', RATINGS[rating][shift.rating === rating])
                    .attr('title', shift.comment)
                    .data('rating', rating);
            })
        );
};

var renderShiftStatus = function(shift, onUpdateShiftStatus) {
    shift = typeof shift === 'string' ? SHIFTS[shift] : shift;
    if (shift.worked === {{ c.SHIFT_UNMARKED }}) {
        return $('<select></select>').change(function(event) {
            updateShiftStatus(shift, $(event.target).val(), onUpdateShiftStatus);
        }).append(
            $.map({{ c.WORKED_STATUS_OPTS|jsonize }}, function(opt) {
                return $('<option></option>').val(opt[0]).text(opt[1]);
            })
        );
    }

    return $('<i>' + shift.worked_label + '&nbsp;&nbsp;</i>').add(
        $('<a href="#">Undo</a>').click(function(event) {
            event.preventDefault();
            updateShiftStatus(shift, {{ c.SHIFT_UNMARKED }}, onUpdateShiftStatus);
        }));
};

var updateShiftStatus = function(shift, status, onUpdateShiftStatus) {
    $.post('../jobs/set_worked', {
        id: shift.id,
        status: status,
        csrf_token: csrf_token
    }, function(job) {
        if (!job.error) {
            shift = _.filter(job.shifts, {id: shift.id})[0];
            if (typeof SHIFTS !== 'undefined') {
                SHIFTS[shift.id] = shift;
            }
        }
        if (onUpdateShiftStatus) {
            onUpdateShiftStatus(job, shift);
        }
    }, 'json');
};
