// Row-by-row review of an uploaded hotel room list: apply one imported value
// to a booking, or point an ambiguous row at the right one.

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

  root.addEventListener('click', function (e) {
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
