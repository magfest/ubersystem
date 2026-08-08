// Attendee-search autocomplete for the hotel section's admin pages.
//
// Markup comes from the `attendee_search_widget` macro in
// hotel_lottery_admin/_macros.html: a `.attendee-search-widget`
// container holding the hidden id input, the query input, the results
// dropdown, and the selected badge. Configuration is read from data-*
// attributes on the container:
//
//   data-search-url    - endpoint to fetch (returns a JSON list of
//                        {id, name, email, badge_num, badge_type})
//   data-extra-params  - OPTIONAL pre-encoded query-string fragment
//                        appended to every search (e.g.
//                        "partition_id=<uuid>")
(function () {
  function initWidget(widget) {
    var q       = widget.querySelector('.attendee-search-query');
    var results = widget.querySelector('.attendee-search-results');
    var hidden  = widget.querySelector('.attendee-search-id');
    var selBox  = widget.querySelector('.attendee-search-selected');
    var selName = widget.querySelector('.attendee-search-name');
    var clearBtn= widget.querySelector('.attendee-search-clear');
    if (!q) return;

    var searchUrl   = widget.getAttribute('data-search-url') || 'search_attendees';
    var extraParams = widget.getAttribute('data-extra-params') || '';

    var debounceTimer = null;
    var lastQuery = '';

    function clearSelection() {
      hidden.value = '';
      selBox.style.display = 'none';
      q.value = '';
      q.style.display = '';
      q.focus();
    }
    clearBtn.addEventListener('click', clearSelection);

    function chooseAttendee(item) {
      hidden.value = item.id;
      selName.textContent = item.name + (item.email ? ' (' + item.email + ')' : '');
      selBox.style.display = '';
      q.style.display = 'none';
      results.innerHTML = '';
      results.style.display = 'none';
    }

    function render(items) {
      if (!items || items.length === 0) {
        results.innerHTML = '<div class="list-group-item text-muted small">No matches</div>';
        results.style.display = 'block';
        return;
      }
      results.innerHTML = '';
      items.forEach(function (it) {
        var a = document.createElement('a');
        a.href = '#';
        a.className = 'list-group-item list-group-item-action';
        a.innerHTML = '<strong>' + escapeHtml(it.name) + '</strong>'
          + (it.email ? ' <span class="text-muted small">' + escapeHtml(it.email) + '</span>' : '')
          + (it.badge_num ? ' <span class="badge bg-light text-dark ms-1">Badge ' + escapeHtml(it.badge_num) + '</span>' : '')
          + (it.badge_type ? ' <span class="badge bg-light text-muted ms-1">' + escapeHtml(it.badge_type) + '</span>' : '');
        a.addEventListener('click', function (e) {
          e.preventDefault();
          chooseAttendee(it);
        });
        results.appendChild(a);
      });
      results.style.display = 'block';
    }

    function escapeHtml(s) {
      return String(s).replace(/[&<>"']/g, function (c) {
        return ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'})[c];
      });
    }

    function runSearch() {
      var term = q.value.trim();
      if (term === lastQuery) return;
      lastQuery = term;
      if (term.length < 2) {
        results.style.display = 'none';
        return;
      }
      var url = searchUrl + '?' + (extraParams ? extraParams + '&' : '')
              + 'q=' + encodeURIComponent(term);
      fetch(url, {credentials: 'same-origin'})
        .then(function (r) { return r.json(); })
        .then(function (data) { render(data || []); })
        .catch(function () { results.style.display = 'none'; });
    }

    q.addEventListener('input', function () {
      clearTimeout(debounceTimer);
      debounceTimer = setTimeout(runSearch, 250);
    });
    document.addEventListener('click', function (e) {
      if (e.target !== q && !results.contains(e.target)) {
        results.style.display = 'none';
      }
    });
  }

  document.querySelectorAll('.attendee-search-widget').forEach(initWidget);
})();
