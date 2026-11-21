// Per-hotel export-details modal glue for
// hotel_lottery_admin/export_tracking.html: loads the paginated
// details partial into the modal, wires the export/import buttons to
// the hotel picked from the table, and reloads when the pending-only
// filter changes.
(function () {
  var modalEl       = document.getElementById('hotel-export-details-modal');
  var modalLabel    = document.getElementById('hotel-export-details-modal-label');
  var modalBody     = document.getElementById('hotel-export-details-body');
  var pendingOnly   = document.getElementById('hotel-export-pending-only');
  if (!modalEl) return;

  var csvBtn         = document.getElementById('hotel-export-csv-btn');
  var xlsxBtn        = document.getElementById('hotel-export-xlsx-btn');
  var importToggle   = document.getElementById('hotel-import-toggle-btn');
  var importForm     = document.getElementById('hotel-import-form');
  var importCancel   = document.getElementById('hotel-import-cancel-btn');
  var importHotelId  = document.getElementById('hotel-import-hotel-id');

  importToggle.addEventListener('click', function () {
    importForm.style.display = (importForm.style.display === 'none') ? '' : 'none';
  });
  importCancel.addEventListener('click', function () {
    importForm.style.display = 'none';
  });

  // Currently-open hotel id, so pagination links know what to ask for.
  var currentHotelId = null;

  function loadPage(hotelId, page) {
    modalBody.innerHTML =
      '<div class="text-center text-muted py-5">' +
      '<div class="spinner-border" role="status" aria-hidden="true"></div>' +
      '<p class="mt-2 mb-0">Loading...</p></div>';

    var url = 'hotel_export_details?hotel_id=' + encodeURIComponent(hotelId)
            + '&page=' + encodeURIComponent(page || 1)
            + (pendingOnly.checked ? '&pending_only=1' : '');
    fetch(url, {credentials: 'same-origin'})
      .then(function (r) {
        if (!r.ok) throw new Error('HTTP ' + r.status);
        return r.text();
      })
      .then(function (html) {
        modalBody.innerHTML = html;
      })
      .catch(function (err) {
        modalBody.innerHTML =
          '<div class="alert alert-danger mb-0">Failed to load details: ' +
          (err && err.message ? err.message : 'unknown error') + '</div>';
      });
  }

  // Pagination links are inside the swapped-in partial, so delegate
  // off the always-mounted modalBody. A click on any [data-page] anchor
  // re-fetches the partial at the requested page.
  modalBody.addEventListener('click', function (event) {
    var a = event.target.closest('.hotel-export-pagination [data-page]');
    if (!a) return;
    event.preventDefault();
    var li = a.closest('.page-item');
    if (li && li.classList.contains('disabled')) return;
    if (!currentHotelId) return;
    loadPage(currentHotelId, a.getAttribute('data-page'));
  });

  // The filter runs on the server, so it covers every page.
  pendingOnly.addEventListener('change', function () {
    if (currentHotelId) loadPage(currentHotelId, 1);
  });

  modalEl.addEventListener('show.bs.modal', function (event) {
    var trigger = event.relatedTarget;
    if (!trigger) return;
    var hotelId   = trigger.getAttribute('data-hotel-id');
    var hotelName = trigger.getAttribute('data-hotel-name') || 'Hotel Export Details';
    modalLabel.textContent = hotelName;
    currentHotelId = hotelId;

    // Wire up export download links + import target.
    csvBtn.href  = 'export_hotel_bookings_csv?hotel_id='  + encodeURIComponent(hotelId);
    xlsxBtn.href = 'export_hotel_bookings_xlsx?hotel_id=' + encodeURIComponent(hotelId);
    importHotelId.value = hotelId;
    importForm.style.display = 'none';

    loadPage(hotelId, 1);
  });
})();
