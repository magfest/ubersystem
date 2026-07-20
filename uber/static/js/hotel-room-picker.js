// Shared JS for the hotel section's room pickers, plus the escapeHtml
// helper used by pages that build DOM from AJAX responses.
//
// Load via:  {{ "js/hotel-room-picker.js"|serve_static_content }}
//
// Partition->inventory cascade shared by every room picker: the
// form-page modals, the standalone assignment editor, and the manual
// assign_room page.
//
// Convention: each picker sits inside a <form> containing exactly one
// .room-picker-partition <select> and one .room-picker-inventory
// <select>. Each inventory <option> carries:
//   data-partitions - comma-separated partition ids the block is
//                     allocated to; an option with none is always shown
//                     (the unrestricted inventory blocks).
//   data-avail      - OPTIONAL JSON map of scope -> available count,
//                     keyed '' for the main (unpartitioned) pool and by
//                     partition id otherwise. When present (with
//                     data-label) the option text appends
//                     "(N available)" for the chosen scope.
//   data-label      - the option's base text, required with data-avail.

function escapeHtml(str) {
    var div = document.createElement('div');
    div.appendChild(document.createTextNode(str));
    return div.innerHTML;
}

(function () {
  function filterPicker(form) {
    var partitionSel = form.querySelector('.room-picker-partition');
    var inventorySel = form.querySelector('.room-picker-inventory');
    if (!partitionSel || !inventorySel) return;

    var chosen = partitionSel.value || '';
    var selectedStillValid = false;
    var selectedValue = inventorySel.value;

    Array.prototype.forEach.call(inventorySel.options, function (opt) {
      if (!opt.value) {
        opt.hidden = false;  // keep the placeholder
        return;
      }
      var raw = opt.getAttribute('data-partitions') || '';
      var partitions = raw ? raw.split(',') : [];
      // No partition picked -> every block; picked -> only its blocks.
      var allowed = !chosen || partitions.indexOf(chosen) !== -1;
      opt.hidden = !allowed;
      opt.disabled = !allowed;

      var availRaw = opt.getAttribute('data-avail');
      if (availRaw) {
        var avail = {};
        try { avail = JSON.parse(availRaw); } catch (e) { /* leave label */ }
        var n = avail[chosen];
        var base = opt.getAttribute('data-label') || opt.textContent;
        opt.textContent = (n === undefined)
            ? base
            : base + ' (' + n + ' available)';
      }

      if (opt.value === selectedValue && allowed) selectedStillValid = true;
    });

    if (!selectedStillValid) {
      inventorySel.value = '';
    }
  }

  document.querySelectorAll('.room-picker-partition').forEach(function (sel) {
    var form = sel.closest('form');
    if (!form) return;
    sel.addEventListener('change', function () { filterPicker(form); });
    filterPicker(form);  // initial pass
  });
})();
