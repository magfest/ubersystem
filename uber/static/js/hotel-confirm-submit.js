// Shared "are you sure?" gate for the hotel lottery section, attendee-facing
// and admin alike.
//
// Any form carrying `data-confirm-message` is intercepted on submit and only
// actually submitted once the user confirms in a bootbox dialog. This
// replaces the per-page `bootbox.confirm({...})` and inline
// `onsubmit="return confirm(...)"` handlers that every page in the section
// used to hand-roll.
//
// Attributes (only the message is required):
//   data-confirm-message  HTML body of the dialog
//   data-confirm-title    dialog title
//   data-confirm-label    confirm-button label   (default "Yes")
//   data-confirm-class    confirm-button class   (default "btn-danger")
//
// A `{name}` placeholder in the title, message, or label is replaced with the
// value of the form's `[name=member_name]` input, so per-row forms rendered in
// a loop can share one message string.
//
// Handlers are delegated off `document`, so forms added after page load work
// too, and including this file more than once is harmless.
$(function () {
    var fill = function (text, name) {
        return (text === undefined || text === null ? '' : String(text))
            .replace(/\{name\}/g, name);
    };

    $(document).on('submit', 'form[data-confirm-message]', function (event) {
        var form = this;
        var $form = $(form);
        event.preventDefault();

        var name = $form.find('[name=member_name]').first().val() || '';

        bootbox.confirm({
            backdrop: true,
            title: fill($form.data('confirm-title'), name),
            message: fill($form.data('confirm-message'), name),
            buttons: {
                confirm: {
                    label: fill($form.data('confirm-label'), name) || 'Yes',
                    className: $form.data('confirm-class') || 'btn-danger'
                },
                cancel: {
                    label: 'Nevermind',
                    className: 'btn-outline-secondary'
                }
            },
            callback: function (result) {
                if (result) {
                    // Native submit() does not re-fire jQuery submit handlers,
                    // so this can't loop back into the dialog.
                    form.submit();
                }
            }
        });
    });
});
