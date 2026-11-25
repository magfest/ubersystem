// Row-by-row review of an uploaded hotel room list: apply one imported value
// to a booking, or point a row at the right one.

(function () {
  var root = document.getElementById('import-review');
  if (!root) { return; }
  var fileId = root.dataset.fileId;

  function csrfToken() {
    var el = document.querySelector('input[name="csrf_token"]');
    return el ? el.value : '';
  }

  function post(url, data) {
    var body = new FormData();
    body.append('csrf_token', csrfToken());
    body.append('file_id', fileId);
    Object.keys(data).forEach(function (key) { body.append(key, data[key]); });
    return fetch(url, {method: 'POST', body: body, credentials: 'same-origin'})
      .then(function (r) { return r.json(); });
  }

  function flash(el, text, isError) {
    var note = document.createElement('span');
    note.className = 'small ms-2 ' + (isError ? 'text-danger' : 'text-success');
    note.textContent = text;
    el.parentNode.appendChild(note);
    if (!isError) {
      setTimeout(function () { note.remove(); }, 4000);
    }
  }

  function searchBookings(panel) {
    var query = panel.querySelector('.import-rematch-query').value.trim();
    var results = panel.querySelector('.import-rematch-results');
    if (!query) { return; }
    results.textContent = 'Searching...';
    fetch('search_import_bookings?file_id=' + encodeURIComponent(fileId) +
          '&q=' + encodeURIComponent(query), {credentials: 'same-origin'})
      .then(function (r) { return r.json(); })
      .then(function (payload) {
        results.innerHTML = '';
        if (payload.error || !payload.results.length) {
          results.textContent = payload.error || 'No bookings found at this hotel.';
          return;
        }
        payload.results.forEach(function (booking) {
          var line = document.createElement('div');
          line.className = 'd-flex gap-2 align-items-center mb-1';
          var button = document.createElement('button');
          button.type = 'button';
          button.className = 'btn btn-sm btn-outline-primary import-rematch-pick';
          button.dataset.assignmentId = booking.id;
          button.textContent = 'Match';
          var label = document.createElement('span');
          label.className = 'small';
          label.textContent = [booking.name, booking.email, booking.room,
            booking.confirmation ? 'conf. ' + booking.confirmation : '']
            .filter(Boolean).join(' - ');
          line.appendChild(button);
          line.appendChild(label);
          results.appendChild(line);
        });
      });
  }

  root.addEventListener('keydown', function (e) {
    if (e.key === 'Enter' && e.target.classList.contains('import-rematch-query')) {
      e.preventDefault();
      searchBookings(e.target.closest('.import-rematch-panel'));
    }
  });

  root.addEventListener('click', function (e) {
    var toggle = e.target.closest('.import-rematch-toggle');
    if (toggle) {
      var panel = toggle.parentNode.querySelector('.import-rematch-panel');
      panel.style.display = panel.style.display === 'none' ? '' : 'none';
      return;
    }

    var search = e.target.closest('.import-rematch-search');
    if (search) {
      searchBookings(search.closest('.import-rematch-panel'));
      return;
    }

    var rematch = e.target.closest('.import-rematch-pick');
    if (rematch) {
      rematch.disabled = true;
      post('resolve_import_row', {
        row_index: rematch.closest('.import-row').dataset.rowIndex,
        assignment_id: rematch.dataset.assignmentId,
      }).then(function (payload) {
        if (payload.error) {
          rematch.disabled = false;
          flash(rematch, payload.error, true);
          return;
        }
        window.location.reload();
      });
      return;
    }

    var sync = e.target.closest('.import-sync');
    if (sync) {
      var row = sync.closest('.import-row');
      var tr = sync.closest('tr');
      sync.disabled = true;
      post('sync_import_value', {
        row_index: row.dataset.rowIndex,
        field: sync.dataset.field,
        assignment_id: sync.dataset.assignmentId,
      }).then(function (payload) {
        if (payload.error) {
          sync.disabled = false;
          flash(sync, payload.error, true);
          return;
        }
        // Show the booking's new value in place rather than reloading, so a
        // long review keeps its scroll position.
        var cell = tr.querySelector('.current-value');
        if (cell) {
          cell.innerHTML = '';
          var code = document.createElement('code');
          code.textContent = payload.current;
          cell.appendChild(code);
        }
        sync.replaceWith(document.createTextNode('Applied'));
      });
      return;
    }

    var pick = e.target.closest('.import-disambiguate');
    if (pick) {
      var pickRow = pick.closest('.import-row');
      var select = pickRow.querySelector('.import-candidate');
      pick.disabled = true;
      post('resolve_import_row', {
        row_index: pickRow.dataset.rowIndex,
        assignment_id: select ? select.value : '',
      }).then(function (payload) {
        if (payload.error) {
          pick.disabled = false;
          flash(pick, payload.error, true);
          return;
        }
        // The row's whole shape changes once it is matched, so re-render it
        // from the server rather than patching it here.
        window.location.reload();
      });
    }
  });
})();
