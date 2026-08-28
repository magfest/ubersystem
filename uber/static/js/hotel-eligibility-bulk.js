// Bulk hotel-eligibility selection glue for
// staff_rooming/hotel_eligibility.html: wires the row checkboxes and
// select-all box to the standalone hidden bulk form and submits it
// with the chosen eligible value.
(function () {
  var form = document.getElementById('bulk-eligibility-form');
  if (!form) return;
  var idsInput   = document.getElementById('bulk-ids-value');
  var eligibleInput = document.getElementById('bulk-eligible-value');
  var selAll     = document.getElementById('bulk-select-all');
  var countLabel = document.getElementById('bulk-selected-count');
  // Checkboxes live in the table, outside the bulk form, so query the
  // whole document rather than `form`.
  var rowChecks  = document.querySelectorAll('.bulk-row-check');

  function updateIds() {
    var ids = [];
    rowChecks.forEach(function (cb) { if (cb.checked) ids.push(cb.value); });
    idsInput.value = ids.join(',');
    countLabel.textContent = ids.length;
    return ids.length;
  }

  rowChecks.forEach(function (cb) {
    cb.addEventListener('change', updateIds);
  });
  if (selAll) {
    selAll.addEventListener('change', function () {
      rowChecks.forEach(function (cb) { cb.checked = selAll.checked; });
      updateIds();
    });
  }

  // Which of the two eligibility flags this bulk action targets.
  var fieldInput = document.getElementById('bulk-field-value');

  function submitBulk(field, value) {
    if (updateIds() === 0) {
      alert('No staffers selected.');
      return;
    }
    if (fieldInput) { fieldInput.value = field; }
    eligibleInput.value = value;
    form.submit();
  }

  document.querySelectorAll('.bulk-set').forEach(function (button) {
    button.addEventListener('click', function () {
      submitBulk(button.dataset.field, button.dataset.eligible);
    });
  });

  updateIds();
})();
