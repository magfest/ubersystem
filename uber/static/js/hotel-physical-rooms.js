// Page behaviors for hotel_lottery_admin/physical_rooms.html.
//
// 1. Hotel memory: the server defaults to the first hotel, but the page
//    remembers the last hotel the admin explicitly viewed (per browser,
//    via localStorage) and returns there.
//
// 2. Instant assignment: picking a room in an unroomed booking's
//    dropdown saves immediately (board_assign_json) and removes that
//    room from every other dropdown. The saved row stays in place -
//    just marked done - so rapid assignment doesn't reflow the page;
//    a refresh re-sorts everything.
(function () {
  var KEY = 'hotel_lottery.physical_rooms.hotel_id';
  var select = document.querySelector(
      'form[action="physical_rooms"] select[name="hotel_id"]');
  if (select) {
    var explicit = new URLSearchParams(window.location.search)
        .get('hotel_id');
    if (explicit) {
      try { localStorage.setItem(KEY, explicit); } catch (e) {}
    } else {
      var stored;
      try { stored = localStorage.getItem(KEY); } catch (e) {}
      if (stored && stored !== select.value &&
          select.querySelector('option[value="' + stored + '"]')) {
        window.location.replace('physical_rooms?hotel_id=' +
                                encodeURIComponent(stored));
      }
    }
  }
})();

// 3. Lazy floors: each accordion body fetches its own rows the first
//    time it opens, so a page with thousands of catalogued rooms ships
//    only the floor headers.
(function () {
  document.querySelectorAll('.floor-rows').forEach(function (host) {
    var pane = host.closest('.accordion-collapse');
    if (!pane) return;

    function load() {
      if (host.dataset.loaded) return;
      host.dataset.loaded = 'yes';
      fetch(host.getAttribute('data-rows-url'), {credentials: 'same-origin'})
        .then(function (resp) {
          if (!resp.ok) throw new Error('HTTP ' + resp.status);
          return resp.text();
        })
        .then(function (html) { host.innerHTML = html; })
        .catch(function (err) {
          host.dataset.loaded = '';
          host.innerHTML = '';
          var alert = document.createElement('div');
          alert.className = 'alert alert-danger mb-0';
          alert.textContent = 'Could not load these rooms (' + err + ').';
          host.appendChild(alert);
        });
    }

    pane.addEventListener('show.bs.collapse', load);
    if (pane.classList.contains('show')) load();
  });
})();

(function () {
  var forms = document.querySelectorAll('form[action="board_assign"]');
  if (!forms.length) return;

  function showError(form, message) {
    var note = form.querySelector('.quick-assign-error');
    if (!note) {
      note = document.createElement('div');
      note.className = 'quick-assign-error text-danger small w-100';
      form.appendChild(note);
    }
    note.textContent = message;
  }

  function markSaved(form, roomNumbers) {
    form.querySelectorAll('select, button').forEach(function (el) {
      el.disabled = true;
    });
    var badge = document.createElement('span');
    badge.className = 'badge bg-success align-self-center';
    badge.textContent = 'Saved: ' + roomNumbers.join(', ');
    form.appendChild(badge);
    form.closest('tr').classList.add('table-success');
  }

  // A suite takes its connector rooms with it, so drop every room the
  // save consumed from the other dropdowns.
  function removeFromOtherLists(currentSelect, roomIds) {
    forms.forEach(function (form) {
      var sel = form.querySelector('select[name="physical_room_id"]');
      if (!sel || sel === currentSelect) return;
      roomIds.forEach(function (roomId) {
        var option = sel.querySelector('option[value="' + roomId + '"]');
        if (option) option.remove();
      });
      if (sel.roomGroups) {
        sel.roomGroups = sel.roomGroups.filter(function (opt) {
          return roomIds.indexOf(opt.id) === -1;
        });
      }
    });
  }

  // Each dropdown fetches its own room list the first time it's used,
  // so the page doesn't ship a full catalog of <option>s per booking.
  function loadOptions(sel) {
    if (sel.dataset.loading) return sel.dataset.loading === 'done'
        ? Promise.resolve() : sel._optionsPromise;
    sel.dataset.loading = 'yes';
    sel._optionsPromise = fetch(sel.getAttribute('data-options-url'),
                                {credentials: 'same-origin'})
      .then(function (resp) { return resp.json(); })
      .then(function (json) {
        // Kept for the map picker, which highlights and assigns a
        // suite's connector rooms as one group.
        sel.roomGroups = json.options || [];
        sel.roomGroups.forEach(function (opt) {
          var option = document.createElement('option');
          option.value = opt.id;
          option.textContent = opt.label;
          sel.appendChild(option);
        });
        sel.dataset.loading = 'done';
      })
      .catch(function () { sel.dataset.loading = ''; });
    return sel._optionsPromise;
  }

  forms.forEach(function (form) {
    var sel = form.querySelector('select[name="physical_room_id"]');
    if (!sel) return;
    sel.addEventListener('focus', function () { loadOptions(sel); });
    // The map picker reads this select for which rooms are offered and
    // which ones a suite would take with it, so the options must be in
    // place BEFORE it opens: swallow the first click, load, then let
    // the click through.
    var mapBtn = form.querySelector('.room-map-open');
    if (mapBtn) {
      mapBtn.addEventListener('mouseenter', function () { loadOptions(sel); });
      mapBtn.addEventListener('click', function (event) {
        if (sel.dataset.loading === 'done') return;
        event.preventDefault();
        event.stopPropagation();
        mapBtn.disabled = true;
        loadOptions(sel).then(function () {
          mapBtn.disabled = false;
          mapBtn.click();
        });
      }, true);
    }
    // The submit button is redundant once selection saves instantly;
    // without JS the form still posts to board_assign normally.
    form.addEventListener('submit', function (e) { e.preventDefault(); });
    var submit = form.querySelector('button[type="submit"]');
    if (submit) submit.classList.add('d-none');

    sel.addEventListener('change', function () {
      if (!sel.value) return;
      // Build the payload BEFORE disabling the select: a disabled
      // control is omitted from FormData.
      var body = new FormData(form);
      sel.disabled = true;
      fetch('board_assign_json', {
        method: 'POST',
        credentials: 'same-origin',
        body: body,
      })
        .then(function (resp) { return resp.json(); })
        .then(function (json) {
          if (json.success) {
            markSaved(form, json.room_numbers || [json.room_number]);
            removeFromOtherLists(sel, json.room_ids || [json.room_id]);
          } else {
            sel.disabled = false;
            showError(form, json.message || 'Could not assign.');
          }
        })
        .catch(function (err) {
          sel.disabled = false;
          showError(form, 'Could not assign (' + err + ').');
        });
    });
  });
})();
