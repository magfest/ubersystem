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
  // already chosen for a column of that key. Each pair is {raw, key}: the
  // heading as the file spells it and the normalized key it matches under.
  function renderColumns(pairs) {
    var existing = {};
    columnMap.querySelectorAll('.column-row').forEach(function (row) {
      var select = row.querySelector('.column-target');
      existing[row.dataset.source] = select ? select.value : '';
    });

    columnMap.innerHTML = pairs.map(function (pair) {
      return [
        '<div class="row g-2 align-items-end mb-2 column-row" data-source="' + escapeHtml(pair.key) + '">',
        '  <div class="col-md-5">',
        '    <div class="form-control form-control-sm bg-light">' + escapeHtml(pair.raw || pair.key) + '</div>',
        '    <div class="form-text mt-1 mb-0 matched-as">matched as <code>' + escapeHtml(pair.key) + '</code></div>',
        '    <input type="hidden" name="column__' + escapeHtml(pair.key) + '" class="column-target-input" />',
        '    <input type="hidden" name="raw__' + escapeHtml(pair.key) + '" class="raw-header-input" value="' + escapeHtml(pair.raw || '') + '" />',
        '  </div>',
        '  <div class="col-md-5">',
        '    <select class="form-select form-select-sm column-target">' +
             optionsHtml(existing[pair.key] || 'match.ignore') + '</select>',
        '  </div>',
        '  <div class="col-md-2 date-format" style="display:none;">',
        '    <input type="text" class="form-control form-control-sm" placeholder="%m/%d/%Y" />',
        '  </div>',
        '</div>'
      ].join('');
    }).join('');
    syncHiddenInputs();
  }

  // Older payloads carry only normalized header keys.
  function headerPairs(payload) {
    if (payload.header_pairs && payload.header_pairs.length) {
      return payload.header_pairs;
    }
    return (payload.headers || []).map(function (key) {
      return { raw: key, key: key };
    });
  }

  // Update existing rows with the raw headings a preview reports, including
  // the raw__ inputs so saving persists them on the format.
  function annotateRawHeaders(pairs) {
    pairs.forEach(function (pair) {
      var row = columnMap.querySelector(
        '.column-row[data-source="' + CSS.escape(pair.key) + '"]');
      if (!row || !pair.raw) { return; }
      var display = row.querySelector('.form-control.bg-light');
      if (!display) { return; }
      display.textContent = pair.raw;
      var note = row.querySelector('.matched-as');
      if (!note) {
        note = document.createElement('div');
        note.className = 'form-text mt-1 mb-0 matched-as';
        display.insertAdjacentElement('afterend', note);
      }
      note.innerHTML = 'matched as <code>' + escapeHtml(pair.key) + '</code>';
      var rawInput = row.querySelector('.raw-header-input');
      if (!rawInput) {
        rawInput = document.createElement('input');
        rawInput.type = 'hidden';
        rawInput.name = 'raw__' + pair.key;
        rawInput.className = 'raw-header-input';
        row.querySelector('.col-md-5').appendChild(rawInput);
      }
      rawInput.value = pair.raw;
    });
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
      // appear without a separate step; rows already on screen keep their
      // choices and just gain the raw headings.
      var pairs = headerPairs(payload);
      if (pairs.length && !columnMap.querySelector('.column-row')) {
        renderColumns(pairs);
      } else {
        annotateRawHeaders(pairs);
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
          pairs.map(function (p) { return escapeHtml(p.raw || p.key); }).join(', ') + '</p>',
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
