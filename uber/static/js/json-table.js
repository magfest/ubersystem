// Generic recursive JSON -> <table> renderer.
//
// Exposes window.renderJsonTable(tableId, data): replaces the <tbody>
// of #tableId with rows for every key/value in `data`, recursing into
// nested objects/arrays with section headers and indentation.
(function () {
  function escapeHtml(str) {
    var div = document.createElement('div');
    div.appendChild(document.createTextNode(str));
    return div.innerHTML;
  }

  function formatKey(key) {
    return escapeHtml(String(key).replace(/_/g, ' ').replace(/\b\w/g, function(c) { return c.toUpperCase(); }));
  }

  function formatValue(val) {
    if (val === null || val === undefined) return '<span class="text-muted">—</span>';
    if (typeof val === 'number') return escapeHtml(val.toLocaleString());
    if (typeof val === 'boolean') return val ? 'Yes' : 'No';
    return escapeHtml(String(val));
  }

  function renderRows(entries, indent) {
    var html = '';
    indent = indent || 0;
    var padClass = indent ? ' class="ps-' + (indent * 3) + '"' : '';

    for (var i = 0; i < entries.length; i++) {
      var key = entries[i][0], val = entries[i][1];

      if (Array.isArray(val)) {
        html += '<tr><th colspan="2" class="bg-light">' + formatKey(key) + '</th></tr>';
        for (var j = 0; j < val.length; j++) {
          if (typeof val[j] === 'object' && val[j] !== null) {
            var objEntries = Object.keys(val[j]).map(function(k) { return [k, val[j][k]]; });
            // Use first distinctive value as a sub-header
            var label = val[j].description || val[j].name || val[j].id || ('Item ' + (j + 1));
            html += '<tr><td colspan="2" class="ps-3 fw-semibold bg-light bg-opacity-50">' + formatValue(label) + '</td></tr>';
            html += renderRows(objEntries, indent + 2);
          } else {
            html += '<tr><td class="ps-3">' + (j + 1) + '</td><td>' + formatValue(val[j]) + '</td></tr>';
          }
        }
      } else if (typeof val === 'object' && val !== null) {
        html += '<tr><th colspan="2" class="bg-light">' + formatKey(key) + '</th></tr>';
        var subEntries = Object.keys(val).map(function(k) { return [k, val[k]]; });
        html += renderRows(subEntries, indent + 1);
      } else {
        html += '<tr><td' + padClass + '>' + formatKey(key) + '</td><td>' + formatValue(val) + '</td></tr>';
      }
    }
    return html;
  }

  window.renderJsonTable = function (tableId, data) {
    var tbody = document.querySelector('#' + tableId + ' tbody');
    tbody.innerHTML = '';
    if (!data || typeof data !== 'object') {
      tbody.innerHTML = '<tr><td class="text-muted">No data available</td></tr>';
      return;
    }
    var entries = Object.keys(data).map(function(k) { return [k, data[k]]; });
    tbody.innerHTML = renderRows(entries, 0);
  };
})();
