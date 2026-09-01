// Delete dialog for hotel lottery resources.
//
// The row control is a real form posting to confirm_delete_resource, so the
// whole flow works without JavaScript. This intercepts it, asks the server
// what still points at the resource, and offers to resolve each conflict in
// place. Every resolution re-renders from the server's response, so the
// dialog is never acting on a stale picture; perform_delete re-checks again
// regardless.

(function () {
  var modalId = 'hl-delete-modal';
  var state = {kind: '', id: '', returnTo: ''};

  function csrfToken() {
    var el = document.querySelector('input[name="csrf_token"]');
    return el ? el.value : '';
  }

  function ensureModal() {
    var existing = document.getElementById(modalId);
    if (existing) { return existing; }
    var wrapper = document.createElement('div');
    wrapper.innerHTML = [
      '<div class="modal fade" id="' + modalId + '" tabindex="-1">',
      '  <div class="modal-dialog modal-lg modal-dialog-scrollable">',
      '    <div class="modal-content">',
      '      <div class="modal-header">',
      '        <h5 class="modal-title"></h5>',
      '        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>',
      '      </div>',
      '      <div class="modal-body"></div>',
      '      <div class="modal-footer justify-content-between">',
      '        <span class="text-success small hl-delete-message"></span>',
      '        <span class="d-flex gap-2">',
      '          <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancel</button>',
      '          <button type="button" class="btn btn-warning hl-delete-soft">Deactivate</button>',
      '          <button type="button" class="btn btn-danger hl-delete-hard">Delete permanently</button>',
      '        </span>',
      '      </div>',
      '    </div>',
      '  </div>',
      '</div>'
    ].join('');
    document.body.appendChild(wrapper.firstChild);
    return document.getElementById(modalId);
  }

  function post(url, data) {
    var body = new FormData();
    body.append('csrf_token', csrfToken());
    Object.keys(data).forEach(function (key) { body.append(key, data[key]); });
    return fetch(url, {method: 'POST', body: body, credentials: 'same-origin'})
      .then(function (r) { return r.json(); });
  }

  function render(payload) {
    var modal = ensureModal();
    if (payload.error) {
      modal.querySelector('.modal-body').innerHTML =
        '<div class="alert alert-danger mb-0"></div>';
      modal.querySelector('.alert').textContent = payload.error;
      return;
    }

    modal.querySelector('.modal-title').textContent =
      'Delete ' + payload.title + ': ' + payload.label;
    modal.querySelector('.modal-body').innerHTML = payload.html;
    modal.querySelector('.hl-delete-message').textContent = payload.message || '';

    var soft = modal.querySelector('.hl-delete-soft');
    soft.style.display = (payload.soft_delete_available && payload.is_active)
      ? '' : 'none';

    var hard = modal.querySelector('.hl-delete-hard');
    hard.disabled = Boolean(payload.has_blocking);
    hard.title = payload.has_blocking
      ? 'Resolve the items above first.' : '';
  }

  function refresh(extra) {
    return post('deletion_conflicts', {kind: state.kind, id: state.id})
      .then(function (payload) {
        if (extra && extra.message && !payload.error) {
          payload.message = extra.message;
        }
        render(payload);
        return payload;
      });
  }

  function submitDelete(mode) {
    var form = document.createElement('form');
    form.method = 'post';
    form.action = 'delete_resource';
    [['csrf_token', csrfToken()], ['kind', state.kind], ['id', state.id],
     ['mode', mode], ['return_to', state.returnTo],
     ['force', state.acknowledged ? '1' : '']].forEach(function (pair) {
      var input = document.createElement('input');
      input.type = 'hidden';
      input.name = pair[0];
      input.value = pair[1];
      form.appendChild(input);
    });
    document.body.appendChild(form);
    form.submit();
  }

  document.addEventListener('submit', function (e) {
    var form = e.target.closest('.hl-delete-form');
    if (!form) { return; }
    e.preventDefault();

    state.kind = form.dataset.kind;
    state.id = form.dataset.id;
    state.returnTo = form.dataset.returnTo || '';
    state.acknowledged = false;

    refresh().then(function (payload) {
      if (payload.error) { return; }
      new bootstrap.Modal(ensureModal()).show();
    });
  });

  document.addEventListener('click', function (e) {
    var modal = document.getElementById(modalId);
    if (!modal) { return; }

    var action = e.target.closest('.hl-conflict-action');
    if (action && modal.contains(action)) {
      var wrapper = action.closest('.hl-conflict-bulk');
      if (action.dataset.needsConfirm) {
        var check = wrapper.querySelector('.hl-conflict-confirm');
        if (check && !check.checked) {
          modal.querySelector('.hl-delete-message').textContent =
            'Tick the box first.';
          return;
        }
      }
      var select = wrapper.querySelector('.hl-conflict-target');
      action.disabled = true;
      post('resolve_deletion_conflict', {
        kind: state.kind, id: state.id,
        category: wrapper.dataset.category,
        action: action.dataset.action,
        target_id: select ? select.value : '',
      }).then(function (payload) {
        render(payload);
        // Acknowledging is a decision rather than a data change, so the
        // group stays; remember it so the delete carries the force flag.
        if (action.dataset.action === 'acknowledge') {
          state.acknowledged = true;
          var hard = document.getElementById(modalId).querySelector('.hl-delete-hard');
          hard.disabled = false;
        }
      });
      return;
    }

    if (e.target.closest('.hl-delete-soft')) { submitDelete('soft'); }
    if (e.target.closest('.hl-delete-hard')) { submitDelete('hard'); }
  });
})();
