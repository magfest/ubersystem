// Grays out room types that no currently-selected hotel offers, and explains
// why underneath the ranking. Grayed types stay fully selectable: an entrant
// may want one anticipating they will also pick a hotel that has it. Only
// selecting nothing BUT unavailable types is blocked, and that check lives
// server-side in uber.validations.hotel_lottery.

(function () {
  var config = window.hotelAvailabilityConfig || {};

  var PAIRS = [
    {typeField: 'room_type_preference', map: config.room || {}},
    {typeField: 'suite_type_preference', map: config.suite || {}},
  ];

  function selectedIds(fieldId) {
    var list = document.getElementById('selected_' + fieldId);
    if (!list) { return []; }
    return Array.from(list.children).map(function (li) { return li.dataset.choice; });
  }

  function availableTypes(hotelIds, map) {
    var out = {};
    hotelIds.forEach(function (hotelId) {
      (map[hotelId] || []).forEach(function (typeId) { out[typeId] = true; });
    });
    return out;
  }

  function typeName(typeId) {
    return (config.type_names || {})[typeId] || 'this room type';
  }

  function refresh(pair) {
    var lists = ['selected_' + pair.typeField, 'deselected_' + pair.typeField]
      .map(function (id) { return document.getElementById(id); })
      .filter(Boolean);
    if (!lists.length) { return; }

    var hotelIds = selectedIds('hotel_preference');
    var warning = document.getElementById(pair.typeField + '-availability-warning');

    // With no hotels chosen yet there is nothing to be unavailable at, so
    // leave everything ungrayed rather than graying the whole list.
    if (!hotelIds.length) {
      lists.forEach(function (list) {
        Array.from(list.children).forEach(function (li) {
          li.classList.remove('ranking-unavailable');
        });
      });
      if (warning) { warning.textContent = ''; }
      return;
    }

    var available = availableTypes(hotelIds, pair.map);
    var unavailableSelected = [];

    lists.forEach(function (list) {
      var isSelectedList = list.id.indexOf('selected_') === 0;
      Array.from(list.children).forEach(function (li) {
        var typeId = li.dataset.choice;
        var missing = !available[typeId];
        li.classList.toggle('ranking-unavailable', missing);
        if (missing && isSelectedList) {
          unavailableSelected.push(typeName(typeId));
        }
      });
    });

    if (!warning) { return; }
    if (!unavailableSelected.length) {
      warning.textContent = '';
      return;
    }
    warning.textContent =
      'Not available at the hotels you selected: ' + unavailableSelected.join(', ') +
      '. You can still rank these, but they will only be considered if you add a ' +
      'hotel that offers them.';
  }

  function refreshAll() { PAIRS.forEach(refresh); }

  document.addEventListener('sortableext:change', function (e) {
    var id = e.detail && e.detail.id;
    if (id === 'hotel_preference') {
      refreshAll();
      return;
    }
    PAIRS.forEach(function (pair) {
      // Re-run for the type list too, so a newly dragged item picks up its
      // styling right away.
      if (id === pair.typeField) { refresh(pair); }
    });
  });

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', refreshAll);
  } else {
    refreshAll();
  }
})();
