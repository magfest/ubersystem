// Waitlist reveal previews: who a send would reach, and what they would get.

(function () {
  function csrfToken() {
    var el = document.querySelector('input[name="csrf_token"]');
    return el ? el.value : '';
  }

  function modal() { return document.getElementById('hl-reveal-preview-modal'); }

  function show(title, bodyHtml) {
    var el = modal();
    el.querySelector('.modal-title').textContent = title;
    el.querySelector('.modal-body').innerHTML = bodyHtml;
    new bootstrap.Modal(el).show();
  }

  function escapeHtml(text) {
    var div = document.createElement('div');
    div.textContent = text === null || text === undefined ? '' : text;
    return div.innerHTML;
  }

  function post(url, id) {
    var body = new FormData();
    body.append('csrf_token', csrfToken());
    body.append('id', id);
    return fetch(url, {method: 'POST', body: body, credentials: 'same-origin'})
      .then(function (r) { return r.json(); });
  }

  function recipientsHtml(payload) {
    var rows = payload.sample.map(function (person) {
      return '<tr><td>' + escapeHtml(person.name) + '</td><td>' +
        escapeHtml(person.email) + '</td><td>' + escapeHtml(person.badge) +
        '</td></tr>';
    }).join('');

    return [
      '<div class="row g-2 mb-3">',
      '  <div class="col"><div class="border rounded p-2"><div class="small text-muted">Eligible now</div><strong>' + payload.eligible + '</strong></div></div>',
      '  <div class="col"><div class="border rounded p-2"><div class="small text-muted">Already emailed</div><strong>' + payload.already_emailed + '</strong></div></div>',
      '  <div class="col"><div class="border rounded p-2"><div class="small text-muted">Links awaiting send</div><strong>' + payload.awaiting_send + '</strong></div></div>',
      '  <div class="col"><div class="border rounded p-2"><div class="small text-muted">Would be emailed</div><strong>' + payload.would_email + '</strong></div></div>',
      '</div>',
      payload.would_email
        ? '<table class="table table-sm"><thead><tr><th>Name</th><th>Email</th><th>Badge</th></tr></thead><tbody>' +
          rows + '</tbody></table>' +
          (payload.truncated ? '<p class="form-text">Showing the first ' + payload.sample.length + '.</p>' : '')
        : '<p class="mb-0">Nobody would be emailed right now.</p>'
    ].join('');
  }

  function emailHtml(payload) {
    return [
      payload.leak_warning
        ? '<div class="alert alert-danger">This email template prints the destination URL, which would reveal it early. It has been masked here; fix the template before sending.</div>'
        : '',
      '<dl class="row">',
      '  <dt class="col-sm-2">To</dt><dd class="col-sm-10">' + escapeHtml(payload.recipient) + '</dd>',
      '  <dt class="col-sm-2">Subject</dt><dd class="col-sm-10">' + escapeHtml(payload.subject) + '</dd>',
      '</dl>',
      // Sandboxed so the email's own markup cannot restyle the admin page.
      '<iframe sandbox="" style="width:100%;height:24em;border:1px solid #dee2e6;border-radius:.25rem;"',
      '        srcdoc="' + escapeHtml(payload.body).replace(/"/g, '&quot;') + '"></iframe>'
    ].join('');
  }

  document.addEventListener('click', function (e) {
    var recipients = e.target.closest('.hl-reveal-recipients');
    if (recipients) {
      post('waitlist_reveal_recipients', recipients.dataset.id).then(function (payload) {
        if (payload.error) { show('Preview recipients', '<div class="alert alert-danger mb-0">' + escapeHtml(payload.error) + '</div>'); return; }
        show('Who would be emailed', recipientsHtml(payload));
      });
      return;
    }

    var email = e.target.closest('.hl-reveal-email');
    if (email) {
      post('preview_waitlist_reveal_email', email.dataset.id).then(function (payload) {
        if (payload.error) { show('Preview email', '<div class="alert alert-danger mb-0">' + escapeHtml(payload.error) + '</div>'); return; }
        show('Reveal email preview', emailHtml(payload));
      });
    }
  });
})();
