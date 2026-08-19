// Modals for the exports page's activity timeline.
//
// Load via:  {{ "js/hotel-change-log.js"|serve_static_content }}
//
// Two viewers share this file because they answer the same question
// from different angles:
//
//   .hotel-changes-open  what changed - either a time window between
//                        two events (data-hotel-id + data-start/end) or
//                        the changes one import caused (data-import-id)
//   .hotel-file-open     the retained file itself, as a table
//                        (data-kind + data-file-id), paginated because
//                        a real booking export runs to thousands of rows
(function () {
  var modalEl = document.getElementById('hotel-changes-modal');
  if (!modalEl) return;

  var body = modalEl.querySelector('.hotel-changes-body');
  var windowLabel = modalEl.querySelector('.hotel-changes-window');
  var modal = null;

  function cell(row, text, className) {
    var td = row.insertCell();
    td.textContent = text;
    if (className) td.className = className;
    return td;
  }

  function render(changes) {
    body.replaceChildren();
    if (!changes.length) {
      var empty = document.createElement('p');
      empty.className = 'text-muted mb-0';
      empty.textContent = 'No room changes recorded here.';
      body.appendChild(empty);
      return;
    }

    var table = document.createElement('table');
    table.className = 'table table-sm align-middle';
    var head = table.createTHead().insertRow();
    ['When', 'Room', 'Guest', 'Action', 'What changed', 'Who']
        .forEach(function (label) {
          var th = document.createElement('th');
          th.textContent = label;
          head.appendChild(th);
        });

    var tbody = table.createTBody();
    changes.forEach(function (change) {
      var row = tbody.insertRow();
      cell(row, (change.when || '').replace('T', ' ').slice(0, 16), 'small');
      cell(row, change.number || '-');
      cell(row, change.guest || '-');
      cell(row, change.action || '');

      var fields = row.insertCell();
      fields.className = 'small';
      if (!change.fields.length) {
        fields.textContent = '-';
      } else {
        change.fields.forEach(function (f) {
          var line = document.createElement('div');
          var name = document.createElement('strong');
          name.textContent = f.field + ': ';
          line.appendChild(name);
          line.appendChild(document.createTextNode(f.old + ' → ' + f.new));
          fields.appendChild(line);
        });
      }
      cell(row, change.who || '', 'small');
    });
    body.appendChild(table);
  }

  function loading(host) {
    host.replaceChildren();
    var note = document.createElement('div');
    note.className = 'text-muted';
    note.textContent = 'Loading…';
    host.appendChild(note);
  }

  function failed(host, err) {
    host.replaceChildren();
    var alert = document.createElement('div');
    alert.className = 'alert alert-danger mb-0';
    alert.textContent = 'Could not load (' + err + ').';
    host.appendChild(alert);
  }

  document.addEventListener('click', function (event) {
    var btn = event.target.closest('.hotel-changes-open');
    if (!btn) return;

    var importId = btn.getAttribute('data-import-id');
    var url;
    if (importId) {
      windowLabel.textContent = 'caused by this import';
      url = 'hotel_import_changes?' +
          new URLSearchParams({id: importId}).toString();
    } else {
      var start = btn.getAttribute('data-start') || '';
      var end = btn.getAttribute('data-end') || '';
      windowLabel.textContent =
          (start.slice(0, 16).replace('T', ' ') || 'start') + ' → ' +
          (end.slice(0, 16).replace('T', ' ') || 'now');
      url = 'hotel_change_details?' + new URLSearchParams({
        hotel_id: btn.getAttribute('data-hotel-id'),
        start: start,
        end: end,
      }).toString();
    }

    loading(body);
    modal = modal || new bootstrap.Modal(modalEl);
    modal.show();

    fetch(url, {credentials: 'same-origin'})
      .then(function (resp) { return resp.json(); })
      .then(function (json) { render(json.changes || []); })
      .catch(function (err) { failed(body, err); });
  });
})();

(function () {
  var modalEl = document.getElementById('hotel-file-modal');
  if (!modalEl) return;

  var body = modalEl.querySelector('.hotel-file-body');
  var nameLabel = modalEl.querySelector('.hotel-file-name');
  var countLabel = modalEl.querySelector('.hotel-file-count');
  var pager = modalEl.querySelector('.hotel-file-pager');
  var modal = null;
  var current = null;   // {kind, id}

  function renderTable(json) {
    body.replaceChildren();
    if (json.error) {
      var alert = document.createElement('div');
      alert.className = 'alert alert-warning mb-0';
      alert.textContent = json.error;
      body.appendChild(alert);
      return;
    }

    var table = document.createElement('table');
    table.className = 'table table-sm table-bordered align-middle';
    table.style.whiteSpace = 'nowrap';
    var head = table.createTHead().insertRow();
    json.columns.forEach(function (col) {
      var th = document.createElement('th');
      th.textContent = col;
      head.appendChild(th);
    });
    var tbody = table.createTBody();
    json.rows.forEach(function (row) {
      var tr = tbody.insertRow();
      row.forEach(function (value) {
        var td = tr.insertCell();
        td.textContent = value;
        td.className = 'small';
      });
    });
    body.appendChild(table);
  }

  function renderPager(json) {
    pager.replaceChildren();
    if (!json.pages || json.pages < 2) return;
    [['«', json.page - 1], ['»', json.page + 1]].forEach(function (pair) {
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'btn btn-outline-secondary';
      btn.textContent = pair[0];
      btn.disabled = pair[1] < 1 || pair[1] > json.pages;
      btn.addEventListener('click', function () { load(pair[1]); });
      pager.appendChild(btn);
    });
    var label = document.createElement('span');
    label.className = 'btn btn-outline-secondary disabled';
    label.textContent = json.page + ' / ' + json.pages;
    pager.insertBefore(label, pager.lastChild);
  }

  function load(page) {
    body.replaceChildren();
    var note = document.createElement('div');
    note.className = 'text-muted';
    note.textContent = 'Loading…';
    body.appendChild(note);

    fetch('hotel_file_rows?' + new URLSearchParams({
      kind: current.kind, id: current.id, page: page,
    }).toString(), {credentials: 'same-origin'})
      .then(function (resp) { return resp.json(); })
      .then(function (json) {
        countLabel.textContent = json.total
            ? json.total + ' row(s), ' + json.columns.length + ' column(s)'
            : '';
        renderTable(json);
        renderPager(json);
      })
      .catch(function (err) {
        body.replaceChildren();
        var alert = document.createElement('div');
        alert.className = 'alert alert-danger mb-0';
        alert.textContent = 'Could not load the file (' + err + ').';
        body.appendChild(alert);
      });
  }

  document.addEventListener('click', function (event) {
    var btn = event.target.closest('.hotel-file-open');
    if (!btn) return;
    current = {
      kind: btn.getAttribute('data-kind'),
      id: btn.getAttribute('data-file-id'),
    };
    nameLabel.textContent = btn.getAttribute('data-filename') || 'File';
    countLabel.textContent = '';
    pager.replaceChildren();
    modal = modal || new bootstrap.Modal(modalEl);
    modal.show();
    load(1);
  });
})();
