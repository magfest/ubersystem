// The shared-room request status images come from the external staff
// checklist system. If it is unreachable, replace the broken-image icon with
// a muted dash so an outage does not litter every row on the page.

(function () {
  // The error event does not bubble, so this has to listen in the capture
  // phase rather than delegating normally.
  document.addEventListener('error', function (e) {
    var img = e.target;
    if (!img || img.tagName !== 'IMG' || !img.classList.contains('tuber-status')) {
      return;
    }
    var placeholder = document.createElement('span');
    placeholder.className = 'text-muted';
    placeholder.title = 'Could not reach the staff checklist system.';
    placeholder.textContent = '-';
    img.replaceWith(placeholder);
  }, true);
})();
