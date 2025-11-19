// Immediately Invoked Function Expression (IIFE) to isolate scope
// All functions in this file are *stateless* and *can* be initialized multiple times by includes.

(function(global) {
    const RATINGS = {
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

    const UNRATED = {{c.UNRATED}};

    let findOrCreateElement = function(id, el) {
        let $el = $('#' + id);
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
            //show the comment row
            let $shiftRatingRow = $(`#shift_comment_${shift.id}`);
            $shiftRatingRow.data("shift", shift);
            $shiftRatingRow.data("rating", shift.rating);
            $shiftRatingRow.find('input[type="text"]').val(shift.comment || '');
            $shiftRatingRow.show();
            //See commentSubmit for next step on submit of comment
        });

        $(document.body).on('click', '.rating img', function (event) {
            console.log("HMD rating image clicked!");
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
                        let r = $(this).data('rating');
                        $(this)
                            .attr('title', '')
                            .attr('src', RATINGS[r][false]);
                    });

                    shift.rating = UNRATED;
                    shift.comment = '';
                }, 'json');
            } else {
                //Show the comment row
                let $shiftRatingRow = $(`#shift_comment_${shift.id}`);
                $shiftRatingRow.data("shift", shift);
                $shiftRatingRow.data("rating", rating);
                $shiftRatingRow.find('input[type="text"]').val(shift.comment || '');
                $shiftRatingRow.find('.required-indicator').show();
                $shiftRatingRow.show();
                //See commentSubmit for next step on comment submit;
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

    let commentSubmit = function (shiftId) {
        //Get the comment row
        let $commentRow = $(`#shift_comment_${shiftId}`);
        let shift = $commentRow.data("shift"); //Points to same object as container!
        let rating = $commentRow.data("rating");
        let $commentInput = $commentRow.find('input[name="shift_comment"]');
        let $commentInvalid = $commentRow.find('.invalid-feedback');
        let comment = $commentInput.val().trim();

        if (!comment && rating !== UNRATED) {
            // show Bootstrap invalid feedback
             $commentInput.addClass("is-invalid");
             $commentInvalid.css('display', 'flex');
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
                let r = $(this).data('rating');
                $(this)
                    .attr('title', comment)
                    .attr('src', RATINGS[r][r == rating]);
            });
            updateCommentIcon($container, shift.comment);
            hideShiftComment($commentRow);

         }, 'json');
    };

    const renderShiftRating = function(shift) {
        shift = typeof shift === 'string' ? SHIFTS[shift] : shift;

        //Shift is not marked worked or unworked.
        if (shift.worked !== {{ c.SHIFT_WORKED }} && shift.worked !== {{c.SHIFT_UNWORKED}}) {
            return '';
        }

        if(shift.worked === {{c.SHIFT_UNWORKED}}){
            let icon = shift.comment ? 'fa-comment' : 'fa-comment-o';
            // Allow commends on unworked shifts
           return findOrCreateElement('rating_' + shift.id, '<span class="rating"></span>')
            .data('shift', shift)
            .empty()
            .append('<i class="fw-bold fs-3 fa '+icon+' comment-btn" title="Add comment"></i>');
        }

        //Else shift.worked is the SHIFT_WORKED constant.
        return findOrCreateElement('rating_' + shift.id, '<span class="rating"></span>')
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

    const findShiftComment = function(shiftId){
        return $(`#shift_comment_${shiftId}`);
    }

    const hideShiftComment = function (commentRow){
        let commentInput = commentRow.find('input[name="shift_comment"]');
        //Hide the row and reset the state
        commentRow.hide();

        // reset validation state
        commentRow.find('.invalid-feedback').hide();
        commentRow.find(".required-indicator").hide();
        commentInput.removeClass("is-invalid");

        // clear stored data
        commentRow.data("shift", undefined);
        commentRow.data("rating", undefined);
    }

    const renderShiftStatus = function(shift, onUpdateShiftStatus) {
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

                hideShiftComment(findShiftComment(shift.id));
            }));
    };

    const updateShiftStatus = function(shift, status, onUpdateShiftStatus) {
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
    // ===== Expose only public API =====
    global.RatingModule = {
        findOrCreateElement,
        setupShiftRatingClickHandler,
        renderShiftRating,
        renderShiftStatus,
        commentSubmit
    };

})(window); // pass the global object
