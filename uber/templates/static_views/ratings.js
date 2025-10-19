let RATINGS = {
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

let UNRATED = {{c.UNRATED}};

var $id = function(id, el) {
    var $el = $('#' + id);
    if (!$el.length) {
       $el = $(el).attr('id', id);
    }
    return $el;
};

let setupShiftRatingClickHandler = function () {
    $(document.body).on('click', '.rating img', function (event) {
        let $img = $(event.target);
        let $container = $img.parent();
        let shift = $container.data('shift');
        let rating = $img.data('rating');
        let comment = '';
        let isSameRating = shift.rating === rating;

        //If they have chosen the same rating the shift already has
        //Unset it which allows for an "undo" feature.
        if(isSameRating){
            let params = {
                shift_id: shift.id,
                rating: UNRATED, // No rating
                comment: '',
                csrf_token: csrf_token
            };
            $.post('../shifts_admin/rate', params, function (json) {
                $container.find('img').each(function () {
                    var r = $(this).data('rating');
                    $(this)
                        .attr('title', '')
                        .attr('src', RATINGS[r][false]);
                });

                shift.rating = UNRATED;
                shift.comment = '';
            }, 'json');
        } else {
            while (comment === '' && RATINGS[rating].prompt) {
                comment = prompt(RATINGS[rating].prompt);
            }

            if (comment !== null ) {
                let params = {shift_id: shift.id, rating: rating, comment: comment, csrf_token: csrf_token};
                $.post('../shifts_admin/rate', params, function (json) {
                    $img.parent().find('img').each(function () {
                        var r = $(this).data('rating');
                        $(this)
                            .attr('title', comment)
                            .attr('src', RATINGS[r][r == rating]);
                    });
                    //Update our copy in memory of the shift since it didn't come back from the server API
                    //And this is a *success* call back
                    shift.rating = rating;
                    shift.comment = comment;
                }, 'json');
            }
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
            $.map([{{ c.RATED_BAD }}, {{ c.RATED_GREAT }}], function(rating, i) {
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
    $.post('../shifts_admin/set_worked', {
        id: shift.id,
        status: status,
        csrf_token: csrf_token
    }, function(job) {
        if (!job.error) {
            shift = Array.isArray(job.shifts) ? job.shifts.find(s => s.id === shift.id) : undefined;
            if (typeof SHIFTS !== 'undefined') {
                SHIFTS[shift.id] = shift;
            }
        }
        if (onUpdateShiftStatus) {
            onUpdateShiftStatus(job, shift);
        }
    }, 'json');
};
