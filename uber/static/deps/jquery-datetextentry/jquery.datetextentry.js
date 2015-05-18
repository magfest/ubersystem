/*
 * jQuery datetextentry v2.0.9
 * Copyright (c) 2010-2014 Grant McLean (grant@mclean.net.nz)
 *
 * Source repo: https://github.com/grantm/jquery-datetextentry
 *
 * Dual licensed under the MIT and GPL licenses:
 *   http://opensource.org/licenses/MIT
 *   http://opensource.org/licenses/GPL-3.0
 *
 */

(function($){

    "use strict";


    /* DATETEXTENTRY CLASS DEFINITION
     * ============================== */

    var days_in_month = [ 31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31 ];
    var key = { BACKSPACE : 8 };

    var DateTextEntry = function (element, options) {
        this.$element = $(element);
        this.options = $.extend({}, $.fn.datetextentry.defaults, options)
        this.add_century = this.options.add_century || this.add_century;
        this.parse_date = this.options.parse_date || this.parse_date;
        this.format_date = this.options.format_date || this.format_date;
        this.human_format_date = this.options.human_format_date || this.human_format_date;
        this.on_blur = this.options.on_blur;
        this.on_change = this.options.on_change;
        this.on_error = this.options.on_error;
        this.custom_validation = this.options.custom_validation;
        this.build_ui();
        this.set_date( this.$element.attr('value') );
        this.proxy_label_clicks();
    };

    function str_right(str, n) { return str.substr(str.length - n); }
    function pad2(n) { return str_right('00'   + (n || 0), 2); }
    function pad4(n) { return str_right('0000' + (n || 0), 4); }

    DateTextEntry.prototype = {

        constructor: DateTextEntry

        ,build_ui: function() {
            var dte = this;
            this.wrapper = $( this.$element.wrap('<span class="jq-dte" />').parent()[0] );
            this.inner   = $('<span class="jq-dte-inner" />');
            this.add_entry_fields();
            this.tooltip = $('<span class="jq-dte-tooltip" />').hide();
            this.errorbox = $('<span class="jq-dte-errorbox" />').hide();
            this.inner.on('paste', 'input', function(e) {
                var input = this;
                setTimeout(function() { dte.after_paste(input, e);}, 2);
            });
            this.wrapper.append( this.inner, this.tooltip, this.errorbox );
            this.set_field_widths();
            this.$element.hide();
        }

        ,add_entry_fields: function() {
            var dte = this;
            dte.fields = [];
            $.each(this.options.field_order.split(''), function(i, field) {
                switch(field) {
                    case 'D': dte.build_field('day',   i); break;
                    case 'M': dte.build_field('month', i); break;
                    case 'Y': dte.build_field('year',  i); break;
                    default :
                        throw "Unexpected field order '" + field + "' expected D, M or Y";
                };
            });
        }

        ,build_field: function(name, index) {
            var dte = this;
            var opt = this.options;
            var input = new DateTextInput({
                name      : name,
                dte       : dte,
                index     : index,
                hint_text : opt.show_hints ? opt['field_hint_text_' + name] : null,
                tip_text  : opt['field_tip_text_'  + name]
            });
            this.inner.append(input.$input);
            this['input_' + name] = input;

            if(index < 2) {
                this.inner.append( $('<span class="separator" />').text(opt.separator));
            }

            this.fields[index] = input;
            this[name] = input;
        }

        ,set_field_widths: function() {
            var opt = this.options;
            var available = this.$element.width() - 2;
            var total = opt.field_width_year + opt.field_width_sep + opt.field_width_month +
                        opt.field_width_sep + opt.field_width_day;
            this.input_day.set_width  ( Math.floor(opt.field_width_day   * available / total) );
            this.input_month.set_width( Math.floor(opt.field_width_month * available / total) );
            this.input_year.set_width ( Math.floor(opt.field_width_year  * available / total) );

        }

        ,set_date: function(new_date) {
            var dte = this;
            new_date = this.parse_date(new_date);
            delete this.day_value;
            delete this.month_value;
            delete this.year_value;
            this.input_day.set(  new_date ? new_date.day   : '');
            this.input_month.set(new_date ? new_date.month : '');
            this.input_year.set( new_date ? new_date.year  : '');
            this.clear_error();
            this.$element.val(new_date);
            if(new_date) {
                $.each(this.fields, function(i, input) {
                    dte.validate(input);
                });
            }
        }

        ,proxy_label_clicks: function() {
            var dte = this;
            var id = this.$element.attr('id');
            if(!id) { return; } 
            $('label[for=' + id + ']').click(function() {
                dte.focus();
            });
        }

        ,clear: function() {
            this.clear_error('');
            this.set_date('');
        }

        ,destroy: function() {
            this.$element.show();
            this.$element.css('display', '');
            this.wrapper.find('span').remove();
            this.$element.unwrap();
            this.$element.removeData('datetextentry');
            delete this.inner;
            delete this.wrapper;
            delete this.$element;
        }

        ,after_paste: function(target, event) {
            if(this.parse_date( $(target).val() ) ) {
                this.set_date( $(target).val() );
            }
        }

        ,parse_date: function(text) {
            return this.parse_iso_date(text);
        }

        ,parse_iso_date: function(text) {
            return text && text.match(/^(\d\d\d\d)-(\d\d)-(\d\d)/)
                ? { day: RegExp.$3, month: RegExp.$2, year: RegExp.$1 }
                : null;
        }

        ,get_date : function() {
            return (this.day_value  &&  this.month_value  &&  this.year_value)
                ?  { day: this.day_value, month: this.month_value, year: this.year_value }
                : null;
        }

        ,get_today : function() {
            var today = new Date();
            return {
                day:   pad2(today.getDate()),
                month: pad2(today.getMonth() + 1),
                year:  pad4(today.getFullYear())
            };
        }

        ,format_date : function(date) {
            return this.iso_format_date(date);
        }

        ,iso_format_date : function(date) {
            return [ pad4(date.year), pad2(date.month), pad2(date.day) ].join('-');
        }

        ,human_format_date: function(date) {
            return [ pad2(date.day), pad2(date.month), pad4(date.year) ].join('/');
        }

        ,add_century: function (year) {
            return 2000 + year;
        }

        ,focus_in: function() {
            this.wrapper.addClass('focus');
        }

        ,focus_out: function() {
            if(this.on_blur) {
                var self = this;
                setTimeout(function() { self.widget_focus_lost(); }, 2);
            }
            this.wrapper.removeClass('focus');
        }

        ,widget_focus_lost: function() {
            if(this.on_blur && !this.wrapper.is('.focus')) {
                this.on_blur();
            }
        }

        ,show_input_tip: function(input) {
            var opt = this.options;
            if(!opt.show_tooltips) { return; }
            var x_offset = (input.left() + opt.tooltip_x) + 'px';
            var y_offset = (this.wrapper.height() + opt.tooltip_y) + 'px';
            this.tooltip.css({position: 'absolute', top: y_offset, left: x_offset})
                .text(input.tip_text)
                .show();
        }

        ,hide_input_tip: function() {
            this.tooltip.hide();
        }

        ,set_error: function(error_text) {
            this.error_text = error_text;
            this.show_error();
        }

        ,clear_error: function() {
            delete this.error_text;
            this.show_error();
        }

        ,set_readonly: function(mode) {
            if(mode === undefined) {
                mode = true;
            }
            this.input_day.set_readonly(mode);
            this.input_month.set_readonly(mode);
            this.input_year.set_readonly(mode);
            if(mode) {
                this.wrapper.addClass('readonly');
            }
            else {
                this.wrapper.removeClass('readonly');
            }
        }

        ,show_error: function() {
            var opt = this.options;
            var error_text = this.widget_error_text();
            if(this.on_error) {
                this.on_error(error_text);
            }
            if(!opt.show_errors) {
                return;
            }
            if(error_text === '') {
                this.errorbox.hide();
                this.errorbox.text('');
            }
            else {
                var x_offset = (this.inner.outerWidth() + opt.errorbox_x) + 'px';
                var y_offset = opt.errorbox_y + 'px';
                this.errorbox.css({position: 'absolute', top: y_offset, left: x_offset});
                this.errorbox.text(error_text);
                this.errorbox.show();
            }
        }

        ,widget_error_text: function() {
            var error_text = '';
            $.each(this.fields, function(i, input) {
                if(input.error_text) {
                    if(input.has_focus  ||  error_text === '') {
                        error_text = input.error_text
                    }
                }
            });
            if(error_text === ''  &&  this.error_text) {
                error_text = this.error_text;
            }
            return error_text;
        }

        ,focus: function() {
            this.fields[0].set_focus(true);
        }

        ,focus_field_before: function(input) {
            var index = input.index;
            if(index < 1) { return };
            var next = this.fields[index - 1];
            var val = next.get();
            next.set_focus(false);
        }

        ,focus_field_after: function(input) {
            var index = input.index;
            if(index > 1) { return };
            this.fields[index + 1].set_focus(true);
        }

        ,validate: function( current_input ) {
            this.$element.val('');
            if(current_input) {
                try {
                    this['validate_' + current_input.name]();
                    current_input.clear_error();
                }
                catch(e) {
                    current_input.set_error(e);
                    return false;
                }
            }
            if(this.day_value && this.month_value && this.year_value) {
                this.clear_error();
                try {
                    this.validate_days_in_month();
                    if(this.year_value.length === 4) {
                        this.validate_complete_date();
                        var date_obj = this.get_date();
                        var date_str = this.format_date( date_obj );
                        this.$element.val( date_str );
                        if(this.on_change) {
                            this.on_change( date_str );
                        }
                    }
                }
                catch(e) {
                    this.set_error(e);
                }
            }
            return true;
        }

        ,validate_day: function() {
            var opt = this.options;
            var input = this.input_day;
            this.day_value = undefined;
            var text = input.get();
            if(text === ''  ||  (text === '0'  &&  input.has_focus)) {
                return;
            }
            if(text.match(/\D/)) {
                throw(opt.E_DAY_NAN);
            }
            var num = parseInt(text, 10);
            if(num < 1)  { throw(opt.E_DAY_TOO_SMALL); }
            if(num > 31) { throw(opt.E_DAY_TOO_BIG);   }
            text = num < 10 ? '0' + num : '' + num;
            if(!input.has_focus) { input.set(text); }
            this.day_value = text;
        }

        ,validate_month: function() {
            var opt = this.options;
            var input = this.input_month;
            this.month_value = undefined;
            var text = input.get();
            if(text === ''  ||  (text === '0'  &&  input.has_focus)) {
                return;
            }
            if(text.match(/\D/)) {
                throw(opt.E_MONTH_NAN);
            }
            var num = parseInt(text, 10);
            if(num < 1)  { throw(opt.E_MONTH_TOO_SMALL); }
            if(num > 12) { throw(opt.E_MONTH_TOO_BIG);   }
            text = num < 10 ? '0' + num : '' + num;
            if(!input.has_focus) { input.set(text); }
            this.month_value = text;
        }

        ,validate_year: function() {
            var opt = this.options;
            var input = this.input_year;
            this.year_value = undefined;
            var text = input.get();
            if(text === ''  ||  (text === '0'  &&  input.has_focus)) {
                return;
            }
            if(text.match(/\D/)) {
                throw(opt.E_YEAR_NAN);
            }
            if(input.has_focus) {
                if(text.length > 4) {
                    throw(opt.E_YEAR_LENGTH);
                }
            }
            else {
                if(text.length == 2) {
                    text = '' + this.add_century(parseInt(text, 10));
                    this.input_year.set(text);
                }
                if(text.length != 4) {
                    throw(opt.E_YEAR_LENGTH);
                }
            }
            if(text.length == 4) {
                var num = parseInt(text, 10);
                if(opt.min_year  &&  num < opt.min_year) {
                    throw(opt.E_YEAR_TOO_SMALL.replace(/%y/, opt.min_year));
                }
                if(opt.max_year  &&  num > opt.max_year) {
                    throw(opt.E_YEAR_TOO_BIG.replace(/%y/, opt.max_year));
                }
            }
            this.year_value = text;
        }

        ,validate_days_in_month: function() {
            var opt = this.options;
            var day   = parseInt(this.day_value,   10);
            var month = parseInt(this.month_value, 10);
            var year  = parseInt(this.year_value,  10);
            if(day < 1  ||  month < 1) { return; }
            var max = days_in_month[month - 1];
            var msg = opt.E_BAD_DAY_FOR_MONTH;
            if(month == 2  &&  ('' + year).length == 4) {
                max = year % 4 ? 28 : year % 100 ? 29 : year % 400 ? 28 : 29;
                msg = msg.replace(/%y/, year);
            }
            else {
                msg = msg.replace(/ *%y/, '');
            }
            if(day > max) {
                throw(msg.replace(/%d/, max).replace(/%m/, opt.month_name[month - 1]));
            }
        }

        ,validate_complete_date: function() {
            var opt = this.options;
            var date_obj = this.get_date();
            var date_iso = this.iso_format_date( date_obj );

            var max_date = opt.max_date;
            if(typeof max_date === 'function') {
                max_date = max_date.call(this);
            }
            if(typeof max_date === 'string') {
                max_date = this.parse_date(max_date);
            }
            if(max_date) {
                if( date_iso > this.iso_format_date( max_date ) ) {
                    var msg = opt.max_date_message ? opt.max_date_message : opt.E_MAX_DATE;
                    if(msg) {
                        throw(msg.replace(/%DATE/, this.human_format_date( max_date )));
                    }
                }
            }

            var min_date = opt.min_date;
            if(typeof min_date === 'function') {
                min_date = min_date.call(this);
            }
            if(typeof min_date === 'string') {
                min_date = this.parse_date(min_date);
            }
            if(min_date) {
                if( date_iso < this.iso_format_date( min_date ) ) {
                    var msg = opt.min_date_message ? opt.min_date_message : opt.E_MIN_DATE;
                    if(msg) {
                        throw(msg.replace(/%DATE/, this.human_format_date( min_date )));
                    }
                }
            }

            if(this.custom_validation) {
                date_obj.date = new Date(
                    parseInt(date_obj.year, 10),
                    parseInt(date_obj.month, 10) - 1,
                    parseInt(date_obj.day, 10)
                );
                this.custom_validation(date_obj);
            }
        }

    };


    /* DATETEXTINPUT CLASS DEFINITION
     * ============================== */

    var DateTextInput = function (options) {
        var input = this;
        var dte = this.dte = options.dte
        var opt = dte.options;
        this.name = options.name;
        this.index = options.index;
        this.hint_text = options.hint_text;
        this.tip_text = options.tip_text;
        this.has_focus = false;
        this.empty = true;
        this.$input = $('<input type="text" value="" />')
            .addClass( 'jq-dte-' + this.name )
            .attr('aria-label', dte.options['field_tip_text_' + this.name])
            .focus( $.proxy(input, 'focus') )
            .blur(  $.proxy(input, 'blur' ) )
            .keydown( function(e) { setTimeout(function () { input.keydown(e); }, 2) } )
            .keyup( function(e) { setTimeout(function () { input.keyup(e); }, 2) } );
    };

    DateTextInput.prototype = {

        constructor: DateTextInput

        ,set: function(new_value) {
            this.$input.val(new_value).removeClass('hint');
            if(!this.has_focus) {
                this.show_hint();
            }
            this.empty = new_value === '';
            this.clear_error();
            return this;
        }

        ,get: function() {
            var val = this.$input.val();
            return val === this.hint_text ? '' : val;
        }

        ,left: function() {
            return this.$input.position().left;
        }

        ,set_width: function(new_width) {
            this.$input.width(new_width);
            return this;
        }

        ,show_hint: function() {
            if(this.get() === ''  &&  typeof(this.hint_text) === 'string') {
                this.$input.val( this.hint_text ).addClass('hint');
            }
            return this;
        }

        ,set_focus: function(select_all) {
            var $input = this.$input;
            $input.focus();
            if(select_all) {
                $input.select();
            }
            else {
                $input.val( $input.val() );
            }
            return this;
        }

        ,set_error: function(text) {
            this.error_text = text;
            this.$input.addClass('error');
            this.dte.show_error();
        }

        ,clear_error: function() {
            delete this.error_text;
            this.$input.removeClass('error');
        }

        ,set_readonly: function(mode) {
            this.$input.prop('readonly', mode);
        }

        ,focus: function(e) {
            this.key_is_down = false;
            if( this.$input.prop('readonly') ) {
                return;
            }
            this.has_focus = true;
            this.dte.focus_in();
            if( this.$input.hasClass('hint') ) {
                this.$input.val('').removeClass('hint');
            }
            this.dte.show_input_tip(this);
            this.dte.show_error();
        }

        ,blur: function(e) {
            this.has_focus = false;
            this.dte.focus_out();
            this.dte.hide_input_tip();
            this.show_hint();
            this.dte.validate(this);
        }

        ,keydown: function(e) {
            // Ignore keyup events that arrive after focus moved to next field
            this.key_is_down = true;
        }

        ,keyup: function(e) {
            if(!this.key_is_down) {
                return;
            }
            // Handle Backspace - shifting focus to previous field if required
            var keycode = e.which;
            if(keycode === key.BACKSPACE  &&  this.empty) {
                return this.dte.focus_field_before(this);
            }
            var text = this.get();
            this.empty = text === '';

            // Trap and discard separator characters - advancing focus if required
            if(text.match(/[\/\\. -]/)) {
                text = text.replace(/[\/\\. -]/, '');
                this.set(text);
                if(!this.empty  &&  this.index < 2) {
                    this.dte.focus_field_after(this);
                }
            }

            // Advance focus if this field is both valid and full
            if( this.dte.validate(this) ) {
                var want = this.name === 'year' ? 4 : 2;
                if(this.is_digit_key(e) && text.length == want) {
                        this.dte.focus_field_after(this);
                }
            }
        }

        ,is_digit_key: function(e) {
            var keycode = e.which;
            return keycode >= 48 && keycode <= 57 || keycode >= 96 && keycode <= 105;
        }


    };


    /* DATETEXTENTRY PLUGIN DEFINITION
     * =============================== */

    $.fn.datetextentry = function (option) {
        var args = Array.prototype.slice.call(arguments, 1);
        return this.each(function () {
            var $this = $(this);
            var data = $this.data('datetextentry');
            if(!data) {
                data = new DateTextEntry(this, option);
                $this.data('datetextentry', data);
            }
            if(typeof option === 'string') {  // option is a method - call it
                if(typeof data[option] !== 'function') {
                    throw "jquery.datetextentry has no '" + option + "' method";
                }
                data[option].apply(data, args);
            }
        })
    };

    $.fn.datetextentry.defaults = {
        field_order           : 'DMY',
        separator             : '/',
        show_tooltips         : true,
        show_hints            : true,
        show_errors           : true,
        field_width_day       : 40,
        field_width_month     : 40,
        field_width_year      : 60,
        field_width_sep       : 4,
        errorbox_x            : 8,
        errorbox_y            : 3,
        tooltip_x             : 0,
        tooltip_y             : 6,
        field_tip_text_day    : 'Day',
        field_tip_text_month  : 'Month',
        field_tip_text_year   : 'Year',
        field_hint_text_day   : 'DD',
        field_hint_text_month : 'MM',
        field_hint_text_year  : 'YYYY',
        E_DAY_NAN             : 'Day must be a number',
        E_DAY_TOO_BIG         : 'Day must be 1-31',
        E_DAY_TOO_SMALL       : 'Day must be 1-31',
        E_BAD_DAY_FOR_MONTH   : 'Only %d days in %m %y',
        E_MONTH_NAN           : 'Month must be a number',
        E_MONTH_TOO_BIG       : 'Month must be 1-12',
        E_MONTH_TOO_SMALL     : 'Month must be 1-12',
        E_YEAR_NAN            : 'Year must be a number',
        E_YEAR_LENGTH         : 'Year must be 4 digits',
        E_YEAR_TOO_SMALL      : 'Year must not be before %y',
        E_YEAR_TOO_BIG        : 'Year must not be after %y',
        E_MIN_DATE            : 'Date must not be earlier than %DATE',
        E_MAX_DATE            : 'Date must not be later than %DATE',
        month_name            : [
                                  'January', 'February', 'March', 'April',
                                  'May', 'June', 'July', 'August', 'September',
                                  'October', 'November', 'December'
                              ]
    };

})(window.jQuery);
