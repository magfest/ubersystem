/*global $:false */
/*global moment:false */
"use strict";

// registration queue.  OLDEST STUFF is at front of queue, NEWEST STUFF is at back
var all_regs = [];

 // seconds
var base_delay = 60;
var ajax_update_frequency = base_delay - 10;

var num_regs_seen_so_far = 0;

function custom_reg_msg()
{
    return "#" + num_regs_seen_so_far + ": New Registration: A NEW CHALLENGER APPROACHES!"
}

function on_reg_activate(item) {
    num_regs_seen_so_far++;
    document.getElementById('sfx').play(); // lol.
    $("#registrations").append("<div>"+ custom_reg_msg() +"</div>");
}

// take new data we have from JSON, merge it in with our existing list.
// id_hash: a unique attendee_ID hash for this registration
// timestamp: when this attendee registered
function merge_new_data(id_hash, timestamp) {
    if (how_many_seconds_from_base_time_until(timestamp) < 0) {
        return; // event already occurred, no need to add to queue
    }

    for (var i = 0; i < all_regs.length; ++i) {
        if (all_regs[i].id_hash === id_hash) {
            return; // duplicate, so skip it.
        }
    }

    // ensure new event time always takes place in the future of any queued events.
    if (all_regs.length > 0) {
        console.assert(timestamp > all_regs[all_regs.length - 1].timestamp);
    }

    var new_item = {};
    new_item["id_hash"] = id_hash;
    new_item["timestamp"] = timestamp;

    add_item_to_queue(new_item);
}

// we've determined we really want to add this thing and it's not a duplicate.
function add_item_to_queue(new_item)
{
    all_regs.push(new_item);

    // if this was empty before, then nothing is queued to notify, and we need to set it up.
    if (all_regs.length == 1)
    {
        try_to_schedule_next_valid_event();
    }
}

function dequeue_next_item() {
    return all_regs.shift();
}

var reg_timer;

function get_base_time()
{
    return moment().subtract('seconds', base_delay);
}

function how_many_seconds_from_base_time_until(unix_timestamp)
{
     return moment.duration(moment.unix(unix_timestamp) - get_base_time()).asSeconds();
}

// schedule the next "valid event" in the queue.
// a "valid event" is one that occurs in the future from now (the queue could contain events that already occured)
function try_to_schedule_next_valid_event()
{
    if (all_regs.length === 0) {
        return; // nothing to schedule, we're done.
    }

    for (var i = 0; i < all_regs.length; ++i) {
        var item = all_regs[i];

        var seconds_til_event_happens = how_many_seconds_from_base_time_until(item.timestamp);

        if (seconds_til_event_happens < 0) {
            // this should be impossible as we don't allow items in the queue that are in the past,
            // but handle this case anyway.
            all_regs.shift();   // delete our current item from the queue
            continue;           // try and schedule another one
        }

        // found a valid event! schedule it to pop in the future
        schedule_next_event(seconds_til_event_happens);
        return;
    }
}

function schedule_next_event(num_seconds_from_now) {
    reg_timer.once(num_seconds_from_now*1000);
    console.log("scheduling next event for +" + num_seconds_from_now + "seconds");
}

function process_incoming_ajax_data(registrations)
{
    for (var i=0; i<registrations.length; ++i) {
        var attendee_timestamp = registrations[i][0];
        var attendee_id_hash = registrations[i][1];

        merge_new_data(attendee_id_hash, attendee_timestamp);
    }
}

// FOR TESTING ONLY. make the base delay match our data.
function doctor_base_time()
{
    var oldest_timestamp = 1400811447;

    var target_base_time = moment.unix(oldest_timestamp).subtract('seconds', 5);
    var now = moment();
    base_delay = Math.round(moment.duration(now - target_base_time).asSeconds());

    console.log("DOCTORED BASE DELAY: #sec=+" + base_delay + ")");
    console.log("how_many_seconds_from_base_time_until("+oldest_timestamp+") is "+how_many_seconds_from_base_time_until(oldest_timestamp));
}

function do_ajax_request() {
    var ajax_data_url = "recent_regs_json";
     $.post(ajax_data_url,[], function(json_data, status) {
            process_incoming_ajax_data(json_data);
     });
}

$( document ).ready(function() {

    // doctor_base_time(); // DONT ENABLE UNLESS YOU ARE TESTING

    var ajax_timer = $.timer(function() {
       do_ajax_request();
    });

    // this one doesn't auto-start.
    reg_timer = $.timer(function() {
        reg_timer.stop();
        var next_item = dequeue_next_item();
        on_reg_activate(next_item);
        next_item = null;

        try_to_schedule_next_valid_event();
    });

    ajax_timer.set({ time: ajax_update_frequency*1000, autostart: true });

    do_ajax_request(); // kick the entire thing off
 });
