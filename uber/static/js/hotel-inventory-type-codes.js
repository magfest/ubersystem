// Checkbox dropdown for the physical-room-types field on the Edit
// Inventory Item page.
//
// Load via:  {{ "js/hotel-inventory-type-codes.js"|serve_static_content }}
//
// The text input stays the source of truth (comma-separated codes,
// arbitrary text allowed); the dropdown just offers the catalog's
// known codes for the currently selected hotel as checkboxes.
// #type-codes-data supplies {hotel_id: [code, ...]}.
(function () {
  var input = document.getElementById('physical_room_types');
  var menu = document.getElementById('type-code-menu');
  var hotelSelect = document.getElementById('hotel_id');
  var dataEl = document.getElementById('type-codes-data');
  if (!input || !menu || !dataEl) return;

  var codesByHotel = JSON.parse(dataEl.textContent || '{}');

  function tokens() {
    return input.value.split(',')
        .map(function (t) { return t.trim(); })
        .filter(Boolean);
  }

  function toggle(code, on) {
    var kept = tokens().filter(function (t) {
      return t.toUpperCase() !== code.toUpperCase();
    });
    if (on) kept.push(code);
    input.value = kept.join(', ');
  }

  function syncChecks() {
    var current = new Set(tokens().map(function (t) {
      return t.toUpperCase();
    }));
    menu.querySelectorAll('input[type=checkbox]').forEach(function (box) {
      box.checked = current.has(box.value.toUpperCase());
    });
  }

  function render() {
    var codes = codesByHotel[hotelSelect ? hotelSelect.value : ''] || [];
    menu.replaceChildren();
    if (!codes.length) {
      var li = document.createElement('li');
      li.className = 'dropdown-item-text text-muted small';
      li.textContent = 'No catalog type codes for this hotel yet.';
      menu.appendChild(li);
      return;
    }
    codes.forEach(function (code) {
      var li = document.createElement('li');
      var label = document.createElement('label');
      label.className = 'dropdown-item d-flex gap-2 align-items-center mb-0';
      var box = document.createElement('input');
      box.type = 'checkbox';
      box.className = 'form-check-input m-0';
      box.value = code;
      box.addEventListener('change', function () {
        toggle(code, box.checked);
      });
      label.appendChild(box);
      label.appendChild(document.createTextNode(code));
      li.appendChild(label);
      menu.appendChild(li);
    });
    syncChecks();
  }

  input.addEventListener('input', syncChecks);
  if (hotelSelect) hotelSelect.addEventListener('change', render);
  render();
})();
