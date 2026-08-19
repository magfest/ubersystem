(function () {
  // Copy-to-clipboard for the pending-invite codes. Delegated off the
  // page so it works for every row without per-row handlers; falls back
  // to a hidden-textarea + execCommand on browsers/contexts where the
  // async Clipboard API isn't available (e.g. non-HTTPS dev origins).
  function copyText(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      return navigator.clipboard.writeText(text);
    }
    return new Promise(function (resolve, reject) {
      try {
        var ta = document.createElement('textarea');
        ta.value = text;
        ta.style.position = 'fixed';
        ta.style.opacity = '0';
        document.body.appendChild(ta);
        ta.focus();
        ta.select();
        document.execCommand('copy');
        document.body.removeChild(ta);
        resolve();
      } catch (err) {
        reject(err);
      }
    });
  }

  document.addEventListener('click', function (e) {
    var btn = e.target.closest('.copy-invite-code');
    if (!btn) return;
    e.preventDefault();
    var code = btn.getAttribute('data-code') || '';
    copyText(code).then(function () {
      // Brief visual confirmation: swap the icon to a check, then revert.
      var icon = btn.querySelector('i');
      var prev = icon ? icon.className : null;
      if (icon) icon.className = 'fa fa-check text-success';
      btn.setAttribute('title', 'Copied!');
      setTimeout(function () {
        if (icon && prev !== null) icon.className = prev;
        btn.setAttribute('title', 'Copy invite code');
      }, 1200);
    });
  });
})();
