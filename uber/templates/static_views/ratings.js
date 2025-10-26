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
    $(document.body).on('click', '.rating .comment-btn', function(event){
        let $btn = $(event.target);
        let $container = $btn.parent();
        let shift = $container.data('shift');
        //Launch the comment modal.
        let $modal = $("#shiftCommentModal");
        $modal.data("shift", shift);
        $modal.data("rating", shift.rating);
        $modal.find("#shiftCommentText").val(shift.comment || '');
        $modal.modal("show");
        //See commentSubmit for next step on modal submit.
    });

    $(document.body).on('click', '.rating img', function (event) {
        let $img = $(event.target);
        let $container = $img.parent();
        let shift = $container.data('shift');
        let rating = $img.data('rating');
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
            //Launch the comment modal.
            let $modal = $("#shiftCommentModal");
            $modal.data("shift", shift);
            $modal.data("rating", rating);
            $modal.find("#shiftCommentText").val(shift.comment || '');
            $modal.find("#shiftCommentRequired").show();
            $modal.modal("show");
            //See commentSubmit for next step on modal submit.
        }
    });
};

let updateCommentIcon = function($container, comment) {
    let $icon = $container.find("i.comment-btn");
    if ($icon.length === 0) {
        // No icon to update; just exit
        return;
    }

    if (comment && comment.trim() !== "") {
        $icon.removeClass("fa-comment-o").addClass("fa-comment");
    } else {
        $icon.removeClass("fa-comment").addClass("fa-comment-o");
    }
}

let commentSubmit = function () {
    let $modal = $("#shiftCommentModal");
    let shift = $modal.data("shift"); //Points to same object as container!
    let rating = $modal.data("rating");
    let $textarea = $modal.find("#shiftCommentText");
    let comment = $textarea.val().trim();

    if (!comment && rating !== UNRATED) {
        // show Bootstrap invalid feedback
        $textarea.addClass("is-invalid");
        $modal.find("#invalidShiftComment").show();
        return; // stop submission
    }

    let $container = $('#rating_' + shift.id); //find the right rating object.

    let params = {
        shift_id: shift.id,
        rating: rating,
        comment: comment,
        csrf_token: csrf_token
    };

     $.post('../shifts_admin/rate', params, function (jsonResponse) {
        //Update our copy in memory of the shift
        let updatedShift = jsonResponse.shift;
        shift.rating = updatedShift.rating;
        shift.comment = updatedShift.comment;

        $container.find('img').each(function () {
            var r = $(this).data('rating');
            $(this)
                .attr('title', comment)
                .attr('src', RATINGS[r][r == rating]);
        });
        updateCommentIcon($container, shift.comment);
        $modal.modal("hide");
        //Reset the modal state for the next launch
        $modal.find("#invalidShiftComment").hide();
        $modal.find("#shiftCommentRequired").hide();
        $textarea.removeClass("is-invalid");
        $modal.data("shift", undefined);

     }, 'json');
};

var renderShiftRating = function(shift) {
    shift = typeof shift === 'string' ? SHIFTS[shift] : shift;

    //Shift is not marked worked or unworked.
    if (shift.worked !== {{ c.SHIFT_WORKED }} && shift.worked !== {{c.SHIFT_UNWORKED}}) {
        return '';
    }

    if(shift.worked === {{c.SHIFT_UNWORKED}}){
        let icon = shift.comment ? 'fa-comment' : 'fa-comment-o';
        // Allow commends on unworked shifts
       return $id('rating_' + shift.id, '<span class="rating"></span>')
        .data('shift', shift)
        .empty()
        .append('<i class="fw-bold fs-3 fa '+icon+' comment-btn" title="Add comment"></i>');
    }

    //Else shift.worked is the SHIFT_WORKED constant.
    return $id('rating_' + shift.id, '<span class="rating"></span>')
        .data('shift', shift)
        .empty()
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

