// Secure-room wizard state machine (hotel_lottery/secure_room.html).
//
// The template provides its per-assignment values via a small config
// stanza BEFORE this script loads:
//
//   window.secureWizardConfig = {
//     assignmentId: ...,   // RoomAssignment id posted to every endpoint
//     cardToken: ...,      // seeded card state, '' when no card on file
//     cardLastFour: ...,
//     cardType: ...,
//     redirectUrl: ...     // where to send the user after securing
//   };
//
// goToStep() and submitWithExistingCard() are referenced by inline
// onclick= handlers in the template, so they stay top-level (global).
// Relies on the app-wide globals jQuery ($) and csrf_token.

var secureWizardConfig = window.secureWizardConfig || {};

var iframeUrl = null;       // Set lazily via AJAX
var vaultSessionLoading = false;
var vaultSessionReady = false;

// Card state - seeded from server if a card was already captured on this assignment.
var cardToken = secureWizardConfig.cardToken || null;
var cardLastFour = secureWizardConfig.cardLastFour || '';
var cardType = secureWizardConfig.cardType || '';
var vaultOrigin = null;  // Set when vault iframe URL is loaded

function loadVaultSession(callback) {
  if (iframeUrl) {
    if (callback) callback();
    return;
  }
  if (vaultSessionLoading) return;
  vaultSessionLoading = true;

  $('#vault-loading').show();
  $('#vault-iframe-container').hide();
  $('#secure-error').hide();

  $.ajax({
    url: 'create_vault_session',
    method: 'POST',
    data: { assignment_id: secureWizardConfig.assignmentId, csrf_token: csrf_token },
    success: function(json) {
      vaultSessionLoading = false;
      $('#vault-loading').hide();
      if (json.success) {
        iframeUrl = json.iframe_url;
        try { vaultOrigin = new URL(iframeUrl).origin; } catch(e) {}
        vaultSessionReady = true;
        document.getElementById('vault-iframe').src = iframeUrl;
        if (callback) callback();
      } else {
        $('#secure-error').text(json.error || 'Failed to load card form.').show();
      }
    },
    error: function() {
      vaultSessionLoading = false;
      $('#vault-loading').hide();
      $('#secure-error').text('Failed to connect to payment service. Please try again.').show();
    }
  });
}

function goToStep(step) {
  if (step === 3 && !isAddressComplete()) {
    $('#step2-error').text('Please fill in all required billing address fields.').show();
    return;
  }
  $('#step2-error').hide();

  // Hide all steps
  $('#step-1, #step-2, #step-3').hide();
  $('#step-' + step).show();

  // Update step badges
  for (var i = 1; i <= 3; i++) {
    var badge = document.getElementById('badge-' + i);
    badge.className = 'badge rounded-pill step-badge ' + (i === step ? 'bg-primary' : (i < step ? 'bg-success' : 'bg-secondary'));
  }

  if (step === 3) {
    if (hasCard()) {
      // Already has a card - show summary + secure button immediately
      updateCardDisplay();
    } else {
      // No card yet - create vault session and show iframe
      loadVaultSession(function() { updateCardDisplay(); });
    }
  }

  window.scrollTo({ top: 0, behavior: 'smooth' });
}

$(function() {
  $('input[name="date_choice"]').on('change', function() {
    $('#waitlist-dates').toggle(this.value === 'waitlist');
  });
});

function isAddressComplete() {
  return document.getElementById('address1').value.trim()
      && document.getElementById('city').value.trim()
      && document.getElementById('region').value.trim()
      && document.getElementById('zip_code').value.trim()
      && document.getElementById('country').value;
}

function hasCard() {
  return !!cardToken;
}

function cardSummaryText() {
  if (cardLastFour) {
    return (cardType ? cardType + ' ' : '') + 'ending in ' + cardLastFour;
  }
  return 'Credit card stored';
}

function updateCardDisplay() {
  var card = hasCard();
  var editing = $('#vault-iframe-container').data('showIframe');

  $('#card-summary, #vault-iframe-container, #secure-btn, #vault-loading').hide();

  if (card && !editing) {
    $('#card-summary-text').text(cardSummaryText());
    $('#card-summary').show();
    $('#secure-btn').show();
  } else if (vaultSessionReady) {
    $('#vault-iframe-container').show();
    if (card) {
      $('#card-summary-text').text(cardSummaryText());
      $('#card-summary').show();
    }
  }
}

$('#change-card-btn').on('click', function() {
  $('#vault-iframe-container').data('showIframe', true);
  // Reset so loadVaultSession creates a fresh capture endpoint
  iframeUrl = null;
  vaultSessionReady = false;
  loadVaultSession(function() {
    document.getElementById('vault-iframe').src = iframeUrl;
    updateCardDisplay();
  });
});

function submitWithExistingCard() {
  $('#secure-error').hide();
  $('#secure-btn').prop('disabled', true);

  $.ajax({
    url: 'secure_room_callback',
    method: 'POST',
    data: {
      assignment_id: secureWizardConfig.assignmentId,
      token: cardToken,
      address1: document.getElementById('address1').value.trim(),
      address2: document.getElementById('address2').value.trim(),
      city: document.getElementById('city').value.trim(),
      region: document.getElementById('region').value.trim(),
      zip_code: document.getElementById('zip_code').value.trim(),
      country: document.getElementById('country').value,
      hotel_rewards_number: document.getElementById('hotel_rewards_number').value.trim(),
      // Connector rooms render `date_choice` as a hidden input (no
      // radio / waitlist date pickers), so fall back to the plain
      // value and guard the optional date fields.
      date_choice: ($('input[name="date_choice"]:checked').val()
                    || $('input[name="date_choice"]').val() || 'accept'),
      requested_checkin: (document.getElementById('requested_checkin') || {}).value || '',
      requested_checkout: (document.getElementById('requested_checkout') || {}).value || '',
      csrf_token: csrf_token
    },
    success: function(response) {
      if (response.success) {
        $('#card-summary, #vault-iframe-container, #secure-btn, #step3-back-btn').hide();
        $('#secure-success').show();
        setTimeout(function() {
          window.location.href = secureWizardConfig.redirectUrl;
        }, 2000);
      } else {
        $('#secure-error').text(response.error || 'An error occurred.').show();
        $('#secure-btn').prop('disabled', false);
      }
    },
    error: function() {
      $('#secure-error').show();
      $('#secure-btn').prop('disabled', false);
    }
  });
}

window.addEventListener('message', function(event) {
  // Only accept messages from the vault iframe origin
  if (vaultOrigin && event.origin !== vaultOrigin) return;

  var data = event.data;
  if (!data || typeof data !== 'object') return;

  if (data.height) {
    document.getElementById('vault-iframe').style.height = data.height + 'px';
    return;
  }

  if (data.token) {
    cardToken = data.token;
    cardLastFour = '';
    cardType = '';
    $('#vault-iframe-container').data('showIframe', false);

    // Save just the token to the server (card metadata arrives via webhook)
    $.ajax({
      url: 'save_card_token',
      method: 'POST',
      data: {
        assignment_id: secureWizardConfig.assignmentId,
        token: cardToken,
        csrf_token: csrf_token
      },
      success: function(response) {
        if (!response.success) {
          $('#secure-error').text(response.error || 'Failed to save card token.').show();
        }
      },
      error: function() {
        $('#secure-error').text('Failed to save card token. Please try again.').show();
      }
    });

    updateCardDisplay();
  } else if (data.error) {
    $('#secure-error').text(data.error).show();
  }
});
