// Upload format editor: load a sample file's columns, map them to our fields,
// and see what the mapping produces before saving anything.

(function () {
  var form = document.getElementById('template-form');
  if (!form) { return; }

  var targetFields = JSON.parse(
    document.getElementById('target-fields-data').textContent || '[]');
  var kindByKey = {};
  targetFields.forEach(function (f) { kindByKey[f.key] = f.kind; });

  var columnMap = document.getElementById('column-map');
  var sampleInput = document.getElementById('sample-file');
  var output = document.getElementById('preview-output');

  function csrfToken() {
    var el = form.querySelector('input[name="csrf_token"]');
    return el ? el.value : '';
  }

  function escapeHtml(text) {
    var div = document.createElement('div');
    div.textContent = text === null || text === undefined ? '' : text;
    return div.innerHTML;
  }

  function optionsHtml(selected) {
    return targetFields.map(function (f) {
      return '<option value="' + f.key + '"' +
        (f.key === selected ? ' selected' : '') + '>' + escapeHtml(f.label) + '</option>';
    }).join('');
  }

  // Build a row per column the sample file actually has, keeping whatever was
  // already chosen for a column of that name.
  function renderColumns(headers) {
    var existing = {};
    columnMap.querySelectorAll('.column-row').forEach(function (row) {
      var select = row.querySelector('.column-target');
      existing[row.dataset.source] = select ? select.value : '';
    });

    columnMap.innerHTML = headers.map(function (header) {
      return [
        '<div class="row g-2 align-items-end mb-2 column-row" data-source="' + escapeHtml(header) + '">',
        '  <div class="col-md-5">',
        '    <div class="form-control form-control-sm bg-light">' + escapeHtml(header) + '</div>',
        '    <input type="hidden" name="column__' + escapeHtml(header) + '" class="column-target-input" />',
        '  </div>',
        '  <div class="col-md-5">',
        '    <select class="form-select form-select-sm column-target">' +
             optionsHtml(existing[header] || 'match.ignore') + '</select>',
        '  </div>',
        '  <div class="col-md-2 date-format" style="display:none;">',
        '    <input type="text" class="form-control form-control-sm" placeholder="%m/%d/%Y" />',
        '  </div>',
        '</div>'
      ].join('');
    }).join('');
    syncHiddenInputs();
  }

  // The selects drive hidden inputs so the form posts column__<name> pairs.
  function syncHiddenInputs() {
    columnMap.querySelectorAll('.column-row').forEach(function (row) {
      var select = row.querySelector('.column-target');
      var hidden = row.querySelector('.column-target-input');
      var dateBox = row.querySelector('.date-format');
      var dateInput = dateBox ? dateBox.querySelector('input') : null;
      if (!select || !hidden) { return; }
      hidden.value = select.value;
      var isDate = kindByKey[select.value] === 'date';
      if (dateBox) { dateBox.style.display = isDate ? '' : 'none'; }
      if (dateInput) {
        dateInput.name = isDate ? 'format__' + select.value : '';
      }
    });
  }

  columnMap.addEventListener('change', function (e) {
    if (e.target.classList.contains('column-target')) { syncHiddenInputs(); }
  });
  syncHiddenInputs();

  function currentMaps() {
    var columns = {};
    var formats = {};
    columnMap.querySelectorAll('.column-row').forEach(function (row) {
      var select = row.querySelector('.column-target');
      if (!select || select.value === 'match.ignore') { return; }
      columns[row.dataset.source] = select.value;
      var dateInput = row.querySelector('.date-format input');
      if (dateInput && dateInput.value) { formats[select.value] = dateInput.value; }
    });

    var enums = {};
    form.querySelectorAll('[name^="enum__"]').forEach(function (input) {
      if (!input.value) { return; }
      var rest = input.name.slice('enum__'.length);
      var split = rest.indexOf('__');
      if (split < 0) { return; }
      var target = rest.slice(0, split);
      var sourceValue = rest.slice(split + 2);
      enums[target] = enums[target] || {};
      enums[target][sourceValue] = input.value;
    });

    return {
      sheet_name: document.getElementById('sheet_name').value,
      header_row: parseInt(document.getElementById('header_row').value || '1', 10),
      column_map: columns,
      format_map: formats,
      enum_map: enums,
    };
  }

  document.getElementById('run-preview').addEventListener('click', function () {
    if (!sampleInput.files.length) {
      output.innerHTML = '<div class="alert alert-warning mb-0">Choose a sample file first.</div>';
      return;
    }
    var body = new FormData();
    body.append('csrf_token', csrfToken());
    body.append('maps', JSON.stringify(currentMaps()));
    body.append('sample_file', sampleInput.files[0]);

    output.innerHTML = '<p class="text-muted">Reading...</p>';
    fetch('preview_import_template', {
      method: 'POST', body: body, credentials: 'same-origin'
    }).then(function (r) { return r.json(); }).then(function (payload) {
      if (payload.error) {
        output.innerHTML = '<div class="alert alert-danger mb-0">' +
          escapeHtml(payload.error) + '</div>';
        return;
      }

      // First preview of a file also loads its columns, so the mapping rows
      // appear without a separate step.
      if (payload.headers && payload.headers.length &&
          !columnMap.querySelector('.column-row')) {
        renderColumns(payload.headers);
      }

      var rows = payload.sample.map(function (row) {
        var pairs = Object.keys(row.mapped).map(function (label) {
          return '<div><span class="text-muted">' + escapeHtml(label) + ':</span> ' +
            escapeHtml(row.mapped[label]) + '</div>';
        }).join('');
        return '<li class="list-group-item px-0"><span class="badge bg-' +
          (row.status === 'matched' ? 'success'
            : row.status === 'ambiguous' ? 'warning text-dark' : 'secondary') +
          '">' + row.status + '</span><div class="small mt-1">' + pairs + '</div></li>';
      }).join('');

      output.innerHTML = [
        '<p class="mb-1"><strong>' + payload.total + '</strong> row(s): ',
        '<span class="badge bg-success">' + payload.counts.matched + ' matched</span> ',
        '<span class="badge bg-warning text-dark">' + payload.counts.ambiguous + ' ambiguous</span> ',
        '<span class="badge bg-secondary">' + payload.counts.unmatched + ' unmatched</span></p>',
        '<p class="form-text">Columns found: ' +
          payload.headers.map(escapeHtml).join(', ') + '</p>',
        '<ul class="list-group list-group-flush">' + rows + '</ul>'
      ].join('');
    });
  });

  // Loading columns before any mapping exists needs a preview run, so nudge
  // toward it when the list is empty.
  if (!columnMap.querySelector('.column-row')) {
    output.innerHTML = '<p class="form-text mb-0">' +
      'Preview a sample file to load its columns.</p>';
  }
})();
