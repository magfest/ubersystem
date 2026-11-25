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

    // Repeated headings collapse to one key when the file is read.
    var seen = {};
    pairs = pairs.filter(function (pair) {
      if (seen[pair.key]) { return false; }
      seen[pair.key] = true;
      return true;
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
      // Dates and combined-name patterns both take a format string.
      var kind = kindByKey[select.value];
      var hasFormat = kind === 'date' || kind === 'pattern';
      if (dateBox) { dateBox.style.display = hasFormat ? '' : 'none'; }
      if (dateInput) {
        dateInput.name = hasFormat ? 'format__' + select.value : '';
        dateInput.placeholder = kind === 'pattern' ? '%last_name, %first_name' : '%m/%d/%Y';
      }
    });
  }

  columnMap.addEventListener('change', function (e) {
    if (e.target.classList.contains('column-target')) { syncHiddenInputs(); }
  });
  syncHiddenInputs();

  var enumRows = document.getElementById('enum-rows');
  var labelByKey = {};
  targetFields.forEach(function (f) { labelByKey[f.key] = f.label; });

  function hasEnumRow(target, source) {
    var wanted = ('enum__' + target + '__' + source).toLowerCase();
    return Array.prototype.some.call(
      enumRows.querySelectorAll('[name^="enum__"]'),
      function (input) { return input.name.toLowerCase() === wanted; });
  }

  function addEnumRow(target, source, ours) {
    if (!target || !source || hasEnumRow(target, source)) { return; }
    var row = document.createElement('div');
    row.className = 'row g-2 align-items-center mb-1 enum-row';
    row.innerHTML = [
      '<div class="col-md-3 small text-muted">' + escapeHtml(labelByKey[target] || target) + '</div>',
      '<div class="col-md-4"><input type="text" class="form-control form-control-sm bg-light" readonly /></div>',
      '<div class="col-md-4"><input type="text" class="form-control form-control-sm enum-ours" /></div>',
      '<div class="col-md-1"><button type="button" class="btn btn-sm btn-outline-secondary enum-remove" title="Remove">&times;</button></div>'
    ].join('');
    row.querySelector('[readonly]').value = source;
    var input = row.querySelector('.enum-ours');
    input.name = 'enum__' + target + '__' + source;
    input.value = ours || '';
    enumRows.appendChild(row);
  }

  enumRows.addEventListener('click', function (e) {
    var remove = e.target.closest('.enum-remove');
    if (remove) { remove.closest('.enum-row').remove(); }
  });

  document.getElementById('enum-add').addEventListener('click', function () {
    var source = document.getElementById('enum-add-source');
    var ours = document.getElementById('enum-add-ours');
    addEnumRow(document.getElementById('enum-add-target').value,
               source.value.trim(), ours.value.trim());
    source.value = '';
    ours.value = '';
    source.focus();
  });

  function currentMaps() {
    var columns = {};
    var formats = {};
    columnMap.querySelectorAll('.column-row').forEach(function (row) {
      var select = row.querySelector('.column-target');
      if (!select || select.value === 'match.ignore') { return; }
      columns[row.dataset.source] = select.value;
      var dateInput = row.querySelector('.date-format input');
      if (dateInput && dateInput.name && dateInput.value) { formats[select.value] = dateInput.value; }
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

      // Offer a row for every value the file uses in a list-backed column.
      Object.keys(payload.enum_values || {}).forEach(function (target) {
        payload.enum_values[target].forEach(function (value) {
          addEnumRow(target, value, '');
        });
      });

      var statuses = ['matched', 'ambiguous', 'unmatched'];
      var samples = {};
      statuses.forEach(function (status) { samples[status] = []; });
      payload.sample.forEach(function (row) {
        var fields = Object.keys(row.mapped).map(function (label) {
          return '<div><span class="text-muted">' + escapeHtml(label) + ':</span> ' +
            escapeHtml(row.mapped[label]) + '</div>';
        }).join('');
        (samples[row.status] || []).push(
          '<li class="list-group-item px-0 small">' +
          (fields || '<span class="text-muted">Nothing mapped from this row.</span>') + '</li>');
      });

      // Open on the first outcome that has rows.
      var active = statuses.filter(function (s) { return samples[s].length; })[0] || 'matched';

      output.innerHTML = [
        '<p class="mb-1"><strong>' + payload.total + '</strong> row(s)</p>',
        '<p class="form-text">Columns found: ' +
          pairs.map(function (p) { return escapeHtml(p.raw || p.key); }).join(', ') + '</p>',
        '<ul class="nav nav-tabs mb-2">' + statuses.map(function (status) {
          return '<li class="nav-item"><button type="button" class="nav-link preview-tab' +
            (status === active ? ' active' : '') + '" data-status="' + status + '">' +
            status.charAt(0).toUpperCase() + status.slice(1) +
            ' <span class="badge bg-' + (status === 'matched' ? 'success'
              : status === 'ambiguous' ? 'warning text-dark' : 'secondary') + '">' +
            payload.counts[status] + '</span></button></li>';
        }).join('') + '</ul>',
        statuses.map(function (status) {
          var count = payload.counts[status];
          var note = !count ? '<p class="form-text mb-0">No ' + status + ' rows.</p>'
            : count > samples[status].length
              ? '<p class="form-text mb-1">Showing the first ' + samples[status].length +
                ' of ' + count + '.</p>' : '';
          return '<div class="preview-pane" data-status="' + status + '"' +
            (status === active ? '' : ' style="display:none;"') + '>' + note +
            '<ul class="list-group list-group-flush">' + samples[status].join('') + '</ul></div>';
        }).join('')
      ].join('');
    });
  });

  output.addEventListener('click', function (e) {
    var tab = e.target.closest('.preview-tab');
    if (!tab) { return; }
    output.querySelectorAll('.preview-tab').forEach(function (other) {
      other.classList.toggle('active', other === tab);
    });
    output.querySelectorAll('.preview-pane').forEach(function (pane) {
      pane.style.display = pane.dataset.status === tab.dataset.status ? '' : 'none';
    });
  });

  // Loading columns before any mapping exists needs a preview run, so nudge
  // toward it when the list is empty.
  if (!columnMap.querySelector('.column-row')) {
    output.innerHTML = '<p class="form-text mb-0">' +
      'Preview a sample file to load its columns.</p>';
  }
})();
