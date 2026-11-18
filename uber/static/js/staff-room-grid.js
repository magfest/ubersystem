// Spreadsheet-style room editor for staff_rooming/room_grid.
// Rows arrive as JSON in #room-grid-data; filtering, sorting and searching are local.
// Edits are staged in `pending`; each change is dry-run through grid_save, and Save posts with commit.
(function () {
  var source = document.getElementById('room-grid-data');
  if (!source) return;
  var data = JSON.parse(source.textContent);
  var wrap = document.querySelector('.rg-wrap');
  var table = document.getElementById('room-grid');
  var head = table.querySelector('thead tr');
  var tbody = table.querySelector('tbody');
  var statusEl = document.getElementById('rg-status');
  var countEl = document.getElementById('rg-count');
  var shownEl = document.getElementById('rg-shown');
  var issuesEl = document.getElementById('rg-issues');
  var saveBtn = document.getElementById('rg-save');
  var discardBtn = document.getElementById('rg-discard');
  var undoBtn = document.getElementById('rg-undo');
  var redoBtn = document.getElementById('rg-redo');
  var filtersEl = document.getElementById('rg-filters');
  var findEl = document.getElementById('rg-find');
  var findCountEl = document.getElementById('rg-find-count');
  var chooserEl = document.getElementById('rg-columns');
  var roomModal = document.getElementById('rg-room-modal');

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function each(list, fn) {
    Array.prototype.forEach.call(list, fn);
  }

  function find(list, id) {
    return list.filter(function (item) { return item.id === id; })[0];
  }

  function labelOf(col, value) {
    var match = col.all().filter(function (opt) { return opt[0] === value; })[0];
    return match ? match[1] : '';
  }

  // Columns after Roommates, in display order. key: row property; field: name saved under (none = read-only);
  // all: every [value, label]; options: the choices for one row; w: starting width; off: hidden by default;
  // link: click handler.
  var FIELDS = [
    {label: 'Leader badge', key: 'leader_badge', w: 95},
    {label: 'Inventory block', field: 'inventory_id', key: 'inventory_id', w: 220,
     all: function () { return data.blocks.map(function (b) { return [b.id, b.label]; }); },
     // A partitioned room picks from its partition's blocks; others pick from all of them.
     options: function (row) {
       var options = data.blocks.filter(function (b) {
         return !row.partition_id || b.partitions.indexOf(row.partition_id) !== -1 || b.id === row.inventory_id;
       }).map(function (b) { return [b.id, b.label]; });
       if (row.inventory_id && !find(data.blocks, row.inventory_id)) {
         options.unshift([row.inventory_id, row.inventory_label + ' (current)']);
       }
       return options;
     },
     text: function (row) { return row.inventory_label; }},
    {label: 'Room type', key: 'room_type', off: true, w: 200},
    {label: 'Partition', field: 'partition_id', key: 'partition_id', blank: true, w: 130,
     all: function () { return [['', '(No partition)']].concat(data.partitions.map(function (p) { return [p.id, p.name]; })); },
     text: function (row) { return row.partition_id ? labelOf(this, row.partition_id) : ''; }},
    {label: 'Check-in', field: 'assigned_check_in_date', key: 'check_in', date: true, w: 96},
    {label: 'Check-out', field: 'assigned_check_out_date', key: 'check_out', date: true, w: 96},
    {label: 'Requested in', key: 'requested_in', date: true, off: true, w: 105},
    {label: 'Requested out', key: 'requested_out', date: true, off: true, w: 110},
    {label: 'Billing', field: 'payment_type', key: 'payment_type', w: 190, all: function () { return data.payment_types; }},
    {label: 'Card on file', key: 'card', w: 120},
    {label: 'Card expires', key: 'card_expiry', off: true, w: 100},
    {label: 'Deposit cutoff', field: 'deposit_cutoff_date', key: 'deposit_cutoff_date', date: true, blank: true, off: true, w: 110},
    {label: 'Source', field: 'assignment_reason', key: 'assignment_reason', w: 125, all: function () { return data.reasons; },
     locked: function (row) { return row.source_locked && 'A lottery room\'s source comes from its lottery run.'; },
     // A lottery room shows which lottery it came from rather than its stored reason.
     text: function (row) { return row.source_locked ? row.source : labelOf(this, row.assignment_reason) || row.source; }},
    {label: 'Status', key: 'status', w: 85},
    {label: 'Hotel conf #', field: 'hotel_confirmation_number', key: 'hotel_confirmation_number', blank: true, w: 115},
    {label: 'Cancellation #', field: 'cancellation_confirmation_number', key: 'cancellation_confirmation_number',
     blank: true, off: true, w: 120},
    {label: 'Physical room', key: 'physical_room', w: 110,
     text: function (row) { return row.physical_room || 'Pick…'; },
     link: function (row) { openRoom(row.id, roomUrl(row.id), true); }, linkTitle: 'Pick a room on the floor map'},
    {label: 'Room #', field: 'room_number', key: 'room_number', blank: true, w: 80,
     locked: function (row) { return row.physical_room && 'The room number follows the linked physical room.'; }},
    {label: 'Special requests', field: 'special_requests', key: 'special_requests', blank: true, off: true, w: 200},
    {label: 'Room notes', field: 'admin_notes', key: 'admin_notes', blank: true, off: true, w: 200},
    {label: 'Message to roommates', field: 'occupant_message', key: 'occupant_message', blank: true, off: true, w: 200,
     locked: function (row) { return row.assignment_reason !== String(data.crash_reason) && 'Only crash space rooms show a message.'; }},
    {label: 'Lottery entry', key: 'app_label', off: true, w: 115,
     link: function (row) { openRoom(row.id, '../hotel_lottery_admin/form?id=' + encodeURIComponent(row.app_id)); },
     linkTitle: 'Open the lottery entry'},
    {label: 'Entry notes', key: 'app_notes', off: true, w: 200},
    {label: '', name: 'Edit link', key: 'open', w: 48, text: function () { return 'Edit'; },
     link: function (row) { openRoom(row.id, roomUrl(row.id)); }, linkTitle: 'Open the full room form'}
  ];
  var MATES = {label: 'Roommates', key: 'mates', w: 360};
  var NUM_WIDTH = 40;

  function roomUrl(id) {
    return '../hotel_lottery_admin/edit_room_assignment?id=' + encodeURIComponent(id);
  }

  function column(key) {
    return key === 'mates' ? MATES : FIELDS.filter(function (col) { return col.key === key; })[0];
  }

  var order = [];        // every row id, in the order the server sent them
  var visible = [];      // the ids that pass the filters, sorted
  var original = {};     // id -> row as last saved
  var pending = {};      // id -> {fields: {field: value}, add: [{id, name, badge}], remove: [id], leader: id}
  var undoStack = [], redoStack = [];   // JSON snapshots of `pending`; cleared on save
  var selected = {};     // 'rowIndex|colIndex' into `visible` and FIELDS -> true
  var anchor = null, active = null;
  var drag = null, fill = null, editing = false, menu = null;
  var issues = [], checkTimer = null, checkSeq = 0;
  var sort = {by: '', dir: 1};
  var hidden = {};       // column key -> true
  var widths = {};       // column key -> px, for columns the viewer resized
  var frozen = 0;        // how many columns after Roommates stay put sideways
  var colFilters = {};   // column key -> {values: [text]} | {text, blank} | {from, to, blank}
  var found = {};        // 'rowIndex|colIndex' -> true, for the find bar's matches

  // The most common check-in year; dates in it display without a year.
  var usualYear = (function () {
    var counts = {}, best = '';
    data.rows.forEach(function (row) {
      var year = row.check_in.slice(0, 4);
      counts[year] = (counts[year] || 0) + 1;
      if (year && (!best || counts[year] > counts[best])) best = year;
    });
    return best;
  })();

  function setStatus(text, bad) {
    statusEl.textContent = text || '';
    statusEl.className = 'small ' + (bad ? 'text-danger' : 'text-success');
  }

  function fmtDate(iso) {
    if (!iso) return '';
    var options = {weekday: 'short', month: 'short', day: 'numeric'};
    // Other years are shown explicitly.
    if (iso.slice(0, 4) !== usualYear) options.year = 'numeric';
    return new Date(iso + 'T00:00:00').toLocaleDateString('en-US', options);
  }

  // ---- saved configuration ----------------------------------------

  // Columns, order, widths, frozen count and sort, in a cookie named for this page.
  var CONFIG_COOKIE = 'grid_' + location.pathname.replace(/[^a-z0-9]+/gi, '_').replace(/^_|_$/g, '');
  var chosen = {};   // what the viewer changed from the defaults, as {column key: shown}

  function saveConfig() {
    var config = {cols: chosen, widths: widths, sort: sort, frozen: frozen,
                  order: FIELDS.map(function (col) { return col.key; })};
    document.cookie = CONFIG_COOKIE + '=' + encodeURIComponent(JSON.stringify(config)) +
      '; path=' + location.pathname + '; max-age=31536000; SameSite=Lax';
  }

  (function () {
    var match = document.cookie.split('; ').filter(function (part) { return part.indexOf(CONFIG_COOKIE + '=') === 0; })[0];
    if (!match) return;
    try {
      var config = JSON.parse(decodeURIComponent(match.slice(CONFIG_COOKIE.length + 1)));
      chosen = config.cols || {};
      Object.keys(config.widths || {}).forEach(function (key) { if (column(key)) widths[key] = +config.widths[key] || 100; });
      if (config.sort && column(config.sort.by)) sort = {by: config.sort.by, dir: config.sort.dir === -1 ? -1 : 1};
      frozen = Math.max(0, +config.frozen || 0);
      // Columns missing from the saved order go last.
      var rank = {};
      FIELDS.forEach(function (col, i) {
        var at = (config.order || []).indexOf(col.key);
        rank[col.key] = at === -1 ? 1000 + i : at;
      });
      FIELDS.sort(function (a, b) { return rank[a.key] - rank[b.key]; });
    } catch (e) { /* a mangled cookie just means the defaults */ }
  })();
  FIELDS.forEach(function (col) {
    if (col.key in chosen ? !chosen[col.key] : col.off) hidden[col.key] = true;
  });

  // ---- staged edits -------------------------------------------------

  // A row as it would look once the staged edits are saved.
  function view(id) {
    var row = original[id], edit = pending[id];
    if (!edit) return row;
    var out = Object.assign({}, row);
    out.staged = edit.fields || {};
    FIELDS.forEach(function (col) {
      if (col.field && col.field in out.staged) out[col.key] = out.staged[col.field];
    });
    var block = find(data.blocks, out.inventory_id);
    if (block) {
      out.inventory_label = block.label;
      out.room_type = block.room_type;
      out.capacity = block.capacity;
      out.hotel_id = block.hotel_id;
    } else if ('inventory_id' in out.staged) {
      out.inventory_label = out.inventory_id;
      out.room_type = '';
    }
    out.leader_id = edit.leader || row.leader_id;
    out.occupants = row.occupants.filter(function (o) { return (edit.remove || []).indexOf(o.id) === -1; })
      .concat((edit.add || []).map(function (o) { return {id: o.id, name: o.name, badge: o.badge, staged: true}; }));
    out.occupants.sort(function (a, b) { return (a.id !== out.leader_id) - (b.id !== out.leader_id); });
    // Follows a staged change of leader.
    var leader = find(out.occupants, out.leader_id);
    if (leader) out.leader_badge = leader.badge || '';
    return out;
  }

  function stage(id) {
    pending[id] = pending[id] || {};
    ['add', 'remove'].forEach(function (k) { pending[id][k] = pending[id][k] || []; });
    pending[id].fields = pending[id].fields || {};
    return pending[id];
  }

  // False when the cell cannot take a value.
  function setField(id, col, value) {
    if (!col.field || (col.locked && col.locked(original[id]))) return false;
    var edit = stage(id);
    if (value === original[id][col.key]) delete edit.fields[col.field];
    else edit.fields[col.field] = value;
    return true;
  }

  // Run a change to `pending`, remembering the state before it for undo.
  function mutate(change, focusSelector) {
    var before = JSON.stringify(pending);
    change();
    Object.keys(pending).forEach(function (id) {
      var edit = pending[id];
      if (!Object.keys(edit.fields || {}).length && !(edit.add || []).length && !(edit.remove || []).length && !edit.leader) {
        delete pending[id];
      }
    });
    if (JSON.stringify(pending) === before) { render(focusSelector); return; }
    undoStack.push(before);
    redoStack = [];
    setStatus('');
    render(focusSelector);
    scheduleCheck();
  }

  function step(from, to) {
    if (!from.length) return;
    to.push(JSON.stringify(pending));
    pending = JSON.parse(from.pop());
    setStatus('');
    render();
    scheduleCheck();
  }

  function undo() { step(undoStack, redoStack); }
  function redo() { step(redoStack, undoStack); }

  function payload() {
    var edits = {};
    Object.keys(pending).forEach(function (id) {
      var edit = pending[id];
      edits[id] = {fields: edit.fields, remove: edit.remove, leader: edit.leader || '',
                   add: edit.add.map(function (o) { return o.id; })};
    });
    return JSON.stringify(edits);
  }

  function post(commit) {
    var body = new URLSearchParams({edits: payload(), commit: commit ? '1' : '', csrf_token: csrf_token});
    return fetch('grid_save', {method: 'POST', body: body, credentials: 'same-origin'})
      .then(function (r) { return r.json(); })
      .then(function (resp) {
        if (!resp || resp.error || !resp.issues) throw new Error((resp && resp.error) || 'The server did not answer.');
        return resp;
      });
  }

  function scheduleCheck() {
    clearTimeout(checkTimer);
    var seq = ++checkSeq;
    if (!Object.keys(pending).length) { issues = []; renderIssues(); return; }
    checkTimer = setTimeout(function () {
      post(false).then(function (resp) {
        if (seq !== checkSeq) return;
        issues = resp.issues;
        renderIssues();
      }).catch(function (err) { if (seq === checkSeq) setStatus(err.message, true); });
    }, 250);
  }

  function saveAll() {
    if (!Object.keys(pending).length) return;
    clearTimeout(checkTimer);
    var seq = ++checkSeq;
    saveBtn.disabled = true;
    post(true).then(function (resp) {
      if (seq !== checkSeq) return;
      if (resp.saved) {
        pending = {};
        resp.rows.forEach(function (row) {
          if (row.live) original[row.id] = row; else dropRow(row.id);
        });
        undoStack = []; redoStack = []; issues = [];
        setStatus('Saved ' + resp.rows.length + ' room' + (resp.rows.length === 1 ? '' : 's') + '.');
      } else {
        issues = resp.issues;
        var errors = issues.filter(function (i) { return i.severity === 'error'; }).length;
        setStatus('Not saved: fix the ' + errors + ' error' + (errors === 1 ? '' : 's') + ' listed first.', true);
      }
      render();
    }).catch(function (err) { setStatus(err.message, true); render(); });
  }

  // Drop a room that was removed or cancelled.
  function dropRow(id) {
    order.splice(order.indexOf(id), 1);
    if (visible.indexOf(id) !== -1) visible.splice(visible.indexOf(id), 1);
    delete original[id];
    delete pending[id];
    selected = {};
    anchor = active = null;
  }

  // ---- values -------------------------------------------------------

  var ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;

  // Whether a staged value could not be saved.
  function invalid(col, row) {
    if (!col.field || !row.staged || !(col.field in row.staged)) return false;
    var value = row[col.key];
    if (value === '') return !col.blank;
    if (col.date) return !ISO_DATE.test(value);
    return !!col.all && !labelOf(col, value);
  }

  // Whether to paint a cell as wrong: an unsavable value, or a stay that ends before it starts.
  function flagged(col, row) {
    if (invalid(col, row)) return true;
    if (col.key !== 'check_in' && col.key !== 'check_out') return false;
    var touched = row.staged && ('assigned_check_in_date' in row.staged || 'assigned_check_out_date' in row.staged);
    return !!touched && ISO_DATE.test(row.check_in) && ISO_DATE.test(row.check_out) && row.check_out <= row.check_in;
  }

  // What a cell displays.
  function shown(col, row) {
    if (invalid(col, row)) return row[col.key];
    if (col.date) return fmtDate(row[col.key]);
    if (col.text) return col.text(row);
    return (col.all ? labelOf(col, row[col.key]) : row[col.key]) || '';
  }

  // What a cell holds, for filtering, finding, copying and exporting: dates
  // as ISO, and a link column's value rather than its link text.
  function cellText(col, row) {
    if (col.link) return col.key === 'open' ? '' : String(row[col.key] || '');
    if (col.date && !invalid(col, row)) return row[col.key] || '';
    return String(shown(col, row));
  }

  // Typed or pasted text as a value for this column; text that doesn't parse is kept and shown invalid.
  function parsed(col, text) {
    text = text.trim();
    if (col.date) {
      if (ISO_DATE.test(text)) return text;
      var when = /\d{4}/.test(text) ? new Date(text) : null;   // no guessing a missing year
      if (!when || isNaN(when)) return text;
      return when.getFullYear() + '-' + ('0' + (when.getMonth() + 1)).slice(-2) + '-' + ('0' + when.getDate()).slice(-2);
    }
    if (!text || !col.all) return text;
    var lower = text.toLowerCase();
    var match = col.all().filter(function (opt) { return opt[1].toLowerCase() === lower || opt[0] === text; })[0];
    return match ? match[0] : text;
  }

  // ---- layout: widths, frozen columns, header -----------------------

  var layoutStyle = document.head.appendChild(el('style'));
  var resized = false;   // swallows the click that ends a drag on a header

  function widthOf(key) {
    return widths[key] || column(key).w;
  }

  function shownColumns() {
    return FIELDS.map(function (col, c) { return c; }).filter(function (c) { return !hidden[FIELDS[c].key]; });
  }

  // One stylesheet holds every column's width and frozen offset, so newly drawn rows need no sizing.
  function layout() {
    var size = function (px) { return 'width:' + px + 'px;min-width:' + px + 'px;max-width:' + px + 'px;'; };
    var rules = ['#room-grid .rg-num{' + size(NUM_WIDTH) + '}',
                 '#room-grid [data-col="mates"]{' + size(widthOf('mates')) + '}'];
    var left = NUM_WIDTH + widthOf('mates'), total = left;
    shownColumns().forEach(function (c, n) {
      var key = FIELDS[c].key, width = widthOf(key);
      rules.push('#room-grid [data-col="' + key + '"]{' + size(width) + '}');
      if (n < frozen) {
        rules.push('#room-grid td[data-col="' + key + '"]{position:sticky;left:' + left + 'px;z-index:1;}');
        rules.push('#room-grid th[data-col="' + key + '"]{left:' + left + 'px;z-index:4;}');
        left += width;
      }
      total += width;
    });
    layoutStyle.textContent = rules.join('\n');
    table.style.width = total + 'px';
    each(head.children, function (th) { th.classList.toggle('rg-hidden', !!hidden[th.dataset.col]); });
  }

  function showSort() {
    each(head.querySelectorAll('th[data-sort]'), function (th) {
      var on = th.dataset.sort === sort.by;
      th.querySelector('.rg-arrow').textContent = on ? (sort.dir === 1 ? ' ▲' : ' ▼') : '';
      th.setAttribute('aria-sort', on ? (sort.dir === 1 ? 'ascending' : 'descending') : 'none');
      th.classList.toggle('rg-filtered', !!colFilters[th.dataset.col]);
    });
  }

  // FIELDS is the column order, so the header follows it. Roommates stays first.
  function orderHeader() {
    FIELDS.forEach(function (col) { head.appendChild(head.querySelector('th[data-col="' + col.key + '"]')); });
  }

  var dragKey = null;

  function clearDropMarks() {
    each(head.children, function (th) { th.classList.remove('rg-drop-before', 'rg-drop-after'); });
  }

  function buildHeader() {
    head.appendChild(el('th', 'rg-num', '#'));
    [MATES].concat(FIELDS).forEach(function (col) {
      var th = el('th', '', col.label);
      th.dataset.col = col.key;
      th.title = col.name || col.label;
      if (col === MATES) th.appendChild(el('span', 'fw-normal text-muted', ' (★ leader)'));

      if (col.label) {
        th.dataset.sort = col.key;
        th.setAttribute('aria-sort', 'none');
        th.appendChild(el('span', 'rg-arrow'));
        th.addEventListener('click', function (event) {
          if (resized || event.target.classList.contains('rg-grip') || event.target.classList.contains('rg-filter-btn')) return;
          // Ascending, descending, then back to the original order.
          if (sort.by !== col.key) sort = {by: col.key, dir: 1};
          else if (sort.dir === 1) sort.dir = -1;
          else sort = {by: '', dir: 1};
          saveConfig();
          refilter();
        });
      }

      if (col !== MATES && col.label) {
        var filter = th.appendChild(el('button', 'rg-filter-btn', '▼'));
        filter.type = 'button';
        filter.title = 'Filter ' + col.label;
        filter.setAttribute('aria-label', filter.title);
        filter.addEventListener('click', function (event) { event.stopPropagation(); openFilter(col, th); });
      }

      var grip = th.appendChild(el('span', 'rg-grip'));
      grip.title = 'Drag to resize; double-click to reset';
      grip.addEventListener('mousedown', function (event) {
        event.preventDefault();
        event.stopPropagation();
        var startX = event.clientX, startWidth = th.getBoundingClientRect().width;

        function move(e) {
          resized = true;
          widths[col.key] = Math.max(40, Math.round(startWidth + e.clientX - startX));
          layout();
          if (col === MATES) render();   // its width decides how the chips wrap
        }
        function done() {
          document.removeEventListener('mousemove', move);
          document.removeEventListener('mouseup', done);
          saveConfig();
          setTimeout(function () { resized = false; }, 0);
        }
        document.addEventListener('mousemove', move);
        document.addEventListener('mouseup', done);
      });
      grip.addEventListener('dblclick', function (event) {
        event.stopPropagation();
        delete widths[col.key];
        layout();
        render();
        saveConfig();
      });

      // Dragging a header onto another moves its column there.
      if (col !== MATES) {
        var dropsAfter = function (event) {
          var box = th.getBoundingClientRect();
          return event.clientX > box.left + box.width / 2;
        };
        th.draggable = true;
        th.addEventListener('dragstart', function (event) {
          dragKey = col.key;
          event.dataTransfer.effectAllowed = 'move';
          event.dataTransfer.setData('text/plain', col.label);
        });
        th.addEventListener('dragover', function (event) {
          if (!dragKey || dragKey === col.key) return;
          event.preventDefault();
          clearDropMarks();
          th.classList.add(dropsAfter(event) ? 'rg-drop-after' : 'rg-drop-before');
        });
        th.addEventListener('drop', function (event) {
          if (!dragKey || dragKey === col.key) return;
          event.preventDefault();
          var moved = FIELDS.splice(FIELDS.indexOf(column(dragKey)), 1)[0];
          FIELDS.splice(FIELDS.indexOf(col) + (dropsAfter(event) ? 1 : 0), 0, moved);
          columnsChanged();
        });
        th.addEventListener('dragend', function () { dragKey = null; clearDropMarks(); });
      }
      head.appendChild(th);
    });
  }

  // Column indexes shift on a reorder or hide, so clear the selection.
  function columnsChanged() {
    orderHeader();
    selected = {};
    anchor = active = null;
    saveConfig();
    layout();
    buildChooser();
    render();
  }

  // ---- filters and sorting ------------------------------------------

  function filterValue(name) {
    return filtersEl.elements[name].value;
  }

  function passesColumnFilter(col, filter, row) {
    var text = cellText(col, row);
    if (filter.values) return filter.values.indexOf(text) !== -1;
    if (filter.blank === 'blank') return !text;
    if (filter.blank === 'filled' && !text) return false;
    if (filter.text && text.toLowerCase().indexOf(filter.text.toLowerCase()) === -1) return false;
    if (filter.from && !(text && text >= filter.from)) return false;
    if (filter.to && !(text && text <= filter.to)) return false;
    return true;
  }

  function matches(id) {
    var row = view(id);
    var needle = filterValue('search').trim().toLowerCase();
    if (needle) {
      var names = row.occupants.map(function (o) { return o.name; }).join(' ').toLowerCase();
      if ((row.haystack + ' ' + names).indexOf(needle) === -1) return false;
    }
    var fromLottery = row.has_run || data.lottery_reasons.indexOf(row.assignment_reason) !== -1;
    var crash = !fromLottery && row.assignment_reason === data.crash_reason;
    var from = filterValue('source');
    if (from === 'lottery' && !fromLottery) return false;
    if (from === 'crash_space' && !crash) return false;
    if (from === 'other' && (fromLottery || crash)) return false;
    var billing = filterValue('billing'), card = data.card_types.indexOf(row.payment_type) !== -1;
    if (billing === 'self_pay' && !card) return false;
    if (billing === 'master_bill' && card) return false;
    if (billing === 'parking' && data.parking_types.indexOf(row.payment_type) === -1) return false;
    var hotel = filterValue('hotel');
    if (hotel && row.hotel_id !== hotel) return false;
    if (filtersEl.elements.unsaved.checked && !pending[id]) return false;
    return Object.keys(colFilters).every(function (key) { return passesColumnFilter(column(key), colFilters[key], row); });
  }

  function sortKey(id) {
    var row = view(id);
    if (sort.by === 'mates') return row.occupants.length ? row.occupants[0].name.toLowerCase() : '';
    return cellText(column(sort.by), row).toLowerCase();
  }

  // Rows only join or leave the screen here, never while they are being edited.
  function refilter() {
    visible = order.filter(matches);
    if (sort.by !== '') {
      var keys = {};
      visible.forEach(function (id) { keys[id] = sortKey(id); });
      visible.sort(function (a, b) { return (keys[a] < keys[b] ? -1 : keys[a] > keys[b] ? 1 : 0) * sort.dir; });
    }
    selected = {};
    anchor = active = null;
    wrap.scrollTop = 0;
    showSort();
    render();
  }

  filtersEl.addEventListener('input', refilter);
  filtersEl.addEventListener('submit', function (event) { event.preventDefault(); });
  filtersEl.addEventListener('reset', function () {
    colFilters = {};
    setTimeout(refilter, 0);
  });

  // ---- per-column filters -------------------------------------------

  var pop = null;

  function closePop() {
    if (pop) pop.remove();
    pop = null;
  }

  document.addEventListener('mousedown', function (event) {
    if (pop && !pop.contains(event.target) && !event.target.classList.contains('rg-filter-btn')) closePop();
  });

  // Dates filter by range, text by substring, and columns with few distinct values by checklist.
  function openFilter(col, th) {
    var was = pop && pop.dataset.col === col.key;
    closePop();
    if (was) return;
    pop = el('div', 'rg-pop');
    pop.dataset.col = col.key;
    var filter = colFilters[col.key] || {};

    function apply(next) {
      var empty = !next || (next.values ? false : !(next.text || next.from || next.to || next.blank));
      if (empty) delete colFilters[col.key]; else colFilters[col.key] = next;
      refilter();
    }

    var blankChoice = function () {
      var select = el('select');
      [['', 'Blank or filled'], ['blank', 'Blank only'], ['filled', 'Filled only']].forEach(function (opt) {
        select.add(new Option(opt[1], opt[0], false, (filter.blank || '') === opt[0]));
      });
      return select;
    };

    var distinct = {};
    order.forEach(function (id) { distinct[cellText(col, view(id))] = true; });
    var texts = Object.keys(distinct).sort(function (a, b) { return a.localeCompare(b); });

    if (col.date) {
      var from = el('input'), to = el('input'), blank = blankChoice();
      from.type = to.type = 'date';
      from.value = filter.from || '';
      to.value = filter.to || '';
      var changed = function () { apply({from: from.value, to: to.value, blank: blank.value}); };
      [['On or after', from], ['On or before', to], ['', blank]].forEach(function (pair) {
        if (pair[0]) pop.appendChild(el('div', 'text-muted', pair[0]));
        pair[1].addEventListener('input', changed);
        pop.appendChild(pair[1]);
      });
    } else if (col.all || texts.length <= 25) {
      // No filter means everything is ticked.
      var picked = {};
      (filter.values || texts).forEach(function (text) { picked[text] = true; });
      var list = el('div', 'rg-pop-values'), boxes = [];
      var sync = function () {
        var values = texts.filter(function (text) { return picked[text]; });
        apply(values.length === texts.length ? null : {values: values});
      };
      var bar = el('div', 'd-flex gap-2 mb-1');
      [['All', true], ['None', false]].forEach(function (pair) {
        var link = el('a', '', pair[0]);
        link.href = '#';
        link.addEventListener('click', function (event) {
          event.preventDefault();
          texts.forEach(function (text) { picked[text] = pair[1]; });
          boxes.forEach(function (box) { box.checked = pair[1]; });
          sync();
        });
        bar.appendChild(link);
      });
      pop.appendChild(bar);
      texts.forEach(function (text) {
        var label = el('label'), box = el('input');
        box.type = 'checkbox';
        box.checked = !!picked[text];
        box.addEventListener('change', function () { picked[text] = box.checked; sync(); });
        boxes.push(box);
        label.appendChild(box);
        label.appendChild(document.createTextNode(' ' + (text || '(blank)')));
        list.appendChild(label);
      });
      pop.appendChild(list);
    } else {
      var contains = el('input'), which = blankChoice();
      contains.type = 'text';
      contains.placeholder = 'Contains…';
      contains.value = filter.text || '';
      var update = function () { apply({text: contains.value, blank: which.value}); };
      contains.addEventListener('input', update);
      which.addEventListener('input', update);
      pop.appendChild(contains);
      pop.appendChild(which);
    }

    var clear = el('button', 'btn btn-sm btn-outline-secondary', 'Clear filter');
    clear.type = 'button';
    clear.addEventListener('click', function () { apply(null); closePop(); });
    pop.appendChild(clear);

    var box = th.getBoundingClientRect();
    pop.style.top = box.bottom + 2 + 'px';
    pop.style.left = Math.max(4, Math.min(box.left, window.innerWidth - 300)) + 'px';
    document.body.appendChild(pop);
    var first = pop.querySelector('input');
    if (first) first.focus();
  }

  // ---- drawing only the rows on screen ------------------------------

  // Row heights are computed from the roommate names, not measured, so undrawn rows have one too.
  var LINE = 26, EXTRA_LINE = 22, overscan = 12;
  var win = {start: 0, end: 0};
  var offsets = [0];     // offsets[r] is where row r starts; one more entry than rows
  var ruler = document.createElement('canvas').getContext('2d'), textWidths = {};
  var fontFamily = getComputedStyle(table).fontFamily;

  function textWidth(text, bold) {
    var key = (bold ? 'b' : 'n') + text;
    if (!(key in textWidths)) {
      ruler.font = (bold ? '600 ' : '') + '12.5px ' + fontFamily;
      textWidths[key] = ruler.measureText(text).width;
    }
    return textWidths[key];
  }

  // How many lines the roommate chips wrap to.
  function chipLines(row) {
    var full = row.capacity && row.occupants.length >= row.capacity;
    // The cell less its padding, the add box and the count.
    var room = widthOf('mates') - 10 - (full ? 0 : 86) - (row.capacity ? 28 : 0), used = 0, lines = 1;
    row.occupants.forEach(function (person) {
      var leader = person.id === row.leader_id;
      var width = textWidth(person.name, leader) + (leader ? 30 : 42) + 3;   // the chip's padding, star and buttons
      if (used && used + width > room) { lines++; used = 0; }
      used += width;
    });
    return lines;
  }

  function measureRows() {
    offsets = [0];
    visible.forEach(function (id) {
      offsets.push(offsets[offsets.length - 1] + LINE + (chipLines(view(id)) - 1) * EXTRA_LINE);
    });
  }

  // The row at scroll offset y.
  function rowAt(y) {
    var low = 0, high = visible.length - 1;
    while (low < high) {
      var mid = (low + high + 1) >> 1;
      if (offsets[mid] <= y) low = mid; else high = mid - 1;
    }
    return Math.max(0, low);
  }

  function spacer(px) {
    var tr = el('tr', 'rg-spacer');
    var td = tr.appendChild(el('td'));
    td.colSpan = FIELDS.length + 2;
    td.style.height = px + 'px';
    return tr;
  }

  function drawRows() {
    // Before the first rows exist the scroller has no height to measure.
    var top = wrap.scrollTop, height = wrap.clientHeight > 200 ? wrap.clientHeight : window.innerHeight;
    win = {start: Math.max(0, rowAt(top) - overscan),
           end: Math.min(visible.length, rowAt(top + height) + 1 + overscan)};
    var rows = document.createDocumentFragment();
    if (win.start) rows.appendChild(spacer(offsets[win.start]));
    for (var r = win.start; r < win.end; r++) rows.appendChild(renderRow(visible[r], r));
    if (win.end < visible.length) rows.appendChild(spacer(offsets[visible.length] - offsets[win.end]));
    tbody.textContent = '';
    tbody.appendChild(rows);
    paint();
    markIssues();
  }

  function editingSomething() {
    return editing || !!(document.activeElement && document.activeElement.closest('td.rg-mates'));
  }

  // Redraw when scrolling nears the edge of the drawn rows; never mid-edit, which would destroy the editor.
  function redrawIfScrolled() {
    if (editingSomething()) return;
    var first = rowAt(wrap.scrollTop), last = rowAt(wrap.scrollTop + wrap.clientHeight) + 1;
    if ((first < win.start + 3 && win.start > 0) || (last > win.end - 3 && win.end < visible.length)) drawRows();
  }

  wrap.addEventListener('scroll', function () {
    closeMenu();
    closePop();
    redrawIfScrolled();
  });

  function cellEl(cell) {
    if (cell.c === MATES_COLUMN) return tbody.querySelector('td.rg-mates[data-r="' + cell.r + '"]');
    return tbody.querySelector('td[data-r="' + cell.r + '"][data-c="' + cell.c + '"]');
  }

  // Scroll a cell into view and make sure it is drawn.
  function ensureVisible(cell) {
    var headHeight = head.offsetHeight;
    var top = offsets[cell.r], bottom = offsets[cell.r + 1];
    if (top < wrap.scrollTop) wrap.scrollTop = top;
    else if (bottom > wrap.scrollTop + wrap.clientHeight - headHeight) {
      wrap.scrollTop = bottom - wrap.clientHeight + headHeight;
    }
    if (cell.r < win.start || cell.r >= win.end) drawRows();
    var td = cellEl(cell);
    if (!td || cell.c === MATES_COLUMN || shownColumns().indexOf(cell.c) < frozen) return td;
    var pinned = NUM_WIDTH + widthOf('mates');
    shownColumns().slice(0, frozen).forEach(function (c) { pinned += widthOf(FIELDS[c].key); });
    if (td.offsetLeft - pinned < wrap.scrollLeft) wrap.scrollLeft = td.offsetLeft - pinned;
    else if (td.offsetLeft + td.offsetWidth > wrap.scrollLeft + wrap.clientWidth) {
      wrap.scrollLeft = td.offsetLeft + td.offsetWidth - wrap.clientWidth;
    }
    return td;
  }

  // ---- selection ----------------------------------------------------

  function selectedCells() {
    return Object.keys(selected).map(function (key) {
      var parts = key.split('|');
      return {r: +parts[0], c: +parts[1]};
    });
  }

  // Hidden columns are never selected, so they are never filled, copied or pasted over.
  function selectRange(from, to, keep) {
    if (!keep) selected = {};
    for (var r = Math.min(from.r, to.r); r <= Math.max(from.r, to.r); r++) {
      for (var c = Math.max(0, Math.min(from.c, to.c)); c <= Math.max(from.c, to.c); c++) {
        if (!hidden[FIELDS[c].key]) selected[r + '|' + c] = true;
      }
    }
  }

  // Column -1 is the Roommates cell: it can be active, for keyboard editing, but is never in `selected`.
  var MATES_COLUMN = -1;

  function selectOnly(cell) {
    selected = {};
    if (cell.c !== MATES_COLUMN) selected[cell.r + '|' + cell.c] = true;
    anchor = active = cell;
  }

  function bounds(cells) {
    var rs = cells.map(function (x) { return x.r; }), cs = cells.map(function (x) { return x.c; });
    return {r0: Math.min.apply(null, rs), r1: Math.max.apply(null, rs), c0: Math.min.apply(null, cs), c1: Math.max.apply(null, cs)};
  }

  function paint() {
    var cells = selectedCells();
    var corner = cells.length && !editing ? bounds(cells) : null;
    var old = tbody.querySelector('.rg-fill-handle');
    if (old) old.remove();
    each(tbody.querySelectorAll('td.rg-mates'), function (td) {
      td.classList.toggle('rg-active', !!active && active.c === MATES_COLUMN && +td.dataset.r === active.r);
    });
    each(tbody.querySelectorAll('td.rg-edit'), function (td) {
      var r = +td.dataset.r, c = +td.dataset.c, key = r + '|' + c;
      td.classList.toggle('rg-sel', !!selected[key]);
      td.classList.toggle('rg-active', !!active && r === active.r && c === active.c);
      td.classList.toggle('rg-found', !!found[key]);
      td.classList.toggle('rg-fill-target', !!fill && fill.to !== null && c >= fill.c0 && c <= fill.c1 &&
                          ((r > fill.r1 && r <= fill.to) || (r < fill.r0 && r >= fill.to)));
      // The fill handle sits on the selection's bottom-right cell.
      if (corner && r === corner.r1 && c === corner.c1 && !td.classList.contains('rg-editing')) {
        var handle = td.appendChild(el('span', 'rg-fill-handle'));
        handle.title = 'Drag to fill';
        handle.addEventListener('mousedown', function (event) {
          event.preventDefault();
          event.stopPropagation();
          fill = {r0: corner.r0, r1: corner.r1, c0: corner.c0, c1: corner.c1, to: null};
        });
      }
    });
  }

  function cellAt(target) {
    var td = target.closest && target.closest('td.rg-edit');
    return td && !td.classList.contains('rg-editing') ? {r: +td.dataset.r, c: +td.dataset.c} : null;
  }

  tbody.addEventListener('mousedown', function (event) {
    var cell = cellAt(event.target);
    if (!cell || event.button !== 0) return;
    event.preventDefault();
    wrap.focus({preventScroll: true});
    var extend = event.ctrlKey || event.metaKey;
    if (event.shiftKey && anchor) {
      selectRange(anchor, cell, extend);
    } else if (extend) {
      var key = cell.r + '|' + cell.c;
      if (selected[key]) delete selected[key]; else selected[key] = true;
      anchor = active = cell;
    } else {
      // A second click on the one selected cell opens it.
      var again = active && active.r === cell.r && active.c === cell.c && Object.keys(selected).length === 1;
      selectOnly(cell);
      drag = {moved: false, again: again};
    }
    paint();
  });

  // Take a drag-select or a fill as far as `cell`.
  function dragTo(cell) {
    if (!cell) return;
    if (fill) {
      fill.to = cell.r;
      paint();
    } else if (drag && !(cell.r === anchor.r && cell.c === anchor.c && !drag.moved)) {
      drag.moved = true;
      selectRange(anchor, cell);
      paint();
    }
  }

  tbody.addEventListener('mouseover', function (event) { dragTo(cellAt(event.target)); });

  // Dragging past an edge scrolls, faster the further past. Rows redraw as they scroll, so the cell under
  // the pointer is looked up on every tick.
  var pointer = null, scrollTimer = null;

  function stopAutoScroll() {
    clearInterval(scrollTimer);
    scrollTimer = null;
  }

  function autoScroll() {
    if (!pointer || (!drag && !fill)) { stopAutoScroll(); return; }
    var box = wrap.getBoundingClientRect(), edge = 28;
    // Clamp the edges to the window in case the grid runs past it.
    var top = Math.max(0, box.top) + head.offsetHeight, bottom = Math.min(window.innerHeight, box.top + wrap.clientHeight);
    var left = box.left + NUM_WIDTH + widthOf('mates'), right = Math.min(window.innerWidth, box.left + wrap.clientWidth);
    var pull = function (at, low, high) { return at > high - edge ? at - (high - edge) : (at < low + edge ? at - (low + edge) : 0); };
    var dy = pull(pointer.y, top, bottom);
    // No sideways scroll for a fill, or when the pinned columns take the whole width.
    var dx = fill || right - left < 3 * edge ? 0 : pull(pointer.x, left, right);
    if (!dy && !dx) { stopAutoScroll(); return; }
    if (!scrollTimer) { scrollTimer = setInterval(autoScroll, 40); return; }
    wrap.scrollTop += Math.max(-60, Math.min(60, dy));
    wrap.scrollLeft += Math.max(-60, Math.min(60, dx));
    redrawIfScrolled();
    // Inset from the edges, where the scrollbars are.
    var under = document.elementFromPoint(Math.max(left + 4, Math.min(right - 20, pointer.x)),
                                          Math.max(top + 4, Math.min(bottom - 20, pointer.y)));
    if (under) dragTo(cellAt(under));
  }

  document.addEventListener('mousemove', function (event) {
    if (!drag && !fill) return;
    pointer = {x: event.clientX, y: event.clientY};
    autoScroll();
  });

  document.addEventListener('mouseup', function () {
    var opened = drag && drag.again && !drag.moved, filling = fill;
    drag = fill = null;
    pointer = null;
    stopAutoScroll();
    if (filling && filling.to !== null && (filling.to > filling.r1 || filling.to < filling.r0)) fillRows(filling);
    else if (filling) paint();
    else if (opened) startEdit();
  });

  tbody.addEventListener('dblclick', function (event) {
    var cell = cellAt(event.target);
    if (!cell) return;
    if (!selected[cell.r + '|' + cell.c]) selectOnly(cell);
    active = cell;
    startEdit();
  });

  function moveActive(rows, cols, extend) {
    if (!active) return;
    var columns = [MATES_COLUMN].concat(shownColumns());
    var at = Math.max(0, Math.min(columns.length - 1, columns.indexOf(active.c) + cols));
    var next = {r: Math.max(0, Math.min(visible.length - 1, active.r + rows)), c: columns[at]};
    if (extend) { active = next; selectRange(anchor, next); } else selectOnly(next);
    ensureVisible(next);
    paint();
  }

  // ---- filling ------------------------------------------------------

  // Dragging the handle repeats the selected rows over the rows dragged across.
  function fillRows(range) {
    var span = range.r1 - range.r0 + 1;
    var first = range.to > range.r1 ? range.r1 + 1 : range.to, last = range.to > range.r1 ? range.to : range.r0 - 1;
    mutate(function () {
      for (var r = first; r <= last; r++) {
        var from = view(visible[range.r0 + (((r - range.r0) % span) + span) % span]);
        for (var c = range.c0; c <= range.c1; c++) {
          if (!hidden[FIELDS[c].key]) setField(visible[r], FIELDS[c], from[FIELDS[c].key]);
        }
      }
      selectRange({r: Math.min(range.r0, first), c: range.c0}, {r: Math.max(range.r1, last), c: range.c1});
    });
  }

  // Ctrl+D copies each column's topmost selected cell down its other selected cells.
  function fillDown() {
    var tops = {};
    selectedCells().forEach(function (cell) { if (!(cell.c in tops) || cell.r < tops[cell.c]) tops[cell.c] = cell.r; });
    mutate(function () {
      selectedCells().forEach(function (cell) {
        var col = FIELDS[cell.c];
        if (cell.r !== tops[cell.c]) setField(visible[cell.r], col, view(visible[tops[cell.c]])[col.key]);
      });
    });
  }

  // ---- keyboard -----------------------------------------------------

  wrap.addEventListener('keydown', function (event) {
    if (editing || event.target !== wrap) return;
    var command = event.ctrlKey || event.metaKey, letter = event.key.toLowerCase();
    if (command && letter === 'z') { event.preventDefault(); if (event.shiftKey) redo(); else undo(); return; }
    if (command && letter === 'y') { event.preventDefault(); redo(); return; }
    if (command && letter === 's') { event.preventDefault(); saveAll(); return; }
    if (command && (letter === 'f' || letter === 'h')) { event.preventDefault(); openFind(); return; }
    if (command && letter === 'd') { event.preventDefault(); fillDown(); return; }
    if (command && letter === 'a' && visible.length) {
      event.preventDefault();
      selectRange({r: 0, c: 0}, {r: visible.length - 1, c: FIELDS.length - 1});
      paint();
      return;
    }
    if (!active || command || event.altKey || (active.c !== MATES_COLUMN && hidden[FIELDS[active.c].key])) return;
    var move = {ArrowUp: [-1, 0], ArrowDown: [1, 0], ArrowLeft: [0, -1], ArrowRight: [0, 1]}[event.key];
    if (move) {
      event.preventDefault();
      moveActive(move[0], move[1], event.shiftKey);
    } else if (event.key === 'Tab') {
      event.preventDefault();
      moveActive(0, event.shiftKey ? -1 : 1);
    } else if (event.key === 'Enter' || event.key === 'F2') {
      event.preventDefault();
      startEdit();
    } else if (event.key === 'Escape') {
      selectOnly(active);
      paint();
    } else if (event.key === 'Delete' || event.key === 'Backspace') {
      // Emptying a required cell is allowed; it shows as invalid until it is filled again.
      event.preventDefault();
      mutate(function () {
        selectedCells().forEach(function (cell) { setField(visible[cell.r], FIELDS[cell.c], ''); });
      });
    } else if (event.key.length === 1) {
      // Typing starts an edit with what was typed.
      event.preventDefault();
      startEdit(event.key);
    }
  });

  // ---- copy and paste -----------------------------------------------

  function gridHasFocus() {
    return document.activeElement === wrap && !editing;
  }

  document.addEventListener('copy', function (event) {
    var cells = selectedCells();
    if (!gridHasFocus() || !cells.length) return;
    var box = bounds(cells), lines = [];
    for (var r = box.r0; r <= box.r1; r++) {
      var line = [];
      for (var c = box.c0; c <= box.c1; c++) {
        if (hidden[FIELDS[c].key]) continue;
        line.push(selected[r + '|' + c] ? cellText(FIELDS[c], view(visible[r])) : '');
      }
      lines.push(line.join('\t'));
    }
    event.clipboardData.setData('text/plain', lines.join('\n'));
    event.preventDefault();
  });

  document.addEventListener('paste', function (event) {
    var cells = selectedCells();
    if (!gridHasFocus() || !cells.length) return;
    event.preventDefault();
    var text = event.clipboardData.getData('text/plain').replace(/\r/g, '').replace(/\n$/, '');
    var block = text.split('\n').map(function (line) { return line.split('\t'); });
    var targets = [];
    if (block.length === 1 && block[0].length === 1) {
      // One value fills the whole selection.
      targets = cells.map(function (cell) { return {cell: cell, text: block[0][0]}; });
    } else {
      // A block lands with its top-left corner on the selection's.
      var box = bounds(cells), columns = shownColumns(), left = columns.indexOf(box.c0);
      block.forEach(function (line, i) {
        line.forEach(function (value, j) {
          if (box.r0 + i < visible.length && left + j < columns.length) {
            targets.push({cell: {r: box.r0 + i, c: columns[left + j]}, text: value});
          }
        });
      });
    }
    var skipped = 0;
    mutate(function () {
      selected = {};
      targets.forEach(function (target) {
        var col = FIELDS[target.cell.c];
        selected[target.cell.r + '|' + target.cell.c] = true;
        if (!setField(visible[target.cell.r], col, parsed(col, target.text))) skipped++;
      });
    });
    if (skipped) {
      setStatus(skipped === 1 ? '1 read-only cell was skipped.' : skipped + ' read-only cells were skipped.', true);
    }
  });

  // ---- cell editors -------------------------------------------------

  function closeMenu() {
    if (menu) menu.remove();
    menu = null;
  }

  function placeMenu(anchorEl) {
    var box = anchorEl.getBoundingClientRect();
    menu.style.left = box.left + 'px';
    menu.style.top = box.bottom + 2 + 'px';
    menu.style.minWidth = box.width + 'px';
    document.body.appendChild(menu);
  }

  // Edit the active cell; the value lands in every selected cell of its
  // column. `typed` is the keystroke that opened the editor, if one did.
  function startEdit(typed) {
    if (!active || editing) return;
    if (active.c === MATES_COLUMN) { editMates(typed); return; }
    var col = FIELDS[active.c], column = active.c;
    if (!col.field) return;
    var id = visible[active.r];
    var why = col.locked && col.locked(original[id]);
    if (why) { setStatus(why, true); return; }
    var td = ensureVisible(active);
    if (!td) return;
    var row = view(id), done = false;
    var options = col.all ? (col.options ? col.options(row) : col.all()) : null;
    var input = el('input'), shownOptions = [], current = 0;
    editing = true;

    // `move` is [rows, columns] to step afterwards, as Enter and Tab do.
    function finish(commit, value, move) {
      if (done) return;
      done = true;
      editing = false;
      closeMenu();
      var cells = selectedCells().filter(function (cell) { return cell.c === column; });
      if (commit) mutate(function () { cells.forEach(function (cell) { setField(visible[cell.r], col, value); }); });
      else render();
      wrap.focus({preventScroll: true});
      if (move && cells.length <= 1) moveActive(move[0], move[1]);
    }

    // A choice column filters its list by what is typed.
    function showOptions() {
      closeMenu();
      var needle = input.value.trim().toLowerCase();
      shownOptions = options.filter(function (opt) { return opt[1].toLowerCase().indexOf(needle) !== -1; });
      if (!needle) {
        var at = shownOptions.map(function (opt) { return opt[0]; }).indexOf(row[col.key]);
        current = Math.max(0, at);
      } else {
        current = 0;
      }
      menu = el('div', 'rg-menu');
      if (!shownOptions.length) menu.appendChild(el('div', 'text-muted', 'No match; Enter keeps what you typed.'));
      shownOptions.forEach(function (opt, i) {
        var item = el('div', i === current ? 'rg-active' : '', opt[1]);
        // mousedown, so the pick lands before the input's blur cancels the edit.
        item.addEventListener('mousedown', function (event) { event.preventDefault(); finish(true, opt[0]); });
        menu.appendChild(item);
      });
      placeMenu(td);
      var lit = menu.querySelector('.rg-active');
      if (lit) lit.scrollIntoView({block: 'nearest'});
    }

    function value() {
      if (!options) return input.value;
      if (shownOptions.length) return shownOptions[current][0];
      return parsed(col, input.value);   // nothing matches: keep it, flagged invalid
    }

    if (col.date) {
      input.type = 'date';
      input.value = ISO_DATE.test(row[col.key]) ? row[col.key] : '';
    } else {
      input.type = 'text';
      input.autocomplete = 'off';
      if (options) input.placeholder = shown(col, row) || 'Type to filter';
      else input.value = typed === undefined ? row[col.key] : '';
      if (typed !== undefined) input.value = typed;
    }

    td.classList.add('rg-editing');
    td.textContent = '';
    td.appendChild(input);
    input.focus();
    if (options) {
      showOptions();
      input.addEventListener('input', showOptions);
    }
    // Leaving a choice cancels; leaving a typed value keeps it.
    input.addEventListener('blur', function () { finish(!options, options ? undefined : value()); });
    input.addEventListener('keydown', function (event) {
      event.stopPropagation();
      if (options && (event.key === 'ArrowDown' || event.key === 'ArrowUp') && shownOptions.length) {
        event.preventDefault();
        current = (current + (event.key === 'ArrowDown' ? 1 : shownOptions.length - 1)) % shownOptions.length;
        each(menu.children, function (item, i) { item.classList.toggle('rg-active', i === current); });
        menu.children[current].scrollIntoView({block: 'nearest'});
      } else if (event.key === 'Enter') {
        event.preventDefault();
        finish(true, value(), [event.shiftKey ? -1 : 1, 0]);
      } else if (event.key === 'Tab') {
        event.preventDefault();
        finish(true, value(), [0, event.shiftKey ? -1 : 1]);
      } else if (event.key === 'Escape') {
        event.preventDefault();
        finish(false);
      }
    });
  }

  // ---- roommates ----------------------------------------------------

  function chipButton(symbol, title, action) {
    var button = el('button', '', symbol);
    button.type = 'button';
    button.title = title;
    button.setAttribute('aria-label', title);
    button.addEventListener('click', action);
    return button;
  }

  // Step into the active Roommates cell: the add box takes what is typed,
  // or a full room goes to its last chip.
  function editMates(typed) {
    var td = ensureVisible(active);
    if (!td) return;
    var input = td.querySelector('.rg-add'), chips = td.querySelectorAll('.rg-chip');
    if (input) {
      input.focus();
      if (typed !== undefined) {
        input.value = typed;
        input.dispatchEvent(new Event('input'));
      }
    } else if (chips.length) {
      chips[chips.length - 1].focus();
      setStatus('This room is full; remove a roommate to add another.', true);
    }
  }

  function backToGrid(move) {
    wrap.focus({preventScroll: true});
    if (move) moveActive(move[0], move[1]);
  }

  // A focused chip: arrows walk the chips, Delete removes, L makes leader.
  function chipKeys(chip, td) {
    chip.tabIndex = -1;
    chip.addEventListener('keydown', function (event) {
      if (event.target !== chip) return;
      event.stopPropagation();
      var chips = Array.prototype.slice.call(td.querySelectorAll('.rg-chip')), at = chips.indexOf(chip);
      var buttons = chip.querySelectorAll('button');   // [make leader, remove]; the leader has neither
      if (event.key === 'ArrowLeft' && at > 0) chips[at - 1].focus();
      else if (event.key === 'ArrowRight' || event.key === 'Enter') {
        var next = chips[at + 1] || td.querySelector('.rg-add');
        if (next && event.key !== 'Enter') next.focus();
        else if (td.querySelector('.rg-add')) td.querySelector('.rg-add').focus();
      } else if (event.key === 'Delete' || event.key === 'Backspace') {
        if (buttons.length) buttons[1].click();
        else setStatus('The room leader cannot be removed; make someone else the leader first.', true);
      } else if (event.key.toLowerCase() === 'l' || event.key === '*') {
        if (buttons.length) { buttons[0].click(); backToGrid(); }
      } else if (event.key === 'Escape') backToGrid();
      else if (event.key === 'Tab') backToGrid([0, event.shiftKey ? -1 : 1]);
      else return;
      event.preventDefault();
    });
  }

  function roommateCell(row, r) {
    var edit = pending[row.id] || {};
    var dirty = (edit.add || []).length || (edit.remove || []).length || edit.leader;
    var td = el('td', 'rg-mates' + (dirty ? ' rg-dirty' : ''));
    td.dataset.col = 'mates';
    td.dataset.r = r;
    td.title = row.occupants.map(function (o) { return o.name; }).join(', ');
    var inner = td.appendChild(el('div', 'rg-mates-inner'));
    var chips = inner.appendChild(el('div', 'rg-chips'));
    var addBox = 'tr[data-id="' + row.id + '"] .rg-add';
    row.occupants.forEach(function (person) {
      var leader = person.id === row.leader_id;
      var chip = el('span', 'rg-chip' + (leader ? ' rg-leader' : '') + (person.staged ? ' rg-new' : ''));
      if (leader) chip.appendChild(el('span', '', '★'));
      chip.appendChild(el('span', '', person.name));
      if (!leader) {
        chip.appendChild(chipButton('☆', 'Make ' + person.name + ' the room leader', function () {
          mutate(function () { stage(row.id).leader = person.id === original[row.id].leader_id ? '' : person.id; });
          if (original[row.id].has_card && person.id !== original[row.id].leader_id) {
            setStatus('Saving will reset the payment information on this room; ' + person.name +
                      ' will need to secure it with their own card.', true);
          }
        }));
        chip.appendChild(chipButton('×', 'Remove ' + person.name, function () {
          mutate(function () {
            var staged = stage(row.id);
            if (person.staged) staged.add = staged.add.filter(function (o) { return o.id !== person.id; });
            else staged.remove.push(person.id);
          }, addBox);
        }));
      }
      chipKeys(chip, td);
      chips.appendChild(chip);
    });
    // Clicking or tabbing into the cell makes it the active one.
    td.addEventListener('focusin', function () {
      if (active && active.c === MATES_COLUMN && active.r === r) return;
      selectOnly({r: r, c: MATES_COLUMN});
      paint();
    });
    td.addEventListener('mousedown', function (event) {
      if (event.target.closest('button, input')) return;
      selectOnly({r: r, c: MATES_COLUMN});
      paint();
      wrap.focus({preventScroll: true});
      event.preventDefault();
    });

    // The add box and the count sit outside the chips, so a full room's chips can't push them out of the cell.
    if (!row.capacity || row.occupants.length < row.capacity) inner.appendChild(addInput(row, addBox));
    if (row.capacity) {
      var over = row.occupants.length > row.capacity;
      inner.appendChild(el('span', 'rg-count' + (over ? ' rg-over' : ''), row.occupants.length + '/' + row.capacity));
    }
    return td;
  }

  function addInput(row, addBox) {
    var input = el('input', 'rg-add');
    input.type = 'text';
    input.placeholder = '+ roommate';
    input.autocomplete = 'off';
    input.setAttribute('aria-label', 'Add a roommate');
    var timer = null, results = [], current = 0, latest = '';

    function show() {
      closeMenu();
      menu = el('div', 'rg-menu');
      if (!results.length) menu.appendChild(el('div', 'text-muted', 'No eligible attendees match.'));
      results.forEach(function (person, i) {
        var item = el('div', i === current ? 'rg-active' : '', person.name);
        item.appendChild(el('small', '', [person.email, person.badge_type].filter(Boolean).join(' · ')));
        // mousedown, so the pick lands before the input's blur closes the menu.
        item.addEventListener('mousedown', function (event) { event.preventDefault(); pick(person); });
        menu.appendChild(item);
      });
      placeMenu(input);
    }

    function pick(person) {
      closeMenu();
      mutate(function () { stage(row.id).add.push({id: person.id, name: person.name, badge: person.badge_type}); }, addBox);
    }

    function search() {
      var term = input.value.trim();
      latest = term;
      if (term.length < 2) { closeMenu(); return; }
      fetch('grid_search_roommates?id=' + encodeURIComponent(row.id) + '&q=' + encodeURIComponent(term), {credentials: 'same-origin'})
        .then(function (r) { return r.json(); })
        .then(function (found) {
          if (term !== latest || document.activeElement !== input) return;
          var here = row.occupants.map(function (o) { return o.id; });
          results = (found || []).filter(function (person) { return here.indexOf(person.id) === -1; });
          current = 0;
          show();
        })
        .catch(closeMenu);
    }

    input.addEventListener('input', function () {
      clearTimeout(timer);
      timer = setTimeout(search, 200);
    });
    input.addEventListener('blur', function () {
      clearTimeout(timer);
      latest = '';
      closeMenu();
      redrawIfScrolled();
    });
    input.addEventListener('keydown', function (event) {
      event.stopPropagation();
      var empty = !input.value;
      if (event.key === 'Escape') {
        // Once to clear what was typed, again to leave the cell.
        input.value = ''; latest = ''; closeMenu();
        if (empty) backToGrid();
        return;
      }
      if (event.key === 'Tab') { event.preventDefault(); backToGrid([0, event.shiftKey ? -1 : 1]); return; }
      if (event.key === 'ArrowLeft' && empty) {
        var chips = input.closest('td').querySelectorAll('.rg-chip');
        if (chips.length) { event.preventDefault(); chips[chips.length - 1].focus(); }
        return;
      }
      if (!menu || !results.length) return;
      if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
        event.preventDefault();
        current = (current + (event.key === 'ArrowDown' ? 1 : results.length - 1)) % results.length;
        show();
      }
      if (event.key === 'Enter') { event.preventDefault(); pick(results[current]); }
    });
    return input;
  }

  // ---- rendering ----------------------------------------------------

  function renderRow(id, r) {
    var row = view(id), saved = original[id];
    var tr = el('tr', offsets[r + 1] - offsets[r] > LINE ? 'rg-tall' : '');
    if (tr.className) tr.style.setProperty('--rg-h', offsets[r + 1] - offsets[r] + 'px');
    tr.dataset.id = id;
    var number = el('td', 'rg-num', r + 1);
    number.title = 'Select this row';
    number.addEventListener('click', function (event) {
      // Shift extends from the last row picked, as with cells.
      var from = event.shiftKey && anchor ? anchor.r : r;
      selectRange({r: from, c: 0}, {r: r, c: FIELDS.length - 1}, event.ctrlKey || event.metaKey);
      if (!event.shiftKey || !anchor) anchor = {r: r, c: 0};
      active = {r: r, c: shownColumns()[0] || 0};
      paint();
      wrap.focus({preventScroll: true});
    });
    tr.appendChild(number);
    tr.appendChild(roommateCell(row, r));
    FIELDS.forEach(function (col, c) {
      var text = shown(col, row);
      var td = el('td', 'rg-edit' + (row[col.key] !== saved[col.key] ? ' rg-dirty' : '') +
                  (!col.field ? ' rg-readonly' : (col.locked && col.locked(saved) ? ' rg-locked' : '')) +
                  (flagged(col, row) ? ' rg-invalid' : '') +
                  (hidden[col.key] ? ' rg-hidden' : ''), col.link ? undefined : text);
      td.dataset.r = r;
      td.dataset.c = c;
      td.dataset.col = col.key;
      td.title = text;
      if (col.link && text) {
        var link = el('a', '', text);
        link.href = '#';
        link.title = col.linkTitle;
        link.addEventListener('click', function (event) { event.preventDefault(); col.link(row); });
        td.appendChild(link);
      }
      tr.appendChild(td);
    });
    return tr;
  }

  function markIssues() {
    var worst = {};
    issues.forEach(function (issue) {
      if (issue.row_id && worst[issue.row_id] !== 'error') worst[issue.row_id] = issue.severity;
    });
    each(tbody.rows, function (tr) {
      tr.classList.toggle('rg-has-error', worst[tr.dataset.id] === 'error');
      tr.classList.toggle('rg-has-warning', worst[tr.dataset.id] === 'warning');
    });
  }

  function renderIssues() {
    issuesEl.textContent = '';
    issuesEl.hidden = !issues.length;
    fitHeight();
    issues.forEach(function (issue) {
      var item = el('li', issue.severity === 'error' ? 'rg-error' : '', (issue.room ? issue.room + ': ' : '') + issue.text);
      if (issue.row_id) {
        item.addEventListener('click', function () {
          var r = visible.indexOf(issue.row_id);
          if (r === -1) { setStatus('That room is hidden by the current filters.', true); return; }
          selectRange({r: r, c: 0}, {r: r, c: FIELDS.length - 1});
          anchor = active = {r: r, c: shownColumns()[0] || 0};
          ensureVisible(active);
          paint();
          wrap.focus({preventScroll: true});
        });
      }
      issuesEl.appendChild(item);
    });
    markIssues();
  }

  // Size the grid to end at the bottom of the window, whatever sits above it.
  function fitHeight() {
    var top = wrap.getBoundingClientRect().top + window.scrollY;
    wrap.style.maxHeight = Math.max(240, window.innerHeight - top - 36) + 'px';
  }

  function render(focusSelector) {
    closeMenu();
    fitHeight();
    if (!findEl.hidden) findMatches();
    measureRows();
    drawRows();
    renderIssues();
    var changed = Object.keys(pending).length;
    countEl.textContent = changed ? changed + ' room' + (changed === 1 ? '' : 's') + ' with unsaved changes' : 'No unsaved changes';
    shownEl.textContent = visible.length === order.length ? order.length + ' rooms' : visible.length + ' of ' + order.length + ' rooms';
    saveBtn.disabled = discardBtn.disabled = !changed;
    undoBtn.disabled = !undoStack.length;
    redoBtn.disabled = !redoStack.length;
    var target = focusSelector && tbody.querySelector(focusSelector);
    if (target) target.focus();
  }

  // ---- find and replace ---------------------------------------------

  // Matches are found in the row data, not the drawn cells, so rows that
  // are scrolled out of sight count too.
  var findList = [], findAt = -1;

  function findColumns() {
    var only = findEl.querySelector('[name=column]').value;
    return shownColumns().filter(function (c) { return FIELDS[c].key !== 'open' && (!only || FIELDS[c].key === only); });
  }

  function findMatches() {
    var needle = findEl.querySelector('[name=find]').value.toLowerCase();
    findList = [];
    found = {};
    if (needle) {
      var columns = findColumns();
      visible.forEach(function (id, r) {
        var row = view(id);
        columns.forEach(function (c) {
          if (shownOrText(FIELDS[c], row).toLowerCase().indexOf(needle) !== -1) {
            findList.push({r: r, c: c});
            found[r + '|' + c] = true;
          }
        });
      });
    }
    if (findAt >= findList.length) findAt = findList.length - 1;
    findCountEl.textContent = !needle ? '' : (findList.length ? (findAt + 1 || '-') + ' of ' + findList.length : 'No matches');
  }

  // Find looks at what the cell shows, and at the stored value too (so an ISO date matches either way).
  function shownOrText(col, row) {
    return col.link && col.key !== 'open' ? String(row[col.key] || '') : shown(col, row) + '\n' + cellText(col, row);
  }

  function findStep(by) {
    findMatches();
    if (!findList.length) { paint(); return; }
    findAt = (findAt + by + findList.length) % findList.length;
    selectOnly(findList[findAt]);
    ensureVisible(active);
    paint();
    findCountEl.textContent = (findAt + 1) + ' of ' + findList.length;
  }

  // A text cell has the found text swapped out; a choice or a date is replaced whole.
  function replaced(col, row) {
    var needle = findEl.querySelector('[name=find]').value, swap = findEl.querySelector('[name=replace]').value;
    if (col.all || col.date) return parsed(col, swap);
    var escaped = needle.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    return String(row[col.key] || '').replace(new RegExp(escaped, 'gi'), function () { return swap; });
  }

  function replaceMatches(list) {
    var skipped = 0;
    mutate(function () {
      list.forEach(function (match) {
        var col = FIELDS[match.c], id = visible[match.r];
        if (!setField(id, col, replaced(col, view(id)))) skipped++;
      });
    });
    setStatus('Replaced ' + (list.length - skipped) + (skipped ? '; ' + skipped + ' read-only skipped.' : '.'), !!skipped);
  }

  function openFind() {
    var picker = findEl.querySelector('[name=column]');
    var keep = picker.value || (active ? FIELDS[active.c].key : '');
    picker.textContent = '';
    picker.add(new Option('All columns', ''));
    shownColumns().forEach(function (c) {
      if (FIELDS[c].key !== 'open') picker.add(new Option(FIELDS[c].label, FIELDS[c].key, false, FIELDS[c].key === keep));
    });
    findEl.hidden = false;
    fitHeight();
    var box = findEl.querySelector('[name=find]');
    box.focus();
    box.select();
    findMatches();
    paint();
  }

  function closeFind() {
    findEl.hidden = true;
    fitHeight();
    findList = [];
    found = {};
    findAt = -1;
    paint();
    wrap.focus({preventScroll: true});
  }

  findEl.addEventListener('input', function () { findAt = -1; findMatches(); paint(); });
  findEl.addEventListener('keydown', function (event) {
    var command = event.ctrlKey || event.metaKey;
    if (event.key === 'Escape') { event.preventDefault(); closeFind(); }
    else if (event.key === 'Enter' && event.target.name === 'find') { event.preventDefault(); findStep(event.shiftKey ? -1 : 1); }
    else if (event.key === 'Enter' && event.target.name === 'replace') { event.preventDefault(); findEl.querySelector('[data-find=replace]').click(); }
    else if (command && event.key.toLowerCase() === 'f') { event.preventDefault(); findEl.querySelector('[name=find]').select(); }
  });
  findEl.addEventListener('click', function (event) {
    var action = event.target.dataset.find;
    if (action === 'next') findStep(1);
    else if (action === 'prev') findStep(-1);
    else if (action === 'close') closeFind();
    else if (action === 'all') { findMatches(); if (findList.length) replaceMatches(findList.slice()); }
    else if (action === 'replace') {
      if (findAt === -1) { findStep(1); return; }
      findMatches();
      if (!findList[findAt]) return;
      replaceMatches([findList[findAt]]);
      findAt--;
      findStep(1);
    }
  });
  document.getElementById('rg-find-open').addEventListener('click', openFind);

  // ---- CSV export ---------------------------------------------------

  // The rows and columns on screen, staged edits included.
  document.getElementById('rg-export').addEventListener('click', function () {
    var columns = shownColumns().filter(function (c) { return FIELDS[c].key !== 'open'; });
    var quote = function (text) {
      text = String(text === undefined || text === null ? '' : text);
      return /[",\n\r]/.test(text) ? '"' + text.replace(/"/g, '""') + '"' : text;
    };
    var lines = [['Room leader', 'Roommates'].concat(columns.map(function (c) { return FIELDS[c].label; }))];
    visible.forEach(function (id) {
      var row = view(id), names = row.occupants.map(function (o) { return o.name; });
      lines.push([names[0] || '', names.slice(1).join('; ')].concat(
        columns.map(function (c) { return cellText(FIELDS[c], row); })));
    });
    var csv = '﻿' + lines.map(function (line) { return line.map(quote).join(','); }).join('\r\n');
    var link = el('a');
    link.href = URL.createObjectURL(new Blob([csv], {type: 'text/csv'}));
    link.download = 'staff-rooms-' + new Date().toISOString().slice(0, 10) + '.csv';
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(function () { URL.revokeObjectURL(link.href); }, 1000);
    var unsaved = Object.keys(pending).length;
    setStatus('Exported ' + visible.length + ' rows' + (unsaved ? ', including unsaved changes.' : '.'));
  });

  // ---- summary -----------------------------------------------------

  // Totals for the rows the filters leave, staged edits included.
  var summaryModal = document.getElementById('rg-summary-modal');
  var summaryBody = summaryModal.querySelector('.modal-body');
  var summarySplit = summaryModal.querySelector('[name=split]');

  function partitionOf(row) {
    return row.partition_id ? labelOf(column('partition_id'), row.partition_id) || row.partition_id : '(No partition)';
  }

  function nightsOf(row) {
    var nights = [];
    if (!ISO_DATE.test(row.check_in) || !ISO_DATE.test(row.check_out)) return nights;
    var day = new Date(row.check_in + 'T12:00:00'), end = new Date(row.check_out + 'T12:00:00');
    for (var guard = 0; day < end && guard < 60; guard++) {
      nights.push(day.toISOString().slice(0, 10));
      day.setDate(day.getDate() + 1);
    }
    return nights;
  }

  function buildSummary() {
    var rows = visible.map(view);
    var split = summarySplit.checked;
    var groups = [];
    if (split) {
      rows.forEach(function (row) { if (groups.indexOf(partitionOf(row)) === -1) groups.push(partitionOf(row)); });
      groups.sort(function (a, b) { return a.localeCompare(b); });
    }
    summaryBody.textContent = '';

    var people = 0, roomNights = 0;
    rows.forEach(function (row) {
      people += row.occupants.length;
      roomNights += nightsOf(row).length;
    });
    var tiles = summaryBody.appendChild(el('div', 'd-flex flex-wrap gap-4 mb-3'));
    [['Rooms', rows.length], ['Roommates', people], ['Room-nights', roomNights]].forEach(function (pair) {
      var tile = tiles.appendChild(el('div'));
      tile.appendChild(el('div', 'fs-4 fw-bold', pair[1].toLocaleString()));
      tile.appendChild(el('div', 'small text-muted', pair[0]));
    });

    // One table: a line per key, counting rooms (and their roommates), with
    // a column per partition when splitting. A room can count under several
    // keys, as it does for each night it is held.
    function tableOf(title, keysOf, labelFor, totalRow) {
      var counts = {}, mates = {};
      rows.forEach(function (row) {
        keysOf(row).forEach(function (key) {
          counts[key] = counts[key] || {};
          counts[key][partitionOf(row)] = (counts[key][partitionOf(row)] || 0) + 1;
          counts[key].total = (counts[key].total || 0) + 1;
          mates[key] = (mates[key] || 0) + row.occupants.length;
        });
      });
      var keys = Object.keys(counts).sort(function (a, b) { return a.localeCompare(b); });
      if (!keys.length) return;
      var holder = grid.appendChild(el('div'));
      var tbl = holder.appendChild(el('table', 'table table-sm table-bordered small mb-0 w-auto'));
      var headRow = tbl.appendChild(el('thead')).appendChild(el('tr'));
      headRow.appendChild(el('th', '', title));
      groups.forEach(function (group) { headRow.appendChild(el('th', 'text-end', group)); });
      headRow.appendChild(el('th', 'text-end', 'Rooms'));
      if (!split) headRow.appendChild(el('th', 'text-end', 'Roommates'));
      var body = tbl.appendChild(el('tbody')), sums = {total: 0, mates: 0};
      keys.forEach(function (key) {
        var tr = body.appendChild(el('tr'));
        tr.appendChild(el('td', '', labelFor ? labelFor(key) : key || '(blank)'));
        groups.forEach(function (group) {
          tr.appendChild(el('td', 'text-end', counts[key][group] || ''));
          sums[group] = (sums[group] || 0) + (counts[key][group] || 0);
        });
        tr.appendChild(el('td', 'text-end fw-bold', counts[key].total));
        if (!split) tr.appendChild(el('td', 'text-end', mates[key]));
        sums.total += counts[key].total;
        sums.mates += mates[key];
      });
      if (totalRow) {
        var foot = tbl.appendChild(el('tfoot')).appendChild(el('tr', 'fw-bold'));
        foot.appendChild(el('td', '', 'Total'));
        groups.forEach(function (group) { foot.appendChild(el('td', 'text-end', sums[group] || 0)); });
        foot.appendChild(el('td', 'text-end', sums.total));
        if (!split) foot.appendChild(el('td', 'text-end', sums.mates));
      }
    }

    var grid = summaryBody.appendChild(el('div', 'd-flex flex-wrap gap-4 align-items-start'));
    var by = function (key) { return function (row) { return [cellText(column(key), row)]; }; };
    tableOf('Inventory block', by('inventory_id'), null, true);
    tableOf('Room type', by('room_type'), null, true);
    if (!split) tableOf('Partition', function (row) { return [partitionOf(row)]; }, null, true);
    tableOf('Night', nightsOf, function (iso) { return fmtDate(iso) + ', ' + iso.slice(0, 4); }, false);
    tableOf('Billing', by('payment_type'), null, true);
    tableOf('Source', by('assignment_reason'), null, true);
    tableOf('Status', by('status'), null, true);
    tableOf('Leader badge', by('leader_badge'), null, true);
    tableOf('Roommates in room', function (row) { return [String(row.occupants.length)]; }, null, true);

    summaryModal.querySelector('.rg-summary-scope').textContent =
      (visible.length === order.length ? 'All ' + order.length + ' rooms' : visible.length + ' of ' + order.length + ' rooms (filtered)') +
      (Object.keys(pending).length ? ', including unsaved changes' : '');
  }

  document.getElementById('rg-summary-open').addEventListener('click', function () {
    buildSummary();
    bootstrap.Modal.getOrCreateInstance(summaryModal).show();
  });
  summarySplit.addEventListener('change', buildSummary);

  // ---- column chooser -----------------------------------------------

  function buildChooser() {
    chooserEl.textContent = '';
    var freeze = el('label', 'd-block text-nowrap mb-2', 'Freeze first ');
    var count = freeze.appendChild(el('input'));
    count.type = 'number';
    count.min = 0;
    count.max = FIELDS.length;
    count.value = frozen;
    count.style.width = '3.5em';
    freeze.appendChild(document.createTextNode(' columns'));
    count.addEventListener('input', function () {
      frozen = Math.max(0, Math.min(FIELDS.length, +count.value || 0));
      saveConfig();
      layout();
    });
    chooserEl.appendChild(freeze);

    // Roommates identifies the row, so it is not on the list.
    FIELDS.forEach(function (col) {
      var label = el('label', 'form-check d-block text-nowrap');
      var box = el('input', 'form-check-input');
      box.type = 'checkbox';
      box.checked = !hidden[col.key];
      box.addEventListener('change', function () {
        if (box.checked) delete hidden[col.key]; else hidden[col.key] = true;
        chosen[col.key] = box.checked;
        delete colFilters[col.key];   // a hidden column must not keep filtering unseen
        columnsChanged();
        refilter();
      });
      label.appendChild(box);
      label.appendChild(document.createTextNode(' ' + (col.name || col.label)));
      chooserEl.appendChild(label);
    });
  }

  // ---- full room form ---------------------------------------------

  // The full form is the lottery admin's own page in a frame, minus its
  // navigation. `map` goes straight to the form's floor-map room picker,
  // where the hotel has a map.
  var frame = roomModal.querySelector('iframe'), openId = null, wantMap = false;

  function openRoom(id, href, map) {
    openId = id;
    wantMap = !!map;
    frame.src = href;
    bootstrap.Modal.getOrCreateInstance(roomModal).show();
  }

  frame.addEventListener('load', function () {
    var doc;
    try { doc = frame.contentDocument; } catch (e) { return; }
    if (!doc || !doc.head) return;
    var style = doc.createElement('style');
    style.textContent = 'nav, ul.nav-tabs, ul.nav-pills, footer { display: none !important; }';
    doc.head.appendChild(style);
    var picker = wantMap && doc.querySelector('.room-map-open');
    wantMap = false;
    if (picker) picker.click();
  });

  // Whatever was saved in the form shows up in the grid once it closes.
  roomModal.addEventListener('hidden.bs.modal', function () {
    var id = openId;
    openId = null;
    frame.src = 'about:blank';
    if (!id) return;
    fetch('grid_rows?ids=' + encodeURIComponent(id), {credentials: 'same-origin'})
      .then(function (r) { return r.json(); })
      .then(function (fresh) {
        if (fresh.length && fresh[0].live) original[id] = fresh[0];
        else dropRow(id);
        render();
        scheduleCheck();
      })
      .catch(function () { setStatus('Could not refresh that room. Reload the page.', true); });
  });

  // ---- toolbar ------------------------------------------------------

  saveBtn.addEventListener('click', saveAll);
  undoBtn.addEventListener('click', undo);
  redoBtn.addEventListener('click', redo);
  discardBtn.addEventListener('click', function () {
    undoStack.push(JSON.stringify(pending));
    redoStack = [];
    pending = {};
    issues = [];
    checkSeq++;
    setStatus('Changes discarded. Undo brings them back.');
    render();
  });
  window.addEventListener('beforeunload', function (event) {
    if (Object.keys(pending).length) { event.preventDefault(); event.returnValue = ''; }
  });
  window.addEventListener('resize', function () { fitHeight(); redrawIfScrolled(); });

  // ---- start --------------------------------------------------------

  data.rows.forEach(function (row) { order.push(row.id); original[row.id] = row; });
  buildHeader();
  orderHeader();
  layout();
  buildChooser();
  refilter();
})();
